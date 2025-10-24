import json
import os
import requests

from datetime import date, datetime, timezone
from flask import Blueprint, current_app
import xml.etree.ElementTree as ET
from rapidfuzz import fuzz

from helpers import get_db, normalize_text
from dotenv import load_dotenv

load_dotenv()  # load variables from .env

# https://realpython.com/flask-blueprint/
# Define blueprint for fetchin news
news_bp = Blueprint("fetch_news", __name__)

FUZZY_LIMIT = 65  # Fuzzy matching threshold (0–100)
NEWSDATA_KEY = os.environ.get("NEWSDATA_KEY")


# News Data has char limit for queries
def batch_keywords(keywords: set, max_chars=100):
    """Split keywords into batches"""

    batch = []
    total_len = 0

    # Ensure query does not exceed char limit
    for word in keywords:

        word = word.strip()
        if not word:
            continue
        
        # Skip lengthy words
        if len(word) > max_chars:
            print(f"Keyword too long, skipped: {word}")
            continue

        # Count chars including spaces and operators
        added_len = len(word) + (len(" OR ") if batch else 0)

        # Word with added space exceeds limit
        if total_len + added_len > max_chars:
            # Yield current batch
            if batch:
                yield batch
            # Start new batch
            batch = [word]
            total_len = len(word)
            
        # Can append more words
        else:
            batch.append(word)
            total_len += added_len

    if batch:
        yield batch  # Out of keywords


def fetch_google_tech_news(batch):
    """Fetch latest news from Google News"""

    queries = " OR ".join(batch)
    url = f"https://news.google.com/rss/search?q={queries}+topic:TECHNOLOGY&hl=en-US&gl=US&ceid=US:en" 

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    # Print raw XML
    #print("===== RAW XML START =====")
    #print(response.text[:2000])  # print first 2k chars to avoid huge output
    #print("===== RAW XML END =====")

    articles = []
    #today = date.today()

    # Parse XML and extract details
    root = ET.fromstring(response.text)
    channel = root.find("channel")

    for item in channel.findall("item"):    
        # Filter by date
        pub_date_text = item.findtext("pubDate")
        if not pub_date_text:
            continue

        # Parse date, skip if fails
        try:
            # Read timezone info from %Z
            pub_date = datetime.strptime(pub_date_text, "%a, %d %b %Y %H:%M:%S %Z")
            # Replace with UTC and convert to local time
            pub_date = pub_date.replace(tzinfo=timezone.utc).astimezone()
        except ValueError:
            continue
        
        # Limit to current day articles
        #if pub_date.date() != today:
            #continue

        # Extract basic info
        id = item.findtext("guid", "")
        link = item.findtext("link", "")
        source = item.findtext("source", "Google News")
        title = item.findtext("title", "")
        desc = item.findtext("description", "")

        # Keyword matching
        keywords = set()
        clean_title = normalize_text(title or "")
        clean_desc = normalize_text(desc or "")
        text = " ".join([clean_title, clean_desc])

        for word in batch:
            if fuzz.partial_ratio(word, text) > FUZZY_LIMIT:
                keywords.add(word)  # Add keyword to set
        
        # Ensure required info exists
        if id and link and keywords:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "description": desc,
                "keywords": keywords
            })

    return articles


# max 10 articles per request for free tier
def fetch_from_newsdata(batch, max_results=10):
    """Fetch latest news from NewsData.io"""

    queries = " OR ".join(batch)
    url = "https://newsdata.io/api/1/latest"
    articles = []
 
    params = {
        "apikey": NEWSDATA_KEY,
        "q": queries,
        "category": "technology",
        "language": "en",
        "sort": "pubdateasc",
        "removeduplicate": 1,
    }     
    #print(f"🔍 Querying NewsData.io with: {queries}")
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()  
    data = response.json()       

    # Ensure the fetch is success
    if data.get("status") != "success":
        return []
    
    # Validate results
    results = data.get("results")
    if not results:
        print("⚠️ No results returned from NewsData.io — likely invalid query or daily limit reached.")
        print("Full response:", data)
        return []
    
    for r in results:
        # Extract basic info
        id = r.get("article_id")
        link = r.get("link")
        source = r.get("source_id")
        title = r.get("title")
        desc = r.get("description")

        # Normalize long texts
        keywords = set()
        clean_title = normalize_text(title or "")
        clean_desc = normalize_text(desc or "")

        # Normalize keywords from article if any
        keys = r.get("keywords") or []
        clean_keys = [normalize_text(str(k)) for k in keys if k]

        # Combine all text for fuzzy matching
        text = " ".join([clean_title, clean_desc] + clean_keys)

        # Match keywords
        for word in batch:
            if fuzz.partial_ratio(word, text) > FUZZY_LIMIT:
                keywords.add(word)

        # Ensure required info exists
        if id and link and keywords:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "description": desc,
                "keywords": keywords
            })

    return articles


def save_article(db, article_id, article_url, source, desc, keywords: set):
    """Insert unique articles and update relevant keywords"""

    existing = db.execute("SELECT keywords FROM articles WHERE id = ?", (article_id,)).fetchone()
    if existing:
        # Merge old and new keywords
        old_keywords = set(json.loads(existing["keywords"])) if existing["keywords"] else set()
        merged = list(old_keywords.union(keywords))
        # Update db
        db.execute("UPDATE articles SET keywords = ? WHERE id = ?", (json.dumps(merged), article_id))
    else:
        # Insert article into db
        db.execute("""
            INSERT OR IGNORE INTO articles (id, article_url, source, description, keywords)
            VALUES (?, ?, ?, ?)""",
            (article_id, article_url, source, desc, json.dumps(list(keywords))))


def fetch_tech_articles():
    """Fetch lastest tech news filtered by keywords"""

    db = get_db()

    rows = db.execute("SELECT keyword FROM preferences").fetchall()
    # Set stores unique only
    all_keywords = set()
    for row in rows:
        try:
            # Convert json string back to list and update set
            keywords_list = json.loads(row["keyword"])
            all_keywords.update(k for k in keywords_list if k)
        except (TypeError, json.JSONDecodeError):
            continue  # Move onto next list

    if all_keywords:
        for batch in batch_keywords(all_keywords):
            # Fetch from Google News or fallback to NewsData.io
            try:
                articles = fetch_google_tech_news(batch)
            except Exception as e:
                current_app.logger.warning(f"Google News fetch failed: {e}")
                try:
                    articles = fetch_from_newsdata(batch)
                except Exception as e:
                    current_app.logger.warning(f"NewsData.io fetch failed: {e}")
                    continue  # Move onto next batch
            
            # Ensure articles exist
            if not articles:
                continue 

            # Ensure no duplicate articles
            for a in articles:
                save_article(db, a["id"], a["article_url"], a["source"], a["description"], a["keywords"])

        db.commit()  # Ensure data is saved in between batches
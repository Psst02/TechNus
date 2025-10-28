import nltk
import json
import os
import requests
import xml.etree.ElementTree as ET

from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from flask import current_app
from newspaper import Article, Config

from dotenv import load_dotenv
from helpers import get_db, normalize_text, get_sematic_matches

load_dotenv()  # Always load first

FUZZY_LIMIT = 60  # Fuzzy matching threshold (0–100)
NEWSDATA_KEY = os.environ.get("NEWSDATA_KEY")

try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt')

config = Config()
config.browser_user_agent = os.environ.get("USER_AGENT")
 
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
            print(f"Batch full, starting new batch with: {word}")
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

# Limit the articles returned to keep it neat
def fetch_google_tech_news(batch, max_articles=10):
    """Fetch latest news from Google News"""

    queries = " OR ".join(batch)
    url = f"https://news.google.com/rss/search?q={queries}+topic:TECHNOLOGY&hl=en-US&gl=US&ceid=US:en" 

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    articles = []
    start_date = date.today() - timedelta(days=5)  # Last 5 days

    # Parse XML and extract details
    root = ET.fromstring(response.text)
    channel = root.find("channel")

    for item in channel.findall("item")[:max_articles]:    
        # Parse date, skip if fails
        pub_date_str = item.findtext("pubDate")
        try:
            pub_date = parsedate_to_datetime(pub_date_str).date()
        except ValueError:
            continue  # Can't filter by date
        
        # Skip if older than 5 days ago
        if pub_date < start_date:
            continue

        # Extract basic info
        id = item.findtext("guid", "")
        link = item.findtext("link", "")
        source = item.findtext("source", "Google News")
        title = item.findtext("title")

        # Resolve Google News redirect
        if "news.google.com/rss/articles/" in link:
            try:
                response = requests.get(link, allow_redirects=True, timeout=5)
                link = response.url  # This is the real article URL
            except Exception as e:
                print(f"Failed to resolve Google redirect: {link} -> {e}")
                continue

        # Keyword matching
        filtered = set()
        try:
            # Parse content inside url
            article = Article(link, config=config)
            article.download()
            article.parse()
            article.nlp()
            keywords = [normalize_text(str(k)) for k in article.keywords if k]

        except Exception as e:
            print(f"Failed to extract: {link} -> {e}")
            keywords = []  # Return empty list

        filtered.update(get_sematic_matches(batch, keywords))
        
        # Ensure required info exists
        if id and link and filtered and title:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "pub_date": pub_date,
                "keywords": filtered,
                "title": title
            })

    return articles


# max 10 articles per request for free tier
def fetch_from_newsdata(batch):
    """Fetch latest news from NewsData.io"""

    queries = " OR ".join(batch)
    url = "https://newsdata.io/api/1/latest"
    articles = []
    
    start_date = date.today() - timedelta(days=5)  # Last 5 days

    params = {
        "apikey": NEWSDATA_KEY,
        "q": queries,
        "category": "technology",
        "language": "en",
        "sort": "pubdateasc",
        "removeduplicate": 1,
    }     
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()  
    data = response.json()       

    # Ensure the fetch is success
    if data.get("status") != "success":
        return []
    
    # Validate results
    results = data.get("results")
    if not results:
        print("No results returned from NewsData.io")
        print("Full response:", data)
        return []
    
    for r in results:
        # Filter by date
        pub_date_str = r.get("pubDate")
        if not pub_date_str:
            continue
        try:
            # Remove time from published date
            pub_date = datetime.fromisoformat(pub_date_str).date()
        except ValueError:
            continue  # Can't filter by date

        # Skip if older than 5 days ago
        if pub_date < start_date:
            continue

        # Extract basic info
        id = r.get("article_id")
        link = r.get("link")
        source = r.get("source_id")
        title = r.get("title")

        # Normalize keywords from article if any
        keys = r.get("keywords") or []
        clean_keys = [normalize_text(str(k)) for k in keys if k]

        # Keyword matching
        filtered = set()
        try:
            # Parse content inside url
            article = Article(link, config=config)
            article.download()
            article.parse()
            article.nlp()
            keywords = [normalize_text(str(k)) for k in article.keywords if k]
        except Exception as e:
            print(f"Failed to extract: {link} -> {e}")
            keywords = []  # Return empty list

        all_keys = keywords + clean_keys  # Combine 2 lists
        filtered.update(get_sematic_matches(batch, all_keys))

        # Ensure required info exists
        if id and link and filtered and title:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "pub_date": pub_date,
                "keywords": filtered,
                "title": title
            })

    return articles


def save_article(db, article_id, article_url, source, date, keywords: set, title):
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
            INSERT OR IGNORE INTO articles (id, article_url, source, pub_date, keywords, title)
            VALUES (?, ?, ?, ?)""",
            (article_id, article_url, source, date, json.dumps(list(keywords))), title)


def fetch_tech_articles():
    """Fetch lastest tech news filtered by keywords"""

    db = get_db()

    rows = db.execute("SELECT keywords FROM preferences").fetchall()
    # Set stores unique only
    all_keywords = set()
    for row in rows:
        try:
            # Convert json string back to list and update set
            keywords_list = json.loads(row["keywords"])
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
                save_article(db, a["id"], a["article_url"], a["source"], a["pub_date"], a["keywords"], a["title"])

        db.commit()  # Ensure data is saved in between batches
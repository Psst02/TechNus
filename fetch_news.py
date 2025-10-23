import json
import os
import requests

from datetime import date, datetime, timezone
from itertools import islice
import xml.etree.ElementTree as ET

from flask import Blueprint, render_template, flash, current_app
from helpers import login_required, get_db

# https://realpython.com/flask-blueprint/
# Define blueprint for fetchin news
news_bp = Blueprint("fetch_news", __name__)


def batch_keywords(keywords, size=10):
    """Queue keywords into batches (default 10)"""

    # Convert to iterator
    iterator = iter(keywords)
    while True:
        batch = list(islice(iterator, size))
        # Exit when no more items left
        if not batch:
            break
        # Return each batch
        yield batch


def fetch_google_tech_news(batch):
    """Fetch latest news from Google News"""

    queries = " OR ".join(batch)
    url = f"https://news.google.com/rss/search?q={queries}+topic:TECHNOLOGY&hl=en-US&gl=US&ceid=US:en" 

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    articles = []
    today = date.today()

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
        if pub_date.date() != today:
            continue
        
        # Extract basic info
        id = item.findtext("guid", "")
        link = item.findtext("link", "")
        source = item.findtext("source", "Google News")
        title = item.findtext("title", "")
        desc = item.findtext("description", "")

        # Keyword matching (case-insensitive)
        text = " ".join([title, desc]).lower()
        keywords = {k for k in batch if k in text}
        
        # Ensure required info exists
        if id and link and keywords:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "keywords": keywords
            })

    return articles


# max 10 articles per request for free tier
def fetch_from_newsdata(batch, max_results=10):
    """Fetch latest news from NewsData.io"""

    queries = " OR ".join(batch)
    url = "https://newsdata.io/api/1/latest"
    NEWSDATA_KEY = os.getenv("NEWSDATA_KEY")

    today = date.today().isoformat()
    articles = []
    
    params = {
        "apikey": NEWSDATA_KEY,
        "q": queries,
        "language": "en",
        "sort": "relevancy",
        "from_date": today,
        "to_date": today,
        "removeduplicate": 1,
        "size": max_results,
    }     
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()  
    data = response.json()       

    # Ensure the fetch is success
    if data.get("status") != "success":
        return []

    # Validate results
    results = data.get("results", [])    
    for r in results:
        # Extract basic info
        id = r.get("article_id")
        article_url = r.get("link")
        source = r.get("source_id")
        title = r.get("title")
        desc = r.get("description")
        kw = r.get("keywords", [])

        # Match keywords
        text = " ".join([title, desc] + kw).lower()
        keywords = {k for k in batch if k in text}

        # Ensure required info exists
        if id and article_url and keywords:
            articles.append({
                "id": id,
                "article_url": article_url,
                "source": source,
                "keywords": keywords
            })
        
    return articles


def save_article(db, article_id, article_url, source, keywords):
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
        db.execute("""INSERT OR IGNORE INTO articles (id, article_url, source, keywords)
                      VALUES (?, ?, ?, ?)""",
                      (article_id, article_url, source, json.dumps(list(keywords))))


def fetch_tech_articles():
    """Fetch lastest tech news filtered by keywords"""

    db = get_db()
    rows = db.execute("SELECT keyword FROM preferences").fetchall()
    # Unique, case-insensitive
    all_keywords = {row["keyword"].lower() for row in rows}

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
                save_article(db, a["id"], a["article_url"], a["source"], a["keywords"])

        db.commit()  # Ensure data is saved in between batches
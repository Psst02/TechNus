import os
import requests
import sqlite3

from datetime import date, datetime
from itertools import islice
import xml.etree.ElementTree as ET

from flask import Blueprint, render_template, request, redirect, session, flash, current_app
from helpers import login_required, get_db

# https://realpython.com/flask-blueprint/
# Define blueprint for fetchin news
news_bp = Blueprint("news", __name__)

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GNEWS_KEY = os.getenv("GNEWS_KEY")


@news_bp.route("/")
@login_required
def dashboard():
    """Show dashboard"""

    return render_template("dashboard.html")


def batch_keywords(keywords, size=10):
    """Queue keywords into batches (default 10)"""

    if size > 0 and keywords:
        # Convert to iterator
        iterator = iter(keywords)
        while True:
            batch = list(islice(iterator, size))
            # Exit when no more items left
            if not batch:
                break
            # Return each batch
            yield batch


def fetch_google_tech_news(queries):
    """Fetch latest news from Google News"""

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
        pub_date = item.findtext("pubDate")
        if not pub_date:
            continue

        # Extract date, skip if fails
        try:
            pub_date = datetime.strptime(pub_date.replace(" GMT", ""), "%a, %d %b %Y %H:%M:%S")
        except ValueError:
            continue
        
        # Limit to current day articles
        if pub_date.date() != today:
            continue
        
        # Extract basic info
        id = item.findtext("guid") or ""
        link = item.findtext("link") or ""
        source = item.find("source").text or "Google News"

        # Manually extract keywords 
        title = item.findtext("title") or ""
        desc = item.findtext("description") or ""
        text = f"{title} {desc}".lower()
        # Unique, case-insensitive
        keywords = {q for q in queries if q in text}
        
        # Ensure required info exists
        if id and link and keywords:
            articles.append({
                "id": id,
                "article_url": link,
                "source": source,
                "keywords": list(keywords)
            })

    return articles


# max 10 articles per request for free tier
def fetch_from_newsdata(queries, max_results=10):
    """Fetch latest news from NewsData.io"""

    url = "https://newsdata.io/api/1/latest"
    NEWSDATA_KEY = os.getenv("NEWSDATA_KEY")

    today = date.today().isoformat()
    articles = []
    
    # Request up to 2 pages
    for page in range(1, 3):
        params = {
            "apikey": NEWSDATA_KEY,
            "q": queries,
            "language": "en",
            "sort": "relevancy",
            "from_date": today,
            "to_date": today,
            "removeduplicate": 1,
            "size": max_results,
            "page": page
        }     
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()  
        data = response.json()       

        # Ensure the fetch is success
        if data.get("status") != "success":
            return []
        # Validate results
        articles = data.get("results", [])
        
        return [
            {
                "id": a.get("article_id"),
                "article_url": a.get("link"),
                "source": a.get("source_id"),
                "keywords": list(a.get("keywords").values) if
            }
            for a in articles
        ]


def fetch_tech_articles():
    """Fetch lastest tech news filtered by keywords"""

    db = get_db()
    rows = db.execute("SELECT keyword FROM preferences").fetchall()
    # Unique, case-insensitive
    all_keywords = {row["keyword"].lower() for row in rows}

    if all_keywords:
        for batch in batch_keywords(all_keywords):
            queries = " OR ".join(batch)

        # Fetch from Google News or fallback to NewsData.io
        try:
            articles = fetch_google_tech_news(queries)
        except:
            articles = fetch_from_newsdata(queries)

        # Ensure no duplicate articles
        for a in articles:
            try:
                db.execute("""INSERT OR IGNORE INTO articles (id, article_url, source, keywords)
                              VALUES (?, ?, ?, ?)""",(a["id"], a["article_url"], a["source"], a["keywords"]))
            except sqlite3.Error:
                continue
    db.commit()
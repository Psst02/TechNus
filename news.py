import os
from datetime import date
import requests

from flask import Blueprint, render_template, request, redirect, session, flash, current_app
from helpers import login_required, get_db

# https://realpython.com/flask-blueprint/
# Define blueprint for fetchin news
news_bp = Blueprint("news", __name__)

NEWSDATA_KEY = os.getenv("NEWSDATA_KEY")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GNEWS_KEY = os.getenv("GNEWS_KEY")


@news_bp.route("/")
@login_required
def dashboard():
    """Show dashboard"""

    return render_template("dashboard.html")


# max 10 articles per request for free tier
def fetch_from_newsdata(max_results=10):
    """Get latest article url(s) from NewsData.io"""

    db = get_db()
    rows = db.execute("SELECT keyword FROM preferences").fetchall()
    all_keywords = {row["keyword"].lower() for row in rows}

    # Ensure keywords not empty
    if not all_keywords:
        return []    
    query = " OR ".join([k.strip() for k in all_keywords.split(",")])
    
    today = date.today()
    url = "https://newsdata.io/api/1/latest"
    params = {
        "apikey": NEWSDATA_KEY,
        "q": query,
        "language": "en",
        "sort": "relevancy",
        "from_date": today,
        "to_date": today,
        "removeduplicate": 1,
        "size": max_results,
        "page": 0
    }
    
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()  
    data = response.json()       

    # Ensure the fetch is success
    if data.get("status") != "success":
        return []
    # Validate results
    articles = data.get("results", [])
    
    # Return details for summarizer
    for a in articles:
        article_url = a.get("link")
        source = a.get("source_id")
        published_at = a.get("pubDate")

        keywords = a.get("keywords")
        db.execute("""INSERT INTO articles () 
                    VALUES (?, ?, ?, ?)""", article_url, source, published_at, keywords)
    db.commit()
    
import json
import os

from datetime import date, datetime, timedelta
from flask import Flask, flash, session, render_template, request, redirect, jsonify
from flask_session import Session
from helpers import login_required, get_db, db_teardown
from newspaper import Article
from typing import Literal

# Blueprints
from auth import auth_bp, oauth
from settings import settings_bp

from dotenv import load_dotenv
load_dotenv()  # Always load this first

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY")

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

oauth.init_app(app)  # Sets up Authlib OAuth with Flask
db_teardown(app)     # Register db teardown

# https://realpython.com/flask-blueprint/
# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(settings_bp)


# Disable data cache (Ensures fresh content)
@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/")
@login_required
def dashboard():
    """Show all/filtered articles in dashboard"""
    
    tab = request.args.get("tab", "all")

    # Validate tab
    if tab not in ["all", "new", "old"]:
        tab = "all"

    articles = get_articles(tab)  # Get relevant articles

    # Notify users of new articles if any
    newly_fetched = len(get_articles("new"))
    if newly_fetched > 0:
        flash(f"{newly_fetched} new articles available for you today!", "info")
        
    return render_template("dashboard.html", articles=articles, current_tab=tab)


@app.route("/extract-article")
@login_required
def extract_article():
    """Let summarizer call this function to extract article text content"""

    # Ensure article url exists
    url = request.args.get("url")
    if not url:
        return jsonify({"e": "Missing URL parameter"}), 400

    # Try parsing text from url
    try:
        article = Article(url)
        article.download()
        article.parse()
        article.nlp()

        # Extract clean text and validate
        text = article.text.strip()
        if not text:
            return jsonify({"e": "No article text found"}), 404

        return text, 200, {"Content-Type": "text/plain; charset=utf-8"}
    # Maybe broken link
    except Exception as e:
        print("Extraction failed:", e)  # For debugging
        return jsonify({"e": "Failed to fetch article text."}), 500
    

@app.route("/update-summary", methods=["POST"])
@login_required
def update_summary():
    """Update summarized content"""

    data = request.get_json()
    article_id = data.get("article_id")
    summary = data.get("summary")

    db = get_db()
    db.execute("UPDATE articles summary = ? WHERE id = ?", (summary, article_id))
    db.commit()
    return jsonify({"success": True})


@app.route("/delete-article/<int:id>")
@login_required
def delete_article(id):
    """Let user delete article"""

    db = get_db()
    db.execute("DELETE FROM articles WHERE id = ?", (id,))
    db.commit()
    flash("Article deleted.", "success")
    return redirect("/")


# Limit params to all, new, old
def get_articles(filter_mode: Literal["all", "new", "old"] = "all"):
    """Fetch and filter articles based on user's keywords and date."""

    db = get_db()
    filtered_articles = []

    # Ensure user has keyword preferences
    prefs = db.execute("SELECT keywords FROM preferences WHERE user_id = ?", (session["user_id"],)).fetchone()
    if not prefs:
        flash("Please set your preferences to get started.", "error")
        return redirect("/preferences")

    user_keywords = json.loads(prefs["keywords"])  # Get keywords string

    # Dynamic placeholders for keyword filter
    placeholders = " OR ".join(["keywords LIKE ?"] * len(user_keywords))
    params = [f"%{word}%" for word in user_keywords]

    # Date condition in query
    today_str = date.today().isoformat()
    date_condition = ""

    if filter_mode == "new":
        date_condition = "AND fetched_at = ?"  # Today
        params.append(today_str)

    elif filter_mode == "old":
        date_condition = "AND fetched_at < ?"  # Previous days
        params.append(today_str)

    # Execute query
    query = f"""
        SELECT id, article_url, source, pub_date, title, summary, fetched_at
        FROM articles
        WHERE ({placeholders}) {date_condition}
        ORDER BY fetched_at DESC
    """
    articles = db.execute(query, params).fetchall()

    # Format for front end
    for a in articles:
        
        # Expiry countdown
        fetched_date = datetime.fromisoformat(a["fetched_at"]).date()
        countdown = compute_expiry(fetched_date)

        filtered_articles.append({
            "id": a["id"],
            "url": a["article_url"],
            "source": a["source"],
            "expiry": countdown,
            "pub_date": a["pub_date"] or "-",
            "title": a["title"],
            "summary": a["summary"] or ""
        })

    return filtered_articles


def compute_expiry(fetched_at: date):
    """Get expiry countdown from fetch date"""

    # Expires in 5 days from fetch date
    expires_at = fetched_at + timedelta(days=5)
    countdown = (expires_at - date.today()).days
    return countdown




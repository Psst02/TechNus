import json
import os

from datetime import date
from flask import Flask, flash, session, render_template
from flask_session import Session
from helpers import login_required, get_db, db_teardown
from newspaper import Article

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
    """Show dashboard"""

    db = get_db()
    processed_articles = []

    # Get fetch_status
    status = db.execute("SELECT completed FROM fetch_status WHERE fetch_date = ?", (date.today(),)).fetchone()
    # Fetched but not processed
    if status and status["completed"] == 0:
        # Get user's keywords
        prefs = db.execute("SELECT keywords FROM preferences WHERE user_id = ?", (session["user_id"],)).fetchone()

        # Ensure user has set prefs
        if not prefs:
            flash("Please set your preferences first!", "error")
            return("/preferences")
        
        u_keywords = json.loads(prefs["keywords"])

        # Get article matches
        placeholders = " OR ".join(["keywords LIKE ?"] * len(u_keywords))
        params = [f"%{word}%" for word in u_keywords]
        articles = db.execute(f"SELECT * FROM articles WHERE {placeholders}", params).fetchall()

        for a in articles:
            try:
                # Parse content inside url
                article = Article(a["article_url"])
                article.download()
                article.parse()
                article.nlp()
                text = article.text
            except Exception as e:
                print(f"Failed to extract: {a["article_url"]} -> {e}")
                text = ""  # Return empty string
            
            # Get article details
            processed_articles.append({
                "url": a["article_url"],
                "pub_date": a["pub_date"],
                "source": a["source"],
                "content": text[:5000]  # Limit to 5000 chars
            })

        # Update status to processed
        db.execute("UPDATE fetch_status SET completed = 1 WHERE fetch_date = ?", (date.today(),))
        db.commit()

    return render_template("dashboard.html", articles=processed_articles)
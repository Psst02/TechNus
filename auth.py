import os
import sqlite3

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, render_template, request, redirect, session, flash, url_for
from helpers import get_db

# https://realpython.com/flask-blueprint/
# Define blueprint for all user auth routes
auth_bp = Blueprint("auth", __name__)

oauth = OAuth()

# https://www.geeksforgeeks.org/python/oauth-authentication-with-flask-connect-to-google-twitter-and-facebook/
# Create OAuth for Google
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

# Auto-fetch all the URLs (authorize, token, userinfo) using OpenID metadata
CONF_URL = 'https://accounts.google.com/.well-known/openid-configuration'
oauth.register(
    name='google',
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=CONF_URL,
    client_kwargs={'scope': 'openid email profile'}
)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Redirect user for authentication"""

    if request.method == "POST":

        redirect_uri = url_for('auth.callback', _external=True)
        return oauth.google.authorize_redirect(redirect_uri)
    
    return render_template("login.html")


@auth_bp.route("/login/oauth2callback")
def callback():
    """Handle call back and log user in"""

    # https://docs.authlib.org/en/latest/client/flask.html#authorization-code-grant
    # Exchange auth code for token
    token = oauth.google.authorize_access_token()

    # Get user info from Google
    user_info = token.get("userinfo")
    google_id = user_info.get("sub")
    name = user_info.get("preferred_username") or user_info.get("name")
    email = user_info.get("email") if user_info.get("email_verified") else None
    photo_url = user_info.get("picture")

    db = get_db()
    cur = db.cursor()
    # Store in db if new user
    cur.execute("SELECT id, photo_url FROM users WHERE google_id = ?", (google_id,))
    user = cur.fetchone()
    if user:
        user_id = user["id"]
        photo = user["photo_url"]
    else:
        try:
            cur.execute("""INSERT into users (google_id, name, email, photo_url) 
                           VALUES (?, ?, ?, ?)""", (google_id, name, email, photo_url))
            db.commit()
            user_id = cur.lastrowid
            photo = photo_url
            
        except sqlite3.IntegrityError:
            flash("Email not verified.", "error")
            return redirect("/login")
        
    session["user_id"] = user_id
    session["user_photo"] = photo

    flash("You're logged in!", "success")
    return redirect("/")


@auth_bp.route("/logout")
def logout():
    """Log user out"""

    session.clear()
    return redirect("/")


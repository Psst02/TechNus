import os

from flask import Flask, render_template
from flask_session import Session
from helpers import login_required, db_teardown

# Blueprints
from auth import auth_bp, oauth

app = Flask(__name__)

# Running locally
if os.environ.get("PYTHONANYWHERE_DOMAIN") is None:
    # Load local .env file
    # In PythonAnywhere, loaded from WSGI
    from dotenv import load_dotenv
    load_dotenv()
    
app.secret_key = os.environ.get("SECRET_KEY")
print("SECRET_KEY =", app.secret_key)

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

oauth.init_app(app)  # Sets up Authlib OAuth with Flask
db_teardown(app)     # Register db teardown

# Adapted from: Real Python
# URL: https://realpython.com/flask-blueprint/
# Register blueprints
app.register_blueprint(auth_bp)


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

    return render_template("dashboard.html")
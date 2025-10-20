import os
import sqlite3

from flask import redirect, session, g, current_app
from functools import wraps


def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/latest/patterns/viewdecorators/
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)

    return decorated_function


# https://flask.palletsprojects.com/en/latest/patterns/sqlite3/
def get_db():
    """Store db connection for current request in Flask's g"""

    # Creat connection if none
    if "db" not in g:
        db_path = os.path.join(current_app.root_path, "technus.db")
        g.db = sqlite3.connect(db_path)
        g.db.row_factory = sqlite3.Row  # Enable access via column names like CS50 SQL
    return g.db


def close_db(error=None):
    """Close the DB connection at the end"""

    # Remove db connection from g if any
    db = g.pop("db", None)
    # Close the connection if any (to free resources)
    if db is not None:
        db.close()


def db_teardown(app):
    """Register database teardown for the given Flask app."""

    app.teardown_appcontext(close_db)


def remove_photo(web_path, default_web_path):
    """Delete photo from file system if it's not default photo"""

    if web_path and web_path != default_web_path:
        # https://docs.python.org/3/library/os.path.html
        # Convert from web to file path
        file_path = os.path.join(current_app.root_path, web_path.lstrip("/"))
        file_path = os.path.normpath(file_path)

        # Validate path and ensure selected is a file before delete
        if os.path.exists(file_path) and os.path.isfile(file_path):
            os.remove(file_path)
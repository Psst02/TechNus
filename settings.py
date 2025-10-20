import json

from flask import Blueprint, render_template, request, redirect, session, flash, url_for
from helpers import login_required, get_db

# https://realpython.com/flask-blueprint/
# Define blueprint for all settings
settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/preferences", methods=["GET", "POST"])
@login_required
def preferences():
    """Let user set up keywords"""

    db = get_db()
    # Check if user already got preferences
    existing = db.execute("SELECT 1 FROM preferences WHERE user_id = ?", (session["user_id"],)).fetchone()
    has_existing = bool(existing)

    if request.method == "POST":
        # parse Tagify json string
        def parse_tagify(field_name):
            raw = request.form.get(field_name, '[]')
            try:
                # Converts to python dict and discard empty
                return [item["value"].strip() for item in json.loads(raw) if item.get("value", "").strip()]
            except json.JSONDecodeError:
                return []
            
        jobs = parse_tagify("jobs")
        industries = parse_tagify("industries")
        keywords = parse_tagify("keywords")

        fb1 = fb2 = fb3 = ""
        if not jobs:
            fb1 = "Required field"
        if not industries:
            fb2 = "Required field"
        if not keywords:
            fb3 = "Required field"

        # Ensure at least 1 input each
        if fb1 or fb2 or fb3:
            return render_template("preferences.html", fb1=fb1, fb2=fb2, fb3=fb3, has_existing=has_existing)   
        
        combined_keywords = jobs + industries + keywords
        # Delete if existing
        db.execute("DELETE FROM preferences WHERE user_id = ?", (session["user_id"],))
        # Add to preferences
        for word in combined_keywords:
            db.execute("INSERT INTO preferences (user_id, keyword) VALUES (?, ?)", (session["user_id"], word))
        db.commit()
        
        # Feedback on change and redirect
        flash("Preferences saved successfully!")
        return redirect("/preferences")

    return render_template("preferences.html", has_existing=has_existing)


@settings_bp.route("/delete-account", methods=["GET", "POST"])
@login_required
def delete_acc():
    """Let user delete account and related data"""

    if request.method == "POST":
        return
    return render_template("delete_acc.html")


@settings_bp.route("/profile", methods=["GET", "POST"])
@login_required
def manage_pf():
    """Let user edit profile"""
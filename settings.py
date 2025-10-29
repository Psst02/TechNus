import os
import json
import uuid

from werkzeug.utils import secure_filename
from helpers import login_required, get_db, normalize_text
from flask import Blueprint, render_template, request, redirect, session, flash, current_app

# https://realpython.com/flask-blueprint/
# Define blueprint for all settings
settings_bp = Blueprint("settings", __name__)


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


@settings_bp.route("/profile", methods=["GET", "POST"])
@login_required
def manage_pf():
    """Let user edit profile"""

    db = get_db()
    user_id = session["user_id"]

    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    d_web_path = "/static/default.jpg" # Default photo

    if request.method == "POST":
        # Remove photo (to default)
        if request.form.get("remove") == "1":
            # Store photo to be removed before changing to default
            r_web_path = user["photo_url"]
            db.execute("UPDATE users SET photo_url = ? WHERE id = ?", (d_web_path, user_id))
            db.commit()

            remove_photo(r_web_path, d_web_path)
            session["user_photo"] = d_web_path

            flash("Profile photo removed!", "success")
            return redirect("/profile")
        
        # Change photo (to upload)
        upload_file = request.files.get("upload")
        # Ensure file is chosen and named
        if upload_file and upload_file.filename:
            
            # https://docs.python.org/3/library/os.path.html
            # Ensure safe naming and get file path to save (hex in case of similar names)
            file_name = f"{uuid.uuid4().hex}_{secure_filename(upload_file.filename)}"
            file_path = os.path.join(current_app.root_path, "static", file_name)
            upload_file.save(file_path)

            # Create web path from file path
            u_web_path = "/" + os.path.relpath(file_path, current_app.root_path).replace(os.sep, "/")

            # Store photo to be removed before changing to default
            r_web_path = user["photo_url"]
            db.execute("UPDATE users SET photo_url = ? WHERE id = ?", (u_web_path, user_id))
            db.commit()

            remove_photo(r_web_path, d_web_path)
            session["user_photo"] = u_web_path

            flash("Profile photo updated!", "success")
            return redirect("/profile")
        
        name = (request.form.get("username") or user["name"]).strip()
        if not name:
            return render_template("profile.html", user=user, name_fb="required field")
        
        db.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
        db.commit()

        flash("Changes saved!", "success")
        return redirect("/profile")
    
    return render_template("profile.html", user=user)


@settings_bp.route("/preferences", methods=["GET", "POST"])
@login_required
def preferences():
    """Let user set up keywords"""

    db = get_db()

    # Initialize default prefs
    prefs = {"jobs": [], "industries": [], "keywords": []}

    # Fetch existing prefs if any
    rows = db.execute("""
        SELECT p.keywords, t.name
        FROM preferences p
        JOIN preference_types t ON p.type_id = t.id
        WHERE p.user_id = ?
    """, (session["user_id"],)).fetchall()

    # Load json lists (strings) from db
    for row in rows:
        prefs[row["name"]] = (json.loads(row["keywords"]) if row["keywords"] else []) or []

    # Map type names to id(s)
    type_map = {row["name"]: row["id"] for row in db.execute("SELECT * FROM preference_types")}
    # Check if user already set prefs
    has_existing = bool(rows)

    if request.method == "POST":
        # Parse tagify json string
        def parse_tagify(field_name):
            raw = request.form.get(field_name, '[]')
            try:
                # Discard empty and normalize valid words
                return [
                    normalize_text(item["value"])
                    for item in json.loads(raw) 
                    if item.get("value", "").strip()]
            
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
            return render_template(
                "preferences.html", 
                fb1=fb1, fb2=fb2, fb3=fb3, 
                has_existing=has_existing,
                prefs={key: json.dumps(values) for key, values in prefs.items()},  # Convert lists to strings
            )   
                
        # Overwrite preferences
        db.execute("DELETE FROM preferences WHERE user_id = ?", (session["user_id"],))

        # Insert JSON lists into relevant types
        for key, values in {"jobs": jobs, "industries": industries, "keywords": keywords}.items():
            db.execute(
                "INSERT INTO preferences (user_id, type_id, keywords) VALUES (?, ?, ?)",
                (session["user_id"], type_map[key], json.dumps(values)))
                
        db.commit()
        flash("Preferences saved successfully!")
        return redirect("/preferences")

    return render_template(
        "preferences.html", 
        has_existing=has_existing,
        prefs={key: json.dumps(values) for key, values in prefs.items()},  # Convert lists to strings
    )


@settings_bp.route("/delete-account", methods=["GET", "POST"])
@login_required
def delete_acc():
    """Let user delete account and related data"""

    db = get_db()

    if request.method == "POST":
        text = request.form.get("confirm-delete")
        if not text:
            return render_template("delete_acc.html", fb="Required field")
        
        # Ensure case insensitive
        text = text.lower().strip()
        if text != "confirm":
            return render_template("delete_acc.html", fb="Please confirm")
        
        if text == "confirm":       
            session.clear()
            # Delete from db
            db.execute("DELETE FROM users WHERE id = ?", (session["user_id"],))
        db.commit()

        flash("Account deleted.", "success")
        return redirect("/")
        
    return render_template("delete_acc.html")
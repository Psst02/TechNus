import json
import os
import uuid

from flask import Blueprint, render_template, request, redirect, session, flash, current_app
from helpers import login_required, get_db, remove_photo
from werkzeug.utils import secure_filename

# https://realpython.com/flask-blueprint/
# Define blueprint for all settings
settings_bp = Blueprint("settings", __name__)


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
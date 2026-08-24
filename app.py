import json
import os
import secrets
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCHEDULE_FILE = DATA_DIR / "schedule.json"
COACHES_FILE = DATA_DIR / "coaches.json"
GALLERY_FILE = DATA_DIR / "gallery.json"
HERO_FILE = DATA_DIR / "hero.json"

COACHES_UPLOAD_DIR = BASE_DIR / "static" / "images" / "coaches"
GALLERY_UPLOAD_DIR = BASE_DIR / "static" / "images" / "gallery"
VIDEOS_UPLOAD_DIR = BASE_DIR / "static" / "videos"
IMAGES_UPLOAD_DIR = BASE_DIR / "static" / "images"

ALLOWED_IMAGE_EXT = {"jpg", "jpeg", "png", "webp"}
ALLOWED_VIDEO_EXT = {"mp4"}

BADGE_CLASSES = {
    "free": "badge badge-free",
    "coach": "badge badge-coach",
    "offsite": "badge badge-offsite",
}

DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB per upload

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")


def load_json(path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_schedule():
    return load_json(SCHEDULE_FILE, [])


def save_schedule(rows):
    save_json(SCHEDULE_FILE, rows)


def load_coaches():
    return load_json(COACHES_FILE, [])


def save_coaches(rows):
    save_json(COACHES_FILE, rows)


def load_gallery():
    return load_json(GALLERY_FILE, [])


def save_gallery(rows):
    save_json(GALLERY_FILE, rows)


def load_hero():
    return load_json(HERO_FILE, {"video": "hero.mp4", "poster": "hero-poster.jpg"})


def save_hero(data):
    save_json(HERO_FILE, data)


def save_upload(file_storage, dest_dir, allowed_ext):
    """Validate + save an uploaded file, returning its stored filename."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in allowed_ext:
        return None
    filename = f"{secrets.token_hex(6)}_{secure_filename(file_storage.filename)}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_storage.save(dest_dir / filename)
    return filename


def group_schedule_by_day(rows):
    """group rows into one column per weekday"""
    by_day = {}
    for r in rows:
        row = dict(r)
        row["badge_class"] = BADGE_CLASSES.get((row.get("badge") or {}).get("type"))
        by_day.setdefault(row["day"], []).append(row)

    extra_days = [d for d in by_day if d not in DAY_ORDER]
    return [
        {"day": day, "classes": by_day.get(day, [])}
        for day in DAY_ORDER + extra_days
    ]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return render_template(
        "index.html",
        schedule_days=group_schedule_by_day(load_schedule()),
        coaches=load_coaches(),
        gallery=load_gallery(),
        hero=load_hero(),
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session["is_admin"] = True
            session["csrf_token"] = secrets.token_hex(16)
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        flash("Incorrect password.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/admin")
@login_required
def admin_dashboard():
    return render_template("admin_dashboard.html")


@app.route("/admin/schedule", methods=["GET", "POST"])
@login_required
def admin_schedule():
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("Session expired — please try again.")
            return redirect(url_for("admin_schedule"))

        days = request.form.getlist("day")
        times = request.form.getlist("time")
        classes = request.form.getlist("class_name")
        levels = request.form.getlist("level")
        badge_types = request.form.getlist("badge_type")
        badge_texts = request.form.getlist("badge_text")

        rows = []
        for day, time, cls, level, btype, btext in zip(
            days, times, classes, levels, badge_types, badge_texts
        ):
            if not day.strip() and not time.strip() and not cls.strip():
                continue
            rows.append(
                {
                    "day": day.strip(),
                    "time": time.strip(),
                    "class": cls.strip(),
                    "level": level.strip(),
                    "badge": (
                        {"type": btype, "text": btext.strip()}
                        if btype != "none" and btext.strip()
                        else None
                    ),
                }
            )
        save_schedule(rows)
        flash("Schedule updated.")
        return redirect(url_for("admin_schedule"))

    session.setdefault("csrf_token", secrets.token_hex(16))
    return render_template(
        "admin_schedule.html", schedule=load_schedule(), csrf_token=session["csrf_token"]
    )


@app.route("/admin/coaches", methods=["GET", "POST"])
@login_required
def admin_coaches():
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("Session expired — please try again.")
            return redirect(url_for("admin_coaches"))

        names = request.form.getlist("name")
        roles = request.form.getlist("role")
        belts = request.form.getlist("belt")
        bios = request.form.getlist("bio")
        existing_photos = request.form.getlist("existing_photo")
        photo_files = request.files.getlist("photo")

        rows = []
        for name, role, belt, bio, existing_photo, photo_file in zip(
            names, roles, belts, bios, existing_photos, photo_files
        ):
            if not name.strip():
                continue
            uploaded = save_upload(photo_file, COACHES_UPLOAD_DIR, ALLOWED_IMAGE_EXT)
            rows.append(
                {
                    "name": name.strip(),
                    "role": role.strip(),
                    "belt": belt.strip(),
                    "bio": bio.strip(),
                    "photo": uploaded or (existing_photo.strip() or None),
                }
            )
        save_coaches(rows)
        flash("Coaches updated.")
        return redirect(url_for("admin_coaches"))

    session.setdefault("csrf_token", secrets.token_hex(16))
    return render_template(
        "admin_coaches.html", coaches=load_coaches(), csrf_token=session["csrf_token"]
    )


@app.route("/admin/gallery", methods=["GET", "POST"])
@login_required
def admin_gallery():
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("Session expired — please try again.")
            return redirect(url_for("admin_gallery"))

        photo_file = request.files.get("photo")
        uploaded = save_upload(photo_file, GALLERY_UPLOAD_DIR, ALLOWED_IMAGE_EXT)
        if uploaded:
            rows = load_gallery()
            rows.append({"filename": uploaded, "caption": request.form.get("caption", "").strip()})
            save_gallery(rows)
            flash("Photo added.")
        else:
            flash("Choose a jpg, jpeg, png or webp file to upload.")
        return redirect(url_for("admin_gallery"))

    session.setdefault("csrf_token", secrets.token_hex(16))
    return render_template(
        "admin_gallery.html", gallery=load_gallery(), csrf_token=session["csrf_token"]
    )


@app.route("/admin/gallery/delete/<filename>", methods=["POST"])
@login_required
def admin_gallery_delete(filename):
    if request.form.get("csrf_token") != session.get("csrf_token"):
        flash("Session expired — please try again.")
        return redirect(url_for("admin_gallery"))

    rows = [r for r in load_gallery() if r["filename"] != filename]
    save_gallery(rows)
    photo_path = GALLERY_UPLOAD_DIR / secure_filename(filename)
    if photo_path.exists():
        photo_path.unlink()
    flash("Photo removed.")
    return redirect(url_for("admin_gallery"))


@app.route("/admin/hero", methods=["GET", "POST"])
@login_required
def admin_hero():
    if request.method == "POST":
        if request.form.get("csrf_token") != session.get("csrf_token"):
            flash("Session expired — please try again.")
            return redirect(url_for("admin_hero"))

        hero = load_hero()
        video_file = request.files.get("video")
        poster_file = request.files.get("poster")

        uploaded_video = save_upload(video_file, VIDEOS_UPLOAD_DIR, ALLOWED_VIDEO_EXT)
        if uploaded_video:
            hero["video"] = uploaded_video

        uploaded_poster = save_upload(poster_file, IMAGES_UPLOAD_DIR, ALLOWED_IMAGE_EXT)
        if uploaded_poster:
            hero["poster"] = uploaded_poster

        if uploaded_video or uploaded_poster:
            save_hero(hero)
            flash("Hero video updated.")
        else:
            flash("Choose an mp4 video and/or a jpg/png/webp poster to upload.")
        return redirect(url_for("admin_hero"))

    session.setdefault("csrf_token", secrets.token_hex(16))
    return render_template("admin_hero.html", hero=load_hero(), csrf_token=session["csrf_token"])


if __name__ == "__main__":
    app.run(debug=True)

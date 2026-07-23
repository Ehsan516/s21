import json
import os
import secrets
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

BASE_DIR = Path(__file__).resolve().parent
SCHEDULE_FILE = BASE_DIR / "data" / "schedule.json"

BADGE_CLASSES = {
    "free": "tag-free",
    "coach": "coach-tag",
    "offsite": "off-site",
}

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH")


def load_schedule():
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_schedule(rows):
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
        f.write("\n")


def with_rowspans(rows):
    """Annotate each row with day_rowspan so consecutive same-day rows
    can share a single <td rowspan> cell in the template."""
    grouped = []
    i, n = 0, len(rows)
    while i < n:
        day = rows[i]["day"]
        j = i
        while j < n and rows[j]["day"] == day:
            j += 1
        span = j - i
        for k in range(i, j):
            row = dict(rows[k])
            row["day_rowspan"] = span if k == i else 0
            row["badge_class"] = BADGE_CLASSES.get((row.get("badge") or {}).get("type"))
            grouped.append(row)
        i = j
    return grouped


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@app.route("/")
def index():
    return render_template("index.html", schedule=with_rowspans(load_schedule()))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session.clear()
            session["is_admin"] = True
            session["csrf_token"] = secrets.token_hex(16)
            return redirect(request.args.get("next") or url_for("admin_schedule"))
        flash("Incorrect password.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


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


if __name__ == "__main__":
    app.run(debug=True)

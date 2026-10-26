"""Landing page, role-based home redirect, notifications, profile and
protected file downloads."""
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from . import services as svc
from .config import CATEGORIES, PRIORITIES, PRIORITY_HELP, PRIORITY_SLA_HOURS, ROLE_LABELS
from .db import execute, query_one, transaction
from .security import current_user, login_required
from .utils import fmt_datetime
from .validators import validate_password, validate_profile

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user():
        return redirect(url_for("main.home"))
    resolved = query_one("SELECT COUNT(*) AS n FROM requests WHERE status = 'Resolved'")["n"]
    targets = [
        {"priority": p, "help": PRIORITY_HELP[p], "hours": PRIORITY_SLA_HOURS[p]}
        for p in reversed(PRIORITIES)
    ]
    return render_template("index.html", categories=CATEGORIES, targets=targets, resolved=resolved)


@bp.route("/home")
@login_required
def home():
    user = current_user()
    if user["role"] == "admin":
        return redirect(url_for("admin.overview"))
    if user["role"] == "technician":
        return redirect(url_for("tickets.assigned"))
    dashboard = svc.user_dashboard(user["id"])
    return render_template("dashboard.html", dashboard=dashboard)


# ----------------------------------------------------------------- notifications
@bp.route("/notifications")
@login_required
def notifications():
    user = current_user()
    return render_template("notifications.html", items=svc.latest_notifications(user["id"]))


@bp.route("/notifications/read", methods=["POST"])
@login_required
def mark_read():
    execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (current_user()["id"],))
    flash("All notifications marked as read.", "success")
    return redirect(url_for("main.notifications"))


# ------------------------------------------------------------------------ profile
@bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = current_user()
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "department", "phone")}
        errors = validate_profile(form)
        if errors:
            for message in errors:
                flash(message, "error")
        else:
            execute(
                "UPDATE users SET name = ?, department = ?, phone = ? WHERE id = ?",
                (form["name"], form["department"], form["phone"], user["id"]),
            )
            flash("Profile updated.", "success")
            return redirect(url_for("main.profile"))
    mine = svc.status_counts(owner_id=user["id"])
    return render_template("profile.html", role_label=ROLE_LABELS[user["role"]],
                           total_requests=sum(mine.values()), joined=fmt_datetime(user["created_at"]))


@bp.route("/profile/password", methods=["POST"])
@login_required
def change_password():
    user = current_user()
    current = request.form.get("current", "")
    new = request.form.get("new", "")
    confirm = request.form.get("confirm", "")
    problem = validate_password(new)
    if not check_password_hash(user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif problem:
        flash(problem, "error")
    elif new != confirm:
        flash("The new passwords do not match.", "error")
    else:
        execute("UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(new), user["id"]))
        flash("Password changed.", "success")
    return redirect(url_for("main.profile"))


# ------------------------------------------------------------------------ uploads
@bp.route("/uploads/<path:filename>")
@login_required
def uploads(filename):
    """Serve a request photo only to people allowed to see that request."""
    req = query_one("SELECT * FROM requests WHERE attachment = ?", (filename,))
    if req is None or not svc.can_view(current_user(), req):
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)

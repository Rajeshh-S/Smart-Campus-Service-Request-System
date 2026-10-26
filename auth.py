"""Registration, sign-in and sign-out."""
import sqlite3

from flask import (Blueprint, current_app, flash, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, query_one
from .security import current_user
from .utils import is_safe_redirect, now_str
from .validators import validate_registration

bp = Blueprint("auth", __name__)

# Verified against when the email is unknown so response time doesn't reveal
# which addresses are registered.
_DUMMY_HASH = generate_password_hash("not-a-real-password")


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user():
        return redirect(url_for("main.home"))
    form = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("name", "email", "department", "phone")}
        form["email"] = form["email"].lower()
        password = request.form.get("password", "")
        errors = validate_registration(form, password, request.form.get("confirm", ""))
        if not errors:
            try:
                execute(
                    "INSERT INTO users (name, email, password_hash, role, department, phone, created_at)"
                    " VALUES (?, ?, ?, 'user', ?, ?, ?)",
                    (form["name"], form["email"], generate_password_hash(password),
                     form["department"], form["phone"], now_str()),
                )
            except sqlite3.IntegrityError:
                errors.append("That email is already registered. Try signing in instead.")
            else:
                flash("Account created. Sign in to raise your first request.", "success")
                return redirect(url_for("auth.login"))
        for message in errors:
            flash(message, "error")
    return render_template("auth/register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user():
        return redirect(url_for("main.home"))
    next_url = request.values.get("next", "")
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        throttle = current_app.extensions["throttle"]
        key = f"{request.remote_addr}|{email}"
        if throttle.blocked(key):
            flash(f"Too many failed attempts. Try again in {throttle.retry_minutes(key)} minute(s).", "error")
        else:
            user = query_one("SELECT * FROM users WHERE email = ?", (email,))
            valid = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password)
            if user and valid and user["is_active"]:
                throttle.reset(key)
                session.clear()
                session["user_id"] = user["id"]
                session.permanent = True
                execute("UPDATE users SET last_login = ? WHERE id = ?", (now_str(), user["id"]))
                return redirect(next_url if is_safe_redirect(next_url) else url_for("main.home"))
            throttle.fail(key)
            if user and valid and not user["is_active"]:
                flash("This account has been disabled. Contact the campus administrator.", "error")
            else:
                flash("Email or password is incorrect.", "error")
    return render_template("auth/login.html", next_url=next_url)


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.index"))

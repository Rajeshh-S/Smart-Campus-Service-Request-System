"""Authentication helpers, CSRF protection, login throttling and HTTP headers."""
import secrets
import time
from collections import defaultdict, deque
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

from .db import query_one


# ------------------------------------------------------------------------ CSRF
def csrf_token():
    """Return (and lazily create) the per-session CSRF token."""
    token = session.get("_csrf")
    if not token:
        token = secrets.token_hex(16)
        session["_csrf"] = token
    return token


def verify_csrf():
    """Reject any state-changing request that lacks the session's token."""
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf") or ""
    if not expected or not secrets.compare_digest(sent.encode(), expected.encode()):
        abort(400, "Your form expired. Go back, refresh the page and try again.")


# ----------------------------------------------------------------- current user
def current_user():
    """Load the signed-in user once per request (None for guests)."""
    if "user" in g:
        return g.user
    user = None
    uid = session.get("user_id")
    if uid:
        user = query_one("SELECT * FROM users WHERE id = ? AND is_active = 1", (uid,))
        if user is None:
            session.pop("user_id", None)
    g.user = user
    return user


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Please sign in to continue.", "info")
            target = None
            if request.method == "GET":
                target = request.full_path.rstrip("?")
            return redirect(url_for("auth.login", next=target))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    """Allow only users whose role is in `roles` (403 for everyone else)."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if current_user()["role"] not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


# --------------------------------------------------------------- login throttle
class LoginThrottle:
    """Tiny in-memory brute-force guard: N failures per key within a window."""

    def __init__(self, limit=5, window=600):
        self.limit = limit
        self.window = window
        self._hits = defaultdict(deque)

    def _recent(self, key):
        hits = self._hits[key]
        cutoff = time.time() - self.window
        while hits and hits[0] < cutoff:
            hits.popleft()
        return hits

    def blocked(self, key):
        return len(self._recent(key)) >= self.limit

    def fail(self, key):
        self._recent(key).append(time.time())

    def reset(self, key):
        self._hits.pop(key, None)

    def retry_minutes(self, key):
        hits = self._recent(key)
        if not hits:
            return 0
        wait = self.window - (time.time() - hits[0])
        return max(1, int(wait // 60) + 1)


# ---------------------------------------------------------------------- headers
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if "user_id" in session and request.endpoint != "static":
        response.headers["Cache-Control"] = "no-store"
    return response


def init_app(app):
    app.extensions["throttle"] = LoginThrottle(
        app.config["LOGIN_MAX_ATTEMPTS"], app.config["LOGIN_WINDOW_SECONDS"]
    )
    app.before_request(verify_csrf)
    app.after_request(add_security_headers)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["current_user"] = current_user

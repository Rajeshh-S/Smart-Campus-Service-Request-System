"""Small JSON API used by the dashboard charts and the notification badge."""
from functools import wraps

from flask import Blueprint, jsonify

from . import services as svc
from .security import current_user

bp = Blueprint("api", __name__, url_prefix="/api")


def api_auth(*roles):
    """Like login_required/roles_required, but answers with JSON errors."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = current_user()
            if user is None:
                return jsonify(error="Sign in required."), 401
            if roles and user["role"] not in roles:
                return jsonify(error="Not allowed."), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator


@bp.route("/admin/stats")
@api_auth("admin")
def admin_stats():
    return jsonify(svc.admin_stats())


@bp.route("/notifications/unread")
@api_auth()
def unread():
    return jsonify(count=svc.unread_count(current_user()["id"]))

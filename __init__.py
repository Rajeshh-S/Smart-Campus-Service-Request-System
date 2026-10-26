"""Smart Campus Service Request System.

Author: Rajesh S (GitHub: Rajeshh-S)

A Flask + SQLite web application where students and staff report campus
problems and technicians / administrators track them to resolution.
"""
import os

from flask import Flask, render_template, session

from . import db, security, services
from .config import (CATEGORIES, CATEGORY_ICONS, PRIORITIES, PRIORITY_HELP,
                     PRIORITY_SLA_HOURS, ROLE_LABELS, STATUSES, Config, load_secret_key)
from .icons import icon
from .utils import (fmt_date, fmt_datetime, hours_label, initials, time_ago)

__version__ = "2.0.0"


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = load_secret_key()
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    security.init_app(app)
    _register_template_helpers(app)
    _register_blueprints(app)
    _register_error_pages(app)

    with app.app_context():
        db.init_db()
    return app


def _register_blueprints(app):
    from . import admin, api, auth, main, tickets

    for module in (main, auth, tickets, admin, api):
        app.register_blueprint(module.bp)


def _register_template_helpers(app):
    env = app.jinja_env
    env.filters.update(
        ticket=services.ticket_code,
        ago=time_ago,
        dt=fmt_datetime,
        date=fmt_date,
        initials=initials,
        hours=hours_label,
    )
    env.globals.update(
        icon=icon,
        sla_info=services.sla_info,
        category_icon=lambda name: CATEGORY_ICONS.get(name, "dots"),
    )

    @app.context_processor
    def inject_globals():
        user = security.current_user() if "user_id" in session else None
        return {
            "me": user,
            "unread": services.unread_count(user["id"]) if user else 0,
            "CATEGORIES": CATEGORIES,
            "PRIORITIES": PRIORITIES,
            "PRIORITY_HELP": PRIORITY_HELP,
            "PRIORITY_SLA_HOURS": PRIORITY_SLA_HOURS,
            "STATUSES": STATUSES,
            "ROLE_LABELS": ROLE_LABELS,
            "app_version": __version__,
        }


def _register_error_pages(app):
    messages = {
        400: ("That request didn't look right.", "Go back, refresh the page and try again."),
        403: ("You don't have access to this page.", "Ask an administrator if you think that's a mistake."),
        404: ("We couldn't find that page.", "The link may be old, or the request may not be yours."),
        405: ("That action isn't allowed here.", "Use the buttons on the page instead."),
        413: ("That file is too large.", "Photos can be up to 5 MB."),
        500: ("Something went wrong on our side.", "Please try again in a moment."),
    }

    def handler(error):
        code = getattr(error, "code", 500) or 500
        title, hint = messages.get(code, messages[500])
        detail = getattr(error, "description", "") if code == 400 else ""
        return render_template("error.html", code=code, title=title, hint=detail or hint), code

    for code in messages:
        app.register_error_handler(code, handler)

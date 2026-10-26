"""Server-side validation for every form. Each function returns a list of
human-readable error strings (empty list = valid)."""
import re

from flask import current_app

from .config import BUILDINGS, CATEGORY_NAMES, PRIORITIES

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+\-\s()]{7,20}$")


def validate_password(password):
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must include at least one letter and one number."
    return None


def validate_email(email):
    if not EMAIL_RE.match(email) or len(email) > 120:
        return "Enter a valid email address."
    domains = current_app.config.get("ALLOWED_EMAIL_DOMAINS") or []
    if domains and email.rsplit("@", 1)[-1] not in domains:
        return "Use your campus email address (" + ", ".join("@" + d for d in domains) + ")."
    return None


def _optional_phone(phone):
    if phone and not PHONE_RE.match(phone):
        return "Enter a valid phone number or leave it blank."
    return None


def validate_registration(form, password, confirm):
    errors = []
    if not 2 <= len(form["name"]) <= 80:
        errors.append("Enter your full name (2 to 80 characters).")
    for problem in (validate_email(form["email"]), _optional_phone(form["phone"])):
        if problem:
            errors.append(problem)
    if len(form["department"]) > 80:
        errors.append("Department is too long (80 characters maximum).")
    problem = validate_password(password)
    if problem:
        errors.append(problem)
    elif password != confirm:
        errors.append("The two passwords do not match.")
    return errors


def validate_ticket(form):
    errors = []
    if not 4 <= len(form["title"]) <= 100:
        errors.append("Give the request a short title (4 to 100 characters).")
    if form["category"] not in CATEGORY_NAMES:
        errors.append("Choose what kind of problem it is.")
    if form["building"] not in BUILDINGS:
        errors.append("Choose the building or area.")
    if len(form["room"]) > 40:
        errors.append("Room or spot is too long (40 characters maximum).")
    if form["priority"] not in PRIORITIES:
        errors.append("Choose a priority.")
    if not 10 <= len(form["description"]) <= 2000:
        errors.append("Describe the problem in 10 to 2000 characters.")
    return errors


def validate_profile(form):
    errors = []
    if not 2 <= len(form["name"]) <= 80:
        errors.append("Enter your full name (2 to 80 characters).")
    if len(form["department"]) > 80:
        errors.append("Department is too long (80 characters maximum).")
    problem = _optional_phone(form["phone"])
    if problem:
        errors.append(problem)
    return errors


def validate_comment(text):
    if len(text) < 2:
        return "Write a message before sending."
    if len(text) > 1000:
        return "Messages can be up to 1000 characters."
    return None

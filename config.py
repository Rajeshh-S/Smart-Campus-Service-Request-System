"""Configuration and domain constants for the Smart Campus Service Request System.

Everything a campus would want to tweak (categories, buildings, response
targets, upload limits, default admin) lives here so the rest of the code
never hard-codes it.
"""
import os
import secrets
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------
CATEGORIES = [
    {"name": "Electrical", "icon": "bolt", "hint": "Lights, fans, sockets, power cuts"},
    {"name": "Plumbing", "icon": "drop", "hint": "Leaks, taps, drainage, water supply"},
    {"name": "Wi-Fi / Network", "icon": "wifi", "hint": "No signal, slow speed, LAN ports"},
    {"name": "Classroom / Lab", "icon": "monitor", "hint": "Projectors, PCs, benches, boards"},
    {"name": "Cleaning", "icon": "trash", "hint": "Washrooms, corridors, waste bins"},
    {"name": "Hostel", "icon": "home", "hint": "Rooms, mess, laundry, furniture"},
    {"name": "Transport", "icon": "bus", "hint": "Bus routes, delays, vehicle issues"},
    {"name": "Library", "icon": "book", "hint": "Seating, books, reading rooms"},
    {"name": "Security", "icon": "shield", "hint": "Gates, CCTV, lost and found"},
    {"name": "Other", "icon": "dots", "hint": "Anything not listed above"},
]
CATEGORY_NAMES = [c["name"] for c in CATEGORIES]
CATEGORY_ICONS = {c["name"]: c["icon"] for c in CATEGORIES}

BUILDINGS = [
    "Main Block",
    "Science Block",
    "Engineering Block",
    "Library",
    "Auditorium",
    "Cafeteria",
    "Boys Hostel",
    "Girls Hostel",
    "Sports Complex",
    "Parking and Gates",
    "Other",
]

PRIORITIES = ["Low", "Medium", "High", "Urgent"]
PRIORITY_SLA_HOURS = {"Urgent": 4, "High": 24, "Medium": 72, "Low": 168}
PRIORITY_HELP = {
    "Urgent": "Safety risk or a complete outage",
    "High": "Blocks classes, work or daily life",
    "Medium": "Needs fixing, but there is a workaround",
    "Low": "Minor or cosmetic",
}

STATUSES = ["Pending", "In Progress", "Resolved", "Rejected", "Cancelled"]
OPEN_STATUSES = ("Pending", "In Progress")
CLOSED_STATUSES = ("Resolved", "Rejected", "Cancelled")
TECHNICIAN_STATUSES = ("In Progress", "Resolved")

ROLES = ["user", "technician", "admin"]
ROLE_LABELS = {
    "user": "Student / Staff",
    "technician": "Technician",
    "admin": "Administrator",
}

# Every "kind" of entry that can appear in a request timeline.
EVENT_KINDS = ("created", "status", "assign", "priority", "comment", "note", "feedback")


def load_secret_key():
    """Return the session signing key.

    Uses the SECRET_KEY environment variable when set, otherwise generates a
    random key once and stores it in `.secret_key` (which is git-ignored).
    """
    key = os.environ.get("SECRET_KEY")
    if key:
        return key
    path = os.path.join(BASE_DIR, ".secret_key")
    try:
        with open(path, encoding="utf-8") as handle:
            saved = handle.read().strip()
            if saved:
                return saved
    except FileNotFoundError:
        pass
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(key)
    return key


def _domains(raw):
    return [d.strip().lower().lstrip("@") for d in raw.split(",") if d.strip()]


class Config:
    """Default settings. Override any of them with environment variables."""

    SECRET_KEY = os.environ.get("SECRET_KEY")
    DATABASE = os.environ.get("DATABASE", os.path.join(BASE_DIR, "smartcampus.db"))
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(BASE_DIR, "uploads"))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB per upload
    ALLOWED_IMAGE_TYPES = {"png", "jpg", "jpeg", "gif", "webp"}

    PER_PAGE = 10
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 600

    # Comma separated list, e.g. "college.edu,students.college.edu". Empty = anyone.
    ALLOWED_EMAIL_DOMAINS = _domains(os.environ.get("ALLOWED_EMAIL_DOMAINS", ""))

    ADMIN_NAME = os.environ.get("ADMIN_NAME", "Campus Admin")
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@campus.local").strip().lower()
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE") == "1"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)

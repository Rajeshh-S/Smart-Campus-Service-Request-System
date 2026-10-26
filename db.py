"""SQLite connection handling, schema and first-run bootstrap."""
import sqlite3
from contextlib import contextmanager

from flask import current_app, g
from werkzeug.security import generate_password_hash

from .utils import now_str

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user'
                  CHECK (role IN ('user', 'technician', 'admin')),
    department    TEXT,
    phone         TEXT,
    specialty     TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    assignee_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title       TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    building    TEXT    NOT NULL,
    room        TEXT,
    priority    TEXT    NOT NULL DEFAULT 'Medium',
    description TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'Pending',
    attachment  TEXT,
    due_at      TEXT    NOT NULL,
    rating      INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback    TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id  INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    kind        TEXT    NOT NULL,
    message     TEXT    NOT NULL,
    is_internal INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message    TEXT    NOT NULL,
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_user     ON requests(user_id);
CREATE INDEX IF NOT EXISTS idx_requests_assignee ON requests(assignee_id);
CREATE INDEX IF NOT EXISTS idx_requests_status   ON requests(status);
CREATE INDEX IF NOT EXISTS idx_events_request    ON events(request_id);
CREATE INDEX IF NOT EXISTS idx_notif_user        ON notifications(user_id, is_read);
"""


# ------------------------------------------------------------------ connection
def get_db():
    """Return the SQLite connection for the current request."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DATABASE"])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def execute(sql, params=()):
    """Run a single write statement, commit it and return the new row id."""
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor.lastrowid


@contextmanager
def transaction():
    """Group several writes into one atomic commit."""
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


# ------------------------------------------------------------------- bootstrap
def init_db():
    """Create tables on first run and make sure an administrator exists."""
    path = current_app.config["DATABASE"]
    conn = sqlite3.connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            conn.executescript(SCHEMA)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        elif version != SCHEMA_VERSION:
            raise RuntimeError(
                f"{path} uses database schema v{version} but this version of the "
                f"app needs v{SCHEMA_VERSION}. Delete the file to start fresh."
            )
        _ensure_admin(conn)
    finally:
        conn.close()


def _ensure_admin(conn):
    if conn.execute("SELECT 1 FROM users WHERE role = 'admin' LIMIT 1").fetchone():
        return
    cfg = current_app.config
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role, department, created_at)"
        " VALUES (?, ?, ?, 'admin', 'Administration', ?)",
        (
            cfg["ADMIN_NAME"],
            cfg["ADMIN_EMAIL"],
            generate_password_hash(cfg["ADMIN_PASSWORD"]),
            now_str(),
        ),
    )
    conn.commit()
    if not cfg.get("TESTING"):
        print(f"[setup] Default admin created: {cfg['ADMIN_EMAIL']} / {cfg['ADMIN_PASSWORD']}")
        print("[setup] Change this password from the Profile page after signing in.")


def init_app(app):
    app.teardown_appcontext(close_db)

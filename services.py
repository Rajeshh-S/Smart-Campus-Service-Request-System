"""Business logic shared by the blueprints: SLA rules, audit trail,
notifications, searching/filtering requests and the admin analytics."""
import math
import re
from datetime import timedelta

from .config import (CATEGORY_NAMES, CLOSED_STATUSES, OPEN_STATUSES, PRIORITIES,
                     PRIORITY_SLA_HOURS, STATUSES)
from .db import query_all, query_one
from .utils import (Page, humanize_seconds, like_escape, now, now_str, parse_ts,
                    TS_FORMAT)


# ------------------------------------------------------------------ identifiers
def ticket_code(number):
    """1 -> 'SC-0001'."""
    return f"SC-{int(number):04d}"


# ------------------------------------------------------------------------- SLA
def sla_due(priority, start=None):
    """Deadline for a request of `priority` created at `start` (default: now)."""
    start = start or now()
    hours = PRIORITY_SLA_HOURS.get(priority, PRIORITY_SLA_HOURS["Medium"])
    return (start + timedelta(hours=hours)).strftime(TS_FORMAT)


def sla_info(row):
    """Describe a request's response-target state.

    Returns {'state': ok|soon|overdue|done|late|closed, 'label': str}.
    """
    status = row["status"]
    due = parse_ts(row["due_at"])
    if status == "Resolved":
        finished = parse_ts(row["resolved_at"])
        if finished and due and finished > due:
            return {"state": "late", "label": "Resolved late"}
        return {"state": "done", "label": "Resolved on time"}
    if status in CLOSED_STATUSES:
        return {"state": "closed", "label": "Closed"}
    if due is None:
        return {"state": "ok", "label": "No target"}
    remaining = (due - now()).total_seconds()
    if remaining < 0:
        return {"state": "overdue", "label": f"Overdue by {humanize_seconds(remaining)}"}
    created = parse_ts(row["created_at"])
    window = (due - created).total_seconds() if created else 0
    state = "soon" if window and remaining < window * 0.25 else "ok"
    return {"state": state, "label": f"Due in {humanize_seconds(remaining)}"}


# ------------------------------------------------------------ audit trail / inbox
def log_event(db, request_id, user_id, kind, message, internal=False, created_at=None):
    db.execute(
        "INSERT INTO events (request_id, user_id, kind, message, is_internal, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, user_id, kind, message, 1 if internal else 0, created_at or now_str()),
    )


def notify(db, user_id, message, link=None):
    db.execute(
        "INSERT INTO notifications (user_id, message, link, created_at) VALUES (?, ?, ?, ?)",
        (user_id, message, link, now_str()),
    )


def notify_admins(db, message, link=None, exclude=None):
    for row in db.execute("SELECT id FROM users WHERE role = 'admin' AND is_active = 1"):
        if row["id"] != exclude:
            notify(db, row["id"], message, link)


def notify_parties(db, req, actor_id, message, link, include_admins=False):
    """Tell the requester and the assignee (never the person who acted)."""
    targets = {req["user_id"], req["assignee_id"]} - {None, actor_id}
    for uid in targets:
        notify(db, uid, message, link)
    if include_admins:
        notify_admins(db, message, link, exclude=actor_id)


def unread_count(user_id):
    return query_one(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
    )["n"]


def latest_notifications(user_id, limit=50):
    return query_all(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)
    )


# ------------------------------------------------------------------- permissions
def is_staff(user):
    return user["role"] in ("admin", "technician")


def can_view(user, req):
    if user["role"] == "admin" or req["user_id"] == user["id"]:
        return True
    return user["role"] == "technician" and req["assignee_id"] == user["id"]


# ----------------------------------------------------------------- single lookups
def get_request(req_id):
    return query_one(
        "SELECT r.*, u.name AS requester, u.email AS requester_email,"
        " u.department AS requester_dept, u.phone AS requester_phone,"
        " t.name AS assignee_name, t.specialty AS assignee_specialty"
        " FROM requests r JOIN users u ON u.id = r.user_id"
        " LEFT JOIN users t ON t.id = r.assignee_id WHERE r.id = ?",
        (req_id,),
    )


def get_events(request_id, include_internal):
    sql = (
        "SELECT e.*, u.name AS actor, u.role AS actor_role FROM events e"
        " LEFT JOIN users u ON u.id = e.user_id WHERE e.request_id = ?"
    )
    if not include_internal:
        sql += " AND e.is_internal = 0"
    return query_all(sql + " ORDER BY e.id ASC", (request_id,))


def technician_options():
    return query_all(
        "SELECT id, name, specialty FROM users"
        " WHERE role = 'technician' AND is_active = 1 ORDER BY name"
    )


# ---------------------------------------------------------- searching / filtering
_PRIORITY_ORDER = "CASE r.priority WHEN 'Urgent' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END"
SORTS = {
    "newest": "r.id DESC",
    "oldest": "r.id ASC",
    "priority": f"{_PRIORITY_ORDER}, r.id DESC",
    "due": "r.due_at ASC",
    "triage": (
        "CASE WHEN r.status IN ('Pending', 'In Progress') THEN 0 ELSE 1 END, "
        f"{_PRIORITY_ORDER}, r.due_at ASC"
    ),
}
SORT_LABELS = {
    "newest": "Newest first",
    "oldest": "Oldest first",
    "priority": "Highest priority",
    "due": "Nearest deadline",
    "triage": "Needs attention first",
}

_FROM = (
    "FROM requests r JOIN users u ON u.id = r.user_id"
    " LEFT JOIN users t ON t.id = r.assignee_id"
)
_CODE_RE = re.compile(r"(?:sc-?)?0*(\d{1,9})")


def parse_filters(args):
    """Whitelist and normalise the query-string filters of a list page."""
    status = args.get("status", "")
    category = args.get("category", "")
    priority = args.get("priority", "")
    assignee = args.get("assignee", "")
    sort = args.get("sort", "")
    valid_assignee = assignee == "none" or (assignee.isascii() and assignee.isdigit())
    return {
        "q": args.get("q", "").strip()[:80],
        "status": status if status in STATUSES else "",
        "category": category if category in CATEGORY_NAMES else "",
        "priority": priority if priority in PRIORITIES else "",
        "assignee": assignee if valid_assignee else "",
        "sort": sort if sort in SORTS else "",
        "overdue": args.get("overdue") == "1",
    }


def _where(filters, owner_id, assignee_id):
    clauses, params = [], []
    if owner_id is not None:
        clauses.append("r.user_id = ?")
        params.append(owner_id)
    if assignee_id is not None:
        clauses.append("r.assignee_id = ?")
        params.append(assignee_id)
    for column in ("status", "category", "priority"):
        if filters[column]:
            clauses.append(f"r.{column} = ?")
            params.append(filters[column])
    if filters["assignee"] == "none":
        clauses.append("r.assignee_id IS NULL")
    elif filters["assignee"]:
        clauses.append("r.assignee_id = ?")
        params.append(int(filters["assignee"]))
    if filters["overdue"]:
        clauses.append("r.status IN ('Pending', 'In Progress') AND r.due_at < ?")
        params.append(now_str())
    q = filters["q"]
    if q:
        like = f"%{like_escape(q)}%"
        parts = [f"{col} LIKE ? ESCAPE '\\'" for col in ("r.title", "r.building", "r.room", "u.name")]
        params.extend([like] * len(parts))
        code = _CODE_RE.fullmatch(q.lower())
        if code:
            parts.append("r.id = ?")
            params.append(int(code.group(1)))
        clauses.append("(" + " OR ".join(parts) + ")")
    return (" AND ".join(clauses) or "1 = 1"), params


def search_requests(filters, *, owner_id=None, assignee_id=None, page=1, per_page=10,
                    default_sort="newest", paginate=True):
    """Filtered, sorted (and optionally paginated) list of requests."""
    where, params = _where(filters, owner_id, assignee_id)
    total = query_one(f"SELECT COUNT(*) AS n {_FROM} WHERE {where}", params)["n"]
    order = SORTS[filters["sort"] or default_sort]
    select = (
        "SELECT r.*, u.name AS requester, u.email AS requester_email,"
        " u.department AS requester_dept, t.name AS assignee_name "
        f"{_FROM} WHERE {where} ORDER BY {order}"
    )
    if not paginate:
        return Page(query_all(select, params), 1, max(total, 1), total)
    pages = max(1, math.ceil(total / per_page))
    page = min(page, pages)
    rows = query_all(select + " LIMIT ? OFFSET ?", params + [per_page, (page - 1) * per_page])
    return Page(rows, page, per_page, total)


def status_counts(owner_id=None, assignee_id=None):
    counts = {status: 0 for status in STATUSES}
    clause, params = "1 = 1", []
    if owner_id is not None:
        clause, params = "user_id = ?", [owner_id]
    elif assignee_id is not None:
        clause, params = "assignee_id = ?", [assignee_id]
    for row in query_all(
        f"SELECT status, COUNT(*) AS n FROM requests WHERE {clause} GROUP BY status", params
    ):
        counts[row["status"]] = row["n"]
    return counts


def user_dashboard(user_id, limit=6):
    """Return compact, actionable data for the signed-in user's dashboard."""
    counts = status_counts(owner_id=user_id)
    recent = query_all(
        "SELECT r.*, t.name AS assignee_name FROM requests r "
        "LEFT JOIN users t ON t.id = r.assignee_id "
        "WHERE r.user_id = ? ORDER BY r.id DESC LIMIT ?",
        (user_id, limit),
    )
    overdue = query_one(
        "SELECT COUNT(*) AS n FROM requests "
        "WHERE user_id = ? AND status IN ('Pending', 'In Progress') AND due_at < ?",
        (user_id, now_str()),
    )["n"]
    awaiting_feedback = query_one(
        "SELECT COUNT(*) AS n FROM requests "
        "WHERE user_id = ? AND status = 'Resolved' AND rating IS NULL",
        (user_id,),
    )["n"]
    return {
        "counts": counts,
        "recent": recent,
        "overdue": overdue,
        "awaiting_feedback": awaiting_feedback,
        "total": sum(counts.values()),
    }


# ------------------------------------------------------------------- analytics
def admin_stats(days=14):
    """Everything the admin overview page and charts need, as plain data."""
    counts = status_counts()
    total = sum(counts.values())
    open_now = counts["Pending"] + counts["In Progress"]
    overdue = query_one(
        "SELECT COUNT(*) AS n FROM requests"
        " WHERE status IN ('Pending', 'In Progress') AND due_at < ?",
        (now_str(),),
    )["n"]
    resolution = query_one(
        "SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) AS avg_hours,"
        " COUNT(*) AS n, COALESCE(SUM(resolved_at <= due_at), 0) AS on_time"
        " FROM requests WHERE status = 'Resolved' AND resolved_at IS NOT NULL"
    )
    rating = query_one(
        "SELECT AVG(rating) AS avg, COUNT(rating) AS n FROM requests WHERE rating IS NOT NULL"
    )

    today = now().date()
    day_list = [today - timedelta(days=i) for i in range(days - 1, -1, -1)]
    start = day_list[0].isoformat()
    created = {
        r["d"]: r["n"]
        for r in query_all(
            "SELECT date(created_at) AS d, COUNT(*) AS n FROM requests"
            " WHERE date(created_at) >= ? GROUP BY d",
            (start,),
        )
    }
    resolved = {
        r["d"]: r["n"]
        for r in query_all(
            "SELECT date(resolved_at) AS d, COUNT(*) AS n FROM requests"
            " WHERE resolved_at IS NOT NULL AND date(resolved_at) >= ? GROUP BY d",
            (start,),
        )
    }
    categories = [
        {"label": r["category"], "value": r["n"]}
        for r in query_all(
            "SELECT category, COUNT(*) AS n FROM requests GROUP BY category ORDER BY n DESC, category"
        )
    ]
    avg_hours = resolution["avg_hours"]
    return {
        "kpis": {
            "total": total,
            "open": open_now,
            "overdue": overdue,
            "resolved": counts["Resolved"],
            "avg_resolution_label": humanize_seconds(avg_hours * 3600) if avg_hours else None,
            "on_time_pct": round(100 * resolution["on_time"] / resolution["n"]) if resolution["n"] else None,
            "avg_rating": round(rating["avg"], 1) if rating["avg"] is not None else None,
            "rating_count": rating["n"],
        },
        "trend": {
            "labels": [d.strftime("%d %b") for d in day_list],
            "created": [created.get(d.isoformat(), 0) for d in day_list],
            "resolved": [resolved.get(d.isoformat(), 0) for d in day_list],
        },
        "statuses": [{"label": s, "value": counts[s]} for s in STATUSES],
        "categories": categories,
    }


def attention_list(limit=6):
    """Open requests that are overdue or urgent, most pressing first."""
    return query_all(
        "SELECT r.*, u.name AS requester, t.name AS assignee_name " + _FROM +
        " WHERE r.status IN ('Pending', 'In Progress') AND (r.due_at < ? OR r.priority = 'Urgent')"
        " ORDER BY r.due_at ASC LIMIT ?",
        (now_str(), limit),
    )


def category_report():
    rows = query_all(
        "SELECT category, COUNT(*) AS total,"
        " COALESCE(SUM(status = 'Resolved'), 0) AS resolved,"
        " COALESCE(SUM(status IN ('Pending', 'In Progress')), 0) AS open,"
        " COALESCE(SUM(status IN ('Pending', 'In Progress') AND due_at < ?), 0) AS overdue,"
        " AVG(CASE WHEN status = 'Resolved' AND resolved_at IS NOT NULL"
        "     THEN (julianday(resolved_at) - julianday(created_at)) * 24 END) AS avg_hours,"
        " AVG(rating) AS avg_rating"
        " FROM requests GROUP BY category ORDER BY total DESC, category",
        (now_str(),),
    )
    return [
        {
            **dict(r),
            "avg_time": humanize_seconds(r["avg_hours"] * 3600) if r["avg_hours"] else None,
            "avg_rating": round(r["avg_rating"], 1) if r["avg_rating"] is not None else None,
        }
        for r in rows
    ]


def priority_report():
    found = {
        r["priority"]: r
        for r in query_all(
            "SELECT priority, COUNT(*) AS total,"
            " COALESCE(SUM(status = 'Resolved'), 0) AS resolved,"
            " COALESCE(SUM(status = 'Resolved' AND resolved_at <= due_at), 0) AS on_time"
            " FROM requests GROUP BY priority"
        )
    }
    report = []
    for name in reversed(PRIORITIES):
        row = found.get(name)
        total, resolved, on_time = (row["total"], row["resolved"], row["on_time"]) if row else (0, 0, 0)
        report.append({
            "priority": name,
            "total": total,
            "resolved": resolved,
            "on_time": on_time,
            "on_time_pct": round(100 * on_time / resolved) if resolved else None,
        })
    return report


def technician_report():
    rows = query_all(
        "SELECT u.id, u.name, u.specialty,"
        " COALESCE(SUM(r.status IN ('Pending', 'In Progress')), 0) AS open,"
        " COALESCE(SUM(r.status = 'Resolved'), 0) AS resolved,"
        " AVG(CASE WHEN r.status = 'Resolved' AND r.resolved_at IS NOT NULL"
        "     THEN (julianday(r.resolved_at) - julianday(r.created_at)) * 24 END) AS avg_hours,"
        " AVG(r.rating) AS avg_rating"
        " FROM users u LEFT JOIN requests r ON r.assignee_id = u.id"
        " WHERE u.role = 'technician' AND u.is_active = 1"
        " GROUP BY u.id ORDER BY open DESC, u.name"
    )
    return [
        {
            **dict(r),
            "avg_time": humanize_seconds(r["avg_hours"] * 3600) if r["avg_hours"] else None,
            "avg_rating": round(r["avg_rating"], 1) if r["avg_rating"] is not None else None,
        }
        for r in rows
    ]


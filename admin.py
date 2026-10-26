"""Administrator tools: overview dashboard, triage list, CSV export,
user management and reports."""
import csv
import io

from flask import (Blueprint, Response, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from . import services as svc
from .config import CATEGORY_NAMES, ROLE_LABELS, ROLES
from .db import execute, query_all, query_one
from .security import current_user, roles_required
from .utils import Page, clamp_page, csv_safe, is_safe_redirect, like_escape, now

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("")
@roles_required("admin")
def overview():
    return render_template(
        "admin/overview.html",
        stats=svc.admin_stats(),
        attention=svc.attention_list(),
        technicians=svc.technician_report(),
    )


@bp.route("/requests")
@roles_required("admin")
def requests_list():
    filters = svc.parse_filters(request.args)
    page = svc.search_requests(
        filters,
        page=clamp_page(request.args.get("page")),
        per_page=current_app.config["PER_PAGE"],
        default_sort="triage",
    )
    return render_template(
        "admin/requests.html",
        page=page,
        filters=filters,
        args={k: v for k, v in request.args.items() if k != "page"},
        technicians=svc.technician_options(),
        sort_labels=svc.SORT_LABELS,
    )


@bp.route("/requests/export.csv")
@roles_required("admin")
def export_csv():
    filters = svc.parse_filters(request.args)
    rows = svc.search_requests(filters, default_sort="triage", paginate=False)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Ticket", "Title", "Category", "Building", "Room", "Priority", "Status",
        "Requester", "Requester email", "Assigned to", "Created", "Due", "Resolved", "Rating",
    ])
    for r in rows:
        writer.writerow([csv_safe(v) for v in (
            svc.ticket_code(r["id"]), r["title"], r["category"], r["building"], r["room"] or "",
            r["priority"], r["status"], r["requester"], r["requester_email"],
            r["assignee_name"] or "", r["created_at"], r["due_at"], r["resolved_at"] or "",
            r["rating"] if r["rating"] is not None else "",
        )])
    stamp = now().strftime("%Y%m%d-%H%M")
    return Response(
        "\ufeff" + out.getvalue(),  # BOM so Excel opens UTF-8 correctly
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=smart-campus-requests-{stamp}.csv"},
    )


# ------------------------------------------------------------------------- users
@bp.route("/users")
@roles_required("admin")
def users():
    q = request.args.get("q", "").strip()[:80]
    role = request.args.get("role", "")
    role = role if role in ROLES else ""
    clauses, params = [], []
    if q:
        like = f"%{like_escape(q)}%"
        clauses.append("(name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\' OR department LIKE ? ESCAPE '\\')")
        params += [like, like, like]
    if role:
        clauses.append("role = ?")
        params.append(role)
    where = " AND ".join(clauses) or "1 = 1"
    per_page = 15
    total = query_one(f"SELECT COUNT(*) AS n FROM users WHERE {where}", params)["n"]
    probe = Page([], 1, per_page, total)
    page_no = min(clamp_page(request.args.get("page")), probe.pages)
    rows = query_all(
        "SELECT u.*, (SELECT COUNT(*) FROM requests r WHERE r.user_id = u.id) AS raised,"
        " (SELECT COUNT(*) FROM requests r WHERE r.assignee_id = u.id"
        "  AND r.status IN ('Pending', 'In Progress')) AS open_assigned"
        f" FROM users u WHERE {where} ORDER BY u.role, u.name LIMIT ? OFFSET ?",
        params + [per_page, (page_no - 1) * per_page],
    )
    return render_template(
        "admin/users.html",
        page=Page(rows, page_no, per_page, total),
        q=q,
        role=role,
        args={k: v for k, v in request.args.items() if k != "page"},
        roles=ROLES,
        role_labels=ROLE_LABELS,
        categories=CATEGORY_NAMES,
    )


@bp.route("/users/<int:user_id>/update", methods=["POST"])
@roles_required("admin")
def update_user(user_id):
    me = current_user()
    target = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if target is None:
        abort(404)
    role = request.form.get("role", target["role"])
    specialty = request.form.get("specialty", "")
    active = 1 if request.form.get("active") == "1" else 0
    if role not in ROLES:
        abort(400, "Unknown role.")
    if specialty not in CATEGORY_NAMES:
        specialty = ""
    if target["id"] == me["id"] and (role != "admin" or not active):
        flash("You can't remove your own administrator access.", "error")
    else:
        execute(
            "UPDATE users SET role = ?, specialty = ?, is_active = ? WHERE id = ?",
            (role, specialty or None, active, user_id),
        )
        flash(f"Updated {target['name']}.", "success")
    back = request.form.get("next", "")
    return redirect(back if is_safe_redirect(back) else url_for("admin.users"))


# ----------------------------------------------------------------------- reports
@bp.route("/reports")
@roles_required("admin")
def reports():
    return render_template(
        "admin/reports.html",
        by_category=svc.category_report(),
        by_priority=svc.priority_report(),
        by_technician=svc.technician_report(),
        stats=svc.admin_stats(),
    )

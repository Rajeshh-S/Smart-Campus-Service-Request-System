"""Service requests as seen by the people who raise them and the staff who
work on them: create, browse, discuss, update, cancel and rate."""
import os
import uuid

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from . import services as svc
from .config import BUILDINGS, PRIORITIES, STATUSES, TECHNICIAN_STATUSES
from .db import query_one, transaction
from .security import current_user, login_required, roles_required
from .utils import clamp_page, now, now_str, parse_ts, sniff_image
from .validators import validate_comment, validate_ticket

bp = Blueprint("tickets", __name__)


# --------------------------------------------------------------------- helpers
def _load_request(req_id):
    """Fetch a request the current user may see, otherwise respond 404."""
    req = svc.get_request(req_id)
    if req is None or not svc.can_view(current_user(), req):
        abort(404)
    return req


def _save_photo(file):
    """Validate and store an uploaded image. Returns (filename, error)."""
    if file is None or not file.filename:
        return None, None
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in current_app.config["ALLOWED_IMAGE_TYPES"]:
        return None, "Photos must be PNG, JPG, GIF or WebP images."
    kind = sniff_image(file.stream.read(16))
    file.stream.seek(0)
    if kind is None:
        return None, "That file doesn't look like a real image."
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{kind}"
    file.save(os.path.join(folder, name))
    return name, None


def _delete_photo(name):
    if name:
        try:
            os.remove(os.path.join(current_app.config["UPLOAD_FOLDER"], name))
        except OSError:
            pass


def _detail_url(req_id, anchor=""):
    return url_for("tickets.detail", req_id=req_id) + anchor


# ------------------------------------------------------------------- list views
def _render_list(*, heading, subtitle, endpoint, owner_id=None, assignee_id=None, empty_text):
    filters = svc.parse_filters(request.args)
    page = svc.search_requests(
        filters,
        owner_id=owner_id,
        assignee_id=assignee_id,
        page=clamp_page(request.args.get("page")),
        per_page=current_app.config["PER_PAGE"],
    )
    return render_template(
        "tickets/list.html",
        heading=heading,
        subtitle=subtitle,
        endpoint=endpoint,
        page=page,
        filters=filters,
        args={k: v for k, v in request.args.items() if k != "page"},
        counts=svc.status_counts(owner_id=owner_id, assignee_id=assignee_id),
        sort_labels=svc.SORT_LABELS,
        empty_text=empty_text,
    )


@bp.route("/requests")
@login_required
def mine():
    return _render_list(
        heading="My requests",
        subtitle="Everything you have reported, newest first.",
        endpoint="tickets.mine",
        owner_id=current_user()["id"],
        empty_text="You haven't reported anything yet.",
    )


@bp.route("/assigned")
@roles_required("technician", "admin")
def assigned():
    return _render_list(
        heading="Assigned to me",
        subtitle="Requests an administrator has handed to you.",
        endpoint="tickets.assigned",
        assignee_id=current_user()["id"],
        empty_text="Nothing is assigned to you right now.",
    )


# ------------------------------------------------------------------------ create
@bp.route("/requests/new", methods=["GET", "POST"])
@login_required
def new():
    user = current_user()
    form = {"category": request.args.get("category", ""), "priority": "Medium"}
    if request.method == "POST":
        fields = ("title", "category", "building", "room", "priority", "description")
        form = {k: request.form.get(k, "").strip() for k in fields}
        errors = validate_ticket(form)
        photo = None
        if not errors:
            photo, problem = _save_photo(request.files.get("photo"))
            if problem:
                errors.append(problem)
        if not errors:
            created = now()
            try:
                with transaction() as db:
                    cursor = db.execute(
                        "INSERT INTO requests (user_id, title, category, building, room, priority,"
                        " description, status, attachment, due_at, created_at, updated_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?)",
                        (user["id"], form["title"], form["category"], form["building"],
                         form["room"], form["priority"], form["description"], photo,
                         svc.sla_due(form["priority"], created),
                         created.strftime("%Y-%m-%d %H:%M:%S"), created.strftime("%Y-%m-%d %H:%M:%S")),
                    )
                    req_id = cursor.lastrowid
                    svc.log_event(db, req_id, user["id"], "created", "Request submitted")
                    svc.notify_admins(
                        db,
                        f"New {form['priority'].lower()} priority request: {form['title']}",
                        _detail_url(req_id),
                        exclude=user["id"],
                    )
            except Exception:
                _delete_photo(photo)
                raise
            flash(f"Request {svc.ticket_code(req_id)} submitted. We'll keep you posted.", "success")
            return redirect(_detail_url(req_id))
        for message in errors:
            flash(message, "error")
    return render_template("tickets/new.html", form=form, buildings=BUILDINGS)


# ------------------------------------------------------------------------ detail
@bp.route("/requests/<int:req_id>")
@login_required
def detail(req_id):
    user = current_user()
    req = _load_request(req_id)
    staff = svc.is_staff(user)
    return render_template(
        "tickets/detail.html",
        r=req,
        events=svc.get_events(req_id, include_internal=staff),
        technicians=svc.technician_options() if user["role"] == "admin" else [],
        sla=svc.sla_info(req),
        is_owner=req["user_id"] == user["id"],
        can_manage=staff and (user["role"] == "admin" or req["assignee_id"] == user["id"]),
        tech_statuses=TECHNICIAN_STATUSES,
    )


@bp.route("/requests/<int:req_id>/comment", methods=["POST"])
@login_required
def comment(req_id):
    user = current_user()
    req = _load_request(req_id)
    text = request.form.get("message", "").strip()
    internal = request.form.get("internal") == "1" and svc.is_staff(user)
    problem = validate_comment(text)
    if problem:
        flash(problem, "error")
        return redirect(_detail_url(req_id, "#reply"))
    with transaction() as db:
        svc.log_event(db, req_id, user["id"], "note" if internal else "comment", text, internal)
        db.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (now_str(), req_id))
        if not internal:
            svc.notify_parties(
                db, req, user["id"],
                f"{user['name']} commented on {svc.ticket_code(req_id)}",
                _detail_url(req_id, "#timeline"),
                include_admins=req["assignee_id"] is None and req["user_id"] == user["id"],
            )
    flash("Internal note saved." if internal else "Comment posted.", "success")
    return redirect(_detail_url(req_id, "#timeline"))


# ------------------------------------------------------------------ staff update
@bp.route("/requests/<int:req_id>/update", methods=["POST"])
@roles_required("technician", "admin")
def update(req_id):
    user = current_user()
    req = _load_request(req_id)
    is_admin = user["role"] == "admin"
    if not is_admin and req["assignee_id"] != user["id"]:
        abort(403)

    code = svc.ticket_code(req_id)
    sets, params, notes = [], [], []

    # -- status
    status = request.form.get("status", req["status"])
    if status != req["status"]:
        allowed = STATUSES if is_admin else TECHNICIAN_STATUSES
        if status not in allowed or (not is_admin and req["status"] in ("Rejected", "Cancelled")):
            flash("You can't move this request to that status.", "error")
            return redirect(_detail_url(req_id))
        sets += ["status = ?", "resolved_at = ?"]
        params += [status, now_str() if status == "Resolved" else None]
        notes.append(("status", f"Status changed from {req['status']} to {status}"))

    # -- assignee and priority (administrators only)
    if is_admin:
        raw = request.form.get("assignee", "")
        new_assignee = int(raw) if raw.isascii() and raw.isdigit() else None
        if new_assignee != req["assignee_id"]:
            target = None
            if new_assignee is not None:
                target = query_one(
                    "SELECT id, name FROM users WHERE id = ? AND role = 'technician' AND is_active = 1",
                    (new_assignee,),
                )
                if target is None:
                    flash("Choose an active technician.", "error")
                    return redirect(_detail_url(req_id))
            sets.append("assignee_id = ?")
            params.append(new_assignee)
            notes.append(("assign", f"Assigned to {target['name']}" if target else "Assignment removed"))

        priority = request.form.get("priority", req["priority"])
        if priority != req["priority"] and priority in PRIORITIES:
            created = parse_ts(req["created_at"]) or now()
            sets += ["priority = ?", "due_at = ?"]
            params += [priority, svc.sla_due(priority, created)]
            notes.append(("priority", f"Priority changed from {req['priority']} to {priority}"))

    reply = request.form.get("message", "").strip()
    internal = request.form.get("internal") == "1"
    if reply:
        problem = validate_comment(reply)
        if problem:
            flash(problem, "error")
            return redirect(_detail_url(req_id))

    if not notes and not reply:
        flash("Nothing to update.", "info")
        return redirect(_detail_url(req_id))

    with transaction() as db:
        if sets:
            db.execute(f"UPDATE requests SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
                       params + [now_str(), req_id])
        else:
            db.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (now_str(), req_id))
        for kind, message in notes:
            svc.log_event(db, req_id, user["id"], kind, message)
        if reply:
            svc.log_event(db, req_id, user["id"], "note" if internal else "comment", reply, internal)

        fresh = svc.get_request(req_id)
        link = _detail_url(req_id, "#timeline")
        for kind, message in notes:
            if kind == "assign" and fresh["assignee_id"]:
                svc.notify(db, fresh["assignee_id"], f"{code} was assigned to you", link)
            svc.notify_parties(db, fresh, user["id"], f"{code}: {message}", link)
        if reply and not internal and not notes:
            svc.notify_parties(db, fresh, user["id"], f"{user['name']} replied on {code}", link)
    flash("Request updated.", "success")
    return redirect(_detail_url(req_id, "#timeline"))


# ------------------------------------------------------------------ owner actions
@bp.route("/requests/<int:req_id>/cancel", methods=["POST"])
@login_required
def cancel(req_id):
    user = current_user()
    req = _load_request(req_id)
    if req["user_id"] != user["id"]:
        abort(403)
    if req["status"] != "Pending":
        flash("Only pending requests can be cancelled.", "error")
        return redirect(_detail_url(req_id))
    with transaction() as db:
        db.execute("UPDATE requests SET status = 'Cancelled', updated_at = ? WHERE id = ?",
                   (now_str(), req_id))
        svc.log_event(db, req_id, user["id"], "status", "Requester cancelled the request")
        svc.notify_admins(db, f"{svc.ticket_code(req_id)} was cancelled by the requester",
                          _detail_url(req_id), exclude=user["id"])
        if req["assignee_id"]:
            svc.notify(db, req["assignee_id"], f"{svc.ticket_code(req_id)} was cancelled",
                       _detail_url(req_id))
    flash("Request cancelled.", "info")
    return redirect(_detail_url(req_id))


@bp.route("/requests/<int:req_id>/feedback", methods=["POST"])
@login_required
def feedback(req_id):
    user = current_user()
    req = _load_request(req_id)
    if req["user_id"] != user["id"]:
        abort(403)
    if req["status"] != "Resolved":
        flash("You can rate a request once it has been resolved.", "error")
        return redirect(_detail_url(req_id))
    if req["rating"] is not None:
        flash("You have already rated this request.", "info")
        return redirect(_detail_url(req_id))
    raw = request.form.get("rating", "")
    if not (raw.isascii() and raw.isdigit() and 1 <= int(raw) <= 5):
        flash("Choose a rating from 1 to 5 stars.", "error")
        return redirect(_detail_url(req_id, "#feedback"))
    rating = int(raw)
    comment_text = request.form.get("feedback", "").strip()[:500]
    with transaction() as db:
        db.execute("UPDATE requests SET rating = ?, feedback = ?, updated_at = ? WHERE id = ?",
                   (rating, comment_text or None, now_str(), req_id))
        svc.log_event(db, req_id, user["id"], "feedback",
                      f"Rated the service {rating} out of 5" + (f": {comment_text}" if comment_text else ""))
        if req["assignee_id"]:
            svc.notify(db, req["assignee_id"], f"{svc.ticket_code(req_id)} received {rating} star(s)",
                       _detail_url(req_id))
    flash("Thanks for the feedback.", "success")
    return redirect(_detail_url(req_id, "#feedback"))

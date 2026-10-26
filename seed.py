"""Load demo data so every screen has something to show.

    python seed.py            add demo users and requests (safe to run twice)
    python seed.py --reset    delete the database first, then add demo data

Demo logins
    Administrator   admin@campus.local      admin123
    Technicians     ravi@campus.local       Tech@1234     (also meena, karthik, suresh)
    Students        anitha@campus.local     Student@123   (also vignesh, priya, arun, divya, lakshmi)
"""
import argparse
import os
import random
from datetime import timedelta

from werkzeug.security import generate_password_hash

from smartcampus import create_app
from smartcampus.config import Config, PRIORITY_SLA_HOURS
from smartcampus.db import query_one, transaction
from smartcampus.services import log_event, notify, sla_due, ticket_code
from smartcampus.utils import TS_FORMAT, now

TECH_PASSWORD = "Tech@1234"
STUDENT_PASSWORD = "Student@123"

TECHNICIANS = [
    ("Ravi Kumar", "ravi@campus.local", "Electrical"),
    ("Meena Devi", "meena@campus.local", "Plumbing"),
    ("Karthik Raj", "karthik@campus.local", "Wi-Fi / Network"),
    ("Suresh Babu", "suresh@campus.local", "Classroom / Lab"),
]
STUDENTS = [
    ("Anitha S", "anitha@campus.local", "CSE"),
    ("Vignesh M", "vignesh@campus.local", "ECE"),
    ("Priya R", "priya@campus.local", "Mechanical"),
    ("Arun Kumar", "arun@campus.local", "Boys Hostel"),
    ("Divya K", "divya@campus.local", "Girls Hostel"),
    ("Dr. Lakshmi N", "lakshmi@campus.local", "Physics Department"),
]

# category -> [(title, description, building, room)]
PROBLEMS = {
    "Electrical": [
        ("Ceiling fan not working", "The ceiling fan stopped during the morning lecture and hums when switched on.", "Main Block", "Room 204"),
        ("Corridor lights flickering", "The tube lights on the first floor corridor flicker and switch off for a few seconds.", "Engineering Block", "1st floor corridor"),
        ("Socket sparking near the desks", "One socket at the back sparks when a charger is plugged in. Nobody should use it.", "Science Block", "Lab 3"),
    ],
    "Plumbing": [
        ("Leaking tap in washroom", "The tap in the ground floor washroom drips all day and the floor stays wet.", "Main Block", "Ground floor washroom"),
        ("No water on the second floor", "There has been no water supply on the second floor since last evening.", "Boys Hostel", "2nd floor"),
        ("Blocked drain behind the cafeteria", "Water is pooling near the back door and starting to smell.", "Cafeteria", "Back entrance"),
    ],
    "Wi-Fi / Network": [
        ("Wi-Fi keeps disconnecting", "The network drops every few minutes in the seminar hall, so online sessions keep freezing.", "Auditorium", "Seminar hall"),
        ("LAN port dead in computer lab", "Four systems in the second row have no network even though the cable is plugged in.", "Engineering Block", "CSE Lab 2"),
        ("No Wi-Fi signal in hostel block", "There has been no signal in the east wing for two days.", "Girls Hostel", "East wing"),
    ],
    "Classroom / Lab": [
        ("Projector shows a green tint", "The picture has a strong green tint, so slides are hard to read.", "Main Block", "Room 112"),
        ("Two lab PCs will not boot", "Systems 14 and 15 stop at a black screen after the logo appears.", "Science Block", "Computer Lab"),
        ("Whiteboard marker tray broken", "The tray fell off the wall and the markers keep rolling away.", "Main Block", "Room 305"),
    ],
    "Cleaning": [
        ("Washroom needs urgent cleaning", "The first floor washroom has not been cleaned for two days.", "Engineering Block", "1st floor washroom"),
        ("Overflowing waste bins", "The bins near the cafeteria entrance are overflowing and attracting flies.", "Cafeteria", "Entrance"),
    ],
    "Hostel": [
        ("Window latch broken", "The window latch in my room is broken, so the window will not close at night.", "Boys Hostel", "Room 118"),
        ("Water cooler not cooling", "The mess hall water cooler only dispenses warm water.", "Girls Hostel", "Mess hall"),
        ("Bed frame loose", "The bed frame wobbles and one of the bolts is missing.", "Boys Hostel", "Room 231"),
    ],
    "Transport": [
        ("Route 7 bus running late", "The Route 7 bus has been arriving 25 to 30 minutes late all week.", "Parking and Gates", "Bus bay 2"),
        ("Bus seat torn", "Two seats at the back of the Route 3 bus are torn and unsafe.", "Parking and Gates", "Bus bay 1"),
    ],
    "Library": [
        ("Reading room AC too cold", "The AC is set far too low and students cannot sit there for long.", "Library", "Reading room"),
        ("Broken chairs in reading room", "Three chairs have broken backs and need replacing.", "Library", "Ground floor"),
    ],
    "Security": [
        ("Main gate CCTV offline", "The camera at the main gate shows a blank screen on the monitor.", "Parking and Gates", "Main gate"),
        ("Street light out near parking", "The light near the two-wheeler parking has been off for a week.", "Parking and Gates", "Two-wheeler parking"),
    ],
    "Other": [
        ("Notice board glass cracked", "The glass on the main notice board is cracked and could cut someone.", "Main Block", "Entrance lobby"),
    ],
}
CATEGORY_WEIGHTS = {
    "Electrical": 5, "Plumbing": 4, "Wi-Fi / Network": 5, "Classroom / Lab": 4, "Cleaning": 3,
    "Hostel": 4, "Transport": 2, "Library": 2, "Security": 2, "Other": 1,
}
PRIORITY_WEIGHTS = {"Low": 15, "Medium": 45, "High": 28, "Urgent": 12}
FEEDBACK = {
    "good": [
        "Fixed quickly, thank you.",
        "The technician was polite and explained what went wrong.",
        "Problem solved. Please check the other rooms on this floor too.",
        "Good work.",
    ],
    "mixed": ["Works now, but it took longer than expected."],
    "poor": ["The problem came back after two days.", "Nobody told me when the technician was coming."],
}
REJECT_REASONS = [
    "Duplicate of an earlier request.",
    "This falls under the contractor's warranty, so it was forwarded to them.",
]
FOLLOW_UPS = [
    "Any update on this? It is affecting our class.",
    "I have added the room number in the description.",
    "Thanks, I can see the technician has started.",
]
STAFF_REPLIES = [
    "We have ordered the spare part and will fix it as soon as it arrives.",
    "A technician will visit this afternoon.",
    "Please keep the area clear so we can work.",
]


def ts(value):
    return value.strftime(TS_FORMAT)


def pick(rng, weights):
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def add_user(db, name, email, password_hash, role, department, specialty, joined):
    cursor = db.execute(
        "INSERT INTO users (name, email, password_hash, role, department, specialty, is_active, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
        (name, email, password_hash, role, department, specialty, ts(joined)),
    )
    return cursor.lastrowid


def choose_status(rng, age_hours):
    if age_hours > 96:
        table = {"Resolved": 62, "In Progress": 12, "Pending": 12, "Rejected": 7, "Cancelled": 7}
    elif age_hours > 24:
        table = {"Resolved": 35, "In Progress": 30, "Pending": 25, "Rejected": 5, "Cancelled": 5}
    else:
        table = {"Pending": 55, "In Progress": 35, "Resolved": 10}
    status = pick(rng, table)
    if status == "Resolved" and age_hours < 8:
        status = "In Progress"
    return status


def seed():
    if query_one("SELECT 1 FROM users WHERE email = ?", (TECHNICIANS[0][1],)):
        print("Demo data is already loaded. Run `python seed.py --reset` to start over.")
        return False

    rng = random.Random(42)
    stamp = now()
    admin_id = query_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")["id"]
    tech_hash = generate_password_hash(TECH_PASSWORD)
    student_hash = generate_password_hash(STUDENT_PASSWORD)

    with transaction() as db:
        technicians = [
            (add_user(db, n, e, tech_hash, "technician", "Maintenance", s, stamp - timedelta(days=90)), s)
            for n, e, s in TECHNICIANS
        ]
        student_ids = [
            add_user(db, n, e, student_hash, "user", d, None, stamp - timedelta(days=rng.randint(30, 80)))
            for n, e, d in STUDENTS
        ]
        by_specialty = {spec: uid for uid, spec in technicians}
        tech_names = {uid: name for (uid, _), (name, _e, _s) in zip(technicians, TECHNICIANS)}

        plans = []
        for _ in range(48):
            category = pick(rng, CATEGORY_WEIGHTS)
            title, description, building, room = rng.choice(PROBLEMS[category])
            created = stamp - timedelta(hours=30 * 24 * rng.random() ** 1.3 + 1)
            plans.append({
                "category": category, "title": title, "description": description,
                "building": building, "room": room, "priority": pick(rng, PRIORITY_WEIGHTS),
                "user_id": rng.choice(student_ids), "created": created.replace(microsecond=0),
            })
        plans.sort(key=lambda plan: plan["created"])  # ticket numbers follow time

        latest = {"Pending": [], "assigned": [], "resolved": []}
        for plan in plans:
            created = plan["created"]
            age_hours = (stamp - created).total_seconds() / 3600
            status = choose_status(rng, age_hours)
            sla_hours = PRIORITY_SLA_HOURS[plan["priority"]]

            assignee = None
            if status in ("In Progress", "Resolved") or (status == "Pending" and rng.random() < 0.2):
                specialist = by_specialty.get(plan["category"])
                assignee = specialist if specialist and rng.random() < 0.7 else rng.choice(technicians)[0]

            limit = stamp - timedelta(minutes=5)
            assigned_at = min(created + timedelta(hours=rng.uniform(0.3, 3)), limit)
            started_at = min(assigned_at + timedelta(hours=rng.uniform(0.5, 6)), limit)
            resolved_at = None
            if status == "Resolved":
                wanted = created + timedelta(hours=sla_hours * rng.uniform(0.25, 1.35))
                resolved_at = min(max(wanted, started_at + timedelta(minutes=10)), limit)

            rating = feedback = None
            if status == "Resolved" and rng.random() < 0.75:
                rating = rng.choices([5, 4, 3, 2, 1], weights=[45, 30, 15, 7, 3])[0]
                mood = "good" if rating >= 4 else "mixed" if rating == 3 else "poor"
                feedback = rng.choice(FEEDBACK[mood]) if rng.random() < 0.6 else None

            cursor = db.execute(
                "INSERT INTO requests (user_id, assignee_id, title, category, building, room, priority,"
                " description, status, due_at, rating, feedback, created_at, updated_at, resolved_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (plan["user_id"], assignee, plan["title"], plan["category"], plan["building"],
                 plan["room"], plan["priority"], plan["description"], status,
                 sla_due(plan["priority"], created), rating, feedback, ts(created), ts(created),
                 ts(resolved_at) if resolved_at else None),
            )
            req_id = cursor.lastrowid
            last = created

            def event(kind, message, when, user_id, internal=False):
                nonlocal last
                log_event(db, req_id, user_id, kind, message, internal, ts(when))
                last = max(last, when)

            event("created", "Request submitted", created, plan["user_id"])
            if assignee:
                event("assign", f"Assigned to {tech_names[assignee]}", assigned_at, admin_id)
            if status == "In Progress" or status == "Resolved":
                event("status", "Status changed from Pending to In Progress", started_at, assignee)
                if rng.random() < 0.4:
                    event("comment", rng.choice(STAFF_REPLIES), started_at + timedelta(minutes=20), assignee)
            if rng.random() < 0.3 and status != "Cancelled":
                event("comment", rng.choice(FOLLOW_UPS), min(created + timedelta(hours=rng.uniform(1, 12)), limit), plan["user_id"])
            if status == "Resolved":
                event("status", "Status changed from In Progress to Resolved", resolved_at, assignee)
                if rating:
                    when = min(resolved_at + timedelta(hours=rng.uniform(1, 20)), limit)
                    event("feedback", f"Rated the service {rating} out of 5" + (f": {feedback}" if feedback else ""),
                          when, plan["user_id"])
            elif status == "Rejected":
                event("status", "Status changed from Pending to Rejected", min(created + timedelta(hours=2), limit), admin_id)
                event("comment", rng.choice(REJECT_REASONS), min(created + timedelta(hours=2, minutes=1), limit), admin_id)
            elif status == "Cancelled":
                event("status", "Requester cancelled the request", min(created + timedelta(hours=rng.uniform(0.5, 10)), limit), plan["user_id"])

            db.execute("UPDATE requests SET updated_at = ? WHERE id = ?", (ts(last), req_id))
            link = f"/requests/{req_id}"
            if status == "Pending":
                latest["Pending"].append((req_id, plan, link))
            if assignee and status in ("Pending", "In Progress"):
                latest["assigned"].append((req_id, assignee, link))
            if status == "Resolved":
                latest["resolved"].append((req_id, plan["user_id"], link))

        # A few unread notifications so the bell badges have something to show.
        for req_id, plan, link in latest["Pending"][-4:]:
            notify(db, admin_id, f"New {plan['priority'].lower()} priority request: {plan['title']}", link)
        for req_id, tech_id, link in latest["assigned"][-8:]:
            notify(db, tech_id, f"{ticket_code(req_id)} was assigned to you", link)
        for req_id, user_id, link in latest["resolved"][-6:]:
            notify(db, user_id, f"{ticket_code(req_id)}: Status changed from In Progress to Resolved", link)

    total = query_one("SELECT COUNT(*) AS n FROM requests")["n"]
    print(f"Loaded {len(TECHNICIANS)} technicians, {len(STUDENTS)} students and {total} requests.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Load demo data into the Smart Campus database.")
    parser.add_argument("--reset", action="store_true", help="delete the existing database first")
    args = parser.parse_args()

    if args.reset:
        for suffix in ("", "-wal", "-shm", "-journal"):
            path = Config.DATABASE + suffix
            if os.path.exists(path):
                os.remove(path)
        print("Existing database removed.")

    app = create_app()
    with app.app_context():
        if not seed():
            return
    print()
    print("Sign in at http://127.0.0.1:5000 with any of these:")
    print(f"  Administrator  {app.config['ADMIN_EMAIL']}   {app.config['ADMIN_PASSWORD']}")
    print(f"  Technician     ravi@campus.local        {TECH_PASSWORD}")
    print(f"  Student        anitha@campus.local      {STUDENT_PASSWORD}")


if __name__ == "__main__":
    main()

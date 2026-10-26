"""End-to-end tests for the Smart Campus Service Request System.

Run from the project folder:

    python -m unittest -v
"""
import html
import io
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import timedelta

from smartcampus import create_app
from smartcampus.db import get_db
from smartcampus.services import sla_info, ticket_code
from smartcampus.utils import (clamp_page, csv_safe, hours_label, is_safe_redirect,
                               now, sniff_image, TS_FORMAT)

ADMIN = ("admin@test.local", "admin12345")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TOKEN_RE = re.compile(r'name="csrf_token" value="(\w+)"')


class Browser:
    """A tiny wrapper that behaves like a person using a browser."""

    def __init__(self, app):
        self.client = app.test_client()
        self.token_page = "/login"

    def get(self, url, follow=True):
        return self.client.get(url, follow_redirects=follow)

    def post(self, url, data=None, follow=True, **kwargs):
        page = self.client.get(self.token_page).get_data(as_text=True)
        payload = dict(data or {})
        payload["csrf_token"] = TOKEN_RE.search(page).group(1)
        return self.client.post(url, data=payload, follow_redirects=follow, **kwargs)

    def login(self, email, password):
        response = self.post("/login", {"email": email, "password": password})
        if "/login" not in response.request.path:
            self.token_page = "/profile"
        return response

    def logout(self):
        response = self.post("/logout")
        self.token_page = "/login"
        return response


def text(response):
    return html.unescape(response.get_data(as_text=True))


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": os.path.join(self.tmp.name, "test.db"),
            "UPLOAD_FOLDER": os.path.join(self.tmp.name, "uploads"),
            "ADMIN_EMAIL": ADMIN[0],
            "ADMIN_PASSWORD": ADMIN[1],
            "LOGIN_MAX_ATTEMPTS": 3,
            "PER_PAGE": 10,
        })

    def tearDown(self):
        self.tmp.cleanup()

    # ------------------------------------------------------------- helpers
    def browser(self):
        return Browser(self.app)

    def register(self, who, name, email, password="Passw0rd!1"):
        return who.post("/register", {
            "name": name, "email": email, "department": "CSE",
            "phone": "", "password": password, "confirm": password,
        })

    def make_user(self, name, email, password="Passw0rd!1"):
        browser = self.browser()
        self.register(browser, name, email, password)
        browser.login(email, password)
        return browser

    def make_admin(self):
        browser = self.browser()
        browser.login(*ADMIN)
        return browser

    @staticmethod
    def status(browser, url, follow=True):
        """Fetch a URL, close the response (releases file handles) and return its status."""
        response = browser.get(url, follow=follow)
        code = response.status_code
        response.close()
        return code

    def user_id(self, email):
        with self.app.app_context():
            return get_db().execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()["id"]

    def sql(self, query, params=()):
        with self.app.app_context():
            db = get_db()
            rows = db.execute(query, params).fetchall()
            db.commit()
            return rows

    def new_request(self, who, title="Fan not working", **overrides):
        data = {
            "title": title, "category": "Electrical", "building": "Main Block",
            "room": "Room 204", "priority": "High",
            "description": "The ceiling fan stopped working yesterday.",
        }
        data.update(overrides)
        return who.post("/requests/new", data)

    def make_technician(self, admin, name="Ravi Kumar", email="ravi@test.local"):
        self.make_user(name, email)
        admin.post(f"/admin/users/{self.user_id(email)}/update",
                   {"role": "technician", "specialty": "Electrical", "active": "1"})
        return self.user_id(email)


class PublicAndAuthTests(AppTestCase):
    def test_public_pages_render(self):
        guest = self.browser()
        for url in ("/", "/login", "/register"):
            self.assertEqual(guest.get(url).status_code, 200, url)
        self.assertIn("Report a campus problem", text(guest.get("/")))
        self.assertIn("Response targets", text(guest.get("/")))

    def test_protected_pages_redirect_guests(self):
        guest = self.browser()
        response = guest.get("/requests", follow=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        self.assertEqual(guest.get("/api/notifications/unread").status_code, 401)

    def test_registration_rules(self):
        guest = self.browser()
        weak = self.register(guest, "Anitha S", "anitha@test.local", "short")
        self.assertIn("at least 8 characters", text(weak))
        nodigit = self.register(guest, "Anitha S", "anitha@test.local", "onlyletters")
        self.assertIn("letter and one number", text(nodigit))
        mismatch = guest.post("/register", {"name": "Anitha S", "email": "anitha@test.local",
                                            "password": "Passw0rd!1", "confirm": "Different1"})
        self.assertIn("do not match", text(mismatch))
        ok = self.register(guest, "Anitha S", "anitha@test.local")
        self.assertIn("Account created", text(ok))
        duplicate = self.register(guest, "Someone Else", "ANITHA@test.local")
        self.assertIn("already registered", text(duplicate))

    def test_email_domain_restriction(self):
        self.app.config["ALLOWED_EMAIL_DOMAINS"] = ["college.edu"]
        guest = self.browser()
        blocked = self.register(guest, "Outsider", "x@gmail.com")
        self.assertIn("campus email", text(blocked))
        allowed = self.register(guest, "Student", "s@college.edu")
        self.assertIn("Account created", text(allowed))

    def test_login_logout_and_redirect_by_role(self):
        user = self.make_user("Anitha S", "anitha@test.local")
        self.assertIn("My requests", text(user.get("/home")))
        user.logout()
        self.assertEqual(user.get("/requests", follow=False).status_code, 302)
        admin = self.make_admin()
        self.assertIn("Open requests", text(admin.get("/home")))

    def test_login_throttle_and_wrong_password(self):
        self.make_user("Anitha S", "anitha@test.local")
        guest = self.browser()
        for _ in range(3):
            self.assertIn("incorrect", text(guest.login("anitha@test.local", "wrong-pass1")))
        blocked = guest.login("anitha@test.local", "Passw0rd!1")
        self.assertIn("Too many failed attempts", text(blocked))

    def test_next_url_is_followed_only_when_local(self):
        self.make_user("Anitha S", "anitha@test.local")
        guest = self.browser()
        token = TOKEN_RE.search(guest.get("/login").get_data(as_text=True)).group(1)
        good = guest.client.post("/login", data={
            "email": "anitha@test.local", "password": "Passw0rd!1",
            "csrf_token": token, "next": "/requests/new"})
        self.assertTrue(good.headers["Location"].endswith("/requests/new"))
        guest.token_page = "/profile"
        guest.logout()
        token = TOKEN_RE.search(guest.get("/login").get_data(as_text=True)).group(1)
        evil = guest.client.post("/login", data={
            "email": "anitha@test.local", "password": "Passw0rd!1",
            "csrf_token": token, "next": "https://evil.example/steal"})
        self.assertNotIn("evil.example", evil.headers["Location"])

    def test_csrf_token_is_required(self):
        guest = self.browser()
        response = guest.client.post("/login", data={"email": "a@b.co", "password": "x"})
        self.assertEqual(response.status_code, 400)

    def test_disabled_account_cannot_sign_in(self):
        admin = self.make_admin()
        self.make_user("Anitha S", "anitha@test.local")
        admin.post(f"/admin/users/{self.user_id('anitha@test.local')}/update", {"role": "user"})
        guest = self.browser()
        self.assertIn("disabled", text(guest.login("anitha@test.local", "Passw0rd!1")))

    def test_security_headers_present(self):
        response = self.browser().get("/login")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")


class RequestFlowTests(AppTestCase):
    def test_user_dashboard_shows_actionable_summary(self):
        student = self.make_user("Anitha S", "anitha@test.local")
        self.assertIn("Everything about your campus requests", text(student.get("/home")))
        self.new_request(student, title="Broken projector")
        dashboard = text(student.get("/home"))
        self.assertIn("Broken projector", dashboard)
        self.assertIn("Open requests", dashboard)
        self.assertIn("Quick actions", dashboard)

    def test_create_request_and_view_it(self):
        student = self.make_user("Anitha S", "anitha@test.local")
        response = self.new_request(student)
        page = text(response)
        self.assertIn("SC-0001", page)
        self.assertIn("Fan not working", page)
        self.assertIn("Pending", page)
        listing = text(student.get("/requests"))
        self.assertIn("Fan not working", listing)

    def test_validation_errors_keep_form_values(self):
        student = self.make_user("Anitha S", "anitha@test.local")
        response = self.new_request(student, title="ab", description="short")
        page = text(response)
        self.assertIn("short title", page)
        self.assertIn("10 to 2000 characters", page)
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM requests")[0]["n"], 0)

    def test_other_users_cannot_see_a_request(self):
        owner = self.make_user("Anitha S", "anitha@test.local")
        other = self.make_user("Vignesh M", "vignesh@test.local")
        self.new_request(owner)
        self.assertEqual(other.get("/requests/1").status_code, 404)
        self.assertEqual(other.post("/requests/1/cancel").status_code, 404)
        self.assertEqual(self.make_admin().get("/requests/1").status_code, 200)

    def test_admin_is_notified_of_new_requests(self):
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student, title="Broken window latch")
        admin = self.make_admin()
        page = text(admin.get("/notifications"))
        self.assertIn("New high priority request: Broken window latch", page)
        self.assertEqual(admin.get("/api/notifications/unread").get_json()["count"], 1)
        admin.post("/notifications/read")
        self.assertEqual(admin.get("/api/notifications/unread").get_json()["count"], 0)

    def test_cancel_only_while_pending(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student)
        self.new_request(student, title="Second problem")
        self.assertIn("Request cancelled", text(student.post("/requests/1/cancel")))
        admin.post("/requests/2/update", {"status": "In Progress"})
        self.assertIn("Only pending requests", text(student.post("/requests/2/cancel")))

    def test_comments_and_internal_notes(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student)
        student.post("/requests/1/comment", {"message": "It is getting worse."})
        admin.post("/requests/1/comment", {"message": "Secret staff detail", "internal": "1"})
        admin.post("/requests/1/comment", {"message": "We are on it."})
        student_view = text(student.get("/requests/1"))
        self.assertIn("It is getting worse.", student_view)
        self.assertIn("We are on it.", student_view)
        self.assertNotIn("Secret staff detail", student_view)
        self.assertIn("Secret staff detail", text(admin.get("/requests/1")))
        self.assertIn("Write a message", text(student.post("/requests/1/comment", {"message": " "})))

    def test_photo_upload_is_validated_and_access_controlled(self):
        owner = self.make_user("Anitha S", "anitha@test.local")
        other = self.make_user("Vignesh M", "vignesh@test.local")
        good = self.new_request(owner, photo=(io.BytesIO(PNG), "leak.png"))
        self.assertIn("Photo attached", text(good))
        stored = self.sql("SELECT attachment FROM requests WHERE id = 1")[0]["attachment"]
        self.assertTrue(stored.endswith(".png"))
        self.assertTrue(os.path.exists(os.path.join(self.app.config["UPLOAD_FOLDER"], stored)))
        self.assertEqual(self.status(owner, f"/uploads/{stored}"), 200)
        self.assertEqual(self.status(other, f"/uploads/{stored}"), 404)
        self.assertEqual(self.status(self.browser(), f"/uploads/{stored}", follow=False), 302)

        fake = self.new_request(owner, title="Fake image here", photo=(io.BytesIO(b"<script>x</script>"), "evil.png"))
        self.assertIn("doesn't look like a real image", text(fake))
        wrong_type = self.new_request(owner, title="Wrong type here", photo=(io.BytesIO(PNG), "notes.txt"))
        self.assertIn("PNG, JPG, GIF or WebP", text(wrong_type))
        self.assertEqual(self.sql("SELECT COUNT(*) AS n FROM requests")[0]["n"], 1)


class StaffWorkflowTests(AppTestCase):
    def test_full_lifecycle_with_technician_and_feedback(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        tech_id = self.make_technician(admin)
        technician = self.browser()
        technician.login("ravi@test.local", "Passw0rd!1")
        self.new_request(student)

        # admin assigns and raises priority
        result = text(admin.post("/requests/1/update", {
            "status": "Pending", "assignee": str(tech_id), "priority": "Urgent"}))
        self.assertIn("Assigned to Ravi Kumar", result)
        self.assertIn("Priority changed from High to Urgent", result)
        self.assertIn("SC-0001 was assigned to you", text(technician.get("/notifications")))
        self.assertIn("Fan not working", text(technician.get("/assigned")))

        # technician moves it forward
        self.assertIn("Request updated", text(technician.post("/requests/1/update", {"status": "In Progress"})))
        self.assertIn("Status changed from Pending to In Progress", text(student.get("/notifications")))
        technician.post("/requests/1/update", {"status": "Resolved", "message": "Replaced the capacitor."})
        row = self.sql("SELECT status, resolved_at FROM requests WHERE id = 1")[0]
        self.assertEqual(row["status"], "Resolved")
        self.assertIsNotNone(row["resolved_at"])

        # requester rates it exactly once
        page = text(student.get("/requests/1"))
        self.assertIn("Service feedback", page)
        self.assertIn("Replaced the capacitor.", page)
        self.assertIn("Thanks for the feedback", text(student.post("/requests/1/feedback", {"rating": "5", "feedback": "Great"})))
        self.assertIn("already rated", text(student.post("/requests/1/feedback", {"rating": "1"})))
        self.assertEqual(self.sql("SELECT rating FROM requests WHERE id = 1")[0]["rating"], 5)

    def test_technician_limits(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.make_technician(admin)
        technician = self.browser()
        technician.login("ravi@test.local", "Passw0rd!1")
        self.new_request(student)
        self.assertEqual(technician.get("/requests/1").status_code, 404)          # not assigned
        self.assertEqual(technician.post("/requests/1/update", {"status": "Resolved"}).status_code, 404)
        self.assertEqual(technician.get("/admin").status_code, 403)
        admin.post("/requests/1/update", {"assignee": str(self.user_id("ravi@test.local"))})
        denied = text(technician.post("/requests/1/update", {"status": "Rejected"}))
        self.assertIn("can't move this request", denied)
        self.assertEqual(self.sql("SELECT status FROM requests WHERE id = 1")[0]["status"], "Pending")

    def test_admin_cannot_assign_to_non_technician(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student)
        page = text(admin.post("/requests/1/update", {"assignee": str(self.user_id("anitha@test.local"))}))
        self.assertIn("Choose an active technician", page)

    def test_priority_change_recomputes_deadline(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student, priority="Low")
        before = self.sql("SELECT due_at, created_at FROM requests WHERE id = 1")[0]
        admin.post("/requests/1/update", {"priority": "Urgent"})
        after = self.sql("SELECT due_at FROM requests WHERE id = 1")[0]["due_at"]
        created = now().strptime(before["created_at"], TS_FORMAT)
        due = now().strptime(after, TS_FORMAT)
        self.assertEqual(due - created, timedelta(hours=4))
        self.assertNotEqual(before["due_at"], after)


class AdminTests(AppTestCase):
    def test_admin_pages_render_and_students_are_blocked(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student)
        for url in ("/admin", "/admin/requests", "/admin/users", "/admin/reports",
                    "/notifications", "/profile", "/requests/new", "/assigned"):
            self.assertEqual(admin.get(url).status_code, 200, url)
        for url in ("/admin", "/admin/requests", "/admin/users", "/admin/reports",
                    "/admin/requests/export.csv", "/assigned"):
            self.assertEqual(student.get(url).status_code, 403, url)

    def test_filters_search_and_pagination(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        for i in range(12):
            self.new_request(student, title=f"Problem number {i + 1}",
                             category="Plumbing" if i % 2 else "Electrical")
        page1 = text(admin.get("/admin/requests"))
        self.assertEqual(page1.count('class="plaque"'), 10)
        self.assertIn("Showing 1 to 10 of 12", page1)
        page2 = text(admin.get("/admin/requests?page=2"))
        self.assertEqual(page2.count('class="plaque"'), 2)
        self.assertEqual(text(admin.get("/admin/requests?page=999")).count('class="plaque"'), 2)
        self.assertEqual(text(admin.get("/admin/requests?category=Plumbing")).count('class="plaque"'), 6)
        by_code = text(admin.get("/admin/requests?q=SC-0003"))
        self.assertIn("Problem number 3", by_code)
        self.assertEqual(by_code.count('class="plaque"'), 1)
        self.assertEqual(text(admin.get("/admin/requests?q=100%25")).count('class="plaque"'), 0)
        self.assertEqual(text(admin.get("/admin/requests?assignee=none")).count('class="plaque"'), 10)
        self.assertEqual(text(admin.get("/admin/requests?status=Bogus")).count('class="plaque"'), 10)

    def test_overdue_filter_and_sla(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student, title="Late one")
        self.new_request(student, title="On time one")
        past = (now() - timedelta(hours=5)).strftime(TS_FORMAT)
        self.sql("UPDATE requests SET due_at = ? WHERE id = 1", (past,))
        overdue = text(admin.get("/admin/requests?overdue=1"))
        self.assertIn("Late one", overdue)
        self.assertNotIn("On time one", overdue)
        self.assertIn("Overdue by 5 h", overdue)
        self.assertEqual(admin.get("/api/admin/stats").get_json()["kpis"]["overdue"], 1)

    def test_csv_export_neutralises_formulas(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student, title="=HYPERLINK(\"http://evil\")")
        response = admin.get("/admin/requests/export.csv")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.mimetype.startswith("text/csv"))
        body = response.get_data(as_text=True)
        self.assertIn("SC-0001", body)
        self.assertIn("'=HYPERLINK", body)
        self.assertNotIn(",=HYPERLINK", body)

    def test_user_management_guardrails(self):
        admin = self.make_admin()
        self.make_user("Anitha S", "anitha@test.local")
        admin_id = self.user_id(ADMIN[0])
        self.assertIn("can't remove your own", text(admin.post(f"/admin/users/{admin_id}/update", {"role": "user", "active": "1"})))
        self.assertEqual(self.sql("SELECT role FROM users WHERE id = ?", (admin_id,))[0]["role"], "admin")
        self.assertEqual(admin.post(f"/admin/users/{self.user_id('anitha@test.local')}/update", {"role": "root", "active": "1"}).status_code, 400)
        self.assertEqual(admin.post("/admin/users/9999/update", {"role": "user"}).status_code, 404)
        admin.post(f"/admin/users/{self.user_id('anitha@test.local')}/update",
                   {"role": "technician", "specialty": "Plumbing", "active": "1"})
        row = self.sql("SELECT role, specialty FROM users WHERE email = 'anitha@test.local'")[0]
        self.assertEqual((row["role"], row["specialty"]), ("technician", "Plumbing"))
        self.assertIn("Anitha S", text(admin.get("/admin/users?q=anitha&role=technician")))

    def test_stats_api_permissions(self):
        admin = self.make_admin()
        student = self.make_user("Anitha S", "anitha@test.local")
        self.new_request(student)
        data = admin.get("/api/admin/stats").get_json()
        self.assertEqual(data["kpis"]["total"], 1)
        self.assertEqual(data["kpis"]["open"], 1)
        self.assertEqual(len(data["trend"]["labels"]), 14)
        self.assertEqual(sum(data["trend"]["created"]), 1)
        self.assertEqual(data["categories"][0]["label"], "Electrical")
        self.assertEqual(student.get("/api/admin/stats").status_code, 403)
        self.assertEqual(self.browser().get("/api/admin/stats").status_code, 401)


class ProfileTests(AppTestCase):
    def test_update_profile_and_change_password(self):
        user = self.make_user("Anitha S", "anitha@test.local")
        done = user.post("/profile", {"name": "Anitha Sundar", "department": "ECE", "phone": "+91 98765 43210"})
        self.assertIn("Profile updated", text(done))
        self.assertIn("Anitha Sundar", text(user.get("/profile")))
        self.assertIn("valid phone", text(user.post("/profile", {"name": "Anitha", "phone": "abc"})))

        self.assertIn("current password is incorrect",
                      text(user.post("/profile/password", {"current": "nope", "new": "NewPassw0rd", "confirm": "NewPassw0rd"})))
        self.assertIn("at least 8", text(user.post("/profile/password", {"current": "Passw0rd!1", "new": "x1", "confirm": "x1"})))
        self.assertIn("Password changed",
                      text(user.post("/profile/password", {"current": "Passw0rd!1", "new": "NewPassw0rd", "confirm": "NewPassw0rd"})))
        user.logout()
        self.assertIn("My requests", text(user.login("anitha@test.local", "NewPassw0rd")))


class UnitTests(unittest.TestCase):
    def test_sla_info_states(self):
        base = now()

        def row(status, due_hours, created_hours=-10, resolved_hours=None):
            fmt = lambda h: None if h is None else (base + timedelta(hours=h)).strftime(TS_FORMAT)
            return {"status": status, "due_at": fmt(due_hours), "created_at": fmt(created_hours),
                    "resolved_at": fmt(resolved_hours)}

        self.assertEqual(sla_info(row("Pending", -3))["state"], "overdue")
        self.assertEqual(sla_info(row("Pending", 40, created_hours=-10))["state"], "ok")
        self.assertEqual(sla_info(row("In Progress", 1, created_hours=-20))["state"], "soon")
        self.assertEqual(sla_info(row("Resolved", -5, resolved_hours=-8))["state"], "done")
        self.assertEqual(sla_info(row("Resolved", -5, resolved_hours=-1))["state"], "late")
        self.assertEqual(sla_info(row("Cancelled", -5))["state"], "closed")

    def test_helpers(self):
        self.assertEqual(ticket_code(7), "SC-0007")
        self.assertEqual(hours_label(4), "4 hours")
        self.assertEqual(hours_label(24), "1 day")
        self.assertEqual(hours_label(168), "7 days")
        self.assertEqual(csv_safe("=1+1"), "'=1+1")
        self.assertEqual(csv_safe("plain"), "plain")
        self.assertTrue(is_safe_redirect("/requests/3?x=1"))
        for bad in ("//evil.com", "https://evil.com", "javascript:alert(1)", "/\\evil", ""):
            self.assertFalse(is_safe_redirect(bad), bad)
        self.assertEqual(sniff_image(PNG), "png")
        self.assertEqual(sniff_image(b"\xff\xd8\xff\xe0abc"), "jpg")
        self.assertEqual(sniff_image(b"GIF89a....."), "gif")
        self.assertEqual(sniff_image(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertIsNone(sniff_image(b"not an image"))
        self.assertEqual(clamp_page("abc"), 1)
        self.assertEqual(clamp_page("-4"), 1)
        self.assertEqual(clamp_page("3"), 3)

    def test_old_schema_is_rejected_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "old.db")
            conn = sqlite3.connect(path)
            conn.execute("PRAGMA user_version = 1")
            conn.commit()
            conn.close()
            with self.assertRaises(RuntimeError) as caught:
                create_app({"TESTING": True, "SECRET_KEY": "x", "DATABASE": path,
                            "UPLOAD_FOLDER": os.path.join(folder, "u")})
            self.assertIn("Delete the file", str(caught.exception))


if __name__ == "__main__":
    unittest.main()

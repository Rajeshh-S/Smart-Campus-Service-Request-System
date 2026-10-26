# Smart Campus Service Request System

A web app where students and staff report campus problems (electrical faults, leaking taps, dead Wi-Fi, broken projectors) and administrators and technicians track every request through to resolution, with response deadlines, notifications, photo evidence, analytics and reports.

**Author:** Rajesh S ([@Rajeshh-S](https://github.com/Rajeshh-S))

![Landing page](docs/landing.png)

## Screenshots

| Admin overview | Request detail |
| --- | --- |
| ![Admin overview](docs/admin-overview.png) | ![Request detail](docs/request-detail.png) |

| New request | On a phone |
| --- | --- |
| ![New request form](docs/new-request.png) | <img src="docs/mobile.png" alt="Mobile view" width="260"> |

## Features

**For students and staff**
- Create an account, then report a problem by picking a category sign, building, room, priority and an optional photo
- Follow each request from Pending to Resolved with a full activity timeline
- Comment on a request, cancel it while it is still pending, and rate the service once it is resolved
- In-app notifications whenever the status changes, plus a live unread badge

**For technicians**
- A personal "Assigned to me" queue
- Move requests to In Progress or Resolved, reply to the requester, or leave internal notes that the requester can never see

**For administrators**
- Overview dashboard with key figures and charts (14-day trend, status split, requests by category)
- "Needs attention" list of overdue and urgent requests
- Triage list with search, filters, sorting, pagination and one-click CSV export
- Assign technicians, change priority, and manage users and roles
- Reports: per category, per priority (response-target compliance) and per technician

**Under the hood**
- Response deadlines (SLA) by priority: Urgent 4 h, High 1 day, Medium 3 days, Low 7 days
- Passwords hashed with Werkzeug, CSRF tokens on every form, login throttling, secure session cookies, security headers
- Uploads are checked by file signature (not just extension) and served only to people allowed to see the request
- Parameterised SQL everywhere, LIKE wildcard escaping, CSV formula-injection protection
- Responsive layout that works on phones, keyboard friendly, respects reduced-motion settings
- 31 automated tests

## Tech stack

Python 3.9+, Flask, SQLite, Jinja2, vanilla JavaScript (charts are plain SVG, no libraries), hand-written CSS.

## Quick start

### Windows (PowerShell)

```powershell
git clone https://github.com/Rajeshh-S/Smart-Campus-Service-Request-System.git
cd Smart-Campus-Service-Request-System

python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt

python seed.py      # optional: loads demo users and 48 sample requests
python app.py
```

If PowerShell blocks `activate`, run `Set-ExecutionPolicy -Scope Process Bypass` first.

### macOS / Linux

```bash
git clone https://github.com/Rajeshh-S/Smart-Campus-Service-Request-System.git
cd Smart-Campus-Service-Request-System

python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt

python seed.py      # optional demo data
python app.py
```

Open **http://127.0.0.1:5000**. The database (`smartcampus.db`) is created on first run.

## Logins

| Role | Email | Password |
| --- | --- | --- |
| Administrator | `admin@campus.local` | `admin123` |
| Technician (after `python seed.py`) | `ravi@campus.local` | `Tech@1234` |
| Student (after `python seed.py`) | `anitha@campus.local` | `Student@123` |

Anyone can register at `/register` as a student. Administrators promote people to Technician from the **Users** page. `python seed.py --reset` wipes the database and loads the demo data again.

## Configuration

Set environment variables before starting the app. PowerShell example: `$env:ADMIN_PASSWORD = "a-strong-password"`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADMIN_EMAIL` | `admin@campus.local` | Email of the first administrator (used on first run only) |
| `ADMIN_PASSWORD` | `admin123` | Password of the first administrator (used on first run only) |
| `SECRET_KEY` | generated into `.secret_key` | Signs session cookies |
| `ALLOWED_EMAIL_DOMAINS` | empty (anyone) | e.g. `college.edu,students.college.edu` to restrict sign-ups |
| `DATABASE` | `smartcampus.db` | SQLite file location |
| `UPLOAD_FOLDER` | `uploads/` | Where request photos are stored |
| `PORT` / `HOST` | `5000` / `127.0.0.1` | Server address |
| `SESSION_COOKIE_SECURE` | off | Set to `1` when serving over HTTPS |

Categories, buildings and response targets live in `smartcampus/config.py`.

## How a request moves

1. A user submits a request. It starts as **Pending**, gets a deadline from its priority, and every administrator is notified.
2. An administrator sets the priority and assigns a technician. The technician and the requester are notified.
3. The technician sets it to **In Progress** and later **Resolved**, replying along the way.
4. The requester rates the fix. Administrators see satisfaction and on-time rates in the reports.

Administrators can also **Reject** a request (for example a duplicate), and requesters can **Cancel** while it is still pending.

## Project structure

```
Smart-Campus-Service-Request-System/
├── app.py                  # entry point: python app.py
├── seed.py                 # demo data loader
├── requirements.txt
├── smartcampus/
│   ├── __init__.py         # application factory, template helpers, error pages
│   ├── config.py           # settings and domain constants
│   ├── db.py               # SQLite schema, connection and bootstrap
│   ├── security.py         # CSRF, auth decorators, login throttle, headers
│   ├── services.py         # SLA rules, search, notifications, analytics
│   ├── validators.py       # form validation
│   ├── utils.py            # time, pagination, upload sniffing helpers
│   ├── icons.py            # inline SVG icon set
│   ├── auth.py             # register, login, logout
│   ├── tickets.py          # create, list, detail, comment, update, cancel, rate
│   ├── admin.py            # overview, triage list, CSV export, users, reports
│   ├── main.py             # landing, notifications, profile, protected uploads
│   ├── api.py              # JSON endpoints
│   ├── templates/          # Jinja2 pages (public, app shell, admin)
│   └── static/             # css/style.css, js/app.js, js/charts.js, favicon
├── tests/test_app.py       # 31 end-to-end and unit tests
├── docs/                   # README screenshots
└── uploads/                # request photos (git-ignored)
```

## JSON endpoints

| Endpoint | Who | Returns |
| --- | --- | --- |
| `GET /api/admin/stats` | Administrators | Key figures, 14-day trend, status and category counts |
| `GET /api/notifications/unread` | Signed-in users | `{ "count": n }` |

## Running the tests

```bash
python -m unittest -v
```

The tests use a temporary database and cover registration, login throttling, permissions, uploads, the full assign / resolve / rate workflow, filters and pagination, CSV export, user management and the JSON API.

## Deploying

The built-in server is for development. For a real deployment use a production server such as Waitress (works on Windows): `pip install waitress`, then `waitress-serve --port=8000 app:app`. Set `SECRET_KEY`, `ADMIN_PASSWORD` and `SESSION_COOKIE_SECURE=1` (behind HTTPS) first. The login throttle keeps its counters in memory, so run a single worker process.

## Ideas for next steps

- Email or SMS alerts alongside in-app notifications
- Scheduled reminders for requests that are about to breach their deadline
- QR codes on classroom doors that open the request form with the room pre-filled
- Postgres or MySQL support for larger campuses

## License

MIT, see [LICENSE](LICENSE).


## 2.0 Experience Upgrade

This version keeps the original Flask/SQLite architecture and adds a more useful application layer:

- Personalized student/staff dashboard with live request KPIs.
- Recent-request cards and quick actions.
- Responsive mobile-first dashboard layout.
- Persistent light/dark theme toggle.
- Command palette with `Ctrl+K` / `Cmd+K`.
- Keyboard shortcuts: `N` new request, `M` my requests, `B` notifications, `P` profile.
- Progressive Web App manifest and a small offline shell cache.
- Improved focus states, reduced-motion support, hover feedback and touch targets.
- More efficient lazy image loading and external-link hardening.
- Existing authentication, CSRF protection, request lifecycle, technician workflow,
  admin reporting, CSV export and protected uploads are retained.

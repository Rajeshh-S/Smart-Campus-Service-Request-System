# Smart Campus Service Desk — Experience Upgrade

## What changed

### User experience
- Added a personalized `/home` dashboard for student/staff accounts.
- Added live summary cards for open, resolved, overdue and feedback-needed requests.
- Added recent request cards with direct ticket navigation.
- Added quick actions and a campus guidance panel.
- Added responsive layouts for phones, tablets and desktop screens.

### Productivity
- Added a command palette opened with `Ctrl+K` / `Cmd+K`.
- Added keyboard shortcuts: `N`, `M`, `B`, and `P` when not typing.
- Added persistent light/dark mode using local browser storage.
- Added lazy loading for images.
- Added a small PWA manifest and offline shell service worker.

### Engineering
- Kept the existing Flask + SQLite architecture.
- Kept existing authentication, CSRF, roles, ticket lifecycle, notifications,
  admin reporting, CSV export and protected uploads.
- Added `services.user_dashboard()` as a focused data-access layer for the new dashboard.
- Added a dashboard regression test.
- No external JavaScript chart dependency was introduced.

## Validation

Python source files compile successfully and all template icon references resolve.
The full test suite should be run after installing the project's requirements:

```bash
python -m pip install -r requirements.txt
python -m unittest discover -v
```

"""Small, dependency-free helpers shared across the application."""
import math
from datetime import datetime
from urllib.parse import urlsplit

TS_FORMAT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------- date / time
def now():
    return datetime.now().replace(microsecond=0)


def now_str():
    return now().strftime(TS_FORMAT)


def parse_ts(value):
    """Parse a stored timestamp into a datetime (or None)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in (TS_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fmt_date(value):
    ts = parse_ts(value)
    return ts.strftime("%d %b %Y") if ts else ""


def fmt_datetime(value):
    ts = parse_ts(value)
    return ts.strftime("%d %b %Y, %H:%M") if ts else ""


def time_ago(value):
    """'5 min ago', '3 h ago', '2 days ago', or a date for anything older."""
    ts = parse_ts(value)
    if ts is None:
        return ""
    seconds = int((now() - ts).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    if seconds < 7 * 86400:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''} ago"
    return ts.strftime("%d %b %Y")


def humanize_seconds(seconds):
    """Compact duration text: '25 min', '6 h', '3 days'."""
    seconds = abs(int(seconds))
    if seconds < 3600:
        return f"{max(seconds // 60, 1)} min"
    if seconds < 2 * 86400:
        return f"{seconds // 3600} h"
    return f"{seconds // 86400} days"


def hours_label(hours):
    """Turn a number of hours into friendly text: 4 -> '4 hours', 24 -> '1 day'."""
    hours = int(hours)
    if hours % 24 == 0:
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''}"
    return f"{hours} hour{'s' if hours != 1 else ''}"


def initials(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# ------------------------------------------------------------------ text/urls
def like_escape(text):
    """Escape SQL LIKE wildcards (use together with ESCAPE '\\')."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def csv_safe(value):
    """Neutralise spreadsheet formula injection in exported CSV cells."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def is_safe_redirect(target):
    """Only allow same-site relative redirects such as '/requests/4'."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc


def sniff_image(head):
    """Identify an image by its magic bytes. Returns an extension or None."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpg"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


# ----------------------------------------------------------------- pagination
class Page:
    """A slice of results plus everything a template needs to draw a pager."""

    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, math.ceil(total / per_page))

    @property
    def start(self):
        return 0 if self.total == 0 else (self.page - 1) * self.per_page + 1

    @property
    def end(self):
        return min(self.page * self.per_page, self.total)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def clamp_page(raw, default=1):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, 100000))

"""Urgency: how soon is something due, and where does it belong in the paper?

    < 24h until due  -> "breaking"  (ticker + red headline)
    < 48h            -> "banner"    (front-page banner)
    < 7 days         -> "front"     (front page)
    otherwise        -> "archive"   (archive only: past, undated, or far off)

A date-only value (``2026-10-20``) is treated as due at the *end* of that day
(23:59:59) in the class time zone (``CLASSROOM_TZ`` env var, default UTC).
Pure and deterministic: no network, no model.
"""
from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

URGENCY_LEVELS = ("breaking", "banner", "front", "archive")
BREAKING_WINDOW = timedelta(hours=24)
BANNER_WINDOW = timedelta(hours=48)
FRONT_WINDOW = timedelta(days=7)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%b %d %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%B %d, %Y",
    "%d %b %Y",
    "%d %B %Y",
)


def get_timezone() -> tzinfo:
    name = os.environ.get("CLASSROOM_TZ", "UTC")
    try:
        return ZoneInfo(name)
    except Exception:  # unknown zone name -> UTC rather than crash the build
        return timezone.utc


def parse_date(value) -> date | None:
    """Parse a front-matter date (date object or common string formats)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def parse_due(value, tz: tzinfo | None = None) -> datetime | None:
    """Return an aware datetime for when something is due (or None)."""
    tz = tz or get_timezone()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=tz)
    if isinstance(value, str) and "T" in value:
        try:
            dt = datetime.fromisoformat(value.strip())
            return dt if dt.tzinfo else dt.replace(tzinfo=tz)
        except ValueError:
            pass
    d = parse_date(value)
    if d is None:
        return None
    return datetime.combine(d, time(23, 59, 59), tzinfo=tz)


def compute_urgency(due, now: datetime | None = None) -> str:
    """Map a due date/datetime to an urgency level. Undated or past -> archive."""
    tz = get_timezone()
    due_dt = parse_due(due, tz)
    if due_dt is None:
        return "archive"
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=tz)

    remaining = due_dt - now
    if remaining <= timedelta(0):
        return "archive"
    if remaining < BREAKING_WINDOW:
        return "breaking"
    if remaining < BANNER_WINDOW:
        return "banner"
    if remaining < FRONT_WINDOW:
        return "front"
    return "archive"

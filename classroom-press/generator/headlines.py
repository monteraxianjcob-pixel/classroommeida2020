"""Deterministic headline + subhead templates: the floor of the pipeline.

Zero model dependency, zero network. Template choice is "random but seeded":
the seed is an md5 of the article's identity, so the same article always gets
the same headline on every run and every machine.

Every headline produced here is ALL CAPS, quote-free, and <= 60 characters.
"""
from __future__ import annotations

import hashlib
import random
import re

from generator.urgency import parse_date

MAX_HEADLINE = 60
MAX_SUBHEAD = 110
CATEGORIES = ("exam", "deadline", "event", "academics", "sports", "general")

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_QUOTE_CHARS = "\"'`\u201c\u201d\u2018\u2019\u00ab\u00bb"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


# ── small helpers (shared with headline_gen.py) ─────────────────────────────
def squash(value) -> str:
    """Collapse whitespace/newlines, drop the '|' prompt delimiter."""
    text = "" if value is None else str(value)
    text = text.replace("|", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_quotes(text: str) -> str:
    return "".join(ch for ch in text if ch not in _QUOTE_CHARS)


def normalize_category(value) -> str:
    cat = squash(value).lower()
    return cat if cat in CATEGORIES else "general"


def format_date_short(value) -> str:
    """'2026-10-20' -> 'Oct 20'. Unparseable text is passed through cleaned."""
    d = parse_date(value)
    if d is not None:
        return f"{_MONTHS[d.month - 1]} {d.day}"
    return squash(value)


# ── headline templates ──────────────────────────────────────────────────────
# {subj} falls back to "CLASS"; templates needing a missing {loc} are skipped.
# "floor" templates are short and always fit; used only if nothing else does.
TEMPLATES: dict[str, dict] = {
    "exam": {
        "dated": [
            "{subj} EXAM SET FOR {date}",
            "{subj} TEST SCHEDULED FOR {date}",
            "STUDENTS TO SIT {subj} EXAM ON {date}",
            "{date} MARKED AS {subj} EXAM DAY",
            "{loc} TO HOST {subj} EXAM ON {date}",
        ],
        "undated": [
            "{subj} EXAM ANNOUNCED",
            "{subj} EXAM NOTICE POSTED",
            "{loc} TO HOST {subj} EXAM",
        ],
        "floor": {"dated": "EXAM SET FOR {date}", "undated": "EXAM NOTICE POSTED"},
    },
    "deadline": {
        "dated": [
            "{subj} WORK DUE {date}",
            "{subj} DEADLINE SET FOR {date}",
            "SUBMIT {subj} WORK BY {date}",
            "{date} DEADLINE LOOMS FOR {subj}",
        ],
        "undated": [
            "{subj} DEADLINE ANNOUNCED",
            "{subj} SUBMISSION NOTICE POSTED",
        ],
        "floor": {"dated": "DEADLINE SET FOR {date}", "undated": "DEADLINE NOTICE POSTED"},
    },
    "event": {
        "dated": [
            "{title} SET FOR {date}",
            "{title} PLANNED FOR {date}",
            "CLASS EVENT CONFIRMED FOR {date}",
            "{loc} TO HOST EVENT ON {date}",
        ],
        "undated": [
            "{title}",
            "CLASS EVENT ANNOUNCED",
            "{loc} TO HOST CLASS EVENT",
        ],
        "floor": {"dated": "EVENT SET FOR {date}", "undated": "EVENT NOTICE POSTED"},
    },
    "academics": {
        "dated": [
            "{subj} ACADEMIC NOTICE FOR {date}",
            "{subj} CLASS UPDATE FOR {date}",
            "{title} IN FOCUS FOR {date}",
        ],
        "undated": [
            "{subj} CLASS UPDATE POSTED",
            "{title}",
            "{subj} ACADEMIC NOTICE POSTED",
        ],
        "floor": {"dated": "ACADEMIC NOTICE FOR {date}", "undated": "ACADEMIC NOTICE POSTED"},
    },
    "sports": {
        "dated": [
            "{title} SLATED FOR {date}",
            "{subj} MATCH SET FOR {date}",
            "{loc} TO HOST GAME ON {date}",
            "{subj} SPORTS UPDATE FOR {date}",
        ],
        "undated": [
            "{title}",
            "{subj} SPORTS UPDATE POSTED",
        ],
        "floor": {"dated": "SPORTS UPDATE FOR {date}", "undated": "SPORTS NOTICE POSTED"},
    },
    "general": {
        "dated": [
            "{title} NOTICE FOR {date}",
            "CLASS NOTICE ISSUED FOR {date}",
            "{subj} NOTICE POSTED FOR {date}",
        ],
        "undated": [
            "{title}",
            "{subj} NOTICE POSTED",
        ],
        "floor": {"dated": "CLASS NOTICE FOR {date}", "undated": "CLASS NOTICE POSTED"},
    },
}


def _seed(fm: dict, salt: str = "") -> int:
    key = "|".join([
        normalize_category(fm.get("category")),
        squash(fm.get("title")),
        squash(fm.get("date")),
        salt,
    ])
    return int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)


def _vars(fm: dict) -> dict[str, str]:
    def up(v) -> str:
        return strip_quotes(squash(v)).upper()

    return {
        "subj": up(fm.get("subject")) or "CLASS",
        "title": up(fm.get("title")),
        "loc": up(fm.get("location")),
        "date": up(format_date_short(fm.get("date"))),
    }


def _render(template: str, values: dict[str, str]) -> str | None:
    """Fill a template; None if any placeholder has no value."""
    for name in _PLACEHOLDER.findall(template):
        if not values.get(name):
            return None
    return template.format_map(values)


def fallback_headline(fm: dict) -> str:
    """Deterministic headline from a front-matter dict (no model, no network)."""
    cat = normalize_category(fm.get("category"))
    spec = TEMPLATES[cat]
    values = _vars(fm)
    mode = "dated" if values["date"] else "undated"

    fits = []
    for template in spec[mode]:
        text = _render(template, values)
        if text and len(text) <= MAX_HEADLINE:
            fits.append(text)

    if fits:
        return random.Random(_seed(fm)).choice(fits)

    floor = _render(spec["floor"][mode], values) or "CLASS NOTICE POSTED"
    return floor[:MAX_HEADLINE].rstrip()


# ── subhead (deterministic) ─────────────────────────────────────────────────
_DEFAULT_SUBHEADS = {
    "exam": "Students should review the details below.",
    "deadline": "Read the details below before handing in work.",
    "event": "Details for the class are below.",
    "academics": "The latest class update is below.",
    "sports": "Details for the team and class are below.",
    "general": "Details for the class are below.",
}


def _sentence(prefix: str, value: str) -> str:
    value = squash(value).rstrip(".!?;: ")
    return f"{prefix} {value}." if value else ""


def fallback_subhead(fm: dict) -> str:
    """One short, factual sentence assembled only from authored fields."""
    pieces = [
        _sentence("Covers", fm.get("scope")),
        _sentence("Required:", fm.get("requirement")),
        _sentence("Takes place in", fm.get("location")),
        _sentence("Note:", fm.get("restriction")),
    ]
    out = ""
    for piece in pieces:
        if not piece:
            continue
        candidate = f"{out} {piece}".strip()
        if len(candidate) <= MAX_SUBHEAD:
            out = candidate
    return out or _DEFAULT_SUBHEADS[normalize_category(fm.get("category"))]

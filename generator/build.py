"""build.py: content/*.md  ->  web/public/data/{articles,sections,editions}.json

No model calls here. Everything is deterministic given (content, now, state).

    python generator/build.py                      # normal build (bumps edition)
    python generator/build.py --no-increment       # local preview, edition unchanged
    python generator/build.py --now 2026-10-12T09:00:00   # pin the clock
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):  # allow `python generator/build.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from generator.headlines import CATEGORIES, normalize_category, squash
from generator.photos import assign_photo
from generator.urgency import compute_urgency, get_timezone, parse_date, parse_due

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = REPO_ROOT / "content"
STATIC_DIR = REPO_ROOT / "static"
OUT_DIR = REPO_ROOT / "web" / "public" / "data"
PUBLIC_PHOTOS = REPO_ROOT / "web" / "public" / "photos"
STATE_PATH = REPO_ROOT / "generator" / "state.json"

SECTION_META = {
    "exam": ("Exams", "Tests and assessments on the calendar."),
    "deadline": ("Deadlines", "Work that has to be handed in."),
    "event": ("Events", "Trips, shows and gatherings."),
    "academics": ("Academics", "Lessons, schedules and class news."),
    "sports": ("Sports", "Matches, results and team notices."),
    "general": ("General", "Everything else worth knowing."),
}

_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n(.*))?\Z", re.DOTALL)


# ── slugs ───────────────────────────────────────────────────────────────────
def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > max_len:
        text = text[:max_len].rsplit("-", 1)[0] or text[:max_len]
    return text or "untitled"


def unique_slug(base: str, taken: set[str]) -> str:
    slug, n = base, 2
    while slug in taken:
        slug = f"{base}-{n}"
        n += 1
    return slug


# ── reading content ─────────────────────────────────────────────────────────
def parse_markdown(text: str) -> tuple[dict, str]:
    """Split YAML front matter from the markdown body."""
    match = _FRONT_MATTER.match(text.lstrip("\ufeff"))
    if not match:
        return {}, text.strip()
    data = yaml.safe_load(match.group(1)) or {}
    if not isinstance(data, dict):
        raise ValueError("front matter must be a YAML mapping")
    return data, (match.group(2) or "").strip()


def _opt(value) -> str | None:
    text = squash(value)
    return text or None


def build_article(fm: dict, body: str, slug: str, now: datetime, photo_root: Path) -> dict:
    """One JSON article. Authored fields are copied, never rewritten."""
    due = parse_due(fm.get("date"))
    d = parse_date(fm.get("date"))
    pinned = bool(fm.get("pinned", False))
    urgency = compute_urgency(due, now)
    if pinned and urgency == "archive":
        urgency = "front"  # pinned notices stay on the front page

    issue = fm.get("issue_number")
    category = normalize_category(fm.get("category"))
    photo = assign_photo({**fm, "category": category}, slug, photo_root)

    return {
        "slug": slug,
        "title": str(fm.get("title") or slug),
        "headline": _opt(fm.get("headline")),   # model/template output, or null
        "subhead": _opt(fm.get("subhead")),
        "category": category,
        "subject": _opt(fm.get("subject")),
        "date": d.isoformat() if d else None,
        "author": _opt(fm.get("author")),
        "location": _opt(fm.get("location")),
        "body": body,
        "photo": photo["photo"],
        "photo_caption": photo["photo_caption"],
        "photo_credit": photo["photo_credit"],
        "urgency": urgency,
        "pinned": pinned,
        "issue_number": int(issue) if str(issue or "").isdigit() else None,
        # Extras beyond the base schema (used by the frontend):
        "due_at": due.isoformat() if due else None,
        "scope": _opt(fm.get("scope")),
        "requirement": _opt(fm.get("requirement")),
        "restriction": _opt(fm.get("restriction")),
    }


def load_articles(content_dir: Path, now: datetime, photo_root: Path) -> list[dict]:
    articles, taken = [], set()
    for path in sorted(Path(content_dir).glob("*.md")):
        fm, body = parse_markdown(path.read_text(encoding="utf-8"))
        if not fm.get("title"):
            print(f"warning: {path.name} has no title; skipped", file=sys.stderr)
            continue
        if fm.get("date") and parse_date(fm["date"]) is None:
            print(f"warning: {path.name}: unparseable date {fm['date']!r}; treated as undated",
                  file=sys.stderr)
        slug = unique_slug(str(fm.get("slug") or slugify(fm["title"])), taken)
        taken.add(slug)
        articles.append(build_article(fm, body, slug, now, photo_root))
    return sort_articles(articles)


def sort_articles(articles: list[dict]) -> list[dict]:
    """Newest due date first; undated last; slug breaks ties (stable output)."""
    dated = sorted(
        (a for a in articles if a["date"]), key=lambda a: (a["date"], a["slug"]), reverse=True
    )
    undated = sorted((a for a in articles if not a["date"]), key=lambda a: a["slug"])
    return dated + undated


def group_by_category(articles: list[dict]) -> dict[str, list[dict]]:
    groups = {cat: [] for cat in CATEGORIES}
    for article in articles:
        groups[article["category"]].append(article)
    return groups


# ── edition counter ─────────────────────────────────────────────────────────
def next_edition(state_path: Path, now: datetime, increment: bool = True) -> dict:
    """Read (and by default bump + persist) the edition state file."""
    path = Path(state_path)
    state = {"volume": 1, "edition": 0, "history": []}
    if path.is_file():
        state.update(json.loads(path.read_text(encoding="utf-8")))
    if increment:
        state["edition"] = int(state["edition"]) + 1
        state["history"] = (state.get("history", []) + [
            {"number": state["edition"], "date": now.date().isoformat()}
        ])[-100:]
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


# ── emit ────────────────────────────────────────────────────────────────────
def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build(
    content_dir: Path = CONTENT_DIR,
    static_dir: Path = STATIC_DIR,
    out_dir: Path = OUT_DIR,
    public_photos: Path | None = PUBLIC_PHOTOS,
    state_path: Path = STATE_PATH,
    now: datetime | None = None,
    increment: bool = True,
) -> dict:
    now = now or datetime.now(get_timezone())
    photo_root = Path(static_dir) / "photos"

    articles = load_articles(content_dir, now, photo_root)
    groups = group_by_category(articles)
    state = next_edition(state_path, now, increment)

    articles_doc = {
        "edition": state["edition"],
        "generated_at": now.isoformat(timespec="seconds"),
        "articles": articles,
    }
    sections_doc = [
        {
            "slug": cat,
            "label": SECTION_META[cat][0],
            "description": SECTION_META[cat][1],
            "count": len(groups[cat]),
            "slugs": [a["slug"] for a in groups[cat]],
        }
        for cat in CATEGORIES
    ]
    editions_doc = {
        "volume": state["volume"],
        "current": state["edition"],
        "editions": state["history"],
    }

    out_dir = Path(out_dir)
    _write_json(out_dir / "articles.json", articles_doc)
    _write_json(out_dir / "sections.json", sections_doc)
    _write_json(out_dir / "editions.json", editions_doc)

    if public_photos and photo_root.is_dir():
        shutil.copytree(photo_root, public_photos, dirs_exist_ok=True)

    return articles_doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--now", help="ISO datetime to use instead of the clock")
    ap.add_argument("--no-increment", action="store_true", help="do not bump the edition")
    args = ap.parse_args(argv)

    now = None
    if args.now:
        now = datetime.fromisoformat(args.now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=get_timezone())

    doc = build(now=now, increment=not args.no_increment)
    print(f"Edition {doc['edition']}: {len(doc['articles'])} article(s) written to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

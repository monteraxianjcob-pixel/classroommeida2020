"""Photo assignment: deterministic, hash-based, with natural captions.

static/photos/{category}/ holds press photos. An article gets one by hashing
its slug with md5 (stable across runs and machines, unlike Python's hash()).
If the category folder is empty, static/photos/default.* is used.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from generator.headlines import normalize_category, squash

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTO_ROOT = REPO_ROOT / "static" / "photos"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".svg"}
DEFAULT_STEM = "default"
DEFAULT_CREDIT = "Classroom Press archive"

# Category -> folder under static/photos/ (kept explicit so it can be remapped).
CATEGORY_DIRS = {
    "exam": "exam",
    "deadline": "deadline",
    "event": "event",
    "academics": "academics",
    "sports": "sports",
    "general": "general",
}

# Captions: {loc} is the location, {subj} the subject (either may be blank;
# whitespace is collapsed afterwards).
_CAPTIONS = {
    "exam": {
        "loc": ["{loc}, where the {subj} exam will be held.",
                "Desks in {loc} await the {subj} exam."],
        "noloc": ["A classroom set up for the {subj} exam.",
                  "Desks lined up ahead of the {subj} exam."],
    },
    "deadline": {
        "loc": ["{loc}, where {subj} work is handed in.",
                "Students hand in {subj} work in {loc}."],
        "noloc": ["Assignments wait to be collected for {subj}.",
                  "Pages and projects pile up as the {subj} deadline nears."],
    },
    "event": {
        "loc": ["{loc}, the setting for the event.",
                "The scene at {loc}, ahead of the event."],
        "noloc": ["Preparations get under way for the class event.",
                  "The class gathers ahead of the event."],
    },
    "academics": {
        "loc": ["{loc}, where {subj} lessons take place.",
                "A {subj} lesson in progress in {loc}."],
        "noloc": ["A {subj} lesson in progress.",
                  "Books and notes from the {subj} classroom."],
    },
    "sports": {
        "loc": ["{loc}, where the {subj} action will unfold.",
                "Players prepare at {loc}."],
        "noloc": ["The class prepares for the {subj} match.",
                  "Teams warm up before play."],
    },
    "general": {
        "loc": ["{loc}, as seen from the classroom.",
                "A view of {loc}."],
        "noloc": ["A view from around the classroom.",
                  "Notes and news from the classroom."],
    },
}


def _digest(text: str) -> int:
    return int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)


def list_photos(category: str, photo_root: Path | None = None) -> list[str]:
    root = Path(photo_root or PHOTO_ROOT)
    folder = root / CATEGORY_DIRS.get(normalize_category(category), "general")
    if not folder.is_dir():
        return []
    return sorted(
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS
    )


def _default_photo(photo_root: Path) -> str | None:
    for path in sorted(photo_root.glob(f"{DEFAULT_STEM}.*")):
        if path.suffix.lower() in IMAGE_EXTS:
            return f"/photos/{path.name}"
    return None


def pick_photo(slug: str, category: str, photo_root: Path | None = None) -> str | None:
    """Web path (e.g. /photos/exam/exam-2.jpg) chosen by md5(slug)."""
    root = Path(photo_root or PHOTO_ROOT)
    cat = normalize_category(category)
    files = list_photos(cat, root)
    if not files:
        return _default_photo(root)
    chosen = files[_digest(slug) % len(files)]
    return f"/photos/{CATEGORY_DIRS[cat]}/{chosen}"


def make_caption(fm: dict, slug: str) -> str:
    cat = normalize_category(fm.get("category"))
    loc = squash(fm.get("location"))
    subj = squash(fm.get("subject"))
    options = _CAPTIONS[cat]["loc" if loc else "noloc"]
    template = options[_digest(slug + "|caption") % len(options)]
    text = template.format(loc=loc, subj=subj)
    text = re.sub(r"\s+", " ", text).replace(" .", ".").strip()
    return text[0].upper() + text[1:]


def _credit_for(photo: str | None, photo_root: Path) -> str:
    """Optional static/photos/{category}/credits.json: {"file.jpg": "Credit"}."""
    if not photo:
        return DEFAULT_CREDIT
    parts = photo.strip("/").split("/")  # photos/<cat>/<file> or photos/<file>
    folder = photo_root.joinpath(*parts[1:-1])
    credits = folder / "credits.json"
    if credits.is_file():
        try:
            mapping = json.loads(credits.read_text(encoding="utf-8"))
            if parts[-1] in mapping:
                return str(mapping[parts[-1]])
        except (OSError, ValueError):
            pass
    return DEFAULT_CREDIT


def assign_photo(fm: dict, slug: str, photo_root: Path | None = None) -> dict:
    """Return {photo, photo_caption, photo_credit}. Authored values win."""
    root = Path(photo_root or PHOTO_ROOT)
    photo = fm.get("photo") or pick_photo(slug, fm.get("category"), root)
    return {
        "photo": photo,
        "photo_caption": (squash(fm.get("photo_caption")) or make_caption(fm, slug))
        if photo else None,
        "photo_credit": (squash(fm.get("photo_credit")) or _credit_for(photo, root))
        if photo else None,
    }

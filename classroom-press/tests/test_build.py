import json
from datetime import datetime, timezone

from generator import build as B
from generator.urgency import compute_urgency

NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def write(dirpath, name, front, body="Body text."):
    lines = ["---"] + [f"{k}: {v}" for k, v in front.items()] + ["---", "", body, ""]
    (dirpath / name).write_text("\n".join(lines), encoding="utf-8")


# ── slugs ──────────────────────────────────────────────────────────────────
def test_slugify_basic_and_unicode():
    assert B.slugify("Math Test: Chapters 1-4!") == "math-test-chapters-1-4"
    assert B.slugify("Café Day") == "cafe-day"
    assert B.slugify("   ") == "untitled"
    assert len(B.slugify("word " * 40)) <= 60


def test_unique_slug_dedupes():
    taken = {"field-trip", "field-trip-2"}
    assert B.unique_slug("field-trip", taken) == "field-trip-3"
    assert B.unique_slug("new", taken) == "new"


# ── urgency assignment ─────────────────────────────────────────────────────
def test_urgency_thresholds():
    # date-only values are due at 23:59:59 that day
    assert compute_urgency("2026-10-12", NOW) == "breaking"   # ~15h
    assert compute_urgency("2026-10-13", NOW) == "banner"     # ~39h
    assert compute_urgency("2026-10-16", NOW) == "front"      # ~4.6d
    assert compute_urgency("2026-10-20", NOW) == "archive"    # >7d
    assert compute_urgency("2026-10-01", NOW) == "archive"    # past
    assert compute_urgency(None, NOW) == "archive"            # undated


def test_urgency_boundaries_use_exact_hours():
    due = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
    assert compute_urgency(due, NOW.replace(hour=9, minute=0, second=1)) == "breaking"
    assert compute_urgency(due, datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)) == "banner"  # exactly 24h


def test_pinned_undated_goes_to_front(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    write(content, "a.md", {"title": "Pinned notice", "category": "general", "pinned": "true"})
    arts = B.load_articles(content, NOW, tmp_path / "photos")
    assert arts[0]["urgency"] == "front" and arts[0]["pinned"] is True


# ── sorting ────────────────────────────────────────────────────────────────
def test_sorting_newest_first_undated_last(tmp_path):
    content = tmp_path / "content"
    content.mkdir()
    write(content, "a.md", {"title": "Old", "category": "exam", "date": "'2026-10-01'"})
    write(content, "b.md", {"title": "New", "category": "exam", "date": "'2026-10-20'"})
    write(content, "c.md", {"title": "Undated", "category": "general"})
    write(content, "d.md", {"title": "Mid", "category": "exam", "date": "'2026-10-10'"})
    arts = B.load_articles(content, NOW, tmp_path / "photos")
    assert [a["slug"] for a in arts] == ["new", "mid", "old", "undated"]


# ── edition counter ────────────────────────────────────────────────────────
def test_edition_increments_and_persists(tmp_path):
    state = tmp_path / "state.json"
    assert B.next_edition(state, NOW)["edition"] == 1
    assert B.next_edition(state, NOW)["edition"] == 2
    assert json.loads(state.read_text())["edition"] == 2
    # preview mode does not bump
    assert B.next_edition(state, NOW, increment=False)["edition"] == 2
    assert json.loads(state.read_text())["edition"] == 2


# ── end to end ─────────────────────────────────────────────────────────────
def test_build_emits_three_json_files_and_keeps_authored_text(tmp_path):
    content, out = tmp_path / "content", tmp_path / "out"
    content.mkdir()
    write(content, "a.md",
          {"title": "Summative test", "category": "exam", "subject": "Math",
           "date": "'2026-10-13'", "headline": "MATH TEST SET FOR OCT 13",
           "issue_number": 7},
          body="Original **body**.")
    write(content, "b.md", {"title": "No headline yet", "category": "event", "date": "'2026-10-16'"})
    doc = B.build(content, tmp_path / "static", out, None, tmp_path / "state.json", NOW)

    assert doc["edition"] == 1
    assert set(json.loads((out / "articles.json").read_text())) == {"edition", "generated_at", "articles"}
    sections = json.loads((out / "sections.json").read_text())
    assert [s["slug"] for s in sections] == list(B.CATEGORIES)
    assert next(s for s in sections if s["slug"] == "exam")["count"] == 1
    editions = json.loads((out / "editions.json").read_text())
    assert editions["current"] == 1 and editions["editions"][0]["number"] == 1

    by_slug = {a["slug"]: a for a in doc["articles"]}
    assert by_slug["summative-test"]["headline"] == "MATH TEST SET FOR OCT 13"
    assert by_slug["summative-test"]["body"] == "Original **body**."
    assert by_slug["summative-test"]["issue_number"] == 7
    assert by_slug["no-headline-yet"]["headline"] is None  # build never invents one
    for key in ("slug", "title", "headline", "subhead", "category", "subject", "date",
                "author", "location", "body", "photo", "photo_caption", "photo_credit",
                "urgency", "pinned", "issue_number"):
        assert key in by_slug["summative-test"]


def test_parse_markdown_without_front_matter():
    fm, body = B.parse_markdown("Just text")
    assert fm == {} and body == "Just text"

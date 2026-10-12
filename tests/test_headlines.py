import pytest

from generator.headline_gen import HeadlineInput, validate_headline
from generator.headlines import (
    CATEGORIES, MAX_HEADLINE, MAX_SUBHEAD, fallback_headline, fallback_subhead,
    format_date_short,
)

FULL = {"title": "Summative test", "subject": "Math", "date": "2026-10-20",
        "location": "Room 204", "scope": "chapters 1-4", "requirement": "Bring a calculator"}
MINIMAL = {"title": "Something happened"}
LONG = {"title": "An extremely long announcement title that goes on and on and on forever",
        "subject": "Interdisciplinary Studies And Applied Humanities",
        "location": "The Far Western Annex Behind The Gymnasium Building",
        "date": "2026-12-01"}
QUOTEY = {"title": 'The "big" O\'Brien event', "subject": "Mr. O'Brien's class",
          "location": "Room \"7\"", "date": "2026-11-05"}


@pytest.mark.parametrize("category", CATEGORIES)
@pytest.mark.parametrize("fm", [FULL, MINIMAL, LONG, QUOTEY], ids=["full", "minimal", "long", "quotes"])
def test_every_category_respects_rules(category, fm):
    headline = fallback_headline({**fm, "category": category})
    assert 0 < len(headline) <= MAX_HEADLINE
    assert headline == headline.upper()
    assert not any(ch in headline for ch in "\"'`\u201c\u201d\u2018\u2019")


@pytest.mark.parametrize("category", CATEGORIES)
def test_fallback_passes_the_same_validator_as_the_model(category):
    fm = {**FULL, "category": category}
    ok, reason = validate_headline(fallback_headline(fm), HeadlineInput.from_front_matter(fm))
    assert ok, reason


def test_deterministic_across_calls():
    fm = {**FULL, "category": "exam"}
    assert len({fallback_headline(fm) for _ in range(20)}) == 1


def test_unknown_category_uses_general():
    assert fallback_headline({**FULL, "category": "nonsense"})


def test_no_digits_invented():
    headline = fallback_headline({**FULL, "category": "exam"})
    assert set(c for c in headline if c.isdigit()) <= set("20")


def test_date_formatting():
    assert format_date_short("2026-10-20") == "Oct 20"
    assert format_date_short("Nov 5, 2026") == "Nov 5"
    assert format_date_short("sometime soon") == "sometime soon"


def test_subhead_is_short_and_factual():
    sub = fallback_subhead({**FULL, "category": "exam"})
    assert len(sub) <= MAX_SUBHEAD
    assert "chapters 1-4" in sub
    assert fallback_subhead({"category": "sports", "title": "x"})  # default sentence


def test_every_dated_template_keeps_the_date():
    from generator.headlines import TEMPLATES
    for cat, spec in TEMPLATES.items():
        for template in spec["dated"] + [spec["floor"]["dated"]]:
            assert "{date}" in template, (cat, template)

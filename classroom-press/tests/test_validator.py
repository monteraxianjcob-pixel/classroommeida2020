import pytest

from generator import headline_gen as H
from generator.headline_gen import HeadlineInput, validate_headline, validate_subhead

INP = HeadlineInput(title="Summative test", subject="Math", date="Oct 20", scope="chapters 1-4")


def check(text, inp=INP):
    return validate_headline(text, inp)


def test_happy_path_spec_example():
    ok, reason = check("SUMMATIVE TEST SET FOR MATH, OCT 20")
    assert ok and reason == "ok"


def test_may_omit_scope_numbers():
    # scope digits (1-4) are allowed, not required
    assert check("MATH TEST ON OCT 20")[0]


def test_too_long():
    ok, reason = check("SUMMATIVE TEST FOR MATH IS SET FOR OCT 20 AND STUDENTS SHOULD PREPARE NOW")
    assert not ok and "too long" in reason


def test_exactly_60_is_ok_61_is_not():
    base = "MATH TEST OCT 20 " + "A" * 43          # 17 + 43 = 60
    assert len(base) == 60 and check(base)[0]
    assert not check(base + "A")[0]


@pytest.mark.parametrize("text", ["Summative test set for math, Oct 20", "SUMMATIVE test OCT 20"])
def test_not_uppercase(text):
    ok, reason = check(text)
    assert not ok and "CAPS" in reason


@pytest.mark.parametrize("text", ['"MATH TEST" ON OCT 20', "MATH TEST ON OCT 20'",
                                  "\u201cMATH TEST ON OCT 20\u201d", "TEACHER'S TEST OCT 20"])
def test_contains_quotes(text):
    ok, reason = check(text)
    assert not ok and "quote" in reason


def test_invented_number():
    ok, reason = check("MATH TEST SET FOR OCT 20 WITH 15 QUESTIONS")
    assert not ok and "invented" in reason and "15" in reason


def test_numbers_are_whole_tokens_not_digits():
    # "12" is built from digits that exist in the input (1, 2) but is not in the input
    assert not check("MATH TEST OCT 20, ROOM 12")[0]


def test_dropped_date():
    ok, reason = check("SUMMATIVE TEST SET FOR MATH")
    assert not ok and "dropped" in reason and "20" in reason


def test_wrong_date_is_rejected():
    assert not check("SUMMATIVE TEST SET FOR MATH, OCT 21")[0]


def test_title_digits_are_required():
    inp = HeadlineInput(title="Chapter 3 quiz", subject="Math", date="n/a", scope="n/a")
    assert not validate_headline("MATH QUIZ ANNOUNCED", inp)[0]
    assert validate_headline("MATH CHAPTER 3 QUIZ ANNOUNCED", inp)[0]


@pytest.mark.parametrize("text", ["", "   ", "MATH TEST\nOCT 20", "123"])
def test_empty_multiline_or_no_letters(text):
    assert not check(text)[0]


# ── subhead validator ───────────────────────────────────────────────────────
def test_subhead_rules():
    src = "MATH TEST Subject: Math; Date: Oct 20; Scope: chapters 1-4"
    assert validate_subhead("Covers chapters 1-4 in the Math unit.", src)[0]
    assert not validate_subhead("COVERS CHAPTERS 1-4.", src)[0]
    assert not validate_subhead("Covers chapters 1-9.", src)[0]
    assert not validate_subhead('Covers "chapters" 1-4.', src)[0]
    assert not validate_subhead("x" * 111, src)[0]


# ── generate_headline: model path, rejection path, failure path ─────────────
FM = {"category": "exam", "title": "Summative test", "subject": "Math",
      "date": "2026-10-20", "scope": "chapters 1-4"}


def test_prompt_is_verbatim_and_filled():
    user = INP.user_prompt()
    assert user.rstrip().endswith("Input: Summative test | Math | Oct 20 | chapters 1-4\nOutput:")
    assert "Maximum 60 characters" in user
    assert H.SYSTEM_PROMPT.startswith("You are a newspaper copy editor.")


def test_model_output_used_when_valid():
    seen = {}

    def caller(system, user):
        seen["system"], seen["user"] = system, user
        return "SUMMATIVE TEST SET FOR MATH, OCT 20\n"

    assert H.generate_headline(FM, caller=caller) == ("SUMMATIVE TEST SET FOR MATH, OCT 20", "model")
    assert "Oct 20" in seen["user"]


def test_invalid_model_output_falls_back():
    headline, source = H.generate_headline(FM, caller=lambda s, u: "Math test coming soon!")
    assert source == "fallback" and headline == headline.upper() and len(headline) <= 60


def test_model_exception_falls_back():
    def boom(system, user):
        raise TimeoutError("network down")

    assert H.generate_headline(FM, caller=boom)[1] == "fallback"


def test_no_token_means_fallback_without_network(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert H.generate_headline(FM)[1] == "fallback"


def test_subhead_model_and_fallback():
    good = H.generate_subhead(FM, "MATH TEST SET FOR OCT 20", caller=lambda s, u: "Covers chapters 1-4.")
    assert good == ("Covers chapters 1-4.", "model")
    bad = H.generate_subhead(FM, "MATH TEST SET FOR OCT 20", caller=lambda s, u: "Covers 99 chapters.")
    assert bad[1] == "fallback"

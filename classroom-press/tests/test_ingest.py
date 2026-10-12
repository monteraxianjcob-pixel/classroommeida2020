import yaml

from generator.build import parse_markdown
from scripts import issue_to_article as I

BODY = """category: exam
subject: Math
date: 2026-10-20
author: Priya N.
location: Room 204
scope: chapters 1-4
requirement: Bring a calculator

Note: this line stays in the body.

Arrive early.
"""


def test_parse_issue_body_splits_fields_and_body():
    fields, body = I.parse_issue_body(BODY)
    assert fields["category"] == "exam" and fields["scope"] == "chapters 1-4"
    assert body.startswith("Note: this line stays in the body.")
    assert "category:" not in body


def test_end_to_end_writes_markdown_and_keeps_authored_fields(tmp_path):
    env = {"ISSUE_TITLE": "Summative test", "ISSUE_BODY": BODY, "ISSUE_NUMBER": "12"}
    assert I.main(env, tmp_path, tmp_path / "photos") == 0
    files = list(tmp_path.glob("issue-12-*.md"))
    assert len(files) == 1
    fm, body = parse_markdown(files[0].read_text(encoding="utf-8"))
    assert fm["title"] == "Summative test" and fm["author"] == "Priya N."
    assert fm["headline"] == fm["headline"].upper() and len(fm["headline"]) <= 60
    assert fm["issue_number"] == 12 and "Arrive early." in body
    # second run (labeled after opened) is a no-op
    assert I.main(env, tmp_path, tmp_path / "photos") == 0
    assert len(list(tmp_path.glob("issue-12-*.md"))) == 1


def test_missing_env_fails(tmp_path):
    assert I.main({"ISSUE_BODY": "x"}, tmp_path) == 1

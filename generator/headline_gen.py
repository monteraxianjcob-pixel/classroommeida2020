"""Headline + subhead generation: GitHub Models call, validator, fallback.

Pattern:  the model only rewrites wording  ->  the validator gates it  ->
the template engine (headlines.py) is the floor.

This module runs ONLY at ingest time (GitHub Actions). Never import it from
the frontend build, and never call a model from browser code.
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Callable

from generator.headlines import (
    MAX_HEADLINE,
    MAX_SUBHEAD,
    fallback_headline,
    fallback_subhead,
    format_date_short,
    squash,
)

log = logging.getLogger("classroom_press.headline_gen")

BASE_URL = "https://models.github.ai/inference"
MODEL = "openai/gpt-4o-mini"

# ── RUNTIME HEADLINE PROMPT (verbatim from the project brief) ───────────────
SYSTEM_PROMPT = (
    "You are a newspaper copy editor. You rewrite school announcements\n"
    "as headlines. You never invent facts. You never add dates, numbers,\n"
    "names, or locations that are not in the input."
)

USER_PROMPT_TEMPLATE = """\
Rewrite this school announcement as a newspaper headline.

Rules:
- Maximum 60 characters
- ALL CAPS
- No facts beyond the input
- No dates or numbers unless present in the input
- Output only the headline. No quotes, no preamble.

Examples:
Input: Summative test | Math | Oct 20 | chapters 1-4
Output: SUMMATIVE TEST SET FOR MATH, OCT 20

Input: Field trip | Museum | Nov 5 | Room 204
Output: MUSEUM FIELD TRIP CONFIRMED FOR NOV 5

Input: Project submission | Science | Dec 1 | group work
Output: SCIENCE GROUP PROJECT DUE DEC 1

Input: {title} | {subject} | {date} | {scope}
Output:"""

# Subhead prompt (same system message; one sentence, sentence case).
SUBHEAD_PROMPT_TEMPLATE = """\
Write a one-sentence subhead that supports this newspaper headline.

Rules:
- Maximum 110 characters
- Sentence case, ending with a period
- Use only facts from the details below
- No dates or numbers unless present in the details
- Output only the subhead. No quotes, no preamble.

Headline: {headline}
Details: {details}
Subhead:"""

Caller = Callable[[str, str], str]  # (system, user) -> raw model text

_NUMBER = re.compile(r"\d+")
# Straight/curly quotes, guillemets and backticks. Apostrophes count as quotes.
_QUOTES = "\"'`\u201c\u201d\u2018\u2019\u00ab\u00bb"
_DOUBLE_QUOTES = "\"\u201c\u201d\u00ab\u00bb`"


# ── inputs shown to the model ───────────────────────────────────────────────
@dataclass(frozen=True)
class HeadlineInput:
    """Exactly the four strings the model sees. The validator checks against
    these same strings, so what the model saw is what the validator trusts."""

    title: str
    subject: str
    date: str   # short form, e.g. "Oct 20"
    scope: str

    @classmethod
    def from_front_matter(cls, fm: dict) -> "HeadlineInput":
        def field(v) -> str:
            return squash(v) or "n/a"

        return cls(
            title=field(fm.get("title")),
            subject=field(fm.get("subject")),
            date=field(format_date_short(fm.get("date"))) if fm.get("date") else "n/a",
            scope=field(fm.get("scope")),
        )

    def user_prompt(self) -> str:
        return USER_PROMPT_TEMPLATE.format(
            title=self.title, subject=self.subject, date=self.date, scope=self.scope
        )

    def allowed_numbers(self) -> set[str]:
        return _numbers(" ".join([self.title, self.subject, self.date, self.scope]))

    def required_numbers(self) -> set[str]:
        """Numbers a headline may not drop: the date and anything in the title."""
        return _numbers(self.title + " " + self.date)


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


# ── validators ──────────────────────────────────────────────────────────────
def validate_headline(output: str, inp: HeadlineInput) -> tuple[bool, str]:
    """Gate model output. Returns (ok, reason); reason is "ok" on success.

    Rejects: empty / multi-line, > 60 chars, not ALL CAPS, any quote,
    a required number (date, title) missing, or any number not in the input.
    Numbers are compared as whole tokens ("20" is not "2" + "0").
    """
    if not output or not output.strip():
        return False, "empty output"
    if "\n" in output or "\r" in output:
        return False, "multi-line output"
    if len(output) > MAX_HEADLINE:
        return False, f"too long ({len(output)} > {MAX_HEADLINE})"
    if not any(ch.isalpha() for ch in output) or output != output.upper():
        return False, "not ALL CAPS"
    if any(ch in _QUOTES for ch in output):
        return False, "contains quotes"

    found = _numbers(output)
    missing = inp.required_numbers() - found
    if missing:
        return False, f"dropped number(s) from input: {sorted(missing)}"
    invented = found - inp.allowed_numbers()
    if invented:
        return False, f"invented number(s) not in input: {sorted(invented)}"
    return True, "ok"


def validate_subhead(output: str, allowed_source: str) -> tuple[bool, str]:
    """Gate a model subhead against the text the model was given."""
    if not output or not output.strip():
        return False, "empty output"
    if "\n" in output or "\r" in output:
        return False, "multi-line output"
    if len(output) > MAX_SUBHEAD:
        return False, f"too long ({len(output)} > {MAX_SUBHEAD})"
    if output == output.upper():
        return False, "ALL CAPS subhead"
    if any(ch in _DOUBLE_QUOTES for ch in output):
        return False, "contains quotes"
    invented = _numbers(output) - _numbers(allowed_source)
    if invented:
        return False, f"invented number(s) not in input: {sorted(invented)}"
    return True, "ok"


# ── GitHub Models transport ─────────────────────────────────────────────────
def make_github_models_caller(
    token: str, *, model: str = MODEL, base_url: str = BASE_URL, timeout: float = 20.0
) -> Caller:
    """OpenAI-compatible chat call to GitHub Models, authenticated by token."""

    def call(system: str, user: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 80,
        }
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        return data["choices"][0]["message"]["content"]

    return call


def _resolve_caller(token: str | None, caller: Caller | None) -> Caller | None:
    if caller is not None:
        return caller
    token = token or os.environ.get("GITHUB_TOKEN")
    if not token:
        log.info("No GITHUB_TOKEN; using template fallback")
        return None
    return make_github_models_caller(token)


# ── public API ──────────────────────────────────────────────────────────────
def generate_headline(
    fm: dict, token: str | None = None, caller: Caller | None = None
) -> tuple[str, str]:
    """Return (headline, source) where source is "model" or "fallback"."""
    inp = HeadlineInput.from_front_matter(fm)
    call = _resolve_caller(token, caller)
    if call is None:
        return fallback_headline(fm), "fallback"

    try:
        raw = call(SYSTEM_PROMPT, inp.user_prompt())
    except Exception as exc:  # network, auth, rate limit, bad JSON: all -> floor
        log.warning("Model call failed (%s: %s); using template fallback",
                    type(exc).__name__, exc)
        return fallback_headline(fm), "fallback"

    candidate = (raw or "").strip()
    ok, reason = validate_headline(candidate, inp)
    if ok:
        return candidate, "model"

    log.warning("Model headline rejected (%s): %r; using template fallback",
                reason, candidate)
    return fallback_headline(fm), "fallback"


def generate_subhead(
    fm: dict, headline: str, token: str | None = None, caller: Caller | None = None
) -> tuple[str, str]:
    """Return (subhead, source). Same pattern as generate_headline."""
    parts = [
        ("Subject", fm.get("subject")),
        ("Date", format_date_short(fm.get("date")) if fm.get("date") else ""),
        ("Scope", fm.get("scope")),
        ("Location", fm.get("location")),
        ("Requirement", fm.get("requirement")),
        ("Restriction", fm.get("restriction")),
    ]
    details = "; ".join(f"{k}: {squash(v)}" for k, v in parts if squash(v)) or "n/a"
    allowed_source = f"{headline} {details} {squash(fm.get('title'))}"

    call = _resolve_caller(token, caller)
    if call is None:
        return fallback_subhead(fm), "fallback"

    try:
        raw = call(
            SYSTEM_PROMPT,
            SUBHEAD_PROMPT_TEMPLATE.format(headline=headline, details=details),
        )
    except Exception as exc:
        log.warning("Subhead call failed (%s: %s); using template fallback",
                    type(exc).__name__, exc)
        return fallback_subhead(fm), "fallback"

    candidate = (raw or "").strip()
    ok, reason = validate_subhead(candidate, allowed_source)
    if ok:
        return candidate, "model"

    log.warning("Model subhead rejected (%s): %r; using template fallback",
                reason, candidate)
    return fallback_subhead(fm), "fallback"

"""GitHub Issue -> content/<file>.md

Env vars: ISSUE_TITLE, ISSUE_BODY, ISSUE_NUMBER (required);
          ISSUE_AUTHOR (optional byline fallback), GITHUB_TOKEN (for the model).

The issue body is simple `key: value` lines for structured fields; every other
line becomes the markdown body. Human-authored fields are copied verbatim.
Only `headline` and `subhead` come from the model/templates.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import yaml

from generator.build import slugify
from generator.headline_gen import generate_headline, generate_subhead
from generator.headlines import CATEGORIES
from generator.photos import PHOTO_ROOT, pick_photo
from generator.urgency import parse_date

CONTENT_DIR = REPO_ROOT / "content"
FIELD_KEYS = ("category", "subject", "date", "author", "location",
              "scope", "requirement", "restriction")
_KV = re.compile(r"^\s*([A-Za-z][A-Za-z _]*?)\s*:\s*(.*?)\s*$")


def parse_issue_body(body: str) -> tuple[dict[str, str], str]:
    """Return (structured fields, remaining markdown). First occurrence wins."""
    fields: dict[str, str] = {}
    rest: list[str] = []
    for line in (body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _KV.match(line.replace("**", ""))
        key = match.group(1).strip().lower().replace(" ", "_") if match else None
        if match and key in FIELD_KEYS and key not in fields:
            fields[key] = match.group(2)
        else:
            rest.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(rest)).strip()
    return fields, text


def build_front_matter(title: str, fields: dict[str, str], issue_number: int,
                       default_author: str = "") -> dict:
    category = fields.get("category", "").strip().lower()
    if category not in CATEGORIES:
        category = "general"

    fm: dict = {"title": title.strip(), "category": category}
    for key in ("subject", "date", "author", "location", "scope", "requirement", "restriction"):
        value = fields.get(key, "").strip()
        if key == "author" and not value:
            value = default_author
        if value:
            fm[key] = value
    fm["pinned"] = False
    fm["issue_number"] = issue_number
    return fm


def render_markdown(fm: dict, body: str) -> str:
    header = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{header}---\n\n{body}\n" if body else f"---\n{header}---\n"


def main(env=None, content_dir: Path = CONTENT_DIR, photo_root: Path = PHOTO_ROOT,
         caller=None) -> int:
    env = os.environ if env is None else env
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    title = (env.get("ISSUE_TITLE") or "").strip()
    number = (env.get("ISSUE_NUMBER") or "").strip()
    if not title or not number.isdigit():
        print("ISSUE_TITLE and a numeric ISSUE_NUMBER are required", file=sys.stderr)
        return 1

    content_dir = Path(content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    if any(content_dir.glob(f"issue-{number}-*.md")):  # `opened` + `labeled` both fire
        print(f"Issue #{number} already ingested; nothing to do")
        return 0

    fields, body = parse_issue_body(env.get("ISSUE_BODY") or "")
    fm = build_front_matter(title, fields, int(number), env.get("ISSUE_AUTHOR", ""))
    if fm.get("date") and parse_date(fm["date"]) is None:
        print(f"::warning::Issue #{number}: could not read date {fm['date']!r}; use YYYY-MM-DD")

    token = env.get("GITHUB_TOKEN")
    headline, h_source = generate_headline(fm, token=token, caller=caller)
    subhead, s_source = generate_subhead(fm, headline, token=token, caller=caller)
    fm["headline"], fm["subhead"] = headline, subhead

    slug = slugify(title)
    photo = pick_photo(slug, fm["category"], photo_root)
    if photo:
        fm["photo"] = photo

    path = content_dir / f"issue-{number}-{slug}.md"
    path.write_text(render_markdown(fm, body), encoding="utf-8")

    print(f"::notice title=Headline ({h_source})::{headline}")
    print(f"headline source={h_source}  subhead source={s_source}  wrote {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

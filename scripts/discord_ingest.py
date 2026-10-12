"""Discord #announcements -> content/discord-<message id>-<slug>.md

Static hosting has no server to listen on, so a scheduled GitHub Action polls the
channel with the Discord REST API. Messages use the same `key: value` format as
GitHub issues, plus `title:` and `caption:`. An attached image becomes the cover
photo (saved to static/photos/covers/). Editing the Discord message updates the article.

Env: DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID (required); GITHUB_TOKEN (headline model);
     DISCORD_WEBHOOK_URL (optional: posts "Published: <headline>" back to Discord);
     GITHUB_OUTPUT (set by Actions; receives changed=true|false).
The bot token is read from the environment ONLY. Never commit it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from generator.build import slugify
from generator.headline_gen import generate_headline, generate_subhead
from scripts.issue_to_article import build_front_matter, parse_issue_body, render_markdown

API = "https://discord.com/api/v10"
CONTENT_DIR = REPO_ROOT / "content"
COVER_DIR = REPO_ROOT / "static" / "photos" / "covers"
STATE_PATH = REPO_ROOT / "generator" / "discord_state.json"
UA = "DiscordBot (https://github.com/classroom-press, 1.0)"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
log = logging.getLogger("classroom_press.discord")


# ── transport (injectable for tests) ────────────────────────────────────────
def fetch_messages(channel_id: str, token: str, limit: int = 50) -> list[dict]:
    req = urllib.request.Request(
        f"{API}/channels/{channel_id}/messages?limit={limit}",
        headers={"Authorization": f"Bot {token}", "User-Agent": UA},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def download(url: str, dest: Path) -> None:
    host = urlparse(url).hostname or ""
    if not (host.endswith("discordapp.com") or host.endswith("discordapp.net")):
        raise ValueError(f"refusing to download from {host}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image too large")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def notify(webhook_url: str, text: str) -> None:
    body = json.dumps({"content": text, "allowed_mentions": {"parse": []}}).encode()
    req = urllib.request.Request(webhook_url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    urllib.request.urlopen(req, timeout=15).close()


# ── parsing ─────────────────────────────────────────────────────────────────
def clean_mentions(text: str, mentions: list[dict]) -> str:
    names = {m["id"]: m.get("global_name") or m.get("username", "someone") for m in mentions}
    text = re.sub(r"<@!?(\d+)>", lambda m: "@" + names.get(m.group(1), "someone"), text)
    text = re.sub(r"<a?:(\w+):\d+>", "", text)        # custom emoji
    return re.sub(r"<[#&]\d+>", "", text)             # channel / role mentions


def split_extra_keys(text: str) -> tuple[dict[str, str], str]:
    """Pull `title:` and `caption:` lines out before the shared field parser."""
    extra, rest = {}, []
    for line in text.split("\n"):
        m = re.match(r"^\s*(title|caption)\s*:\s*(.+?)\s*$", line.replace("**", ""), re.I)
        if m and m.group(1).lower() not in extra:
            extra[m.group(1).lower()] = m.group(2)
        else:
            rest.append(line)
    return extra, "\n".join(rest)


def message_to_parts(msg: dict) -> dict | None:
    """Return {title, fields, body, caption} or None if there is no usable title."""
    text = clean_mentions((msg.get("content") or "").replace("\r\n", "\n"), msg.get("mentions", []))
    extra, text = split_extra_keys(text)
    fields, body = parse_issue_body(text)
    title = extra.get("title", "")
    if not title:  # first plain line of the message becomes the title
        lines = body.split("\n")
        for i, line in enumerate(lines):
            if line.strip():
                title = re.sub(r"^[#>\-*\s]+|\*\*|__", "", line).strip()
                body = "\n".join(lines[i + 1:]).strip()
                break
    title = title[:90].rsplit(" ", 1)[0] if len(title) > 90 else title
    if not title:
        return None
    return {"title": title, "fields": fields, "body": body, "caption": extra.get("caption", "")}


def cover_attachment(msg: dict) -> dict | None:
    for att in msg.get("attachments", []):
        ext = Path(att.get("filename", "")).suffix.lower()
        if ext in IMAGE_EXTS and (att.get("content_type", "image/").startswith("image/")) \
                and att.get("size", 0) <= MAX_IMAGE_BYTES:
            return att
    return None


# ── main ────────────────────────────────────────────────────────────────────
def process_message(msg, content_dir, cover_dir, token_for_model, download_fn, caller=None):
    parts = message_to_parts(msg)
    if not parts:
        return None
    author = msg.get("author", {})
    display = author.get("global_name") or author.get("username") or "Classmate"
    fm = build_front_matter(parts["title"], parts["fields"], None, display)

    att = cover_attachment(msg)
    if att:
        ext = Path(att["filename"]).suffix.lower()
        name = f"discord-{msg['id']}{ext}"
        try:
            download_fn(att["url"], Path(cover_dir) / name)
            fm["photo"] = f"/photos/covers/{name}"
            fm["photo_credit"] = f"Photo: {display}"
            if parts["caption"]:
                fm["photo_caption"] = parts["caption"]
        except Exception as exc:
            log.warning("cover download failed for message %s: %s", msg["id"], exc)

    headline, _ = generate_headline(fm, token=token_for_model, caller=caller)
    subhead, _ = generate_subhead(fm, headline, token=token_for_model, caller=caller)
    fm["headline"], fm["subhead"] = headline, subhead

    path = Path(content_dir) / f"discord-{msg['id']}-{slugify(parts['title'])}.md"
    path.write_text(render_markdown(fm, parts["body"]), encoding="utf-8")
    return headline


def run(env, content_dir=CONTENT_DIR, cover_dir=COVER_DIR, state_path=STATE_PATH,
        fetch=fetch_messages, download_fn=download, notify_fn=notify, caller=None) -> bool:
    token, channel = env.get("DISCORD_BOT_TOKEN"), env.get("DISCORD_CHANNEL_ID")
    if not token or not channel:
        print("DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID not set; skipping Discord ingest")
        return False

    content_dir, state_path = Path(content_dir), Path(state_path)
    content_dir.mkdir(parents=True, exist_ok=True)
    state = json.loads(state_path.read_text()) if state_path.is_file() else {"edited": {}}
    seen_edits = state.setdefault("edited", {})

    changed = False
    for msg in reversed(fetch(channel, token)):          # oldest first
        if msg.get("author", {}).get("bot") or msg.get("type", 0) not in (0, 19):
            continue
        mid = msg["id"]
        edit_ts = msg.get("edited_timestamp") or ""
        existing = list(content_dir.glob(f"discord-{mid}-*.md"))
        if existing and seen_edits.get(mid, "") == edit_ts:
            continue
        for old in existing:                              # edited: rebuild from the message
            old.unlink()
        headline = process_message(msg, content_dir, cover_dir, env.get("GITHUB_TOKEN"),
                                   download_fn, caller)
        if headline is None:
            print(f"message {mid}: no title found, skipped")
            continue
        seen_edits[mid] = edit_ts
        changed = True
        print(f"{'updated' if existing else 'created'} article from message {mid}: {headline}")
        if env.get("DISCORD_WEBHOOK_URL"):
            try:
                notify_fn(env["DISCORD_WEBHOOK_URL"],
                          f"Published to the Press: {headline}")
            except Exception as exc:
                log.warning("webhook notify failed: %s", exc)

    state_path.write_text(json.dumps(state, indent=2) + "\n")
    return changed


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        changed = run(os.environ)
    except Exception as exc:  # Discord down / bad token: don't fail the whole pipeline
        print(f"::warning::Discord ingest failed: {type(exc).__name__}: {exc}")
        changed = False
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as fh:
            fh.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

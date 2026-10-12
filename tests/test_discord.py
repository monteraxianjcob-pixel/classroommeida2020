from pathlib import Path

from generator.build import parse_markdown
from scripts import discord_ingest as D

ENV = {"DISCORD_BOT_TOKEN": "x", "DISCORD_CHANNEL_ID": "1"}


def msg(mid="100", content="", **kw):
    base = {"id": mid, "type": 0, "content": content, "author": {"username": "sam", "global_name": "Sam"},
            "attachments": [], "mentions": [], "edited_timestamp": None}
    base.update(kw)
    return base


def run(tmp_path, messages, downloads=None):
    got = downloads if downloads is not None else []

    def dl(url, dest):
        got.append(url)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"img")

    changed = D.run(ENV, tmp_path / "content", tmp_path / "covers", tmp_path / "state.json",
                    fetch=lambda c, t: messages, download_fn=dl, notify_fn=lambda u, t: None)
    return changed, got


def test_message_becomes_article_with_cover(tmp_path):
    m = msg(content="title: Summative test\ncategory: exam\nsubject: Math\ndate: 2026-10-20\n"
                    "caption: The hall\n\nBring a pencil, <@5>.",
            mentions=[{"id": "5", "username": "lee"}],
            attachments=[{"filename": "hall.JPG", "url": "https://cdn.discordapp.com/a/hall.jpg",
                          "content_type": "image/jpeg", "size": 10}])
    changed, got = run(tmp_path, [m])
    assert changed and got == ["https://cdn.discordapp.com/a/hall.jpg"]
    (path,) = (tmp_path / "content").glob("discord-100-*.md")
    fm, body = parse_markdown(path.read_text())
    assert fm["title"] == "Summative test" and fm["author"] == "Sam"
    assert fm["photo"] == "/photos/covers/discord-100.jpg" and fm["photo_credit"] == "Photo: Sam"
    assert fm["photo_caption"] == "The hall" and fm["headline"] == fm["headline"].upper()
    assert "@lee" in body and "<@5>" not in body
    assert (tmp_path / "covers" / "discord-100.jpg").exists()


def test_first_line_is_title_when_no_title_key(tmp_path):
    run(tmp_path, [msg(content="Field trip Friday\ncategory: event\n\nMeet at the gate.")])
    (path,) = (tmp_path / "content").glob("discord-100-*.md")
    fm, body = parse_markdown(path.read_text())
    assert fm["title"] == "Field trip Friday" and body == "Meet at the gate."


def test_bots_ignored_and_second_run_is_noop(tmp_path):
    bot = msg("7", "title: spam", author={"username": "b", "bot": True})
    human = msg("8", "title: Real news")
    assert run(tmp_path, [bot, human])[0] is True
    assert len(list((tmp_path / "content").glob("*.md"))) == 1
    assert run(tmp_path, [bot, human])[0] is False


def test_edit_updates_article(tmp_path):
    run(tmp_path, [msg(content="title: Old title\ncategory: event")])
    changed, _ = run(tmp_path, [msg(content="title: New title\ncategory: event",
                                    edited_timestamp="2026-10-12T10:00:00+00:00")])
    assert changed
    (path,) = (tmp_path / "content").glob("discord-100-*.md")
    assert "new-title" in path.name


def test_non_discord_image_host_is_refused():
    try:
        D.download("https://evil.example/x.png", Path("/tmp/x.png"))
    except ValueError:
        return
    raise AssertionError("should refuse")


def test_missing_secrets_skips(tmp_path):
    assert D.run({}, tmp_path, tmp_path, tmp_path / "s.json") is False

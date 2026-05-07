"""Fetch new messages from WeTheAgents Telegram inbox, extract URLs, append to queue.

Idempotent via Telegram's offset mechanism + local last_update_id state.
Reads token+chat_id from .env.telegram in repo root.

Output:
  agent0/inbox/telegram_queue.jsonl - one JSON per line, each a message with extracted URLs.
  agent0/inbox/telegram_state.json - {"last_update_id": N}

Usage:
  python gunnery/tools/telegram_fetch.py
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env.telegram"
INBOX_DIR = REPO_ROOT / "agent0" / "inbox"
QUEUE_FILE = INBOX_DIR / "telegram_queue.jsonl"
STATE_FILE = INBOX_DIR / "telegram_state.json"

URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)


def load_env() -> tuple[str, str]:
    if not ENV_FILE.exists():
        sys.exit(f"missing {ENV_FILE}")
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    token = env.get("TELEGRAM_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing in .env.telegram")
    return token, chat_id


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_update_id": 0}


def save_state(state: dict) -> None:
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def call_get_updates(token: str, offset: int) -> list[dict]:
    url = (
        f"https://api.telegram.org/bot{token}"
        f"/getUpdates?offset={offset}"
        f"&timeout=0&allowed_updates="
        + urllib.parse.quote(json.dumps(["message", "channel_post"]))
    )
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        sys.exit(f"telegram api error: {data}")
    return data.get("result", [])


def extract_urls(msg: dict) -> list[str]:
    """Pull URLs from plain text AND from Telegram entities/preview/buttons.

    Forwarded posts often hide the real URL in entities[type=text_link].url
    while the visible text is just "github.com" - regex on text alone misses it.
    """
    urls: list[str] = []
    text = msg.get("text") or msg.get("caption") or ""
    urls.extend(URL_RE.findall(text))

    for ent in (msg.get("entities") or []) + (msg.get("caption_entities") or []):
        if ent.get("type") == "text_link" and ent.get("url"):
            urls.append(ent["url"])

    preview = (msg.get("link_preview_options") or {}).get("url")
    if preview:
        urls.append(preview)

    for row in (msg.get("reply_markup") or {}).get("inline_keyboard", []) or []:
        for btn in row or []:
            if btn.get("url"):
                urls.append(btn["url"])

    seen: set[str] = set()
    uniq: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    return uniq


def pick_message(update: dict) -> dict | None:
    msg = update.get("message") or update.get("channel_post")
    if not msg:
        return None
    text = msg.get("text") or msg.get("caption") or ""
    urls = extract_urls(msg)
    if not urls:
        return None
    return {
        "update_id": update["update_id"],
        "message_id": msg.get("message_id"),
        "chat_id": (msg.get("chat") or {}).get("id"),
        "date": msg.get("date"),
        "text": text,
        "urls": urls,
        "status": "new",
    }


def append_queue(entries: list[dict]) -> None:
    if not entries:
        return
    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    with QUEUE_FILE.open("a", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def main() -> int:
    token, chat_id = load_env()
    state = load_state()
    offset = state["last_update_id"] + 1
    updates = call_get_updates(token, offset)

    new_entries: list[dict] = []
    max_id = state["last_update_id"]
    filtered = 0
    for u in updates:
        max_id = max(max_id, u["update_id"])
        entry = pick_message(u)
        if entry is None:
            filtered += 1
            continue
        if str(entry["chat_id"]) != str(chat_id):
            filtered += 1
            continue
        new_entries.append(entry)

    append_queue(new_entries)
    state["last_update_id"] = max_id
    save_state(state)

    print(
        f"telegram_fetch: updates={len(updates)} queued={len(new_entries)}"
        f" skipped={filtered} last_id={max_id}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

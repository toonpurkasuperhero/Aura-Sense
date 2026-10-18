"""Outbound actions: WhatsApp deep links (no API key needed) and optional push
notifications via ntfy.sh or a Telegram bot (enabled only when configured)."""
from __future__ import annotations

import urllib.parse

import requests

from .config import NTFY_SERVER, NTFY_TOPIC, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def whatsapp_link(number_digits: str, text: str) -> str:
    return f"https://wa.me/{number_digits}?text={urllib.parse.quote(text)}"


def sms_link(phone: str, text: str) -> str:
    return f"sms:{phone}?body={urllib.parse.quote(text)}"


def channels() -> dict:
    return {"ntfy": bool(NTFY_TOPIC), "telegram": bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)}


def push(title: str, message: str, priority: str = "default", tags: str = "warning") -> list[dict]:
    """Send to every configured channel. Returns a log of what was sent."""
    sent = []
    if NTFY_TOPIC:
        try:
            r = requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=message.encode(),
                              headers={"Title": title.encode("ascii", "ignore").decode(), "Priority": priority, "Tags": tags},
                              timeout=8)
            sent.append({"channel": "ntfy", "ok": r.ok})
        except requests.RequestException as e:
            sent.append({"channel": "ntfy", "ok": False, "error": str(e)})
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                              json={"chat_id": TELEGRAM_CHAT_ID, "text": f"{title}\n\n{message}"}, timeout=8)
            sent.append({"channel": "telegram", "ok": r.ok})
        except requests.RequestException as e:
            sent.append({"channel": "telegram", "ok": False, "error": str(e)})
    return sent

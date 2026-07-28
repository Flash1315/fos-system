"""Optional Telegram notifications (bot token from env, chat per org)."""

import json
import urllib.error
import urllib.request

from app.config import settings
from app.models import Organization


def telegram_configured() -> bool:
    return bool(settings.telegram_bot_token.strip())


def send_telegram(chat_id: str, text: str) -> bool:
    token = settings.telegram_bot_token.strip()
    chat = (chat_id or "").strip()
    if not token or not chat:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat, "text": text[:3500]}).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = 200 <= resp.status < 300
            print(f"telegram notify chat={chat} ok={ok}")
            return ok
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"telegram notify failed: {exc}")
        return False


def notify_org(org: Organization | None, text: str) -> bool:
    if not org:
        return False
    return send_telegram(getattr(org, "telegram_chat_id", "") or "", text)

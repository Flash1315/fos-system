"""Optional Telegram notifications (bot token from env, chat per org)."""

import json
import logging
import urllib.error
import urllib.request

from fastapi import BackgroundTasks

from app.config import settings
from app.models import Organization

logger = logging.getLogger(__name__)

_TELEGRAM_TIMEOUT_SEC = 5


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
        with urllib.request.urlopen(req, timeout=_TELEGRAM_TIMEOUT_SEC) as resp:
            ok = 200 <= resp.status < 300
            logger.info("telegram notify ok=%s", ok)
            return ok
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.warning("telegram notify failed err=%s", type(exc).__name__)
        return False


def notify_org(org: Organization | None, text: str) -> bool:
    """Synchronous send — use for explicit test endpoints that need the result."""
    if not org:
        return False
    return send_telegram(getattr(org, "telegram_chat_id", "") or "", text)


def schedule_org_notify(
    background_tasks: BackgroundTasks,
    org: Organization | None,
    text: str,
) -> None:
    """Best-effort Telegram after the response — pass primitives, not ORM state."""
    if not org or not telegram_configured():
        return
    chat = (getattr(org, "telegram_chat_id", "") or "").strip()
    if not chat:
        return
    background_tasks.add_task(send_telegram, chat, text)

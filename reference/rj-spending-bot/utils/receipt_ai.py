"""Apply Gemini receipt reading to manual Expense/Fuel photo steps."""
from io import BytesIO

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils.gemini import read_receipt_full
from utils.sheets import format_idr


def receipt_has_data(data: dict) -> bool:
    return any([
        data.get("amount"),
        data.get("place"),
        data.get("items"),
        data.get("receipt_date"),
    ])


def receipt_read_failure_message(result: dict) -> str:
    err = (result.get("error") or "").strip()
    if err:
        low = err.lower()
        if "not set" in low or "no gemini key" in low:
            return "⚠️ GEMINI_API_KEY not set on server. Admin: add key to systemd or config."
        if "permission_denied" in low or "denied access" in low:
            return (
                "⚠️ Gemini API key blocked or invalid.\n"
                "Admin: create a new key at aistudio.google.com/apikey "
                "and set GEMINI_API_KEY on the server."
            )
        if "api key" in low or "403" in err or "401" in err or "invalid" in low:
            return (
                "⚠️ Gemini API key problem.\n"
                "Admin: check GEMINI_API_KEY on server (new key from aistudio.google.com/apikey)."
            )
        if "empty_response" in low:
            return "⚠️ AI could not process this photo. Try better lighting or retake."
        return f"⚠️ AI error: {err[:160]}"
    if not receipt_has_data(result):
        return "⚠️ Could not read receipt clearly. Enter details manually or retake photo."
    return ""


def guess_fuel_type(items: str) -> str | None:
    text = (items or "").lower()
    if "pertamax" in text or "premium" in text:
        return "Pertamax"
    if "pertalite" in text or "solar" in text or "bensin" in text or "gasoline" in text:
        return "Pertalite"
    return None


async def download_receipt_bytes(bot, file_id: str) -> bytes:
    file = await bot.get_file(file_id)
    buf = BytesIO()
    await bot.download_file(file.file_path, buf)
    return buf.getvalue()


async def read_receipt_from_photo(bot, file_id: str) -> dict:
    image_bytes = await download_receipt_bytes(bot, file_id)
    return await read_receipt_full(image_bytes)


def _normalize_comment(text: str) -> str:
    return " ".join((text or "").lower().split())


def comments_similar(user_comment: str, ai_items: str) -> bool:
    user = _normalize_comment(user_comment)
    ai = _normalize_comment(ai_items)
    if not ai:
        return True
    if not user:
        return False
    if ai in user or user in ai:
        return True
    user_words = {w for w in user.split() if len(w) > 3}
    ai_words = {w for w in ai.split() if len(w) > 3}
    if user_words and ai_words:
        overlap = len(user_words & ai_words)
        if overlap >= min(2, len(ai_words)):
            return True
    return False


def resolve_comment_conflict(action: str, user_comment: str, ai_items: str) -> str:
    user = (user_comment or "").strip()
    ai = (ai_items or "").strip()
    if action == "replace":
        return ai or user
    if action == "append" and user and ai:
        return f"{user} — Receipt: {ai}"
    return user


def receipt_comment_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Keep mine", callback_data=f"{prefix}:keep")],
        [
            InlineKeyboardButton(text="🤖 Use receipt", callback_data=f"{prefix}:replace"),
            InlineKeyboardButton(text="➕ Append both", callback_data=f"{prefix}:append"),
        ],
    ])


def apply_receipt_fields(
    data: dict,
    result: dict,
    *,
    fill_comment: bool = True,
    check_amount: bool = True,
) -> tuple[dict, list[str], dict | None]:
    """Returns updates, info lines, and optional comment conflict payload."""
    updates = {}
    lines = []
    conflict = None

    items = (result.get("items") or "").strip()
    user_comment = (data.get("comment") or "").strip()
    if fill_comment and items:
        if not user_comment:
            updates["comment"] = items
            lines.append(f"📋 Comment: {items}")
        elif not comments_similar(user_comment, items):
            conflict = {"user_comment": user_comment, "ai_items": items}

    ai_amount = result.get("amount")
    entered_amount = data.get("amount")
    if check_amount and ai_amount:
        if entered_amount and int(entered_amount) != int(ai_amount):
            lines.append(
                f"⚠️ Receipt total: {format_idr(ai_amount)} "
                f"(you entered {format_idr(entered_amount)})"
            )
        elif not entered_amount:
            updates["amount"] = int(ai_amount)
            lines.append(f"💵 Amount: {format_idr(ai_amount)}")

    place = (result.get("place") or "").strip()
    if place:
        lines.append(f"📍 Place: {place}")

    receipt_date = (result.get("receipt_date") or "").strip()
    if receipt_date:
        lines.append(f"📅 Date on receipt: {receipt_date}")

    if conflict:
        lines.extend([
            "",
            f"💬 Your comment: {user_comment}",
            f"📋 Receipt items: {items}",
            "",
            "Comments differ — choose what to save:",
        ])
    elif result.get("error"):
        lines.append(receipt_read_failure_message(result))
    elif not lines and not any([ai_amount, place, items, receipt_date]):
        lines.append("⚠️ Could not read receipt clearly.")

    return updates, lines, conflict


async def enrich_from_receipt_photo(bot, file_id: str, data: dict) -> tuple[dict, list[str], dict | None]:
    result = await read_receipt_from_photo(bot, file_id)
    return apply_receipt_fields(data, result)


async def read_receipt_for_ai_flow(bot, file_id: str) -> dict:
    """Full receipt read for AI-first expense/fuel flows."""
    return await read_receipt_from_photo(bot, file_id)

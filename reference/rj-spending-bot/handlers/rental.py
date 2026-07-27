import io
import re
import copy
from datetime import datetime, timedelta
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS, EMPLOYEES, LESSON_GROUP_CHAT_ID
from keyboards.kb import (
    rental_submenu_kb, manager_menu_kb, back_cancel_kb, cancel_kb,
    confirm_kb, main_menu, calendar_kb, skip_comment_kb,
)
from utils.sheets import (
    get_sheet, SHEET_RENTALS, SHEET_BIKE_ISSUES,
    RENT_COL_ID, RENT_COL_STATUS, RENT_COL_CLIENT, RENT_COL_BIKE,
    RENT_COL_DELIVERY_DATE, RENT_COL_RETURN_DATE, RENT_COL_RENTAL_PRICE,
    RENT_COL_INSTRUCTOR, RENT_COL_LOCATION, RENT_COL_SOURCE,
    ISS_COL_BIKE, ISS_COL_DESCRIPTION, ISS_COL_STATUS, ISS_COL_DATE,
    get_next_rental_id, append_rental, format_idr, now_time, parse_date,
)
from utils.bikes import get_rental_bikes
from utils.gemini import parse_rental_request, parse_voice_message, read_passport, _match_bike_from_list
from utils.rental_rules import (
    extract_price_from_text, parse_relative_delivery_date, parse_delivery_time_from_text,
    find_rental_corrections, save_correction_rule, suggest_phrase_from_text, FIELD_LABELS,
)

router = Router()

RENTAL_THREAD_ID = 2

AI_FIELDS = [
    ("client_name", "👤 Client name"),
    ("delivery_date", "📅 Delivery date"),
    ("duration_days", "📆 Duration (days)"),
    ("price", "💵 Price (IDR)"),
    ("helmets", "🪖 Helmets"),
    ("insurance", "🛡 Insurance"),
    ("location", "📍 Location"),
    ("bike_name", "🏍 Bike"),
]

REQUIRED_FIELDS = [
    "delivery_date", "duration_days", "bike", "source",
    "client_name", "contact_platform", "contact_info", "location", "rental_price",
]

AI_REQUIRED_FIELDS = [
    "delivery_date", "duration_days", "bike", "client_name", "rental_price",
    "helmets", "insurance", "source", "location", "contact_platform", "contact_info",
]


class RentalForm(StatesGroup):
    input_method = State()
    ai_input = State()
    ai_fill_missing = State()
    ai_helmets = State()
    ai_helmets_custom = State()
    ai_comment = State()
    delivery_date = State()
    delivery_time = State()
    duration = State()
    duration_custom = State()
    bike = State()
    source = State()
    client_name = State()
    contact_platform = State()
    contact_info = State()
    instructor = State()
    instructor_custom = State()
    location = State()
    location_text = State()
    price = State()
    helmets = State()
    helmets_custom = State()
    insurance = State()
    insurance_cost = State()
    extra_name = State()
    extra_amount = State()
    extra_more = State()
    passport = State()
    passport_confirm = State()
    comment = State()
    confirm = State()


def is_manager(uid: int) -> bool:
    return uid in MANAGERS


def manager_name(uid: int) -> str:
    return MANAGERS.get(uid, {}).get("name", "Manager")


def default_rental_data() -> dict:
    return {
        "delivery_time": "Set later",
        "instructor": "Set later",
        "helmets": "0",
        "insurance": "No insurance",
        "insurance_cost": "",
        "extra_charges": "",
        "passport": "",
        "passport_info": "",
        "comment": "",
        "extras_list": [],
    }


def compute_return_date(delivery_date: str, duration_days: int) -> str:
    dt = parse_date(delivery_date)
    if not dt or duration_days <= 0:
        return ""
    return (dt + timedelta(days=duration_days - 1)).strftime("%d.%m.%Y")


def parse_delivery_date(text: str) -> Optional[str]:
    t = text.strip()
    m = re.search(
        r"(?:^|[\s,:;-]|(?:дата|date)\s*)"
        r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?(?:\b|$)",
        t,
        re.I,
    )
    if not m:
        return None
    day, month, year_raw = int(m.group(1)), int(m.group(2)), m.group(3)
    if month < 1 or month > 12:
        return None
    prefix = t[max(0, m.start() - 4):m.start()].lower()
    if re.search(r"(?:с|from)\s*$", prefix):
        return None
    if year_raw:
        year = int(year_raw)
        if year < 100:
            year += 2000
    else:
        year = datetime.now().year
    return f"{day:02d}.{month:02d}.{year}"


def parse_idr_value(text: str) -> int:
    t = text.strip().lower()
    if not t or parse_delivery_date(t):
        return 0
    if re.search(r"(?:млн|mln|million|jt|juta)", t):
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:млн|mln|million|jt|juta)", t)
        if m:
            return int(float(m.group(1).replace(",", ".")) * 1_000_000)
    if re.search(r"(?:\bк\b|\bk\b|тыс|rb|ribu)", t):
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\bк\b|\bk\b|тыс|rb|ribu)", t)
        if m:
            return int(float(m.group(1).replace(",", ".")) * 1_000)
    blocks = re.findall(r"\d+", t)
    if not blocks:
        return 0
    if len(blocks) >= 2 and not re.search(
        r"(?:с|from)\s*\d{1,2}[.:]\d{2}\s*(?:до|to|-)\s*\d{1,2}[.:]\d{2}", t, re.I
    ):
        joined = "".join(blocks)
        if len(joined) >= 5 or len(blocks) >= 3:
            return int(joined)
    long_blocks = [b for b in blocks if len(b) >= 4]
    if long_blocks:
        return int(long_blocks[0])
    if len(blocks) == 1:
        return int(blocks[0])
    return int(max(blocks, key=len))


def is_pure_price_text(text: str) -> bool:
    t = text.strip().replace(" ", "").replace(",", "")
    return t.isdigit() and len(t) >= 4


def parse_duration_from_text(text: str) -> Optional[int]:
    t = text.strip().lower()
    if re.search(r"полтора\s*месяц|полторы\s*месяц", t):
        return 45
    word_months = {
        "один": 1, "one": 1, "два": 2, "two": 2, "три": 3, "three": 3,
        "четыре": 4, "four": 4, "пять": 5, "five": 5, "шесть": 6, "six": 6,
    }
    for word, num in word_months.items():
        if re.search(rf"\b{word}\b\s*месяц", t):
            return num * 30
    m = re.search(r"(\d+)\s*месяц", t)
    if m:
        return int(m.group(1)) * 30
    m = re.search(r"(\d+)\s*мес", t)
    if m:
        return int(m.group(1)) * 30
    if re.search(r"(?<!\d)месяц(?!\w)", t):
        return 30
    m = re.search(r"(\d+)\s*(?:дн|day|days|дней)", t)
    if m:
        return int(m.group(1))
    if t.isdigit() and len(t) <= 3:
        return int(t)
    return None


def parse_helmets_from_text(text: str) -> Optional[str]:
    t = text.strip().lower()
    word_map = {"один": "1", "one": "1", "два": "2", "two": "2", "три": "3", "three": "3"}
    m = re.search(r"(\d+)\s*шлем", t)
    if m:
        return str(int(m.group(1)))
    for word, num in word_map.items():
        if re.search(rf"\b{word}\b\s*шлем", t):
            return num
    return None


def parse_insurance_from_text(text: str) -> Optional[str]:
    t = text.strip().lower()
    if re.search(r"без\s*страхов", t) or "no insurance" in t:
        return "No insurance"
    if re.search(r"со\s*страхов|with insurance", t):
        return "With insurance"
    return None


def _passport_display(val) -> str:
    if val is None or str(val).strip().lower() in ("", "none", "null"):
        return "—"
    return str(val).strip()


def normalize_source_value(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = text
    if re.search(r"(?:telegram|телеграм)", text, re.I):
        cleaned = re.sub(
            r"(?:из|from|via|через)?\s*(?:telegram|телеграм(?:а|е|у)?)\s+[A-Za-zА-Яа-яЁё0-9 ._@-]+",
            "",
            text,
            flags=re.I,
        )
    sl = cleaned.strip().lower()
    compact = re.sub(r"[\s&\-_]", "", sl)
    rj_variants = (
        "ridejoy", "rideandjoy", "brighterjoy", "райдджой", "райдэндджой",
        "rj", "рдж", "ride&joy",
    )
    if compact in rj_variants or any(v in compact for v in ("ridejoy", "brighterjoy", "райдджой")):
        return "Ride&Joy"
    if re.search(r"\b(ride\s*joy|ride\s*and\s*joy|brighter\s*joy|райд\s*джой|rj)\b", sl):
        return "Ride&Joy"
    if compact in ("travelask", "travelask") or re.search(r"\b(travel\s*ask|travelask|травел\s*аск)\b", sl):
        return "TravelAsk"
    return None


def extract_telegram_from_message(text: str) -> tuple:
    t = text.strip()
    if is_telegram_contact(t):
        return "Telegram", t
    m = re.search(
        r"(?:она\s+)?(?:из|from|via|через)?\s*(?:telegram|телеграм(?:а|е|у)?)"
        r"[\s,:-]+([A-Za-zА-Яа-яЁё0-9 ._@-]+)",
        t,
        re.I,
    )
    if m:
        info = m.group(1).strip().strip("\"'., ")
        if info:
            return "Telegram", info
    return None, None


def apply_telegram_from_message(data: dict, text: str) -> dict:
    platform, info = extract_telegram_from_message(text)
    if platform and info:
        data["contact_platform"] = platform
        data["contact_info"] = info
    return data


def is_telegram_contact(text: str) -> bool:
    return bool(re.search(r"(?:https?://)?t\.me/\S+|@\w{3,}", text.strip(), re.I))


def apply_telegram_contact(data: dict, text: str) -> dict:
    if is_telegram_contact(text):
        data["contact_platform"] = "Telegram"
        data["contact_info"] = text.strip()
    return data


def format_duration_display(data: dict) -> str:
    delivery = data.get("delivery_date")
    days = data.get("duration_days")
    if not delivery or not days:
        return "—"
    try:
        days_int = int(days)
    except (ValueError, TypeError):
        return str(days)
    ret = data.get("return_date") or compute_return_date(delivery, days_int)
    return f"{delivery} — {ret} ({days_int} дней)"


def ai_core_fields_ready(data: dict) -> bool:
    return not missing_ai_required(data)


def missing_ai_required(data: dict) -> list:
    missing = []
    for key in AI_REQUIRED_FIELDS:
        val = data.get(key)
        if val is None or str(val).strip() == "":
            missing.append(key)
    return missing


def calc_total(data: dict) -> int:
    total = int(data.get("rental_price") or 0)
    if data.get("insurance") == "With insurance":
        try:
            total += int(str(data.get("insurance_cost") or "0").replace(",", "").replace(".", "") or 0)
        except ValueError:
            pass
    for item in data.get("extras_list") or []:
        try:
            total += int(item.get("amount", 0))
        except (ValueError, TypeError):
            pass
    return total


def format_extra_charges(data: dict) -> str:
    items = data.get("extras_list") or []
    if not items:
        return ""
    return "; ".join(f"{i['name']}: {i['amount']}" for i in items)


def missing_required(data: dict) -> list:
    missing = []
    for key in REQUIRED_FIELDS:
        val = data.get(key)
        if val is None or str(val).strip() == "":
            missing.append(key)
    if data.get("insurance") == "With insurance" and not str(data.get("insurance_cost") or "").strip():
        missing.append("insurance_cost")
    return missing


def instructor_tag(name: str) -> str:
    if not name or name == "Set later":
        return ""
    for info in EMPLOYEES.values():
        if info.get("name", "").lower() == name.lower() and info.get("username"):
            return f"@{info['username']}"
    return name


def input_method_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎤 Voice / text (AI fills)")],
            [KeyboardButton(text="✍️ Fill manually")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def delivery_time_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏳ Set later")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
        input_field_placeholder="10:00 or 10:00-11:00",
    )


def duration_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="7 days"), KeyboardButton(text="10 days"), KeyboardButton(text="14 days")],
            [KeyboardButton(text="30 days"), KeyboardButton(text="1 month"), KeyboardButton(text="Custom")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def rental_bikes_kb() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=b)] for b in get_rental_bikes()]
    rows.append([KeyboardButton(text="TBD")])
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def source_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Ride&Joy"), KeyboardButton(text="TravelAsk")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def contact_platform_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="WhatsApp"), KeyboardButton(text="Instagram")],
            [KeyboardButton(text="Facebook"), KeyboardButton(text="TikTok")],
            [KeyboardButton(text="Telegram"), KeyboardButton(text="Phone")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def instructor_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Ray"), KeyboardButton(text="Alex")],
            [KeyboardButton(text="Other"), KeyboardButton(text="⏳ Set later")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def location_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Google Maps link")],
            [KeyboardButton(text="🏘 District (text)")],
            [KeyboardButton(text="✏️ Other")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def helmets_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0"), KeyboardButton(text="1"), KeyboardButton(text="2")],
            [KeyboardButton(text="Other")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def insurance_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="No insurance"), KeyboardButton(text="With insurance")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def extra_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Add extra charge")],
            [KeyboardButton(text="⏭ Skip")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def passport_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def passport_confirm_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Confirm passport"), KeyboardButton(text="✏️ Edit passport")],
            [KeyboardButton(text="⏭ Skip")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def ai_fill_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Teach AI")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def ai_field_label(key: str) -> str:
    for k, label in AI_FIELDS:
        if k == key:
            return label
    return key


def apply_ai_parsed(data: dict, parsed: dict, raw_text: str = "") -> dict:
    mapping = {
        "client_name": "client_name",
        "delivery_date": "delivery_date",
        "delivery_time": "delivery_time",
        "duration_days": "duration_days",
        "price": "rental_price",
        "helmets": "helmets",
        "insurance": "insurance",
        "location": "location",
        "bike_name": "bike",
    }
    for src, dst in mapping.items():
        val = parsed.get(src)
        if val is None:
            continue
        if isinstance(val, bool):
            if dst == "insurance":
                data[dst] = "No insurance" if not val else "With insurance"
            continue
        if not str(val).strip():
            continue
        if dst == "rental_price":
            price = parsed.get("price")
            if price is not None:
                data[dst] = int(price)
        elif dst == "duration_days":
            days = parse_duration_from_text(raw_text) if raw_text else None
            if days is None:
                try:
                    days = int(str(val).strip())
                except ValueError:
                    days = None
            if days:
                data[dst] = days
        elif dst == "insurance":
            sl = str(val).strip().lower()
            if sl in ("false", "0", "no", "none", "без страховки", "no insurance", "без"):
                data[dst] = "No insurance"
            elif sl in ("true", "1", "yes", "with insurance", "со страховкой"):
                data[dst] = "With insurance"
            else:
                data[dst] = str(val).strip()
        elif dst == "helmets":
            helmets = parse_helmets_from_text(raw_text) if raw_text else None
            data[dst] = helmets if helmets is not None else str(val).strip()
        elif dst == "delivery_date":
            normalized = parse_relative_delivery_date(raw_text) or parse_delivery_date(str(val)) or str(val).strip()
            data[dst] = normalized
        elif dst == "delivery_time":
            data[dst] = str(val).strip()
        else:
            data[dst] = str(val).strip()
    src = parsed.get("source")
    if src:
        data["source"] = src
    elif raw_text:
        detected = normalize_source_value(raw_text)
        if detected:
            data["source"] = detected
    cp = parsed.get("contact_platform")
    ci = parsed.get("contact_info")
    if ci:
        if is_telegram_contact(str(ci)):
            data["contact_platform"] = "Telegram"
            data["contact_info"] = str(ci).strip()
        elif cp:
            data["contact_platform"] = str(cp).strip()
            data["contact_info"] = str(ci).strip()
    if raw_text:
        data = apply_telegram_from_message(data, raw_text)
        ins = parse_insurance_from_text(raw_text)
        if ins:
            data["insurance"] = ins
        helmets = parse_helmets_from_text(raw_text)
        if helmets is not None:
            data["helmets"] = helmets
        days = parse_duration_from_text(raw_text)
        if days:
            data["duration_days"] = days
        rel_date = parse_relative_delivery_date(raw_text)
        if rel_date:
            data["delivery_date"] = rel_date
        delivery_time = parse_delivery_time_from_text(raw_text)
        if delivery_time:
            data["delivery_time"] = delivery_time
        if not data.get("rental_price"):
            price = extract_price_from_text(raw_text)
            if price:
                data["rental_price"] = price
        text_price = parse_idr_value(raw_text)
        if text_price >= 1000:
            current = int(data.get("rental_price") or 0)
            if text_price > current:
                data["rental_price"] = text_price
    if data.get("bike"):
        data["bike"] = _match_bike_from_list(data["bike"], raw_text)
    elif raw_text:
        matched = _match_bike_from_list(None, raw_text)
        if matched:
            data["bike"] = matched
    if data.get("duration_days") and data.get("delivery_date"):
        data["return_date"] = compute_return_date(data["delivery_date"], int(data["duration_days"]))
    return data


def format_ai_review(data: dict) -> str:
    lines = ["🤖 <b>AI parsed booking:</b>\n"]
    field_labels = {
        "client_name": "👤 Client name",
        "delivery_date": "📅 Delivery date",
        "duration_days": "📆 Duration (days)",
        "rental_price": "💵 Price (IDR)",
        "helmets": "🪖 Helmets",
        "insurance": "🛡 Insurance",
        "location": "📍 Location",
        "delivery_time": "🕐 Delivery time",
        "bike": "🏍 Bike",
        "source": "📣 Source",
        "contact_platform": "📱 Contact platform",
        "contact_info": "📱 Contact info",
        "insurance_cost": "🛡 Insurance cost",
        "passport": "🛂 Passport",
    }
    review_keys = list(AI_REQUIRED_FIELDS)
    optional_keys = ["delivery_time", "passport"]
    for key in review_keys:
        val = data.get(key)
        label = field_labels.get(key, key)
        if val is not None and str(val).strip():
            if key == "rental_price":
                display = format_idr(int(val))
            elif key == "duration_days":
                display = format_duration_display(data)
            else:
                display = val
            lines.append(f"✅ {label}: {display}")
        else:
            lines.append(f"❓ {label}")
    for key in optional_keys:
        val = data.get(key)
        label = field_labels.get(key, key)
        if val is not None and str(val).strip():
            lines.append(f"✅ {label}: {val}")
    missing = missing_ai_required(data)
    if missing:
        lines.append("\n✏️ Send text, voice, or forward a passport photo. I'll fill missing fields.")
    else:
        lines.append("\n✅ Required fields filled.")
    return "\n".join(lines)


def detect_field_from_text(text: str, missing: list) -> Optional[str]:
    t = text.strip()
    lower = t.lower()

    if is_pure_price_text(t):
        return "rental_price"

    if "maps.google" in lower or "goo.gl/maps" in lower or "google.com/maps" in lower:
        return "location"

    if is_telegram_contact(t):
        return "contact_info"

    parsed_date = parse_delivery_date(t)
    if parsed_date:
        return "delivery_date"

    source_val = normalize_source_value(t)
    if source_val and "source" in missing:
        return "source"

    price_val = parse_idr_value(t)
    if price_val > 0 and "rental_price" in missing:
        return "rental_price"

    ins_val = parse_insurance_from_text(t)
    if ins_val and "insurance" in missing:
        return "insurance"

    helmets_val = parse_helmets_from_text(t)
    if helmets_val is not None and "helmets" in missing:
        return "helmets"

    days_val = parse_duration_from_text(t)
    if days_val and "duration_days" in missing:
        return "duration_days"

    if "insurance_cost" in missing:
        ins_val = parse_idr_value(t)
        if ins_val > 0:
            return "insurance_cost"

    digits = "".join(c for c in t if c.isdigit())
    if digits:
        if digits in ("0", "1", "2") and "helmets" in missing and len(digits) == 1:
            return "helmets"
        dur_match = re.search(r"(\d+)\s*(?:дн|day|days|дней)", lower)
        if dur_match and "duration_days" in missing:
            return "duration_days"
        if len(digits) <= 3 and "duration_days" in missing and not parse_delivery_date(t):
            return "duration_days"

    bikes = [b.lower() for b in get_rental_bikes()] + ["tbd", "nmax", "scoop", "fazzio", "lexi"]
    if any(b in lower for b in bikes) and "bike" in missing:
        return "bike"

    if "insurance" in lower or "no insurance" in lower:
        return "insurance" if "insurance" in missing else None

    platforms = ["whatsapp", "instagram", "facebook", "tiktok", "telegram", "phone"]
    if any(p in lower for p in platforms) and "contact_platform" in missing:
        return "contact_platform"

    if t.startswith("+") or (t.replace(" ", "").isdigit() and len(t.replace(" ", "")) >= 7):
        return "contact_info" if "contact_info" in missing else None

    if "client_name" in missing and len(t.split()) <= 4 and not parse_idr_value(t):
        return "client_name"

    return None


def apply_detected_field(data: dict, field: str, text: str) -> dict:
    t = text.strip()
    if field == "rental_price":
        data["rental_price"] = parse_idr_value(t)
    elif field == "delivery_date":
        parsed = parse_delivery_date(t)
        if parsed:
            data["delivery_date"] = parsed
            if data.get("duration_days"):
                data["return_date"] = compute_return_date(parsed, int(data["duration_days"]))
    elif field == "duration_days":
        days = parse_duration_from_text(t)
        if not days:
            dur_match = re.search(r"(\d+)\s*(?:дн|day|days|дней)", t, re.I)
            if dur_match:
                days = int(dur_match.group(1))
        if days:
            data["duration_days"] = days
            if data.get("delivery_date"):
                data["return_date"] = compute_return_date(data["delivery_date"], days)
    elif field == "helmets":
        helmets = parse_helmets_from_text(t)
        data["helmets"] = helmets if helmets is not None else t
    elif field == "insurance":
        ins = parse_insurance_from_text(t)
        data["insurance"] = ins if ins else ("With insurance" if "with" in t.lower() or "yes" in t.lower() else "No insurance")
    elif field == "insurance_cost":
        data["insurance_cost"] = parse_idr_value(t)
    elif field == "contact_platform":
        for p in ["WhatsApp", "Instagram", "Facebook", "TikTok", "Telegram", "Phone"]:
            if p.lower() in t.lower():
                data["contact_platform"] = p
                break
    elif field == "contact_info":
        apply_telegram_contact(data, t)
        if not data.get("contact_info"):
            data["contact_info"] = t
    elif field == "source":
        src = normalize_source_value(t)
        if src:
            data["source"] = src
    elif field == "bike":
        data["bike"] = t if t.upper() != "TBD" else "TBD"
    else:
        data[field] = t
    return data


def format_passport_from_result(result: dict) -> str:
    r = result or {}
    name = r.get("name")
    if not name:
        given = r.get("given_names") or ""
        surname = r.get("surname") or ""
        name = f"{given} {surname}".strip()
    return (
        f"{_passport_display(name)} | №{_passport_display(r.get('passport_number'))} | "
        f"Issued: {_passport_display(r.get('issue_date'))}"
    )


def passport_has_data(result: dict) -> bool:
    r = result or {}
    for key in ("name", "surname", "given_names", "passport_number", "issue_date"):
        val = r.get(key)
        if val and str(val).strip() and str(val).strip().lower() not in ("null", "none", "—"):
            return True
    return False


def apply_passport_to_rental(rental: dict, result: dict, photo_url: str = "") -> tuple:
    passport_text = format_passport_from_result(result)
    rental["passport_info"] = passport_text
    rental["passport"] = photo_url or passport_text
    name = str((result or {}).get("name") or "").strip()
    if not name:
        given = str((result or {}).get("given_names") or "").strip()
        surname = str((result or {}).get("surname") or "").strip()
        name = f"{given} {surname}".strip()
    if name and name.lower() not in ("null", "none", "—"):
        rental["client_name"] = name.upper()
    return rental, passport_text


def format_passport_for_sheet(rental: dict) -> str:
    info = str(rental.get("passport_info") or "").strip()
    passport = str(rental.get("passport") or "").strip()
    if passport.startswith("http") and info and info != "—":
        return f"{info} | {passport}"
    return passport or info


async def upload_passport_photo(message: Message, file_id: str) -> str:
    try:
        from utils.drive_upload import upload_receipt_to_drive
        date_str = datetime.now().strftime("%d-%m-%Y")
        return await upload_receipt_to_drive(
            message.bot, file_id, f"passport_{date_str}.jpg", date_str
        ) or ""
    except Exception as e:
        print(f"passport upload error: {e}")
        return ""


def passport_file_id_from_message(message: Message) -> Optional[str]:
    if message.document and (message.document.mime_type or "").startswith("image/"):
        return message.document.file_id
    if message.photo:
        return message.photo[-1].file_id
    return None


async def load_passport_from_message(message: Message):
    file_id = passport_file_id_from_message(message)
    if not file_id:
        return None, None, None
    file = await message.bot.get_file(file_id)
    buf = io.BytesIO()
    await message.bot.download_file(file.file_path, buf)
    image_bytes = buf.getvalue()
    print(f"passport download: {len(image_bytes)} bytes, file_id={file_id[:24]}...")
    if len(image_bytes) < 500:
        print("passport warning: image very small, OCR may fail")
    result = await read_passport(image_bytes)
    return result, file_id, image_bytes


def format_passport_display(data: dict) -> str:
    info = data.get("passport_info") or data.get("passport_draft") or ""
    if info and str(info).strip() and "None" not in str(info):
        return str(info).strip()
    passport = data.get("passport") or ""
    if passport and "None" not in str(passport):
        if str(passport).startswith("http") or "google.com" in str(passport):
            return data.get("passport_info") or "—"
        return str(passport).strip()
    return "—"


def format_rental_summary(data: dict) -> str:
    extras = format_extra_charges(data)
    total = calc_total(data)
    contact_platform = data.get("contact_platform") or "—"
    contact_info = data.get("contact_info") or "—"
    insurance_line = data.get("insurance", "—")
    if data.get("insurance") == "With insurance":
        insurance_line += f" — {format_idr(int(data.get('insurance_cost') or 0))}"
    return (
        f"📋 <b>Confirm rental booking:</b>\n\n"
        f"📅 Delivery date: {data.get('delivery_date', '—')}\n"
        f"🕐 Delivery time: {data.get('delivery_time', '—')}\n"
        f"📆 Duration: {format_duration_display(data)}\n"
        f"🏍 Bike: {data.get('bike', '—')}\n"
        f"📣 Source: {data.get('source', '—')}\n"
        f"👤 Client: {data.get('client_name', '—')}\n"
        f"📱 Contact: {contact_platform} — {contact_info}\n"
        f"👨‍🏫 Instructor: {data.get('instructor', '—')}\n"
        f"📍 Location: {data.get('location', '—')}\n"
        f"💵 Price: {format_idr(int(data.get('rental_price') or 0))}\n"
        f"🪖 Helmets: {data.get('helmets', '0')}\n"
        f"🛡 Insurance: {insurance_line}\n"
        f"➕ Extras: {extras or '—'}\n"
        f"💰 Total: <b>{format_idr(total)}</b>\n"
        f"🛂 Passport: {format_passport_display(data)}\n"
        f"💬 Comment: {data.get('comment') or '—'}"
    )


async def cancel_rental(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=is_superadmin))


async def show_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    rental = data.get("rental", {})
    rental["total"] = calc_total(rental)
    show_remember = bool(
        data.get("ai_mode")
        and data.get("last_ai_text")
        and data.get("initial_ai_rental")
    )
    await state.update_data(rental=rental)
    await state.set_state(RentalForm.confirm)
    await message.answer(
        format_rental_summary(rental),
        reply_markup=confirm_kb(show_remember=show_remember),
        parse_mode="HTML",
    )


async def maybe_ai_advance(message: Message, state: FSMContext):
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    if missing_ai_required(rental):
        await state.set_state(RentalForm.ai_fill_missing)
        return
    if data.get("ai_mode") and not data.get("ai_went_passport"):
        await state.update_data(ai_went_passport=True)
        await goto_step(message, state, "passport")
        return
    await show_confirm(message, state)


async def _process_ai_passport_photo(message: Message, state: FSMContext):
    await message.answer("⏳ Reading passport...")
    loaded = await load_passport_from_message(message)
    if loaded[0] is None:
        await message.answer("⚠️ Send a passport photo.")
        return
    result, file_id, _ = loaded
    print(f"read_passport result in rental handler: {result}")

    photo_url = await upload_passport_photo(message, file_id)
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental, passport_text = apply_passport_to_rental(rental, result, photo_url=photo_url)

    await state.update_data(rental=rental, passport_result=result, ai_mode=True, ai_went_passport=True)
    await state.set_state(RentalForm.ai_fill_missing)

    if passport_has_data(result):
        summary = f"🛂 <b>Passport:</b> {passport_text}"
        if rental.get("client_name"):
            summary += f"\n👤 Client name set: <b>{rental['client_name']}</b>"
    else:
        summary = "⚠️ Could not read passport text."
        if photo_url:
            summary += f"\n📎 Photo saved: {photo_url}"
        else:
            summary += "\nPhoto was not saved to Drive."
    await message.answer(summary, parse_mode="HTML")
    await message.answer(format_ai_review(rental), parse_mode="HTML", reply_markup=ai_fill_kb())
    await maybe_ai_advance(message, state)


async def _process_ai_fill_text(message: Message, state: FSMContext, text: str, show_parsing: bool = False):
    if show_parsing:
        await message.answer("⏳ Parsing...")
    parsed = await parse_rental_request(text)
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental = apply_ai_parsed(rental, parsed, raw_text=text)
    if is_pure_price_text(text):
        rental["rental_price"] = parse_idr_value(text)
    missing = missing_ai_required(rental)
    if missing or not is_pure_price_text(text):
        field = detect_field_from_text(text, missing)
        if field:
            rental = apply_detected_field(rental, field, text)
        elif not is_pure_price_text(text):
            src = normalize_source_value(text)
            if src and not rental.get("source"):
                rental["source"] = src
            rental = apply_telegram_from_message(rental, text)
    if rental.get("duration_days") and rental.get("delivery_date"):
        rental["return_date"] = compute_return_date(
            rental["delivery_date"], int(rental["duration_days"])
        )
    update = {"rental": rental, "ai_mode": True, "last_ai_text": text}
    if data.get("initial_ai_rental") is None:
        update["initial_ai_rental"] = copy.deepcopy(rental)
    await state.update_data(**update)
    await state.set_state(RentalForm.ai_fill_missing)
    await message.answer(format_ai_review(rental), parse_mode="HTML", reply_markup=ai_fill_kb())
    await maybe_ai_advance(message, state)


async def _transcribe_and_fill(message: Message, state: FSMContext):
    await message.answer("⏳ Transcribing voice...")
    file = await message.bot.get_file(message.voice.file_id)
    buf = io.BytesIO()
    await message.bot.download_file(file.file_path, buf)
    transcript = await parse_voice_message(buf.getvalue())
    if not transcript:
        await message.answer("⚠️ Could not transcribe. Try again or type text.")
        return
    await message.answer(f"📝 <i>{transcript}</i>", parse_mode="HTML")
    await _process_ai_fill_text(message, state, transcript)


async def goto_step(message: Message, state: FSMContext, step: str):
    uid = message.from_user.id
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    if step == "input_method":
        await state.set_state(RentalForm.input_method)
        await message.answer("🏍 <b>Book bike</b>\n\nChoose input method:", reply_markup=input_method_kb(), parse_mode="HTML")
    elif step == "delivery_date":
        await state.set_state(RentalForm.delivery_date)
        await message.answer("📅 Delivery date:", reply_markup=cancel_kb())
        await message.answer("👇", reply_markup=calendar_kb(prefix="rentcal"))
    elif step == "delivery_time":
        await state.set_state(RentalForm.delivery_time)
        await message.answer(
            "Enter delivery time (e.g. 10:00 or 10:00-11:00 or 10:00-10:30):",
            reply_markup=delivery_time_kb(),
        )
    elif step == "duration":
        await state.set_state(RentalForm.duration)
        await message.answer("📆 Rental duration:", reply_markup=duration_kb())
    elif step == "bike":
        await state.set_state(RentalForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=rental_bikes_kb())
    elif step == "source":
        await state.set_state(RentalForm.source)
        await message.answer("📣 Source:", reply_markup=source_kb())
    elif step == "client_name":
        await state.set_state(RentalForm.client_name)
        await message.answer("👤 Client name:", reply_markup=back_cancel_kb())
    elif step == "contact_platform":
        await state.set_state(RentalForm.contact_platform)
        await message.answer("📱 Contact platform:", reply_markup=contact_platform_kb())
    elif step == "contact_info":
        await state.set_state(RentalForm.contact_info)
        data = await state.get_data()
        platform = data.get("rental", {}).get("contact_platform", "")
        await message.answer(f"📱 Enter {platform} contact:", reply_markup=back_cancel_kb())
    elif step == "instructor":
        await state.set_state(RentalForm.instructor)
        await message.answer("👨‍🏫 Instructor:", reply_markup=instructor_kb())
    elif step == "location":
        await state.set_state(RentalForm.location)
        await message.answer("📍 Location:", reply_markup=location_kb())
    elif step == "price":
        await state.set_state(RentalForm.price)
        await message.answer("💵 Rental price (IDR):", reply_markup=back_cancel_kb())
    elif step == "helmets":
        await state.set_state(RentalForm.helmets)
        await message.answer("🪖 Helmets:", reply_markup=helmets_kb())
    elif step == "insurance":
        await state.set_state(RentalForm.insurance)
        await message.answer("🛡 Insurance:", reply_markup=insurance_kb())
    elif step == "extra_more":
        await state.set_state(RentalForm.extra_more)
        await message.answer("➕ Extra charges:", reply_markup=extra_kb())
    elif step == "passport":
        await state.set_state(RentalForm.passport)
        await message.answer("🛂 Send passport photo or skip:", reply_markup=passport_kb())
    elif step == "comment":
        await state.set_state(RentalForm.comment)
        await message.answer("💬 Comment:", reply_markup=skip_comment_kb())
    elif step == "submenu":
        await state.clear()
        await message.answer("🏍 <b>Bike Rental</b>", reply_markup=rental_submenu_kb(), parse_mode="HTML")


STEP_BACK = {
    "delivery_date": "input_method",
    "delivery_time": "delivery_date",
    "duration": "delivery_time",
    "duration_custom": "duration",
    "bike": "duration",
    "source": "bike",
    "client_name": "source",
    "contact_platform": "client_name",
    "contact_info": "contact_platform",
    "instructor": "contact_info",
    "location": "instructor",
    "location_text": "location",
    "price": "location",
    "helmets": "price",
    "insurance": "helmets",
    "insurance_cost": "insurance",
    "extra_name": "insurance",
    "extra_amount": "extra_name",
    "extra_more": "insurance",
    "passport": "extra_more",
    "passport_confirm": "passport",
    "comment": "passport",
    "confirm": "comment",
}


async def handle_back(message: Message, state: FSMContext):
    current = await state.get_state()
    if not current:
        await goto_step(message, state, "submenu")
        return
    step = current.split(":")[-1]
    if step == "ai_input":
        await goto_step(message, state, "input_method")
        return
    if step == "ai_fill_missing":
        await goto_step(message, state, "ai_input")
        return
    if step == "ai_helmets" or step == "ai_helmets_custom":
        await state.set_state(RentalForm.ai_fill_missing)
        data = await state.get_data()
        rental = data.get("rental", default_rental_data())
        await message.answer(format_ai_review(rental), parse_mode="HTML", reply_markup=ai_fill_kb())
        return
    if step == "ai_comment":
        await state.set_state(RentalForm.ai_helmets)
        await message.answer("🪖 Helmets:", reply_markup=helmets_kb())
        return
    prev = STEP_BACK.get(step, "submenu")
    await goto_step(message, state, prev)


# ─── Submenu ───────────────────────────────────────────────────

@router.message(F.text == "🏍 Bike Rental")
async def rental_menu(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await state.clear()
    await message.answer("🏍 <b>Bike Rental</b>", reply_markup=rental_submenu_kb(), parse_mode="HTML")


@router.message(F.text == "« Back")
async def rental_back_to_manager(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    current = await state.get_state()
    if current and current.startswith("RentalForm:"):
        await handle_back(message, state)
        return
    await state.clear()
    is_superadmin = MANAGERS.get(message.from_user.id, {}).get("superadmin", False)
    await message.answer("👔 <b>Manager panel</b>", reply_markup=manager_menu_kb(is_superadmin=is_superadmin), parse_mode="HTML")


@router.message(F.text == "📋 Book bike")
async def book_bike_start(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await state.clear()
    await state.update_data(rental=default_rental_data())
    await goto_step(message, state, "input_method")


@router.message(F.text == "⚠️ Bike issues")
async def bike_issues(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    try:
        rows = get_sheet(SHEET_BIKE_ISSUES).get_all_values()[1:]
    except Exception as e:
        await message.answer(f"⚠️ Could not load issues: {e}")
        return
    open_issues = [r for r in rows if len(r) > ISS_COL_STATUS and str(r[ISS_COL_STATUS]).lower() not in ("resolved", "closed", "done")]
    if not open_issues:
        await message.answer(
            "✅ No open bike issues.\n\n"
            "To report: tap <b>⚠️ Report bike issue</b> in the main menu.",
            parse_mode="HTML",
        )
        return
    lines = ["⚠️ <b>Bike issues</b>\n"]
    for r in open_issues[:15]:
        date = r[ISS_COL_DATE] if len(r) > ISS_COL_DATE else "—"
        bike = r[ISS_COL_BIKE] if len(r) > ISS_COL_BIKE else "—"
        desc = r[ISS_COL_DESCRIPTION] if len(r) > ISS_COL_DESCRIPTION else "—"
        status = r[ISS_COL_STATUS] if len(r) > ISS_COL_STATUS else "—"
        lines.append(f"• {date} | {bike} | {status}\n  {desc[:80]}")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── Step 1: input method ──────────────────────────────────────

@router.message(RentalForm.input_method)
async def rental_input_method(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "submenu")
        return
    if "Voice" in text or "AI" in text:
        await state.set_state(RentalForm.ai_input)
        await message.answer(
            "🎤 Send voice or text with booking details.\nI'll fill what I can.",
            reply_markup=back_cancel_kb(),
        )
        return
    if "manually" in text.lower():
        await goto_step(message, state, "delivery_date")
        return
    await message.answer("Choose an option from the menu.")


@router.message(RentalForm.ai_input, F.voice)
async def rental_ai_voice(message: Message, state: FSMContext):
    file = await message.bot.get_file(message.voice.file_id)
    buf = io.BytesIO()
    await message.bot.download_file(file.file_path, buf)
    transcript = await parse_voice_message(buf.getvalue())
    if not transcript:
        await message.answer("⚠️ Could not transcribe. Try again or type text.")
        return
    await message.answer(f"📝 <i>{transcript}</i>", parse_mode="HTML")
    await _process_ai_fill_text(message, state, transcript, show_parsing=True)


@router.message(RentalForm.ai_input, F.photo)
async def rental_ai_input_photo(message: Message, state: FSMContext):
    await _process_ai_passport_photo(message, state)


@router.message(RentalForm.ai_input, F.document)
async def rental_ai_input_document(message: Message, state: FSMContext):
    if message.document and (message.document.mime_type or "").startswith("image/"):
        await _process_ai_passport_photo(message, state)
    else:
        await message.answer("⚠️ Send a passport photo or type/voice your booking details.")


@router.message(RentalForm.ai_input)
async def rental_ai_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    await _process_ai_fill_text(message, state, text, show_parsing=True)


@router.message(RentalForm.ai_fill_missing, F.voice)
async def rental_ai_fill_voice(message: Message, state: FSMContext):
    await _transcribe_and_fill(message, state)


@router.message(RentalForm.ai_fill_missing, F.photo)
async def rental_ai_fill_photo(message: Message, state: FSMContext):
    await _process_ai_passport_photo(message, state)


@router.message(RentalForm.ai_fill_missing, F.document)
async def rental_ai_fill_document(message: Message, state: FSMContext):
    if message.document and (message.document.mime_type or "").startswith("image/"):
        await _process_ai_passport_photo(message, state)
    else:
        await message.answer("⚠️ Send a passport photo.")


@router.message(RentalForm.ai_fill_missing)
async def rental_ai_fill(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "📚 Teach AI":
        return
    await _process_ai_fill_text(message, state, text)


@router.message(RentalForm.ai_helmets)
async def ai_step_helmets(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "Other":
        await state.set_state(RentalForm.ai_helmets_custom)
        await message.answer("🪖 Enter helmets:", reply_markup=back_cancel_kb())
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["helmets"] = text
    await state.update_data(rental=rental, ai_helmets_done=True)
    await state.set_state(RentalForm.ai_comment)
    await message.answer("💬 Comment:", reply_markup=skip_comment_kb())


@router.message(RentalForm.ai_helmets_custom)
async def ai_step_helmets_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(RentalForm.ai_helmets)
        await message.answer("🪖 Helmets:", reply_markup=helmets_kb())
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["helmets"] = text
    await state.update_data(rental=rental, ai_helmets_done=True)
    await state.set_state(RentalForm.ai_comment)
    await message.answer("💬 Comment:", reply_markup=skip_comment_kb())


@router.message(RentalForm.ai_comment)
async def ai_step_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["comment"] = "" if text == "⏭ Skip" else text
    await state.update_data(rental=rental, ai_comment_done=True)
    await show_confirm(message, state)


# ─── Calendar (rentcal) ────────────────────────────────────────

@router.callback_query(F.data.startswith("rentcal:"))
async def rental_calendar(call: CallbackQuery, state: FSMContext):
    parts = call.data.split(":")
    action = parts[1]
    if action == "ignore":
        await call.answer()
        return
    if action == "cancel":
        await call.message.delete()
        uid = call.from_user.id
        await state.clear()
        is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
        await call.message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=is_superadmin))
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await goto_step(call.message, state, "input_method")
        await call.answer()
        return
    if action == "day":
        date_str = parts[2]
        data = await state.get_data()
        rental = data.get("rental", default_rental_data())
        rental["delivery_date"] = date_str
        if rental.get("duration_days"):
            rental["return_date"] = compute_return_date(date_str, int(rental["duration_days"]))
        await state.update_data(rental=rental)
        try:
            await call.message.delete()
        except Exception:
            pass
        await goto_step(call.message, state, "delivery_time")
        await call.answer()
        return
    if action in ("prev", "next"):
        year, month = int(parts[2]), int(parts[3])
        if action == "prev":
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        else:
            month += 1
            if month == 13:
                month, year = 1, year + 1
        await call.message.edit_reply_markup(reply_markup=calendar_kb(year, month, prefix="rentcal"))
        await call.answer()


# ─── Manual steps ──────────────────────────────────────────────

@router.message(RentalForm.delivery_time)
async def step_delivery_time(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    if "Set later" in text:
        rental["delivery_time"] = "Set later"
    else:
        rental["delivery_time"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "duration")


@router.message(RentalForm.duration)
async def step_duration(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "Custom":
        await state.set_state(RentalForm.duration_custom)
        await message.answer(
            "📆 Enter duration (e.g. 14 days, 2 months, 60):",
            reply_markup=back_cancel_kb(),
        )
        return
    days_map = {"7 days": 7, "10 days": 10, "14 days": 14, "30 days": 30, "1 month": 30}
    days = days_map.get(text) or parse_duration_from_text(text)
    if not days:
        await message.answer("Choose duration from buttons or type e.g. 14 days / 2 months.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["duration_days"] = days
    if rental.get("delivery_date"):
        rental["return_date"] = compute_return_date(rental["delivery_date"], days)
    await state.update_data(rental=rental)
    await goto_step(message, state, "bike")


@router.message(RentalForm.duration_custom)
async def step_duration_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "duration")
        return
    days = parse_duration_from_text(text)
    if not days:
        digits = "".join(c for c in text if c.isdigit())
        if digits and len(digits) <= 3:
            days = int(digits)
    if not days:
        await message.answer("Enter duration like 14 days, 2 months, or 60.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["duration_days"] = days
    if rental.get("delivery_date"):
        rental["return_date"] = compute_return_date(rental["delivery_date"], days)
    await state.update_data(rental=rental)
    await goto_step(message, state, "bike")


@router.message(RentalForm.bike)
async def step_bike(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["bike"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "source")


@router.message(RentalForm.source)
async def step_source(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text not in ("Ride&Joy", "TravelAsk"):
        await message.answer("Choose Ride&Joy or TravelAsk.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["source"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "client_name")


@router.message(RentalForm.client_name)
async def step_client_name(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["client_name"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "contact_platform")


@router.message(RentalForm.contact_platform)
async def step_contact_platform(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    allowed = {"WhatsApp", "Instagram", "Facebook", "TikTok", "Telegram", "Phone"}
    if text not in allowed:
        await message.answer("Choose contact platform.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["contact_platform"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "contact_info")


@router.message(RentalForm.contact_info)
async def step_contact_info(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["contact_info"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "instructor")


@router.message(RentalForm.instructor)
async def step_instructor(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    if text == "Other":
        await state.set_state(RentalForm.instructor_custom)
        await message.answer("👨‍🏫 Enter instructor name:", reply_markup=back_cancel_kb())
        return
    rental["instructor"] = "Set later" if "Set later" in text else text
    await state.update_data(rental=rental)
    await goto_step(message, state, "location")


@router.message(RentalForm.instructor_custom)
async def step_instructor_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "instructor")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["instructor"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "location")


@router.message(RentalForm.location)
async def step_location(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "📍 Google Maps link":
        await state.set_state(RentalForm.location_text)
        await message.answer("📍 Paste Google Maps link:", reply_markup=back_cancel_kb())
        return
    if text == "🏘 District (text)":
        await state.set_state(RentalForm.location_text)
        await message.answer("🏘 Enter district / area:", reply_markup=back_cancel_kb())
        return
    if text == "✏️ Other":
        await state.set_state(RentalForm.location_text)
        await message.answer("📍 Enter location:", reply_markup=back_cancel_kb())
        return
    await message.answer("Choose location type.")


@router.message(RentalForm.location_text)
async def step_location_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "location")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["location"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "price")


@router.message(RentalForm.price)
async def step_price(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    price = parse_idr_value(text)
    if price <= 0:
        await message.answer("Enter price in IDR.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["rental_price"] = price
    await state.update_data(rental=rental)
    await goto_step(message, state, "helmets")


@router.message(RentalForm.helmets)
async def step_helmets(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "Other":
        await state.set_state(RentalForm.helmets_custom)
        await message.answer("🪖 Enter helmets:", reply_markup=back_cancel_kb())
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["helmets"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "insurance")


@router.message(RentalForm.helmets_custom)
async def step_helmets_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "helmets")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["helmets"] = text
    await state.update_data(rental=rental)
    await goto_step(message, state, "insurance")


@router.message(RentalForm.insurance)
async def step_insurance(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    if text == "With insurance":
        rental["insurance"] = "With insurance"
        await state.update_data(rental=rental)
        await state.set_state(RentalForm.insurance_cost)
        await message.answer("🛡 Insurance cost (IDR):", reply_markup=back_cancel_kb())
        return
    rental["insurance"] = "No insurance"
    rental["insurance_cost"] = ""
    await state.update_data(rental=rental)
    await goto_step(message, state, "extra_more")


@router.message(RentalForm.insurance_cost)
async def step_insurance_cost(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "insurance")
        return
    digits = "".join(c for c in text if c.isdigit())
    if not digits:
        await message.answer("Enter insurance cost in IDR.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["insurance_cost"] = int(digits)
    await state.update_data(rental=rental)
    await goto_step(message, state, "extra_more")


@router.message(RentalForm.extra_more)
async def step_extra_more(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "⏭ Skip":
        await goto_step(message, state, "passport")
        return
    if "Add extra" in text:
        await state.set_state(RentalForm.extra_name)
        await message.answer("➕ Extra charge name:", reply_markup=back_cancel_kb())
        return
    await message.answer("Choose an option.")


@router.message(RentalForm.extra_name)
async def step_extra_name(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "extra_more")
        return
    await state.update_data(extra_name=text)
    await state.set_state(RentalForm.extra_amount)
    await message.answer("💵 Extra charge amount (IDR):", reply_markup=back_cancel_kb())


@router.message(RentalForm.extra_amount)
async def step_extra_amount(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(RentalForm.extra_name)
        data = await state.get_data()
        await message.answer("➕ Extra charge name:", reply_markup=back_cancel_kb())
        return
    digits = "".join(c for c in text if c.isdigit())
    if not digits:
        await message.answer("Enter amount in IDR.")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    extras = rental.get("extras_list") or []
    extras.append({"name": data.get("extra_name", "Extra"), "amount": int(digits)})
    rental["extras_list"] = extras
    rental["extra_charges"] = format_extra_charges(rental)
    await state.update_data(rental=rental, extra_name=None)
    await state.set_state(RentalForm.extra_more)
    await message.answer(
        f"✅ Added: {extras[-1]['name']} — {format_idr(extras[-1]['amount'])}\n\nAdd another?",
        reply_markup=extra_kb(),
    )


@router.message(RentalForm.passport, F.photo)
async def step_passport_photo(message: Message, state: FSMContext):
    await _handle_manual_passport_photo(message, state)


@router.message(RentalForm.passport, F.document)
async def step_passport_document(message: Message, state: FSMContext):
    if message.document and (message.document.mime_type or "").startswith("image/"):
        await _handle_manual_passport_photo(message, state)
    else:
        await message.answer("Send a passport photo or tap Skip.", reply_markup=passport_kb())


async def _handle_manual_passport_photo(message: Message, state: FSMContext):
    await message.answer("⏳ Reading passport...")
    loaded = await load_passport_from_message(message)
    if loaded[0] is None:
        await message.answer("⚠️ Send a passport photo.", reply_markup=passport_kb())
        return
    result, file_id, _ = loaded
    photo_url = await upload_passport_photo(message, file_id)
    passport_text = format_passport_from_result(result)
    await state.update_data(
        passport_draft=passport_text,
        passport_result=result,
        passport_photo_url=photo_url,
    )
    await state.set_state(RentalForm.passport_confirm)
    lines = [f"🛂 <b>Passport data:</b>\n{passport_text}"]
    if photo_url:
        lines.append(f"\n📎 Photo saved to Drive.")
    elif not passport_has_data(result):
        lines.append("\n⚠️ Could not read passport text. Photo not saved to Drive.")
    await message.answer("\n".join(lines), parse_mode="HTML", reply_markup=passport_confirm_kb())


@router.message(RentalForm.passport)
async def step_passport(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    if text == "⏭ Skip":
        data = await state.get_data()
        rental = data.get("rental", default_rental_data())
        rental["passport"] = ""
        rental["passport_info"] = ""
        await state.update_data(rental=rental)
        await goto_step(message, state, "comment")
        return
    await message.answer("Send passport photo or tap Skip.", reply_markup=passport_kb())


@router.message(RentalForm.passport_confirm)
async def step_passport_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "passport")
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    if text == "⏭ Skip":
        rental["passport"] = ""
        rental["passport_info"] = ""
    elif text == "✏️ Edit passport":
        await goto_step(message, state, "passport")
        return
    else:
        result = data.get("passport_result") or {}
        photo_url = data.get("passport_photo_url") or ""
        rental, _ = apply_passport_to_rental(rental, result, photo_url=photo_url)
        if not passport_has_data(result) and not photo_url:
            draft = data.get("passport_draft", "")
            rental["passport"] = draft
            rental["passport_info"] = draft
    await state.update_data(rental=rental)
    await goto_step(message, state, "comment")


@router.message(RentalForm.comment)
async def step_comment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await handle_back(message, state)
        return
    data = await state.get_data()
    rental = data.get("rental", default_rental_data())
    rental["comment"] = "" if text == "⏭ Skip" else text
    await state.update_data(rental=rental)
    await show_confirm(message, state)


# ─── Confirm ───────────────────────────────────────────────────

@router.message(RentalForm.confirm, F.text == "✅ Confirm")
async def rental_confirm(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    rental = data.get("rental", {})
    rental_id = get_next_rental_id()
    today = datetime.now().strftime("%d.%m.%Y")
    time = now_time()
    total = calc_total(rental)
    rental["extra_charges"] = format_extra_charges(rental)
    row = {
        "rental_id": rental_id,
        "date_booked": today,
        "added_by": manager_name(uid),
        "bike": rental.get("bike", ""),
        "status": "booked",
        "source": rental.get("source", ""),
        "client_name": rental.get("client_name", ""),
        "passport": format_passport_for_sheet(rental),
        "contact_platform": rental.get("contact_platform", ""),
        "contact_info": rental.get("contact_info", ""),
        "delivery_date": rental.get("delivery_date", ""),
        "delivery_time": rental.get("delivery_time", ""),
        "return_date": rental.get("return_date", ""),
        "duration_days": rental.get("duration_days", ""),
        "instructor": rental.get("instructor", ""),
        "location": rental.get("location", ""),
        "helmets": rental.get("helmets", ""),
        "insurance": rental.get("insurance", ""),
        "insurance_cost": rental.get("insurance_cost", ""),
        "rental_price": rental.get("rental_price", ""),
        "extra_charges": rental.get("extra_charges", ""),
        "total": total,
        "payment_method": "",
        "comment": rental.get("comment", ""),
        "tg_message_id": "",
    }
    await append_rental(row)

    tag = instructor_tag(rental.get("instructor", ""))
    notify = (
        f"🏍 <b>New rental booked</b> <code>{rental_id}</code>\n\n"
        f"👤 {rental.get('client_name', '—')}\n"
        f"🏍 {rental.get('bike', '—')}\n"
        f"📅 {rental.get('delivery_date', '—')} {rental.get('delivery_time', '')}\n"
        f"📆 {rental.get('duration_days', '—')} days → {rental.get('return_date', '—')}\n"
        f"📍 {rental.get('location', '—')}\n"
        f"💵 {format_idr(int(rental.get('rental_price') or 0))} | Total {format_idr(total)}\n"
        f"👨‍🏫 Instructor: {rental.get('instructor', '—')}"
    )
    if tag:
        notify += f"\n{tag}"
    notify += f"\n\n📝 By {manager_name(uid)}"

    sent = await message.bot.send_message(
        chat_id=LESSON_GROUP_CHAT_ID,
        text=notify,
        parse_mode="HTML",
        message_thread_id=RENTAL_THREAD_ID,
    )
    try:
        from utils.sheets import get_sheet as gs, SHEET_RENTALS, RENT_COL_TG_MSG_ID
        ws = gs(SHEET_RENTALS)
        rows = ws.get_all_values()
        for i, r in enumerate(rows):
            if r and r[0] == rental_id:
                ws.update_cell(i + 1, RENT_COL_TG_MSG_ID + 1, str(sent.message_id))
                break
    except Exception as e:
        print(f"rental tg msg id update error: {e}")

    await state.clear()
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    await message.answer(
        f"✅ Rental <code>{rental_id}</code> saved!",
        reply_markup=manager_menu_kb(is_superadmin=is_superadmin),
        parse_mode="HTML",
    )


@router.message(RentalForm.confirm, F.text == "✏️ Edit")
async def rental_edit(message: Message, state: FSMContext):
    await goto_step(message, state, "delivery_date")


@router.message(RentalForm.confirm, F.text == "✅ Remember fix")
async def rental_remember_fix(message: Message, state: FSMContext):
    data = await state.get_data()
    initial = data.get("initial_ai_rental") or {}
    rental = data.get("rental") or {}
    text = data.get("last_ai_text") or ""
    corrections = find_rental_corrections(initial, rental)
    if not corrections:
        await message.answer("✅ AI values match the final booking. Nothing to remember.")
        return
    await state.update_data(pending_corrections=corrections)
    lines = [
        "💾 <b>Remember fix for AI</b>",
        f"<i>{text[:200]}{'…' if len(text) > 200 else ''}</i>\n",
        "Tap ✅ to save what changed:",
    ]
    buttons = []
    for i, c in enumerate(corrections):
        phrase = suggest_phrase_from_text(text, c["rule_field"], c["value"])
        lines.append(f"• {c['label']}: {c['old']} → <b>{c['new']}</b>")
        lines.append(f"  phrase: <i>{phrase}</i>")
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ {c['label']}",
                callback_data=f"remfix:{i}",
            )
        ])
    buttons.append([InlineKeyboardButton(text="✅ Save all fixes", callback_data="remfix:all")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="remfix:cancel")])
    await message.answer(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("remfix:"))
async def rental_remember_fix_action(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    data = await state.get_data()
    corrections = data.get("pending_corrections") or []
    text = data.get("last_ai_text") or ""
    if action == "cancel":
        await call.message.edit_text("Back to confirm.")
        return
    if not corrections:
        await call.message.edit_text("No fixes to save.")
        return
    name = MANAGERS.get(call.from_user.id, {}).get("name", "")
    saved = []
    if action == "all":
        targets = corrections
    else:
        try:
            targets = [corrections[int(action)]]
        except (IndexError, ValueError):
            await call.message.edit_text("Fix not found.")
            return
    for corr in targets:
        rule = save_correction_rule(text, corr, created_by=name)
        saved.append(
            f"✅ If contains <i>{rule['contains']}</i> → "
            f"{FIELD_LABELS.get(rule['field'], rule['field'])} = <b>{rule['value']}</b>"
        )
    await call.message.edit_text(
        "💾 <b>Saved for AI:</b>\n\n" + "\n".join(saved) + "\n\nNext similar message will use these rules.",
        parse_mode="HTML",
    )


@router.message(RentalForm.confirm)
async def rental_confirm_other(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_rental(message, state)
        return
    if text == "⬅️ Back":
        await goto_step(message, state, "comment")
        return
    await message.answer("Tap ✅ Confirm, ✏️ Edit, ✅ Remember fix, or ❌ Cancel.")


@router.message(F.text == "❌ Cancel")
async def cancel_any_rental_state(message: Message, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("RentalForm:"):
        await cancel_rental(message, state)

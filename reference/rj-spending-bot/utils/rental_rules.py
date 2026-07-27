import json
import os
import re
import uuid
from datetime import datetime, timedelta

RULES_FILE = "/root/rjbot/rental_parse_rules.json"
LOCAL_RULES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "rental_parse_rules.json")

FIELD_LABELS = {
    "delivery_date": "Delivery date",
    "delivery_time": "Delivery time",
    "duration_days": "Duration (days)",
    "price": "Price (IDR)",
    "helmets": "Helmets",
    "insurance": "Insurance",
    "location": "Location",
    "bike_name": "Bike",
    "source": "Source",
    "contact_info": "Contact info",
}

DEFAULT_RULES = {"version": 1, "field_rules": []}

RENTAL_TO_RULE_FIELD = {
    "location": "location",
    "rental_price": "price",
    "bike": "bike_name",
    "source": "source",
    "delivery_date": "delivery_date",
    "delivery_time": "delivery_time",
    "duration_days": "duration_days",
    "helmets": "helmets",
    "insurance": "insurance",
    "contact_info": "contact_info",
}

BALI_LOCATIONS = [
    "ubud", "убуд", "canggu", "чангу", "seminyak", "семиньяк",
    "kuta", "кута", "sanur", "санур", "nusa dua", "uluwatu",
    "denpasar", "денпасар", "jimbaran", "джимbaran", "legian",
]


def _rules_path() -> str:
    if os.path.exists(RULES_FILE):
        return RULES_FILE
    return LOCAL_RULES_FILE


def load_rules() -> dict:
    path = _rules_path()
    if not os.path.exists(path):
        save_rules(DEFAULT_RULES.copy())
        return DEFAULT_RULES.copy()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("version", 1)
    data.setdefault("field_rules", [])
    return data


def save_rules(rules: dict) -> None:
    path = _rules_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2, ensure_ascii=False)


def add_field_rule(contains: str, field: str, value: str, created_by: str = "") -> dict:
    normalized, err = normalize_rule_value(field, value)
    if err:
        raise ValueError(err)
    rules = load_rules()
    rule = {
        "id": uuid.uuid4().hex[:8],
        "contains": contains.strip().lower(),
        "field": field,
        "value": normalized,
        "created_by": created_by,
    }
    rules["field_rules"].append(rule)
    save_rules(rules)
    return rule


def normalize_rule_value(field: str, value: str):
    raw = (value or "").strip()
    if not raw:
        return None, "Value cannot be empty."
    if field == "price":
        if re.search(r"[a-zA-Zа-яА-Я]", raw):
            return None, "For Price send number only, e.g. 5000000"
        digits = re.sub(r"[^\d]", "", raw)
        if len(digits) < 4:
            return None, "For Price send number only, e.g. 5000000"
        return str(int(digits)), None
    if field == "duration_days":
        digits = re.sub(r"[^\d]", "", raw)
        if not digits:
            return None, "For Duration send days number, e.g. 60"
        return str(int(digits)), None
    if field == "helmets":
        digits = re.sub(r"[^\d]", "", raw)
        if digits not in ("0", "1", "2", "3"):
            return None, "Helmets: number 0–3 only"
        return digits, None
    if field == "source":
        sl = raw.lower()
        if "travel" in sl:
            return "TravelAsk", None
        if any(x in sl for x in ("ride", "joy", "rj", "р&дж", "райд")):
            return "Ride&Joy", None
        if raw in ("Ride&Joy", "TravelAsk"):
            return raw, None
        return None, "Source must be Ride&Joy or TravelAsk"
    if field == "insurance":
        sl = raw.lower()
        if sl in ("false", "0", "no", "none", "без", "no insurance", "без страховки"):
            return "No insurance", None
        if sl in ("true", "1", "yes", "with", "with insurance", "со страховкой"):
            return "With insurance", None
    return raw, None


def normalize_rule_phrase(field: str, phrase: str):
    p = (phrase or "").strip()
    if len(p) < 2:
        return None, "Phrase too short."
    if field == "price" and ("=" in p or len(p) > 40):
        return None, "For Price use a short phrase only, e.g. 5 миллионов"
    return p.lower(), None


def delete_field_rule(rule_id: str) -> bool:
    rules = load_rules()
    before = len(rules["field_rules"])
    rules["field_rules"] = [r for r in rules["field_rules"] if r.get("id") != rule_id]
    if len(rules["field_rules"]) == before:
        return False
    save_rules(rules)
    return True


def _normalize_rental_value(key: str, val) -> str:
    if val is None or str(val).strip() == "":
        return ""
    if key in ("rental_price", "duration_days", "insurance_cost"):
        try:
            return str(int(val))
        except (TypeError, ValueError):
            return str(val).strip()
    return str(val).strip()


def find_rental_corrections(initial: dict, current: dict) -> list:
    corrections = []
    for rental_key, rule_field in RENTAL_TO_RULE_FIELD.items():
        old = _normalize_rental_value(rental_key, initial.get(rental_key))
        new = _normalize_rental_value(rental_key, current.get(rental_key))
        if old != new and new:
            corrections.append({
                "rental_key": rental_key,
                "rule_field": rule_field,
                "label": FIELD_LABELS.get(rule_field, rule_field),
                "old": old or "—",
                "new": new,
                "value": current.get(rental_key),
            })
    return corrections


def suggest_phrase_from_text(text: str, rule_field: str, value) -> str:
    if not text:
        return str(value).strip().lower()[:40]
    lower = text.lower()
    val = str(value).strip()
    val_lower = val.lower()
    if val_lower and val_lower in lower:
        idx = lower.find(val_lower)
        start = max(0, lower.rfind(" ", 0, max(idx - 1, 0)))
        end = min(len(text), idx + len(val) + 20)
        snippet = text[start:end].strip(" ,.;")
        words = snippet.split()
        if len(words) > 6:
            snippet = " ".join(words[:6])
        if len(snippet) >= 2:
            return snippet.lower()
    if rule_field == "location":
        for place in BALI_LOCATIONS:
            if place in lower:
                return place
    if rule_field == "price":
        m = re.search(
            r"(\d[\d\s.,]*\s*(?:млн|mln|million|jt|juta|idr|rp|руб|₽)?|\d[\d\s.,]{4,})",
            lower,
        )
        if m:
            return m.group(1).strip()
    if rule_field == "bike_name":
        m = re.search(r"\b(nmax|enmax|scoopy|fazzio|lexi)[\s\d\w-]*", lower)
        if m:
            return m.group(0).strip()
    if rule_field == "duration_days" and re.search(r"месяц|month|мес", lower):
        m = re.search(r"[\w\d]+\s*(?:месяц|month|months|мес)", lower)
        if m:
            return m.group(0).strip()
    return val_lower[:40] if val_lower else lower[:40]


def save_correction_rule(text: str, correction: dict, created_by: str = "") -> dict:
    phrase = suggest_phrase_from_text(text, correction["rule_field"], correction["value"])
    value = correction["value"]
    if correction["rule_field"] == "price":
        value = str(int(value or 0))
    elif correction["rule_field"] == "duration_days":
        value = str(int(value or 0))
    else:
        value = str(value).strip()
    return add_field_rule(phrase, correction["rule_field"], value, created_by=created_by)


def format_rules_list() -> str:
    rules = load_rules()
    items = rules.get("field_rules", [])
    if not items:
        return "📚 <b>AI parsing rules</b>\n\nNo custom rules yet.\nTap ➕ Add rule to teach the bot."
    lines = ["📚 <b>AI parsing rules</b>\n"]
    for r in items:
        field = FIELD_LABELS.get(r.get("field", ""), r.get("field", "?"))
        lines.append(
            f"• If contains <i>{r.get('contains', '')}</i>\n"
            f"  → {field} = <b>{r.get('value', '')}</b>"
        )
    return "\n".join(lines)


def parse_relative_delivery_date(text: str):
    if not text:
        return None
    t = text.lower()
    today = datetime.now().date()
    if re.search(r"\bзавтра\b", t):
        return (today + timedelta(days=1)).strftime("%d.%m.%Y")
    if re.search(r"\bпослезавтра\b", t):
        return (today + timedelta(days=2)).strftime("%d.%m.%Y")
    if re.search(r"\bсегодня\b", t):
        return today.strftime("%d.%m.%Y")
    return None


def parse_delivery_time_from_text(text: str):
    if not text:
        return None
    m = re.search(
        r"(?:с|from)\s*(\d{1,2})[.:](\d{2})\s*(?:до|to|-)\s*(\d{1,2})[.:](\d{2})",
        text,
        re.I,
    )
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}-{int(m.group(3)):02d}:{m.group(4)}"
    m = re.search(r"\b(\d{1,2})[.:](\d{2})\s*[-–]\s*(\d{1,2})[.:](\d{2})\b", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}-{int(m.group(3)):02d}:{m.group(4)}"
    return None


def is_time_confused_date(date_str: str, text: str) -> bool:
    if not date_str or not text:
        return False
    m = re.search(
        r"(?:с|from)\s*(\d{1,2})[.:](\d{2})\s*(?:до|to|-)\s*(\d{1,2})[.:](\d{2})",
        text,
        re.I,
    )
    if not m:
        return False
    time_fragment = f"{int(m.group(1)):02d}.{m.group(2)}"
    return time_fragment in str(date_str)


def extract_price_from_text(text: str):
    if not text:
        return None
    t = text.lower()
    if re.search(r"(?:млн|mln|million|jt|juta)", t):
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:млн|mln|million|jt|juta)", t)
        if m:
            return int(float(m.group(1).replace(",", ".")) * 1_000_000)
    if re.search(r"(?:\bк\b|\bk\b|тыс|rb|ribu)", t):
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:\bк\b|\bk\b|тыс|rb|ribu)", t)
        if m:
            return int(float(m.group(1).replace(",", ".")) * 1_000)
    m = re.search(r"(?:стоимость|цена|price|cost)\s*[:\-]?\s*(\d[\d\s.,]*)", t)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if len(digits) >= 4:
            return int(digits)
    blocks = re.findall(r"\d+", t)
    if len(blocks) >= 2 and not re.search(
        r"(?:с|from)\s*\d{1,2}[.:]\d{2}\s*(?:до|to|-)\s*\d{1,2}[.:]\d{2}", t, re.I
    ):
        joined = "".join(blocks)
        if len(joined) >= 5 or len(blocks) >= 3:
            return int(joined)
    return None


def extract_location_from_text(text: str):
    if not text:
        return None
    lower = text.lower()
    for place in BALI_LOCATIONS:
        if place in lower:
            return place.title() if place.isascii() else place.capitalize()
    m = re.search(r"(?:в|in|to|deliver(?:y)?\s+to)\s+([A-Za-zА-Яа-яЁё\s-]{3,30})", text, re.I)
    if m:
        loc = m.group(1).strip(" .,;")
        stop_words = ("enmax", "nmax", "scoopy", "fazzio", "шлем", "паспорт", "клиент")
        if loc and not any(w in loc.lower() for w in stop_words):
            return loc.title()
    return None


def _coerce_rule_value(field: str, value: str):
    normalized, _ = normalize_rule_value(field, str(value))
    if normalized is None:
        return value
    if field in ("price", "duration_days", "helmets"):
        digits = re.sub(r"[^\d]", "", str(normalized))
        return int(digits) if digits else value
    if field == "insurance":
        sl = str(normalized).strip().lower()
        if sl in ("false", "0", "no", "none", "без", "no insurance", "без страховки"):
            return False
        if sl in ("true", "1", "yes", "with", "with insurance", "со страховкой"):
            return True
    return normalized


def apply_custom_field_rules(parsed: dict, text: str) -> dict:
    if not text:
        return parsed
    lower = text.lower()
    for rule in load_rules().get("field_rules", []):
        needle = str(rule.get("contains", "")).strip().lower()
        field = rule.get("field")
        value = rule.get("value")
        if not needle or not field or value is None or str(value).strip() == "":
            continue
        if needle in lower:
            parsed[field] = _coerce_rule_value(field, str(value))
    return parsed


def apply_builtin_rules(parsed: dict, text: str) -> dict:
    if not text:
        return parsed

    rel_date = parse_relative_delivery_date(text)
    if rel_date:
        parsed["delivery_date"] = rel_date
    elif parsed.get("delivery_date") and is_time_confused_date(str(parsed["delivery_date"]), text):
        parsed["delivery_date"] = None
        rel_date = parse_relative_delivery_date(text)
        if rel_date:
            parsed["delivery_date"] = rel_date

    delivery_time = parse_delivery_time_from_text(text)
    if delivery_time:
        parsed["delivery_time"] = delivery_time

    if not parsed.get("price"):
        price = extract_price_from_text(text)
        if price:
            parsed["price"] = price
    else:
        text_price = extract_price_from_text(text)
        if text_price and text_price > int(parsed.get("price") or 0):
            parsed["price"] = text_price

    if not parsed.get("location"):
        location = extract_location_from_text(text)
        if location:
            parsed["location"] = location

    return parsed


def apply_rental_rules(parsed: dict, text: str) -> dict:
    result = dict(parsed or {})
    result = apply_builtin_rules(result, text)
    result = apply_custom_field_rules(result, text)
    return result

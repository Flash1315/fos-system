import asyncio
import base64
import json
import os
import re
from typing import Optional
from google import genai
from google.genai import types
from openai import OpenAI
from config import GEMINI_API_KEY

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
_openai_client = None
MODEL = "gemini-2.5-flash"


def _get_openai_client():
    """Lazy init — bot must start even without OPENAI_API_KEY (Whisper/passport fallback only)."""
    global _openai_client
    if not OPENAI_API_KEY:
        return None
    if _openai_client is None:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client

PASSPORT_SAFETY_SETTINGS = [
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
    types.SafetySetting(category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=types.HarmBlockThreshold.BLOCK_NONE),
]


def _extract_gemini_text(response) -> str:
    try:
        text = getattr(response, "text", None)
        if text and str(text).strip():
            return str(text).strip()
    except Exception:
        pass
    chunks = []
    for cand in getattr(response, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for part in getattr(content, "parts", None) or []:
            t = getattr(part, "text", None)
            if t and str(t).strip():
                chunks.append(str(t).strip())
    return "\n".join(chunks)


def _log_gemini_diagnostics(response, label: str = "passport") -> None:
    try:
        prompt_fb = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_fb, "block_reason", None) if prompt_fb else None
        if block_reason:
            print(f"Gemini {label} prompt blocked: {block_reason}")
        for i, cand in enumerate(getattr(response, "candidates", None) or []):
            finish = getattr(cand, "finish_reason", None)
            if finish and str(finish) not in ("STOP", "FinishReason.STOP", "FinishReasonStop"):
                print(f"Gemini {label} candidate {i} finish_reason: {finish}")
    except Exception as e:
        print(f"Gemini {label} diagnostics error: {e}")


def _detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b"\x89PNG":
        return "image/png"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"

async def read_odometer_photo(image_bytes: bytes) -> dict:
    """Read odometer and fuel level from photo."""
    try:
        loop = asyncio.get_event_loop()
        def _call():
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                    "This is a motorcycle odometer photo. Extract: 1) Total odometer reading in km (the main large number, NOT trip/daily). 2) Fuel level in bars. Reply ONLY in JSON: {\"odometer\": 12345, \"fuel_bar\": 3}"
                ]
            )
            return response.text
        text = await loop.run_in_executor(None, _call)
        import json, re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return json.loads(match.group())
        return {"odometer": None, "fuel_bar": None, "raw": text}
    except Exception as e:
        print(f"Gemini odometer error: {e}")
        return {"odometer": None, "fuel_bar": None, "raw": str(e)}

RECEIPT_FULL_PROMPT = (
    "This is a business expense receipt photo (Indonesia or international).\n"
    "Extract as much as possible. Reply ONLY with valid JSON:\n"
    '{"amount": 45000, "place": "Yamaha Dealer", "items": "Oil change, filter replacement", '
    '"receipt_date": "26.05.2026", "currency": "IDR"}\n'
    "Rules:\n"
    "- amount: final TOTAL paid in IDR as a number (no dots/commas in JSON number)\n"
    "- place: shop/dealer/station name\n"
    "- items: what was bought or service done; if text is Indonesian translate items to English\n"
    "- receipt_date: dd.mm.yyyy from the receipt, or null\n"
    "- currency: IDR unless clearly another currency\n"
    "- use null for any field you cannot read\n"
    "- if the image is too blurry or unreadable, return all fields null except currency IDR"
)

RECEIPT_FULL_EMPTY = {
    "amount": None,
    "place": None,
    "items": None,
    "receipt_date": None,
    "currency": "IDR",
}


def _parse_receipt_json(text: str) -> dict:
    if not text:
        return dict(RECEIPT_FULL_EMPTY)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return dict(RECEIPT_FULL_EMPTY)
    result = json.loads(match.group())
    amount = result.get("amount")
    if amount is not None:
        try:
            amount = int(re.sub(r"[^\d]", "", str(amount)) or 0) or None
        except (TypeError, ValueError):
            amount = None
    return {
        "amount": amount,
        "place": result.get("place") or None,
        "items": result.get("items") or None,
        "receipt_date": result.get("receipt_date") or None,
        "currency": result.get("currency") or "IDR",
    }


async def _read_receipt_gemini(image_bytes: bytes, prompt: str) -> dict:
    if not GEMINI_API_KEY or client is None:
        return {**RECEIPT_FULL_EMPTY, "error": "GEMINI_API_KEY not set", "raw": "no gemini key"}
    mime_type = _detect_image_mime(image_bytes)
    try:
        loop = asyncio.get_event_loop()

        def _call():
            return client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    safety_settings=PASSPORT_SAFETY_SETTINGS,
                ),
            )

        response = await loop.run_in_executor(None, _call)
        _log_gemini_diagnostics(response, "receipt")
        text = _extract_gemini_text(response)
        print(f"Gemini receipt raw response: {text!r}")
        if not text:
            return {**RECEIPT_FULL_EMPTY, "error": "empty_response", "raw": str(response)}
        parsed = _parse_receipt_json(text)
        parsed["raw"] = text
        return parsed
    except Exception as e:
        print(f"Gemini receipt error: {e}")
        return {**RECEIPT_FULL_EMPTY, "error": str(e), "raw": str(e)}


async def read_receipt_amount(image_bytes: bytes) -> dict:
    """Read total amount from receipt photo."""
    prompt = (
        "This is a receipt photo. Extract the TOTAL amount in IDR. "
        'Reply ONLY in JSON: {"amount": 25000}'
    )
    result = await _read_receipt_gemini(image_bytes, prompt)
    return {
        "amount": result.get("amount"),
        "raw": result.get("raw"),
        "error": result.get("error"),
    }


async def read_receipt_full(image_bytes: bytes) -> dict:
    """Read place, items, amount, and date from a receipt photo."""
    return await _read_receipt_gemini(image_bytes, RECEIPT_FULL_PROMPT)

PASSPORT_EMPTY = {
    "name": None, "surname": None, "given_names": None,
    "passport_number": None, "issue_date": None,
    "dob": None, "expiry": None,
}

PASSPORT_PROMPT = (
    "Legitimate motorcycle rental business: extract passport data page fields from this photo.\n"
    "Photo may be compressed, angled, forwarded, or partially cropped.\n"
    "Read printed text AND the MRZ machine-readable zone (two lines at the bottom).\n"
    "Return ONLY valid JSON with these keys (use null if unreadable):\n"
    '{"surname": "IVANOV", "given_names": "IVAN", "name": "IVAN IVANOV", '
    '"passport_number": "123456789", "issue_date": "15.03.2020", '
    '"dob": "01.01.1990", "expiry": "15.03.2030"}\n'
    "Priority fields:\n"
    "1) passport_number — from data page or MRZ line 2 (first 9 chars)\n"
    "2) surname + given_names — latin as printed; Cyrillic names → transliterate to latin\n"
    "3) issue_date — DATE OF ISSUE only (dd.mm.yyyy), NOT expiry\n"
    "4) name — combine given_names + surname if possible\n"
    "Labels may be in any language (Date of issue / Дата выдачи).\n"
)


def _passport_field(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "—", "-"):
        return None
    return s


def _build_passport_name(result: dict) -> Optional[str]:
    name = _passport_field(result.get("name"))
    if name:
        return name.upper()
    given = _passport_field(result.get("given_names"))
    surname = _passport_field(result.get("surname"))
    if given and surname:
        return f"{given} {surname}".upper()
    if surname:
        return surname.upper()
    if given:
        return given.upper()
    return None


def _parse_passport_json(text: str, raw_fallback: str = "") -> dict:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return {**PASSPORT_EMPTY, "raw": raw_fallback or text}
    try:
        parsed = json.loads(match.group())
    except json.JSONDecodeError:
        return {**PASSPORT_EMPTY, "raw": raw_fallback or text}
    result = {**PASSPORT_EMPTY, "raw": raw_fallback or text}
    for src, dst in (
        ("surname", "surname"),
        ("last_name", "surname"),
        ("family_name", "surname"),
        ("given_names", "given_names"),
        ("given_name", "given_names"),
        ("first_name", "given_names"),
        ("name", "name"),
        ("full_name", "name"),
        ("fullName", "name"),
        ("holder_name", "name"),
        ("passport_number", "passport_number"),
        ("number", "passport_number"),
        ("passport_no", "passport_number"),
        ("document_number", "passport_number"),
        ("issue_date", "issue_date"),
        ("date_of_issue", "issue_date"),
        ("issued", "issue_date"),
        ("issue", "issue_date"),
        ("dob", "dob"),
        ("date_of_birth", "dob"),
        ("birth_date", "dob"),
        ("expiry", "expiry"),
        ("expiry_date", "expiry"),
        ("expiration_date", "expiry"),
    ):
        val = _passport_field(parsed.get(src))
        if val and not result.get(dst):
            result[dst] = val
    result["name"] = _build_passport_name(result)
    _parse_mrz_into_result(text, result)
    return result


def _find_mrz_lines(text: str) -> list:
    if not text:
        return []
    lines = [re.sub(r"\s+", "", ln.strip().upper()) for ln in text.splitlines() if ln.strip()]
    mrz_lines = [ln for ln in lines if len(ln) >= 30 and ln.count("<") >= 2]
    if len(mrz_lines) >= 2:
        return mrz_lines[:2]
    compact = re.sub(r"[\s\r\n]+", "", text.upper())
    m = re.search(r"(P<[A-Z0-9<]{42})([A-Z0-9<]{43})", compact)
    if m:
        return [m.group(1), m.group(2)]
    m = re.search(r"P<[A-Z0-9<]{20,}\n?[A-Z0-9<]{20,}", text, re.I)
    if m:
        parts = [seg for seg in re.split(r"[\r\n]+", m.group(0).upper()) if len(seg) >= 30]
        if len(parts) >= 2:
            return parts[:2]
    return []


def _parse_mrz_into_result(text: str, result: dict) -> None:
    if not text:
        return
    mrz_lines = _find_mrz_lines(text)
    if len(mrz_lines) < 2:
        return
    line1, line2 = mrz_lines[0], mrz_lines[1]
    if "<<" in line1:
        parts = line1.split("<<", 1)
        if len(parts) == 2:
            prefix = parts[0].replace("<", " ").strip()
            surname = prefix.split()[-1] if prefix else ""
            given = parts[1].replace("<", " ").strip()
            if surname and not result.get("surname"):
                result["surname"] = surname
            if given and not result.get("given_names"):
                result["given_names"] = given
    if not result.get("passport_number") and len(line2) >= 9:
        doc = line2[:9].replace("<", "").strip()
        if doc and re.search(r"[0-9A-Z]", doc):
            result["passport_number"] = doc
    result["name"] = _build_passport_name(result)


def _passport_needs_fallback(result: dict) -> bool:
    if not _passport_field(result.get("passport_number")):
        return True
    if not _build_passport_name(result):
        return True
    if not _passport_field(result.get("issue_date")):
        return True
    return False


def _merge_passport_results(primary: dict, secondary: dict) -> dict:
    merged = dict(primary or {})
    for key in PASSPORT_EMPTY:
        if not _passport_field(merged.get(key)) and _passport_field((secondary or {}).get(key)):
            merged[key] = secondary[key]
    merged["name"] = _build_passport_name(merged)
    if secondary.get("raw") and not merged.get("name"):
        _parse_mrz_into_result(str(secondary.get("raw", "")), merged)
    return merged


async def _read_passport_gemini(image_bytes: bytes, mime_type: str) -> dict:
    try:
        loop = asyncio.get_event_loop()

        def _call():
            return client.models.generate_content(
                model=MODEL,
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    PASSPORT_PROMPT,
                ],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    safety_settings=PASSPORT_SAFETY_SETTINGS,
                ),
            )

        response = await loop.run_in_executor(None, _call)
        _log_gemini_diagnostics(response)
        text = _extract_gemini_text(response)
        print(f"Gemini passport raw response: {text!r}")
        if not text:
            print(f"Gemini passport empty text, response: {response}")
        result = _parse_passport_json(text, text)
        print(f"Gemini passport parsed JSON: {result}")
        return result
    except Exception as e:
        print(f"Gemini passport error: {e}")
        return {**PASSPORT_EMPTY, "raw": str(e)}


async def _read_passport_openai(image_bytes: bytes, mime_type: str) -> dict:
    if not OPENAI_API_KEY:
        print("OpenAI passport skipped: OPENAI_API_KEY not set")
        return {**PASSPORT_EMPTY, "raw": "no openai key"}
    try:
        loop = asyncio.get_event_loop()

        oai = _get_openai_client()
        if not oai:
            return {**PASSPORT_EMPTY, "raw": "no openai key"}

        def _call():
            b64 = base64.standard_b64encode(image_bytes).decode("ascii")
            response = oai.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PASSPORT_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}", "detail": "high"}},
                    ],
                }],
                max_tokens=500,
            )
            return response.choices[0].message.content or ""

        text = await loop.run_in_executor(None, _call)
        print(f"OpenAI passport raw response: {text!r}")
        return _parse_passport_json(text, text)
    except Exception as e:
        print(f"OpenAI passport error: {e}")
        return {**PASSPORT_EMPTY, "raw": str(e)}


def _finalize_passport_result(*results: dict) -> dict:
    merged = {**PASSPORT_EMPTY, "raw": ""}
    raw_parts = []
    for result in results:
        merged = _merge_passport_results(merged, result or {})
        raw = str((result or {}).get("raw") or "").strip()
        if raw:
            raw_parts.append(raw)
    combined_raw = "\n".join(raw_parts)
    if combined_raw:
        merged["raw"] = combined_raw
        _parse_mrz_into_result(combined_raw, merged)
        merged["name"] = _build_passport_name(merged)
    return merged


async def read_passport(image_bytes: bytes) -> dict:
    """Read passport from phone photo via Gemini + OpenAI merge."""
    if not image_bytes:
        print("Gemini passport error: empty image bytes")
        return {**PASSPORT_EMPTY, "raw": "empty bytes"}
    mime_type = _detect_image_mime(image_bytes)
    print(f"read_passport: {len(image_bytes)} bytes, mime={mime_type}")

    if OPENAI_API_KEY:
        gemini_result, openai_result = await asyncio.gather(
            _read_passport_gemini(image_bytes, mime_type),
            _read_passport_openai(image_bytes, mime_type),
        )
        merged = _finalize_passport_result(gemini_result, openai_result)
        print(f"Passport merged JSON: {merged}")
        return merged

    gemini_result = await _read_passport_gemini(image_bytes, mime_type)
    if _passport_needs_fallback(gemini_result):
        openai_result = await _read_passport_openai(image_bytes, mime_type)
        merged = _finalize_passport_result(gemini_result, openai_result)
        print(f"Passport merged JSON: {merged}")
        return merged
    return _finalize_passport_result(gemini_result)


RIDE_JOY_VARIANTS = (
    "ride joy", "ridejoy", "ride and joy", "brighter joy",
    "райд джой", "райд энд джой", "rj", "р&дж", "ride&joy",
)
TRAVEL_ASK_VARIANTS = (
    "travel ask", "travelask", "травел аск",
)


def _detect_source_from_text(text: str):
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
    sl = cleaned.lower()
    compact = re.sub(r"[\s&\-_]", "", sl)

    rj_compact = {
        "ridejoy", "rideandjoy", "brighterjoy", "райдджой", "райдэндджой",
        "rj", "рдж",
    }
    if compact in rj_compact:
        return "Ride&Joy"

    rj_patterns = (
        r"ride\s*joy", r"ride\s*and\s*joy", r"brighter\s*joy",
        r"райд\s*джой", r"райд\s*энд\s*джой", r"ride\s*&?\s*joy",
        r"\brj\b", r"р\s*&?\s*дж",
    )
    for pat in rj_patterns:
        if re.search(pat, sl, re.I):
            return "Ride&Joy"

    for variant in RIDE_JOY_VARIANTS:
        if variant.replace(" ", "") in compact or variant in sl:
            return "Ride&Joy"

    ta_compact = {"travelask", "травеласк"}
    if compact in ta_compact:
        return "TravelAsk"

    ta_patterns = (r"travel\s*ask", r"travelask", r"травел\s*аск")
    for pat in ta_patterns:
        if re.search(pat, sl, re.I):
            return "TravelAsk"

    for variant in TRAVEL_ASK_VARIANTS:
        if variant.replace(" ", "") in compact or variant in sl:
            return "TravelAsk"

    return None


def _normalize_rental_source(val, full_text=""):
    detected = _detect_source_from_text(full_text) if full_text else None
    if detected:
        return detected
    if val is None:
        return None
    return _detect_source_from_text(str(val))


def _get_rental_bike_list():
    bikes = []
    try:
        from utils.bikes import get_rental_bikes
        bikes.extend(get_rental_bikes())
    except Exception:
        pass
    try:
        from config import BIKES_GPS
        bikes.extend(info["name"] for info in BIKES_GPS.values() if info.get("type") == "rental")
    except Exception:
        pass
    return sorted(set(bikes))


def _match_bike_from_list(name, full_text="", bike_list=None):
    bike_list = bike_list or _get_rental_bike_list()
    if not bike_list:
        return name
    candidates = []
    if name:
        candidates.append(str(name).strip())
    if full_text:
        candidates.append(str(full_text).strip())
    for candidate in candidates:
        cl = candidate.lower()
        for bike in bike_list:
            if bike.lower() == cl:
                return bike
        nums = re.findall(r"\d+", candidate)
        if nums:
            for bike in bike_list:
                bike_nums = re.findall(r"\d+", bike)
                if bike_nums and nums[-1] == bike_nums[-1]:
                    return bike
        for bike in bike_list:
            bl = bike.lower()
            if bl in cl or cl in bl:
                return bike
    return name


def _normalize_duration_days(val, full_text=""):
    text = (full_text or str(val or "")).lower()
    if re.search(r"полтора\s*месяц|полторы\s*месяц", text):
        return 45
    word_months = {
        "один": 1, "one": 1, "два": 2, "two": 2, "три": 3, "three": 3,
        "четыре": 4, "four": 4, "пять": 5, "five": 5, "шесть": 6, "six": 6,
    }
    for word, num in word_months.items():
        if re.search(rf"\b{word}\b\s*(?:месяц|month|months|мес)", text):
            return num * 30
    m = re.search(r"(\d+)\s*(?:месяц|month|months|мес)", text)
    if m:
        return int(m.group(1)) * 30
    if re.search(r"(?<!\d)(?:месяц|month)(?!\w)", text):
        return 30
    m = re.search(r"(\d+)\s*(?:дн|day|days|дней)", text)
    if m:
        return int(m.group(1))
    if val is not None:
        try:
            n = int(str(val).strip())
            if re.search(r"(?:месяц|month|months|мес)", text) and n <= 12:
                return n * 30
            return n
        except (ValueError, TypeError):
            pass
    return None


def _normalize_insurance(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return "No insurance" if not val else "With insurance"
    sl = str(val).strip().lower()
    if sl in ("false", "0", "no", "none", "null", "без страховки", "no insurance", "без"):
        return "No insurance"
    if sl in ("true", "1", "yes", "with insurance", "со страховкой", "with"):
        return "With insurance"
    if "no" in sl or "без" in sl:
        return "No insurance"
    if "with" in sl or "со" in sl or "insurance" in sl:
        return "With insurance"
    return str(val).strip()


def _normalize_helmets(val, full_text=""):
    text = (full_text or str(val or "")).lower()
    word_map = {"один": 1, "one": 1, "два": 2, "two": 2, "три": 3, "three": 3}
    m = re.search(r"(\d+)\s*шлем", text)
    if m:
        return str(int(m.group(1)))
    for word, num in word_map.items():
        if re.search(rf"\b{word}\b\s*шлем", text):
            return str(num)
    if val is not None and str(val).strip():
        return str(val).strip()
    return None


def _normalize_rental_price(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        return int(val)
    raw = str(val).strip()
    blocks = re.findall(r"\d+", raw)
    if len(blocks) >= 2:
        joined = "".join(blocks)
        if len(joined) >= 5:
            return int(joined)
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _extract_telegram_from_text(text: str):
    if not text:
        return None, None
    m = re.search(
        r"(?:она\s+)?(?:из|from|via|через)?\s*(?:telegram|телеграм(?:а|е|у)?)"
        r"[\s,:-]+([A-Za-zА-Яа-яЁё0-9 ._@-]+)",
        text,
        re.I,
    )
    if m:
        info = m.group(1).strip().strip("\"'., ")
        if info:
            return "Telegram", info
    if re.search(r"(?:https?://)?t\.me/\S+|@\w{3,}", text, re.I):
        return "Telegram", text.strip()
    return None, None


async def parse_rental_request(text: str) -> dict:
    """Parse free-text rental request into structured fields."""
    empty = {
        "client_name": None, "delivery_date": None, "duration_days": None,
        "price": None, "helmets": None, "insurance": None, "location": None,
        "bike_name": None, "source": None, "contact_platform": None, "contact_info": None,
    }
    if not text or not text.strip():
        return empty
    bike_list = _get_rental_bike_list()
    bikes_prompt = ", ".join(bike_list) if bike_list else "Nmax 5579, SCOOPY 2719 Green, ..."
    try:
        loop = asyncio.get_event_loop()
        def _call():
            response = client.models.generate_content(
                model=MODEL,
                contents=(
                    "Parse this motorcycle rental booking message. Extract ONLY what is explicitly stated.\n"
                    "Return ONLY valid JSON with these keys (use null if unknown):\n"
                    '{"client_name": "...", "delivery_date": "DD.MM.YYYY", "duration_days": 7, '
                    '"price": 1500000, "helmets": 2, "insurance": false, '
                    '"location": "...", "bike_name": "...", "source": "Ride&Joy" or "TravelAsk", '
                    '"contact_platform": "Telegram", "contact_info": "..."}\n\n'
                    "STRICT field rules — never mix fields:\n"
                    "- delivery_date: ONLY calendar dates DD.MM or DD.MM.YYYY. Words 'дата'/'date' + date → delivery_date.\n"
                    "- duration_days: convert periods to days — '2 месяца'=60, '1 месяц'/'месяц'=30, 'полтора месяца'=45, '7 дней'=7.\n"
                    "- price: ONLY rental amount in IDR as integer. k/тыс/млн/million/jt = price. Never merge date digits into price.\n"
                    "- helmets: integer count. 'два шлема'=2, 'без шлемов'=0.\n"
                    "- insurance: boolean or string. 'без страховки'=false, 'со страховкой'=true.\n"
                    f"- bike_name: MUST be one exact name from this rental bike list: {bikes_prompt}\n"
                    "  Match spoken variants to closest list name (e.g. 'iMac and Max'/'nmax 5579' → 'Nmax 5579').\n"
                    "- source: ONLY exact output 'Ride&Joy' or 'TravelAsk', or null if not found.\n"
                    "  Match by sound/spelling variants in the message:\n"
                    "  Ride&Joy examples → output 'Ride&Joy':\n"
                    "    ride joy, ridejoy, ride and joy, brighter joy,\n"
                    "    райд джой, райд энд джой, rj, RJ, р&дж, ride&joy\n"
                    "  TravelAsk examples → output 'TravelAsk':\n"
                    "    travel ask, travelask, травел аск\n"
                    "  Do NOT set source from Telegram contact names (e.g. 'Brighter Joy' after 'из Телеграма' is contact, not source).\n"
                    "  If nothing similar to the above → source: null.\n"
                    "- location: address, district, or Google Maps link only.\n"
                    "- contact: @username or t.me/ → platform Telegram, info = tag/link.\n"
                    "  If message says 'из Телеграма X' / 'from Telegram X' / 'Telegram X' → platform Telegram, info = X.\n"
                    "- client_name: person's name only.\n\n"
                    f"Message:\n{text}"
                ),
            )
            return response.text
        raw = await loop.run_in_executor(None, _call)
        import json
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return empty
        parsed = json.loads(match.group())
        result = {}
        for key in empty:
            val = parsed.get(key)
            if val is None or str(val).strip().lower() in ("", "null", "none"):
                result[key] = None
            else:
                result[key] = val
        result["source"] = _normalize_rental_source(result.get("source"), text)
        result["price"] = _normalize_rental_price(result.get("price"))
        result["duration_days"] = _normalize_duration_days(result.get("duration_days"), text)
        result["insurance"] = _normalize_insurance(result.get("insurance"))
        result["helmets"] = _normalize_helmets(result.get("helmets"), text)
        result["bike_name"] = _match_bike_from_list(result.get("bike_name"), text, bike_list)
        tg_platform, tg_info = _extract_telegram_from_text(text)
        if tg_platform and tg_info:
            result["contact_platform"] = tg_platform
            result["contact_info"] = tg_info
        elif result.get("contact_info") and re.search(r"(?:https?://)?t\.me/\S+|@\w{3,}", str(result["contact_info"]), re.I):
            result["contact_platform"] = "Telegram"
        elif result.get("contact_platform"):
            cp = str(result["contact_platform"]).strip().lower()
            if cp == "telegram":
                result["contact_platform"] = "Telegram"
        from utils.rental_rules import apply_rental_rules
        result = apply_rental_rules(result, text)
        return result
    except Exception as e:
        print(f"Gemini parse_rental_request error: {e}")
        return empty


async def parse_voice_message(audio_bytes: bytes) -> str:
    oai = _get_openai_client()
    if not oai:
        print("Whisper skipped: OPENAI_API_KEY not set")
        return ""
    try:
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        with open(tmp_path, "rb") as f:
            response = oai.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="ru"
            )
        os.unlink(tmp_path)
        return response.text
    except Exception as e:
        print(f"Whisper error: {e}")
        return ""

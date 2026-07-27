import time
import hashlib
import aiohttp
import logging
from datetime import datetime
from config import WANWAY_APPID, WANWAY_KEY, WANWAY_BASE_URL, BIKES_GPS as BIKES

logger = logging.getLogger(__name__)

_token_cache = {"token": None, "expires_at": 0}


def _md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


async def _get_token() -> str | None:
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]
    ts = int(now)
    signature = _md5(_md5(WANWAY_KEY) + str(ts))
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WANWAY_BASE_URL}/auth",
                json={"appid": WANWAY_APPID, "time": ts, "signature": signature}
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("code") == 0:
                    _token_cache["token"] = data["accessToken"]
                    _token_cache["expires_at"] = now + 5400
                    return _token_cache["token"]
                logger.error(f"WanWay auth failed: {data}")
                return None
    except Exception as e:
        logger.error(f"WanWay auth error: {e}")
        return None


async def get_all_device_status() -> list[dict]:
    token = await _get_token()
    if not token:
        return []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{WANWAY_BASE_URL}/device/status",
                headers={"accessToken": token}
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("code") != 0:
                    return []
                result = []
                for d in data.get("data", []):
                    imei = d.get("imei", "")
                    bike = BIKES.get(imei, {})
                    result.append({
                        "imei": imei,
                        "name": bike.get("name", imei),
                        "type": bike.get("type", "unknown"),
                        "status": d.get("status", ""),
                        "lat": float(d.get("lat", 0)),
                        "lng": float(d.get("lng", 0)),
                        "speed": d.get("speed", 0),
                        "accStatus": d.get("accStatus", False),
                        "gpsTime": d.get("gpsTime", 0),
                        "signalTime": d.get("signalTime", 0),
                        "extVoltage": d.get("extVoltage", 0),
                        "endTime": d.get("endTime", 0),
                    })
                return result
    except Exception as e:
        logger.error(f"get_all_device_status error: {e}")
        return []


async def get_device_mileage(imei: str, start_ts: int, end_ts: int) -> float | None:
    token = await _get_token()
    if not token:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{WANWAY_BASE_URL}/device/miles",
                headers={"accessToken": token},
                params={"imei": imei, "startTime": start_ts, "endTime": end_ts}
            ) as resp:
                data = await resp.json(content_type=None)
                if data.get("code") == 0:
                    return float(data.get("miles", 0))
                return None
    except Exception as e:
        logger.error(f"get_device_mileage error: {e}")
        return None


async def get_device_total_mileage(imei: str) -> float | None:
    import json
    url = f"{WANWAY_BASE_URL}/device/detail"
    params = {"imei": imei}
    print(f"[get_device_total_mileage] imei={imei}")

    token = await _get_token()
    if not token:
        print("[get_device_total_mileage] token: None (auth failed)")
        return None
    print(f"[get_device_total_mileage] token: {token[:10]}...")

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"accessToken": token},
                params=params,
            ) as resp:
                print(f"[get_device_total_mileage] URL: {url}")
                print(f"[get_device_total_mileage] params: {params}")
                print(f"[get_device_total_mileage] HTTP status: {resp.status}")
                data = await resp.json(content_type=None)
                print(f"[get_device_total_mileage] response: {json.dumps(data, ensure_ascii=False, default=str)}")
                ok = data.get("success") is True or data.get("resultBean", {}).get("code") == 0
                if not ok:
                    print(
                        f"[get_device_total_mileage] -> None (success={data.get('success')}, "
                        f"resultBean.code={data.get('resultBean', {}).get('code')})"
                    )
                    return None
                payload = data.get("data") if isinstance(data.get("data"), dict) else {}
                device_status = payload.get("deviceStatus")
                if not isinstance(device_status, dict):
                    print(f"[get_device_total_mileage] -> None (data.deviceStatus missing, data keys={list(payload.keys())})")
                    return None
                if "totalMile" not in device_status:
                    print(f"[get_device_total_mileage] -> None (totalMile not in deviceStatus, keys={list(device_status.keys())})")
                    return None
                km = float(device_status["totalMile"])
                print(f"[get_device_total_mileage] -> OK totalMile={km}")
                return km
    except Exception as e:
        print(f"[get_device_total_mileage] exception: {e}")
        logger.error(f"get_device_total_mileage error: {e}")
        return None


async def get_expiring_trackers(days: int = 30) -> list[dict]:
    devices = await get_all_device_status()
    now = time.time()
    expiring = []
    for d in devices:
        end_ts = d.get("endTime", 0)
        if not end_ts:
            continue
        days_left = (end_ts - now) / 86400
        if 0 < days_left <= days:
            expiring.append({
                "imei": d["imei"],
                "name": d["name"],
                "type": d["type"],
                "days_left": int(days_left),
                "expires": datetime.fromtimestamp(end_ts).strftime("%d.%m.%Y"),
            })
    expiring.sort(key=lambda x: x["days_left"])
    return expiring


def is_in_bali(lat: float, lng: float) -> bool:
    return -8.95 <= lat <= -8.05 and 114.43 <= lng <= 115.71


async def check_bikes_outside_bali() -> list[dict]:
    devices = await get_all_device_status()
    return [d for d in devices if d["lat"] != 0 and not is_in_bali(d["lat"], d["lng"])]


async def cut_engine(imei: str) -> bool:
    token = await _get_token()
    if not token:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WANWAY_BASE_URL}/instruction/relay",
                headers={"accessToken": token},
                json={"parameter": "2", "imeis": [imei]}
            ) as resp:
                data = await resp.json(content_type=None)
                return data.get("code") == 0
    except Exception as e:
        logger.error(f"cut_engine error: {e}")
        return False


async def restore_engine(imei: str) -> bool:
    token = await _get_token()
    if not token:
        return False
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{WANWAY_BASE_URL}/instruction/relay",
                headers={"accessToken": token},
                json={"parameter": "1", "imeis": [imei]}
            ) as resp:
                data = await resp.json(content_type=None)
                return data.get("code") == 0
    except Exception as e:
        logger.error(f"restore_engine error: {e}")
        return False


def format_bike_status(d: dict) -> str:
    gps_time = datetime.fromtimestamp(d["gpsTime"]).strftime("%H:%M") if d["gpsTime"] else "—"
    acc = "🟢 ON" if d["accStatus"] else "⚫️ OFF"
    bali = "✅" if is_in_bali(d["lat"], d["lng"]) else "🚨 OUTSIDE BALI"
    voltage = f"{d['extVoltage'] / 10:.1f}V" if d["extVoltage"] else "—"
    maps = f"https://maps.google.com/?q={d['lat']},{d['lng']}"
    return (
        f"🏍 <b>{d['name']}</b> {bali}\n"
        f"   ACC: {acc} | Speed: {d['speed']} km/h\n"
        f"   Battery: {voltage} | GPS: {gps_time}\n"
        f"   <a href='{maps}'>📍 Map</a>"
    )


# ─── Alert state tracking ───────────────────────────────────────────────
# Structure: {imei: {"type": "offline"|"voltage"|"geofence", "since": ts, "acknowledged": bool}}
_active_alerts: dict[str, dict] = {}


def get_active_alerts() -> dict:
    return _active_alerts


def acknowledge_alert(imei: str) -> bool:
    if imei in _active_alerts:
        _active_alerts[imei]["acknowledged"] = True
        return True
    return False


def clear_alert(imei: str):
    _active_alerts.pop(imei, None)


def set_alert(imei: str, alert_type: str):
    if imei not in _active_alerts:
        _active_alerts[imei] = {
            "type": alert_type,
            "since": time.time(),
            "acknowledged": False
        }


def is_night_time() -> bool:
    """Check if current WITA time is between 20:30 and 05:00."""
    from datetime import datetime, timezone, timedelta
    WITA = timezone(timedelta(hours=8))
    now = datetime.now(WITA)
    hour = now.hour + now.minute / 60
    return hour >= 20.5 or hour < 5.0


async def run_gps_checks(bot, superadmin_chat_id: int):
    """Main GPS monitoring function — called every 15 minutes."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    devices = await get_all_device_status()
    now = time.time()

    for d in devices:
        imei = d["imei"]
        name = d["name"]
        lat, lng = d["lat"], d["lng"]
        signal_time = d["signalTime"]
        voltage = d["extVoltage"]
        speed = d["speed"]
        acc = d["accStatus"]

        maps_link = f"https://maps.google.com/?q={lat},{lng}"

        # ── 1. OFFLINE check (> 1 hour) ──────────────────────────────
        offline_seconds = now - signal_time if signal_time else 0
        if offline_seconds > 3600:
            alert_key = f"{imei}_offline"
            existing = _active_alerts.get(alert_key)
            if not existing or not existing["acknowledged"]:
                # Send or resend alert
                hours = int(offline_seconds // 3600)
                mins = int((offline_seconds % 3600) // 60)
                text = (
                    f"📵 <b>BIKE OFFLINE</b>\n\n"
                    f"🏍 <b>{name}</b>\n"
                    f"⏱ Offline for: <b>{hours}h {mins}m</b>\n"
                    f"📍 Last seen: <a href='{maps_link}'>Map</a>"
                )
                await bot.send_message(superadmin_chat_id, text, parse_mode="HTML")
                set_alert(alert_key, "offline")
        else:
            alert_key = f"{imei}_offline_{today_str}"
            if alert_key in _active_alerts:
                clear_alert(alert_key)
                await bot.send_message(
                    superadmin_chat_id,
                    f"🟢 <b>{name}</b> is back online!",
                    parse_mode="HTML"
                )

        # ── 2. LOW VOLTAGE check (< 11.5V) ───────────────────────────
        if voltage and voltage < 115:
            alert_key = f"{imei}_voltage"
            existing = _active_alerts.get(alert_key)
            if not existing or not existing["acknowledged"]:
                text = (
                    f"🔋 <b>LOW VOLTAGE</b>\n\n"
                    f"🏍 <b>{name}</b>\n"
                    f"⚡️ Voltage: <b>{voltage/10:.1f}V</b> (min 11.5V)\n"
                    f"📍 <a href='{maps_link}'>Map</a>"
                )
                await bot.send_message(superadmin_chat_id, text, parse_mode="HTML")
                set_alert(alert_key, "voltage")
        else:
            alert_key = f"{imei}_voltage_{today_str}"
            if alert_key in _active_alerts:
                clear_alert(alert_key)

        # ── 3. GEOFENCE check (outside Bali) ─────────────────────────
        if lat != 0 and not is_in_bali(lat, lng):
            alert_key = f"{imei}_geofence"
            existing = _active_alerts.get(alert_key)
            if not existing or not existing["acknowledged"]:
                text = (
                    f"🚨 <b>BIKE OUTSIDE BALI!</b>\n\n"
                    f"🏍 <b>{name}</b>\n"
                    f"📍 <a href='{maps_link}'>View location</a>\n\n"
                    f"⚠️ Use manager menu to cut engine if needed."
                )
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="Acknowledged ✅",
                        callback_data=f"gps_ack:geofence:{imei}"
                    )
                ]])
                await bot.send_message(superadmin_chat_id, text, parse_mode="HTML", reply_markup=kb)
                set_alert(alert_key, "geofence")
        else:
            alert_key = f"{imei}_geofence"
            if alert_key in _active_alerts:
                clear_alert(alert_key)
                await bot.send_message(
                    superadmin_chat_id,
                    f"✅ <b>{name}</b> is back in Bali.",
                    parse_mode="HTML"
                )

        # ── 4. SPEEDING check (> 60 km/h) — one time ─────────────────
        if speed > 60:
            alert_key = f"{imei}_speed"
            if alert_key not in _active_alerts:
                text = (
                    f"💨 <b>SPEEDING!</b>\n\n"
                    f"🏍 <b>{name}</b>\n"
                    f"🚀 Speed: <b>{speed} km/h</b>\n"
                    f"📍 <a href='{maps_link}'>Map</a>"
                )
                await bot.send_message(superadmin_chat_id, text, parse_mode="HTML")
                set_alert(alert_key, "speed")
        else:
            clear_alert(f"{imei}_speed")

        # ── 5. NIGHT RIDING check — one time ─────────────────────────
        if acc and is_night_time():
            alert_key = f"{imei}_night"
            if alert_key not in _active_alerts:
                text = (
                    f"🌙 <b>NIGHT RIDING!</b>\n\n"
                    f"🏍 <b>{name}</b> is running after hours.\n"
                    f"📍 <a href='{maps_link}'>Map</a>"
                )
                await bot.send_message(superadmin_chat_id, text, parse_mode="HTML")
                set_alert(alert_key, "night")
        else:
            clear_alert(f"{imei}_night")

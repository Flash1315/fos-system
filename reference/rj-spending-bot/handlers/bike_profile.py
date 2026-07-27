import time

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import MANAGERS, BIKES_GPS, BIKES_NO_GPS
from keyboards.kb import manager_menu_kb
from utils.bikes import get_work_bikes, get_rental_bikes, get_bike_category
from utils.sheets import (
    format_idr,
    get_rentals_for_bike,
    get_current_rental_for_bike,
    get_bike_rental_revenue,
    get_bike_issues_for_bike,
    get_expenses_for_bike,
    get_last_mileage,
    get_rental_by_id,
    get_checklists_for_rental,
    _bike_names_match,
)
from handlers.rental_history import format_history_card
from utils.bike_maintenance import get_bike_service_log, format_service_log_lines, parse_work_description

router = Router()

FUEL_CATEGORIES = ("Bensin",)
SERVICE_CATEGORIES = ("Bike service", "Tires pressure / Wheel repair")


def is_superadmin(user_id: int) -> bool:
    return MANAGERS.get(user_id, {}).get("superadmin", False)


def _find_gps_config_name(bike_name: str) -> str:
    for info in BIKES_GPS.values():
        if _bike_names_match(info["name"], bike_name):
            return info["name"]
    return ""


def bike_list_kb() -> InlineKeyboardMarkup:
    buttons = []
    work = get_work_bikes()
    rental = get_rental_bikes()
    if work:
        buttons.append([InlineKeyboardButton(text="— Work bikes —", callback_data="bprof:ignore")])
        for b in work:
            buttons.append([InlineKeyboardButton(text=b[:55], callback_data=f"bprof:pick:{b}")])
    if rental:
        buttons.append([InlineKeyboardButton(text="— Rental bikes —", callback_data="bprof:ignore")])
        for b in rental:
            buttons.append([InlineKeyboardButton(text=b[:55], callback_data=f"bprof:pick:{b}")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="bprof:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def profile_kb(bike_name: str, rentals: list) -> InlineKeyboardMarkup:
    buttons = []
    for r in rentals[:5]:
        rid = r.get("rental_id", "")
        if rid:
            label = f"📋 {rid} | {r.get('status', '?')}"
            buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"bprof:rent:{rid}")])
    buttons.append([InlineKeyboardButton(text="« Back to bike list", callback_data="bprof:list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _format_expense_line(item: dict) -> str:
    amt = item.get("amount") or "0"
    try:
        amt_fmt = format_idr(int(str(amt).replace(",", "").replace(".", "") or 0))
    except ValueError:
        amt_fmt = str(amt)
    place = item.get("place") or "—"
    if " — " in place:
        place = place.split(" — ", 1)[-1].strip() or place
    line = f"• {item.get('date', '—')} {item.get('category', '')} — {place} — {amt_fmt}"
    work = parse_work_description(item.get("comment", ""), item.get("place", ""), item.get("category", ""))
    if work and work not in (place, item.get("category", "")):
        line += f" | {work[:60]}"
    mileage = str(item.get("mileage") or "").strip()
    if mileage and mileage not in ("—", "0"):
        line += f" | odo {mileage} km"
    emp = item.get("employee")
    if emp and emp != "—":
        line += f" — <i>{emp}</i>"
    return line


async def _gps_status_line(bike_name: str) -> str:
    gps_name = _find_gps_config_name(bike_name)
    if not gps_name:
        if any(_bike_names_match(bike_name, n) for n in BIKES_NO_GPS):
            return "📡 GPS: <b>No tracker</b>"
        return "📡 GPS: <b>Not in GPS list</b>"
    try:
        from utils.gps import get_all_device_status
        devices = await get_all_device_status()
        for d in devices or []:
            if _bike_names_match(d.get("name", ""), gps_name):
                offline_min = 9999
                if d.get("signalTime"):
                    offline_min = int((time.time() - d["signalTime"]) / 60)
                online = offline_min < 60
                voltage = f"{d['extVoltage'] / 10:.1f}V" if d.get("extVoltage") else "?"
                status = "Online" if online else f"Offline {offline_min // 60}h"
                return f"📡 GPS: <b>{status}</b> | {voltage} | {gps_name}"
        return f"📡 GPS: <b>Tracker configured</b> ({gps_name})"
    except Exception as e:
        print(f"bike profile gps error: {e}")
        return f"📡 GPS: {gps_name} (status unavailable)"


async def build_bike_profile(bike_name: str) -> str:
    category = get_bike_category(bike_name)
    cat_label = "Work" if category == "work" else "Rental" if category == "rental" else "Unknown"

    lines = [
        f"🏍 <b>Bike Profile</b>",
        f"<b>{bike_name}</b> ({cat_label})",
        await _gps_status_line(bike_name),
    ]

    current = get_current_rental_for_bike(bike_name)
    if current:
        lines.append(
            f"📌 Status: <b>{str(current.get('status', '')).upper()}</b> — "
            f"<code>{current.get('rental_id', '—')}</code>\n"
            f"   👤 {current.get('client_name', '—')} → {current.get('return_date', '—')}"
        )
    else:
        lines.append("📌 Status: <b>Available</b>")

    last_odo = get_last_mileage(bike_name)
    if last_odo:
        lines.append(f"🔢 Last odometer: <b>{last_odo:,} km</b>".replace(",", "."))

    rev_all, cnt_all = get_bike_rental_revenue(bike_name, days=0)
    rev_90, cnt_90 = get_bike_rental_revenue(bike_name, days=90)
    lines.append("")
    lines.append(f"💰 Revenue (all time): <b>{format_idr(rev_all)}</b> — {cnt_all} rental(s)")
    lines.append(f"💰 Revenue (90 days): <b>{format_idr(rev_90)}</b> — {cnt_90} rental(s)")

    fuel = get_expenses_for_bike(bike_name, categories=FUEL_CATEGORIES, limit=5)
    lines.append("")
    lines.append("⛽ <b>Fuel</b> (recent):")
    if fuel:
        lines.extend(_format_expense_line(x) for x in fuel)
    else:
        lines.append("• —")

    service = get_expenses_for_bike(bike_name, categories=SERVICE_CATEGORIES, limit=5)
    lines.append("")
    lines.append("🔧 <b>Service / Tires</b> (recent):")
    if service:
        lines.extend(_format_expense_line(x) for x in service)
    else:
        lines.append("• —")

    rentals = get_rentals_for_bike(bike_name, limit=8)
    lines.append("")
    lines.append("📋 <b>Rentals</b> (recent):")
    if rentals:
        for r in rentals:
            rid = r.get("rental_id", "—")
            st = r.get("status", "—")
            client = r.get("client_name", "—")
            d1 = r.get("delivery_date", "—")
            d2 = r.get("return_date", "—")
            try:
                amt = format_idr(int(str(r.get("total") or r.get("rental_price") or 0).replace(",", "") or 0))
            except ValueError:
                amt = "—"
            lines.append(f"• <code>{rid}</code> | {st} | {client} | {d1}→{d2} | {amt}")
    else:
        lines.append("• —")

    service_log = get_bike_service_log(bike_name, days=365)
    lines.append("")
    lines.append("🛠 <b>Service & repair log</b>:")
    lines.extend(format_service_log_lines(service_log.get("records") or [], max_items=10))

    issues_open = get_bike_issues_for_bike(bike_name, limit=5, open_only=True)
    lines.append("")
    lines.append("⚠️ <b>Open issues</b>:")
    if issues_open:
        for issue in issues_open:
            desc = str(issue.get("description") or "—")[:70]
            lines.append(f"• {issue.get('date', '—')} | {desc}")
    else:
        lines.append("• None")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text, rentals


@router.message(F.text == "🏍 Bike profile")
async def bike_profile_start(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🏍 <b>Bike profile</b>\n\nSelect bike:",
        reply_markup=bike_list_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bprof:ignore")
async def bike_profile_ignore(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "bprof:menu")
async def bike_profile_menu(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    await state.clear()
    uid = call.from_user.id
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer(
        "👔 <b>Manager panel</b>",
        reply_markup=manager_menu_kb(is_superadmin=True),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "bprof:list")
async def bike_profile_list(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    await state.clear()
    await call.message.edit_text(
        "🏍 <b>Bike profile</b>\n\nSelect bike:",
        reply_markup=bike_list_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("bprof:pick:"))
async def bike_profile_pick(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    bike_name = call.data.split(":", 2)[2]
    await call.message.edit_text("⏳ Loading bike profile...")
    text, rentals = await build_bike_profile(bike_name)
    await state.update_data(bprof_bike=bike_name)
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=profile_kb(bike_name, rentals),
        disable_web_page_preview=True,
    )
    await call.answer()


@router.callback_query(F.data.startswith("bprof:rent:"))
async def bike_profile_rental(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    rental_id = call.data.split(":", 2)[2]
    rental = get_rental_by_id(rental_id)
    if not rental:
        await call.answer("Rental not found.", show_alert=True)
        return
    checklists = get_checklists_for_rental(rental_id)
    text = format_history_card(rental, checklists)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    data = await state.get_data()
    bike_name = data.get("bprof_bike", "")
    back_cb = f"bprof:pick:{bike_name}" if bike_name else "bprof:list"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back to bike profile", callback_data=back_cb)],
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    await call.answer()

import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from handlers.delivery import CHECKLIST_STEPS
from handlers.rental import is_manager
from keyboards.kb import rental_submenu_kb
from utils.sheets import (
    get_rental_by_id, get_rental_history, get_checklists_for_rental, format_idr,
)

router = Router()

PERIOD_LABELS = {
    7: "Last 7 days",
    30: "Last 30 days",
    90: "Last 90 days",
    0: "All history",
}


def calc_total_from_rental(rental: dict) -> int:
    total = int(str(rental.get("rental_price") or 0).replace(",", "") or 0)
    if str(rental.get("insurance", "")).strip() == "With insurance":
        try:
            total += int(str(rental.get("insurance_cost") or 0).replace(",", "").replace(".", "") or 0)
        except ValueError:
            pass
    extras = str(rental.get("extra_charges") or "").strip()
    if extras:
        for part in extras.split(";"):
            part = part.strip()
            if not part:
                continue
            amt_str = part.rsplit(":", 1)[-1].strip() if ":" in part else part
            digits = re.sub(r"[^\d]", "", amt_str)
            if digits:
                total += int(digits)
    return total


def format_checklist_block(ch: dict) -> str:
    ctype = str(ch.get("type") or "checklist").title()
    header = f"📋 <b>{ctype}</b> ({ch.get('date', '—')} {ch.get('time', '')})".strip()
    items = []
    for key, label in CHECKLIST_STEPS:
        val = ch.get(key)
        if val:
            items.append(f"{label}: {val}")
    if ch.get("helmets_count"):
        items.append(f"Helmets: {ch.get('helmets_count')}")
    if ch.get("odometer") or ch.get("fuel_bar"):
        items.append(f"Odo: {ch.get('odometer') or '—'} km | Fuel: {ch.get('fuel_bar') or '—'} bar")
    if ch.get("photo") and str(ch.get("photo")).startswith("http"):
        items.append(f"Photo: {ch.get('photo')}")
    if ch.get("notes"):
        items.append(f"Notes: {ch.get('notes')}")
    body = ", ".join(items) if items else "—"
    return f"{header}\n  {body}"


def format_history_card(rental: dict, checklists: list = None) -> str:
    status = str(rental.get("status") or "—").upper()
    price = int(str(rental.get("rental_price") or 0).replace(",", "") or 0)
    total = int(str(rental.get("total") or 0).replace(",", "") or 0) or calc_total_from_rental(rental)
    ins = rental.get("insurance") or "—"
    if ins == "With insurance" and rental.get("insurance_cost"):
        ins += f" ({format_idr(int(str(rental.get('insurance_cost') or 0).replace(',', '') or 0))})"

    lines = [
        f"📊 <b>{rental.get('rental_id', '—')}</b> — {status}",
        f"👤 {rental.get('client_name', '—')}",
        f"🏍 {rental.get('bike', '—')} | {rental.get('source', '—')}",
        f"📅 Booked: {rental.get('date_booked', '—')} by {rental.get('added_by', '—')}",
        f"🚚 Delivery: {rental.get('delivery_date', '—')} {rental.get('delivery_time', '')}".strip(),
        f"📆 Return: {rental.get('return_date', '—')} ({rental.get('duration_days', '—')} days)",
        f"📍 {rental.get('location', '—')}",
        f"👨‍🏫 {rental.get('instructor', '—')}",
        f"💵 Price: {format_idr(price)} | Extras: {rental.get('extra_charges') or '—'}",
        f"🛡 {ins} | 💰 Total: {format_idr(total)}",
    ]
    if rental.get("payment_method"):
        lines.append(f"💳 Payment: {rental.get('payment_method')}")
    if rental.get("contact_platform") or rental.get("contact_info"):
        lines.append(
            f"📱 {rental.get('contact_platform', '—')}: {rental.get('contact_info', '—')}"
        )
    if rental.get("passport"):
        lines.append(f"🛂 Passport: {rental.get('passport')}")
    if rental.get("odometer_out") or rental.get("fuel_out"):
        lines.append(
            f"🔢 Odo out: {rental.get('odometer_out', '—')} km | Fuel out: {rental.get('fuel_out', '—')} bar"
        )
    if rental.get("odometer_in") or rental.get("fuel_in"):
        lines.append(
            f"🔢 Odo in: {rental.get('odometer_in', '—')} km | Fuel in: {rental.get('fuel_in', '—')} bar"
        )
    if rental.get("video_out"):
        lines.append(f"🎬 Delivery video: {rental.get('video_out')}")
    if rental.get("video_in"):
        lines.append(f"🎬 Return video: {rental.get('video_in')}")
    damages = str(rental.get("damages") or "").strip()
    if damages and damages.lower() not in ("", "no", "—"):
        lines.append(f"⚠️ Damages: {damages}")
        if rental.get("damage_photos"):
            lines.append(f"📎 Damage photos: {rental.get('damage_photos')}")
    if rental.get("comment"):
        lines.append(f"💬 {rental.get('comment')}")

    checklists = checklists if checklists is not None else get_checklists_for_rental(rental.get("rental_id", ""))
    if checklists:
        lines.append("")
        for ch in checklists:
            lines.append(format_checklist_block(ch))

    return "\n".join(lines)


def period_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Last 7 days", callback_data="rhist:p:7")],
        [InlineKeyboardButton(text="Last 30 days", callback_data="rhist:p:30")],
        [InlineKeyboardButton(text="Last 90 days", callback_data="rhist:p:90")],
        [InlineKeyboardButton(text="All history", callback_data="rhist:p:0")],
        [InlineKeyboardButton(text="« Back", callback_data="rhist:menu")],
    ])


def history_list_kb(rentals: list, days: int) -> InlineKeyboardMarkup:
    buttons = []
    for r in rentals[:25]:
        rid = r.get("rental_id", "?")
        ref = r.get("return_date") or r.get("delivery_date") or r.get("date_booked") or "?"
        label = f"{rid} | {r.get('status', '?')} | {ref} | {r.get('client_name', '?')}"
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"rhistpick:{days}:{rid}")])
    buttons.append([InlineKeyboardButton(text="« Change period", callback_data="rhist:period")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="rhist:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def history_card_kb(days: int, rental_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back to list", callback_data=f"rhistlist:{days}")],
    ])


@router.message(F.text == "📊 Rental history")
async def history_start(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "📊 <b>Rental history</b>\n\nSelect period:",
        reply_markup=period_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "rhist:menu")
async def history_menu(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    await state.clear()
    try:
        await call.message.delete()
    except Exception:
        pass
    await call.message.answer("🏍 <b>Bike Rental</b>", reply_markup=rental_submenu_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "rhist:period")
async def history_change_period(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    await call.message.edit_text(
        "📊 <b>Rental history</b>\n\nSelect period:",
        reply_markup=period_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("rhist:p:"))
async def history_period(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    try:
        days = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer("Invalid period.", show_alert=True)
        return
    rentals = get_rental_history(days)
    label = PERIOD_LABELS.get(days, f"Last {days} days")
    if not rentals:
        await call.message.edit_text(
            f"📊 No rentals found for <b>{label}</b>.",
            reply_markup=period_kb(),
            parse_mode="HTML",
        )
        await call.answer()
        return
    await call.message.edit_text(
        f"📊 <b>{label}</b> — {len(rentals)} rental(s)\n\nTap to open:",
        reply_markup=history_list_kb(rentals, days),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("rhistlist:"))
async def history_back_to_list(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    try:
        days = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        days = 30
    rentals = get_rental_history(days)
    label = PERIOD_LABELS.get(days, f"Last {days} days")
    if not rentals:
        await call.message.edit_text(
            f"📊 No rentals found for <b>{label}</b>.",
            reply_markup=period_kb(),
            parse_mode="HTML",
        )
    else:
        await call.message.edit_text(
            f"📊 <b>{label}</b> — {len(rentals)} rental(s)\n\nTap to open:",
            reply_markup=history_list_kb(rentals, days),
            parse_mode="HTML",
        )
    await call.answer()


@router.callback_query(F.data.startswith("rhistpick:"))
async def history_pick(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    days = int(parts[1])
    rental_id = parts[2]
    rental = get_rental_by_id(rental_id)
    if not rental:
        await call.answer("Rental not found.", show_alert=True)
        return
    checklists = get_checklists_for_rental(rental_id)
    text = format_history_card(rental, checklists)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await call.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=history_card_kb(days, rental_id),
        disable_web_page_preview=True,
    )
    await call.answer()

import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.rental import (
    is_manager, compute_return_date, instructor_kb, location_kb, parse_idr_value,
)
from keyboards.kb import rental_submenu_kb, calendar_kb
from utils.sheets import (
    get_rental_by_id, get_manager_active_rentals, update_rental_fields, format_idr, parse_date,
)

router = Router()


class ActiveRentalForm(StatesGroup):
    editing = State()


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


def recalc_duration_days(delivery_date: str, return_date: str) -> str:
    d1 = parse_date(delivery_date)
    d2 = parse_date(return_date)
    if not d1 or not d2:
        return ""
    days = (d2 - d1).days + 1
    return str(max(days, 1))


def format_rental_card(rental: dict) -> str:
    status = str(rental.get("status") or "—").upper()
    price = int(str(rental.get("rental_price") or 0).replace(",", "") or 0)
    total = int(str(rental.get("total") or 0).replace(",", "") or 0) or calc_total_from_rental(rental)
    ins = rental.get("insurance") or "—"
    if ins == "With insurance" and rental.get("insurance_cost"):
        ins += f" ({format_idr(int(str(rental.get('insurance_cost') or 0).replace(',', '') or 0))})"
    lines = [
        f"📖 <b>{rental.get('rental_id', '—')}</b> — {status}",
        f"👤 {rental.get('client_name', '—')}",
        f"🏍 {rental.get('bike', '—')}",
        f"📅 Delivery: {rental.get('delivery_date', '—')} {rental.get('delivery_time', '')}".strip(),
        f"📆 Return: {rental.get('return_date', '—')} ({rental.get('duration_days', '—')} days)",
        f"📍 {rental.get('location', '—')}",
        f"👨‍🏫 {rental.get('instructor', '—')}",
        f"💵 Price: {format_idr(price)}",
        f"➕ Extras: {rental.get('extra_charges') or '—'}",
        f"🛡 {ins}",
        f"💰 Total: {format_idr(total)}",
    ]
    if rental.get("payment_method"):
        lines.append(f"💳 Payment: {rental.get('payment_method')}")
    if rental.get("contact_platform") or rental.get("contact_info"):
        lines.append(
            f"📱 {rental.get('contact_platform', '—')}: {rental.get('contact_info', '—')}"
        )
    if str(rental.get("status", "")).lower() == "active":
        if rental.get("odometer_out"):
            lines.append(
                f"🔢 Odo out: {rental.get('odometer_out')} km | Fuel: {rental.get('fuel_out', '—')} bar"
            )
        if rental.get("video_out"):
            lines.append(f"🎬 Delivery video: {rental.get('video_out')}")
    if rental.get("passport"):
        lines.append(f"🛂 Passport: {rental.get('passport')}")
    if rental.get("comment"):
        lines.append(f"💬 {rental.get('comment')}")
    return "\n".join(lines)


def active_list_kb(rentals: list):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for r in rentals[:20]:
        rid = r.get("rental_id", "?")
        label = f"{rid} | {r.get('status', '?')} | {r.get('client_name', '?')} | {r.get('bike', '?')}"
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"actpick:{rid}")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="actlist:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_menu_kb(rental_id: str):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    rid = rental_id
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍🏫 Instructor", callback_data=f"actedit:{rid}:instructor")],
        [InlineKeyboardButton(text="📍 Location", callback_data=f"actedit:{rid}:location")],
        [InlineKeyboardButton(text="📅 Delivery date", callback_data=f"actedit:{rid}:delivery_date")],
        [InlineKeyboardButton(text="📆 Return date", callback_data=f"actedit:{rid}:return_date")],
        [InlineKeyboardButton(text="💵 Price", callback_data=f"actedit:{rid}:price")],
        [InlineKeyboardButton(text="➕ Extra charges", callback_data=f"actedit:{rid}:extras")],
        [InlineKeyboardButton(text="« Back to list", callback_data="actlist:back")],
    ])


def edit_nav_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


async def show_active_list(message: Message, state: FSMContext):
    await state.clear()
    rentals = get_manager_active_rentals()
    if not rentals:
        await message.answer("📖 No active rentals.", reply_markup=rental_submenu_kb())
        return
    await message.answer(
        "📖 <b>Active rentals</b>\n\nTap a rental:",
        reply_markup=active_list_kb(rentals),
        parse_mode="HTML",
    )


async def show_rental_card(message: Message, rental_id: str, state: FSMContext = None):
    if state:
        await state.clear()
    rental = get_rental_by_id(rental_id)
    if not rental:
        await message.answer("Rental not found.", reply_markup=rental_submenu_kb())
        return
    await message.answer(
        format_rental_card(rental),
        parse_mode="HTML",
        reply_markup=edit_menu_kb(rental_id),
    )


async def apply_update(message: Message, state: FSMContext, updates: dict):
    data = await state.get_data()
    rental_id = data.get("rental_id", "")
    rental = get_rental_by_id(rental_id)
    if not rental:
        await state.clear()
        await message.answer("Rental not found.", reply_markup=rental_submenu_kb())
        return

    merged = dict(rental)
    merged.update(updates)
    if "rental_price" in updates or "extra_charges" in updates:
        updates["total"] = calc_total_from_rental(merged)
    if "delivery_date" in updates and rental.get("duration_days"):
        try:
            ret = compute_return_date(updates["delivery_date"], int(rental["duration_days"]))
            if ret:
                updates["return_date"] = ret
        except (ValueError, TypeError):
            pass
    if "return_date" in updates and (updates.get("delivery_date") or rental.get("delivery_date")):
        delivery = updates.get("delivery_date") or rental.get("delivery_date")
        days = recalc_duration_days(delivery, updates["return_date"])
        if days:
            updates["duration_days"] = days

    await update_rental_fields(rental_id, updates)
    await state.clear()
    await message.answer("✅ Saved.", reply_markup=rental_submenu_kb())
    await show_rental_card(message, rental_id)


@router.message(F.text == "📖 Active rentals")
async def active_rentals_start(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await show_active_list(message, state)


@router.callback_query(F.data == "actlist:back")
async def active_list_back(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    await state.clear()
    rentals = get_manager_active_rentals()
    if not rentals:
        await call.message.edit_text("📖 No active rentals.")
        await call.answer()
        return
    await call.message.edit_text(
        "📖 <b>Active rentals</b>\n\nTap a rental:",
        reply_markup=active_list_kb(rentals),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "actlist:menu")
async def active_list_menu(call: CallbackQuery, state: FSMContext):
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


@router.callback_query(F.data.startswith("actpick:"))
async def active_pick(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    rental_id = call.data.split(":", 1)[1]
    rental = get_rental_by_id(rental_id)
    if not rental:
        await call.answer("Rental not found.", show_alert=True)
        return
    await state.clear()
    await call.message.edit_text(
        format_rental_card(rental),
        parse_mode="HTML",
        reply_markup=edit_menu_kb(rental_id),
    )
    await call.answer()


@router.callback_query(F.data.startswith("actedit:"))
async def active_edit_start(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    rental_id, field = parts[1], parts[2]
    rental = get_rental_by_id(rental_id)
    if not rental:
        await call.answer("Rental not found.", show_alert=True)
        return

    await state.set_state(ActiveRentalForm.editing)
    await state.update_data(rental_id=rental_id, edit_field=field)

    if field == "instructor":
        await call.message.answer("👨‍🏫 Select instructor:", reply_markup=instructor_kb())
    elif field == "location":
        await call.message.answer("📍 Select location type:", reply_markup=location_kb())
    elif field == "delivery_date":
        await call.message.answer("📅 Select delivery date:", reply_markup=edit_nav_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix="actdel"))
    elif field == "return_date":
        await call.message.answer("📆 Select return date:", reply_markup=edit_nav_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix="actret"))
    elif field == "price":
        await call.message.answer(
            f"💵 Enter rental price (IDR).\nCurrent: {format_idr(int(str(rental.get('rental_price') or 0).replace(',', '') or 0))}",
            reply_markup=edit_nav_kb(),
        )
    elif field == "extras":
        await call.message.answer(
            f"➕ Enter extra charges.\n"
            "Format: <code>Helmet: 50000; Late fee: 100000</code>\n"
            "Send <code>—</code> to clear.\n\n"
            f"Current: {rental.get('extra_charges') or '—'}",
            parse_mode="HTML",
            reply_markup=edit_nav_kb(),
        )
    else:
        await state.clear()
        await call.answer("Unknown field.", show_alert=True)
        return
    await call.answer()


@router.callback_query(F.data.startswith("actdel:"))
async def active_delivery_calendar(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    current = await state.get_state()
    if current != ActiveRentalForm.editing.state:
        await call.answer()
        return
    data = await state.get_data()
    if data.get("edit_field") != "delivery_date":
        await call.answer()
        return
    await _handle_calendar(call, state, prefix="actdel", field_key="delivery_date")


@router.callback_query(F.data.startswith("actret:"))
async def active_return_calendar(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id):
        await call.answer()
        return
    current = await state.get_state()
    if current != ActiveRentalForm.editing.state:
        await call.answer()
        return
    data = await state.get_data()
    if data.get("edit_field") != "return_date":
        await call.answer()
        return
    await _handle_calendar(call, state, prefix="actret", field_key="return_date")


async def _handle_calendar(call: CallbackQuery, state: FSMContext, prefix: str, field_key: str):
    parts = call.data.split(":")
    action = parts[1]

    if action == "ignore":
        await call.answer()
        return

    if action == "cancel":
        data = await state.get_data()
        rental_id = data.get("rental_id", "")
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            pass
        await show_rental_card(call.message, rental_id)
        await call.answer()
        return

    if action == "back":
        data = await state.get_data()
        rental_id = data.get("rental_id", "")
        await state.clear()
        try:
            await call.message.delete()
        except Exception:
            pass
        await show_rental_card(call.message, rental_id)
        await call.answer()
        return

    if action == "day":
        date_str = parts[2]
        await apply_update(call.message, state, {field_key: date_str})
        try:
            await call.message.delete()
        except Exception:
            pass
        await call.answer("Saved")
        return

    if action in ("prev", "next"):
        year, month = int(parts[2]), int(parts[3])
        if action == "prev":
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        else:
            month += 1
            if month == 13:
                month = 1
                year += 1
        await call.message.edit_reply_markup(reply_markup=calendar_kb(year, month, prefix=prefix))
        await call.answer()
        return

    await call.answer()


@router.message(ActiveRentalForm.editing)
async def active_edit_value(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    data = await state.get_data()
    rental_id = data.get("rental_id", "")
    field = data.get("edit_field", "")

    if text == "❌ Cancel":
        await state.clear()
        await show_rental_card(message, rental_id)
        return
    if text == "⬅️ Back":
        await state.clear()
        await show_rental_card(message, rental_id)
        return

    if field == "instructor":
        if text == "Other":
            await message.answer("Enter instructor name:", reply_markup=edit_nav_kb())
            await state.update_data(edit_field="instructor_custom")
            return
        if text not in ("Ray", "Alex") and "Set later" not in text and text != "Other":
            await message.answer("Select instructor from the list.", reply_markup=instructor_kb())
            return
        value = "Set later" if "Set later" in text else text
        await apply_update(message, state, {"instructor": value})
        return

    if field == "instructor_custom":
        if len(text) < 2:
            await message.answer("Enter instructor name.", reply_markup=edit_nav_kb())
            return
        await apply_update(message, state, {"instructor": text})
        return

    if field == "location":
        if text == "📍 Google Maps link":
            await message.answer("Paste Google Maps link:", reply_markup=edit_nav_kb())
            await state.update_data(edit_field="location_text", location_hint="maps")
            return
        if text == "🏘 District (text)":
            await message.answer("Enter district / area name:", reply_markup=edit_nav_kb())
            await state.update_data(edit_field="location_text", location_hint="district")
            return
        if text == "✏️ Other":
            await message.answer("Enter location:", reply_markup=edit_nav_kb())
            await state.update_data(edit_field="location_text", location_hint="other")
            return
        await message.answer("Choose location type.", reply_markup=location_kb())
        return

    if field == "location_text":
        if len(text) < 2:
            await message.answer("Enter location.", reply_markup=edit_nav_kb())
            return
        await apply_update(message, state, {"location": text})
        return

    if field == "price":
        price = parse_idr_value(text)
        if price <= 0:
            await message.answer("Enter a valid price in IDR.", reply_markup=edit_nav_kb())
            return
        await apply_update(message, state, {"rental_price": price})
        return

    if field == "extras":
        value = "" if text in ("—", "-", "clear", "none") else text
        await apply_update(message, state, {"extra_charges": value})
        return

    await state.clear()
    await message.answer("Unknown edit step.", reply_markup=rental_submenu_kb())

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import EMPLOYEES, MANAGERS
from keyboards.kb import numeric_cancel_kb, cancel_kb, back_cancel_kb, skip_cancel_kb, skip_comment_kb, bikes_kb, confirm_kb, main_menu, calendar_kb
from utils.sheets import append_expense, get_total_since_last_payout, get_total_since_last_handover, get_held_cash_on_hand, preview_spending_total, format_idr, now_time
from utils.notify import post_expense_to_group

router = Router()

class FuelForm(StatesGroup):
    manager_group = State()
    manager_name = State()
    date = State()
    purpose = State()
    bike = State()
    bike_custom = State()
    station = State()
    fuel_type = State()
    amount = State()
    payment_source = State()
    mileage = State()
    comment = State()
    photo_receipt = State()
    receipt_ai_merge = State()
    photo_odometer = State()
    confirm = State()


class AIFuelForm(StatesGroup):
    manager_group = State()
    manager_name = State()
    date = State()
    purpose = State()
    bike = State()
    bike_custom = State()
    photo_receipt = State()
    ai_review = State()
    manual_amount = State()
    edit_value = State()
    fuel_type = State()
    payment_source = State()
    mileage = State()
    photo_odometer = State()
    confirm = State()

def get_employee(uid): return EMPLOYEES.get(uid)
def is_authorized(uid): return uid in EMPLOYEES or uid in MANAGERS
def get_name(uid):
    e = EMPLOYEES.get(uid)
    return e["name"] if e else MANAGERS.get(uid, {}).get("name", "Unknown")


async def _fuel_after_purpose(message: Message, state: FSMContext):
    await state.set_state(FuelForm.bike)
    await message.answer("🏍 Select bike:", reply_markup=bikes_kb())


async def _fuel_purpose_back(message: Message, state: FSMContext):
    await state.set_state(FuelForm.date)
    await message.answer("📅 Select date:", reply_markup=cancel_kb())
    await message.answer("👇", reply_markup=calendar_kb())

@router.message(F.text == "⛽ Fuel")
async def start_fuel(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    if uid in MANAGERS and uid not in EMPLOYEES:
        await state.set_state(FuelForm.manager_group)
        from config import EMPLOYEES as EMPS, MANAGER_GROUP_CHAT_ID
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        all_groups = MANAGERS.get(uid, {}).get("all_groups", False)
        if all_groups:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"fuel_grp:{eid}")] for eid, info in EMPS.items()]
            buttons.append([InlineKeyboardButton(text="👔 Manager group", callback_data="fuel_grp:manager")])
        else:
            buttons = [[InlineKeyboardButton(text="👔 Manager group", callback_data="fuel_grp:manager")]]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("⛽ <b>Fuel</b>\n\n👥 Send to which group?", reply_markup=kb, parse_mode="HTML")
        return
    await state.set_state(FuelForm.date)
    await message.answer("⛽ <b>Fuel</b>\n\n📅 Select date:", reply_markup=cancel_kb(), parse_mode="HTML")
    await message.answer("👇", reply_markup=calendar_kb())

@router.callback_query(F.data.startswith("fuel_grp:"), FuelForm.manager_group)
async def fuel_grp_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS, MANAGER_GROUP_CHAT_ID
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    group_key = call.data.split(":")[1]
    uid = call.from_user.id
    my_name = MANAGERS.get(uid, {}).get("name", "Manager")
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if group_key == "manager":
        await state.update_data(mgr_group_chat=MANAGER_GROUP_CHAT_ID, mgr_emp_uid=None)
        if is_superadmin:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"fuel_name:mgr_{mid}")] for mid, info in MANAGERS.items()]
            for eid, einfo in EMPS.items():
                buttons.append([InlineKeyboardButton(text=einfo["name"], callback_data=f"fuel_name:{eid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="fuel_name:manager")]]
    else:
        emp_uid = int(group_key)
        emp = EMPS.get(emp_uid, {})
        await state.update_data(mgr_group_chat=emp.get("group_chat_id"), mgr_emp_uid=emp_uid)
        if is_superadmin:
            buttons = [
                [InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="fuel_name:manager")],
                [InlineKeyboardButton(text=emp.get("name","Employee"), callback_data=f"fuel_name:{emp_uid}")],
            ]
            for mgr_uid, mgr_info in MANAGERS.items():
                if mgr_uid != uid:
                    buttons.append([InlineKeyboardButton(text=mgr_info["name"], callback_data=f"fuel_name:mgr_{mgr_uid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="fuel_name:manager")]]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(FuelForm.manager_name)
    await call.message.answer("👤 Record under whose name?", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("fuel_name:"), FuelForm.manager_name)
async def fuel_name_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS
    name_key = call.data.split(":")[1]
    if name_key == "manager":
        uid = call.from_user.id
        record_name = MANAGERS.get(uid, {}).get("name", "Manager")
    elif name_key.startswith("mgr_"):
        mgr_uid = int(name_key.replace("mgr_", ""))
        record_name = MANAGERS.get(mgr_uid, {}).get("name", "Manager")
    else:
        emp = EMPS.get(int(name_key), {})
        record_name = emp.get("name", "Manager")
    await state.update_data(mgr_record_name=record_name)
    await state.set_state(FuelForm.date)
    await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
    await call.message.answer("👇", reply_markup=calendar_kb())
    await call.answer()

@router.callback_query(F.data.startswith("fuelpur:"), FuelForm.purpose)
async def fuel_purpose_callback(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await state.clear()
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await _fuel_purpose_back(call.message, state)
        await call.answer()
        return
    await state.update_data(purpose=action)
    await call.message.delete()
    await _fuel_after_purpose(call.message, state)
    await call.answer()


@router.message(FuelForm.bike)
async def fuel_bike(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(FuelForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await show_purpose_prompt(message, "fuelpur", "Fuel purpose:")
        return
    if message.text == "Other (enter manually)":
        await state.set_state(FuelForm.bike_custom)
        await message.answer("🏍 Enter bike name:", reply_markup=back_cancel_kb())
        return
    await state.update_data(bike=message.text.strip())
    await state.set_state(FuelForm.station)
    await message.answer("⛽ Station name:", reply_markup=back_cancel_kb())

@router.message(FuelForm.bike_custom)
async def fuel_bike_custom(message: Message, state: FSMContext):
    await state.update_data(bike=message.text.strip())
    await state.set_state(FuelForm.station)
    await message.answer("⛽ Station name:", reply_markup=back_cancel_kb())

@router.message(FuelForm.station)
async def fuel_station(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(FuelForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    await state.update_data(station=message.text.strip())
    await state.set_state(FuelForm.fuel_type)
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    fuel_kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Pertalite"), KeyboardButton(text="Pertamax")],
        [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
    ], resize_keyboard=True)
    await message.answer("⛽ Fuel type:", reply_markup=fuel_kb)

FUEL_TYPES = ("Pertalite", "Pertamax")

@router.message(FuelForm.fuel_type)
async def fuel_type_select(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    if message.text == "⬅️ Back":
        await state.set_state(FuelForm.station)
        await message.answer("⛽ Station name:", reply_markup=back_cancel_kb())
        return
    if message.text not in FUEL_TYPES:
        await message.answer("⚠️ Select fuel type from buttons")
        return
    await state.update_data(fuel_type=message.text)
    await state.set_state(FuelForm.amount)
    await message.answer("💵 Amount paid (IDR):", reply_markup=back_cancel_kb())

@router.message(FuelForm.amount)
async def fuel_amount(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        fuel_kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="Pertalite"), KeyboardButton(text="Pertamax")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ], resize_keyboard=True)
        await state.set_state(FuelForm.fuel_type)
        await message.answer("⛽ Select fuel type:", reply_markup=fuel_kb)
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(amount=int(digits))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 My pocket", callback_data="fuelpay:my_pocket"),
         InlineKeyboardButton(text="💰 Cash on hand", callback_data="fuelpay:cash_on_hand")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="fuelpay:back"),
         InlineKeyboardButton(text="❌ Cancel", callback_data="fuelpay:cancel")]
    ])
    await state.set_state(FuelForm.payment_source)
    await message.answer(f"✅ {format_idr(int(digits))}\n\n💳 <b>Paid from:</b>", reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("fuelpay:"), FuelForm.payment_source)
async def fuel_payment_source(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "fuelpay:back":
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        fuel_kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="Pertalite"), KeyboardButton(text="Pertamax")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ], resize_keyboard=True)
        await state.set_state(FuelForm.fuel_type)
        await callback.message.delete()
        await callback.message.answer("⛽ Select fuel type:", reply_markup=fuel_kb)
        return
    if callback.data == "fuelpay:cancel":
        await state.clear()
        uid = callback.from_user.id
        await callback.message.delete()
        await callback.message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    source = "My pocket" if callback.data == "fuelpay:my_pocket" else "Cash on hand"
    await state.update_data(payment_source=source)
    await callback.message.delete()
    await state.set_state(FuelForm.mileage)
    await callback.message.answer(
        "💳 " + source + "\n\n🔢 Mileage at time of refuel (km):",
        reply_markup=back_cancel_kb(), parse_mode="HTML"
    )

@router.message(FuelForm.mileage)
async def fuel_mileage(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(FuelForm.amount)
        await message.answer("💵 Amount paid (IDR):", reply_markup=numeric_cancel_kb())
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter mileage in km, e.g. 12500")
        return
    new_mileage = int(digits)
    data = await state.get_data()
    bike = data.get("bike", "")
    if bike:
        from utils.sheets import get_last_mileage
        import asyncio
        loop = asyncio.get_event_loop()
        last_mileage = await loop.run_in_executor(None, get_last_mileage, bike)
        if last_mileage > 0 and new_mileage < last_mileage:
            await message.answer(
                f"⚠️ <b>Mileage error!</b>\n\n"
                f"Last recorded: <b>{last_mileage} km</b>\n"
                f"You entered: <b>{new_mileage} km</b>\n\n"
                f"Mileage cannot decrease. Please check and re-enter.",
                parse_mode="HTML"
            )
            return
    await state.update_data(mileage=digits)
    await state.set_state(FuelForm.comment)
    await message.answer(
        "💬 <b>Comment</b> (optional)\n\nAdd any notes, or tap Skip.",
        reply_markup=skip_comment_kb(), parse_mode="HTML"
    )

@router.message(FuelForm.comment, F.text)
async def fuel_comment(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(FuelForm.mileage)
        await message.answer("🔢 Mileage (km):", reply_markup=back_cancel_kb())
        return
    if message.text in ("⏭ Skip", "⏭ Skip (no receipt)"):
        await state.update_data(comment="")
    else:
        await state.update_data(comment=message.text.strip())
    await state.set_state(FuelForm.photo_receipt)
    await message.answer(
        "📸 <b>Photo 1/2 — Fuel receipt</b>\n\n"
        "⚠️ Please photograph the receipt:\n"
        "• Lay it flat\n"
        "• Shoot from above\n"
        "• All numbers must be readable\n\n"
        "No receipt? Tap Skip.",
        reply_markup=skip_cancel_kb(), parse_mode="HTML"
    )

@router.message(FuelForm.photo_receipt, F.photo)
async def fuel_photo_receipt(message: Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(photo_receipt=file_id)
    processing = await message.answer("⏳ Reading receipt...")
    try:
        from utils.receipt_ai import enrich_from_receipt_photo, receipt_comment_kb
        data = await state.get_data()
        updates, info_lines, conflict = await enrich_from_receipt_photo(message.bot, file_id, data)
        if conflict:
            await state.update_data(receipt_ai_items=conflict["ai_items"])
            if updates:
                await state.update_data(**updates)
            await state.set_state(FuelForm.receipt_ai_merge)
            text = "🤖 <b>AI read:</b>\n" + "\n".join(info_lines)
            await processing.edit_text(text, reply_markup=receipt_comment_kb("fuelrcmt"), parse_mode="HTML")
            return
        if updates:
            await state.update_data(**updates)
        if info_lines:
            await processing.edit_text("🤖 <b>AI read:</b>\n" + "\n".join(info_lines), parse_mode="HTML")
        else:
            await processing.delete()
    except Exception as e:
        print(f"Fuel receipt AI error: {e}")
        await processing.delete()
    await _fuel_go_odometer(message, state)


async def _fuel_go_odometer(message: Message, state: FSMContext):
    await state.set_state(FuelForm.photo_odometer)
    await message.answer(
        "📸 <b>Photo 2/2 — Odometer</b>\n\n"
        "⚠️ Please photograph the odometer showing current mileage.\n"
        "Make sure the numbers are clearly visible.\n\n"
        "No photo? Tap Skip.",
        reply_markup=skip_comment_kb(), parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("fuelrcmt:"), FuelForm.receipt_ai_merge)
async def fuel_receipt_comment_merge(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    data = await state.get_data()
    from utils.receipt_ai import resolve_comment_conflict
    comment = resolve_comment_conflict(
        action,
        data.get("comment", ""),
        data.get("receipt_ai_items", ""),
    )
    await state.update_data(comment=comment, receipt_ai_items="")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer("💬 Comment saved.")
    await _fuel_go_odometer(call.message, state)
    await call.answer()

@router.message(FuelForm.photo_receipt, F.text == "⏭ Skip (no receipt)")
async def fuel_photo_receipt_skip(message: Message, state: FSMContext):
    await state.update_data(photo_receipt="")
    await _fuel_go_odometer(message, state)

@router.message(FuelForm.photo_odometer, F.photo)
async def fuel_photo_odometer(message: Message, state: FSMContext):
    await state.update_data(photo_odometer=message.photo[-1].file_id)
    await show_fuel_confirm(message, state)



async def show_fuel_confirm(message: Message, state: FSMContext, confirm_state=FuelForm.confirm):
    data = await state.get_data()
    name = data.get("mgr_record_name") or get_name(message.from_user.id)
    payment_source = data.get("payment_source", "My pocket")
    if payment_source == "Cash on hand":
        held_after = max(0, get_held_cash_on_hand(name) - data["amount"])
        totals_block = (
            f"💳 Payment: Cash on hand\n"
            f"💰 Cash on hand after: {format_idr(held_after)}\n"
            f"💸 Reimbursable spending: {format_idr(get_total_since_last_payout(name))} (unchanged)\n"
            f"💰 Income since last handover: {format_idr(get_total_since_last_handover(name))}"
        )
    else:
        totals_block = (
            f"💳 Payment: My pocket\n"
            f"💸 Your total spending: {format_idr(preview_spending_total(name, data['amount'], payment_source))}\n"
            f"💰 Income since last handover: {format_idr(get_total_since_last_handover(name))}"
        )
    from config import MANAGERS
    uid = message.from_user.id
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    extra = ""
    if is_superadmin and data.get("mgr_record_name"):
        group_chat = data.get("mgr_group_chat")
        from config import EMPLOYEES, MANAGER_GROUP_CHAT_ID
        group_name = "Manager group"
        for eid, einfo in EMPLOYEES.items():
            if einfo.get("group_chat_id") == group_chat:
                group_name = einfo["name"] + " group"
                break
        extra = f"👥 Group: {group_name}\n👤 Name: {name}\n"
    text = (
        f"📋 <b>Confirm:</b>\n\n"
        f"{extra}"
        f"📅 {data['date']}\n"
        f"🎯 {data.get('purpose', '—')}\n"
        f"🏍 {data['bike']}\n"
        f"⛽ {data['station']} — {data.get('fuel_type', 'Pertalite')}\n"
        f"💵 {format_idr(data['amount'])}\n"
        f"🔢 {data['mileage']} km\n"
        f"💬 {data.get('comment', '') or '—'}\n"
        f"📸 Receipt: {'✅' if data.get('photo_receipt') else '⚠️ Not provided'}\n"
        f"📸 Odometer: {'✅' if data.get('photo_odometer') else '⚠️ Not provided'}\n\n"
        f"{totals_block}"
    )
    await state.set_state(confirm_state)
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")


async def _fuel_save_record(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    emp = get_employee(uid)
    name = data.get("mgr_record_name") or get_name(uid)
    time = now_time()
    payment_source = data.get("payment_source", "My pocket")

    receipt_url = ""
    odometer_url = ""
    note = f"Bensin — {data['bike']} @ {data['station']} ({data.get('fuel_type', 'Pertalite')}) ({data['mileage']} km)"
    place = f"{data['bike']} @ {data['station']}"
    purpose = data.get("purpose", "")
    rental_id = ""
    if purpose == "Rental":
        import asyncio
        from utils.sheets import get_rental_id_for_bike
        loop = asyncio.get_event_loop()
        rental_id = await loop.run_in_executor(None, get_rental_id_for_bike, data.get("bike", ""))
    await append_expense(
        data["date"], time, "Bensin", place, data["amount"], receipt_url, odometer_url, name,
        data.get("comment", ""), payment_source=payment_source,
        mileage=data.get("mileage", ""), gps_mileage="",
        purpose=purpose, rental_id=rental_id,
    )

    total_since = get_total_since_last_payout(name)
    if payment_source == "My pocket":
        saved_line = f"📊 Total since last payout: <b>{format_idr(total_since)}</b>"
        group_total = total_since
    else:
        saved_line = f"💰 Cash on hand: <b>{format_idr(get_held_cash_on_hand(name))}</b>"
        group_total = total_since

    try:
        from utils.fuel_check import check_fuel_consumption
        await check_fuel_consumption(
            bot=message.bot,
            employee_name=name,
            bike_name=data.get("bike", ""),
            current_odo=data.get("mileage", 0),
            amount_idr=data["amount"],
            fuel_type=data.get("fuel_type", "Pertalite")
        )
    except Exception as e:
        print(f"Fuel check error: {e}")

    try:
        from utils.fuel_check import check_gps_odometer
        from utils.sheets import get_sheet
        import time as time_mod
        ws = get_sheet("Expenses")
        rows = ws.get_all_values()
        prev_odo = 0
        from utils.sheets import EXP_COL_EMPLOYEE, EXP_COL_MILEAGE, EXP_COL_CATEGORY, _parse_mileage_km
        for row in reversed(rows):
            if len(row) > EXP_COL_EMPLOYEE and row[EXP_COL_EMPLOYEE] == name and row[EXP_COL_CATEGORY] == "Bensin":
                km = _parse_mileage_km(row[EXP_COL_MILEAGE] if len(row) > EXP_COL_MILEAGE else "")
                if km > 0:
                    prev_odo = km
                    break
        if prev_odo > 0:
            await check_gps_odometer(
                bot=message.bot,
                bike_name=data.get("bike", ""),
                manual_odo=int(data.get("mileage", 0)),
                prev_odo=prev_odo,
                entry_date_ts=int(time_mod.time()) - 86400
            )
    except Exception as e:
        print(f"GPS odometer check error: {e}")

    group_chat_id = data.get("mgr_group_chat") or (emp["group_chat_id"] if emp else None)
    if group_chat_id:
        await post_expense_to_group(
            bot=message.bot,
            group_chat_id=group_chat_id,
            employee_name=name,
            note=note,
            date=data["date"],
            amount=data["amount"],
            total_spending=group_total,
            photo_file_id=data.get("photo_receipt", ""), comment=data.get("comment", ""), photo_file_id2=data.get("photo_odometer", "")
        )

    await state.clear()
    await message.answer(
        f"✅ Saved!\n{saved_line}",
        reply_markup=main_menu(is_manager=uid in MANAGERS), parse_mode="HTML"
    )

    import asyncio
    saved_date = data["date"]
    saved_time = time
    saved_name = name

    async def upload_fuel_photos():
        try:
            from utils.drive_upload import upload_receipt_to_drive
            from utils.sheets import update_expense_photos
            r_url = ""
            o_url = ""
            if data.get("photo_receipt"):
                r_url = await upload_receipt_to_drive(
                    message.bot, data["photo_receipt"],
                    f"{saved_date.replace('.', '-')}_{saved_name}_fuel_receipt.jpg", saved_date
                )
            if data.get("photo_odometer"):
                o_url = await upload_receipt_to_drive(
                    message.bot, data["photo_odometer"],
                    f"{saved_date.replace('.', '-')}_{saved_name}_odometer.jpg", saved_date
                )
            if r_url or o_url:
                update_expense_photos(saved_date, saved_time, saved_name, r_url, o_url)
        except Exception as e:
            print(f"Fuel upload error: {e}")
    asyncio.create_task(upload_fuel_photos())

    from handlers.expenses import update_gps_mileage_background
    if data.get("bike"):
        async def safe_gps():
            try:
                await update_gps_mileage_background(saved_date, saved_time, saved_name, data["bike"], "Bensin")
            except Exception as e:
                print(f"GPS mileage background error: {e}")
        asyncio.create_task(safe_gps())


@router.message(FuelForm.confirm, F.text == "✅ Confirm")
async def fuel_confirm(message: Message, state: FSMContext):
    await _fuel_save_record(message, state)


@router.message(AIFuelForm.confirm, F.text == "✅ Confirm")
async def ai_fuel_confirm(message: Message, state: FSMContext):
    await _fuel_save_record(message, state)


@router.message(FuelForm.confirm, F.text == "✏️ Edit")
async def fuel_edit(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="📅 Date", callback_data="edit_fuel:date")],
        [InlineKeyboardButton(text="🏍 Bike", callback_data="edit_fuel:bike")],
        [InlineKeyboardButton(text="⛽ Station", callback_data="edit_fuel:station")],
        [InlineKeyboardButton(text="💵 Amount", callback_data="edit_fuel:amount")],
        [InlineKeyboardButton(text="🔢 Mileage", callback_data="edit_fuel:mileage")],
        [InlineKeyboardButton(text="💬 Comment", callback_data="edit_fuel:comment")],
        [InlineKeyboardButton(text="❌ Cancel edit", callback_data="edit_fuel:cancel")],
    ]
    await message.answer("✏️ What do you want to edit?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("edit_fuel:"))
async def fuel_edit_field(call: CallbackQuery, state: FSMContext):
    await call.answer()
    field = call.data.split(":")[1]
    if field == "cancel":
        await call.message.edit_text("Edit cancelled.")
        return
    if field == "date":
        await state.set_state(FuelForm.date)
        await call.message.answer("📅 Select new date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb())
    elif field == "bike":
        await state.set_state(FuelForm.bike)
        await call.message.answer("🏍 Select bike:", reply_markup=bikes_kb())
    elif field == "station":
        await state.set_state(FuelForm.station)
        await call.message.answer("⛽ Station name:", reply_markup=back_cancel_kb())
    elif field == "amount":
        await state.set_state(FuelForm.amount)
        await call.message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
    elif field == "mileage":
        await state.set_state(FuelForm.mileage)
        await call.message.answer("🔢 Mileage (km):", reply_markup=back_cancel_kb())
    elif field == "comment":
        await state.set_state(FuelForm.comment)
        await call.message.answer("💬 Comment:", reply_markup=skip_comment_kb())
    await call.message.edit_text(f"✏️ Editing: {field}")


# ─── AI Fuel flow (receipt-first → Bensin category) ───────────

def _aifuel_fmt(val) -> str:
    if val is None or val == "":
        return "—"
    return str(val)


def _aifuel_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data="aifuelread:confirm"),
            InlineKeyboardButton(text="✏️ Edit", callback_data="aifuelread:edit"),
        ],
        [InlineKeyboardButton(text="📷 Retake photo", callback_data="aifuelread:retake")],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="aifuelread:back"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="aifuelread:cancel"),
        ],
    ])


def _aifuel_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 Amount", callback_data="aifueledit:amount"),
            InlineKeyboardButton(text="⛽ Station", callback_data="aifueledit:station"),
        ],
        [InlineKeyboardButton(text="📋 Items", callback_data="aifueledit:items")],
        [InlineKeyboardButton(text="⬅️ Back to review", callback_data="aifueledit:back")],
    ])


def _aifuel_payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 My pocket", callback_data="aifuelpay:my_pocket"),
            InlineKeyboardButton(text="💰 Cash on hand", callback_data="aifuelpay:cash_on_hand"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="aifuelpay:back"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="aifuelpay:cancel"),
        ],
    ])


async def _aifuel_cancel(message_or_call, state: FSMContext, uid: int):
    await state.clear()
    target = message_or_call.message if hasattr(message_or_call, "message") else message_or_call
    await target.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))


async def _aifuel_go_photo(message: Message, state: FSMContext):
    await state.set_state(AIFuelForm.photo_receipt)
    await message.answer(
        "📸 Photo the fuel receipt. I'll read station, amount, and fuel type.",
        reply_markup=back_cancel_kb(),
    )


async def _aifuel_show_review(message: Message, state: FSMContext):
    data = await state.get_data()
    amount_line = format_idr(data["amount"]) if data.get("amount") else "—"
    text = (
        "🤖 <b>AI read (fuel):</b>\n"
        f"🏍 Bike: {_aifuel_fmt(data.get('bike'))}\n"
        f"⛽ Station: {_aifuel_fmt(data.get('station'))}\n"
        f"📋 Items: {_aifuel_fmt(data.get('items'))}\n"
        f"💵 Amount: {amount_line}\n\n"
        "✅ Confirm / ✏️ Edit / 📷 Retake photo"
    )
    await state.set_state(AIFuelForm.ai_review)
    await message.answer(text, reply_markup=_aifuel_review_kb(), parse_mode="HTML")


async def _aifuel_show_fuel_type(message: Message, state: FSMContext):
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    data = await state.get_data()
    guessed = data.get("fuel_type")
    hint = f"\n\nSuggested: <b>{guessed}</b>" if guessed else ""
    fuel_kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="Pertalite"), KeyboardButton(text="Pertamax")],
        [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
    ], resize_keyboard=True)
    await state.set_state(AIFuelForm.fuel_type)
    await message.answer(f"⛽ Fuel type:{hint}", reply_markup=fuel_kb, parse_mode="HTML")


async def _aifuel_show_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("amount"):
        await message.answer("⚠️ Amount is required. Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        await state.set_state(AIFuelForm.manual_amount)
        return
    await state.set_state(AIFuelForm.payment_source)
    await message.answer(
        f"✅ Amount: <b>{format_idr(data['amount'])}</b>\n\n💳 <b>Paid from:</b>",
        reply_markup=_aifuel_payment_kb(),
        parse_mode="HTML",
    )


async def _aifuel_show_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("station"):
        await state.update_data(station="—")
    await show_fuel_confirm(message, state, AIFuelForm.confirm)


@router.message(F.text == "🧾 Fuel (AI)")
async def start_ai_fuel(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid):
        return
    if uid in MANAGERS and uid not in EMPLOYEES:
        await state.set_state(AIFuelForm.manager_group)
        from config import EMPLOYEES as EMPS
        all_groups = MANAGERS.get(uid, {}).get("all_groups", False)
        if all_groups:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"aifuel_grp:{eid}")] for eid, info in EMPS.items()]
            buttons.append([InlineKeyboardButton(text="👔 Manager group", callback_data="aifuel_grp:manager")])
        else:
            buttons = [[InlineKeyboardButton(text="👔 Manager group", callback_data="aifuel_grp:manager")]]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("🧾 <b>Fuel (AI)</b>\n\n👥 Send to which group?", reply_markup=kb, parse_mode="HTML")
        return
    await state.set_state(AIFuelForm.date)
    await message.answer("🧾 <b>Fuel (AI)</b>\n\n📅 Select date:", reply_markup=cancel_kb(), parse_mode="HTML")
    await message.answer("👇", reply_markup=calendar_kb(prefix="aifuelcal"))


@router.callback_query(F.data.startswith("aifuel_grp:"), AIFuelForm.manager_group)
async def ai_fuel_grp_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS, MANAGER_GROUP_CHAT_ID
    group_key = call.data.split(":")[1]
    uid = call.from_user.id
    my_name = MANAGERS.get(uid, {}).get("name", "Manager")
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if group_key == "manager":
        await state.update_data(mgr_group_chat=MANAGER_GROUP_CHAT_ID, mgr_emp_uid=None)
        if is_superadmin:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"aifuel_name:mgr_{mid}")] for mid, info in MANAGERS.items()]
            for eid, einfo in EMPS.items():
                buttons.append([InlineKeyboardButton(text=einfo["name"], callback_data=f"aifuel_name:{eid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="aifuel_name:manager")]]
    else:
        emp_uid = int(group_key)
        emp = EMPS.get(emp_uid, {})
        await state.update_data(mgr_group_chat=emp.get("group_chat_id"), mgr_emp_uid=emp_uid)
        if is_superadmin:
            buttons = [
                [InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="aifuel_name:manager")],
                [InlineKeyboardButton(text=emp.get("name", "Employee"), callback_data=f"aifuel_name:{emp_uid}")],
            ]
            for mgr_uid, mgr_info in MANAGERS.items():
                if mgr_uid != uid:
                    buttons.append([InlineKeyboardButton(text=mgr_info["name"], callback_data=f"aifuel_name:mgr_{mgr_uid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="aifuel_name:manager")]]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(AIFuelForm.manager_name)
    await call.message.answer("👤 Record under whose name?", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("aifuel_name:"), AIFuelForm.manager_name)
async def ai_fuel_name_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS
    name_key = call.data.split(":")[1]
    if name_key == "manager":
        uid = call.from_user.id
        record_name = MANAGERS.get(uid, {}).get("name", "Manager")
    elif name_key.startswith("mgr_"):
        mgr_uid = int(name_key.replace("mgr_", ""))
        record_name = MANAGERS.get(mgr_uid, {}).get("name", "Manager")
    else:
        emp = EMPS.get(int(name_key), {})
        record_name = emp.get("name", "Manager")
    await state.update_data(mgr_record_name=record_name)
    await state.set_state(AIFuelForm.date)
    await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
    await call.message.answer("👇", reply_markup=calendar_kb(prefix="aifuelcal"))
    await call.answer()


@router.callback_query(F.data.startswith("aifuelpur:"), AIFuelForm.purpose)
async def ai_fuel_purpose_callback(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _aifuel_cancel(call, state, uid)
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await state.set_state(AIFuelForm.date)
        await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix="aifuelcal"))
        await call.answer()
        return
    await state.update_data(purpose=action)
    await call.message.delete()
    await state.set_state(AIFuelForm.bike)
    await call.message.answer("🏍 Select bike:", reply_markup=bikes_kb())
    await call.answer()


@router.message(AIFuelForm.bike)
async def ai_fuel_bike(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await state.set_state(AIFuelForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await show_purpose_prompt(message, "aifuelpur", "Fuel purpose:")
        return
    if message.text.startswith("—"):
        return
    if message.text == "Other (enter manually)":
        await state.set_state(AIFuelForm.bike_custom)
        await message.answer("🏍 Enter bike name:", reply_markup=back_cancel_kb())
        return
    await state.update_data(bike=message.text.strip())
    await _aifuel_go_photo(message, state)


@router.message(AIFuelForm.bike_custom)
async def ai_fuel_bike_custom(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await state.set_state(AIFuelForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    await state.update_data(bike=message.text.strip())
    await _aifuel_go_photo(message, state)


@router.message(AIFuelForm.photo_receipt, F.photo)
async def ai_fuel_photo_receipt(message: Message, state: FSMContext):
    await state.update_data(photo_receipt=message.photo[-1].file_id)
    processing = await message.answer("⏳ Reading receipt...")
    try:
        from utils.receipt_ai import read_receipt_for_ai_flow, receipt_has_data, receipt_read_failure_message, guess_fuel_type

        result = await read_receipt_for_ai_flow(message.bot, message.photo[-1].file_id)
        station = (result.get("place") or "").strip()
        items = (result.get("items") or "").strip()
        fuel_type = guess_fuel_type(items)
        comment = items
        await state.update_data(
            amount=result.get("amount"),
            station=station,
            items=items,
            comment=comment,
            fuel_type=fuel_type,
        )
        if result.get("error"):
            await processing.edit_text(receipt_read_failure_message(result))
            await state.set_state(AIFuelForm.manual_amount)
            await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        elif not receipt_has_data(result):
            await processing.edit_text(receipt_read_failure_message(result))
            await state.set_state(AIFuelForm.manual_amount)
            await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        else:
            await processing.delete()
            await _aifuel_show_review(message, state)
    except Exception as e:
        print(f"AI fuel receipt error: {e}")
        await processing.edit_text(f"⚠️ AI error: {e}")
        await state.set_state(AIFuelForm.manual_amount)
        await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())


@router.message(AIFuelForm.photo_receipt)
async def ai_fuel_photo_invalid(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await state.set_state(AIFuelForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    await message.answer("📸 Please send a fuel receipt photo.", reply_markup=back_cancel_kb())


@router.message(AIFuelForm.manual_amount)
async def ai_fuel_manual_amount(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _aifuel_go_photo(message, state)
        return
    digits = "".join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number, e.g. 25000")
        return
    await state.update_data(amount=int(digits))
    data = await state.get_data()
    if not data.get("station"):
        await state.set_state(AIFuelForm.edit_value)
        await state.update_data(ai_edit_field="station")
        await message.answer("⛽ Station name:", reply_markup=back_cancel_kb())
        return
    await _aifuel_show_fuel_type(message, state)


@router.message(AIFuelForm.edit_value)
async def ai_fuel_edit_value(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _aifuel_show_review(message, state)
        return
    field = (await state.get_data()).get("ai_edit_field", "station")
    value = message.text.strip()
    if field == "amount":
        digits = "".join(c for c in value if c.isdigit())
        if not digits:
            await message.answer("⚠️ Enter a number")
            return
        await state.update_data(amount=int(digits))
    elif field == "station":
        await state.update_data(station=value)
    else:
        await state.update_data(items=value, comment=value)
    await _aifuel_show_review(message, state)


@router.callback_query(F.data.startswith("aifuelread:"), AIFuelForm.ai_review)
async def ai_fuel_read_action(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _aifuel_cancel(call, state, uid)
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await state.set_state(AIFuelForm.bike)
        await call.message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        await call.answer()
        return
    if action == "retake":
        await call.message.delete()
        await state.update_data(photo_receipt="")
        await _aifuel_go_photo(call.message, state)
        await call.answer()
        return
    if action == "edit":
        await call.message.edit_reply_markup(reply_markup=_aifuel_edit_kb())
        await call.answer()
        return
    if action == "confirm":
        await call.message.edit_reply_markup(reply_markup=None)
        await _aifuel_show_fuel_type(call.message, state)
        await call.answer()


@router.callback_query(F.data.startswith("aifueledit:"), AIFuelForm.ai_review)
async def ai_fuel_edit_pick(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":", 1)[1]
    if field == "back":
        await call.message.edit_reply_markup(reply_markup=_aifuel_review_kb())
        await call.answer()
        return
    prompts = {
        "amount": "💵 Enter new amount (IDR):",
        "station": "⛽ Enter station name:",
        "items": "📋 Enter items / notes:",
    }
    await state.update_data(ai_edit_field=field)
    await state.set_state(AIFuelForm.edit_value)
    await call.message.answer(prompts.get(field, "Enter value:"), reply_markup=back_cancel_kb())
    await call.answer()


@router.message(AIFuelForm.fuel_type)
async def ai_fuel_type_select(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _aifuel_show_review(message, state)
        return
    if message.text not in FUEL_TYPES:
        await message.answer("⚠️ Select fuel type from buttons")
        return
    await state.update_data(fuel_type=message.text)
    await _aifuel_show_payment(message, state)


@router.callback_query(F.data.startswith("aifuelpay:"), AIFuelForm.payment_source)
async def ai_fuel_payment(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    if call.data == "aifuelpay:cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _aifuel_cancel(call, state, uid)
        await call.answer()
        return
    if call.data == "aifuelpay:back":
        await call.message.delete()
        await _aifuel_show_fuel_type(call.message, state)
        await call.answer()
        return
    source = "My pocket" if call.data == "aifuelpay:my_pocket" else "Cash on hand"
    await state.update_data(payment_source=source)
    await call.message.edit_reply_markup(reply_markup=None)
    await state.set_state(AIFuelForm.mileage)
    await call.message.answer(
        f"💳 {source}\n\n🔢 Mileage at time of refuel (km):",
        reply_markup=back_cancel_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(AIFuelForm.mileage)
async def ai_fuel_mileage(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _aifuel_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _aifuel_show_payment(message, state)
        return
    digits = "".join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter mileage in km, e.g. 12500")
        return
    new_mileage = int(digits)
    data = await state.get_data()
    bike = data.get("bike", "")
    if bike:
        from utils.sheets import get_last_mileage
        import asyncio
        loop = asyncio.get_event_loop()
        last_mileage = await loop.run_in_executor(None, get_last_mileage, bike)
        if last_mileage > 0 and new_mileage < last_mileage:
            await message.answer(
                f"⚠️ <b>Mileage error!</b>\n\n"
                f"Last recorded: <b>{last_mileage} km</b>\n"
                f"You entered: <b>{new_mileage} km</b>\n\n"
                f"Mileage cannot decrease. Please check and re-enter.",
                parse_mode="HTML",
            )
            return
    await state.update_data(mileage=digits)
    await state.set_state(AIFuelForm.photo_odometer)
    await message.answer(
        "📸 <b>Photo 2/2 — Odometer</b>\n\n"
        "⚠️ Please photograph the odometer showing current mileage.\n\n"
        "No photo? Tap Skip.",
        reply_markup=skip_comment_kb(),
        parse_mode="HTML",
    )


@router.message(AIFuelForm.photo_odometer, F.photo)
async def ai_fuel_photo_odometer(message: Message, state: FSMContext):
    await state.update_data(photo_odometer=message.photo[-1].file_id)
    await _aifuel_show_confirm(message, state)


@router.message(AIFuelForm.photo_odometer, F.text.in_({"⏭ Skip", "⏭ Skip (no receipt)"}))
async def ai_fuel_photo_odometer_skip(message: Message, state: FSMContext):
    await state.update_data(photo_odometer="")
    await _aifuel_show_confirm(message, state)


@router.message(AIFuelForm.photo_odometer)
async def ai_fuel_photo_odometer_invalid(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(AIFuelForm.mileage)
        await message.answer("🔢 Mileage (km):", reply_markup=back_cancel_kb())
        return
    await message.answer("📸 Send odometer photo or tap Skip.", reply_markup=skip_comment_kb())


# ─── Universal Cancel for all FuelForm states ─────────────────
@router.message(F.text == "❌ Cancel")
async def cancel_any_fuel_state(message: Message, state: FSMContext):
    current = await state.get_state()
    if current and (current.startswith("FuelForm:") or current.startswith("AIFuelForm:")):
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))

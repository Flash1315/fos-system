from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import EMPLOYEES, MANAGERS
from keyboards.kb import cancel_kb, back_cancel_kb, skip_cancel_kb, skip_comment_kb, confirm_kb, main_menu, calendar_kb, expense_categories_kb, numeric_cancel_kb
from utils.sheets import append_expense, async_get_all_balances, get_total_since_last_payout, get_total_since_last_handover, get_held_cash_on_hand, preview_spending_total, format_idr, now_time
from utils.notify import post_expense_to_group

router = Router()

MILEAGE_CATEGORIES = ("Bike service", "Tires pressure / Wheel repair")
GPS_MILEAGE_CATEGORIES = ("Bike service", "Tires pressure / Wheel repair", "Bensin")
AI_BIKE_CATEGORIES = ("Bike service", "Tires pressure / Wheel repair", "Bensin")


def _find_bike_imei(bike_name: str) -> str | None:
    from config import BIKES_GPS
    bike_lower = bike_name.lower().strip()
    for imei, info in BIKES_GPS.items():
        gps_name = info.get("name", "").lower()
        if bike_lower in gps_name or gps_name in bike_lower:
            return imei
    bike_words = [w.lower() for w in bike_name.split() if len(w) > 2]
    for imei, info in BIKES_GPS.items():
        gps_name = info.get("name", "").lower()
        if any(w in gps_name for w in bike_words):
            return imei
    return None


async def update_gps_mileage_background(date: str, time: str, employee: str, bike: str, category: str):
    """Fetch GPS total odometer from device detail; update sheet in background."""
    if category not in GPS_MILEAGE_CATEGORIES or not bike:
        return
    import asyncio
    from utils.sheets import update_expense_gps_mileage
    from utils.gps import get_device_total_mileage

    loop = asyncio.get_event_loop()

    imei = await loop.run_in_executor(None, _find_bike_imei, bike)
    if not imei:
        await loop.run_in_executor(None, update_expense_gps_mileage, date, time, employee, "No GPS")
        return

    km = await get_device_total_mileage(imei)
    gps_val = "GPS error" if km is None else f"{km:.0f} km"
    await loop.run_in_executor(None, update_expense_gps_mileage, date, time, employee, gps_val)


class ExpenseForm(StatesGroup):
    manager_group = State()
    manager_name = State()
    date = State()
    category = State()
    category_custom = State()
    purpose = State()
    bike = State()
    place = State()
    payment_source = State()
    amount = State()
    mileage = State()
    comment = State()
    photo_receipt = State()
    receipt_ai_merge = State()
    photo_item = State()
    confirm = State()


class AIExpenseForm(StatesGroup):
    manager_group = State()
    manager_name = State()
    date = State()
    purpose = State()
    rental_bike = State()
    category = State()
    category_custom = State()
    bike = State()
    photo_receipt = State()
    ai_review = State()
    manual_amount = State()
    edit_value = State()
    payment_source = State()
    mileage = State()
    photo_item = State()
    confirm = State()

def get_employee(uid): return EMPLOYEES.get(uid)
def is_authorized(uid): return uid in EMPLOYEES or uid in MANAGERS
def get_name(uid):
    e = EMPLOYEES.get(uid)
    return e["name"] if e else MANAGERS.get(uid, {}).get("name", "Unknown")


async def _expense_after_purpose(message: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("category", "")
    purpose = data.get("purpose", "")
    if purpose == "Rental" or text in ("Bike service", "Tires pressure / Wheel repair"):
        await state.set_state(ExpenseForm.bike)
        from keyboards.kb import bikes_kb
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
    else:
        await state.set_state(ExpenseForm.place)
        await message.answer("🏪 Where did you buy it? (shop / place name):", reply_markup=back_cancel_kb())


async def _expense_purpose_back(message: Message, state: FSMContext):
    await state.set_state(ExpenseForm.category)
    await message.answer("📂 Select category:", reply_markup=expense_categories_kb())

@router.message(F.text == "\U0001f4b8 Expenses")
async def start_expense(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    if uid in MANAGERS and uid not in EMPLOYEES:
        await state.set_state(ExpenseForm.manager_group)
        from config import EMPLOYEES as EMPS, MANAGER_GROUP_CHAT_ID
        all_groups = MANAGERS.get(uid, {}).get("all_groups", False)
        if all_groups:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"mgr_group:{eid}")] for eid, info in EMPS.items()]
            buttons.append([InlineKeyboardButton(text="\U0001f454 Manager group", callback_data="mgr_group:manager")])
        else:
            buttons = [[InlineKeyboardButton(text="\U0001f454 Manager group", callback_data="mgr_group:manager")]]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("\U0001f4b8 <b>New expense</b>\n\n\U0001f465 Send to which group?", reply_markup=kb, parse_mode="HTML")
        return
    await state.set_state(ExpenseForm.date)
    await message.answer("\U0001f4b8 <b>New expense</b>\n\n\U0001f4c5 Select date:", reply_markup=cancel_kb(), parse_mode="HTML")
    await message.answer("\U0001f447", reply_markup=calendar_kb())


@router.callback_query(F.data.startswith("mgr_group:"), ExpenseForm.manager_group)
async def mgr_group_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS, MANAGER_GROUP_CHAT_ID
    group_key = call.data.split(":")[1]
    uid = call.from_user.id
    my_name = MANAGERS.get(uid, {}).get("name", "Manager")
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if group_key == "manager":
        await state.update_data(mgr_group_chat=MANAGER_GROUP_CHAT_ID, mgr_emp_uid=None)
        if is_superadmin:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"mgr_name:mgr_{mid}")] for mid, info in MANAGERS.items()]
            for eid, einfo in EMPS.items():
                buttons.append([InlineKeyboardButton(text=einfo["name"], callback_data=f"mgr_name:{eid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")]]
    else:
        emp_uid = int(group_key)
        emp = EMPS.get(emp_uid, {})
        await state.update_data(mgr_group_chat=emp.get("group_chat_id"), mgr_emp_uid=emp_uid)
        if is_superadmin:
            buttons = [
                [InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")],
                [InlineKeyboardButton(text=emp.get("name","Employee"), callback_data=f"mgr_name:{emp_uid}")],
            ]
            for mgr_uid, mgr_info in MANAGERS.items():
                if mgr_uid != uid:
                    buttons.append([InlineKeyboardButton(text=mgr_info["name"], callback_data=f"mgr_name:mgr_{mgr_uid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")]]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(ExpenseForm.manager_name)
    await call.message.answer("👤 Record under whose name?", reply_markup=kb)
    await call.answer()

@router.callback_query(F.data.startswith("mgr_name:"), ExpenseForm.manager_name)
async def mgr_name_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS
    name_id = call.data.split(":")[1]
    if name_id == "manager":
        uid = call.from_user.id
        record_name = MANAGERS.get(uid, {}).get("name", "Manager")
    elif name_id.startswith("mgr_"):
        mgr_uid = int(name_id.replace("mgr_", ""))
        record_name = MANAGERS.get(mgr_uid, {}).get("name", "Manager")
    else:
        emp = EMPS.get(int(name_id), {})
        record_name = emp.get("name", "Manager")
    await state.update_data(mgr_record_name=record_name)
    await state.set_state(ExpenseForm.date)
    await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
    await call.message.answer("👇", reply_markup=calendar_kb())
    await call.answer()

@router.message(ExpenseForm.category)
async def expense_category(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "❌ Cancel":
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    if text == "⬅️ Back":
        await state.set_state(ExpenseForm.date)
        await message.answer("📅 Select date:", reply_markup=cancel_kb())
        await message.answer("👇", reply_markup=calendar_kb())
        return
    if text == "Other":
        await state.set_state(ExpenseForm.category_custom)
        await message.answer("✏️ Enter custom category:", reply_markup=back_cancel_kb())
        return
    await state.update_data(category=text)
    await state.set_state(ExpenseForm.purpose)
    from utils.purpose_flow import show_purpose_prompt
    await show_purpose_prompt(message, "exppur", "Expense purpose:")

@router.message(ExpenseForm.category_custom)
async def expense_category_custom(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(ExpenseForm.category)
        await message.answer("📂 Select category:", reply_markup=expense_categories_kb())
        return
    await state.update_data(category=message.text.strip())
    await state.set_state(ExpenseForm.purpose)
    from utils.purpose_flow import show_purpose_prompt
    await show_purpose_prompt(message, "exppur", "Expense purpose:")


@router.callback_query(F.data.startswith("exppur:"), ExpenseForm.purpose)
async def expense_purpose_callback(call: CallbackQuery, state: FSMContext):
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
        await _expense_purpose_back(call.message, state)
        await call.answer()
        return
    await state.update_data(purpose=action)
    await call.message.delete()
    await _expense_after_purpose(call.message, state)
    await call.answer()


@router.message(ExpenseForm.bike)
async def expense_bike(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "❌ Cancel":
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    if text == "⬅️ Back":
        await state.set_state(ExpenseForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await show_purpose_prompt(message, "exppur", "Expense purpose:")
        return
    if text.startswith("—"):
        return
    if text == "Other (enter manually)":
        await state.update_data(bike="Other")
    else:
        await state.update_data(bike=text)
    await state.set_state(ExpenseForm.place)
    await message.answer("🏪 Where did you buy it? (shop / place name):", reply_markup=back_cancel_kb())

@router.message(ExpenseForm.place)
async def expense_place(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("category") in ("Bike service", "Tires pressure / Wheel repair") or data.get("purpose") == "Rental":
            await state.set_state(ExpenseForm.bike)
            from keyboards.kb import bikes_kb
            await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        else:
            await state.set_state(ExpenseForm.purpose)
            from utils.purpose_flow import show_purpose_prompt
            await show_purpose_prompt(message, "exppur", "Expense purpose:")
        return
    await state.update_data(place=message.text.strip())
    await state.set_state(ExpenseForm.amount)
    await message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())

@router.message(ExpenseForm.amount)
async def expense_amount(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(ExpenseForm.place)
        await message.answer("🏪 Where did you buy it?", reply_markup=back_cancel_kb())
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number, e.g. 25000")
        return
    await state.update_data(amount=int(digits))
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 My pocket", callback_data="paysrc:my_pocket"),
         InlineKeyboardButton(text="💰 Cash on hand", callback_data="paysrc:cash_on_hand")]
    ])
    await state.set_state(ExpenseForm.payment_source)
    await message.answer(
        f"✅ Amount: <b>{format_idr(int(digits))}</b>\n\n💳 <b>Paid from:</b>",
        reply_markup=kb, parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("paysrc:"), ExpenseForm.payment_source)
async def expense_payment_source(callback: CallbackQuery, state: FSMContext):
    source = "My pocket" if callback.data == "paysrc:my_pocket" else "Cash on hand"
    await state.update_data(payment_source=source)
    await callback.message.delete()
    data = await state.get_data()
    if data.get("category") in MILEAGE_CATEGORIES:
        await state.set_state(ExpenseForm.mileage)
        await callback.message.answer(
            f"💳 {source}\n\n🔢 <b>Mileage (km)</b> — required for {data['category']}:",
            reply_markup=back_cancel_kb(), parse_mode="HTML"
        )
    else:
        await state.set_state(ExpenseForm.comment)
        await callback.message.answer(
            f"💳 {source}\n\n💬 <b>Comment</b> (optional)\n\nAdd any notes, or tap Skip.",
            reply_markup=skip_comment_kb(), parse_mode="HTML"
        )

@router.message(ExpenseForm.mileage, F.text)
async def expense_mileage(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(ExpenseForm.amount)
        await message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
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
    await state.set_state(ExpenseForm.comment)
    await message.answer(
        f"✅ Mileage: <b>{digits} km</b>\n\n💬 <b>Comment</b> (optional)\n\n"
        f"What was repaired? Shop name, parts, work done — or tap Skip.",
        reply_markup=skip_comment_kb(), parse_mode="HTML"
    )

@router.message(ExpenseForm.comment, F.text)
async def expense_comment(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("category") in MILEAGE_CATEGORIES:
            await state.set_state(ExpenseForm.mileage)
            await message.answer("🔢 Mileage (km):", reply_markup=back_cancel_kb())
        else:
            await state.set_state(ExpenseForm.amount)
            await message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
        return
    if message.text in ("⏭ Skip", "⏭ Skip (no receipt)"):
        await state.update_data(comment="")
    else:
        await state.update_data(comment=message.text.strip())
    await state.set_state(ExpenseForm.photo_receipt)
    await message.answer(
        "📸 <b>Photo 1/2 — Receipt</b>\n\n"
        "⚠️ Please photograph the receipt.\n\n"
        "No receipt? Tap Skip.",
        reply_markup=skip_cancel_kb(), parse_mode="HTML"
    )

@router.message(ExpenseForm.photo_receipt, F.photo)
async def expense_photo_receipt(message: Message, state: FSMContext):
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
            await state.set_state(ExpenseForm.receipt_ai_merge)
            text = "🤖 <b>AI read:</b>\n" + "\n".join(info_lines)
            await processing.edit_text(text, reply_markup=receipt_comment_kb("exrcmt"), parse_mode="HTML")
            return
        if updates:
            await state.update_data(**updates)
        if info_lines:
            await processing.edit_text("🤖 <b>AI read:</b>\n" + "\n".join(info_lines), parse_mode="HTML")
        else:
            await processing.delete()
    except Exception as e:
        print(f"Expense receipt AI error: {e}")
        await processing.delete()
    await ask_photo_item(message, state)


@router.callback_query(F.data.startswith("exrcmt:"), ExpenseForm.receipt_ai_merge)
async def expense_receipt_comment_merge(call: CallbackQuery, state: FSMContext):
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
    await call.message.answer(f"💬 Comment saved.")
    await ask_photo_item(call.message, state)
    await call.answer()

@router.message(ExpenseForm.photo_receipt, F.text == "⏭ Skip (no receipt)")
async def expense_photo_receipt_skip(message: Message, state: FSMContext):
    await state.update_data(photo_receipt="")
    await ask_photo_item(message, state)

async def ask_photo_item(message: Message, state: FSMContext):
    await state.set_state(ExpenseForm.photo_item)
    await message.bot.send_message(
        message.chat.id,
        "📸 <b>Photo 2/2 — The item(s) purchased</b>\n\n"
        "⚠️ Please photograph what you bought.\n\n"
        "No photo? Tap Skip.",
        reply_markup=skip_cancel_kb(), parse_mode="HTML"
    )

@router.message(ExpenseForm.photo_item, F.photo)
async def expense_photo_item(message: Message, state: FSMContext):
    await state.update_data(photo_item=message.photo[-1].file_id)
    processing = await message.answer("⏳")
    await show_confirm(message, state)
    await processing.delete()

@router.message(ExpenseForm.photo_item, F.text == "⏭ Skip (no receipt)")
async def expense_photo_item_skip(message: Message, state: FSMContext):
    await state.update_data(photo_item="")
    await show_confirm(message, state)

async def show_confirm(message: Message, state: FSMContext):
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
    mileage_line = f"🔢 {data['mileage']} km\n" if data.get("mileage") else ""
    bike_line = f"🏍 {data['bike']}\n" if data.get("bike") else ""
    purpose_line = f"🎯 {data.get('purpose', '—')}\n"
    text = (
        f"📋 <b>Please confirm:</b>\n\n"
        f"{extra}"
        f"📅 {data['date']}\n"
        f"📂 {data['category']}\n"
        f"{purpose_line}"
        f"{bike_line}"
        f"🏪 {data['place']}\n"
        f"💵 {format_idr(data['amount'])}\n"
        f"{mileage_line}"
        f"💬 {data.get('comment', '') or '—'}\n"
        f"📸 Receipt: {'✅' if data.get('photo_receipt') else '⚠️ Not provided'}\n"
        f"📸 Item photo: {'✅' if data.get('photo_item') else '⚠️ Not provided'}\n\n"
        f"{totals_block}"
    )
    await state.set_state(ExpenseForm.confirm)
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")

@router.message(ExpenseForm.confirm, F.text == "✅ Confirm")
async def expense_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    emp = get_employee(uid)
    name = data.get("mgr_record_name") or get_name(uid)
    time = now_time()
    payment_source = data.get("payment_source", "My pocket")

    place = data["place"]
    if data.get("bike"):
        place = f"{data['bike']} — {place}"
    mileage = data.get("mileage", "") if data.get("category") in MILEAGE_CATEGORIES else ""
    purpose = data.get("purpose", "")
    rental_id = ""
    if purpose == "Rental":
        import asyncio
        from utils.sheets import get_rental_id_for_bike
        bike_for_rental = data.get("bike", "")
        loop = asyncio.get_event_loop()
        rental_id = await loop.run_in_executor(None, get_rental_id_for_bike, bike_for_rental)
    comment = data.get("comment", "")
    await append_expense(
        data["date"], time, data["category"], place, data["amount"], "", "", name,
        comment, payment_source=payment_source,
        mileage=mileage, gps_mileage="",
        purpose=purpose, rental_id=rental_id,
    )

    total_since = get_total_since_last_payout(name)
    if payment_source == "My pocket":
        saved_line = f"📊 Total since last payout: <b>{format_idr(total_since)}</b>"
        group_total = total_since
    else:
        saved_line = f"💰 Cash on hand: <b>{format_idr(get_held_cash_on_hand(name))}</b>"
        group_total = total_since

    group_chat_id = data.get("mgr_group_chat") or (emp["group_chat_id"] if emp else None)
    tg_message_id = ""
    if group_chat_id:
        tg_message_id = await post_expense_to_group(
            bot=message.bot,
            group_chat_id=group_chat_id,
            employee_name=name,
            note=f"{data['category']} — {data['place']}",
            date=data["date"],
            amount=data["amount"],
            total_spending=group_total,
            photo_file_id=data.get("photo_receipt", ""), comment=data.get("comment", ""), photo_file_id2=data.get("photo_item", "")
        ) or ""

    # Обновляем запись с message_id
    from utils.sheets import update_expense_tg_id
    update_expense_tg_id(data["date"], time, name, str(tg_message_id), str(group_chat_id) if group_chat_id else "")

    await state.clear()
    await message.answer(
        f"✅ Saved!\n{saved_line}",
        reply_markup=main_menu(is_manager=uid in MANAGERS), parse_mode="HTML"
    )

    import asyncio
    async def upload_and_update():
        try:
            from utils.drive_upload import upload_receipt_to_drive
            from utils.sheets import update_expense_photos
            receipt_url = ""
            item_url = ""
            if data.get("photo_receipt"):
                receipt_url = await upload_receipt_to_drive(
                    message.bot, data["photo_receipt"],
                    f"{data['date'].replace('.', '-')}_{name}_receipt.jpg", data["date"]
                )
            if data.get("photo_item"):
                item_url = await upload_receipt_to_drive(
                    message.bot, data["photo_item"],
                    f"{data['date'].replace('.', '-')}_{name}_item.jpg", data["date"]
                )
            if receipt_url or item_url:
                update_expense_photos(data["date"], time, name, receipt_url, item_url)
        except Exception as e:
            print(f"Background upload error: {e}")
    async def safe_upload():
        try:
            await upload_and_update()
        except Exception as e:
            print(f"create_task upload error: {e}")
    asyncio.create_task(safe_upload())

    if data.get("category") in GPS_MILEAGE_CATEGORIES and data.get("bike"):
        saved_date, saved_time, saved_bike, saved_category = data["date"], time, data["bike"], data["category"]

        async def safe_gps():
            try:
                await update_gps_mileage_background(saved_date, saved_time, name, saved_bike, saved_category)
            except Exception as e:
                print(f"GPS mileage background error: {e}")

        asyncio.create_task(safe_gps())

@router.message(ExpenseForm.confirm, F.text == "✏️ Edit")
async def expense_edit(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="📅 Date", callback_data="edit_exp:date")],
        [InlineKeyboardButton(text="📂 Category", callback_data="edit_exp:category")],
        [InlineKeyboardButton(text="🏪 Place", callback_data="edit_exp:place")],
        [InlineKeyboardButton(text="💵 Amount", callback_data="edit_exp:amount")],
        [InlineKeyboardButton(text="💬 Comment", callback_data="edit_exp:comment")],
        [InlineKeyboardButton(text="❌ Cancel edit", callback_data="edit_exp:cancel")],
    ]
    await message.answer("✏️ What do you want to edit?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("edit_exp:"))
async def expense_edit_field(call: CallbackQuery, state: FSMContext):
    await call.answer()
    field = call.data.split(":")[1]
    if field == "cancel":
        await call.message.edit_text("Edit cancelled.")
        return
    if field == "date":
        await state.set_state(ExpenseForm.date)
        await call.message.answer("📅 Select new date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb())
    elif field == "category":
        await state.set_state(ExpenseForm.category)
        await call.message.answer("📂 Select category:", reply_markup=expense_categories_kb())
    elif field == "place":
        await state.set_state(ExpenseForm.place)
        await call.message.answer("🏪 Place:", reply_markup=back_cancel_kb())
    elif field == "amount":
        await state.set_state(ExpenseForm.amount)
        await call.message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
    elif field == "comment":
        await state.set_state(ExpenseForm.comment)
        await call.message.answer("💬 Comment:", reply_markup=skip_comment_kb())
    await call.message.edit_text(f"✏️ Editing: {field}")

@router.message(F.text == "📊 My balance")
async def my_balance(message: Message):
    uid = message.from_user.id
    if not is_authorized(uid): return
    name = get_name(uid)
    b = (await async_get_all_balances()).get(name)
    if not b:
        await message.answer("No data yet.")
        return
    last_pay = b.get("last_exp_payout", "—")
    last_hand = b.get("last_inc_handover", "—")
    await message.answer(
        f"💼 <b>Balance — {name}</b>\n\n"
        f"💸 Spendings: <b>{format_idr(b.get('effective_spendings', 0))}</b> (since {last_pay})\n"
        f"💰 Cash on hand: <b>{format_idr(b.get('held_by_employee', 0))}</b> (since {last_hand})",
        parse_mode="HTML"
    )

@router.message(F.text == "📋 My records")
async def my_records(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    if is_superadmin:
        all_users = {**EMPLOYEES, **MANAGERS}
        buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"records:{info['name']}")] for _, info in all_users.items()]
        buttons.append([InlineKeyboardButton(text="👥 All employees", callback_data="records:ALL")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="records:cancel")])
        await message.answer("Select employee:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await show_records(message, get_name(uid))

async def show_records(message, name):
    try:
        from utils.sheets import get_sheet, SHEET_EXPENSES, EXP_COL_EMPLOYEE, EXP_COL_PLACE, EXP_COL_AMOUNT, EXP_COL_CATEGORY
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        if name == "ALL":
            user_rows = [r for r in rows if len(r) > EXP_COL_EMPLOYEE and r[EXP_COL_EMPLOYEE] not in ('','Employee') and r[0] not in ('','Date','TOTAL') and not r[0].startswith('=')]
        else:
            user_rows = [r for r in rows if len(r) > EXP_COL_EMPLOYEE and r[EXP_COL_EMPLOYEE] == name and r[0] not in ('','Date','TOTAL') and not r[0].startswith('=')]
        last5 = user_rows[-5:]
        if not last5:
            await message.answer('No records yet.')
            return
        title = f"Last records — {name}:\n\n" if name != "ALL" else "Last records — All employees:\n\n"
        text = title
        for r in reversed(last5):
            emp = f"[{r[EXP_COL_EMPLOYEE]}] " if name == "ALL" else ""
            text += emp + r[0]+' | '+r[EXP_COL_CATEGORY]+' | '+r[EXP_COL_PLACE]+' | IDR '+str(r[EXP_COL_AMOUNT])+'\n'
        await message.answer(text)
    except Exception as e:
        await message.answer('Error: '+str(e))

@router.callback_query(F.data.startswith("records:"))
async def records_callback(call: CallbackQuery):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await call.message.edit_text("Cancelled.")
        return
    await call.message.edit_text(f"Loading records...")
    await show_records(call.message, choice)


# ─── AI Expense flow (separate from manual ExpenseForm) ─────────

def _ai_fmt(val) -> str:
    if val is None or val == "":
        return "—"
    return str(val)


def _ai_receipt_unreadable(data: dict) -> bool:
    return not any([
        data.get("amount"),
        data.get("place"),
        data.get("items"),
        data.get("receipt_date"),
    ])


def _ai_needs_bike_step(data: dict) -> bool:
    category = data.get("category", "")
    if category not in AI_BIKE_CATEGORIES:
        return False
    return not data.get("bike")


def _ai_ai_review_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Confirm", callback_data="aiexpread:confirm"),
            InlineKeyboardButton(text="✏️ Edit", callback_data="aiexpread:edit"),
        ],
        [InlineKeyboardButton(text="📷 Retake photo", callback_data="aiexpread:retake")],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="aiexpread:back"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="aiexpread:cancel"),
        ],
    ])


def _ai_edit_fields_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 Amount", callback_data="aiexpedit:amount"),
            InlineKeyboardButton(text="🏪 Place", callback_data="aiexpedit:place"),
        ],
        [
            InlineKeyboardButton(text="📋 Items", callback_data="aiexpedit:items"),
            InlineKeyboardButton(text="📅 Date", callback_data="aiexpedit:receipt_date"),
        ],
        [InlineKeyboardButton(text="⬅️ Back to review", callback_data="aiexpedit:back")],
    ])


def _ai_payment_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💵 My pocket", callback_data="aiexpaysrc:my_pocket"),
            InlineKeyboardButton(text="💰 Cash on hand", callback_data="aiexpaysrc:cash_on_hand"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="aiexpaysrc:back"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="aiexpaysrc:cancel"),
        ],
    ])


def _ai_final_edit_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Date", callback_data="aiexpfedit:date"),
            InlineKeyboardButton(text="📂 Category", callback_data="aiexpfedit:category"),
        ],
        [
            InlineKeyboardButton(text="🏪 Place", callback_data="aiexpfedit:place"),
            InlineKeyboardButton(text="💵 Amount", callback_data="aiexpfedit:amount"),
        ],
        [
            InlineKeyboardButton(text="📋 Items", callback_data="aiexpfedit:items"),
            InlineKeyboardButton(text="💳 Payment", callback_data="aiexpfedit:payment"),
        ],
        [InlineKeyboardButton(text="❌ Cancel edit", callback_data="aiexpfedit:cancel")],
    ])


async def _ai_cancel(message_or_call, state: FSMContext, uid: int):
    await state.clear()
    target = message_or_call.message if hasattr(message_or_call, "message") else message_or_call
    await target.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))


def _ai_employee_name(data: dict, uid: int) -> str:
    return data.get("mgr_record_name") or get_name(uid)


async def _ai_show_category(message: Message, state: FSMContext):
    await state.set_state(AIExpenseForm.category)
    await message.answer("📂 Select category:", reply_markup=expense_categories_kb())


async def _ai_go_photo_step(message: Message, state: FSMContext):
    await state.set_state(AIExpenseForm.photo_receipt)
    await message.answer(
        "📸 Photo the receipt. I'll read everything I can.",
        reply_markup=back_cancel_kb(),
    )


async def _ai_show_ai_review(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    amount_line = format_idr(amount) if amount else "—"
    text = (
        "🤖 <b>AI read:</b>\n"
        f"📍 Place: {_ai_fmt(data.get('place'))}\n"
        f"📋 Items: {_ai_fmt(data.get('items'))}\n"
        f"💵 Amount: {amount_line}\n"
        f"📅 Date on receipt: {_ai_fmt(data.get('receipt_date'))}\n\n"
        "✅ Confirm / ✏️ Edit / 📷 Retake photo"
    )
    await state.set_state(AIExpenseForm.ai_review)
    await message.answer(text, reply_markup=_ai_ai_review_kb(), parse_mode="HTML")


async def _ai_show_payment(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    if not amount:
        await message.answer("⚠️ Amount is required. Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        await state.set_state(AIExpenseForm.manual_amount)
        return
    await state.set_state(AIExpenseForm.payment_source)
    await message.answer(
        f"✅ Amount: <b>{format_idr(amount)}</b>\n\n💳 <b>Paid from:</b>",
        reply_markup=_ai_payment_kb(),
        parse_mode="HTML",
    )


async def _ai_go_photo_item(message: Message, state: FSMContext):
    await state.set_state(AIExpenseForm.photo_item)
    await message.answer(
        "📸 <b>Photo 2/2 — The item(s) purchased</b>\n\n"
        "⚠️ Please photograph what you bought.\n\n"
        "No photo? Tap Skip.",
        reply_markup=skip_cancel_kb(),
        parse_mode="HTML",
    )


async def _ai_after_payment_or_mileage(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("ai_return_to") == "confirm":
        await state.update_data(ai_return_to=None)
        await _ai_show_final_confirm(message, state)
    else:
        await _ai_go_photo_item(message, state)


async def _ai_show_final_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    name = _ai_employee_name(data, uid)
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
        if group_chat == MANAGER_GROUP_CHAT_ID:
            group_name = "Manager group"
        extra = f"👥 Group: {group_name}\n👤 Name: {name}\n"
    mileage_line = f"🔢 {data['mileage']} km\n" if data.get("mileage") else ""
    bike_line = f"🏍 {data['bike']}\n" if data.get("bike") else ""
    purpose_line = f"🎯 {data.get('purpose', '—')}\n"
    receipt_date_line = f"📅 Receipt date: {_ai_fmt(data.get('receipt_date'))}\n" if data.get("receipt_date") else ""
    text = (
        f"📋 <b>Please confirm:</b>\n\n"
        f"{extra}"
        f"📅 {data['date']}\n"
        f"📂 {data['category']}\n"
        f"{purpose_line}"
        f"{bike_line}"
        f"🏪 {_ai_fmt(data.get('place'))}\n"
        f"💵 {format_idr(data['amount'])}\n"
        f"{receipt_date_line}"
        f"💬 {data.get('items', '') or '—'}\n"
        f"{mileage_line}"
        f"📸 Receipt: {'✅' if data.get('photo_receipt') else '⚠️ Not provided'}\n"
        f"📸 Item photo: {'✅' if data.get('photo_item') else '⚠️ Not provided'}\n\n"
        f"{totals_block}"
    )
    await state.set_state(AIExpenseForm.confirm)
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")


@router.message(F.text == "🧾 Add expense (AI)")
async def start_ai_expense(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid):
        return
    if uid in MANAGERS and uid not in EMPLOYEES:
        await state.set_state(AIExpenseForm.manager_group)
        from config import EMPLOYEES as EMPS
        all_groups = MANAGERS.get(uid, {}).get("all_groups", False)
        if all_groups:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"mgr_group:{eid}")] for eid, info in EMPS.items()]
            buttons.append([InlineKeyboardButton(text="👔 Manager group", callback_data="mgr_group:manager")])
        else:
            buttons = [[InlineKeyboardButton(text="👔 Manager group", callback_data="mgr_group:manager")]]
        kb = InlineKeyboardMarkup(inline_keyboard=buttons)
        await message.answer("🧾 <b>New expense (AI)</b>\n\n👥 Send to which group?", reply_markup=kb, parse_mode="HTML")
        return
    await state.set_state(AIExpenseForm.date)
    await message.answer("🧾 <b>New expense (AI)</b>\n\n📅 Select date:", reply_markup=cancel_kb(), parse_mode="HTML")
    await message.answer("👇", reply_markup=calendar_kb(prefix="aical"))


@router.callback_query(F.data.startswith("mgr_group:"), AIExpenseForm.manager_group)
async def ai_mgr_group_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS, MANAGER_GROUP_CHAT_ID
    group_key = call.data.split(":")[1]
    uid = call.from_user.id
    my_name = MANAGERS.get(uid, {}).get("name", "Manager")
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if group_key == "manager":
        await state.update_data(mgr_group_chat=MANAGER_GROUP_CHAT_ID, mgr_emp_uid=None)
        if is_superadmin:
            buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"mgr_name:mgr_{mid}")] for mid, info in MANAGERS.items()]
            for eid, einfo in EMPS.items():
                buttons.append([InlineKeyboardButton(text=einfo["name"], callback_data=f"mgr_name:{eid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")]]
    else:
        emp_uid = int(group_key)
        emp = EMPS.get(emp_uid, {})
        await state.update_data(mgr_group_chat=emp.get("group_chat_id"), mgr_emp_uid=emp_uid)
        if is_superadmin:
            buttons = [
                [InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")],
                [InlineKeyboardButton(text=emp.get("name", "Employee"), callback_data=f"mgr_name:{emp_uid}")],
            ]
            for mgr_uid, mgr_info in MANAGERS.items():
                if mgr_uid != uid:
                    buttons.append([InlineKeyboardButton(text=mgr_info["name"], callback_data=f"mgr_name:mgr_{mgr_uid}")])
        else:
            buttons = [[InlineKeyboardButton(text=f"👔 {my_name} (me)", callback_data="mgr_name:manager")]]

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await state.set_state(AIExpenseForm.manager_name)
    await call.message.answer("👤 Record under whose name?", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("mgr_name:"), AIExpenseForm.manager_name)
async def ai_mgr_name_selected(call: CallbackQuery, state: FSMContext):
    from config import EMPLOYEES as EMPS, MANAGERS
    name_id = call.data.split(":")[1]
    if name_id == "manager":
        uid = call.from_user.id
        record_name = MANAGERS.get(uid, {}).get("name", "Manager")
    elif name_id.startswith("mgr_"):
        mgr_uid = int(name_id.replace("mgr_", ""))
        record_name = MANAGERS.get(mgr_uid, {}).get("name", "Manager")
    else:
        emp = EMPS.get(int(name_id), {})
        record_name = emp.get("name", "Manager")
    await state.update_data(mgr_record_name=record_name)
    await state.set_state(AIExpenseForm.date)
    await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
    await call.message.answer("👇", reply_markup=calendar_kb(prefix="aical"))
    await call.answer()


@router.callback_query(F.data.startswith("aiexppur:"), AIExpenseForm.purpose)
async def ai_expense_purpose_callback(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _ai_cancel(call, state, uid)
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await state.set_state(AIExpenseForm.date)
        await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix="aical"))
        await call.answer()
        return
    await state.update_data(purpose=action)
    await call.message.delete()
    if action == "Rental":
        await state.set_state(AIExpenseForm.rental_bike)
        from keyboards.kb import bikes_kb
        await call.message.answer("🏍 Select bike for rental ID:", reply_markup=bikes_kb())
    else:
        await _ai_show_category(call.message, state)
    await call.answer()


@router.message(AIExpenseForm.rental_bike)
async def ai_expense_rental_bike(message: Message, state: FSMContext):
    text = message.text.strip()
    uid = message.from_user.id
    if text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if text == "⬅️ Back":
        await state.set_state(AIExpenseForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await show_purpose_prompt(message, "aiexppur", "Expense purpose:")
        return
    if text.startswith("—"):
        return
    if text == "Other (enter manually)":
        await state.update_data(bike="Other")
    else:
        await state.update_data(bike=text)
    await _ai_show_category(message, state)


@router.message(AIExpenseForm.category)
async def ai_expense_category(message: Message, state: FSMContext):
    text = message.text.strip()
    uid = message.from_user.id
    if text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if text == "⬅️ Back":
        data = await state.get_data()
        if data.get("ai_return_to") == "confirm":
            await state.update_data(ai_return_to=None)
            await _ai_show_final_confirm(message, state)
            return
        if data.get("purpose") == "Rental":
            await state.set_state(AIExpenseForm.rental_bike)
            from keyboards.kb import bikes_kb
            await message.answer("🏍 Select bike for rental ID:", reply_markup=bikes_kb())
        else:
            await state.set_state(AIExpenseForm.purpose)
            from utils.purpose_flow import show_purpose_prompt
            await show_purpose_prompt(message, "aiexppur", "Expense purpose:")
        return
    if text == "Other":
        await state.set_state(AIExpenseForm.category_custom)
        await message.answer("✏️ Enter custom category:", reply_markup=back_cancel_kb())
        return
    await state.update_data(category=text)
    data = await state.get_data()
    if data.get("ai_return_to") == "confirm":
        await state.update_data(ai_return_to=None)
        await _ai_show_final_confirm(message, state)
        return
    if _ai_needs_bike_step(data):
        await state.set_state(AIExpenseForm.bike)
        from keyboards.kb import bikes_kb
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
    else:
        await _ai_go_photo_step(message, state)


@router.message(AIExpenseForm.category_custom)
async def ai_expense_category_custom(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("ai_return_to") == "confirm":
            await state.update_data(ai_return_to=None)
            await _ai_show_final_confirm(message, state)
            return
        await _ai_show_category(message, state)
        return
    await state.update_data(category=message.text.strip())
    data = await state.get_data()
    if data.get("ai_return_to") == "confirm":
        await state.update_data(ai_return_to=None)
        await _ai_show_final_confirm(message, state)
        return
    if _ai_needs_bike_step(data):
        await state.set_state(AIExpenseForm.bike)
        from keyboards.kb import bikes_kb
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
    else:
        await _ai_go_photo_step(message, state)


@router.message(AIExpenseForm.bike)
async def ai_expense_bike(message: Message, state: FSMContext):
    text = message.text.strip()
    uid = message.from_user.id
    if text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if text == "⬅️ Back":
        await _ai_show_category(message, state)
        return
    if text.startswith("—"):
        return
    if text == "Other (enter manually)":
        await state.update_data(bike="Other")
    else:
        await state.update_data(bike=text)
    await _ai_go_photo_step(message, state)


@router.message(AIExpenseForm.photo_receipt, F.photo)
async def ai_expense_photo_receipt(message: Message, state: FSMContext):
    await state.update_data(photo_receipt=message.photo[-1].file_id)
    processing = await message.answer("⏳ Reading receipt...")
    try:
        from utils.receipt_ai import read_receipt_for_ai_flow, receipt_has_data, receipt_read_failure_message

        result = await read_receipt_for_ai_flow(message.bot, message.photo[-1].file_id)
        await state.update_data(
            amount=result.get("amount"),
            place=result.get("place") or "",
            items=result.get("items") or "",
            receipt_date=result.get("receipt_date") or "",
        )
        if result.get("error"):
            await processing.edit_text(receipt_read_failure_message(result))
            await state.update_data(ai_used_manual_amount=True)
            await state.set_state(AIExpenseForm.manual_amount)
            await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        elif not receipt_has_data(result):
            await processing.edit_text(receipt_read_failure_message(result))
            await state.update_data(ai_used_manual_amount=True)
            await state.set_state(AIExpenseForm.manual_amount)
            await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        else:
            await processing.delete()
            await _ai_show_ai_review(message, state)
    except Exception as e:
        print(f"AI receipt read error: {e}")
        await processing.edit_text(f"⚠️ AI error: {e}")
        await state.update_data(ai_used_manual_amount=True)
        await state.set_state(AIExpenseForm.manual_amount)
        await message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())


@router.message(AIExpenseForm.photo_receipt)
async def ai_expense_photo_receipt_invalid(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, message.from_user.id)
        return
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if _ai_needs_bike_step(data):
            await state.set_state(AIExpenseForm.bike)
            from keyboards.kb import bikes_kb
            await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        else:
            await _ai_show_category(message, state)
        return
    await message.answer("📸 Please send a receipt photo.", reply_markup=back_cancel_kb())


@router.message(AIExpenseForm.manual_amount)
async def ai_expense_manual_amount(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _ai_go_photo_step(message, state)
        return
    digits = "".join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number, e.g. 25000")
        return
    await state.update_data(amount=int(digits))
    if not (await state.get_data()).get("place"):
        await state.update_data(place="—")
    await _ai_show_payment(message, state)


@router.callback_query(F.data.startswith("aiexpread:"), AIExpenseForm.ai_review)
async def ai_expense_read_action(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _ai_cancel(call, state, uid)
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        await _ai_go_photo_step(call.message, state)
        await call.answer()
        return
    if action == "retake":
        await call.message.delete()
        await state.update_data(photo_receipt="")
        await _ai_go_photo_step(call.message, state)
        await call.answer()
        return
    if action == "edit":
        await call.message.edit_reply_markup(reply_markup=_ai_edit_fields_kb())
        await call.answer()
        return
    if action == "confirm":
        await call.message.edit_reply_markup(reply_markup=None)
        await _ai_show_payment(call.message, state)
        await call.answer()


@router.callback_query(F.data.startswith("aiexpedit:"), AIExpenseForm.ai_review)
async def ai_expense_edit_pick(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":", 1)[1]
    if field == "back":
        await call.message.edit_reply_markup(reply_markup=_ai_ai_review_kb())
        await call.answer()
        return
    prompts = {
        "amount": "💵 Enter new amount (IDR):",
        "place": "🏪 Enter place name:",
        "items": "📋 Enter items / work description:",
        "receipt_date": "📅 Enter receipt date (dd.mm.yyyy):",
    }
    await state.update_data(ai_edit_field=field)
    await state.set_state(AIExpenseForm.edit_value)
    await call.message.answer(prompts[field], reply_markup=back_cancel_kb())
    await call.answer()


@router.message(AIExpenseForm.edit_value)
async def ai_expense_edit_value(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    data = await state.get_data()
    if message.text == "⬅️ Back":
        if data.get("ai_edit_from_confirm"):
            await state.update_data(ai_edit_from_confirm=False)
            await _ai_show_final_confirm(message, state)
        else:
            await _ai_show_ai_review(message, state)
        return
    field = data.get("ai_edit_field", "")
    text = message.text.strip()
    if field == "amount":
        digits = "".join(c for c in text if c.isdigit())
        if not digits:
            await message.answer("⚠️ Enter a number, e.g. 25000")
            return
        await state.update_data(amount=int(digits))
    elif field == "place":
        await state.update_data(place=text)
    elif field == "items":
        await state.update_data(items=text)
    elif field == "receipt_date":
        await state.update_data(receipt_date=text)
    from_confirm = data.get("ai_edit_from_confirm")
    if from_confirm:
        await state.update_data(ai_edit_from_confirm=False)
        await _ai_show_final_confirm(message, state)
    else:
        await _ai_show_ai_review(message, state)


@router.callback_query(F.data.startswith("aiexpaysrc:"), AIExpenseForm.payment_source)
async def ai_expense_payment_source(call: CallbackQuery, state: FSMContext):
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    if action == "cancel":
        await call.message.edit_reply_markup(reply_markup=None)
        await _ai_cancel(call, state, uid)
        await call.answer()
        return
    if action == "back":
        await call.message.delete()
        data = await state.get_data()
        if data.get("ai_return_to") == "confirm":
            await state.update_data(ai_return_to=None)
            await _ai_show_final_confirm(call.message, state)
        elif data.get("ai_used_manual_amount"):
            await state.set_state(AIExpenseForm.manual_amount)
            await call.message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
        else:
            await _ai_show_ai_review(call.message, state)
        await call.answer()
        return
    source = "My pocket" if action == "my_pocket" else "Cash on hand"
    await state.update_data(payment_source=source)
    await call.message.edit_reply_markup(reply_markup=None)
    data = await state.get_data()
    if data.get("ai_return_to") == "confirm":
        await state.update_data(ai_return_to=None)
        await _ai_show_final_confirm(call.message, state)
    elif data.get("category") in MILEAGE_CATEGORIES and not data.get("mileage"):
        await state.set_state(AIExpenseForm.mileage)
        await call.message.answer(
            f"💳 {source}\n\n🔢 <b>Mileage (km)</b> — required for {data['category']}:",
            reply_markup=back_cancel_kb(),
            parse_mode="HTML",
        )
    else:
        await _ai_after_payment_or_mileage(call.message, state)
    await call.answer()


@router.message(AIExpenseForm.mileage, F.text)
async def ai_expense_mileage(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        await _ai_show_payment(message, state)
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
    await _ai_after_payment_or_mileage(message, state)


@router.message(AIExpenseForm.photo_item, F.photo)
async def ai_expense_photo_item(message: Message, state: FSMContext):
    await state.update_data(photo_item=message.photo[-1].file_id)
    processing = await message.answer("⏳")
    await _ai_show_final_confirm(message, state)
    await processing.delete()


@router.message(AIExpenseForm.photo_item, F.text == "⏭ Skip (no receipt)")
async def ai_expense_photo_item_skip(message: Message, state: FSMContext):
    await state.update_data(photo_item="")
    await _ai_show_final_confirm(message, state)


@router.message(AIExpenseForm.photo_item)
async def ai_expense_photo_item_back(message: Message, state: FSMContext):
    uid = message.from_user.id
    if message.text == "❌ Cancel":
        await _ai_cancel(message, state, uid)
        return
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("category") in MILEAGE_CATEGORIES:
            await state.set_state(AIExpenseForm.mileage)
            await message.answer("🔢 Mileage (km):", reply_markup=back_cancel_kb())
        else:
            await _ai_show_payment(message, state)
        return
    await message.answer(
        "📸 Please send a photo of the item(s), or tap Skip.",
        reply_markup=skip_cancel_kb(),
    )


@router.message(AIExpenseForm.confirm, F.text == "✅ Confirm")
async def ai_expense_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    emp = get_employee(uid)
    name = _ai_employee_name(data, uid)
    time = now_time()
    payment_source = data.get("payment_source", "My pocket")

    place = data.get("place") or "—"
    if data.get("bike"):
        place = f"{data['bike']} — {place}"
    mileage = data.get("mileage", "") if data.get("category") in MILEAGE_CATEGORIES else ""
    purpose = data.get("purpose", "")
    rental_id = ""
    if purpose == "Rental":
        import asyncio
        from utils.sheets import get_rental_id_for_bike
        bike_for_rental = data.get("bike", "")
        loop = asyncio.get_event_loop()
        rental_id = await loop.run_in_executor(None, get_rental_id_for_bike, bike_for_rental)
    comment = data.get("items", "")
    await append_expense(
        data["date"], time, data["category"], place, data["amount"], "", "", name,
        comment, payment_source=payment_source,
        mileage=mileage, gps_mileage="",
        purpose=purpose, rental_id=rental_id,
    )

    total_since = get_total_since_last_payout(name)
    if payment_source == "My pocket":
        saved_line = f"📊 Total since last payout: <b>{format_idr(total_since)}</b>"
        group_total = total_since
    else:
        saved_line = f"💰 Cash on hand: <b>{format_idr(get_held_cash_on_hand(name))}</b>"
        group_total = total_since

    group_chat_id = data.get("mgr_group_chat") or (emp["group_chat_id"] if emp else None)
    tg_message_id = ""
    if group_chat_id:
        tg_message_id = await post_expense_to_group(
            bot=message.bot,
            group_chat_id=group_chat_id,
            employee_name=name,
            note=f"{data['category']} — {data.get('place') or place}",
            date=data["date"],
            amount=data["amount"],
            total_spending=group_total,
            photo_file_id=data.get("photo_receipt", ""),
            comment=comment,
            photo_file_id2=data.get("photo_item", ""),
        ) or ""

    from utils.sheets import update_expense_tg_id
    update_expense_tg_id(data["date"], time, name, str(tg_message_id), str(group_chat_id) if group_chat_id else "")

    await state.clear()
    await message.answer(
        f"✅ Saved!\n{saved_line}",
        reply_markup=main_menu(is_manager=uid in MANAGERS),
        parse_mode="HTML",
    )

    import asyncio

    async def upload_and_update():
        try:
            from utils.drive_upload import upload_receipt_to_drive
            from utils.sheets import update_expense_photos
            receipt_url = ""
            item_url = ""
            if data.get("photo_receipt"):
                receipt_url = await upload_receipt_to_drive(
                    message.bot, data["photo_receipt"],
                    f"{data['date'].replace('.', '-')}_{name}_receipt.jpg", data["date"]
                )
            if data.get("photo_item"):
                item_url = await upload_receipt_to_drive(
                    message.bot, data["photo_item"],
                    f"{data['date'].replace('.', '-')}_{name}_item.jpg", data["date"]
                )
            if receipt_url or item_url:
                update_expense_photos(data["date"], time, name, receipt_url, item_url)
        except Exception as e:
            print(f"AI expense background upload error: {e}")

    async def safe_upload():
        try:
            await upload_and_update()
        except Exception as e:
            print(f"AI expense create_task upload error: {e}")

    asyncio.create_task(safe_upload())

    if data.get("category") in GPS_MILEAGE_CATEGORIES and data.get("bike"):
        saved_date, saved_time, saved_bike, saved_category = data["date"], time, data["bike"], data["category"]

        async def safe_gps():
            try:
                await update_gps_mileage_background(saved_date, saved_time, name, saved_bike, saved_category)
            except Exception as e:
                print(f"AI expense GPS mileage background error: {e}")

        asyncio.create_task(safe_gps())


@router.message(AIExpenseForm.confirm, F.text == "✏️ Edit")
async def ai_expense_final_edit_menu(message: Message, state: FSMContext):
    await message.answer("✏️ What do you want to edit?", reply_markup=_ai_final_edit_kb())


@router.callback_query(F.data.startswith("aiexpfedit:"))
async def ai_expense_final_edit_field(call: CallbackQuery, state: FSMContext):
    field = call.data.split(":", 1)[1]
    if field == "cancel":
        await call.message.edit_text("Edit cancelled.")
        await call.answer()
        return
    if field == "date":
        await state.update_data(ai_return_to="confirm")
        await state.set_state(AIExpenseForm.date)
        await call.message.answer("📅 Select new date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix="aical"))
    elif field == "category":
        await state.update_data(ai_return_to="confirm")
        await _ai_show_category(call.message, state)
    elif field == "place":
        await state.set_state(AIExpenseForm.edit_value)
        await state.update_data(ai_edit_field="place", ai_edit_from_confirm=True)
        await call.message.answer("🏪 Enter place name:", reply_markup=back_cancel_kb())
    elif field == "amount":
        await state.set_state(AIExpenseForm.edit_value)
        await state.update_data(ai_edit_field="amount", ai_edit_from_confirm=True)
        await call.message.answer("💵 Enter amount (IDR):", reply_markup=numeric_cancel_kb())
    elif field == "items":
        await state.set_state(AIExpenseForm.edit_value)
        await state.update_data(ai_edit_field="items", ai_edit_from_confirm=True)
        await call.message.answer("📋 Enter items / work description:", reply_markup=back_cancel_kb())
    elif field == "payment":
        await state.update_data(ai_return_to="confirm")
        await _ai_show_payment(call.message, state)
    await call.message.edit_text(f"✏️ Editing: {field}")
    await call.answer()


@router.message(AIExpenseForm.confirm, F.text == "⬅️ Back")
async def ai_expense_confirm_back(message: Message, state: FSMContext):
    await _ai_go_photo_item(message, state)


# ─── Universal Cancel for all ExpenseForm states ───────────────
from aiogram.fsm.state import State
@router.message(F.text == "❌ Cancel")
async def cancel_any_expense_state(message: Message, state: FSMContext):
    current = await state.get_state()
    if current and (current.startswith("ExpenseForm:") or current.startswith("AIExpenseForm:")):
        await state.clear()
        from keyboards.kb import main_menu
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))

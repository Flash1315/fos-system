from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import EMPLOYEES, MANAGERS
from keyboards.kb import numeric_cancel_kb, cancel_kb, back_cancel_kb, skip_cancel_kb, skip_comment_kb, income_categories_kb, payment_type_kb, confirm_kb, main_menu, calendar_kb
from utils.sheets import append_income, get_total_since_last_payout, get_total_since_last_handover, format_idr, now_time
from utils.notify import post_income_to_group

router = Router()

class IncomeForm(StatesGroup):
    date = State()
    category = State()
    category_custom = State()
    purpose = State()
    client_name = State()
    num_lessons = State()
    amount = State()
    payment_type = State()
    comment = State()
    photo = State()
    confirm = State()

def get_employee(uid): return EMPLOYEES.get(uid)
def is_authorized(uid): return uid in EMPLOYEES or uid in MANAGERS
def get_name(uid):
    e = EMPLOYEES.get(uid)
    return e["name"] if e else MANAGERS.get(uid, {}).get("name", "Unknown")


async def _income_after_purpose(message: Message, state: FSMContext):
    await state.set_state(IncomeForm.client_name)
    await message.answer("👤 Client name:", reply_markup=back_cancel_kb())


async def _income_purpose_back(message: Message, state: FSMContext):
    await state.set_state(IncomeForm.category)
    await message.answer("📂 Category:", reply_markup=income_categories_kb())

@router.message(F.text == "💰 Income")
async def start_income(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id): return
    await state.set_state(IncomeForm.date)
    await message.answer("💰 <b>Income</b>\n\n📅 Select date:", reply_markup=cancel_kb(), parse_mode="HTML")
    await message.answer("👇", reply_markup=calendar_kb())

@router.message(IncomeForm.category)
async def income_category(message: Message, state: FSMContext):
    text = message.text.strip()
    if text == "⬅️ Back":
        await state.set_state(IncomeForm.date)
        await message.answer("📅 Select date:", reply_markup=cancel_kb())
        await message.answer("👇", reply_markup=calendar_kb())
        return
    if "Other" in text:
        await state.set_state(IncomeForm.category_custom)
        await message.answer("✏️ Enter custom category:", reply_markup=back_cancel_kb())
        return
    await state.update_data(category=text)
    await state.set_state(IncomeForm.purpose)
    from utils.purpose_flow import show_purpose_prompt
    await show_purpose_prompt(message, "incpur", "Income purpose:")

@router.message(IncomeForm.category_custom)
async def income_category_custom(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(IncomeForm.category)
        await message.answer("📂 Category:", reply_markup=income_categories_kb())
        return
    await state.update_data(category=message.text.strip())
    await state.set_state(IncomeForm.purpose)
    from utils.purpose_flow import show_purpose_prompt
    await show_purpose_prompt(message, "incpur", "Income purpose:")


@router.callback_query(F.data.startswith("incpur:"), IncomeForm.purpose)
async def income_purpose_callback(call: CallbackQuery, state: FSMContext):
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
        await _income_purpose_back(call.message, state)
        await call.answer()
        return
    await state.update_data(purpose=action)
    await call.message.delete()
    await _income_after_purpose(call.message, state)
    await call.answer()

@router.message(IncomeForm.client_name)
async def income_client_name(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(IncomeForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await show_purpose_prompt(message, "incpur", "Income purpose:")
        return
    await state.update_data(client_name=message.text.strip())
    data = await state.get_data()
    category = data.get("category", "")
    if category == "Lesson":
        await state.set_state(IncomeForm.num_lessons)
        from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
        kb = ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
            [KeyboardButton(text="4"), KeyboardButton(text="5"), KeyboardButton(text="Other")],
            [KeyboardButton(text="❌ Cancel")],
        ], resize_keyboard=True)
        await message.answer("🔢 Number of lessons:", reply_markup=kb)
    else:
        await state.update_data(num_lessons="—")
        await state.set_state(IncomeForm.amount)
        await message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())

@router.message(IncomeForm.num_lessons)
async def income_num_lessons(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(IncomeForm.client_name)
        await message.answer("👤 Client name:", reply_markup=back_cancel_kb())
        return
    await state.update_data(num_lessons=message.text.strip())
    await state.set_state(IncomeForm.amount)
    await message.answer("💵 Amount (IDR) — just numbers, e.g. 750000:", reply_markup=numeric_cancel_kb())

@router.message(IncomeForm.amount)
async def income_amount(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("category") == "Lesson":
            await state.set_state(IncomeForm.num_lessons)
            from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
            kb = ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="1"), KeyboardButton(text="2"), KeyboardButton(text="3")],
                [KeyboardButton(text="4"), KeyboardButton(text="5"), KeyboardButton(text="Other")],
                [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
            ], resize_keyboard=True)
            await message.answer("🔢 Number of lessons:", reply_markup=kb)
        else:
            await state.set_state(IncomeForm.client_name)
            await message.answer("👤 Client name:", reply_markup=back_cancel_kb())
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(amount=int(digits))
    await state.set_state(IncomeForm.payment_type)
    await message.answer(
        f"✅ Amount: <b>{format_idr(int(digits))}</b>\n\n💳 Cash or transfer?",
        reply_markup=payment_type_kb(), parse_mode="HTML"
    )

@router.message(IncomeForm.payment_type)
async def income_payment(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(IncomeForm.amount)
        await message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
        return
    pt = message.text.replace("💵 ", "").replace("💳 ", "").strip()
    await state.update_data(payment_type=pt)
    await state.set_state(IncomeForm.comment)
    await message.answer(
        "💬 <b>Comment</b> (optional)\n\nAdd any notes, or tap Skip.",
        reply_markup=skip_comment_kb(), parse_mode="HTML"
    )

@router.message(IncomeForm.comment, F.text)
async def income_comment(message: Message, state: FSMContext):
    if message.text == "⬅️ Back":
        await state.set_state(IncomeForm.payment_type)
        await message.answer("💳 Payment type:", reply_markup=payment_type_kb())
        return
    if message.text in ("⏭ Skip", "⏭ Skip (no receipt)"):
        await state.update_data(comment="")
    else:
        await state.update_data(comment=message.text.strip())
    await state.set_state(IncomeForm.photo)
    await message.answer(
        "📸 <b>Payment confirmation photo</b> (optional)\n\n"
        "If payment was made by transfer — photograph the screen.\n"
        "For cash — you can skip this.\n\n"
        "Tap Skip if no photo needed.",
        reply_markup=skip_cancel_kb(), parse_mode="HTML"
    )

@router.message(IncomeForm.photo, F.photo)
async def income_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await show_income_confirm(message, state)

@router.message(IncomeForm.photo, F.text == "⏭ Skip (no receipt)")
async def income_photo_skip(message: Message, state: FSMContext):
    await state.update_data(photo="")
    await show_income_confirm(message, state)

async def show_income_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    name = data.get("mgr_record_name") or get_name(message.from_user.id)
    total_inc = get_total_since_last_handover(name) + data["amount"]
    total_exp = get_total_since_last_payout(name)
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
        f"📋 <b>Please confirm:</b>\n\n"
        f"{extra}"
        f"📅 {data['date']}\n"
        f"📂 {data['category']}\n"
        f"🎯 {data.get('purpose', '—')}\n"
        f"👤 {data['client_name']}\n"
        f"🔢 Lessons: {data['num_lessons']}\n"
        f"💵 {format_idr(data['amount'])} ({data['payment_type']})\n"
        f"💬 {data.get('comment', '') or '—'}\n"
        f"📸 Proof: {'✅' if data.get('photo') else '—'}\n\n"
        f"💸 Spendings since last payout: {format_idr(total_exp)}\n"
        f"📊 Cash income after this: <b>{format_idr(total_inc)}</b> (since last handover)"
    )
    await state.set_state(IncomeForm.confirm)
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")

@router.message(IncomeForm.confirm, F.text == "✅ Confirm")
async def income_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    name = data.get("mgr_record_name") or get_name(uid)
    time = now_time()

    total_inc = get_total_since_last_handover(name) + data["amount"]
    purpose = data.get("purpose", "")
    rental_id = ""
    if purpose == "Rental":
        import asyncio
        from utils.sheets import get_rental_id_for_client
        loop = asyncio.get_event_loop()
        rental_id = await loop.run_in_executor(None, get_rental_id_for_client, data.get("client_name", ""))
    await append_income(
        data["date"], time, data["category"], data["client_name"],
        data["num_lessons"], data["amount"], name, data.get("comment", ""),
        purpose=purpose, rental_id=rental_id, payment_type=data.get("payment_type", ""),
    )
    total_exp = get_total_since_last_payout(name)

    group_chat_id = data.get("mgr_group_chat")
    if not group_chat_id:
        for einfo in EMPLOYEES.values():
            if einfo.get("name") == name:
                group_chat_id = einfo.get("group_chat_id")
                break
    if group_chat_id:
        await post_income_to_group(
            bot=message.bot,
            group_chat_id=group_chat_id,
            employee_name=name,
            client_name=data["client_name"],
            note=f"{data['category']} — {data['num_lessons']} lesson(s)",
            date=data["date"],
            amount=data["amount"],
            total_income=total_inc,
            total_spending=total_exp
        )

    await state.clear()
    await message.answer(
        f"✅ Saved!\n📊 Total income: <b>{format_idr(total_inc)}</b>",
        reply_markup=main_menu(is_manager=uid in MANAGERS), parse_mode="HTML"
    )

    import asyncio
    from utils.sheets import get_sheet, SHEET_INCOME, INC_COL_EMPLOYEE, INC_CELL_PHOTO
    saved_date = data["date"]
    saved_time = time
    saved_name = name
    async def upload_income_photo():
        try:
            from utils.drive_upload import upload_receipt_to_drive
            if not data.get("photo"):
                return
            photo_url = await upload_receipt_to_drive(
                message.bot, data["photo"],
                f"{saved_date.replace('.', '-')}_{saved_name}_payment.jpg", saved_date
            )
            if not photo_url:
                return
            from utils.sheets import reset_sheet_cache
            reset_sheet_cache()
            ws = get_sheet(SHEET_INCOME)
            rows = ws.get_all_values()
            for i, row in enumerate(rows):
                if len(row) > INC_COL_EMPLOYEE and row[0] == saved_date and row[1] == saved_time and row[INC_COL_EMPLOYEE] == saved_name:
                    ws.update_cell(i+1, INC_CELL_PHOTO, '=HYPERLINK("' + photo_url + '";"photo")')
                    print(f"Updated income photo for {saved_name} {saved_date} {saved_time}")
                    return
            print(f"[income photos] NOT FOUND for {saved_name} {saved_date} {saved_time}")
        except Exception as e:
            print(f"Income upload error: {e}")
    asyncio.create_task(upload_income_photo())

@router.message(IncomeForm.confirm, F.text == "✏️ Edit")
async def income_edit(message: Message, state: FSMContext):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="📅 Date", callback_data="edit_inc:date")],
        [InlineKeyboardButton(text="📂 Category", callback_data="edit_inc:category")],
        [InlineKeyboardButton(text="👤 Client name", callback_data="edit_inc:client")],
        [InlineKeyboardButton(text="💵 Amount", callback_data="edit_inc:amount")],
        [InlineKeyboardButton(text="💳 Payment type", callback_data="edit_inc:payment")],
        [InlineKeyboardButton(text="💬 Comment", callback_data="edit_inc:comment")],
        [InlineKeyboardButton(text="❌ Cancel edit", callback_data="edit_inc:cancel")],
    ]
    await message.answer("✏️ What do you want to edit?", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("edit_inc:"))
async def income_edit_field(call: CallbackQuery, state: FSMContext):
    await call.answer()
    field = call.data.split(":")[1]
    if field == "cancel":
        await call.message.edit_text("Edit cancelled.")
        return
    if field == "date":
        await state.set_state(IncomeForm.date)
        await call.message.answer("📅 Select new date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb())
    elif field == "category":
        await state.set_state(IncomeForm.category)
        await call.message.answer("📂 Category:", reply_markup=income_categories_kb())
    elif field == "client":
        await state.set_state(IncomeForm.client_name)
        await call.message.answer("👤 Client name:", reply_markup=back_cancel_kb())
    elif field == "amount":
        await state.set_state(IncomeForm.amount)
        await call.message.answer("💵 Amount (IDR):", reply_markup=numeric_cancel_kb())
    elif field == "payment":
        await state.set_state(IncomeForm.payment_type)
        await call.message.answer("💳 Payment type:", reply_markup=payment_type_kb())
    elif field == "comment":
        await state.set_state(IncomeForm.comment)
        await call.message.answer("💬 Comment:", reply_markup=skip_comment_kb())
    await call.message.edit_text(f"✏️ Editing: {field}")

# ─── Universal Cancel for all IncomeForm states ────────────────
@router.message(F.text == "❌ Cancel")
async def cancel_any_income_state(message: Message, state: FSMContext):
    current = await state.get_state()
    if current and current.startswith("IncomeForm:"):
        await state.clear()
        from keyboards.kb import main_menu
        await message.answer("Cancelled.", reply_markup=main_menu())

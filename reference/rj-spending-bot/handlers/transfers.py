from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EMPLOYEES, MANAGERS
from keyboards.kb import cancel_kb, back_cancel_kb, confirm_kb, main_menu
from utils.sheets import format_idr, now_time, append_income, append_payout, fix_income_times_after_handover, invalidate_balance_cache
from datetime import datetime

router = Router()

def is_authorized(uid): return uid in EMPLOYEES or uid in MANAGERS
def get_name(uid):
    e = EMPLOYEES.get(uid)
    return e["name"] if e else MANAGERS.get(uid, {}).get("name", "Unknown")

# ─── Transfer to company ───────────────────────────────────────

class TransferCompanyState(StatesGroup):
    enter_amount = State()
    confirm = State()

@router.message(F.text == "🏦 Transfer to company")
async def transfer_company_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    await state.set_state(TransferCompanyState.enter_amount)
    await message.answer("🏦 <b>Transfer to company account</b>\n\n💵 Enter amount (IDR):", reply_markup=cancel_kb(), parse_mode="HTML")

@router.message(TransferCompanyState.enter_amount)
async def transfer_company_amount(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(amount=int(digits))
    name = get_name(message.from_user.id)
    await state.set_state(TransferCompanyState.confirm)
    await message.answer(
        f"🏦 <b>Transfer to company</b>\n\n"
        f"👤 {name}\n"
        f"💵 Amount: {format_idr(int(digits))}\n\n"
        f"This will be sent to manager for confirmation.",
        reply_markup=confirm_kb(), parse_mode="HTML"
    )

@router.message(TransferCompanyState.confirm, F.text == "✅ Confirm")
async def transfer_company_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    name = get_name(uid)
    amount = data["amount"]
    from config import MANAGER_GROUP_CHAT_ID
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm receipt", callback_data=f"tcmp_ok:{uid}:{amount}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"tcmp_no:{uid}:{amount}")],
    ])
    await message.bot.send_message(
        chat_id=MANAGER_GROUP_CHAT_ID,
        text=f"🏦 <b>Transfer to company — pending confirmation</b>\n\n👤 {name}\n💵 {format_idr(amount)}",
        reply_markup=buttons, parse_mode="HTML"
    )
    await state.clear()
    await message.answer("✅ Request sent to manager for confirmation.", reply_markup=main_menu(is_manager=uid in MANAGERS))

@router.message(TransferCompanyState.confirm, F.text == "❌ Cancel")
async def transfer_company_cancel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))

@router.callback_query(F.data.startswith("tcmp_ok:"))
async def transfer_company_approve(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    emp_uid = int(parts[1])
    amount = int(parts[2])
    emp_name = get_name(emp_uid)
    today = datetime.now().strftime("%d.%m.%Y")
    from config import EMPLOYEES as EMPS, MANAGERS as MGRS
    group_chat = ""
    for uid, info in {**EMPS, **MGRS}.items():
        if uid == emp_uid:
            group_chat = str(info.get("group_chat_id", ""))
            break
    await append_payout(today, now_time(), "Income handover", emp_name, amount, "Bank transfer")
    try:
        fix_income_times_after_handover(emp_name, today)
    except Exception as e:
        print(f"fix_income_times_after_handover error: {e}")
    invalidate_balance_cache()
    if group_chat:
        await call.bot.send_message(
            chat_id=int(group_chat),
            text=f"✅ <b>Transfer to company confirmed</b>\n\n💵 {format_idr(amount)}\n📅 {today}",
            parse_mode="HTML"
        )
    manager_name = MANAGERS.get(call.from_user.id, {}).get("name", "Manager")
    await call.message.edit_text(f"✅ Confirmed by {manager_name}. {emp_name}: {format_idr(amount)} recorded.")

@router.callback_query(F.data.startswith("tcmp_no:"))
async def transfer_company_reject(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    emp_uid = int(parts[1])
    amount = int(parts[2])
    emp_name = get_name(emp_uid)
    from config import EMPLOYEES as EMPS, MANAGERS as MGRS
    group_chat = ""
    for uid, info in {**EMPS, **MGRS}.items():
        if uid == emp_uid:
            group_chat = str(info.get("group_chat_id", ""))
            break
    if group_chat:
        await call.bot.send_message(
            chat_id=int(group_chat),
            text=f"❌ <b>Transfer to company rejected by manager</b>\n\n💵 {format_idr(amount)}",
            parse_mode="HTML"
        )
    await call.message.edit_text(f"❌ Rejected. {emp_name}: {format_idr(amount)} not recorded.")

# ─── Transfer to colleague ─────────────────────────────────────

class TransferColleagueState(StatesGroup):
    select_recipient = State()
    enter_amount = State()
    confirm = State()

@router.message(F.text == "🔄 Transfer to colleague")
async def transfer_colleague_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    my_name = get_name(uid)
    all_users = {**EMPLOYEES, **MANAGERS}
    buttons = []
    for euid, info in all_users.items():
        if euid != uid:
            buttons.append([InlineKeyboardButton(text=info["name"], callback_data=f"tclg_to:{euid}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="tclg_to:cancel")])
    await state.set_state(TransferColleagueState.select_recipient)
    await message.answer("🔄 <b>Transfer to colleague</b>\n\n👤 Select recipient:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("tclg_to:"), TransferColleagueState.select_recipient)
async def transfer_colleague_recipient(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":")[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    recipient_uid = int(choice)
    all_users = {**EMPLOYEES, **MANAGERS}
    recipient_info = all_users.get(recipient_uid, {})
    recipient_name = recipient_info.get("name", "Unknown")
    recipient_group = str(recipient_info.get("group_chat_id", ""))
    await state.update_data(recipient_uid=recipient_uid, recipient_name=recipient_name, recipient_group=recipient_group)
    await state.set_state(TransferColleagueState.enter_amount)
    await call.message.answer(f"🔄 Transfer to <b>{recipient_name}</b>\n\n💵 Enter amount (IDR):", reply_markup=back_cancel_kb(), parse_mode="HTML")

@router.message(TransferColleagueState.enter_amount)
async def transfer_colleague_amount(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        uid = message.from_user.id
        await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
        return
    if message.text == "⬅️ Back":
        await state.set_state(TransferColleagueState.select_recipient)
        uid = message.from_user.id
        my_name = get_name(uid)
        all_users = {**EMPLOYEES, **MANAGERS}
        buttons = []
        for euid, info in all_users.items():
            if euid != uid:
                buttons.append([InlineKeyboardButton(text=info["name"], callback_data=f"tclg_to:{euid}")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="tclg_to:cancel")])
        await message.answer("👤 Select recipient:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(amount=int(digits))
    data = await state.get_data()
    sender_name = get_name(message.from_user.id)
    await state.set_state(TransferColleagueState.confirm)
    await message.answer(
        f"🔄 <b>Transfer to colleague</b>\n\n"
        f"👤 From: {sender_name}\n"
        f"👤 To: {data['recipient_name']}\n"
        f"💵 Amount: {format_idr(int(digits))}\n\n"
        f"Confirm?",
        reply_markup=confirm_kb(), parse_mode="HTML"
    )

@router.message(TransferColleagueState.confirm, F.text == "✅ Confirm")
async def transfer_colleague_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    uid = message.from_user.id
    sender_name = get_name(uid)
    amount = data["amount"]
    recipient_name = data["recipient_name"]
    recipient_group = data.get("recipient_group", "")
    today = datetime.now().strftime("%d.%m.%Y")
    from config import EMPLOYEES as EMPS, MANAGERS as MGRS
    sender_group = ""
    for euid, info in {**EMPS, **MGRS}.items():
        if euid == uid:
            sender_group = str(info.get("group_chat_id", ""))
            break
    notify_text = (
        f"🔄 <b>Cash transfer between colleagues</b>\n\n"
        f"👤 From: {sender_name}\n"
        f"👤 To: {recipient_name}\n"
        f"💵 {format_idr(amount)}\n"
        f"📅 {today}"
    )
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Received", callback_data=f"tclg_ok:{uid}:{data['recipient_uid']}:{amount}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"tclg_no:{uid}:{data['recipient_uid']}:{amount}")],
    ])
    if recipient_group:
        await message.bot.send_message(chat_id=int(recipient_group), text=notify_text, reply_markup=buttons, parse_mode="HTML")
    from config import MANAGER_GROUP_CHAT_ID
    await message.bot.send_message(chat_id=MANAGER_GROUP_CHAT_ID, text=notify_text, parse_mode="HTML")
    await state.clear()
    await message.answer("✅ Transfer request sent. Waiting for recipient confirmation.", reply_markup=main_menu(is_manager=uid in MANAGERS))

@router.message(TransferColleagueState.confirm, F.text == "❌ Cancel")
async def transfer_colleague_cancel(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))

@router.callback_query(F.data.startswith("tclg_ok:"))
async def transfer_colleague_approve(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    sender_uid = int(parts[1])
    recipient_uid = int(parts[2])
    amount = int(parts[3])
    sender_name = get_name(sender_uid)
    recipient_name = get_name(recipient_uid)
    today = datetime.now().strftime("%d.%m.%Y")
    from config import EMPLOYEES as EMPS, MANAGERS as MGRS
    sender_group = ""
    for uid, info in {**EMPS, **MGRS}.items():
        if uid == sender_uid:
            sender_group = str(info.get("group_chat_id", ""))
            break
    await append_payout(today, now_time(), "Income handover", sender_name, amount, "Transfer to colleague")
    time = now_time()
    await append_income(
        today, time, "Other (sales equipment etc.)", sender_name, "—", amount, recipient_name,
        comment=f"Cash from {sender_name}", purpose="Other", payment_type="Cash",
    )
    try:
        fix_income_times_after_handover(sender_name, today)
    except Exception as e:
        print(f"fix_income_times_after_handover error: {e}")
    invalidate_balance_cache()
    if sender_group:
        await call.bot.send_message(
            chat_id=int(sender_group),
            text=f"✅ <b>{recipient_name} confirmed receiving cash</b>\n\n💵 {format_idr(amount)}\n📅 {today}",
            parse_mode="HTML"
        )
    await call.message.edit_text(f"✅ {recipient_name} confirmed. {sender_name} → {format_idr(amount)} recorded.")

@router.callback_query(F.data.startswith("tclg_no:"))
async def transfer_colleague_reject(call: CallbackQuery):
    await call.answer()
    parts = call.data.split(":")
    sender_uid = int(parts[1])
    amount = int(parts[3])
    sender_name = get_name(sender_uid)
    from config import EMPLOYEES as EMPS, MANAGERS as MGRS
    sender_group = ""
    for uid, info in {**EMPS, **MGRS}.items():
        if uid == sender_uid:
            sender_group = str(info.get("group_chat_id", ""))
            break
    if sender_group:
        await call.bot.send_message(
            chat_id=int(sender_group),
            text=f"❌ <b>Transfer rejected</b>\n\n💵 {format_idr(amount)}",
            parse_mode="HTML"
        )
    await call.message.edit_text(f"❌ Transfer rejected. {sender_name}: {format_idr(amount)} not recorded.")

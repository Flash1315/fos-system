import uuid
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS, EMPLOYEES, SHEET_EXPENSES, SHEET_INCOME, SHEET_PAYOUTS
from keyboards.kb import manager_menu_kb, manager_record_inline, main_menu, employee_select_kb, payment_type_kb, pay_expense_type_kb, receive_income_type_kb, cancel_kb
from utils.sheets import get_all_balances, async_get_all_balances, append_payout, format_idr, highlight_paid_rows, fix_income_times_after_handover, now_time, get_all_pending, invalidate_balance_cache
from utils.notify import post_payout_to_group, post_income_handover_to_group, delete_tg_messages

router = Router()

class ManagerState(StatesGroup):
    commenting = State()
    pay_select_employee = State()
    pay_enter_amount = State()
    pay_select_type = State()
    pay_confirm = State()
    receive_select_employee = State()
    receive_enter_amount = State()
    receive_select_type = State()
    receive_confirm = State()

def is_manager(uid): return uid in MANAGERS

def format_expense(r):
    return (
        f"🆔 <code>{r.get('ID','?')}</code> | 👤 {r.get('Employee','—')}\n"
        f"📅 {r.get('Date','—')}\n"
        f"📝 {r.get('Note','—')}\n"
        f"💵 {format_idr(int(str(r.get('Amount (IDR)',0)).replace(',','').replace('.','') or 0))}\n"
        f"🎯 {r.get('Purpose','—')}"
    )

def format_income(r):
    return (
        f"🆔 <code>{r.get('ID','?')}</code> | 👤 {r.get('Added by','—')}\n"
        f"📅 {r.get('Date','—')}\n"
        f"📂 {r.get('Category','—')} | 👤 {r.get('Client name','—')}\n"
        f"💵 {format_idr(int(str(r.get('Amount (IDR)',0)).replace(',','').replace('.','') or 0))}\n"
        f"💳 {r.get('Cash / Transfer','—')}"
    )

@router.message(F.text == "👔 Manager")
async def manager_menu(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_manager(uid): return
    await state.clear()
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    await message.answer("👔 <b>Manager panel</b>", reply_markup=manager_menu_kb(is_superadmin=is_superadmin), parse_mode="HTML")

@router.message(F.text == "📋 Pending expenses")
async def view_pending_expenses(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id): return
    records = get_all_pending(SHEET_EXPENSES)
    if not records:
        await message.answer("✅ No new expenses.")
        return
    for r in records[:10]:
        await message.answer(format_expense(r), reply_markup=manager_record_inline("expenses", str(r.get("ID",""))), parse_mode="HTML")

@router.message(F.text == "📋 Pending income")
async def view_pending_income(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id): return
    records = get_all_pending(SHEET_INCOME)
    if not records:
        await message.answer("✅ No new income.")
        return
    for r in records[:10]:
        await message.answer(format_income(r), reply_markup=manager_record_inline("income", str(r.get("ID",""))), parse_mode="HTML")

@router.callback_query(F.data.startswith("approve:"))
async def approve_record(call: CallbackQuery):
    if not is_manager(call.from_user.id): return
    _, sheet_type, record_id = call.data.split(":")
    sheet = SHEET_EXPENSES if sheet_type == "expenses" else SHEET_INCOME
    update_row_by_id(sheet, record_id, {"Status": "✅ Approved"})
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ Approved: <code>{record_id}</code>", parse_mode="HTML")
    await call.answer("Approved!")

@router.callback_query(F.data.startswith("reject:"))
async def reject_record(call: CallbackQuery):
    if not is_manager(call.from_user.id): return
    _, sheet_type, record_id = call.data.split(":")
    sheet = SHEET_EXPENSES if sheet_type == "expenses" else SHEET_INCOME
    update_row_by_id(sheet, record_id, {"Status": "❌ Rejected"})
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ Rejected: <code>{record_id}</code>", parse_mode="HTML")
    await call.answer("Rejected!")

@router.callback_query(F.data.startswith("comment:"))
async def add_comment_start(call: CallbackQuery, state: FSMContext):
    if not is_manager(call.from_user.id): return
    _, sheet_type, record_id = call.data.split(":")
    await state.update_data(comment_sheet=sheet_type, comment_record_id=record_id)
    await state.set_state(ManagerState.commenting)
    await call.message.answer(f"💬 Comment for <code>{record_id}</code>:", parse_mode="HTML")
    await call.answer()

@router.message(ManagerState.commenting)
async def save_comment(message: Message, state: FSMContext):
    data = await state.get_data()
    sheet = SHEET_EXPENSES if data["comment_sheet"] == "expenses" else SHEET_INCOME
    update_row_by_id(sheet, data["comment_record_id"], {"Manager comment": message.text.strip()})
    await state.clear()
    await message.answer("💬 Comment saved.", reply_markup=manager_menu_kb())

# ─── All balances ─────────────────────────────────────────────

@router.message(F.text == "💼 All balances")
async def all_balances(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id): return
    from config import MANAGERS
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    all_users = {**EMPLOYEES, **MANAGERS}
    buttons = [[InlineKeyboardButton(text=info["name"], callback_data=f"bal:{info['name']}")] for _, info in all_users.items()]
    buttons.append([InlineKeyboardButton(text="👥 All", callback_data="bal:ALL")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="bal:cancel")])
    await message.answer("👤 Select employee:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

def format_balance_text(name, b):
    last_pay = b.get("last_exp_payout", "—")
    last_hand = b.get("last_inc_handover", "—")
    return (
        f"👤 <b>{name}</b>\n"
        f"  💸 Spendings: {format_idr(b.get('effective_spendings', 0))} (since {last_pay})\n"
        f"  💰 Cash on hand: {format_idr(b.get('held_by_employee', 0))} (since {last_hand})\n\n"
    )

@router.callback_query(F.data.startswith("bal:"))
async def bal_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await call.message.edit_text("Cancelled.")
        return
    balances = await async_get_all_balances()
    if not balances:
        await call.message.edit_text("No data yet.")
        return
    if choice == "ALL":
        text = "💼 <b>All balances</b>\n\n"
        for name, b in balances.items():
            text += format_balance_text(name, b)
    else:
        b = balances.get(choice)
        if not b:
            await call.message.edit_text(f"No data for {choice}.")
            return
        text = f"💼 <b>Balance — {choice}</b>\n\n" + format_balance_text(choice, b)
    await call.message.edit_text(text, parse_mode="HTML")

# ─── Pay expense ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("emp:"), ManagerState.pay_select_employee)
async def pay_select_employee(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    from config import MANAGERS
    all_users = {**EMPLOYEES, **MANAGERS}
    balances = await async_get_all_balances()

    if choice == "ALL":
        # Auto amounts for all
        today = datetime.now().strftime("%d.%m.%Y")
        lines = []
        all_data = []
        for uid, info in all_users.items():
            name = info["name"]
            b = balances.get(name, {})
            owed = b.get("effective_spendings", 0)
            held = b.get("held_by_employee", 0)
            group = info.get("group_chat_id")
            all_data.append({"name": name, "owed": b.get('effective_spendings', 0), "held": held, "group": group})
            lines.append(f"👤 <b>{name}</b>: {format_idr(owed)}")
        await state.update_data(pay_all=True, pay_all_data=all_data)
        await state.set_state(ManagerState.pay_select_type)
        text = "💸 <b>Pay all employees</b>\n\n" + "\n".join(lines) + "\n\n💳 Payment type:"
        await call.message.answer(text, reply_markup=pay_expense_type_kb(), parse_mode="HTML")
    else:
        uid = int(choice)
        info = all_users.get(uid)
        if not info:
            await call.message.answer("Not found.")
            return
        name = info["name"]
        b = balances.get(name, {})
        owed = b.get("effective_spendings", 0)
        held = b.get("held_by_employee", 0)
        group = info.get("group_chat_id")
        await state.update_data(pay_all=False, pay_uid=uid, pay_name=name, pay_group=group, pay_owed=owed, pay_held=held, pay_spendings=b.get("effective_spendings", 0))
        await state.set_state(ManagerState.pay_enter_amount)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        spendings_val = b.get('effective_spendings', 0)
        spendings = b.get('effective_spendings', 0)
        await call.message.answer(
            f"👤 <b>{name}</b>\n\n"
            f"💸 Spendings: <b>{format_idr(spendings)}</b>\n"
            f"💰 Cash on hand: <b>{format_idr(held)}</b>\n\n"
            f"Choose payout amount:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ Pay full: {format_idr(spendings)}", callback_data=f"payamt:{spendings}")],
                [InlineKeyboardButton(text="✏️ Enter manually", callback_data="payamt:manual")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="payamt:cancel")],
            ]),
            parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("payamt:"), ManagerState.pay_enter_amount)
async def pay_amount_choice(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if choice == "manual":
        await call.message.answer("💵 Enter amount (IDR):", reply_markup=cancel_kb())
        return
    amount = int(choice)
    await state.update_data(pay_amount=amount)
    await state.set_state(ManagerState.pay_select_type)
    data = await state.get_data()
    await call.message.answer(
        f"✅ Amount: <b>{format_idr(amount)}</b>\n\n💳 Payment type:",
        reply_markup=pay_expense_type_kb(), parse_mode="HTML"
    )

@router.message(ManagerState.pay_enter_amount)
async def pay_enter_amount_manual(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(pay_amount=int(digits))
    await state.set_state(ManagerState.pay_select_type)
    await message.answer(f"✅ Amount: <b>{format_idr(int(digits))}</b>\n\n💳 Payment type:", reply_markup=pay_expense_type_kb(), parse_mode="HTML")

@router.message(ManagerState.pay_select_type)
async def pay_confirm_step(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    if message.text == "⬅️ Back":
        data = await state.get_data()
        if data.get("pay_all"):
            await state.set_state(ManagerState.pay_select_employee)
            from config import MANAGERS
            all_users = {**EMPLOYEES, **MANAGERS}
            balances = await async_get_all_balances()
            lines = []
            for uid, info in all_users.items():
                b = balances.get(info["name"], {})
                lines.append(f"👤 <b>{info['name']}</b>: {format_idr(b.get('effective_spendings', 0))}")
            await message.answer("💸 <b>Pay all employees</b>\n\n" + "\n".join(lines) + "\n\n💳 Payment type:", reply_markup=pay_expense_type_kb(), parse_mode="HTML")
        else:
            await state.set_state(ManagerState.pay_enter_amount)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            data = await state.get_data()
            await message.answer("Choose payout amount:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"✅ Pay full: {format_idr(data.get('pay_spendings', 0))}", callback_data=f"payamt:{data.get('pay_spendings', 0)}")],
                [InlineKeyboardButton(text="✏️ Enter manually", callback_data="payamt:manual")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="payamt:cancel")],
            ]))
        return
    pt = message.text.strip()
    await state.update_data(pay_type=pt)
    data = await state.get_data()
    if data.get("pay_all"):
        lines = []
        for d in data["pay_all_data"]:
            lines.append(f"👤 <b>{d['name']}</b>: {format_idr(d['owed'])}")
        text = (
            f"📋 <b>Confirm payout — All employees</b>\n\n"
            + "\n".join(lines) +
            f"\n\n💳 {pt}\n\nConfirm?"
        )
    else:
        text = (
            f"📋 <b>Confirm payout</b>\n\n"
            f"👤 {data['pay_name']}\n"
            f"💸 Spendings: {format_idr(data.get('pay_spendings', 0))}\n"
            f"💰 Cash on hand: {format_idr(data['pay_held'])}\n"
            f"💵 Payout: {format_idr(data['pay_amount'])}\n"
            f"💳 {pt}\n\nConfirm?"
        )
    from keyboards.kb import confirm_kb
    await message.answer(text, reply_markup=confirm_kb(), parse_mode="HTML")
    await state.set_state(ManagerState.pay_confirm)

@router.message(ManagerState.pay_confirm, F.text == "✅ Confirm")
async def pay_execute(message: Message, state: FSMContext):
    data = await state.get_data()
    today = datetime.now().strftime("%d.%m.%Y")
    pt = data["pay_type"]
    if data.get("pay_all"):
        for d in data["pay_all_data"]:
            if d["owed"] <= 0:
                continue
            await append_payout(today, now_time(), "Expense payout", d["name"], d["owed"], pt)
            invalidate_balance_cache()
            try:
                highlight_paid_rows(d["name"], d["owed"])
            except Exception as e:
                print(f"Highlight error: {e}")
            if d.get("group"):
                try:
                    await post_payout_to_group(
                        bot=message.bot, group_chat_id=d["group"],
                        employee_name=d["name"], amount=d["owed"],
                        payment_type=pt, date=today
                    )
                except Exception as e:
                    print(f"Notify error {d['name']}: {e}")
        await state.clear()
        await message.answer("✅ Payout recorded for all employees.", reply_markup=manager_menu_kb())
    else:
        spendings = data.get("pay_spendings", 0)
        overpayment = max(0, data["pay_amount"] - spendings)
        tg_msg_id = ""
        if data.get("pay_group"):
            tg_msg_id = await post_payout_to_group(
                bot=message.bot, group_chat_id=data["pay_group"],
                employee_name=data["pay_name"], amount=data["pay_amount"],
                payment_type=pt, date=today,
                overpayment=overpayment
            ) or ""
        await append_payout(today, now_time(), "Expense payout", data["pay_name"], data["pay_amount"], pt, overpayment, tg_msg_id)
        invalidate_balance_cache()
        try:
            highlight_paid_rows(data["pay_name"], data["pay_amount"])
        except Exception as e:
            print(f"Highlight error: {e}")
        await state.clear()
        overpay_note = f"\n⚠️ Overpayment: {format_idr(overpayment)} — will be deducted next cycle." if overpayment > 0 else ""
        await message.answer(f"✅ Payout recorded. Notification sent to {data['pay_name']}.{overpay_note}", reply_markup=manager_menu_kb())

@router.message(ManagerState.pay_confirm, F.text == "✏️ Edit")
async def pay_edit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled. Start again.", reply_markup=manager_menu_kb())

@router.message(ManagerState.pay_confirm, F.text == "❌ Cancel")
async def pay_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.", reply_markup=manager_menu_kb())

# ─── Receive income ───────────────────────────────────────────

@router.message(F.text == "💰 Receive income")
async def receive_income_start(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id): return
    await state.set_state(ManagerState.receive_select_employee)
    await message.answer("👤 Select employee:", reply_markup=employee_select_kb(include_all=False))

@router.callback_query(F.data.startswith("emp:"), ManagerState.receive_select_employee)
async def receive_select_employee(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    from config import MANAGERS
    all_users = {**EMPLOYEES, **MANAGERS}
    uid = int(choice)
    info = all_users.get(uid)
    if not info:
        await call.message.answer("Not found.")
        return
    name = info["name"]
    group = info.get("group_chat_id")
    balances = await async_get_all_balances()
    b = balances.get(name, {})
    total_inc = b.get("total_income", 0)
    holds = b.get("held_by_employee", 0)
    await state.update_data(recv_uid=uid, recv_name=name, recv_group=group, recv_holds=holds, recv_total_inc=total_inc)
    await state.set_state(ManagerState.receive_enter_amount)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    suggest_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Receive full: {format_idr(holds)}", callback_data=f"recvamt:{holds}")],
        [InlineKeyboardButton(text="✏️ Enter manually", callback_data="recvamt:manual")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="recvamt:cancel")],
    ])
    await call.message.answer(
        f"👤 <b>{name}</b>\n\n"
        f"💰 Total income collected: <b>{format_idr(total_inc)}</b>\n"
        f"💵 Cash on hand: <b>{format_idr(holds)}</b>\n\n"
        f"Choose amount to receive:",
        reply_markup=suggest_kb, parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("recvamt:"), ManagerState.receive_enter_amount)
async def recv_amount_choice(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if choice == "manual":
        await call.message.answer("💵 Enter amount (IDR):", reply_markup=cancel_kb())
        return
    amount = int(choice)
    await state.update_data(recv_amount=amount)
    await state.set_state(ManagerState.receive_select_type)
    await call.message.answer(
        f"✅ Amount: <b>{format_idr(amount)}</b>\n\n💳 Payment type:",
        reply_markup=receive_income_type_kb(), parse_mode="HTML"
    )

@router.message(ManagerState.receive_enter_amount)
async def receive_enter_amount_manual(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number")
        return
    await state.update_data(recv_amount=int(digits))
    await state.set_state(ManagerState.receive_select_type)
    await message.answer(f"✅ Amount: <b>{format_idr(int(digits))}</b>\n\n💳 Payment type:", reply_markup=receive_income_type_kb(), parse_mode="HTML")

@router.message(ManagerState.receive_select_type)
async def receive_confirm_step(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    if message.text == "⬅️ Back":
        await state.set_state(ManagerState.receive_enter_amount)
        data = await state.get_data()
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer("Choose amount to receive:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"✅ Receive full: {format_idr(data.get('recv_holds', 0))}", callback_data=f"recvamt:{data.get('recv_holds', 0)}")],
            [InlineKeyboardButton(text="✏️ Enter manually", callback_data="recvamt:manual")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="recvamt:cancel")],
        ]))
        return
    pt = message.text.strip()
    await state.update_data(recv_type=pt)
    data = await state.get_data()
    from keyboards.kb import confirm_kb
    await message.answer(
        f"📋 <b>Confirm income handover</b>\n\n"
        f"👤 {data['recv_name']}\n"
        f"💰 Total income: {format_idr(data.get('recv_total_inc', 0))}\n"
        f"💵 Cash on hand: {format_idr(data.get('recv_holds', 0))}\n"
        f"📥 Receiving: {format_idr(data['recv_amount'])}\n"
        f"💳 {pt}\n\nConfirm?",
        reply_markup=confirm_kb(), parse_mode="HTML"
    )
    await state.set_state(ManagerState.receive_confirm)

@router.message(ManagerState.receive_confirm, F.text == "✅ Confirm")
async def receive_execute(message: Message, state: FSMContext):
    data = await state.get_data()
    today = datetime.now().strftime("%d.%m.%Y")
    tg_msg_id = ""
    if data.get("recv_group"):
        tg_msg_id = await post_income_handover_to_group(
            bot=message.bot,
            group_chat_id=data["recv_group"],
            employee_name=data["recv_name"],
            amount=data["recv_amount"],
            payment_type=data["recv_type"],
            date=today
        ) or ""
    await append_payout(today, now_time(), "Income handover", data["recv_name"], data["recv_amount"], data["recv_type"], 0, tg_msg_id)
    try:
        fix_income_times_after_handover(data["recv_name"], today)
    except Exception as e:
        print(f"fix_income_times_after_handover error: {e}")
    invalidate_balance_cache()
    await state.clear()
    await message.answer(f"✅ Handover recorded. Notification sent to {data['recv_name']}.", reply_markup=manager_menu_kb())

@router.message(ManagerState.receive_confirm, F.text == "✏️ Edit")
async def receive_edit(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled. Start again.", reply_markup=manager_menu_kb())

@router.message(ManagerState.receive_confirm, F.text == "❌ Cancel")
async def receive_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.", reply_markup=manager_menu_kb())


class RecordPickerState(StatesGroup):
    select_employees = State()
    select_date = State()
    select_records = State()


async def _recpick_start(message: Message, state: FSMContext, action: str, title: str):
    from keyboards.kb import employee_multiselect_kb
    await state.set_state(RecordPickerState.select_employees)
    await state.update_data(recpick_action=action, recpick_selected_emp=[], recpick_del_selected=[])
    await message.answer(title, reply_markup=employee_multiselect_kb([], prefix="recpick_emp"), parse_mode="HTML")


@router.callback_query(F.data.startswith("recpick_emp:"), RecordPickerState.select_employees)
async def recpick_select_employees(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    data = await state.get_data()
    selected = [str(u) for u in data.get("recpick_selected_emp", [])]

    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return

    if choice == "confirm":
        if not selected:
            await call.answer("Select at least one employee!", show_alert=True)
            return
        from utils.sheets import record_picker_employee_names, collect_record_dates_for_employees
        from keyboards.kb import record_picker_calendar_kb
        names = record_picker_employee_names(selected)
        dates = collect_record_dates_for_employees(names)
        if not dates:
            await call.answer("No records found for selected employees.", show_alert=True)
            return
        await state.update_data(recpick_emp_names=names, recpick_active_dates=list(dates))
        await state.set_state(RecordPickerState.select_date)
        await call.message.edit_text(
            f"📅 Select date ({len(names)} employee(s)):",
            reply_markup=record_picker_calendar_kb(active_dates=dates),
            parse_mode="HTML",
        )
        return

    if choice in selected:
        selected.remove(choice)
    else:
        selected.append(choice)
    await state.update_data(recpick_selected_emp=selected)
    from keyboards.kb import employee_multiselect_kb
    await call.message.edit_reply_markup(reply_markup=employee_multiselect_kb(selected, prefix="recpick_emp"))


@router.callback_query(F.data.startswith("recpick_cal:"), RecordPickerState.select_date)
async def recpick_calendar(call: CallbackQuery, state: FSMContext):
    from keyboards.kb import record_picker_calendar_kb, employee_multiselect_kb
    parts = call.data.split(":")
    action = parts[1]
    data = await state.get_data()
    active_dates = set(data.get("recpick_active_dates", []))

    if action == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        await call.answer()
        return
    if action == "back":
        selected = data.get("recpick_selected_emp", [])
        await state.set_state(RecordPickerState.select_employees)
        action_key = data.get("recpick_action", "edit")
        titles = {
            "edit": "✏️ <b>Edit record</b>\n\n👤 Select employees (tap to toggle):",
            "delete": "🗑 <b>Delete record</b>\n\n👤 Select employees (tap to toggle):",
            "comment": "💬 <b>Add comment</b>\n\n👤 Select employees (tap to toggle):",
        }
        await call.message.edit_text(
            titles.get(action_key, titles["edit"]),
            reply_markup=employee_multiselect_kb(selected, prefix="recpick_emp"),
            parse_mode="HTML",
        )
        await call.answer()
        return
    if action == "ignore":
        await call.answer()
        return

    year, month = datetime.now().year, datetime.now().month
    if action == "prev":
        year, month = int(parts[2]), int(parts[3])
        month -= 1
        if month < 1:
            month, year = 12, year - 1
    elif action == "next":
        year, month = int(parts[2]), int(parts[3])
        month += 1
        if month > 12:
            month, year = 1, year + 1
    elif action == "day":
        date_str = parts[2]
        if date_str not in active_dates:
            await call.answer("No records on this date", show_alert=True)
            return
        await _recpick_show_records(call.message, state, date_str, edit=True)
        await call.answer()
        return

    await call.message.edit_reply_markup(reply_markup=record_picker_calendar_kb(year, month, active_dates))
    await call.answer()


async def _recpick_show_records(message, state, date_str, selected_del=None, edit=False):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from utils.sheets import get_records_for_date_employees
    data = await state.get_data()
    action = data.get("recpick_action", "edit")
    names = data.get("recpick_emp_names", [])
    if selected_del is None:
        selected_del = [str(s) for s in data.get("recpick_del_selected", [])]
    include_payouts = action in ("edit", "delete")
    records = get_records_for_date_employees(
        date_str, names, include_payouts=include_payouts, expenses_income_only=(action == "comment")
    )
    if not records:
        txt = f"No records for <b>{date_str}</b>."
        if edit:
            await message.edit_text(txt, parse_mode="HTML")
        else:
            await message.answer(txt, parse_mode="HTML")
        return

    rows_map = {r["key"]: r["row"] for r in records}
    await state.update_data(recpick_date=date_str, recpick_rows_map=rows_map)
    await state.set_state(RecordPickerState.select_records)

    buttons = []
    show_emp_headers = len(names) > 1
    current_emp = None
    for rec in records:
        if show_emp_headers and rec["employee"] != current_emp:
            current_emp = rec["employee"]
            buttons.append([InlineKeyboardButton(text=f"👤 {current_emp}", callback_data="recpick_del:noop")])
        btn_label = f"{rec['icon']} {rec['label']}"[:50]
        if action == "delete":
            check = "✅" if rec["key"] in selected_del else "☐"
            buttons.append([InlineKeyboardButton(
                text=f"{check} {btn_label}",
                callback_data=f"recpick_del:{rec['sheet']}:{rec['row_idx']}",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                text=btn_label,
                callback_data=f"recpick_row:{rec['sheet']}:{rec['row_idx']}",
            )])

    if action == "delete" and selected_del:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 Delete selected ({len(selected_del)})",
            callback_data="recpick_del:confirm",
        )])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="recpick_del:back_cal"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="recpick_del:cancel"),
    ])

    titles = {
        "edit": f"✏️ Select record — <b>{date_str}</b>:",
        "delete": f"🗑 Select records — <b>{date_str}</b>:",
        "comment": f"💬 Select record — <b>{date_str}</b>:",
    }
    text = titles.get(action, titles["edit"])
    markup = InlineKeyboardMarkup(inline_keyboard=buttons)
    if edit:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await message.edit_text(text, reply_markup=markup, parse_mode="HTML")


async def _edit_record_show_fields(message, state, sheet, row_idx, row):
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from utils.sheets import EXP_COL_PLACE, INC_COL_CLIENT, PAYOUT_COL_AMOUNT, PAYOUT_COL_TYPE
    await state.update_data(sheet=sheet, row_idx=row_idx, row=row)
    if sheet == "Expenses":
        fields = [("Date", "Date"), ("Category", "Category"), ("Purpose", "Purpose"), ("Rental ID", "Rental ID"), ("Place", "Place"), ("Amount", "Amount (IDR)"), ("Mileage", "Mileage (km)"), ("GPS", "GPS Mileage"), ("Receipt", "Receipt"), ("Item photo", "Item photo"), ("Employee", "Employee"), ("Comment", "Comment")]
        record_label = f"{row[0]} | {row[2]} | {row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else row[3]}"
    elif sheet == "Income":
        fields = [("Date", "Date"), ("Category", "Category"), ("Purpose", "Purpose"), ("Rental ID", "Rental ID"), ("Client", "Client name"), ("Amount", "Amount (IDR)"), ("Employee", "Employee"), ("Comment", "Comment")]
        record_label = f"{row[0]} | {row[2]} | {row[INC_COL_CLIENT] if len(row) > INC_COL_CLIENT else row[3]}"
    else:
        fields = [("Date", "Date"), ("Time", "Time"), ("Type", "Type"), ("Employee", "Employee"), ("Amount", "Amount (IDR)"), ("Payment", "Cash / Transfer")]
        record_label = f"{row[0]} | {row[PAYOUT_COL_TYPE] if len(row) > PAYOUT_COL_TYPE else row[2]} | {row[PAYOUT_COL_AMOUNT] if len(row) > PAYOUT_COL_AMOUNT else ''}"
    buttons = [[InlineKeyboardButton(text=f[0], callback_data=f"edrec_field:{f[1]}")] for f in fields]
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="edrec_field:cancel")])
    await state.set_state(EditRecordState.select_field)
    await message.answer(
        f"✏️ <b>{record_label}</b>\n\nSelect field to edit:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("recpick_row:"), RecordPickerState.select_records)
async def recpick_select_record(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    if parts[1] == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    sheet = parts[1]
    row_idx = int(parts[2])
    data = await state.get_data()
    action = data.get("recpick_action", "edit")
    rows_map = data.get("recpick_rows_map", {})
    row = rows_map.get(f"{sheet}:{row_idx}")
    if not row:
        from utils.sheets import get_sheet
        row = get_sheet(sheet).get_all_values()[row_idx]

    if action == "edit":
        await _edit_record_show_fields(call.message, state, sheet, row_idx, row)
        return

    if action == "comment":
        from utils.sheets import EXP_COL_EMPLOYEE, INC_COL_EMPLOYEE, EXP_COL_PLACE, INC_COL_CLIENT
        emp_name = row[EXP_COL_EMPLOYEE] if sheet == "Expenses" and len(row) > EXP_COL_EMPLOYEE else (row[INC_COL_EMPLOYEE] if sheet == "Income" and len(row) > INC_COL_EMPLOYEE else "")
        group_chat = ""
        for uid, info in {**EMPLOYEES, **MANAGERS}.items():
            if info["name"] == emp_name:
                group_chat = str(info.get("group_chat_id", ""))
                break
        await state.update_data(sheet=sheet, row_idx=row_idx, row_data=row, emp_name=emp_name, group_chat=group_chat)
        await state.set_state(CommentState.enter_text)
        if sheet == "Expenses":
            record_label = f"{row[0]} | {row[2]} | {row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else row[3]}"
        else:
            record_label = f"{row[0]} | {row[2]} | {row[INC_COL_CLIENT] if len(row) > INC_COL_CLIENT else row[3]}"
        await call.message.answer(
            f"💬 <b>Comment for:</b>\n{record_label}\n\n✏️ Enter your comment:",
            reply_markup=cancel_kb(), parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("recpick_del:"), RecordPickerState.select_records)
async def recpick_delete_multiselect(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    data = await state.get_data()
    date_str = data.get("recpick_date", "")

    if action == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if action == "back_cal":
        from keyboards.kb import record_picker_calendar_kb
        active_dates = set(data.get("recpick_active_dates", []))
        await state.set_state(RecordPickerState.select_date)
        await call.message.edit_text(
            f"📅 Select date ({len(data.get('recpick_emp_names', []))} employee(s)):",
            reply_markup=record_picker_calendar_kb(active_dates=active_dates),
            parse_mode="HTML",
        )
        return
    if action == "noop":
        return
    if action == "confirm":
        selected = data.get("recpick_del_selected", [])
        if not selected:
            await call.answer("Select at least one!", show_alert=True)
            return
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = [
            [InlineKeyboardButton(text="📋 Table only", callback_data="recpick_del_act:table")],
            [InlineKeyboardButton(text="💬 Chat only", callback_data="recpick_del_act:chat")],
            [InlineKeyboardButton(text="🗑 Table + Chat", callback_data="recpick_del_act:both")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="recpick_del_act:cancel")],
        ]
        await state.set_state(DeleteState.select_action)
        await call.message.edit_text(
            f"🗑 Delete <b>{len(selected)}</b> record(s)?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML",
        )
        return

    parts = action.split(":")
    sheet, row_idx = parts[0], parts[1]
    key = f"{sheet}:{row_idx}"
    selected = [str(s) for s in data.get("recpick_del_selected", [])]
    if key in selected:
        selected.remove(key)
    else:
        selected.append(key)
    await state.update_data(recpick_del_selected=selected)
    await _recpick_show_records(call.message, state, date_str, selected_del=selected, edit=True)


@router.callback_query(F.data.startswith("recpick_del_act:"), DeleteState.select_action)
async def recpick_delete_execute(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return

    data = await state.get_data()
    selected = data.get("recpick_del_selected", [])
    rows_map = data.get("recpick_rows_map", {})
    from utils.sheets import get_sheet, reset_sheet_cache, invalidate_balance_cache
    from utils.sheets import EXP_COL_TG_MSG_ID, EXP_COL_GROUP_CHAT_ID, INC_COL_TG_MSG_ID
    from collections import defaultdict

    reset_sheet_cache()
    by_sheet = defaultdict(list)
    for key in selected:
        sheet, row_idx = key.rsplit(":", 1)
        by_sheet[sheet].append(int(row_idx))

    deleted = 0
    for sheet, indices in by_sheet.items():
        ws = get_sheet(sheet)
        for row_idx in sorted(indices, reverse=True):
            try:
                row = rows_map.get(f"{sheet}:{row_idx}", [])
                tg_msg_id = ""
                group_chat = ""
                if sheet == "Expenses" and len(row) > EXP_COL_TG_MSG_ID:
                    tg_msg_id = row[EXP_COL_TG_MSG_ID]
                    group_chat = row[EXP_COL_GROUP_CHAT_ID] if len(row) > EXP_COL_GROUP_CHAT_ID else ""
                elif sheet == "Income" and len(row) > INC_COL_TG_MSG_ID:
                    tg_msg_id = row[INC_COL_TG_MSG_ID]
                    from utils.sheets import INC_COL_EMPLOYEE
                    emp_name = row[INC_COL_EMPLOYEE] if len(row) > INC_COL_EMPLOYEE else ""
                    for uid, info in {**EMPLOYEES, **MANAGERS}.items():
                        if info["name"] == emp_name:
                            group_chat = str(info.get("group_chat_id", ""))
                            break
                elif sheet == "Payouts":
                    tg_msg_id = row[7] if len(row) > 7 else ""
                    emp_name = row[3] if len(row) > 3 else ""
                    for uid, info in {**EMPLOYEES, **MANAGERS}.items():
                        if info["name"] == emp_name:
                            group_chat = str(info.get("group_chat_id", ""))
                            break
                if action in ("both", "chat") and tg_msg_id and group_chat:
                    await delete_tg_messages(call.bot, group_chat, tg_msg_id)
                if action in ("both", "table"):
                    ws.delete_rows(row_idx + 1)
                deleted += 1
            except Exception as e:
                print(f"Delete row error: {e}")

    invalidate_balance_cache()
    await state.clear()
    uid = call.from_user.id
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)
    await call.message.edit_text(f"✅ Deleted {deleted} record(s).", reply_markup=None)
    await call.message.answer("👔 <b>Manager panel</b>", reply_markup=manager_menu_kb(is_superadmin=is_superadmin), parse_mode="HTML")


class DeleteState(StatesGroup):
    select_sheet = State()
    select_record = State()
    select_action = State()
    confirm = State()
    multi_select = State()

class CommentState(StatesGroup):
    select_sheet = State()
    select_record = State()
    enter_text = State()

class EditRecordState(StatesGroup):
    select_sheet = State()
    select_record = State()
    select_field = State()
    enter_value = State()
    enter_photo = State()

@router.message(F.text == "🗑 Delete record")
async def delete_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False):
        return
    await _recpick_start(message, state, "delete", "🗑 <b>Delete record</b>\n\n👤 Select employees (tap to toggle):")


# ─── Add comment ──────────────────────────────────────────────

@router.message(F.text == "💬 Add comment")
async def comment_start(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await _recpick_start(message, state, "comment", "💬 <b>Add comment</b>\n\n👤 Select employees (tap to toggle):")


@router.message(CommentState.enter_text)
async def comment_enter_text(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    text = message.text.strip()
    data = await state.get_data()
    sheet = data["sheet"]
    row_idx = data["row_idx"]
    emp_name = data.get("emp_name", "")
    group_chat = data.get("group_chat", "")
    row_data = data.get("row_data", [])
    # Update comment in sheet
    try:
        from utils.sheets import get_sheet, EXP_COL_COMMENT, INC_COL_COMMENT
        ws = get_sheet(sheet)
        comment_col = EXP_COL_COMMENT + 1 if sheet == "Expenses" else INC_COL_COMMENT + 1
        ws.update_cell(row_idx + 1, comment_col, text)
    except Exception as e:
        print(f"Comment update error: {e}")
    # Send to employee group chat
    from utils.sheets import EXP_COL_PLACE, INC_COL_CLIENT
    record_label = f"{row_data[0]} | {row_data[2]} | {(row_data[EXP_COL_PLACE] if len(row_data) > EXP_COL_PLACE else row_data[3]) if sheet == 'Expenses' else (row_data[INC_COL_CLIENT] if len(row_data) > INC_COL_CLIENT else row_data[3])}" if len(row_data) >= 4 else ""
    notify_text = (
        f"💬 <b>Comment from manager</b>\n\n"
        f"📋 Record: {record_label}\n"
        f"✏️ {text}"
    )
    manager_name = MANAGERS.get(message.from_user.id, {}).get("name", "Manager")
    full_text = notify_text + f"\n\n👤 {manager_name}"
    from config import MANAGER_GROUP_CHAT_ID
    if group_chat:
        try:
            await message.bot.send_message(chat_id=int(group_chat), text=full_text, parse_mode="HTML")
        except Exception as e:
            print(f"Comment notify error: {e}")
    # Send to manager group only if different from employee group
    if str(group_chat) != str(MANAGER_GROUP_CHAT_ID):
        try:
            await message.bot.send_message(chat_id=MANAGER_GROUP_CHAT_ID, text=full_text, parse_mode="HTML")
        except Exception as e:
            print(f"Manager group notify error: {e}")
    await state.clear()
    await message.answer("✅ Comment saved and sent.", reply_markup=manager_menu_kb())

# ─── Edit record ──────────────────────────────────────────────

@router.message(F.text == "✏️ Edit record")
async def edit_record_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False):
        return
    await _recpick_start(message, state, "edit", "✏️ <b>Edit record</b>\n\n👤 Select employees (tap to toggle):")


@router.callback_query(F.data.startswith("edrec_field:"), EditRecordState.select_field)
async def edit_record_select_field(call: CallbackQuery, state: FSMContext):
    await call.answer()
    field = call.data.split(":", 1)[1]
    if field == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    await state.update_data(field=field)
    data = await state.get_data()
    row = data["row"]
    # Find current value
    from utils.sheets import EXPENSE_HEADERS, INCOME_HEADERS, PAYOUT_HEADERS
    headers = {
        "Expenses": EXPENSE_HEADERS,
        "Income": INCOME_HEADERS,
        "Payouts": PAYOUT_HEADERS,
    }
    sheet_headers = headers.get(data["sheet"], [])
    col_idx = sheet_headers.index(field) if field in sheet_headers else -1
    current_val = row[col_idx] if col_idx >= 0 and col_idx < len(row) else "—"
    if field in ["Receipt", "Item photo"]:
        await state.set_state(EditRecordState.enter_photo)
        await call.message.answer(
            f"📸 Field: <b>{field}</b>\nCurrent value: <code>{current_val}</code>\n\nSend new photo:",
            reply_markup=cancel_kb(), parse_mode="HTML"
        )
    else:
        await state.set_state(EditRecordState.enter_value)
        await call.message.answer(
            f"✏️ Field: <b>{field}</b>\nCurrent value: <code>{current_val}</code>\n\nEnter new value:",
            reply_markup=cancel_kb(), parse_mode="HTML"
        )

@router.message(EditRecordState.enter_value)
async def edit_record_enter_value(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb())
        return
    data = await state.get_data()
    sheet = data["sheet"]
    row_idx = data["row_idx"]
    field = data["field"]
    new_value = message.text.strip()
    from utils.sheets import EXPENSE_HEADERS, INCOME_HEADERS, PAYOUT_HEADERS
    headers = {
        "Expenses": EXPENSE_HEADERS,
        "Income": INCOME_HEADERS,
        "Payouts": PAYOUT_HEADERS,
    }
    sheet_headers = headers.get(sheet, [])
    col_idx = sheet_headers.index(field) + 1 if field in sheet_headers else -1
    if col_idx < 0:
        await message.answer("Field not found.")
        await state.clear()
        return
    try:
        from utils.sheets import get_sheet
        ws = get_sheet(sheet)
        ws.update_cell(row_idx + 1, col_idx, new_value)
        from utils.sheets import invalidate_balance_cache
        invalidate_balance_cache()
    except Exception as e:
        await message.answer(f"Error: {e}")
        await state.clear()
        return
    await state.clear()
    uid = message.from_user.id
    await message.answer(f"✅ <b>{field}</b> updated to: <code>{new_value}</code>", reply_markup=manager_menu_kb(is_superadmin=True), parse_mode="HTML")

@router.message(EditRecordState.enter_photo, F.photo)
async def edit_record_enter_photo(message: Message, state: FSMContext):
    import asyncio
    from datetime import datetime
    data = await state.get_data()
    sheet = data["sheet"]
    row_idx = data["row_idx"]
    field = data["field"]
    file_id = message.photo[-1].file_id
    date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"edit_{field.lower().replace(' ','_')}_{date_str}.jpg"
    await message.answer("⏳ Uploading photo...")
    async def do_upload():
        try:
            from utils.drive_upload import upload_receipt_to_drive
            from utils.sheets import get_sheet
            url = await upload_receipt_to_drive(message.bot, file_id, filename, date_str)
            if url:
                def make_cell(u):
                    return f'=HYPERLINK("{u}";IMAGE("{u}";4;60;60))'
                from utils.sheets import EXPENSE_HEADERS
                ws = get_sheet(sheet)
                sheet_headers = EXPENSE_HEADERS if sheet == "Expenses" else []
                col_idx = sheet_headers.index(field) + 1 if field in sheet_headers else -1
                if col_idx > 0:
                    ws.update_cell(row_idx + 1, col_idx, make_cell(url))
                await message.answer(f"✅ <b>{field}</b> photo updated.", reply_markup=manager_menu_kb(is_superadmin=True), parse_mode="HTML")
            else:
                await message.answer("❌ Upload failed.", reply_markup=manager_menu_kb(is_superadmin=True))
        except Exception as e:
            await message.answer(f"❌ Error: {e}", reply_markup=manager_menu_kb(is_superadmin=True))
    await state.clear()
    asyncio.create_task(do_upload())

@router.message(EditRecordState.enter_photo, F.text == "❌ Cancel")
async def edit_record_photo_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=True))

# ─── Multi-select employee pay ────────────────────────────────

@router.message(F.text == "💸 Pay expense")
async def pay_expense_start_v2(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id): return
    from keyboards.kb import employee_multiselect_kb
    await state.set_state(ManagerState.pay_select_employee)
    await state.update_data(pay_selected=[])
    await message.answer("👤 Select employees (tap to toggle):", reply_markup=employee_multiselect_kb([]))

@router.callback_query(F.data.startswith("empms:"), ManagerState.pay_select_employee)
async def pay_multiselect_employee(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    data = await state.get_data()
    selected = [str(u) for u in data.get("pay_selected", [])]

    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return

    if choice == "confirm":
        if not selected:
            await call.answer("Select at least one employee!", show_alert=True)
            return
        from config import MANAGERS as MGRS
        all_users = {**EMPLOYEES, **MGRS}
        balances = await async_get_all_balances()
        all_data = []
        lines = []
        for uid_str in selected:
            uid = int(uid_str)
            info = all_users.get(uid)
            if not info: continue
            name = info["name"]
            b = balances.get(name, {})
            owed = b.get("effective_spendings", 0)
            held = b.get("held_by_employee", 0)
            group = info.get("group_chat_id")
            all_data.append({"name": name, "owed": owed, "held": held, "group": group})
            lines.append(f"👤 <b>{name}</b>: {format_idr(owed)}")
        await state.update_data(pay_all=True, pay_all_data=all_data)
        await state.set_state(ManagerState.pay_select_type)
        text = "💸 <b>Pay selected employees</b>\n\n" + "\n".join(lines) + "\n\n💳 Payment type:"
        await call.message.answer(text, reply_markup=pay_expense_type_kb(), parse_mode="HTML")
        return

    # Toggle selection
    if choice in selected:
        selected.remove(choice)
    else:
        selected.append(choice)
    await state.update_data(pay_selected=selected)
    from keyboards.kb import employee_multiselect_kb
    await call.message.edit_reply_markup(reply_markup=employee_multiselect_kb(selected))

# ─── GPS vs Odometer report ───────────────────────────────────

class GpsOdoState(StatesGroup):
    select_bike = State()
    select_period = State()


def _gps_odo_period_label(days: int) -> str:
    return f"Last {days} days"


def _format_gps_odo_report(bike_label: str, period_label: str, records: list[dict], show_bike_col: bool) -> str:
    header = f"📊 <b>GPS vs Odometer</b> — {bike_label}\nPeriod: {period_label}\n"
    if not records:
        return header + "\nNo data for this period"
    table_lines = []
    if show_bike_col:
        table_lines.append(f"{'Date':<12}{'Bike':<22}{'Manual':<10}{'GPS':<10}Diff")
    else:
        table_lines.append(f"{'Date':<12}{'Manual':<10}{'GPS':<10}Diff")
    for r in records:
        warn = "⚠️ " if r["diff_pct"] > 5 else "   "
        if show_bike_col:
            bike_short = r["bike"][:20]
            table_lines.append(
                f"{r['date']:<12}{bike_short:<22}{r['manual']} km{'':<4}{r['gps']} km{'':<3}{warn}{r['diff_pct']}%"
            )
        else:
            table_lines.append(
                f"{r['date']:<12}{r['manual']} km{'':<4}{r['gps']} km{'':<3}{warn}{r['diff_pct']}%"
            )
    avg_diff = sum(r["diff_pct"] for r in records) / len(records)
    avg_warn = "⚠️" if avg_diff > 5 else "✅"
    lines = [header]
    lines.append(f"<pre>{chr(10).join(table_lines)}</pre>")
    lines.append(f"\nAvg diff: <b>{avg_diff:.1f}%</b> {avg_warn}")
    return "\n".join(lines)


@router.message(F.text == "📊 GPS vs Odo")
async def gps_odo_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False):
        return
    from keyboards.kb import gps_odo_bike_kb
    await state.set_state(GpsOdoState.select_bike)
    await message.answer(
        "📊 <b>GPS vs Odometer</b>\n\nSelect bike:",
        reply_markup=gps_odo_bike_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("gpsodo_b:"), GpsOdoState.select_bike)
async def gps_odo_select_bike(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "ALL":
        bike_label = "All bikes"
        bike_filter = "ALL"
    else:
        from keyboards.kb import gps_bike_names
        bikes = gps_bike_names()
        try:
            bike_label = bikes[int(choice)]
            bike_filter = bike_label
        except (ValueError, IndexError):
            await call.message.edit_text("Bike not found.")
            return
    await state.update_data(gps_odo_bike=bike_filter, gps_odo_bike_label=bike_label)
    from keyboards.kb import gps_odo_period_kb
    await state.set_state(GpsOdoState.select_period)
    await call.message.edit_text(
        f"📊 <b>{bike_label}</b>\n\nSelect period:",
        reply_markup=gps_odo_period_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("gpsodo_p:"), GpsOdoState.select_period)
async def gps_odo_select_period(call: CallbackQuery, state: FSMContext):
    await call.answer()
    days = int(call.data.split(":", 1)[1])
    data = await state.get_data()
    bike_filter = data.get("gps_odo_bike", "ALL")
    bike_label = data.get("gps_odo_bike_label", "All bikes")
    period_label = _gps_odo_period_label(days)

    import asyncio
    from utils.sheets import get_gps_odo_records
    loop = asyncio.get_event_loop()
    records = await loop.run_in_executor(None, get_gps_odo_records, bike_filter, days)

    show_bike_col = bike_filter == "ALL"
    text = _format_gps_odo_report(bike_label, period_label, records, show_bike_col)
    await state.clear()
    await call.message.edit_text(text, parse_mode="HTML")


@router.callback_query(F.data.startswith("gpsodo_x:"))
async def gps_odo_nav(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    uid = call.from_user.id
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if action == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        await call.message.answer("👔 Manager panel", reply_markup=manager_menu_kb(is_superadmin=is_superadmin))
        return

    if action == "back_menu":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        await call.message.answer("👔 Manager panel", reply_markup=manager_menu_kb(is_superadmin=is_superadmin))
        return

    if action == "back_bike":
        from keyboards.kb import gps_odo_bike_kb
        await state.set_state(GpsOdoState.select_bike)
        await call.message.edit_text(
            "📊 <b>GPS vs Odometer</b>\n\nSelect bike:",
            reply_markup=gps_odo_bike_kb(),
            parse_mode="HTML",
        )

# ─── Manage bikes ─────────────────────────────────────────────

class ManageBikesState(StatesGroup):
    select_action = State()
    select_bike = State()

@router.message(F.text == "📅 Send schedule")
async def send_schedule_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False): return
    from config import CALENDAR_INSTRUCTOR_MAP
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
        buttons.append([InlineKeyboardButton(text=f"☐ {emoji} {name}", callback_data=f"sched_pick:{name}")])
    buttons.append([InlineKeyboardButton(text="✅ Send to all", callback_data="sched_pick:ALL")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="sched_pick:cancel")])
    await state.clear()
    await message.answer("📅 <b>Send schedule</b>\n\nSelect instructors:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("sched_pick:"))
async def send_schedule_pick(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    from config import CALENDAR_INSTRUCTOR_MAP
    data = await state.get_data()
    selected = data.get("sched_selected", [])

    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return

    if choice == "SEND":
        if not selected:
            await call.answer("Select at least one!", show_alert=True)
            return
        names = selected
    elif choice == "ALL":
        names = list(CALENDAR_INSTRUCTOR_MAP.values())
    else:
        if choice in selected:
            selected.remove(choice)
        else:
            selected.append(choice)
        await state.update_data(sched_selected=selected)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
            check = "✅" if name in selected else "☐"
            buttons.append([InlineKeyboardButton(text=f"{check} {emoji} {name}", callback_data=f"sched_pick:{name}")])
        if selected:
            buttons.append([InlineKeyboardButton(text=f"📤 Send to selected ({len(selected)})", callback_data="sched_pick:SEND")])
        buttons.append([InlineKeyboardButton(text="📤 Send to all", callback_data="sched_pick:ALL")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="sched_pick:cancel")])
        await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    from utils.calendar import get_events_for_date, format_schedule_message, parse_event
    from datetime import datetime, timedelta, timezone
    WITA = timezone(timedelta(hours=8))
    tomorrow = datetime.now(WITA) + timedelta(days=1)
    date_label = tomorrow.strftime("%d.%m.%Y")
    events = get_events_for_date(tomorrow)
    from config import LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID, EMPLOYEES
    from utils.lesson_monitor import is_instructor_off

    for name in names:
        username = next((i.get("username","") for i in EMPLOYEES.values() if i.get("name")==name), "")
        tag = f"@{username}" if username else f"<b>{name}</b>"
        instructor_has_lessons = any(name in parse_event(e).get("instructors", []) for e in events)
        if is_instructor_off(events, name):
            text = f"{tag}\n\n🏖 Vacation / Day off tomorrow."
        elif instructor_has_lessons:
            text = f"{tag}\n\n" + format_schedule_message(events, date_label, instructor_filter=name)
        else:
            text = f"{tag}, no lessons tomorrow. Stay on call."
        send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
        if LESSON_GROUP_THREAD_ID:
            send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
        await call.bot.send_message(**send_kwargs)

    await state.clear()
    await call.message.edit_text(f"✅ Schedule sent for: {', '.join(names)}")

@router.message(F.text == "🏍 Manage bikes")
async def manage_bikes_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False): return
    from utils.bikes import get_work_bikes, get_rental_bikes
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    work = get_work_bikes()
    rental = get_rental_bikes()
    text = "🏍 <b>Bikes</b>\n\n🔧 <b>Work:</b>\n" + "\n".join(f"  • {b}" for b in work)
    text += "\n\n🏠 <b>Rental:</b>\n" + "\n".join(f"  • {b}" for b in rental)
    buttons = [
        [InlineKeyboardButton(text="➡️ Work → Rental", callback_data="mbikes:to_rental")],
        [InlineKeyboardButton(text="⬅️ Rental → Work", callback_data="mbikes:to_work")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="mbikes:cancel")],
    ]
    await state.set_state(ManageBikesState.select_action)
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("mbikes:"), ManageBikesState.select_action)
async def manage_bikes_action(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":")[1]
    if action == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    from utils.bikes import get_work_bikes, get_rental_bikes
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    if action == "to_rental":
        bikes = get_work_bikes()
        label = "Work → Rental"
    else:
        bikes = get_rental_bikes()
        label = "Rental → Work"
    await state.update_data(action=action)
    buttons = [[InlineKeyboardButton(text=b, callback_data=f"mbike_pick:{b}")] for b in bikes]
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="mbike_pick:cancel")])
    await state.set_state(ManageBikesState.select_bike)
    await call.message.edit_text(f"🏍 <b>{label}</b>\n\nSelect bike:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("mbike_pick:"), ManageBikesState.select_bike)
async def manage_bikes_pick(call: CallbackQuery, state: FSMContext):
    await call.answer()
    bike = call.data.split(":", 1)[1]
    if bike == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    data = await state.get_data()
    action = data["action"]
    to_category = "rental" if action == "to_rental" else "work"
    from utils.bikes import move_bike
    ok = move_bike(bike, to_category)
    await state.clear()
    if ok:
        await call.message.edit_text(f"✅ <b>{bike}</b> moved to {'Rental' if to_category == 'rental' else 'Work'}.", parse_mode="HTML")
    else:
        await call.message.edit_text(f"❌ Failed to move {bike}.")

# ─── Calendar management ──────────────────────────────────────

class CalendarState(StatesGroup):
    select_action = State()
    select_lesson = State()
    select_instructor = State()
    enter_title = State()
    enter_date = State()
    enter_time = State()
    enter_duration = State()
    select_site = State()
    enter_description = State()
    confirm = State()

@router.message(F.text == "📆 Manage calendar")
async def calendar_manage_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not MANAGERS.get(uid, {}).get("superadmin", False): return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="➕ Add lesson", callback_data="cal_action:add")],
        [InlineKeyboardButton(text="🔄 Reschedule lesson", callback_data="cal_action:reschedule")],
        [InlineKeyboardButton(text="❌ Cancel lesson", callback_data="cal_action:cancel")],
        [InlineKeyboardButton(text="🚫 Close", callback_data="cal_action:close")],
    ]
    await state.set_state(CalendarState.select_action)
    await message.answer("📆 <b>Calendar management</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("cal_action:"), CalendarState.select_action)
async def calendar_action(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "close":
        await state.clear()
        await call.message.edit_text("Closed.")
        return
    await state.update_data(cal_action=action)
    if action == "add":
        await state.set_state(CalendarState.select_instructor)
        from config import CALENDAR_INSTRUCTOR_MAP
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        buttons = []
        for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
            buttons.append([InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"cal_instructor:{name}:{emoji}")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cal_instructor:cancel:")])
        await call.message.edit_text("👤 Select instructor:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    else:
        await _show_lesson_list(call.message, state, action)

async def _show_lesson_list(message, state, action):
    from utils.calendar_manager import get_upcoming_lessons
    from utils.calendar import parse_event
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    lessons = get_upcoming_lessons(days_ahead=14)
    if not lessons:
        await message.edit_text("No upcoming lessons found.")
        return
    buttons = []
    for e in lessons:
        p = parse_event(e)
        label = f"{p['start_time']} {p['summary'][:35]}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"cal_lesson:{e['id'][:40]}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cal_lesson:cancel")])
    action_text = "reschedule" if action == "reschedule" else "cancel"
    await state.set_state(CalendarState.select_lesson)
    await message.edit_text(f"📋 Select lesson to {action_text}:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("cal_instructor:"), CalendarState.select_instructor)
async def calendar_select_instructor(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    name = parts[1]
    emoji = parts[2] if len(parts) > 2 else ""
    if name == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    await state.update_data(cal_instructor=name, cal_instructor_emoji=emoji)
    await state.set_state(CalendarState.enter_title)
    await call.message.edit_text(f"✏️ Enter lesson title for {emoji} {name}:\n\nExample: Roman moto city's")

@router.message(CalendarState.enter_title)
async def calendar_enter_title(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=True))
        return
    data = await state.get_data()
    emoji = data.get("cal_instructor_emoji", "")
    title = f"{emoji} {message.text.strip()}"
    await state.update_data(cal_title=title)
    await message.answer("📅 Select date:", reply_markup=_cal_date_kb())

def _cal_site_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from config import TRAINING_SITES
    buttons = []
    for site in TRAINING_SITES:
        buttons.append([InlineKeyboardButton(text=site, callback_data=f"cal_site:{site}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="cal_site:back"),
                    InlineKeyboardButton(text="❌ Cancel", callback_data="cal_site:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def _cal_date_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    from datetime import datetime, timedelta, timezone
    WITA = timezone(timedelta(hours=8))
    now = datetime.now(WITA)
    buttons = []
    row = []
    for i in range(14):
        d = now + timedelta(days=i)
        label = "Today" if i == 0 else ("Tomorrow" if i == 1 else d.strftime("%d.%m"))
        row.append(InlineKeyboardButton(text=label, callback_data=f"cal_date:{d.strftime('%d.%m.%Y')}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="cal_date:back"), InlineKeyboardButton(text="❌ Cancel", callback_data="cal_date:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def _cal_time_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    row = []
    for h in range(7, 20):
        row.append(InlineKeyboardButton(text=f"{h:02d}:00", callback_data=f"cal_time:{h:02d}:00"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ Custom time", callback_data="cal_time:custom")])
    buttons.append([InlineKeyboardButton(text="⬅️ Back", callback_data="cal_time:back"), InlineKeyboardButton(text="❌ Cancel", callback_data="cal_time:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def _cal_dur_kb():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="60 min", callback_data="cal_dur:60"),
         InlineKeyboardButton(text="90 min", callback_data="cal_dur:90"),
         InlineKeyboardButton(text="120 min", callback_data="cal_dur:120")],
        [InlineKeyboardButton(text="🌅 All day", callback_data="cal_dur:allday"),
         InlineKeyboardButton(text="✏️ Custom", callback_data="cal_dur:custom")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="cal_dur:back"), InlineKeyboardButton(text="❌ Cancel", callback_data="cal_dur:cancel")],
    ])

@router.callback_query(F.data.startswith("cal_date:"))
async def calendar_pick_date(call: CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":", 1)[1]
    if val == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if val == "back":
        data = await state.get_data()
        action = data.get("cal_action")
        if action == "add":
            await state.set_state(CalendarState.enter_title)
            from keyboards.kb import cancel_kb
            await call.message.edit_text("✏️ Enter lesson title:")
        else:
            await _show_lesson_list(call.message, state, action)
        return
    await state.update_data(cal_date=val)
    await call.message.edit_text(f"📅 Date: {val}\n\n🕐 Select time:", reply_markup=_cal_time_kb())

@router.callback_query(F.data.startswith("cal_time:"))
async def calendar_pick_time(call: CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":", 1)[1]
    if val == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if val == "back":
        await call.message.edit_text("📅 Select date:", reply_markup=_cal_date_kb())
        return
    if val == "custom":
        await state.set_state(CalendarState.enter_time)
        from keyboards.kb import cancel_kb
        await call.message.edit_text("✏️ Enter time (HH:MM):")
        await call.message.answer("Enter time:", reply_markup=cancel_kb())
        return
    time_str = val + ":00" if len(val) == 2 else val
    await state.update_data(cal_time=time_str)
    data = await state.get_data()
    await call.message.edit_text(f"📅 {data['cal_date']} {time_str}\n\n⏱ Duration:", reply_markup=_cal_dur_kb())

@router.message(CalendarState.enter_time)
async def calendar_enter_time_custom(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=True))
        return
    try:
        h, m = message.text.strip().split(":")
        int(h); int(m)
        await state.update_data(cal_time=message.text.strip())
        await message.answer("⏱ Duration:", reply_markup=_cal_dur_kb())
    except:
        await message.answer("⚠️ Wrong format. Use HH:MM")

@router.callback_query(F.data.startswith("cal_dur:"))
async def calendar_pick_duration(call: CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":", 1)[1]
    if val == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if val == "back":
        data = await state.get_data()
        await call.message.edit_text(f"📅 {data.get('cal_date','?')}\n\n🕐 Select time:", reply_markup=_cal_time_kb())
        return
    if val == "custom":
        await state.set_state(CalendarState.enter_duration)
        from keyboards.kb import cancel_kb
        await call.message.edit_text("✏️ Enter duration in minutes:")
        await call.message.answer("Enter duration:", reply_markup=cancel_kb())
        return
    await state.update_data(cal_duration=val)
    data = await state.get_data()
    if data.get('cal_action') == 'reschedule':
        await _finalize_reschedule(call.message, state, data)
        return
    await state.set_state(CalendarState.select_site)
    await call.message.edit_text("📍 Select training site:", reply_markup=_cal_site_kb())

@router.message(CalendarState.enter_duration)
async def calendar_enter_duration_custom(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=True))
        return
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter duration in minutes")
        return
    await state.update_data(cal_duration=int(digits))
    data = await state.get_data()
    if data.get('cal_action') == 'reschedule':
        await _finalize_reschedule(message, state, data)
        return
    await state.set_state(CalendarState.enter_description)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    skip_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Skip", callback_data="cal_desc:skip")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cal_desc:cancel")],
    ])
    await message.answer("💬 Description:", reply_markup=skip_kb)

@router.callback_query(F.data.startswith("cal_site:"), CalendarState.select_site)
async def calendar_pick_site(call: CallbackQuery, state: FSMContext):
    await call.answer()
    val = call.data.split(":", 1)[1]
    if val == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    if val == "back":
        data = await state.get_data()
        await call.message.edit_text(f"⏱ Duration:", reply_markup=_cal_dur_kb())
        return
    if val == "Custom":
        await state.set_state(CalendarState.enter_description)
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        skip_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Skip", callback_data="cal_desc:skip")],
            [InlineKeyboardButton(text="⬅️ Back", callback_data="cal_desc:back")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="cal_desc:cancel")],
        ])
        await call.message.edit_text("📍 Enter custom training site:", reply_markup=skip_kb)
        return
    await state.update_data(cal_site=val)
    data = await state.get_data()
    await _show_add_confirm(call.message, state, data)

@router.callback_query(F.data.startswith("cal_desc:"), CalendarState.enter_description)
async def calendar_desc_skip(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if call.data == "cal_desc:cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    await state.update_data(cal_description="")
    data = await state.get_data()
    await _show_add_confirm(call.message, state, data)

async def _show_add_confirm(message, state, data):
    from keyboards.kb import confirm_kb
    await state.set_state(CalendarState.confirm)
    dur = data.get('cal_duration', '?')
    dur_str = "All day" if dur == "allday" else f"{dur} min"
    site = data.get('cal_site', '') or data.get('cal_description', '') or '—'
    await message.answer(
        f"📋 <b>Confirm new lesson:</b>\n\n"
        f"📌 {data.get('cal_title','?')}\n"
        f"📅 {data.get('cal_date','?')} {data.get('cal_time','?')}\n"
        f"⏱ {dur_str}\n"
        f"📍 {site}",
        reply_markup=confirm_kb(), parse_mode="HTML"
    )

async def _finalize_reschedule(message, state, data):
    from utils.calendar_manager import reschedule_lesson
    from datetime import datetime, timedelta, timezone
    WITA = timezone(timedelta(hours=8))
    try:
        d = datetime.strptime(f"{data['cal_date']} {data['cal_time']}", "%d.%m.%Y %H:%M")
        start_dt = d.replace(tzinfo=WITA)
        dur = data.get('cal_duration', 90)
        if dur == 'allday':
            end_dt = start_dt + timedelta(hours=8)
        else:
            end_dt = start_dt + timedelta(minutes=int(dur))
        ok = reschedule_lesson(data['cal_event_full_id'], start_dt, end_dt)
        if ok:
            await message.answer(f"✅ Lesson rescheduled to {data['cal_date']} {data['cal_time']}!", reply_markup=manager_menu_kb(is_superadmin=True))
            from config import LESSON_GROUP_CHAT_ID, EMPLOYEES, CALENDAR_INSTRUCTOR_MAP
            name = data.get('cal_instructor', '')
            username = next((i.get('username','') for i in EMPLOYEES.values() if i.get('name')==name), '')
            tag = f"@{username}" if username else f"<b>{name}</b>"
            old_sum = data.get('cal_old_summary', '')
            text = f"🔄 <b>Lesson rescheduled!</b>\n\n📌 {old_sum}\n📅 {data['cal_date']} {data['cal_time']}\n👤 {tag}"
            await message.bot.send_message(chat_id=LESSON_GROUP_CHAT_ID, text=text, parse_mode="HTML")
        else:
            await message.answer("❌ Failed to reschedule.", reply_markup=manager_menu_kb(is_superadmin=True))
    except Exception as e:
        print(f"_finalize_reschedule error: {e}")
        await message.answer("❌ Error. Check date/time format.", reply_markup=manager_menu_kb(is_superadmin=True))
    await state.clear()

@router.message(CalendarState.enter_description)
async def calendar_enter_description(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=manager_menu_kb(is_superadmin=True))
        return
    desc = "" if message.text in ("⏭ Skip", "⏭ Skip (no receipt)") else message.text.strip()
    await state.update_data(cal_description=desc)
    data = await state.get_data()
    await _show_add_confirm(message, state, data)
    if False:
        await message.answer(
        reply_markup=confirm_kb(), parse_mode="HTML"
    )

@router.message(CalendarState.confirm, F.text == "✅ Confirm")
async def calendar_confirm_add(message: Message, state: FSMContext):
    data = await state.get_data()
    from datetime import datetime, timedelta, timezone
    from utils.calendar_manager import add_lesson
    WITA = timezone(timedelta(hours=8))
    d = datetime.strptime(f"{data['cal_date']} {data['cal_time']}", "%d.%m.%Y %H:%M")
    start_dt = d.replace(tzinfo=WITA)
    dur = data['cal_duration']
    if dur == 'allday':
        end_dt = start_dt + timedelta(hours=8)
    else:
        end_dt = start_dt + timedelta(minutes=int(dur))
    site = data.get('cal_site', '') or data.get('cal_description', '')
    event_id = add_lesson(data['cal_title'], start_dt, end_dt, site)
    if event_id:
        await message.answer("✅ Lesson added to calendar!", reply_markup=manager_menu_kb(is_superadmin=True))
        from config import LESSON_GROUP_CHAT_ID, EMPLOYEES, CALENDAR_INSTRUCTOR_MAP
        name = data.get('cal_instructor', '')
        username = next((i.get('username','') for i in EMPLOYEES.values() if i.get('name')==name), '')
        tag = f"@{username}" if username else f"<b>{name}</b>"
        text = f"➕ <b>New lesson added!</b>\n\n📌 {data['cal_title']}\n📅 {data['cal_date']} {data['cal_time']}\n⏱ {data['cal_duration']} min\n👤 {tag}"
        await message.bot.send_message(chat_id=LESSON_GROUP_CHAT_ID, text=text, parse_mode="HTML")
    else:
        await message.answer("❌ Failed to add lesson.", reply_markup=manager_menu_kb(is_superadmin=True))
    await state.clear()

@router.callback_query(F.data.startswith("cal_lesson:"), CalendarState.select_lesson)
async def calendar_select_lesson(call: CallbackQuery, state: FSMContext):
    await call.answer()
    event_id = call.data.split(":", 1)[1]
    if event_id == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    data = await state.get_data()
    action = data.get('cal_action')
    await state.update_data(cal_event_id=event_id)
    if action == "cancel":
        from utils.calendar_manager import get_upcoming_lessons
        from utils.calendar import parse_event
        lessons = get_upcoming_lessons(14)
        event = next((e for e in lessons if e['id'][:40] == event_id), None)
        if not event:
            await call.message.edit_text("Lesson not found.")
            return
        p = parse_event(event)
        await state.update_data(cal_event_full_id=event['id'])
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await call.message.edit_text(
            f"❌ Cancel lesson?\n\n📌 {p['summary']}\n🕐 {p['start_time']}–{p['end_time']}",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Yes, cancel", callback_data="cal_confirm:cancel")],
                [InlineKeyboardButton(text="🚫 No, go back", callback_data="cal_confirm:back")],
            ])
        )
    else:
        from utils.calendar_manager import get_upcoming_lessons
        from utils.calendar import parse_event
        lessons = get_upcoming_lessons(14)
        event = next((e for e in lessons if e['id'][:40] == event_id), None)
        if not event:
            await call.message.edit_text("Lesson not found.")
            return
        p = parse_event(event)
        await state.update_data(cal_event_full_id=event['id'], cal_old_summary=p['summary'])
        await call.message.edit_text(
            f"🔄 Reschedule: <b>{p['summary']}</b>\n\n📅 Select new date:",
            reply_markup=_cal_date_kb(), parse_mode="HTML"
        )

@router.callback_query(F.data.startswith("cal_confirm:"))
async def calendar_confirm_action(call: CallbackQuery, state: FSMContext):
    await call.answer()
    action = call.data.split(":", 1)[1]
    if action == "back":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        return
    data = await state.get_data()
    event_id = data.get('cal_event_full_id')
    from utils.calendar_manager import cancel_lesson
    ok = cancel_lesson(event_id)
    if ok:
        await call.message.edit_text("✅ Lesson cancelled.")
        from config import LESSON_GROUP_CHAT_ID, EMPLOYEES, CALENDAR_INSTRUCTOR_MAP
        summary = data.get('cal_old_summary', '')
        from config import CALENDAR_INSTRUCTOR_MAP, EMPLOYEES
        tag = ""
        for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
            if emoji in summary:
                username = next((i.get('username','') for i in EMPLOYEES.values() if i.get('name')==name), '')
                tag = f"@{username}" if username else f"<b>{name}</b>"
                break
        tag_str = f"\n👤 {tag}" if tag else ""
        text = f"❌ <b>Lesson cancelled by manager</b>\n\n📌 {summary}{tag_str}"
        await call.bot.send_message(chat_id=LESSON_GROUP_CHAT_ID, text=text, parse_mode="HTML")
    else:
        await call.message.edit_text("❌ Failed to cancel lesson.")
    await state.clear()

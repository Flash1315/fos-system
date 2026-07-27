from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from keyboards.kb import calendar_kb, income_categories_kb, expense_categories_kb, cancel_kb, main_menu

router = Router()


async def _calendar_cancel(call: CallbackQuery, state: FSMContext):
    uid = call.from_user.id
    from config import MANAGERS
    await call.message.delete()
    await state.clear()
    await call.message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS))
    await call.answer()


async def _calendar_back(call: CallbackQuery, state: FSMContext, prefix: str):
    current_state = await state.get_state()
    try:
        await call.message.delete()
    except Exception:
        pass
    if current_state in ("ExpenseForm:date", "FuelForm:date", "IncomeForm:date", "AIExpenseForm:date", "AIFuelForm:date"):
        await call.message.answer("📅 Select date:", reply_markup=cancel_kb())
        await call.message.answer("👇", reply_markup=calendar_kb(prefix=prefix))
    await call.answer()


async def _calendar_day(call: CallbackQuery, state: FSMContext, date_str: str):
    await state.update_data(date=date_str)
    try:
        await call.message.delete()
    except Exception:
        pass
    current_state = await state.get_state()

    if current_state == "ExpenseForm:date":
        from handlers.expenses import ExpenseForm
        await state.set_state(ExpenseForm.category)
        await call.message.answer(
            f"📅 Date: <b>{date_str}</b>\n\n📂 Category:",
            reply_markup=expense_categories_kb(), parse_mode="HTML"
        )
    elif current_state == "FuelForm:date":
        from handlers.fuel import FuelForm
        await state.set_state(FuelForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await call.message.answer(
            f"📅 Date: <b>{date_str}</b>",
            parse_mode="HTML",
        )
        await show_purpose_prompt(call.message, "fuelpur", "Fuel purpose:")
    elif current_state == "IncomeForm:date":
        from handlers.income import IncomeForm
        await state.set_state(IncomeForm.category)
        await call.message.answer(
            f"📅 Date: <b>{date_str}</b>\n\n📂 Category:",
            reply_markup=income_categories_kb(), parse_mode="HTML"
        )
    elif current_state == "AIExpenseForm:date":
        from handlers.expenses import AIExpenseForm, _ai_show_final_confirm
        data = await state.get_data()
        if data.get("ai_return_to") == "confirm":
            await state.update_data(ai_return_to=None)
            await _ai_show_final_confirm(call.message, state)
        else:
            await state.set_state(AIExpenseForm.purpose)
            from utils.purpose_flow import show_purpose_prompt
            await call.message.answer(
                f"📅 Date: <b>{date_str}</b>",
                parse_mode="HTML",
            )
            await show_purpose_prompt(call.message, "aiexppur", "Expense purpose:")
    elif current_state == "AIFuelForm:date":
        from handlers.fuel import AIFuelForm
        await state.set_state(AIFuelForm.purpose)
        from utils.purpose_flow import show_purpose_prompt
        await call.message.answer(
            f"📅 Date: <b>{date_str}</b>",
            parse_mode="HTML",
        )
        await show_purpose_prompt(call.message, "aifuelpur", "Fuel purpose:")
    await call.answer()


async def _calendar_nav(call: CallbackQuery, action: str, year: int, month: int, prefix: str):
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


async def _handle_calendar_callback(call: CallbackQuery, state: FSMContext, prefix: str):
    parts = call.data.split(":")
    action = parts[1]

    if action == "ignore":
        await call.answer()
        return

    if action == "cancel":
        await _calendar_cancel(call, state)
        return

    if action == "back":
        await _calendar_back(call, state, prefix)
        return

    if action == "day":
        date_str = parts[2]
        await _calendar_day(call, state, date_str)
        return

    if action in ("prev", "next"):
        year, month = int(parts[2]), int(parts[3])
        await _calendar_nav(call, action, year, month, prefix)


@router.callback_query(F.data.startswith("cal:"))
async def calendar_handler(call: CallbackQuery, state: FSMContext):
    await _handle_calendar_callback(call, state, "cal")


@router.callback_query(F.data.startswith("aical:"))
async def ai_calendar_handler(call: CallbackQuery, state: FSMContext):
    await _handle_calendar_callback(call, state, "aical")


@router.callback_query(F.data.startswith("aifuelcal:"))
async def ai_fuel_calendar_handler(call: CallbackQuery, state: FSMContext):
    await _handle_calendar_callback(call, state, "aifuelcal")

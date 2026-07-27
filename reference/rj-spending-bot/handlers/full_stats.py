import asyncio

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import MANAGERS
from keyboards.kb import manager_menu_kb
from utils.period_stats import PERIOD_LABELS, get_full_period_stats, format_full_period_report

router = Router()


def is_superadmin(user_id: int) -> bool:
    return MANAGERS.get(user_id, {}).get("superadmin", False)


def period_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Last 7 days", callback_data="fstat:p:7")],
        [InlineKeyboardButton(text="Last 30 days", callback_data="fstat:p:30")],
        [InlineKeyboardButton(text="Last 90 days", callback_data="fstat:p:90")],
        [InlineKeyboardButton(text="All time", callback_data="fstat:p:0")],
        [InlineKeyboardButton(text="« Back", callback_data="fstat:menu")],
    ])


@router.message(F.text == "📈 Full statistics")
async def full_stats_start(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "📈 <b>Full statistics</b>\n\n"
        "Lessons from Calendar + Income/Expenses/Rentals.\n"
        "Select period:",
        reply_markup=period_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "fstat:menu")
async def full_stats_menu(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    await state.clear()
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


@router.callback_query(F.data.startswith("fstat:p:"))
async def full_stats_show(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    try:
        days = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer("Invalid period.", show_alert=True)
        return
    await call.message.edit_text("⏳ Calculating...")
    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, get_full_period_stats, days)
    text = format_full_period_report(stats)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Change period", callback_data="fstat:back")],
        [InlineKeyboardButton(text="« Manager menu", callback_data="fstat:menu")],
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)
    await call.answer()


@router.callback_query(F.data == "fstat:back")
async def full_stats_back(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    await call.message.edit_text(
        "📈 <b>Full statistics</b>\n\nSelect period:",
        reply_markup=period_kb(),
        parse_mode="HTML",
    )
    await call.answer()

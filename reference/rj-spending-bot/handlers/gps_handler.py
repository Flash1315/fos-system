import asyncio
from aiogram import Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timezone, timedelta

from config import MANAGERS, SUPERADMIN_GROUP_CHAT_ID, BIKES
from utils.gps import (
    get_all_device_status, get_device_mileage,
    format_bike_status, cut_engine, restore_engine, is_in_bali
)

router = Router()
WITA = timezone(timedelta(hours=8))


def is_superadmin(user_id: int) -> bool:
    info = MANAGERS.get(user_id, {})
    return info.get("superadmin", False)


# ─── GPS STATUS ──────────────────────────────────────────────────────────────

@router.message(F.text == "📍 GPS Status")
async def gps_status(message: Message):
    if not is_superadmin(message.from_user.id):
        return
    await message.answer("⏳ Fetching GPS data...")
    devices = await get_all_device_status()
    if not devices:
        await message.answer("❌ Could not fetch GPS data.")
        return

    work = [d for d in devices if d["type"] == "work"]
    rental = [d for d in devices if d["type"] == "rental"]

    text = "🏍 <b>GPS Status — Work bikes</b>\n\n"
    for d in work:
        text += format_bike_status(d) + "\n\n"

    text += "─────────────────\n🏍 <b>Rental bikes</b>\n\n"
    for d in rental:
        text += format_bike_status(d) + "\n\n"

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


# ─── MILEAGE TODAY ───────────────────────────────────────────────────────────

@router.message(F.text == "📊 Mileage today")
async def mileage_today(message: Message):
    if not is_superadmin(message.from_user.id):
        return
    await message.answer("⏳ Calculating mileage...")

    now = datetime.now(WITA)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(start.timestamp())
    end_ts = int(now.timestamp())

    devices = await get_all_device_status()
    work = [d for d in devices if d["type"] == "work"]

    lines = [f"📊 <b>Mileage today ({now.strftime('%d.%m.%Y')})</b>\n"]
    total = 0.0
    for d in work:
        km = await get_device_mileage(d["imei"], start_ts, end_ts)
        if km is None:
            lines.append(f"🏍 <b>{d['name']}</b>: —")
        else:
            total += km
            lines.append(f"🏍 <b>{d['name']}</b>: {km:.1f} km")

    lines.append(f"\n📌 Total: <b>{total:.1f} km</b>")
    await message.answer("\n".join(lines), parse_mode="HTML")


# ─── LIVE MAP ────────────────────────────────────────────────────────────────

@router.message(F.text == "🗺 Live map")
async def live_map(message: Message):
    if not is_superadmin(message.from_user.id):
        return
    await message.answer(
        "🗺 <b>Live Map — All bikes</b>\n\n"
        "Updates every 2 seconds:\n"
        "<a href='https://104-248-147-174.nip.io/gps'>🌐 Open Live Map</a>\n\n"
        "🟠 Work bikes | 🔵 Rental bikes",
        parse_mode="HTML",
        disable_web_page_preview=True
    )


# ─── CUT ENGINE ──────────────────────────────────────────────────────────────

class CutEngineStates(StatesGroup):
    select_bike = State()
    confirm = State()


@router.message(F.text == "✂️ Cut engine")
async def cut_engine_start(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return

    devices = await get_all_device_status()
    buttons = []
    for d in devices:
        emoji = "🔴" if d["type"] == "work" else "🔵"
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {d['name']}",
            callback_data=f"cut:{d['imei']}:{d['name']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="cut:cancel")])

    await message.answer(
        "⚠️ <b>Select bike to cut engine</b>\n\n"
        "🔴 Work | 🔵 Rental\n\n"
        "<i>Warning: only use when bike is stationary!</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(CutEngineStates.select_bike)


@router.callback_query(F.data.startswith("cut:"), CutEngineStates.select_bike)
async def cut_engine_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.data == "cut:cancel":
        await callback.message.edit_text("❌ Cancelled.")
        await state.clear()
        return

    _, imei, name = callback.data.split(":", 2)
    await state.update_data(imei=imei, name=name)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✂️ YES, cut engine", callback_data="cut_confirm:yes"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="cut_confirm:no"),
        ]
    ])
    await callback.message.edit_text(
        f"⚠️ <b>CONFIRM ENGINE CUT</b>\n\n"
        f"🏍 <b>{name}</b>\n\n"
        f"Are you sure? Only do this when bike is <b>stationary</b>!",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(CutEngineStates.confirm)


@router.callback_query(F.data.startswith("cut_confirm:"), CutEngineStates.confirm)
async def cut_engine_execute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    imei = data.get("imei")
    name = data.get("name")

    if callback.data == "cut_confirm:no":
        await callback.message.edit_text("❌ Cancelled.")
        await state.clear()
        return

    await callback.message.edit_text(f"⏳ Sending cut engine command to <b>{name}</b>...", parse_mode="HTML")
    success = await cut_engine(imei)

    if success:
        await callback.message.edit_text(
            f"✂️ <b>Engine cut sent!</b>\n\n🏍 {name}\n\n"
            f"Check the bike status in a few seconds.",
            parse_mode="HTML"
        )
        # Notify superadmin group
        from aiogram import Bot
        bot = callback.bot
        user = callback.from_user.first_name
        await bot.send_message(
            SUPERADMIN_GROUP_CHAT_ID,
            f"✂️ <b>Engine cut</b> by <b>{user}</b>\n🏍 {name}",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(f"❌ Failed to send command to <b>{name}</b>.", parse_mode="HTML")

    await state.clear()


# ─── RESTORE ENGINE ──────────────────────────────────────────────────────────

class RestoreEngineStates(StatesGroup):
    select_bike = State()
    confirm = State()


@router.message(F.text == "🔑 Restore engine")
async def restore_engine_start(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return

    devices = await get_all_device_status()
    buttons = []
    for d in devices:
        emoji = "🔴" if d["type"] == "work" else "🔵"
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} {d['name']}",
            callback_data=f"restore:{d['imei']}:{d['name']}"
        )])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="restore:cancel")])

    await message.answer(
        "🔑 <b>Select bike to restore engine</b>\n\n"
        "🔴 Work | 🔵 Rental",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await state.set_state(RestoreEngineStates.select_bike)


@router.callback_query(F.data.startswith("restore:"), RestoreEngineStates.select_bike)
async def restore_engine_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.data == "restore:cancel":
        await callback.message.edit_text("❌ Cancelled.")
        await state.clear()
        return

    _, imei, name = callback.data.split(":", 2)
    await state.update_data(imei=imei, name=name)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔑 YES, restore engine", callback_data="restore_confirm:yes"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="restore_confirm:no"),
        ]
    ])
    await callback.message.edit_text(
        f"🔑 <b>CONFIRM ENGINE RESTORE</b>\n\n"
        f"🏍 <b>{name}</b>\n\n"
        f"Restore engine power?",
        parse_mode="HTML",
        reply_markup=kb
    )
    await state.set_state(RestoreEngineStates.confirm)


@router.callback_query(F.data.startswith("restore_confirm:"), RestoreEngineStates.confirm)
async def restore_engine_execute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    imei = data.get("imei")
    name = data.get("name")

    if callback.data == "restore_confirm:no":
        await callback.message.edit_text("❌ Cancelled.")
        await state.clear()
        return

    await callback.message.edit_text(f"⏳ Sending restore engine command to <b>{name}</b>...", parse_mode="HTML")
    success = await restore_engine(imei)

    if success:
        await callback.message.edit_text(
            f"🔑 <b>Engine restored!</b>\n\n🏍 {name}",
            parse_mode="HTML"
        )
        bot = callback.bot
        user = callback.from_user.first_name
        await bot.send_message(
            SUPERADMIN_GROUP_CHAT_ID,
            f"🔑 <b>Engine restored</b> by <b>{user}</b>\n🏍 {name}",
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(f"❌ Failed to restore engine on <b>{name}</b>.", parse_mode="HTML")

    await state.clear()


# ─── MILEAGE MONTH ───────────────────────────────────────────────────────────


@router.message(F.text == "📅 Mileage month")
async def mileage_month(message: Message):
    if not is_superadmin(message.from_user.id):
        return
    await message.answer("⏳ Calculating monthly mileage...")
    from datetime import datetime, timezone, timedelta
    from utils.sheets import get_sheet
    import re as _re
    WITA = timezone(timedelta(hours=8))
    now = datetime.now(WITA)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(start.timestamp())
    end_ts = int(now.timestamp())
    month_str = now.strftime("%m.%Y")
    devices = await get_all_device_status()
    work = [d for d in devices if d["type"] == "work"]
    try:
        ws = get_sheet("Expenses")
        rows = ws.get_all_values()
        from utils.sheets import EXP_COL_CATEGORY, EXP_COL_MILEAGE
        fuel_rows = [r for r in rows if len(r) > EXP_COL_MILEAGE and r[EXP_COL_CATEGORY] == "Bensin" and month_str in r[0]]
    except:
        fuel_rows = []
    result = ["<b>Monthly Mileage — " + now.strftime("%B %Y") + "</b>", ""]
    gps_total = 0.0
    for d in work:
        gps_km = await get_device_mileage(d["imei"], start_ts, end_ts)
        gps_km = gps_km or 0.0
        gps_total += gps_km
        manual_km = 0
        try:
            from utils.sheets import EXP_COL_MILEAGE, EXP_COL_CATEGORY, EXP_COL_PLACE
            bike_rows = [r for r in fuel_rows if len(r) > EXP_COL_MILEAGE and r[EXP_COL_CATEGORY] == "Bensin" and any(w in r[EXP_COL_PLACE] for w in d["name"].split())]
            odos = []
            for r in bike_rows:
                from utils.sheets import _parse_mileage_km
                km = _parse_mileage_km(r[EXP_COL_MILEAGE])
                if km:
                    odos.append(km)
            if len(odos) >= 2:
                manual_km = max(odos) - min(odos)
        except:
            pass
        result.append("🏍 <b>" + d["name"] + "</b>")
        result.append("   GPS: " + str(round(gps_km, 1)) + " km | Manual: " + (str(manual_km) + " km" if manual_km > 0 else "—"))
    result.append("")
    result.append("GPS Total: <b>" + str(round(gps_total, 1)) + " km</b>")
    await message.answer("\n".join(result), parse_mode="HTML")

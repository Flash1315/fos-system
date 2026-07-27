from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext

from config import MANAGERS
from keyboards.kb import manager_menu_kb
from utils.bikes import get_work_bikes, get_rental_bikes, get_bike_category
from utils.bike_maintenance import format_service_log_lines
from utils.sheets import format_idr, get_bike_statistics

router = Router()

PERIOD_LABELS = {7: "Last 7 days", 30: "Last 30 days", 90: "Last 90 days", 0: "All time"}


def is_superadmin(user_id: int) -> bool:
    return MANAGERS.get(user_id, {}).get("superadmin", False)


def bike_list_kb() -> InlineKeyboardMarkup:
    buttons = []
    work = get_work_bikes()
    rental = get_rental_bikes()
    if work:
        buttons.append([InlineKeyboardButton(text="— Work bikes —", callback_data="bstat:ignore")])
        for b in work:
            buttons.append([InlineKeyboardButton(text=b[:55], callback_data=f"bstat:pick:{b}")])
    if rental:
        buttons.append([InlineKeyboardButton(text="— Rental bikes —", callback_data="bstat:ignore")])
        for b in rental:
            buttons.append([InlineKeyboardButton(text=b[:55], callback_data=f"bstat:pick:{b}")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="bstat:menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def period_kb(bike_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Last 7 days", callback_data="bstat:p:7")],
        [InlineKeyboardButton(text="Last 30 days", callback_data="bstat:p:30")],
        [InlineKeyboardButton(text="Last 90 days", callback_data="bstat:p:90")],
        [InlineKeyboardButton(text="All time", callback_data="bstat:p:0")],
        [InlineKeyboardButton(text="« Change bike", callback_data="bstat:list")],
        [InlineKeyboardButton(text="« Back", callback_data="bstat:menu")],
    ])


def stats_kb(days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Service log", callback_data="bstat:svc")],
        [InlineKeyboardButton(text="📈 Mileage history", callback_data="bstat:hist")],
        [InlineKeyboardButton(text="« Change period", callback_data="bstat:period")],
        [InlineKeyboardButton(text="« Change bike", callback_data="bstat:list")],
        [InlineKeyboardButton(text="« Back", callback_data="bstat:menu")],
    ])


def format_bike_statistics(bike_name: str, days: int, stats: dict) -> str:
    period = PERIOD_LABELS.get(days, f"Last {days} days")
    category = get_bike_category(bike_name)
    cat_label = "Work" if category == "work" else "Rental" if category == "rental" else "Unknown"

    lines = [
        f"📊 <b>Bike statistics</b>",
        f"<b>{bike_name}</b> ({cat_label})",
        f"📅 Period: <b>{period}</b>",
        "",
        "⛽ <b>Fuel</b>",
        f"• Fills: <b>{stats['fuel_count']}</b>",
        f"• Total: <b>{format_idr(stats['fuel_total'])}</b>",
    ]
    if stats["fuel_count"]:
        lines.append(f"• Avg per fill: <b>{format_idr(stats['fuel_avg'])}</b>")
    if stats.get("avg_km_per_fill"):
        lines.append(f"• Avg km between fills: <b>{stats['avg_km_per_fill']} km</b>")

    lines.extend(["", "🔧 <b>Service / Tires</b>", f"• Records: <b>{stats['service_count']}</b>", f"• Total: <b>{format_idr(stats['service_total'])}</b>"])
    for cat, amount in sorted(stats.get("service_breakdown", {}).items()):
        if amount:
            lines.append(f"  — {cat}: {format_idr(amount)}")

    lines.extend(["", "🔢 <b>Mileage</b>", f"• Odometer records: <b>{stats['odometer_records']}</b>"])
    if stats.get("odo_start") is not None and stats.get("odo_end") is not None:
        lines.append(f"• Range: <b>{stats['odo_start']:,} → {stats['odo_end']:,} km</b>".replace(",", "."))
    if stats.get("km_driven") is not None:
        lines.append(f"• Km driven (period): <b>{stats['km_driven']:,} km</b>".replace(",", "."))
    if stats.get("cost_per_km"):
        lines.append(f"• Cost per km (fuel+service): <b>{format_idr(stats['cost_per_km'])}</b>")

    users = stats.get("users") or {}
    if users:
        lines.extend(["", "👤 <b>Used by</b> (fuel/service/rentals):"])
        for name, count in users.items():
            lines.append(f"• {name}: <b>{count}</b> record(s)")

    service_log = stats.get("service_log") or {}
    log_records = service_log.get("records") or []
    if log_records:
        lines.extend(["", "🛠 <b>Service & repair log</b>:"])
        lines.extend(format_service_log_lines(log_records, max_items=8))

    timeline = stats.get("timeline") or []
    if timeline:
        lines.extend(["", "📈 <b>Recent odometer records</b>:"])
        for item in timeline[:8]:
            cat = item.get("category") or "—"
            emp = item.get("employee") or "—"
            delta = item.get("delta")
            delta_str = f" (+{delta} km)" if delta is not None else ""
            lines.append(
                f"• {item.get('date', '—')} {cat} — {item.get('km', '—')} km{delta_str} — <i>{emp}</i>"
            )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


@router.message(F.text == "📊 Bike statistics")
async def bike_stats_start(message: Message, state: FSMContext):
    if not is_superadmin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "📊 <b>Bike statistics</b>\n\nSelect bike:",
        reply_markup=bike_list_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bstat:ignore")
async def bike_stats_ignore(call: CallbackQuery):
    await call.answer()


@router.callback_query(F.data == "bstat:menu")
async def bike_stats_menu(call: CallbackQuery, state: FSMContext):
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


@router.callback_query(F.data == "bstat:list")
async def bike_stats_list(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    await state.clear()
    await call.message.edit_text(
        "📊 <b>Bike statistics</b>\n\nSelect bike:",
        reply_markup=bike_list_kb(),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("bstat:pick:"))
async def bike_stats_pick(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    bike_name = call.data.split(":", 2)[2]
    await state.update_data(bstat_bike=bike_name)
    await call.message.edit_text(
        f"📊 <b>{bike_name}</b>\n\nSelect period:",
        reply_markup=period_kb(bike_name),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "bstat:period")
async def bike_stats_period(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    data = await state.get_data()
    bike_name = data.get("bstat_bike")
    if not bike_name:
        await call.message.edit_text(
            "📊 <b>Bike statistics</b>\n\nSelect bike:",
            reply_markup=bike_list_kb(),
            parse_mode="HTML",
        )
        await call.answer()
        return
    await call.message.edit_text(
        f"📊 <b>{bike_name}</b>\n\nSelect period:",
        reply_markup=period_kb(bike_name),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("bstat:p:"))
async def bike_stats_show(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    try:
        days = int(call.data.split(":")[2])
    except (IndexError, ValueError):
        await call.answer("Invalid period.", show_alert=True)
        return
    data = await state.get_data()
    bike_name = data.get("bstat_bike")
    if not bike_name:
        await call.answer("Select a bike first.", show_alert=True)
        return
    await state.update_data(bstat_days=days)
    await call.message.edit_text("⏳ Calculating...")
    stats = get_bike_statistics(bike_name, days=days)
    text = format_bike_statistics(bike_name, days, stats)
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=stats_kb(days))
    await call.answer()


def format_mileage_history(bike_name: str, days: int, stats: dict) -> str:
    period = PERIOD_LABELS.get(days, f"Last {days} days")
    lines = [
        f"📈 <b>Mileage history</b>",
        f"<b>{bike_name}</b>",
        f"📅 {period}",
        "",
    ]
    intervals = stats.get("intervals") or {}
    fuel = intervals.get("fuel") or []
    if fuel:
        lines.append("⛽ <b>Between refuels:</b>")
        for item in fuel[:15]:
            days_str = f", {item['days']}d" if item.get("days") is not None else ""
            lines.append(
                f"• {item['from_date']} ({item['from_employee']}) → "
                f"{item['to_date']} ({item['to_employee']}): "
                f"<b>+{item['delta_km']} km</b>{days_str}"
            )
    service = intervals.get("service") or []
    if service:
        lines.extend(["", "🔧 <b>Between service / tires:</b>"])
        for item in service[:10]:
            lines.append(
                f"• {item['from_date']} ({item['from_employee']}) → "
                f"{item['to_date']} ({item['to_employee']}): "
                f"<b>+{item['delta_km']} km</b>"
            )
    all_iv = intervals.get("all") or []
    if all_iv and not fuel and not service:
        lines.append("<b>All intervals:</b>")
        for item in all_iv[:15]:
            lines.append(
                f"• {item['from_date']} {item.get('from_cat', '—')} ({item['from_employee']}) → "
                f"{item['to_date']} {item.get('to_cat', '—')} ({item['to_employee']}): "
                f"<b>+{item['delta_km']} km</b>"
            )
    if len(lines) <= 4:
        lines.append("No mileage intervals in this period.")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    return text


@router.callback_query(F.data == "bstat:svc")
async def bike_stats_service_log(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    data = await state.get_data()
    bike_name = data.get("bstat_bike")
    days = data.get("bstat_days", 30)
    if not bike_name:
        await call.answer("Select a bike first.", show_alert=True)
        return
    from utils.bike_maintenance import get_bike_service_log, format_service_log_lines
    log = get_bike_service_log(bike_name, days=days)
    period = PERIOD_LABELS.get(days, f"Last {days} days")
    lines = [f"🛠 <b>Service & repair log</b>", f"<b>{bike_name}</b>", f"📅 {period}", ""]
    lines.extend(format_service_log_lines(log.get("records") or [], max_items=20))
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back to stats", callback_data=f"bstat:p:{days}")],
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "bstat:hist")
async def bike_stats_history(call: CallbackQuery, state: FSMContext):
    if not is_superadmin(call.from_user.id):
        await call.answer()
        return
    data = await state.get_data()
    bike_name = data.get("bstat_bike")
    days = data.get("bstat_days", 30)
    if not bike_name:
        await call.answer("Select a bike first.", show_alert=True)
        return
    stats = get_bike_statistics(bike_name, days=days)
    text = format_mileage_history(bike_name, days, stats)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="« Back to stats", callback_data=f"bstat:p:{days}")],
    ])
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await call.answer()

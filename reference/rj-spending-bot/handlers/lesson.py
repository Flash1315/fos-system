from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import EMPLOYEES, MANAGERS, LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID
from keyboards.kb import main_menu
from datetime import datetime, timedelta
from utils.calendar import get_events_for_date, format_schedule_message
import asyncio

router = Router()

def is_authorized(uid): return uid in EMPLOYEES or uid in MANAGERS
def get_name(uid):
    e = EMPLOYEES.get(uid)
    return e["name"] if e else MANAGERS.get(uid, {}).get("name", "Unknown")

class LessonState(StatesGroup):
    select_duration = State()
    select_reminders = State()
    custom_duration = State()

DURATIONS = [
    ("1h", 60),
    ("1.5h", 90),
    ("2h", 120),
]

REMINDER_OPTIONS = [-20, -15, -10, -5, 5, 10, 15, 20]

active_lessons = {}  # uid -> {end_time, reminders, task}

@router.message(F.text == "⏰ Alarm")
async def lesson_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_authorized(uid): return
    if uid in active_lessons:
        lesson = active_lessons[uid]
        remaining = int((lesson["end_time"] - datetime.now()).total_seconds() / 60)
        await message.answer(
            f"⏳ Lesson already running\n"
            f"⏱ {remaining} min remaining\n\n"
            f"Stop it?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="⏹ Stop lesson", callback_data="lesson_stop")],
                [InlineKeyboardButton(text="❌ Cancel", callback_data="lesson_cancel")],
            ])
        )
        return
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = [
        [InlineKeyboardButton(text="1h", callback_data="lesson_dur:60")],
        [InlineKeyboardButton(text="1.5h", callback_data="lesson_dur:90")],
        [InlineKeyboardButton(text="2h", callback_data="lesson_dur:120")],
        [InlineKeyboardButton(text="✏️ Custom", callback_data="lesson_dur:custom")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="lesson_cancel")],
    ]
    await state.set_state(LessonState.select_duration)
    await message.answer("🏫 <b>New lesson</b>\n\nSelect duration:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

@router.callback_query(F.data.startswith("lesson_dur:"), LessonState.select_duration)
async def lesson_select_duration(call: CallbackQuery, state: FSMContext):
    await call.answer()
    choice = call.data.split(":")[1]
    if choice == "custom":
        await state.set_state(LessonState.custom_duration)
        await call.message.answer("✏️ Enter duration in minutes (e.g. 75):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Cancel", callback_data="lesson_cancel")]]))
        return
    duration = int(choice)
    await state.update_data(duration=duration)
    await show_reminder_selection(call.message, state, duration)

@router.message(LessonState.custom_duration)
async def lesson_custom_duration(message: Message, state: FSMContext):
    digits = ''.join(c for c in message.text if c.isdigit())
    if not digits:
        await message.answer("⚠️ Enter a number in minutes")
        return
    duration = int(digits)
    await state.update_data(duration=duration)
    await show_reminder_selection(message, state, duration)

async def show_reminder_selection(message, state, duration):
    await state.update_data(selected_reminders=[])
    buttons = []
    for offset in REMINDER_OPTIONS:
        if offset < 0:
            label = f"−{abs(offset)} min before end"
        else:
            label = f"+{offset} min after end"
        buttons.append([InlineKeyboardButton(text=f"☐ {label}", callback_data=f"lesson_rem:{offset}")])
    buttons.append([InlineKeyboardButton(text="▶️ Start lesson", callback_data=f"lesson_go:{duration}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="lesson_cancel")])
    await state.set_state(LessonState.select_reminders)
    await message.answer(
        f"🏫 Duration: <b>{duration} min</b>\n\nSelect reminders (tap to toggle):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("lesson_rem:"), LessonState.select_reminders)
async def lesson_toggle_reminder(call: CallbackQuery, state: FSMContext):
    await call.answer()
    offset = int(call.data.split(":")[1])
    data = await state.get_data()
    selected = data.get("selected_reminders", [])
    if offset in selected:
        selected.remove(offset)
    else:
        selected.append(offset)
    await state.update_data(selected_reminders=selected)
    duration = data["duration"]
    buttons = []
    for o in REMINDER_OPTIONS:
        if o < 0:
            label = f"−{abs(o)} min before end"
        else:
            label = f"+{o} min after end"
        checked = "☑" if o in selected else "☐"
        buttons.append([InlineKeyboardButton(text=f"{checked} {label}", callback_data=f"lesson_rem:{o}")])
    buttons.append([InlineKeyboardButton(text="▶️ Start lesson", callback_data=f"lesson_go:{duration}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="lesson_cancel")])
    await call.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("lesson_go"))
async def lesson_start_timer(call: CallbackQuery, state: FSMContext):
    await call.answer()
    parts = call.data.split(":")
    duration = int(parts[1]) if len(parts) > 1 else 60
    data = await state.get_data()
    selected = data.get("selected_reminders", [])
    uid = call.from_user.id
    name = get_name(uid)
    end_time = datetime.now() + timedelta(minutes=duration)
    await state.clear()
    # Get next lesson from calendar for full info
    try:
        from utils.calendar import get_current_or_upcoming_event, parse_event
        cal_events = get_current_or_upcoming_event()
        cal_info = ""
        if cal_events:
            p = parse_event(cal_events[0])
            cal_info += f"\n📌 {p['summary']}"
            if p['lesson_number']:
                cal_info += f" — lesson {p['lesson_number']}"
            if p['pickup_info']:
                cal_info += f"\n🚗 {p['pickup_info']}"
            if p['training_site']:
                cal_info += f"\n📍 {p['training_site']}"
            if p['bike']:
                cal_info += f"\n🏍 {p['bike']}"
    except Exception as e:
        print(f"Calendar error in lesson: {e}")
        cal_info = ""

    notify_text = (
        f"🏫 <b>Lesson started</b>\n"
        f"👤 {name}{cal_info}\n"
        f"⏱ Duration: {duration} min\n"
        f"🕐 Ends at: {end_time.strftime('%H:%M')}"
    )
    send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": notify_text, "parse_mode": "HTML"}
    if LESSON_GROUP_THREAD_ID:
        send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
    await call.bot.send_message(**send_kwargs)
    await call.message.answer(f"✅ Lesson started! Ends at <b>{end_time.strftime('%H:%M')}</b>", parse_mode="HTML", reply_markup=main_menu(is_manager=uid in MANAGERS))
    task = asyncio.create_task(lesson_timer(call.bot, uid, name, end_time, selected, duration))
    active_lessons[uid] = {"end_time": end_time, "reminders": selected, "task": task}

async def lesson_timer(bot, uid, name, end_time, reminders, duration):
    try:
        for offset in sorted(reminders):
            remind_time = end_time + timedelta(minutes=offset)
            wait = (remind_time - datetime.now()).total_seconds()
            if wait > 0:
                await asyncio.sleep(wait)
                if offset < 0:
                    text = f"⏰ <b>{name}</b> — {abs(offset)} min until lesson ends!"
                elif offset == 0:
                    text = f"🔔 <b>{name}</b> — Lesson time is up!"
                else:
                    text = f"⚠️ <b>{name}</b> — Lesson ended {offset} min ago!"
                kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
                if LESSON_GROUP_THREAD_ID:
                    kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
                await bot.send_message(**kwargs)
        # Final notification at end
        wait_end = (end_time - datetime.now()).total_seconds()
        if wait_end > 0:
            await asyncio.sleep(wait_end)
        await bot.send_message(
            chat_id=LESSON_GROUP_CHAT_ID,
            message_thread_id=LESSON_GROUP_THREAD_ID,
            text=f"🔔 <b>{name}</b> — Lesson finished! ({duration} min)",
            parse_mode="HTML"
        )
    finally:
        active_lessons.pop(uid, None)

@router.callback_query(F.data == "lesson_stop")
async def lesson_stop(call: CallbackQuery):
    await call.answer()
    uid = call.from_user.id
    if uid in active_lessons:
        active_lessons[uid]["task"].cancel()
        active_lessons.pop(uid, None)
        name = get_name(uid)
        stop_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": f"⏹ <b>{name}</b> — Lesson stopped early.", "parse_mode": "HTML"}
        if LESSON_GROUP_THREAD_ID:
            stop_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
        await call.bot.send_message(**stop_kwargs)
    await call.message.edit_text("⏹ Lesson stopped.")

@router.callback_query(F.data == "lesson_cancel")
async def lesson_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.edit_text("Cancelled.")


@router.message(F.text == "📅 Next lesson")
async def next_lesson(message, state):
    from aiogram.fsm.context import FSMContext
    uid = message.from_user.id
    if not is_authorized(uid): return
    from utils.calendar import get_current_or_upcoming_event, parse_event
    from config import CALENDAR_INSTRUCTOR_MAP, EMPLOYEES
    events = get_current_or_upcoming_event()
    if not events:
        await message.answer("📅 No upcoming lessons found.")
        return
    name = get_name(uid)
    p = parse_event(events[0])
    if uid in EMPLOYEES and name in CALENDAR_INSTRUCTOR_MAP.values():
        if p["instructors"] and name not in p["instructors"]:
            await message.answer("📅 No upcoming lessons assigned to you.")
            return
    text = f"📅 <b>Next lesson</b>\n\n🕐 {p['start_time']}–{p['end_time']} ({p['duration_min']} min)\n📌 {p['summary']}"
    if p["lesson_number"]: text += f" — lesson {p['lesson_number']}"
    text += "\n"
    if p["pickup_info"]: text += f"🚗 {p['pickup_info']}\n"
    if p["training_site"]: text += f"📍 {p['training_site']}\n"
    if p["bike"]: text += f"🏍 {p['bike']}\n"
    await message.answer(text, parse_mode="HTML")

@router.message(F.text == "🗓 My schedule")
async def my_schedule(message: Message):
    from config import EMPLOYEES, MANAGERS, CALENDAR_INSTRUCTOR_MAP
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    uid = message.from_user.id
    is_superadmin = MANAGERS.get(uid, {}).get("superadmin", False)

    if is_superadmin:
        buttons = []
        for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
            buttons.append([InlineKeyboardButton(text=f"{emoji} {name}", callback_data=f"view_sched:{name}")])
        buttons.append([InlineKeyboardButton(text="👥 All", callback_data="view_sched:ALL")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="view_sched:cancel")])
        await message.answer("🗓 View schedule for:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        return

    name = EMPLOYEES.get(uid, {}).get("name", "")
    from datetime import datetime, timedelta, timezone
    WITA = timezone(timedelta(hours=8))
    tomorrow = datetime.now(WITA) + timedelta(days=1)
    date_label = tomorrow.strftime("%d.%m.%Y")
    events = get_events_for_date(tomorrow)
    text = format_schedule_message(events, date_label, instructor_filter=name if name else None)
    await message.answer(text, parse_mode="HTML")

@router.callback_query(F.data.startswith("view_sched:"))
async def view_schedule_pick(call: CallbackQuery):
    await call.answer()
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await call.message.edit_text("Cancelled.")
        return
    from config import CALENDAR_INSTRUCTOR_MAP
    from datetime import datetime, timedelta, timezone
    WITA = timezone(timedelta(hours=8))
    tomorrow = datetime.now(WITA) + timedelta(days=1)
    date_label = tomorrow.strftime("%d.%m.%Y")
    events = get_events_for_date(tomorrow)
    if choice == "ALL":
        text = format_schedule_message(events, date_label)
    else:
        text = format_schedule_message(events, date_label, instructor_filter=choice)
    await call.message.edit_text(text, parse_mode="HTML")

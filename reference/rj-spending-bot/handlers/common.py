from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import CommandStart
from config import EMPLOYEES, MANAGERS
from keyboards.kb import main_menu

router = Router()

def get_employee(user_id: int):
    return EMPLOYEES.get(user_id)

def is_manager(user_id: int) -> bool:
    return user_id in MANAGERS

def is_authorized(user_id: int) -> bool:
    return user_id in EMPLOYEES or user_id in MANAGERS

def get_name(user_id: int) -> str:
    emp = EMPLOYEES.get(user_id)
    if emp:
        return emp["name"]
    if user_id in MANAGERS:
        return MANAGERS[user_id]["name"]
    return "Unknown"


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if message.chat.type != "private":
        return
    if not is_authorized(uid):
        await message.answer(
            f"⛔️ No access.\nYour Telegram ID: <code>{uid}</code>\nSend it to the administrator.",
            parse_mode="HTML"
        )
        return
    name = get_name(uid)
    await message.answer(
        f"👋 Hi, <b>{name}</b>! Choose an action:",
        reply_markup=main_menu(is_manager=is_manager(uid), user_id=uid),
        parse_mode="HTML"
    )


@router.message(F.text == "❌ Cancel")
async def cancel_handler(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("Cancelled.", reply_markup=main_menu(is_manager=is_manager(uid), user_id=uid))


@router.message(F.text == "« Main menu")
async def main_menu_handler(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("Main menu:", reply_markup=main_menu(is_manager=is_manager(uid), user_id=uid))

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def manager_group_select_kb():
    from config import EMPLOYEES
    buttons = []
    for uid, info in EMPLOYEES.items():
        buttons.append([InlineKeyboardButton(
            text=info["name"],
            callback_data=f"mgr_group:{uid}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def manager_name_select_kb(employee_uid):
    from config import EMPLOYEES
    emp = EMPLOYEES.get(employee_uid, {})
    emp_name = emp.get("name", "Employee")
    buttons = [
        [InlineKeyboardButton(text="Manager (me)", callback_data=f"mgr_name:manager:{employee_uid}")],
        [InlineKeyboardButton(text=emp_name, callback_data=f"mgr_name:{employee_uid}:{employee_uid}")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)



# ─── SOS ─────────────────────────────────────────────────────────────────────

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

@router.message(F.text == "🆘 SOS")
async def sos_request(message: Message):
    from config import EMPLOYEES, MANAGERS, SUPERADMIN_GROUP_CHAT_ID, LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID
    user_id = message.from_user.id
    if user_id in EMPLOYEES:
        name = EMPLOYEES[user_id]["name"]
    elif user_id in MANAGERS:
        name = MANAGERS[user_id]["name"]
    else:
        name = message.from_user.first_name or "Unknown"

    from datetime import datetime, timezone, timedelta
    WITA = timezone(timedelta(hours=8))
    time_str = datetime.now(WITA).strftime("%H:%M")

    alert_text = (
        "🆘 <b>SOS ALERT!</b>\n\n"
        "👤 <b>" + name + "</b>\n"
        "🕐 " + time_str + "\n\n"
        "📞 Call immediately!"
    )
    # Tag all in superadmin group
    from config import MANAGERS
    mentions = " ".join(["<a href='tg://user?id=" + str(uid) + "'>" + info["name"] + "</a>" for uid, info in MANAGERS.items()])
    alert_text += "\n" + mentions

    # Send immediately to both groups
    await message.bot.send_message(
        chat_id=SUPERADMIN_GROUP_CHAT_ID,
        text=alert_text,
        parse_mode="HTML"
    )
    send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": alert_text, "parse_mode": "HTML"}
    if LESSON_GROUP_THREAD_ID:
        send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
    await message.bot.send_message(**send_kwargs)

    # Ask for location or cancel
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Send my location", request_location=True)],
            [KeyboardButton(text="✅ All good — Cancel SOS")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer(
        "✅ <b>SOS sent!</b>\n\nShare your location if possible, or cancel if false alarm:",
        parse_mode="HTML",
        reply_markup=kb
    )


@router.message(F.location)
async def sos_location(message: Message):
    from config import EMPLOYEES, MANAGERS, SUPERADMIN_GROUP_CHAT_ID, LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID
    from keyboards.kb import main_menu

    user_id = message.from_user.id
    lat = message.location.latitude
    lng = message.location.longitude
    maps_link = f"https://maps.google.com/?q={lat},{lng}"

    # Get name
    name = None
    is_mgr = False
    if user_id in EMPLOYEES:
        name = EMPLOYEES[user_id]["name"]
    elif user_id in MANAGERS:
        name = MANAGERS[user_id]["name"]
        is_mgr = True
    else:
        name = message.from_user.first_name or "Unknown"

    text = (
        f"🆘 <b>SOS ALERT!</b>\n\n"
        f"👤 <b>{name}</b>\n"
        f"📍 <a href='{maps_link}'>Open location</a>\n"
        "🕐 " + message.date.astimezone(__import__('datetime').timezone(__import__('datetime').timedelta(hours=8))).strftime('%H:%M')
    )

    # Send to superadmin group
    await message.bot.send_location(
        chat_id=SUPERADMIN_GROUP_CHAT_ID,
        latitude=lat, longitude=lng
    )
    await message.bot.send_message(
        chat_id=SUPERADMIN_GROUP_CHAT_ID,
        text=text,
        parse_mode="HTML"
    )

    # Send to forum group
    send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if LESSON_GROUP_THREAD_ID:
        send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
    await message.bot.send_message(**send_kwargs)
    await message.bot.send_location(
        chat_id=LESSON_GROUP_CHAT_ID,
        latitude=lat, longitude=lng,
        **{"message_thread_id": LESSON_GROUP_THREAD_ID} if LESSON_GROUP_THREAD_ID else {}
    )

    # Confirm to user
    await message.answer(
        "✅ SOS sent! Help is on the way.",
        reply_markup=main_menu(is_manager=is_mgr)
    )


@router.message(F.text == "✅ All good — Cancel SOS")
async def sos_cancel(message: Message):
    from config import EMPLOYEES, MANAGERS, SUPERADMIN_GROUP_CHAT_ID, LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID
    from keyboards.kb import main_menu
    from datetime import datetime, timezone, timedelta
    WITA = timezone(timedelta(hours=8))
    time_str = datetime.now(WITA).strftime("%H:%M")
    user_id = message.from_user.id
    if user_id in EMPLOYEES:
        name = EMPLOYEES[user_id]["name"]
        is_mgr = False
    elif user_id in MANAGERS:
        name = MANAGERS[user_id]["name"]
        is_mgr = True
    else:
        name = message.from_user.first_name or "Unknown"
        is_mgr = False
    cancel_text = "✅ <b>SOS Cancelled</b>\n\n👤 <b>" + name + "</b>\n🕐 " + time_str + "\nEverything is OK."
    await message.bot.send_message(chat_id=SUPERADMIN_GROUP_CHAT_ID, text=cancel_text, parse_mode="HTML")
    send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": cancel_text, "parse_mode": "HTML"}
    if LESSON_GROUP_THREAD_ID:
        send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
    await message.bot.send_message(**send_kwargs)
    await message.answer("✅ Cancellation sent. Stay safe!", reply_markup=main_menu(is_manager=is_mgr))

@router.callback_query(F.data.startswith("lesson_ack:"))
async def lesson_acknowledged(call: CallbackQuery):
    event_id = call.data.split(":", 1)[1]
    uid = call.from_user.id
    from config import EMPLOYEES, MANAGERS
    from utils.lesson_monitor import load_alerts, acknowledge_alert, _get_instructors_from_summary

    user_name = EMPLOYEES.get(uid, {}).get("name") or MANAGERS.get(uid, {}).get("name")
    if uid not in MANAGERS:
        alert_data = load_alerts().get(event_id, {})
        event = alert_data.get("event", {})
        instructors = _get_instructors_from_summary(event.get("summary", ""))
        if not user_name or user_name not in instructors:
            await call.answer("Only assigned instructor or manager can acknowledge.", show_alert=True)
            return

    await call.answer("✅ Acknowledged!")
    acknowledge_alert(event_id)
    name = user_name or call.from_user.first_name
    try:
        await call.message.edit_text(
            call.message.text + f"\n\n✅ Acknowledged by {name}",
            parse_mode="HTML"
        )
    except:
        pass

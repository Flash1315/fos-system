import io
import re
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import EMPLOYEES, MANAGERS, MANAGER_GROUP_CHAT_ID, LESSON_GROUP_CHAT_ID
from handlers.common import is_authorized
from handlers.rental import RENTAL_THREAD_ID
from keyboards.kb import main_menu, pause_back_cancel_kb
from utils.rental_progress import save_progress, clear_progress, load_progress
from utils.sheets import (
    get_all_booked_rentals, get_rental_by_id, update_rental_fields, append_checklist, append_income,
    get_last_bike_checklist, get_last_bike_video_link, format_idr, now_date, now_time,
    CHK_COL_DATE, CHK_COL_ODOMETER, CHK_COL_FUEL_BAR, CHK_COL_PHOTO,
)
from utils.gemini import read_odometer_photo
from utils.drive_upload import upload_receipt_to_drive, upload_telegram_file_to_drive

router = Router()

CHECKLIST_STEPS = [
    ("phone_holder", "Phone holder"),
    ("phone_charger", "Phone charger"),
    ("first_aid", "First aid kit"),
    ("bike_papers", "Bike papers"),
    ("adjuster", "Adjuster"),
]


class DeliveryForm(StatesGroup):
    pick = State()
    review = State()
    odometer_photo = State()
    odometer_confirm = State()
    odometer_manual = State()
    video = State()
    checklist = State()
    helmets = State()
    helmets_custom = State()
    payment = State()
    payment_confirm = State()
    payment_amount = State()
    insurance = State()
    insurance_cost = State()
    confirm = State()


def employee_name(uid: int) -> str:
    if uid in EMPLOYEES:
        return EMPLOYEES[uid]["name"]
    if uid in MANAGERS:
        return MANAGERS[uid]["name"]
    return "Unknown"


def nav_kb(extra_rows=None) -> ReplyKeyboardMarkup:
    rows = list(extra_rows or [])
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="⏸ Pause")])
    rows.append([KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def yes_no_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="Yes"), KeyboardButton(text="No")]])


def confirm_change_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="✅ Confirm"), KeyboardButton(text="✏️ Change")]])


def payment_method_kb() -> ReplyKeyboardMarkup:
    return nav_kb([
        [KeyboardButton(text="Cash"), KeyboardButton(text="Transfer")],
        [KeyboardButton(text="Already paid")],
    ])


def helmets_kb() -> ReplyKeyboardMarkup:
    return nav_kb([
        [KeyboardButton(text="0"), KeyboardButton(text="1"), KeyboardButton(text="2")],
        [KeyboardButton(text="Other")],
    ])


def insurance_kb() -> ReplyKeyboardMarkup:
    return nav_kb([
        [KeyboardButton(text="No insurance"), KeyboardButton(text="With insurance")],
    ])


def delivery_confirm_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="✅ Confirm delivery")]])


async def notify_rental_channels(bot, text: str) -> None:
    targets = [
        (MANAGER_GROUP_CHAT_ID, None),
        (LESSON_GROUP_CHAT_ID, RENTAL_THREAD_ID),
    ]
    for chat_id, thread_id in targets:
        try:
            kwargs = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            await bot.send_message(**kwargs)
        except Exception as e:
            print(f"delivery notify error ({chat_id}): {e}")


def default_delivery_data(rental: dict) -> dict:
    return {
        "rental_id": rental.get("rental_id", ""),
        "rental": rental,
        "odometer": "",
        "fuel_bar": "",
        "odometer_photo_id": "",
        "odometer_photo_url": "",
        "video_file_id": "",
        "video_url": "",
        "checklist": {},
        "checklist_step": 0,
        "helmets": str(rental.get("helmets") or "0"),
        "payment_method": "",
        "rental_price": str(rental.get("rental_price") or "0"),
        "insurance": rental.get("insurance") or "No insurance",
        "insurance_cost": str(rental.get("insurance_cost") or "0"),
    }


def format_booking_card(rental: dict, prev_video: str = "", prev_chk=None) -> str:
    bike = rental.get("bike", "—")
    lines = [
        f"🏍 <b>Delivery</b> <code>{rental.get('rental_id', '—')}</code>\n",
        f"👤 {rental.get('client_name', '—')}",
        f"🏍 {bike}",
        f"📅 {rental.get('delivery_date', '—')} {rental.get('delivery_time', '')}",
        f"📆 Until {rental.get('return_date', '—')} ({rental.get('duration_days', '—')} days)",
        f"📍 {rental.get('location', '—')}",
        f"💵 {format_idr(int(rental.get('rental_price') or 0))}",
        f"🪖 Helmets: {rental.get('helmets', '—')}",
        f"🛡 {rental.get('insurance', '—')}",
        f"👨‍🏫 Instructor: {rental.get('instructor', '—')}",
    ]
    if prev_video:
        lines.append(f"\n🎬 Previous video: {prev_video}")
    if prev_chk and len(prev_chk) > CHK_COL_ODOMETER:
        odo = prev_chk[CHK_COL_ODOMETER] if len(prev_chk) > CHK_COL_ODOMETER else "—"
        fuel = prev_chk[CHK_COL_FUEL_BAR] if len(prev_chk) > CHK_COL_FUEL_BAR else "—"
        photo = prev_chk[CHK_COL_PHOTO] if len(prev_chk) > CHK_COL_PHOTO else ""
        lines.append(f"📋 Last checklist odo: {odo} | fuel: {fuel}")
        if photo and str(photo).startswith("http"):
            lines.append(f"📎 Last photo: {photo}")
    return "\n".join(lines)


def format_delivery_summary(data: dict) -> str:
    rental = data.get("rental") or {}
    chk = data.get("checklist") or {}
    chk_lines = ", ".join(f"{label}: {chk.get(key, '—')}" for key, label in CHECKLIST_STEPS)
    ins = data.get("insurance", "—")
    if ins == "With insurance":
        ins += f" ({format_idr(int(data.get('insurance_cost') or 0))})"
    return (
        f"📋 <b>Confirm delivery</b> <code>{data.get('rental_id', '—')}</code>\n\n"
        f"👤 {rental.get('client_name', '—')} | 🏍 {rental.get('bike', '—')}\n"
        f"🔢 Odometer: {data.get('odometer', '—')} km | Fuel: {data.get('fuel_bar', '—')} bar\n"
        f"🪖 Helmets: {data.get('helmets', '—')}\n"
        f"💳 Payment: {data.get('payment_method', '—')} — {format_idr(int(data.get('rental_price') or 0))}\n"
        f"🛡 Insurance: {ins}\n"
        f"✅ Checklist: {chk_lines or '—'}\n"
        f"🎬 Video: {'✅' if data.get('video_url') or data.get('video_file_id') else '—'}"
    )


async def cancel_delivery(message: Message, state: FSMContext):
    uid = message.from_user.id
    clear_progress(uid)
    await state.clear()
    is_manager = uid in MANAGERS
    await message.answer("Cancelled.", reply_markup=main_menu(is_manager=is_manager, user_id=uid))


async def show_booked_pick(message: Message, state: FSMContext):
    bookings = get_all_booked_rentals()
    bookings.sort(key=lambda b: (b.get("delivery_date") or "", b.get("delivery_time") or ""))
    uid = message.from_user.id
    if not bookings:
        await state.clear()
        await message.answer(
            "📭 No booked deliveries.",
            reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
        )
        return
    buttons = []
    for b in bookings[:20]:
        rid = b.get("rental_id", "?")
        label = f"{rid} | {b.get('delivery_date', '?')} | {b.get('client_name', '?')} | {b.get('bike', '?')}"
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"delpick:{rid}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="delpick:cancel")])
    await state.set_state(DeliveryForm.pick)
    await message.answer(
        "🏍 <b>Booked deliveries</b>\n\nSelect booking:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


async def restore_delivery_state(message: Message, state: FSMContext, state_key: str, data: dict):
    await state.update_data(**data)
    rental = data.get("rental") or {}
    if state_key == "pick":
        await show_booked_pick(message, state)
        return
    if state_key == "review":
        bike = rental.get("bike", "")
        prev_video = get_last_bike_video_link(bike)
        prev_chk = get_last_bike_checklist(bike)
        await state.set_state(DeliveryForm.review)
        await message.answer(
            format_booking_card(rental, prev_video, prev_chk),
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "odometer_photo":
        await state.set_state(DeliveryForm.odometer_photo)
        await message.answer(
            "📸 Send ONE photo of odometer + fuel level.\n"
            "<i>Total mileage (main number), not daily/trip.</i>",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if state_key == "odometer_confirm":
        await state.set_state(DeliveryForm.odometer_confirm)
        await message.answer(
            f"🔢 Odometer: <b>{data.get('odometer') or '—'}</b> km\n"
            f"⛽ Fuel: <b>{data.get('fuel_bar') or '—'}</b> bar",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "odometer_manual":
        await state.set_state(DeliveryForm.odometer_manual)
        await message.answer(
            "Enter odometer km and fuel bar (e.g. <code>12345 3</code>):",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if state_key == "video":
        await state.set_state(DeliveryForm.video)
        await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())
        return
    if state_key == "checklist":
        step = int(data.get("checklist_step") or 0)
        step = min(step, len(CHECKLIST_STEPS) - 1)
        await state.set_state(DeliveryForm.checklist)
        _, label = CHECKLIST_STEPS[step]
        await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())
        return
    if state_key == "helmets":
        await state.set_state(DeliveryForm.helmets)
        await message.answer(
            f"🪖 Helmets booked: <b>{data.get('helmets', '0')}</b>\nConfirm or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "helmets_custom":
        await state.set_state(DeliveryForm.helmets_custom)
        await message.answer("🪖 Enter helmets count:", reply_markup=helmets_kb())
        return
    if state_key == "payment":
        await state.set_state(DeliveryForm.payment)
        await message.answer(
            f"💳 Payment — {format_idr(int(data.get('rental_price') or 0))}\nSelect method:",
            reply_markup=payment_method_kb(),
        )
        return
    if state_key in ("payment_confirm", "payment_amount"):
        await state.set_state(DeliveryForm.payment_confirm)
        await message.answer(
            f"💳 <b>{data.get('payment_method', '—')}</b> — {format_idr(int(data.get('rental_price') or 0))}\n"
            "Confirm price or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "insurance":
        ins = data.get("insurance") or "No insurance"
        extra = ""
        if ins == "With insurance":
            extra = f" ({format_idr(int(data.get('insurance_cost') or 0))})"
        await state.set_state(DeliveryForm.insurance)
        await message.answer(
            f"🛡 Insurance: <b>{ins}{extra}</b>\nConfirm or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "insurance_cost":
        await state.set_state(DeliveryForm.insurance_cost)
        await message.answer("🛡 Insurance:", reply_markup=insurance_kb())
        return
    if state_key == "confirm":
        await state.set_state(DeliveryForm.confirm)
        await message.answer(format_delivery_summary(data), parse_mode="HTML", reply_markup=delivery_confirm_kb())
        return
    await show_booked_pick(message, state)


@router.message(F.text == "🏍 Deliver bike")
async def deliver_start(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    clear_progress(message.from_user.id)
    await state.clear()
    await show_booked_pick(message, state)


@router.message(F.text == "▶ Resume delivery")
async def deliver_resume(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    progress = load_progress(message.from_user.id)
    if not progress or progress.get("flow") != "delivery":
        await message.answer("No saved delivery progress.")
        return
    await restore_delivery_state(message, state, progress.get("state", "pick"), progress.get("data") or {})


@router.message(F.text == "⏸ Pause")
async def deliver_pause(message: Message, state: FSMContext):
    current = await state.get_state()
    if not current or not current.startswith("DeliveryForm:"):
        return
    uid = message.from_user.id
    state_key = current.split(":", 1)[1]
    data = await state.get_data()
    save_progress(uid, "delivery", state_key, data)
    await state.clear()
    await message.answer(
        "⏸ Delivery progress saved.",
        reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
    )


@router.callback_query(F.data.startswith("delpick:"))
async def deliver_pick(call: CallbackQuery, state: FSMContext):
    if not is_authorized(call.from_user.id):
        await call.answer()
        return
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        is_manager = call.from_user.id in MANAGERS
        await call.message.answer("Main menu:", reply_markup=main_menu(is_manager=is_manager, user_id=call.from_user.id))
        await call.answer()
        return
    rental = get_rental_by_id(choice)
    if not rental or str(rental.get("status", "")).lower() != "booked":
        await call.answer("Booking not found or already delivered.", show_alert=True)
        return
    bike = rental.get("bike", "")
    prev_video = get_last_bike_video_link(bike)
    prev_chk = get_last_bike_checklist(bike)
    data = default_delivery_data(rental)
    await state.update_data(**data)
    await state.set_state(DeliveryForm.review)
    await call.message.edit_text(
        format_booking_card(rental, prev_video, prev_chk),
        parse_mode="HTML",
    )
    await call.message.answer("Start delivery checklist?", reply_markup=confirm_change_kb())
    await call.answer()


@router.message(DeliveryForm.review)
async def deliver_review(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await show_booked_pick(message, state)
        return
    if text not in ("✅ Confirm", "✏️ Change"):
        await message.answer("Tap ✅ Confirm to start or ❌ Cancel.", reply_markup=confirm_change_kb())
        return
    await state.set_state(DeliveryForm.odometer_photo)
    await message.answer(
        "📸 Send ONE photo of odometer + fuel level.\n"
        "<i>Total mileage (main number), not daily/trip.</i>",
        parse_mode="HTML",
        reply_markup=pause_back_cancel_kb(),
    )


@router.message(DeliveryForm.odometer_photo, F.photo)
async def deliver_odometer_photo(message: Message, state: FSMContext):
    await message.answer("⏳ Reading odometer...")
    photo = message.photo[-1]
    file = await message.bot.get_file(photo.file_id)
    buf = io.BytesIO()
    await message.bot.download_file(file.file_path, buf)
    result = await read_odometer_photo(buf.getvalue())
    odo = result.get("odometer")
    fuel = result.get("fuel_bar")
    await state.update_data(
        odometer_photo_id=photo.file_id,
        odometer=str(odo) if odo is not None else "",
        fuel_bar=str(fuel) if fuel is not None else "",
    )
    await state.set_state(DeliveryForm.odometer_confirm)
    summary = f"🔢 Odometer: <b>{odo if odo is not None else '—'}</b> km\n⛽ Fuel: <b>{fuel if fuel is not None else '—'}</b> bar"
    if odo is None and fuel is None:
        summary += "\n\n⚠️ Could not read. Confirm or enter manually."
    await message.answer(summary, parse_mode="HTML", reply_markup=confirm_change_kb())


@router.message(DeliveryForm.odometer_photo)
async def deliver_odometer_photo_required(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if message.text == "⬅️ Back":
        await state.set_state(DeliveryForm.review)
        data = await state.get_data()
        rental = data.get("rental") or {}
        await message.answer(format_booking_card(rental), parse_mode="HTML", reply_markup=confirm_change_kb())
        return
    await message.answer("Send odometer photo.", reply_markup=pause_back_cancel_kb())


@router.message(DeliveryForm.odometer_confirm)
async def deliver_odometer_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.odometer_photo)
        await message.answer("📸 Send odometer photo.", reply_markup=pause_back_cancel_kb())
        return
    if text == "✏️ Change":
        await state.set_state(DeliveryForm.odometer_manual)
        await message.answer(
            "Enter odometer km and fuel bar (e.g. <code>12345 3</code>):",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Change.", reply_markup=confirm_change_kb())
        return
    await state.set_state(DeliveryForm.video)
    await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(DeliveryForm.odometer_manual)
async def deliver_odometer_manual(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.odometer_confirm)
        data = await state.get_data()
        await message.answer(
            f"🔢 Odometer: {data.get('odometer') or '—'} km | Fuel: {data.get('fuel_bar') or '—'} bar",
            reply_markup=confirm_change_kb(),
        )
        return
    nums = re.findall(r"\d+", text)
    if len(nums) >= 2:
        await state.update_data(odometer=nums[0], fuel_bar=nums[1])
    elif len(nums) == 1:
        await state.update_data(odometer=nums[0])
    else:
        await message.answer("Enter numbers like: 12345 3", reply_markup=pause_back_cancel_kb())
        return
    await state.set_state(DeliveryForm.video)
    await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(DeliveryForm.video, F.video)
async def deliver_video(message: Message, state: FSMContext):
    await state.update_data(video_file_id=message.video.file_id)
    await state.update_data(checklist_step=0)
    await state.set_state(DeliveryForm.checklist)
    key, label = CHECKLIST_STEPS[0]
    await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())


@router.message(DeliveryForm.video, F.document)
async def deliver_video_document(message: Message, state: FSMContext):
    mime = (message.document.mime_type or "").lower()
    if mime.startswith("video/"):
        await state.update_data(video_file_id=message.document.file_id)
        await state.update_data(checklist_step=0)
        await state.set_state(DeliveryForm.checklist)
        key, label = CHECKLIST_STEPS[0]
        await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())
    else:
        await message.answer("Send a video file.", reply_markup=pause_back_cancel_kb())


@router.message(DeliveryForm.video)
async def deliver_video_required(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if message.text == "⬅️ Back":
        await state.set_state(DeliveryForm.odometer_confirm)
        data = await state.get_data()
        await message.answer(
            f"🔢 Odometer: {data.get('odometer') or '—'} km | Fuel: {data.get('fuel_bar') or '—'} bar",
            reply_markup=confirm_change_kb(),
        )
        return
    await message.answer("Send video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(DeliveryForm.checklist)
async def deliver_checklist(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    data = await state.get_data()
    step = int(data.get("checklist_step") or 0)
    if text == "⬅️ Back":
        if step <= 0:
            await state.set_state(DeliveryForm.video)
            await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())
            return
        step -= 1
        await state.update_data(checklist_step=step)
        key, label = CHECKLIST_STEPS[step]
        await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())
        return
    if text not in ("Yes", "No"):
        key, label = CHECKLIST_STEPS[step]
        await message.answer(f"Answer Yes or No for: {label}", reply_markup=yes_no_kb())
        return
    key, _ = CHECKLIST_STEPS[step]
    checklist = dict(data.get("checklist") or {})
    checklist[key] = text
    step += 1
    if step >= len(CHECKLIST_STEPS):
        await state.update_data(checklist=checklist)
        await state.set_state(DeliveryForm.helmets)
        data = await state.get_data()
        await message.answer(
            f"🪖 Helmets booked: <b>{data.get('helmets', '0')}</b>\nConfirm or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    await state.update_data(checklist=checklist, checklist_step=step)
    _, label = CHECKLIST_STEPS[step]
    await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())


@router.message(DeliveryForm.helmets)
async def deliver_helmets(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.checklist)
        await state.update_data(checklist_step=len(CHECKLIST_STEPS) - 1)
        key, label = CHECKLIST_STEPS[-1]
        await message.answer(f"📋 Checklist — {label}?", reply_markup=yes_no_kb())
        return
    if text == "✏️ Change":
        await state.set_state(DeliveryForm.helmets_custom)
        await message.answer("🪖 Enter helmets count:", reply_markup=helmets_kb())
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Change.", reply_markup=confirm_change_kb())
        return
    data = await state.get_data()
    await state.set_state(DeliveryForm.payment)
    await message.answer(
        f"💳 Payment — {format_idr(int(data.get('rental_price') or 0))}\n"
        f"Select method:",
        reply_markup=payment_method_kb(),
    )


@router.message(DeliveryForm.helmets_custom)
async def deliver_helmets_custom(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.helmets)
        data = await state.get_data()
        await message.answer(
            f"🪖 Helmets booked: <b>{data.get('helmets', '0')}</b>",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    await state.update_data(helmets=text)
    await state.set_state(DeliveryForm.payment)
    data = await state.get_data()
    await message.answer(
        f"💳 Payment — {format_idr(int(data.get('rental_price') or 0))}\nSelect method:",
        reply_markup=payment_method_kb(),
    )


@router.message(DeliveryForm.payment)
async def deliver_payment(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.helmets)
        data = await state.get_data()
        await message.answer(
            f"🪖 Helmets: <b>{data.get('helmets', '0')}</b>",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if text not in ("Cash", "Transfer", "Already paid"):
        await message.answer("Select payment method.", reply_markup=payment_method_kb())
        return
    await state.update_data(payment_method=text)
    data = await state.get_data()
    await state.set_state(DeliveryForm.payment_confirm)
    await message.answer(
        f"💳 <b>{text}</b> — {format_idr(int(data.get('rental_price') or 0))}\n"
        "Confirm price or change?",
        parse_mode="HTML",
        reply_markup=confirm_change_kb(),
    )


@router.message(DeliveryForm.payment_confirm)
async def deliver_payment_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⏸ Pause":
        await deliver_pause(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.payment)
        data = await state.get_data()
        await message.answer(
            f"💳 Payment — {format_idr(int(data.get('rental_price') or 0))}\nSelect method:",
            reply_markup=payment_method_kb(),
        )
        return
    if text == "✏️ Change":
        await state.set_state(DeliveryForm.payment_amount)
        await message.answer(
            f"Enter rental price (IDR). Current: {format_idr(int((await state.get_data()).get('rental_price') or 0))}",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Change.", reply_markup=confirm_change_kb())
        return
    data = await state.get_data()
    ins = data.get("insurance") or "No insurance"
    extra = ""
    if ins == "With insurance":
        extra = f" ({format_idr(int(data.get('insurance_cost') or 0))})"
    await state.set_state(DeliveryForm.insurance)
    await message.answer(
        f"🛡 Insurance: <b>{ins}{extra}</b>\nConfirm or change?",
        parse_mode="HTML",
        reply_markup=confirm_change_kb(),
    )


@router.message(DeliveryForm.payment_amount)
async def deliver_payment_amount(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⏸ Pause":
        await deliver_pause(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.payment_confirm)
        data = await state.get_data()
        await message.answer(
            f"💳 <b>{data.get('payment_method', '—')}</b> — {format_idr(int(data.get('rental_price') or 0))}\n"
            "Confirm price or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    digits = re.sub(r"[^\d]", "", text)
    if not digits or int(digits) <= 0:
        await message.answer("Enter a valid amount in IDR.", reply_markup=pause_back_cancel_kb())
        return
    await state.update_data(rental_price=digits)
    await state.set_state(DeliveryForm.payment_confirm)
    data = await state.get_data()
    await message.answer(
        f"💳 <b>{data.get('payment_method', '—')}</b> — {format_idr(int(digits))}\n"
        "Confirm price or change?",
        parse_mode="HTML",
        reply_markup=confirm_change_kb(),
    )


@router.message(DeliveryForm.insurance)
async def deliver_insurance(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⏸ Pause":
        await deliver_pause(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.payment_confirm)
        data = await state.get_data()
        await message.answer(
            f"💳 <b>{data.get('payment_method', '—')}</b> — {format_idr(int(data.get('rental_price') or 0))}\n"
            "Confirm price or change?",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if text == "✏️ Change":
        await state.set_state(DeliveryForm.insurance_cost)
        await message.answer("🛡 Insurance:", reply_markup=insurance_kb())
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Change.", reply_markup=confirm_change_kb())
        return
    data = await state.get_data()
    await state.set_state(DeliveryForm.confirm)
    await message.answer(format_delivery_summary(data), parse_mode="HTML", reply_markup=delivery_confirm_kb())


@router.message(DeliveryForm.insurance_cost)
async def deliver_insurance_cost(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.insurance)
        data = await state.get_data()
        ins = data.get("insurance") or "No insurance"
        await message.answer(f"🛡 Insurance: {ins}", reply_markup=confirm_change_kb())
        return
    if text == "No insurance":
        await state.update_data(insurance="No insurance", insurance_cost="0")
    elif text == "With insurance":
        await state.update_data(insurance="With insurance")
        await message.answer("Enter insurance cost (IDR):", reply_markup=pause_back_cancel_kb())
        return
    else:
        digits = re.sub(r"[^\d]", "", text)
        if digits:
            data = await state.get_data()
            if data.get("insurance") == "With insurance" and not text.lower().startswith("with"):
                await state.update_data(insurance_cost=digits)
                await state.set_state(DeliveryForm.confirm)
                data = await state.get_data()
                await message.answer(format_delivery_summary(data), parse_mode="HTML", reply_markup=delivery_confirm_kb())
                return
        await message.answer("Select insurance option.", reply_markup=insurance_kb())
        return
    await state.set_state(DeliveryForm.confirm)
    data = await state.get_data()
    await message.answer(format_delivery_summary(data), parse_mode="HTML", reply_markup=delivery_confirm_kb())


@router.message(DeliveryForm.confirm)
async def deliver_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_delivery(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(DeliveryForm.insurance)
        data = await state.get_data()
        ins = data.get("insurance") or "No insurance"
        await message.answer(f"🛡 Insurance: {ins}", reply_markup=confirm_change_kb())
        return
    if text != "✅ Confirm delivery":
        await message.answer("Tap ✅ Confirm delivery.", reply_markup=delivery_confirm_kb())
        return

    uid = message.from_user.id
    data = await state.get_data()
    rental = data.get("rental") or {}
    rental_id = data.get("rental_id") or rental.get("rental_id", "")
    instructor = employee_name(uid)
    today = now_date()
    time = now_time()

    await message.answer("⏳ Saving delivery...")

    odometer_url = ""
    if data.get("odometer_photo_id"):
        odometer_url = await upload_receipt_to_drive(
            message.bot,
            data["odometer_photo_id"],
            f"delivery_odo_{rental_id}_{today}.jpg",
            today,
        ) or ""

    video_url = ""
    if data.get("video_file_id"):
        video_url = await upload_telegram_file_to_drive(
            message.bot,
            data["video_file_id"],
            f"delivery_video_{rental_id}_{today}.mp4",
            "video/mp4",
        ) or ""

    price = int(data.get("rental_price") or 0)
    ins_cost = int(data.get("insurance_cost") or 0) if data.get("insurance") == "With insurance" else 0
    total = price + ins_cost

    await update_rental_fields(rental_id, {
        "status": "active",
        "odometer_out": data.get("odometer", ""),
        "fuel_out": data.get("fuel_bar", ""),
        "video_out": video_url,
        "payment_method": data.get("payment_method", ""),
        "helmets": data.get("helmets", ""),
        "insurance": data.get("insurance", ""),
        "insurance_cost": ins_cost if ins_cost else "",
        "rental_price": price,
        "total": total,
        "instructor": instructor,
    })

    payment_method = data.get("payment_method", "")
    if payment_method in ("Cash", "Transfer") and total > 0:
        client_name = rental.get("client_name", "")
        comment = f"{payment_method} — delivery {rental_id}"
        await append_income(
            today, time, "Rental", client_name, "", total, instructor,
            comment=comment, purpose="Rental", rental_id=rental_id, payment_type=payment_method,
        )

    chk = data.get("checklist") or {}
    await append_checklist({
        "date": today,
        "time": time,
        "rental_id": rental_id,
        "bike": rental.get("bike", ""),
        "type": "delivery",
        "phone_holder": chk.get("phone_holder", ""),
        "phone_charger": chk.get("phone_charger", ""),
        "first_aid": chk.get("first_aid", ""),
        "bike_papers": chk.get("bike_papers", ""),
        "adjuster": chk.get("adjuster", ""),
        "helmets_count": data.get("helmets", ""),
        "odometer": data.get("odometer", ""),
        "fuel_bar": data.get("fuel_bar", ""),
        "photo": odometer_url,
        "instructor": instructor,
        "notes": "",
    })

    notify = (
        f"✅ <b>Bike delivered</b> <code>{rental_id}</code>\n\n"
        f"👤 {rental.get('client_name', '—')}\n"
        f"🏍 {rental.get('bike', '—')}\n"
        f"🔢 Odo out: {data.get('odometer', '—')} km | Fuel: {data.get('fuel_bar', '—')} bar\n"
        f"💳 {data.get('payment_method', '—')} — {format_idr(price)}\n"
        f"👨‍🏫 {instructor}"
    )
    if video_url:
        notify += f"\n🎬 {video_url}"

    try:
        await notify_rental_channels(message.bot, notify)
    except Exception as e:
        print(f"delivery notify error: {e}")

    clear_progress(uid)
    await state.clear()
    is_manager = uid in MANAGERS
    await message.answer(
        f"✅ Delivery complete! Rental <code>{rental_id}</code> is now <b>active</b>.",
        reply_markup=main_menu(is_manager=is_manager, user_id=uid),
        parse_mode="HTML",
    )

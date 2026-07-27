import io
import re

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS
from handlers.common import is_authorized
from handlers.delivery import (
    CHECKLIST_STEPS, yes_no_kb, confirm_change_kb, employee_name, notify_rental_channels, nav_kb,
)
from keyboards.kb import main_menu, pause_back_cancel_kb
from utils.rental_progress import save_progress, clear_progress, load_progress
from utils.sheets import (
    get_active_rentals, get_rental_by_id, update_rental_fields, append_checklist, append_bike_issue,
    format_idr, now_date, now_time,
)
from utils.gemini import read_odometer_photo
from utils.drive_upload import upload_receipt_to_drive, upload_telegram_file_to_drive

router = Router()

MAX_DAMAGE_PHOTOS = 10


class ReturnForm(StatesGroup):
    pick = State()
    review = State()
    video = State()
    odometer_photo = State()
    odometer_confirm = State()
    odometer_manual = State()
    checklist = State()
    damages = State()
    damages_text = State()
    damages_photos = State()
    extras_collected = State()
    confirm = State()


def damages_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="No damages"), KeyboardButton(text="Yes, damages")]])


def damages_photos_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="✅ Done adding photos")]])


def return_confirm_kb() -> ReplyKeyboardMarkup:
    return nav_kb([[KeyboardButton(text="✅ Confirm return")]])


def default_return_data(rental: dict) -> dict:
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
        "has_damages": False,
        "damage_text": "",
        "damage_photo_ids": [],
        "damage_photo_urls": [],
        "extras_collected": "",
    }


def format_return_review(rental: dict) -> str:
    extras = str(rental.get("extra_charges") or "").strip()
    lines = [
        f"🏁 <b>Return</b> <code>{rental.get('rental_id', '—')}</code>\n",
        f"👤 {rental.get('client_name', '—')}",
        f"🏍 {rental.get('bike', '—')}",
        f"📅 Delivered: {rental.get('delivery_date', '—')} → Return: {rental.get('return_date', '—')}",
        f"🔢 Odo out: {rental.get('odometer_out', '—')} km | Fuel out: {rental.get('fuel_out', '—')} bar",
        f"💵 {format_idr(int(rental.get('rental_price') or 0))} | Total {format_idr(int(rental.get('total') or 0))}",
    ]
    if extras and extras not in ("—", "0"):
        lines.append(f"➕ <b>Extra charges from manager:</b> {extras}")
    if rental.get("video_out"):
        lines.append(f"🎬 Delivery video: {rental.get('video_out')}")
    return "\n".join(lines)


def format_return_summary(data: dict) -> str:
    rental = data.get("rental") or {}
    chk = data.get("checklist") or {}
    chk_lines = ", ".join(f"{label}: {chk.get(key, '—')}" for key, label in CHECKLIST_STEPS)
    dmg = "No"
    if data.get("has_damages"):
        dmg = data.get("damage_text") or "Yes"
        n = len(data.get("damage_photo_urls") or [])
        if n:
            dmg += f" ({n} photo(s))"
    extras_line = rental.get("extra_charges") or "—"
    collected = data.get("extras_collected") or "—"
    return (
        f"🏁 <b>Confirm return</b> <code>{data.get('rental_id', '—')}</code>\n\n"
        f"👤 {rental.get('client_name', '—')} | 🏍 {rental.get('bike', '—')}\n"
        f"🔢 Odo in: {data.get('odometer', '—')} km | Fuel: {data.get('fuel_bar', '—')} bar\n"
        f"✅ Checklist: {chk_lines or '—'}\n"
        f"⚠️ Damages: {dmg}\n"
        f"➕ Extras ({extras_line}): collected — <b>{collected}</b>\n"
        f"🎬 Return video: {'✅' if data.get('video_url') or data.get('video_file_id') else '—'}"
    )


async def cancel_return(message: Message, state: FSMContext):
    uid = message.from_user.id
    clear_progress(uid)
    await state.clear()
    await message.answer("Cancelled.", reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid))


async def restore_return_state(message: Message, state: FSMContext, state_key: str, data: dict):
    await state.update_data(**data)
    rental = data.get("rental") or {}
    if state_key == "pick":
        await show_active_pick(message, state)
        return
    if state_key == "review":
        await state.set_state(ReturnForm.review)
        await message.answer(format_return_review(rental), parse_mode="HTML", reply_markup=confirm_change_kb())
        return
    if state_key == "video":
        await state.set_state(ReturnForm.video)
        await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())
        return
    if state_key == "odometer_photo":
        await state.set_state(ReturnForm.odometer_photo)
        await message.answer(
            "📸 Send ONE photo of odometer + fuel level.\n"
            "<i>Total mileage (main number), not daily/trip.</i>",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if state_key == "odometer_confirm":
        await state.set_state(ReturnForm.odometer_confirm)
        await message.answer(
            f"🔢 Odometer: <b>{data.get('odometer') or '—'}</b> km\n"
            f"⛽ Fuel: <b>{data.get('fuel_bar') or '—'}</b> bar",
            parse_mode="HTML",
            reply_markup=confirm_change_kb(),
        )
        return
    if state_key == "odometer_manual":
        await state.set_state(ReturnForm.odometer_manual)
        await message.answer(
            "Enter odometer km and fuel bar (e.g. <code>12345 3</code>):",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if state_key == "checklist":
        step = int(data.get("checklist_step") or 0)
        step = min(step, len(CHECKLIST_STEPS) - 1)
        await state.set_state(ReturnForm.checklist)
        _, label = CHECKLIST_STEPS[step]
        await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())
        return
    if state_key == "damages":
        await state.set_state(ReturnForm.damages)
        await message.answer("⚠️ Any damages?", reply_markup=damages_kb())
        return
    if state_key == "damages_text":
        await state.set_state(ReturnForm.damages_text)
        await message.answer("Describe the damage:", reply_markup=pause_back_cancel_kb())
        return
    if state_key == "damages_photos":
        n = len(data.get("damage_photo_ids") or [])
        await state.set_state(ReturnForm.damages_photos)
        await message.answer(
            f"📸 Send damage photos (up to {MAX_DAMAGE_PHOTOS}) or tap Done.\n"
            f"Added: {n}/{MAX_DAMAGE_PHOTOS}",
            reply_markup=damages_photos_kb(),
        )
        return
    if state_key == "extras_collected":
        extras = str(rental.get("extra_charges") or "").strip()
        await state.set_state(ReturnForm.extras_collected)
        if extras and extras not in ("—", "0", ""):
            await message.answer(
                f"➕ Extra charges: <b>{extras}</b>\nWere they collected from the client?",
                parse_mode="HTML",
                reply_markup=yes_no_kb(),
            )
        else:
            await _goto_confirm(message, state)
        return
    if state_key == "confirm":
        await _goto_confirm(message, state)
        return
    await show_active_pick(message, state)


async def show_active_pick(message: Message, state: FSMContext):
    active = get_active_rentals()
    if not active:
        await state.clear()
        await message.answer(
            "📭 No active rentals to return.",
            reply_markup=main_menu(is_manager=message.from_user.id in MANAGERS, user_id=message.from_user.id),
        )
        return
    buttons = []
    for r in active[:20]:
        rid = r.get("rental_id", "?")
        label = f"{rid} | {r.get('client_name', '?')} | {r.get('bike', '?')}"
        buttons.append([InlineKeyboardButton(text=label[:60], callback_data=f"retpick:{rid}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="retpick:cancel")])
    await state.set_state(ReturnForm.pick)
    await message.answer(
        "🏁 <b>Active rentals</b>\n\nSelect rental to return:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML",
    )


@router.message(F.text == "🏁 Return bike")
async def return_start(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    clear_progress(message.from_user.id)
    await state.clear()
    await show_active_pick(message, state)


@router.message(F.text == "▶ Resume return")
async def return_resume(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    progress = load_progress(message.from_user.id)
    if not progress or progress.get("flow") != "return":
        await message.answer("No saved return progress.")
        return
    await restore_return_state(message, state, progress.get("state", "pick"), progress.get("data") or {})


@router.message(F.text == "⏸ Pause")
async def return_pause(message: Message, state: FSMContext):
    current = await state.get_state()
    if not current or not current.startswith("ReturnForm:"):
        return
    uid = message.from_user.id
    state_key = current.split(":", 1)[1]
    data = await state.get_data()
    save_progress(uid, "return", state_key, data)
    await state.clear()
    await message.answer(
        "⏸ Return progress saved.",
        reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
    )


@router.callback_query(F.data.startswith("retpick:"))
async def return_pick(call: CallbackQuery, state: FSMContext):
    if not is_authorized(call.from_user.id):
        await call.answer()
        return
    choice = call.data.split(":", 1)[1]
    if choice == "cancel":
        await state.clear()
        await call.message.edit_text("Cancelled.")
        await call.message.answer(
            "Main menu:",
            reply_markup=main_menu(is_manager=call.from_user.id in MANAGERS, user_id=call.from_user.id),
        )
        await call.answer()
        return
    rental = get_rental_by_id(choice)
    if not rental or str(rental.get("status", "")).lower() != "active":
        await call.answer("Rental not found or not active.", show_alert=True)
        return
    await state.update_data(**default_return_data(rental))
    await state.set_state(ReturnForm.review)
    await call.message.edit_text(format_return_review(rental), parse_mode="HTML")
    await call.message.answer("Start return process?", reply_markup=confirm_change_kb())
    await call.answer()


@router.message(ReturnForm.review)
async def return_review(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await show_active_pick(message, state)
        return
    if text not in ("✅ Confirm", "✏️ Change"):
        await message.answer("Tap ✅ Confirm to start.", reply_markup=confirm_change_kb())
        return
    await state.set_state(ReturnForm.video)
    await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(ReturnForm.video, F.video)
async def return_video(message: Message, state: FSMContext):
    await state.update_data(video_file_id=message.video.file_id)
    await state.set_state(ReturnForm.odometer_photo)
    await message.answer(
        "📸 Send ONE photo of odometer + fuel level.\n"
        "<i>Total mileage (main number), not daily/trip.</i>",
        parse_mode="HTML",
        reply_markup=pause_back_cancel_kb(),
    )


@router.message(ReturnForm.video, F.document)
async def return_video_doc(message: Message, state: FSMContext):
    if (message.document.mime_type or "").lower().startswith("video/"):
        await state.update_data(video_file_id=message.document.file_id)
        await state.set_state(ReturnForm.odometer_photo)
        await message.answer(
            "📸 Send ONE photo of odometer + fuel level.",
            reply_markup=pause_back_cancel_kb(),
        )
    else:
        await message.answer("Send a video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(ReturnForm.video)
async def return_video_required(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if message.text == "⬅️ Back":
        await state.set_state(ReturnForm.review)
        data = await state.get_data()
        rental = data.get("rental") or {}
        await message.answer(format_return_review(rental), parse_mode="HTML", reply_markup=confirm_change_kb())
        return
    await message.answer("Send video of the bike.", reply_markup=pause_back_cancel_kb())


@router.message(ReturnForm.odometer_photo, F.photo)
async def return_odometer_photo(message: Message, state: FSMContext):
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
    await state.set_state(ReturnForm.odometer_confirm)
    summary = f"🔢 Odometer: <b>{odo if odo is not None else '—'}</b> km\n⛽ Fuel: <b>{fuel if fuel is not None else '—'}</b> bar"
    if odo is None and fuel is None:
        summary += "\n\n⚠️ Could not read. Confirm or enter manually."
    await message.answer(summary, parse_mode="HTML", reply_markup=confirm_change_kb())


@router.message(ReturnForm.odometer_photo)
async def return_odometer_required(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if message.text == "⬅️ Back":
        await state.set_state(ReturnForm.video)
        await message.answer("🎬 Send video of the bike.", reply_markup=pause_back_cancel_kb())
        return
    await message.answer("Send odometer photo.", reply_markup=pause_back_cancel_kb())


@router.message(ReturnForm.odometer_confirm)
async def return_odometer_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(ReturnForm.odometer_photo)
        await message.answer("📸 Send odometer photo.", reply_markup=pause_back_cancel_kb())
        return
    if text == "✏️ Change":
        await state.set_state(ReturnForm.odometer_manual)
        await message.answer(
            "Enter odometer km and fuel bar (e.g. <code>12345 3</code>):",
            parse_mode="HTML",
            reply_markup=pause_back_cancel_kb(),
        )
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Change.", reply_markup=confirm_change_kb())
        return
    await state.update_data(checklist_step=0)
    await state.set_state(ReturnForm.checklist)
    key, label = CHECKLIST_STEPS[0]
    await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())


@router.message(ReturnForm.odometer_manual)
async def return_odometer_manual(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(ReturnForm.odometer_confirm)
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
    await state.update_data(checklist_step=0)
    await state.set_state(ReturnForm.checklist)
    _, label = CHECKLIST_STEPS[0]
    await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())


@router.message(ReturnForm.checklist)
async def return_checklist(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    data = await state.get_data()
    step = int(data.get("checklist_step") or 0)
    if text == "⬅️ Back":
        if step <= 0:
            await state.set_state(ReturnForm.odometer_confirm)
            data = await state.get_data()
            await message.answer(
                f"🔢 Odometer: {data.get('odometer') or '—'} km | Fuel: {data.get('fuel_bar') or '—'} bar",
                reply_markup=confirm_change_kb(),
            )
            return
        step -= 1
        await state.update_data(checklist_step=step)
        _, label = CHECKLIST_STEPS[step]
        await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())
        return
    if text not in ("Yes", "No"):
        _, label = CHECKLIST_STEPS[step]
        await message.answer(f"Answer Yes or No for: {label}", reply_markup=yes_no_kb())
        return
    key, _ = CHECKLIST_STEPS[step]
    checklist = dict(data.get("checklist") or {})
    checklist[key] = text
    step += 1
    if step >= len(CHECKLIST_STEPS):
        await state.update_data(checklist=checklist)
        await state.set_state(ReturnForm.damages)
        await message.answer("⚠️ Any damages?", reply_markup=damages_kb())
        return
    await state.update_data(checklist=checklist, checklist_step=step)
    _, label = CHECKLIST_STEPS[step]
    await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())


@router.message(ReturnForm.damages)
async def return_damages(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(ReturnForm.checklist)
        await state.update_data(checklist_step=len(CHECKLIST_STEPS) - 1)
        _, label = CHECKLIST_STEPS[-1]
        await message.answer(f"📋 Return checklist — {label}?", reply_markup=yes_no_kb())
        return
    if text == "No damages":
        await state.update_data(has_damages=False, damage_text="", damage_photo_ids=[], damage_photo_urls=[])
        await _goto_extras_collected(message, state)
        return
    if text == "Yes, damages":
        await state.update_data(has_damages=True, damage_photo_ids=[], damage_photo_urls=[])
        await state.set_state(ReturnForm.damages_text)
        await message.answer("Describe the damage:", reply_markup=pause_back_cancel_kb())
        return
    await message.answer("Select damages option.", reply_markup=damages_kb())


async def _goto_extras_collected(message: Message, state: FSMContext):
    data = await state.get_data()
    rental = data.get("rental") or {}
    extras = str(rental.get("extra_charges") or "").strip()
    await state.set_state(ReturnForm.extras_collected)
    if extras and extras not in ("—", "0", ""):
        await message.answer(
            f"➕ Extra charges: <b>{extras}</b>\nWere they collected from the client?",
            parse_mode="HTML",
            reply_markup=yes_no_kb(),
        )
    else:
        await state.update_data(extras_collected="N/A")
        await _goto_confirm(message, state)


async def _goto_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(ReturnForm.confirm)
    await message.answer(format_return_summary(data), parse_mode="HTML", reply_markup=return_confirm_kb())


@router.message(ReturnForm.damages_text)
async def return_damages_text(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(ReturnForm.damages)
        await message.answer("⚠️ Any damages?", reply_markup=damages_kb())
        return
    if len(text) < 3:
        await message.answer("Enter damage description (min 3 characters).", reply_markup=pause_back_cancel_kb())
        return
    await state.update_data(damage_text=text)
    await state.set_state(ReturnForm.damages_photos)
    await message.answer(
        f"📸 Send damage photos (up to {MAX_DAMAGE_PHOTOS}) or tap Done.",
        reply_markup=damages_photos_kb(),
    )


async def _add_damage_photo(message: Message, state: FSMContext, file_id: str):
    data = await state.get_data()
    ids = list(data.get("damage_photo_ids") or [])
    if len(ids) >= MAX_DAMAGE_PHOTOS:
        await message.answer(f"Maximum {MAX_DAMAGE_PHOTOS} photos. Tap Done.", reply_markup=damages_photos_kb())
        return
    ids.append(file_id)
    await state.update_data(damage_photo_ids=ids)
    await message.answer(f"Photo {len(ids)}/{MAX_DAMAGE_PHOTOS} added. Send more or tap Done.", reply_markup=damages_photos_kb())


@router.message(ReturnForm.damages_photos, F.photo)
async def return_damage_photo(message: Message, state: FSMContext):
    await _add_damage_photo(message, state, message.photo[-1].file_id)


@router.message(ReturnForm.damages_photos, F.document)
async def return_damage_photo_doc(message: Message, state: FSMContext):
    if (message.document.mime_type or "").startswith("image/"):
        await _add_damage_photo(message, state, message.document.file_id)
    else:
        await message.answer("Send photos or tap Done.", reply_markup=damages_photos_kb())


@router.message(ReturnForm.damages_photos)
async def return_damages_photos_done(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(ReturnForm.damages_text)
        await message.answer("Describe the damage:", reply_markup=pause_back_cancel_kb())
        return
    if text != "✅ Done adding photos":
        await message.answer("Send photos or tap Done.", reply_markup=damages_photos_kb())
        return
    await _goto_extras_collected(message, state)


@router.message(ReturnForm.extras_collected)
async def return_extras_collected(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    data = await state.get_data()
    if text == "⬅️ Back":
        if data.get("has_damages"):
            await state.set_state(ReturnForm.damages_photos)
            await message.answer("Send damage photos or tap Done.", reply_markup=damages_photos_kb())
        else:
            await state.set_state(ReturnForm.damages)
            await message.answer("⚠️ Any damages?", reply_markup=damages_kb())
        return
    if text not in ("Yes", "No"):
        await message.answer("Answer Yes or No.", reply_markup=yes_no_kb())
        return
    await state.update_data(extras_collected=text)
    await _goto_confirm(message, state)


@router.message(ReturnForm.confirm)
async def return_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_return(message, state)
        return
    if text == "⬅️ Back":
        data = await state.get_data()
        rental = data.get("rental") or {}
        extras = str(rental.get("extra_charges") or "").strip()
        if extras and extras not in ("—", "0", "") and data.get("extras_collected") != "N/A":
            await state.set_state(ReturnForm.extras_collected)
            await message.answer(
                f"➕ Extra charges: {extras}\nCollected?",
                reply_markup=yes_no_kb(),
            )
        elif data.get("has_damages"):
            await state.set_state(ReturnForm.damages_photos)
            await message.answer("Damage photos or Done.", reply_markup=damages_photos_kb())
        else:
            await state.set_state(ReturnForm.damages)
            await message.answer("⚠️ Any damages?", reply_markup=damages_kb())
        return
    if text != "✅ Confirm return":
        await message.answer("Tap ✅ Confirm return.", reply_markup=return_confirm_kb())
        return

    uid = message.from_user.id
    data = await state.get_data()
    rental = data.get("rental") or {}
    rental_id = data.get("rental_id") or rental.get("rental_id", "")
    instructor = employee_name(uid)
    today = now_date()
    time = now_time()

    await message.answer("⏳ Saving return...")

    odometer_url = ""
    if data.get("odometer_photo_id"):
        odometer_url = await upload_receipt_to_drive(
            message.bot,
            data["odometer_photo_id"],
            f"return_odo_{rental_id}_{today}.jpg",
            today,
        ) or ""

    video_url = ""
    if data.get("video_file_id"):
        video_url = await upload_telegram_file_to_drive(
            message.bot,
            data["video_file_id"],
            f"return_video_{rental_id}_{today}.mp4",
            "video/mp4",
        ) or ""

    damage_urls = []
    for i, fid in enumerate(data.get("damage_photo_ids") or [], start=1):
        url = await upload_receipt_to_drive(
            message.bot, fid, f"return_damage_{rental_id}_{today}_{i}.jpg", today,
        )
        if url:
            damage_urls.append(url)
    damage_photos_str = " | ".join(damage_urls)

    damage_note = ""
    if data.get("has_damages"):
        damage_note = str(data.get("damage_text") or "Damages reported")

    await update_rental_fields(rental_id, {
        "status": "returned",
        "odometer_in": data.get("odometer", ""),
        "fuel_in": data.get("fuel_bar", ""),
        "video_in": video_url,
        "damages": damage_note if data.get("has_damages") else "No",
        "damage_photos": damage_photos_str,
    })

    chk = data.get("checklist") or {}
    notes_parts = []
    if data.get("extras_collected") and data.get("extras_collected") != "N/A":
        notes_parts.append(f"Extras collected: {data.get('extras_collected')}")
    if damage_note:
        notes_parts.append(damage_note)
    await append_checklist({
        "date": today,
        "time": time,
        "rental_id": rental_id,
        "bike": rental.get("bike", ""),
        "type": "return",
        "phone_holder": chk.get("phone_holder", ""),
        "phone_charger": chk.get("phone_charger", ""),
        "first_aid": chk.get("first_aid", ""),
        "bike_papers": chk.get("bike_papers", ""),
        "adjuster": chk.get("adjuster", ""),
        "helmets_count": rental.get("helmets", ""),
        "odometer": data.get("odometer", ""),
        "fuel_bar": data.get("fuel_bar", ""),
        "photo": odometer_url,
        "instructor": instructor,
        "notes": "; ".join(notes_parts),
    })

    notify = (
        f"🏁 <b>Bike returned</b> <code>{rental_id}</code>\n\n"
        f"👤 {rental.get('client_name', '—')}\n"
        f"🏍 {rental.get('bike', '—')}\n"
        f"🔢 Odo in: {data.get('odometer', '—')} km | Fuel: {data.get('fuel_bar', '—')} bar\n"
        f"👨‍🏫 {instructor}"
    )
    if data.get("has_damages"):
        notify += f"\n⚠️ Damages: {damage_note}"
    if data.get("extras_collected") not in ("", "N/A"):
        notify += f"\n➕ Extras collected: {data.get('extras_collected')}"
    if video_url:
        notify += f"\n🎬 {video_url}"

    try:
        await notify_rental_channels(message.bot, notify)
    except Exception as e:
        print(f"return notify manager error: {e}")

    if data.get("has_damages"):
        issue_desc = f"Rental {rental_id} — {damage_note}"
        if rental.get("client_name"):
            issue_desc += f" (Client: {rental.get('client_name')})"
        await append_bike_issue({
            "date": today,
            "time": time,
            "bike": rental.get("bike", ""),
            "reported_by": instructor,
            "description": issue_desc,
            "photos": damage_photos_str,
            "status": "Open",
            "resolved_date": "",
            "comment": f"Return {rental_id}",
        })
        from handlers.bike_issues import send_bike_issue_notifications
        await send_bike_issue_notifications(
            message.bot,
            bike=rental.get("bike", "—"),
            reported_by=instructor,
            description=issue_desc,
            photos=damage_photos_str,
            rental_id=rental_id,
        )

    clear_progress(uid)
    await state.clear()
    bike = rental.get("bike", "—")
    await message.answer(
        f"✅ Return complete! <code>{rental_id}</code> → <b>returned</b>.\n"
        f"🏍 {bike} is <b>available</b> again.",
        reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
        parse_mode="HTML",
    )

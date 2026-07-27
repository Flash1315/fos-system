from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS, LESSON_GROUP_CHAT_ID, SUPERADMIN_GROUP_CHAT_ID
from handlers.common import is_authorized, get_name
from keyboards.kb import main_menu, back_cancel_kb, bikes_kb, confirm_kb
from utils.sheets import append_bike_issue, now_date, now_time
from utils.drive_upload import upload_receipt_to_drive, upload_telegram_file_to_drive

router = Router()

BIKE_ISSUES_TOPIC_ID = 3775
MAX_ISSUE_MEDIA = 10


class BikeIssueForm(StatesGroup):
    bike = State()
    bike_manual = State()
    description = State()
    photos = State()
    confirm = State()


def issue_media_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip (no photos)")],
            [KeyboardButton(text="✅ Done adding photos")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def format_issue_summary(data: dict) -> str:
    media = data.get("media_ids") or []
    photos_note = "—"
    if media:
        photos_note = f"{len(media)} file(s)"
    return (
        f"⚠️ <b>Confirm bike issue</b>\n\n"
        f"🏍 <b>{data.get('bike', '—')}</b>\n"
        f"📝 {data.get('description', '—')}\n"
        f"📎 Media: {photos_note}"
    )


async def send_bike_issue_notifications(
    bot,
    *,
    bike: str,
    reported_by: str,
    description: str,
    photos: str = "",
    rental_id: str = "",
) -> None:
    text = (
        f"⚠️ <b>Bike issue</b> — {bike}\n"
        f"Reported by {reported_by}\n"
        f"{description}"
    )
    if rental_id:
        text += f"\nRental: <code>{rental_id}</code>"
    if photos:
        text += f"\n📎 {photos}"

    try:
        await bot.send_message(
            chat_id=LESSON_GROUP_CHAT_ID,
            text=text,
            parse_mode="HTML",
            message_thread_id=BIKE_ISSUES_TOPIC_ID,
        )
    except Exception as e:
        print(f"bike issue forum notify error: {e}")

    try:
        await bot.send_message(
            chat_id=SUPERADMIN_GROUP_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"bike issue superadmin notify error: {e}")


async def cancel_issue(message: Message, state: FSMContext):
    uid = message.from_user.id
    await state.clear()
    await message.answer(
        "Cancelled.",
        reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
    )


@router.message(F.text == "⚠️ Report bike issue")
async def issue_start(message: Message, state: FSMContext):
    if not is_authorized(message.from_user.id):
        return
    await state.clear()
    await state.set_state(BikeIssueForm.bike)
    await message.answer("🏍 Select bike:", reply_markup=bikes_kb())


@router.message(BikeIssueForm.bike)
async def issue_bike(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_issue(message, state)
        return
    if text == "⬅️ Back":
        await cancel_issue(message, state)
        return
    if text.startswith("—"):
        return
    if text == "Other (enter manually)":
        await state.set_state(BikeIssueForm.bike_manual)
        await message.answer("🏍 Enter bike name:", reply_markup=back_cancel_kb())
        return
    await state.update_data(bike=text, media_ids=[])
    await state.set_state(BikeIssueForm.description)
    await message.answer("📝 Describe the issue:", reply_markup=back_cancel_kb())


@router.message(BikeIssueForm.bike_manual)
async def issue_bike_manual(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_issue(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(BikeIssueForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    if len(text) < 2:
        await message.answer("Enter bike name (min 2 characters).", reply_markup=back_cancel_kb())
        return
    await state.update_data(bike=text, media_ids=[])
    await state.set_state(BikeIssueForm.description)
    await message.answer("📝 Describe the issue:", reply_markup=back_cancel_kb())


@router.message(BikeIssueForm.description)
async def issue_description(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_issue(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(BikeIssueForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    if len(text) < 3:
        await message.answer("Enter description (min 3 characters).", reply_markup=back_cancel_kb())
        return
    await state.update_data(description=text, media_ids=[])
    await state.set_state(BikeIssueForm.photos)
    await message.answer(
        f"📸 Send photos or video (up to {MAX_ISSUE_MEDIA}), or skip.",
        reply_markup=issue_media_kb(),
    )


async def _add_issue_media(message: Message, state: FSMContext, file_id: str, kind: str):
    data = await state.get_data()
    media = list(data.get("media_ids") or [])
    if len(media) >= MAX_ISSUE_MEDIA:
        await message.answer(
            f"Maximum {MAX_ISSUE_MEDIA} files. Tap Done or Skip.",
            reply_markup=issue_media_kb(),
        )
        return
    media.append({"file_id": file_id, "kind": kind})
    await state.update_data(media_ids=media)
    await message.answer(
        f"Added {len(media)}/{MAX_ISSUE_MEDIA}. Send more or tap Done.",
        reply_markup=issue_media_kb(),
    )


@router.message(BikeIssueForm.photos, F.photo)
async def issue_photo(message: Message, state: FSMContext):
    await _add_issue_media(message, state, message.photo[-1].file_id, "photo")


@router.message(BikeIssueForm.photos, F.video)
async def issue_video(message: Message, state: FSMContext):
    await _add_issue_media(message, state, message.video.file_id, "video")


@router.message(BikeIssueForm.photos, F.document)
async def issue_document(message: Message, state: FSMContext):
    mime = (message.document.mime_type or "").lower()
    if mime.startswith("image/"):
        await _add_issue_media(message, state, message.document.file_id, "photo")
    elif mime.startswith("video/"):
        await _add_issue_media(message, state, message.document.file_id, "video")
    else:
        await message.answer("Send photos or video, or tap Skip.", reply_markup=issue_media_kb())


@router.message(BikeIssueForm.photos)
async def issue_photos_done(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_issue(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(BikeIssueForm.description)
        data = await state.get_data()
        await message.answer(
            f"📝 Current description:\n{data.get('description', '—')}\n\nEdit or send new text:",
            reply_markup=back_cancel_kb(),
        )
        return
    if text not in ("⏭ Skip (no photos)", "✅ Done adding photos"):
        await message.answer("Tap Skip, Done, or send a photo/video.", reply_markup=issue_media_kb())
        return
    if text == "⏭ Skip (no photos)":
        await state.update_data(media_ids=[])
    data = await state.get_data()
    await state.set_state(BikeIssueForm.confirm)
    await message.answer(format_issue_summary(data), parse_mode="HTML", reply_markup=confirm_kb())


@router.message(BikeIssueForm.confirm)
async def issue_confirm(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "❌ Cancel":
        await cancel_issue(message, state)
        return
    if text == "⬅️ Back":
        await state.set_state(BikeIssueForm.photos)
        await message.answer(
            f"📸 Send photos or video (up to {MAX_ISSUE_MEDIA}), or skip.",
            reply_markup=issue_media_kb(),
        )
        return
    if text == "✏️ Edit":
        await state.set_state(BikeIssueForm.bike)
        await message.answer("🏍 Select bike:", reply_markup=bikes_kb())
        return
    if text != "✅ Confirm":
        await message.answer("Tap ✅ Confirm or ✏️ Edit.", reply_markup=confirm_kb())
        return

    uid = message.from_user.id
    data = await state.get_data()
    bike = data.get("bike", "")
    description = data.get("description", "")
    reporter = get_name(uid)
    today = now_date()
    time = now_time()

    await message.answer("⏳ Saving issue...")

    photo_urls = []
    for i, item in enumerate(data.get("media_ids") or [], start=1):
        file_id = item.get("file_id", "")
        kind = item.get("kind", "photo")
        if not file_id:
            continue
        if kind == "video":
            url = await upload_telegram_file_to_drive(
                message.bot,
                file_id,
                f"bike_issue_{bike}_{today}_{i}.mp4".replace(" ", "_"),
                "video/mp4",
            )
        else:
            url = await upload_receipt_to_drive(
                message.bot,
                file_id,
                f"bike_issue_{bike}_{today}_{i}.jpg".replace(" ", "_"),
                today,
            )
        if url:
            photo_urls.append(url)
    photos_str = " | ".join(photo_urls)

    await append_bike_issue({
        "date": today,
        "time": time,
        "bike": bike,
        "reported_by": reporter,
        "description": description,
        "photos": photos_str,
        "status": "Open",
        "resolved_date": "",
        "comment": "",
    })

    await send_bike_issue_notifications(
        message.bot,
        bike=bike,
        reported_by=reporter,
        description=description,
        photos=photos_str,
    )

    await state.clear()
    await message.answer(
        f"✅ Issue reported for <b>{bike}</b>. Managers have been notified.",
        reply_markup=main_menu(is_manager=uid in MANAGERS, user_id=uid),
        parse_mode="HTML",
    )

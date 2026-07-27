from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def purpose_kb(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏍 Rental", callback_data=f"{prefix}:Rental"),
            InlineKeyboardButton(text="📚 Lesson", callback_data=f"{prefix}:Lesson"),
        ],
        [
            InlineKeyboardButton(text="🏢 Office", callback_data=f"{prefix}:Office"),
            InlineKeyboardButton(text="📦 Other", callback_data=f"{prefix}:Other"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data=f"{prefix}:back"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:cancel"),
        ],
    ])


async def show_purpose_prompt(message, prefix: str, title: str = "Purpose:"):
    await message.answer(
        f"🎯 <b>{title}</b>\n\nSelect purpose:",
        reply_markup=purpose_kb(prefix),
        parse_mode="HTML",
    )

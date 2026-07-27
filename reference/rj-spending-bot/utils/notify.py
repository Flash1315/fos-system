from aiogram import Bot
from utils.sheets import format_idr


async def delete_tg_messages(bot: Bot, group_chat_id, tg_message_id):
    """Delete one or more Telegram messages (comma-separated IDs, e.g. media groups)."""
    if not tg_message_id or not group_chat_id:
        return
    for mid in str(tg_message_id).split(","):
        mid = mid.strip()
        if not mid:
            continue
        try:
            await bot.delete_message(chat_id=int(group_chat_id), message_id=int(mid))
        except Exception as e:
            print(f"TG delete error {mid}: {e}")


async def post_expense_to_group(bot: Bot, group_chat_id: int, employee_name: str,
                                 note: str, date: str, amount: int, total_spending: int,
                                 photo_file_id: str = None, comment: str = "",
                                 photo_file_id2: str = None):
    parts = note.split(" — ", 1)
    category = parts[0] if parts else note
    place = parts[1] if len(parts) > 1 else ""
    text = (
        f"👤 {employee_name}\n"
        f"📂 {category}\n"
    )
    if place:
        text += f"📍 {place}\n"
    text += (
        f"📅 {date}\n"
        f"💸 {format_idr(amount)}\n"
        f"📊 Total: {format_idr(total_spending)}"
    )
    if comment:
        text += f"\n💬 {comment}"

    if photo_file_id and photo_file_id2:
        from aiogram.types import InputMediaPhoto
        media = [
            InputMediaPhoto(media=photo_file_id, caption=text),
            InputMediaPhoto(media=photo_file_id2),
        ]
        msgs = await bot.send_media_group(chat_id=group_chat_id, media=media)
        if msgs:
            return ",".join(str(m.message_id) for m in msgs)
        return None
    elif photo_file_id:
        msg = await bot.send_photo(chat_id=group_chat_id, photo=photo_file_id, caption=text)
        return msg.message_id
    else:
        msg = await bot.send_message(chat_id=group_chat_id, text=text)
        return msg.message_id
    return None


async def post_income_to_group(bot: Bot, group_chat_id: int, employee_name: str,
                                client_name: str, note: str, date: str,
                                amount: int, total_income: int, total_spending: int):
    text = (
        f"💰 Received Money\n"
        f"👤 {client_name}\n"
        f"📝 Note: {note}\n"
        f"📅 Date: {date}\n"
        f"💵 Total: {format_idr(amount)}\n"
        f"💸 Spending: {format_idr(total_spending)}\n"
        f"📊 Total Received: {format_idr(total_income)}"
    )
    await bot.send_message(chat_id=group_chat_id, text=text)


async def post_payout_to_group(bot: Bot, group_chat_id: int, employee_name: str,
                                amount: int, payment_type: str, date: str, overpayment: int = 0):
    overpay_line = f"\n⚠️ Advance for next cycle: {format_idr(overpayment)}" if overpayment > 0 else ""
    caption = (
        f"✅ Expense payout — {employee_name}\n"
        f"💵 Amount: {format_idr(amount)}\n"
        f"💳 {payment_type}\n"
        f"📅 {date}"
        f"{overpay_line}"
    )
    import os
    paid_img = "/root/rjbot/assets/paid.png"
    if os.path.exists(paid_img):
        from aiogram.types import FSInputFile
        msg = await bot.send_photo(chat_id=group_chat_id, photo=FSInputFile(paid_img), caption=caption)
    else:
        msg = await bot.send_message(chat_id=group_chat_id, text=caption)
    return msg.message_id


async def post_income_handover_to_group(bot: Bot, group_chat_id: int, employee_name: str,
                                         amount: int, payment_type: str, date: str):
    caption = (
        f"💰 Income handover — {employee_name}\n"
        f"💵 Amount: {format_idr(amount)}\n"
        f"💳 {payment_type}\n"
        f"📅 {date}"
    )
    import os
    recv_img = "/root/rjbot/assets/received.png"
    if os.path.exists(recv_img):
        from aiogram.types import FSInputFile
        msg = await bot.send_photo(chat_id=group_chat_id, photo=FSInputFile(recv_img), caption=caption)
    else:
        msg = await bot.send_message(chat_id=group_chat_id, text=caption)
    return msg.message_id

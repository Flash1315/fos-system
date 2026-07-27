import asyncio
import re
import smtplib
from datetime import datetime, timedelta, timezone
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS, GMAIL_ADDRESS, GMAIL_APP_PASSWORD
from keyboards.kb import manager_menu_kb, back_cancel_kb
from utils.invoice_pdf import generate_invoice_pdf
from utils.sheets import (
    get_next_invoice_no,
    append_invoice,
    update_invoice_sent_via,
    _invoice_total,
    format_idr,
)

router = Router()
WITA = timezone(timedelta(hours=8))


class InvoiceForm(StatesGroup):
    client_type = State()
    client_name = State()
    client_address = State()
    client_npwp = State()
    client_contact = State()
    items = State()
    confirm = State()
    email_address = State()
    sent = State()


def is_manager(uid: int) -> bool:
    return uid in MANAGERS


def manager_kb(uid: int) -> ReplyKeyboardMarkup:
    return manager_menu_kb(is_superadmin=MANAGERS.get(uid, {}).get("superadmin", False))


def client_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👤 Individual"), KeyboardButton(text="🏢 Company")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def items_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Add more"), KeyboardButton(text="✅ Done")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def confirm_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Generate"), KeyboardButton(text="✏️ Edit")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def sent_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💾 Done"), KeyboardButton(text="📱 WhatsApp")],
            [KeyboardButton(text="📧 Email")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )


def _english_date(dt: datetime) -> str:
    return dt.strftime("%B %d, %Y")


def _parse_item_line(text: str) -> dict | None:
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        return None
    description = parts[0]
    try:
        rate = float(parts[1].replace(".", "").replace(",", "").strip())
    except ValueError:
        return None
    qty = 1.0
    if len(parts) >= 3 and parts[2].strip():
        try:
            qty = float(parts[2].strip())
        except ValueError:
            return None
    if not description or rate <= 0 or qty <= 0:
        return None
    return {"description": description, "rate": rate, "qty": qty}


def _items_summary(items: list) -> str:
    if not items:
        return "No items yet."
    lines = []
    for i, item in enumerate(items, 1):
        amount = float(item["rate"]) * float(item["qty"])
        lines.append(
            f"{i}. {item['description']}\n"
            f"   {_fmt_qty(item['qty'])} × {format_idr(int(item['rate']))} = {format_idr(int(amount))}"
        )
    return "\n".join(lines)


def _fmt_qty(qty) -> str:
    q = float(qty)
    return str(int(q)) if q == int(q) else str(q)


def _build_confirm_text(data: dict) -> str:
    client_type = data.get("client_type", "individual")
    type_label = "Individual" if client_type == "individual" else "Company"
    lines = [
        "🧾 <b>Invoice preview</b>\n",
        f"👤 Type: {type_label}",
        f"📛 Name: {data.get('client_name', '—')}",
    ]
    if client_type == "company":
        lines.append(f"📍 Address: {data.get('client_address', '—')}")
        lines.append(f"🆔 NPWP: {data.get('client_npwp', '—')}")
    lines.append(f"📞 Contact: {data.get('client_contact', '—')}")
    lines.append(f"\n<b>Items:</b>\n{_items_summary(data.get('items', []))}")
    total = _invoice_total(data.get("items", []))
    lines.append(f"\n<b>Total:</b> {format_idr(total)}")
    return "\n".join(lines)


async def _cancel_invoice(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    await message.answer("Cancelled.", reply_markup=manager_kb(uid))


async def _send_invoice_email(to_addr: str, pdf_path: str, invoice_no: str, client_name: str):
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD is not configured on the server.")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = f"Invoice {invoice_no} — Ride & Joy Motoschool"
    msg.attach(MIMEText(
        f"Dear {client_name},\n\n"
        f"Please find attached invoice {invoice_no} from Ride & Joy Motoschool Bali.\n\n"
        "Thank you.\n\nRide & Joy Motoschool\nrjbali.com",
        "plain",
    ))

    with open(pdf_path, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="invoice_{invoice_no}.pdf"')
    msg.attach(part)

    def _send():
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send)


def _whatsapp_url(contact: str, invoice_no: str) -> str | None:
    digits = re.sub(r"\D", "", contact or "")
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif not digits.startswith("62"):
        digits = "62" + digits
    text = f"Hello! Here is your invoice {invoice_no} from Ride & Joy Motoschool Bali."
    return f"https://wa.me/{digits}?text={quote(text)}"


@router.message(F.text == "🧾 Invoice")
async def invoice_start(message: Message, state: FSMContext):
    uid = message.from_user.id
    if not is_manager(uid):
        return
    await state.clear()
    await state.set_state(InvoiceForm.client_type)
    await message.answer(
        "🧾 <b>New invoice</b>\n\nSelect client type:",
        reply_markup=client_type_kb(),
        parse_mode="HTML",
    )


@router.message(InvoiceForm.client_type, F.text == "❌ Cancel")
@router.message(InvoiceForm.client_name, F.text == "❌ Cancel")
@router.message(InvoiceForm.client_address, F.text == "❌ Cancel")
@router.message(InvoiceForm.client_npwp, F.text == "❌ Cancel")
@router.message(InvoiceForm.client_contact, F.text == "❌ Cancel")
@router.message(InvoiceForm.items, F.text == "❌ Cancel")
@router.message(InvoiceForm.confirm, F.text == "❌ Cancel")
@router.message(InvoiceForm.email_address, F.text == "❌ Cancel")
@router.message(InvoiceForm.sent, F.text == "❌ Cancel")
async def invoice_cancel(message: Message, state: FSMContext):
    await _cancel_invoice(message, state)


@router.message(InvoiceForm.client_type, F.text == "⬅️ Back")
async def invoice_back_from_type(message: Message, state: FSMContext):
    await _cancel_invoice(message, state)


@router.message(InvoiceForm.client_type, F.text.in_({"👤 Individual", "🏢 Company"}))
async def invoice_client_type(message: Message, state: FSMContext):
    client_type = "individual" if message.text == "👤 Individual" else "company"
    await state.update_data(client_type=client_type, items=[])
    await state.set_state(InvoiceForm.client_name)
    label = "client name" if client_type == "individual" else "company name"
    await message.answer(f"Enter {label}:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_type)
async def invoice_client_type_invalid(message: Message):
    await message.answer("Choose 👤 Individual or 🏢 Company.", reply_markup=client_type_kb())


@router.message(InvoiceForm.client_name, F.text == "⬅️ Back")
async def invoice_back_from_name(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.client_type)
    await message.answer("Select client type:", reply_markup=client_type_kb())


@router.message(InvoiceForm.client_name)
async def invoice_client_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name:
        await message.answer("Please enter a name.", reply_markup=back_cancel_kb())
        return
    await state.update_data(client_name=name)
    data = await state.get_data()
    if data.get("client_type") == "company":
        await state.set_state(InvoiceForm.client_address)
        await message.answer("Enter company address:", reply_markup=back_cancel_kb())
    else:
        await state.set_state(InvoiceForm.client_contact)
        await message.answer("Enter contact (phone or @username):", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_address, F.text == "⬅️ Back")
async def invoice_back_from_address(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.client_name)
    await message.answer("Enter company name:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_address)
async def invoice_client_address(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if not address:
        await message.answer("Please enter an address.", reply_markup=back_cancel_kb())
        return
    await state.update_data(client_address=address)
    await state.set_state(InvoiceForm.client_npwp)
    await message.answer("Enter NPWP:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_npwp, F.text == "⬅️ Back")
async def invoice_back_from_npwp(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.client_address)
    await message.answer("Enter company address:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_npwp)
async def invoice_client_npwp(message: Message, state: FSMContext):
    npwp = (message.text or "").strip()
    if not npwp:
        await message.answer("Please enter NPWP.", reply_markup=back_cancel_kb())
        return
    await state.update_data(client_npwp=npwp)
    await state.set_state(InvoiceForm.client_contact)
    await message.answer("Enter phone or contact:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_contact, F.text == "⬅️ Back")
async def invoice_back_from_contact(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("client_type") == "company":
        await state.set_state(InvoiceForm.client_npwp)
        await message.answer("Enter NPWP:", reply_markup=back_cancel_kb())
    else:
        await state.set_state(InvoiceForm.client_name)
        await message.answer("Enter client name:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.client_contact)
async def invoice_client_contact(message: Message, state: FSMContext):
    contact = (message.text or "").strip()
    if not contact:
        await message.answer("Please enter contact info.", reply_markup=back_cancel_kb())
        return
    await state.update_data(client_contact=contact)
    await state.set_state(InvoiceForm.items)
    await message.answer(
        "Add item. Format:\n"
        "<code>Description | Price | Quantity</code>\n"
        "Example:\n"
        "<code>Rent Yamaha Nmax May 1-7 | 500000 | 1</code>",
        reply_markup=back_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(InvoiceForm.items, F.text == "⬅️ Back")
async def invoice_back_from_items(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.client_contact)
    await message.answer("Enter phone or contact:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.items, F.text == "✅ Done")
async def invoice_items_done(message: Message, state: FSMContext):
    data = await state.get_data()
    if not data.get("items"):
        await message.answer("Add at least one item first.", reply_markup=items_kb())
        return
    await state.set_state(InvoiceForm.confirm)
    await message.answer(_build_confirm_text(data), reply_markup=confirm_kb(), parse_mode="HTML")


@router.message(InvoiceForm.items, F.text == "➕ Add more")
async def invoice_items_add_more(message: Message):
    await message.answer(
        "Send next item:\n"
        "<code>Description | Price | Quantity</code>",
        reply_markup=back_cancel_kb(),
        parse_mode="HTML",
    )


@router.message(InvoiceForm.items)
async def invoice_add_item(message: Message, state: FSMContext):
    item = _parse_item_line(message.text or "")
    if not item:
        await message.answer(
            "Invalid format. Use:\n"
            "<code>Description | Price | Quantity</code>",
            reply_markup=back_cancel_kb(),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    items = list(data.get("items") or [])
    items.append(item)
    await state.update_data(items=items)
    await message.answer(
        f"✅ Added.\n\n<b>Items:</b>\n{_items_summary(items)}",
        reply_markup=items_kb(),
        parse_mode="HTML",
    )


@router.message(InvoiceForm.confirm, F.text == "⬅️ Back")
async def invoice_back_from_confirm(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.items)
    data = await state.get_data()
    await message.answer(
        f"<b>Items:</b>\n{_items_summary(data.get('items', []))}\n\n"
        "Add item or tap ✅ Done.",
        reply_markup=items_kb(),
        parse_mode="HTML",
    )


@router.message(InvoiceForm.confirm, F.text == "✏️ Edit")
async def invoice_edit(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.client_type)
    await message.answer("Select client type:", reply_markup=client_type_kb())


@router.message(InvoiceForm.confirm, F.text == "✅ Generate")
async def invoice_generate(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    now = datetime.now(WITA)
    invoice_no = await get_next_invoice_no()
    date_str = _english_date(now)
    due_str = _english_date(now + timedelta(days=3))
    created_by = MANAGERS.get(uid, {}).get("name", "Manager")
    total = _invoice_total(data.get("items", []))

    pdf_data = {
        "invoice_no": invoice_no,
        "date": date_str,
        "due_date": due_str,
        "client_type": data.get("client_type", "individual"),
        "client_name": data.get("client_name", ""),
        "client_contact": data.get("client_contact", ""),
        "client_address": data.get("client_address", ""),
        "client_npwp": data.get("client_npwp", ""),
        "items": data.get("items", []),
        "created_by": created_by,
    }

    try:
        pdf_path = await generate_invoice_pdf(pdf_data)
        await append_invoice(
            invoice_no=invoice_no,
            date_str=date_str,
            client_type=data.get("client_type", "individual"),
            client_name=data.get("client_name", ""),
            contact=data.get("client_contact", ""),
            items=data.get("items", []),
            total=total,
            sent_via="Telegram",
            created_by=created_by,
        )
    except Exception as e:
        await message.answer(f"❌ Failed to generate invoice: {e}", reply_markup=manager_kb(uid))
        await state.clear()
        return

    await state.update_data(
        invoice_no=invoice_no,
        pdf_path=pdf_path,
        date_str=date_str,
        total=total,
        created_by=created_by,
    )
    await state.set_state(InvoiceForm.sent)

    await message.answer_document(
        FSInputFile(pdf_path, filename=f"invoice_{invoice_no}.pdf"),
        caption=f"✅ Invoice <b>{invoice_no}</b> — {format_idr(total)}",
        parse_mode="HTML",
    )
    await message.answer("Send to client or finish:", reply_markup=sent_kb())


@router.message(InvoiceForm.confirm)
async def invoice_confirm_invalid(message: Message):
    await message.answer("Choose ✅ Generate, ✏️ Edit, ⬅️ Back or ❌ Cancel.", reply_markup=confirm_kb())


@router.message(InvoiceForm.sent, F.text == "💾 Done")
async def invoice_done(message: Message, state: FSMContext):
    uid = message.from_user.id
    data = await state.get_data()
    invoice_no = data.get("invoice_no")
    if invoice_no:
        await update_invoice_sent_via(invoice_no, "Telegram")
    await state.clear()
    await message.answer("✅ Invoice saved.", reply_markup=manager_kb(uid))


@router.message(InvoiceForm.sent, F.text == "📱 WhatsApp")
async def invoice_whatsapp(message: Message, state: FSMContext):
    data = await state.get_data()
    url = _whatsapp_url(data.get("client_contact", ""), data.get("invoice_no", ""))
    if not url:
        await message.answer(
            "Could not build WhatsApp link from contact. Share the PDF manually.",
            reply_markup=sent_kb(),
        )
        return
    invoice_no = data.get("invoice_no")
    if invoice_no:
        await update_invoice_sent_via(invoice_no, "WhatsApp")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Open WhatsApp", url=url)],
    ])
    await message.answer(
        "📱 Share invoice via WhatsApp:",
        reply_markup=kb,
    )
    await message.answer("PDF is already in this chat.", reply_markup=sent_kb())


@router.message(InvoiceForm.sent, F.text == "📧 Email")
async def invoice_email_start(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.email_address)
    await message.answer("Enter recipient email address:", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.email_address, F.text == "⬅️ Back")
async def invoice_email_back(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.sent)
    await message.answer("Send to client or finish:", reply_markup=sent_kb())


@router.message(InvoiceForm.email_address)
async def invoice_email_send(message: Message, state: FSMContext):
    uid = message.from_user.id
    to_addr = (message.text or "").strip()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", to_addr):
        await message.answer("Invalid email. Try again:", reply_markup=back_cancel_kb())
        return

    data = await state.get_data()
    pdf_path = data.get("pdf_path")
    invoice_no = data.get("invoice_no", "")
    if not pdf_path or not Path(pdf_path).is_file():
        await message.answer("PDF not found. Generate again.", reply_markup=manager_kb(uid))
        await state.clear()
        return

    try:
        await _send_invoice_email(
            to_addr,
            pdf_path,
            invoice_no,
            data.get("client_name", "Client"),
        )
        await update_invoice_sent_via(invoice_no, f"Email ({to_addr})")
        await state.set_state(InvoiceForm.sent)
        await message.answer(f"✅ Invoice sent to {to_addr}.", reply_markup=sent_kb())
    except Exception as e:
        await message.answer(f"❌ Email failed: {e}", reply_markup=back_cancel_kb())


@router.message(InvoiceForm.sent, F.text == "⬅️ Back")
async def invoice_sent_back(message: Message, state: FSMContext):
    await state.set_state(InvoiceForm.confirm)
    data = await state.get_data()
    await message.answer(_build_confirm_text(data), reply_markup=confirm_kb(), parse_mode="HTML")

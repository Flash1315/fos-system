"""Generate luxury-style client invoices as PDF (ReportLab)."""
import asyncio
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Project root (Mac: …/RJ-Spending-bot; server: /root/rjbot)
ROOT = Path(__file__).resolve().parent.parent
# Assets: /root/rjbot/assets/logo.png, /root/rjbot/assets/qris.png
LOGO_PATH = ROOT / "assets" / "logo.png"
QRIS_PATH = ROOT / "assets" / "qris.png"

# Brand colours
BLACK = "#000000"
WHITE = "#ffffff"
ORANGE = "#f66000"
GRAY = "#cacaca"
BG_LIGHT = "#fafafa"
DIVIDER = "#e8e8e8"
ROW_DIVIDER = "#f0f0f0"

MARGIN = 40
BOTTOM_BAR_H = 32
LOGO_HEIGHT = 50
QR_SIZE = 72

COMPANY_LINES = [
    "Jl. Sedap Malam Gg. Titi Batu No.88, Sumerta Kelod, Denpasar, Bali 80237",
    "ptrideandjoy@gmail.com · +6287778981036",
]
PAYMENT_BANK = "Permata Bank"
PAYMENT_NAME = "PT. Ride And Joy"
PAYMENT_ACCOUNT = "1237842770"


def _hex(code: str):
    from reportlab.lib import colors
    return colors.HexColor(code)


def _fmt_idr(amount) -> str:
    try:
        n = int(round(float(amount)))
        s = f"{n:,}".replace(",", ".")
        return f"IDR {s}"
    except (TypeError, ValueError):
        return f"IDR {amount}"


def _fmt_rate(amount) -> str:
    try:
        n = int(round(float(amount)))
        return f"{n:,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(amount)


def _draw_spaced_text(c: canvas.Canvas, x: float, y: float, text: str, font: str, size: float, color: str, spacing: float = 1.8):
    c.setFillColor(_hex(color))
    c.setFont(font, size)
    cx = x
    for ch in text:
        c.drawString(cx, y, ch)
        cx += c.stringWidth(ch, font, size) + spacing


def _draw_header(c: canvas.Canvas, w: float, top: float, data: dict) -> float:
    left = MARGIN
    right = w - MARGIN
    y = top

    if LOGO_PATH.is_file():
        c.drawImage(
            ImageReader(str(LOGO_PATH)),
            left, y - LOGO_HEIGHT,
            width=140, height=LOGO_HEIGHT,
            preserveAspectRatio=True, mask="auto",
        )
        brand_bottom = y - LOGO_HEIGHT - 6
    else:
        _draw_spaced_text(c, left, y - 18, "RIDE & JOY", "Helvetica-Bold", 22, BLACK, 2.2)
        brand_bottom = y - 24

    _draw_spaced_text(c, left, brand_bottom - 14, "MOTOSCHOOL BALI", "Helvetica", 7.5, GRAY, 1.4)

    cy = brand_bottom - 28
    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 7.5)
    for line in COMPANY_LINES:
        c.drawString(left, cy, line)
        cy -= 11

    c.setFillColor(_hex(DIVIDER))
    c.setFont("Helvetica-Bold", 42)
    c.drawRightString(right, y - 8, "INVOICE")

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 7)
    c.drawRightString(right, y - 28, "NO")

    c.setFillColor(_hex(ORANGE))
    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(right, y - 44, data.get("invoice_no", "—"))

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 8)
    c.drawRightString(right, y - 58, f"Date  {data.get('date', '—')}")
    c.drawRightString(right, y - 70, f"Due   {data.get('due_date', '—')}")

    line_y = min(cy, y - 78) - 12
    c.setStrokeColor(_hex(DIVIDER))
    c.setLineWidth(0.75)
    c.line(left, line_y, right, line_y)
    return line_y - 18


def _draw_client_block(c: canvas.Canvas, w: float, y: float, data: dict) -> float:
    left = MARGIN
    right = w - MARGIN
    block_h = 78 if data.get("client_type") == "company" else 58
    bottom = y - block_h

    c.setFillColor(_hex(BG_LIGHT))
    c.rect(left, bottom, right - left, block_h, fill=1, stroke=0)
    c.setStrokeColor(_hex(DIVIDER))
    c.setLineWidth(0.5)
    c.line(left, y, right, y)
    c.line(left, bottom, right, bottom)

    ty = y - 16
    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 7)
    c.drawString(left + 12, ty, "BILLED TO")

    c.setFillColor(_hex(BLACK))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(left + 12, ty - 16, data.get("client_name", "—"))

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 8)
    ty -= 32
    if data.get("client_contact"):
        c.drawString(left + 12, ty, data["client_contact"])
        ty -= 12
    if data.get("client_type") == "company":
        if data.get("client_address"):
            c.drawString(left + 12, ty, data["client_address"])
            ty -= 12
        if data.get("client_npwp"):
            c.drawString(left + 12, ty, f"NPWP  {data['client_npwp']}")

    return bottom - 22


def _draw_items_table(c: canvas.Canvas, w: float, y: float, data: dict) -> float:
    left = MARGIN
    right = w - MARGIN
    col_rate = right - 170
    col_qty = right - 110
    col_amt = right

    c.setFillColor(_hex(BLACK))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(left, y, "DESCRIPTION")
    c.drawRightString(col_rate, y, "RATE")
    c.drawRightString(col_qty, y, "QTY")
    c.drawRightString(col_amt, y, "AMOUNT")

    c.setStrokeColor(_hex(BLACK))
    c.setLineWidth(1.5)
    c.line(left, y - 6, right, y - 6)

    items = data.get("items") or []
    subtotal = 0
    row_y = y - 22
    c.setFont("Helvetica", 9)
    for item in items:
        rate = float(item.get("rate", 0))
        qty = float(item.get("qty", 1))
        amount = rate * qty
        subtotal += amount

        c.setFillColor(_hex(BLACK))
        desc = str(item.get("description", ""))
        c.drawString(left, row_y, desc[:70])

        c.setFillColor(_hex(GRAY))
        c.drawRightString(col_rate, row_y, _fmt_rate(rate))
        c.drawRightString(col_qty, row_y, str(int(qty) if qty == int(qty) else qty))
        c.drawRightString(col_amt, row_y, _fmt_rate(amount))

        row_y -= 18
        c.setStrokeColor(_hex(ROW_DIVIDER))
        c.setLineWidth(0.5)
        c.line(left, row_y + 8, right, row_y + 8)

    totals_x = right - 160
    totals_y = row_y - 8

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 9)
    c.drawRightString(col_amt, totals_y, _fmt_idr(subtotal))
    c.drawRightString(totals_x, totals_y, "Subtotal")

    c.setStrokeColor(_hex(BLACK))
    c.setLineWidth(1.5)
    c.line(totals_x - 10, totals_y - 10, col_amt, totals_y - 10)

    total_y = totals_y - 28
    c.setFillColor(_hex(BLACK))
    c.setFont("Helvetica-Bold", 8)
    c.drawRightString(totals_x + 30, total_y + 4, "TOTAL IDR")

    c.setFillColor(_hex(ORANGE))
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(col_amt, total_y, _fmt_rate(subtotal))

    return total_y - 36


def _draw_footer(c: canvas.Canvas, w: float, y: float) -> float:
    left = MARGIN
    right = w - MARGIN

    c.setStrokeColor(_hex(DIVIDER))
    c.setLineWidth(0.75)
    c.line(left, y, right, y)

    fy = y - 18
    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 7)
    c.drawString(left, fy, "PAYMENT DETAILS")

    c.setFillColor(_hex(BLACK))
    c.setFont("Helvetica", 9)
    c.drawString(left, fy - 14, PAYMENT_BANK)
    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 8)
    c.drawString(left, fy - 26, PAYMENT_NAME)
    c.drawString(left, fy - 38, PAYMENT_ACCOUNT)

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 7)
    c.drawRightString(right, fy, "SCAN TO PAY")

    qr_top = fy - 6
    if QRIS_PATH.is_file():
        c.drawImage(
            ImageReader(str(QRIS_PATH)),
            right - QR_SIZE, qr_top - QR_SIZE,
            width=QR_SIZE, height=QR_SIZE,
            preserveAspectRatio=True, mask="auto",
        )
        return qr_top - QR_SIZE - 14

    c.setStrokeColor(_hex(DIVIDER))
    c.setLineWidth(0.75)
    c.rect(right - QR_SIZE, qr_top - QR_SIZE, QR_SIZE, QR_SIZE, fill=0, stroke=1)
    return qr_top - QR_SIZE - 14


def _draw_bottom_bar(c: canvas.Canvas, w: float):
    c.setFillColor(_hex(BLACK))
    c.rect(0, 0, w, BOTTOM_BAR_H, fill=1, stroke=0)

    c.setFillColor(_hex(WHITE))
    _draw_spaced_text(c, MARGIN, 10, "RIDE & JOY MOTOSCHOOL", "Helvetica-Bold", 7.5, WHITE, 1.2)

    c.setFillColor(_hex(GRAY))
    c.setFont("Helvetica", 8)
    c.drawRightString(w - MARGIN, 11, "rjbali.com")


def _generate_invoice_pdf_sync(data: dict) -> str:
    invoice_no = data.get("invoice_no", "draft")
    out_path = f"/tmp/invoice_{invoice_no}.pdf"

    w, h = A4
    c = canvas.Canvas(out_path, pagesize=A4)
    c.setTitle(f"Invoice {invoice_no}")

    content_bottom = BOTTOM_BAR_H + 24
    y = h - MARGIN

    y = _draw_header(c, w, y, data)
    y = _draw_client_block(c, w, y, data)
    y = _draw_items_table(c, w, y, data)

    footer_y = max(y, content_bottom + 90)
    _draw_footer(c, w, footer_y)
    _draw_bottom_bar(c, w)

    c.save()
    return out_path


async def generate_invoice_pdf(data: dict) -> str:
    """Build invoice PDF and return file path, e.g. /tmp/invoice_260525-02.pdf."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _generate_invoice_pdf_sync, data)

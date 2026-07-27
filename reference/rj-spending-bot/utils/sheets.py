import gspread
import asyncio
from functools import partial
import asyncio
from datetime import datetime
from google.oauth2.service_account import Credentials
from functools import partial

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_EXPENSES = "Expenses"
SHEET_INCOME   = "Income"
SHEET_PAYOUTS  = "Payouts"
SHEET_RENTALS = "Rentals"
SHEET_BIKE_CHECKLIST = "Bike Checklist"
SHEET_BIKE_ISSUES = "Bike Issues"
SHEET_INVOICES = "Invoices"

INVOICE_HEADERS = [
    "Invoice No", "Date", "Client type", "Client name", "Contact",
    "Items", "Total (IDR)", "Sent via", "Created by",
]
INV_COL_NO = 0
INV_COL_DATE = 1
INV_COL_CLIENT_TYPE = 2
INV_COL_CLIENT_NAME = 3
INV_COL_CONTACT = 4
INV_COL_ITEMS = 5
INV_COL_TOTAL = 6
INV_COL_SENT_VIA = 7
INV_COL_CREATED_BY = 8

EXPENSE_HEADERS = [
    "Date", "Time", "Category", "Purpose", "Rental ID", "Place", "Amount (IDR)", "Mileage (km)", "GPS Mileage",
    "Receipt", "Item photo", "Employee", "Comment", "Payment Source",
    "TG Message ID", "Group Chat ID",
]
# Expenses column indices (0-based)
EXP_COL_DATE = 0
EXP_COL_TIME = 1
EXP_COL_CATEGORY = 2
EXP_COL_PURPOSE = 3
EXP_COL_RENTAL_ID = 4
EXP_COL_PLACE = 5
EXP_COL_AMOUNT = 6
EXP_COL_MILEAGE = 7
EXP_COL_GPS_MILEAGE = 8
EXP_COL_RECEIPT = 9
EXP_COL_ITEM_PHOTO = 10
EXP_COL_EMPLOYEE = 11
EXP_COL_COMMENT = 12
EXP_COL_PAYMENT_SOURCE = 13
EXP_COL_TG_MSG_ID = 14
EXP_COL_GROUP_CHAT_ID = 15
# 1-based column numbers for gspread update_cell
EXP_CELL_GPS_MILEAGE = EXP_COL_GPS_MILEAGE + 1
EXP_CELL_RECEIPT = EXP_COL_RECEIPT + 1
EXP_CELL_ITEM_PHOTO = EXP_COL_ITEM_PHOTO + 1
EXP_CELL_TG_MSG_ID = EXP_COL_TG_MSG_ID + 1
EXP_CELL_GROUP_CHAT_ID = EXP_COL_GROUP_CHAT_ID + 1

ODOMETER_CATEGORIES = ("Bensin", "Bike service", "Tires pressure / Wheel repair")
INCOME_HEADERS = [
    "Date", "Time", "Category", "Purpose", "Rental ID", "Client name", "No. of lessons",
    "Amount (IDR)", "Employee", "Comment", "Photo", "TG Message ID", "Cash / Transfer",
]
INC_COL_DATE = 0
INC_COL_TIME = 1
INC_COL_CATEGORY = 2
INC_COL_PURPOSE = 3
INC_COL_RENTAL_ID = 4
INC_COL_CLIENT = 5
INC_COL_LESSONS = 6
INC_COL_AMOUNT = 7
INC_COL_EMPLOYEE = 8
INC_COL_COMMENT = 9
INC_COL_PHOTO = 10
INC_COL_TG_MSG_ID = 11
INC_COL_PAYMENT_TYPE = 12
INC_CELL_PHOTO = INC_COL_PHOTO + 1

RENTAL_HEADERS = [
    "Rental ID", "Date booked", "Added by", "Bike", "Status", "Source", "Client name",
    "Passport (link)", "Contact platform", "Contact info", "Delivery date", "Delivery time",
    "Return date", "Duration (days)", "Instructor", "Location", "Helmets", "Insurance",
    "Insurance cost", "Rental price", "Extra charges", "Total", "Payment method",
    "Odometer out", "Fuel out", "Odometer in", "Fuel in", "Video out (link)", "Video in (link)",
    "Damages", "Damage photos (links)", "Comment", "TG Message ID",
]
RENT_COL_ID = 0
RENT_COL_DATE_BOOKED = 1
RENT_COL_ADDED_BY = 2
RENT_COL_BIKE = 3
RENT_COL_STATUS = 4
RENT_COL_SOURCE = 5
RENT_COL_CLIENT = 6
RENT_COL_PASSPORT = 7
RENT_COL_CONTACT_PLATFORM = 8
RENT_COL_CONTACT_INFO = 9
RENT_COL_DELIVERY_DATE = 10
RENT_COL_DELIVERY_TIME = 11
RENT_COL_RETURN_DATE = 12
RENT_COL_DURATION = 13
RENT_COL_INSTRUCTOR = 14
RENT_COL_LOCATION = 15
RENT_COL_HELMETS = 16
RENT_COL_INSURANCE = 17
RENT_COL_INSURANCE_COST = 18
RENT_COL_RENTAL_PRICE = 19
RENT_COL_EXTRA_CHARGES = 20
RENT_COL_TOTAL = 21
RENT_COL_PAYMENT_METHOD = 22
RENT_COL_ODOMETER_OUT = 23
RENT_COL_FUEL_OUT = 24
RENT_COL_ODOMETER_IN = 25
RENT_COL_FUEL_IN = 26
RENT_COL_VIDEO_OUT = 27
RENT_COL_VIDEO_IN = 28
RENT_COL_DAMAGES = 29
RENT_COL_DAMAGE_PHOTOS = 30
RENT_COL_COMMENT = 31
RENT_COL_TG_MSG_ID = 32

CHECKLIST_HEADERS = [
    "Date", "Time", "Rental ID", "Bike", "Type", "Phone holder", "Phone charger",
    "First aid kit", "Bike papers", "Adjuster", "Helmets count", "Odometer", "Fuel bar",
    "Photo (link)", "Instructor", "Notes",
]
CHK_COL_DATE = 0
CHK_COL_TIME = 1
CHK_COL_RENTAL_ID = 2
CHK_COL_BIKE = 3
CHK_COL_TYPE = 4
CHK_COL_PHONE_HOLDER = 5
CHK_COL_PHONE_CHARGER = 6
CHK_COL_FIRST_AID = 7
CHK_COL_BIKE_PAPERS = 8
CHK_COL_ADJUSTER = 9
CHK_COL_HELMETS_COUNT = 10
CHK_COL_ODOMETER = 11
CHK_COL_FUEL_BAR = 12
CHK_COL_PHOTO = 13
CHK_COL_INSTRUCTOR = 14
CHK_COL_NOTES = 15

ISSUE_HEADERS = [
    "Date", "Time", "Bike", "Reported by", "Description", "Photos (links)",
    "Status", "Resolved date", "Comment",
]
ISS_COL_DATE = 0
ISS_COL_TIME = 1
ISS_COL_BIKE = 2
ISS_COL_REPORTED_BY = 3
ISS_COL_DESCRIPTION = 4
ISS_COL_PHOTOS = 5
ISS_COL_STATUS = 6
ISS_COL_RESOLVED_DATE = 7
ISS_COL_COMMENT = 8
PAYOUT_HEADERS  = ["Date", "Time", "Type", "Employee", "Amount (IDR)", "Cash / Transfer"]
PAYOUT_COL_DATE = 0
PAYOUT_COL_TYPE = 2
PAYOUT_COL_EMPLOYEE = 3
PAYOUT_COL_AMOUNT = 4
PAYOUT_COL_OVERPAYMENT = 6

_client = None
_spreadsheet = None
_sheet_cache = {}

def get_client():
    global _client
    if _client is None:
        from config import GOOGLE_CREDENTIALS_FILE
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
        _client = gspread.authorize(creds)
    return _client

def get_spreadsheet():
    global _spreadsheet
    if _spreadsheet is None:
        from config import SPREADSHEET_ID
        _spreadsheet = get_client().open_by_key(SPREADSHEET_ID)
    return _spreadsheet

def get_sheet(name):
    global _sheet_cache
    if name not in _sheet_cache:
        _sheet_cache[name] = get_spreadsheet().worksheet(name)
    return _sheet_cache[name]

def reset_sheet_cache():
    global _client, _spreadsheet, _sheet_cache
    _client = None
    _spreadsheet = None
    _sheet_cache = {}


def _row_has_header(ws, header_name: str) -> bool:
    """True if header_name is in row 1 or any Date-header row in the sheet."""
    try:
        if header_name in ws.row_values(1):
            return True
    except Exception:
        pass
    for row in ws.get_all_values():
        if row and row[0] == "Date" and header_name in row:
            return True
    return False


def _sheet_needs_purpose_columns(ws):
    """True if sheet has Date/Category headers but no Purpose column yet."""
    if _row_has_header(ws, "Purpose"):
        return False
    rows = ws.get_all_values()
    for row in rows:
        if len(row) > 2 and row[0] == "Date" and row[2] == "Category":
            return True
    return False


def _insert_purpose_rental_columns(ws):
    """Insert Purpose and Rental ID columns after Category (shifts existing data right)."""
    if _row_has_header(ws, "Purpose"):
        print(f"Purpose column already present in {ws.title}, skipping insert")
        return
    rows = ws.get_all_values()
    if not rows:
        return
    insert_at = EXP_COL_PURPOSE + 1  # 1-based column index after Category
    purpose_vals = []
    rental_vals = []
    for row in rows:
        if len(row) > 2 and row[0] == "Date" and row[2] == "Category":
            purpose_vals.append("Purpose")
            rental_vals.append("Rental ID")
        else:
            purpose_vals.append("")
            rental_vals.append("")
    ws.insert_cols([purpose_vals, rental_vals], col=insert_at, value_input_option="USER_ENTERED")
    print(f"Inserted Purpose/Rental ID columns in {ws.title}")


def _income_needs_payment_type_column(ws):
    """True if Income header rows are missing the Cash / Transfer column."""
    if _row_has_header(ws, "Cash / Transfer"):
        return False
    rows = ws.get_all_values()
    for row in rows:
        if len(row) > 2 and row[0] == "Date" and row[1] == "Time" and row[2] == "Category":
            return True
    return False


def _append_income_payment_type_column(ws):
    """Add Cash / Transfer header to all Income column-header rows."""
    if _row_has_header(ws, "Cash / Transfer"):
        print(f"Cash / Transfer column already present in {ws.title}, skipping")
        return
    target_col = INC_COL_PAYMENT_TYPE + 1
    if ws.col_count < target_col:
        ws.add_cols(target_col - ws.col_count)
    rows = ws.get_all_values()
    for i, row in enumerate(rows):
        if len(row) > 2 and row[0] == "Date" and row[1] == "Time" and row[2] == "Category":
            if len(row) > INC_COL_PAYMENT_TYPE and row[INC_COL_PAYMENT_TYPE] == "Cash / Transfer":
                continue
            ws.update_cell(i + 1, target_col, "Cash / Transfer")
    print(f"Added Cash / Transfer column header in {ws.title}")


def setup_sheets():
    """Create rental sheets and migrate Expenses/Income column layout if needed."""
    try:
        spreadsheet = get_spreadsheet()
        existing = {ws.title for ws in spreadsheet.worksheets()}
        to_create = {
            SHEET_RENTALS: RENTAL_HEADERS,
            SHEET_BIKE_CHECKLIST: CHECKLIST_HEADERS,
            SHEET_BIKE_ISSUES: ISSUE_HEADERS,
            SHEET_INVOICES: INVOICE_HEADERS,
        }
        for title, headers in to_create.items():
            if title not in existing:
                ws = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
                ws.append_row(headers)
                print(f"Created sheet: {title}")

        for title in (SHEET_EXPENSES, SHEET_INCOME):
            if title not in existing:
                continue
            ws = get_sheet(title)
            if _sheet_needs_purpose_columns(ws):
                _insert_purpose_rental_columns(ws)
                reset_sheet_cache()
            if title == SHEET_INCOME and _income_needs_payment_type_column(ws):
                _append_income_payment_type_column(ws)
                reset_sheet_cache()
    except Exception as e:
        print(f"setup_sheets error: {e}")

def now_date():
    from datetime import timezone, timedelta
    wita = timezone(timedelta(hours=8))
    return datetime.now(wita).strftime("%d.%m.%Y")

def now_time():
    from datetime import timezone, timedelta
    wita = timezone(timedelta(hours=8))
    return datetime.now(wita).strftime("%H:%M")

def month_label(date_str):
    """Convert DD.MM.YYYY to 'April 2026'"""
    try:
        parts = date_str.split(".")
        d = datetime(int(parts[2]), int(parts[1]), int(parts[0]))
        return d.strftime("%B %Y").upper()
    except:
        return datetime.now().strftime("%B %Y").upper()

def get_last_month_label(ws, headers):
    """Find what month label was last written in this sheet."""
    all_vals = ws.get_all_values()
    for row in reversed(all_vals):
        if len(row) > 0 and row[0].startswith("═"):
            return row[0]
    return None

def ensure_month_header(ws, date_str, headers):
    """Add month header + column headers if new month started."""
    label = "═══ " + month_label(date_str) + " ═══"
    last = get_last_month_label(ws, headers)
    if last != label:
        if last is not None:
            add_monthly_total(ws, headers)
            ws.append_row([""] * len(headers))
        ws.append_row([label] + [""] * (len(headers) - 1))
        ws.append_row(headers)

def add_monthly_total(ws, headers):
    """Append a TOTAL row summing the Amount column for the current month."""
    all_vals = ws.get_all_values()
    amount_idx = headers.index("Amount (IDR)") if "Amount (IDR)" in headers else EXP_COL_AMOUNT
    total = 0
    for row in reversed(all_vals):
        if len(row) > 0 and row[0].startswith("═"):
            break
        if len(row) > amount_idx:
            try:
                val = str(row[amount_idx]).replace(".", "").replace(",", "").strip()
                total += int(float(val))
            except:
                pass
    total_row = [""] * len(headers)
    total_row[0] = "TOTAL"
    total_row[amount_idx] = format_idr(total)
    ws.append_row(total_row)


def update_expense_photos(date, time, employee, receipt_url, item_url):
    try:
        reset_sheet_cache()
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        def make_cell(url):
            if url:
                return '=HYPERLINK("' + url + '";IMAGE("' + url + '";4;60;60))'
            return ""
        for i, row in enumerate(rows):
            if len(row) > EXP_COL_EMPLOYEE and row[0] == date and row[1] == time and row[EXP_COL_EMPLOYEE] == employee:
                ws.update_cell(i + 1, EXP_CELL_RECEIPT, make_cell(receipt_url))
                ws.update_cell(i + 1, EXP_CELL_ITEM_PHOTO, make_cell(item_url))
                print(f"Updated photos for {employee} {date} {time}")
                return
    except Exception as e:
        print(f"update_expense_photos error: {e}")


def update_expense_tg_id(date, time, employee, tg_message_id, group_chat_id=""):
    """tg_message_id can be comma-separated list of IDs for media groups."""
    try:
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        for i, row in enumerate(rows):
            if len(row) > EXP_COL_EMPLOYEE and row[0] == date and row[1] == time and row[EXP_COL_EMPLOYEE] == employee:
                ws.update_cell(i + 1, EXP_CELL_TG_MSG_ID, str(tg_message_id))
                if group_chat_id:
                    ws.update_cell(i + 1, EXP_CELL_GROUP_CHAT_ID, group_chat_id)
                print(f"Updated TG ID for {employee} {date} {time}")
                return
    except Exception as e:
        print(f"update_expense_tg_id error: {e}")


def update_expense_gps_mileage(date, time, employee, gps_mileage):
    try:
        reset_sheet_cache()
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        for i, row in enumerate(rows):
            if len(row) > EXP_COL_EMPLOYEE and row[0] == date and row[1] == time and row[EXP_COL_EMPLOYEE] == employee:
                ws.update_cell(i + 1, EXP_CELL_GPS_MILEAGE, str(gps_mileage))
                print(f"Updated GPS mileage for {employee} {date} {time}: {gps_mileage}")
                return
    except Exception as e:
        print(f"update_expense_gps_mileage error: {e}")


def _append_expense_sync(date, time, category, place, amount, receipt_url, item_url, employee, comment="", payment_source="My pocket", tg_message_id="", group_chat_id="", mileage="", gps_mileage="", purpose="", rental_id=""):
    try:
        ws = get_sheet(SHEET_EXPENSES)
        ensure_month_header(ws, date, EXPENSE_HEADERS)
        receipt_cell = f'=HYPERLINK("{receipt_url}","receipt")' if receipt_url else ""
        item_cell = f'=HYPERLINK("{item_url}","photo")' if item_url else ""
        mileage_val = mileage if mileage not in ("", None) else ""
        gps_mileage_val = gps_mileage if gps_mileage not in ("", None) else ""
        ws.append_row([
            date, time, category, purpose, rental_id, place, amount, mileage_val, gps_mileage_val,
            receipt_cell, item_cell, employee, comment, payment_source,
            str(tg_message_id), str(group_chat_id),
        ], value_input_option="USER_ENTERED")
        invalidate_balance_cache()
    except Exception as e:
        reset_sheet_cache()
        raise e

def _append_income_sync(date, time, category, client_name, num_lessons, amount, employee, comment="", photo_url="", tg_message_id="", purpose="", rental_id="", payment_type=""):
    try:
        time = resolve_time_after_cutoff(
            employee, date, time, ("Income handover", "Transfer to colleague")
        )
        ws = get_sheet(SHEET_INCOME)
        ensure_month_header(ws, date, INCOME_HEADERS)
        photo_cell = '=HYPERLINK("' + photo_url + '","photo")' if photo_url else ""
        ws.append_row([
            date, time, category, purpose, rental_id, client_name, num_lessons, amount, employee,
            comment, photo_cell, str(tg_message_id), payment_type,
        ], value_input_option="USER_ENTERED")
        invalidate_balance_cache()
    except Exception as e:
        reset_sheet_cache()
        raise e

def _append_payout_sync(date, time, ptype, employee, amount, payment_type, overpayment=0, tg_message_id=""):
    try:
        ws = get_sheet(SHEET_PAYOUTS)
        ws.append_row([date, time, ptype, employee, amount, payment_type, overpayment, str(tg_message_id)], value_input_option="USER_ENTERED")
        invalidate_balance_cache()
    except Exception as e:
        reset_sheet_cache()
        raise e

async def append_expense(date, time, category, place, amount, receipt_url, item_url, employee, comment="", payment_source="My pocket", tg_message_id="", group_chat_id="", mileage="", gps_mileage="", purpose="", rental_id=""):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(_append_expense_sync, date, time, category, place, amount, receipt_url, item_url, employee, comment, payment_source, tg_message_id, group_chat_id, mileage, gps_mileage, purpose, rental_id),
    )

async def append_income(date, time, category, client_name, num_lessons, amount, employee, comment="", photo_url="", tg_message_id="", purpose="", rental_id="", payment_type=""):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(_append_income_sync, date, time, category, client_name, num_lessons, amount, employee, comment, photo_url, tg_message_id, purpose, rental_id, payment_type),
    )

async def append_payout(date, time, ptype, employee, amount, payment_type, overpayment=0, tg_message_id=""):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_append_payout_sync, date, time, ptype, employee, amount, payment_type, overpayment, tg_message_id))


def get_running_total_expenses(employee_name):
    try:
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        total = 0
        for row in rows:
            if len(row) > EXP_COL_EMPLOYEE and row[EXP_COL_EMPLOYEE] == employee_name:
                try:
                    val = str(row[EXP_COL_AMOUNT]).replace(".", "").replace(",", "").strip()
                    total += int(float(val))
                except:
                    pass
        return total
    except:
        return 0

def get_running_total_income(employee_name):
    try:
        ws = get_sheet(SHEET_INCOME)
        rows = ws.get_all_values()
        total = 0
        for row in rows:
            if len(row) > INC_COL_EMPLOYEE and row[INC_COL_EMPLOYEE] == employee_name:
                try:
                    val = str(row[INC_COL_AMOUNT]).replace(".", "").replace(",", "").strip()
                    total += int(float(val))
                except:
                    pass
        return total
    except:
        return 0

def parse_date(s):
    try:
        from datetime import datetime
        s = str(s).strip()
        if not s:
            return None
        date_part = s.split()[0]
        for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(date_part, fmt)
            except ValueError:
                continue
        return None
    except:
        return None


def _parse_row_datetime(date_str, time_str=""):
    """Combine sheet date + time columns into one datetime for ordering."""
    d = parse_date(date_str)
    if not d:
        return None
    t = str(time_str or "00:00").strip()
    try:
        parts = t.split(":")
        hour = int(parts[0]) if parts else 0
        minute = int(parts[1]) if len(parts) > 1 else 0
        return d.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, TypeError):
        return d


def resolve_time_after_cutoff(employee_name, date_str, time_str, payout_types):
    """
    Ensure a new income/expense row time is strictly after the latest payout/handover
    on the same calendar day (avoids same-day cutoff collisions).
    """
    from datetime import timedelta
    if isinstance(payout_types, str):
        payout_types = (payout_types,)
    try:
        payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()
    except Exception:
        return time_str
    cutoff_row = _find_last_payout_row(payout_rows, employee_name, payout_types)
    if not cutoff_row:
        return time_str
    cutoff_date = str(cutoff_row[PAYOUT_COL_DATE]).strip()
    if cutoff_date != str(date_str).strip():
        return time_str
    cut_dt = _parse_row_datetime(
        cutoff_row[PAYOUT_COL_DATE],
        cutoff_row[1] if len(cutoff_row) > 1 else "",
    )
    row_dt = _parse_row_datetime(date_str, time_str)
    if not cut_dt or not row_dt or row_dt > cut_dt:
        return time_str
    return (cut_dt + timedelta(minutes=1)).strftime("%H:%M")


def _is_sheet_data_row(row):
    if not row or not str(row[0]).strip():
        return False
    first = str(row[0]).strip()
    if first in ("Date", "TOTAL"):
        return False
    if first.startswith("═") or first.startswith("="):
        return False
    return True


def _row_after_cutoff(row, cutoff_row, date_col=0, time_col=1):
    """True when row timestamp is strictly after cutoff row timestamp."""
    if cutoff_row is None:
        return True
    row_dt = _parse_row_datetime(row[date_col] if len(row) > date_col else "", row[time_col] if len(row) > time_col else "")
    cut_dt = _parse_row_datetime(
        cutoff_row[PAYOUT_COL_DATE] if len(cutoff_row) > PAYOUT_COL_DATE else "",
        cutoff_row[1] if len(cutoff_row) > 1 else "",
    )
    if not row_dt or not cut_dt:
        return False
    return row_dt > cut_dt


def _parse_amount(val):
    try:
        cleaned = str(val).replace(".", "").replace(",", "").strip()
        if not cleaned:
            return None
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _expense_payment_source(row):
    return str(row[EXP_COL_PAYMENT_SOURCE]).strip() if len(row) > EXP_COL_PAYMENT_SOURCE else "My pocket"


def _find_nth_last_payout_row(payout_rows, employee_name, payout_types, n=1):
    if isinstance(payout_types, str):
        payout_types = (payout_types,)
    count = 0
    for row in reversed(payout_rows[1:]):
        if len(row) <= PAYOUT_COL_EMPLOYEE or not _is_sheet_data_row(row):
            continue
        if row[PAYOUT_COL_EMPLOYEE] != employee_name:
            continue
        if row[PAYOUT_COL_TYPE] not in payout_types:
            continue
        count += 1
        if count == n:
            return row
    return None


def _find_last_payout_row(payout_rows, employee_name, payout_types):
    return _find_nth_last_payout_row(payout_rows, employee_name, payout_types, n=1)


def _sum_employee_expenses_since(exp_rows, employee_name, cutoff_row, payment_source):
    total = 0
    for row in exp_rows:
        if len(row) <= EXP_COL_EMPLOYEE or row[EXP_COL_EMPLOYEE] != employee_name or not _is_sheet_data_row(row):
            continue
        if _expense_payment_source(row) != payment_source:
            continue
        if not _row_after_cutoff(row, cutoff_row):
            continue
        amount = _parse_amount(row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else "")
        if amount is not None:
            total += amount
    return total


def _sum_employee_income_since(inc_rows, employee_name, cutoff_row):
    total = 0
    for row in inc_rows:
        if len(row) <= INC_COL_EMPLOYEE or row[INC_COL_EMPLOYEE] != employee_name or not _is_sheet_data_row(row):
            continue
        if not _row_after_cutoff(row, cutoff_row):
            continue
        amount = _parse_amount(row[INC_COL_AMOUNT] if len(row) > INC_COL_AMOUNT else "")
        if amount is not None:
            total += amount
    return total


def _sum_payouts(payout_rows, employee_name, payout_types):
    if isinstance(payout_types, str):
        payout_types = (payout_types,)
    total = 0
    for row in payout_rows[1:]:
        if len(row) <= PAYOUT_COL_AMOUNT or not _is_sheet_data_row(row):
            continue
        if row[PAYOUT_COL_EMPLOYEE] != employee_name or row[PAYOUT_COL_TYPE] not in payout_types:
            continue
        amount = _parse_amount(row[PAYOUT_COL_AMOUNT])
        if amount is not None:
            total += amount
    return total


def _cutoff_label(cutoff_row):
    if not cutoff_row:
        return "—"
    dt = _parse_row_datetime(
        cutoff_row[PAYOUT_COL_DATE] if len(cutoff_row) > PAYOUT_COL_DATE else "",
        cutoff_row[1] if len(cutoff_row) > 1 else "",
    )
    if not dt:
        return str(cutoff_row[PAYOUT_COL_DATE] if len(cutoff_row) > PAYOUT_COL_DATE else "—")
    return dt.strftime("%d.%m.%Y %H:%M")


def get_rental_id_for_bike(bike_name: str) -> str:
    """Auto-match active/booked rental ID by bike name (latest first)."""
    if not bike_name or bike_name in ("Other", "Other (enter manually)"):
        return ""
    try:
        ws = get_sheet(SHEET_RENTALS)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"get_rental_id_for_bike error: {e}")
        return ""
    bike_lower = bike_name.lower().strip()
    for row in reversed(rows[1:]):
        if not row or row[0] in ("", "Rental ID"):
            continue
        if len(row) <= RENT_COL_STATUS:
            continue
        if str(row[RENT_COL_STATUS]).strip().lower() not in ("booked", "active"):
            continue
        row_bike = row[RENT_COL_BIKE] if len(row) > RENT_COL_BIKE else ""
        rb = row_bike.lower().strip()
        if not rb:
            continue
        if rb == bike_lower or rb in bike_lower or bike_lower in rb:
            return str(row[RENT_COL_ID]).strip()
    return ""


def get_rental_id_for_client(client_name: str) -> str:
    """Auto-match active/booked rental ID by client name (latest first)."""
    if not client_name:
        return ""
    try:
        ws = get_sheet(SHEET_RENTALS)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"get_rental_id_for_client error: {e}")
        return ""
    needle = client_name.lower().strip()
    for row in reversed(rows[1:]):
        if not row or row[0] in ("", "Rental ID"):
            continue
        if len(row) <= RENT_COL_STATUS:
            continue
        if str(row[RENT_COL_STATUS]).strip().lower() not in ("booked", "active"):
            continue
        client = row[RENT_COL_CLIENT] if len(row) > RENT_COL_CLIENT else ""
        cl = client.lower().strip()
        if not cl:
            continue
        if cl == needle or needle in cl or cl in needle:
            return str(row[RENT_COL_ID]).strip()
    return ""


def get_next_rental_id() -> str:
    """Return next Rental ID like R-2026-001."""
    from datetime import datetime
    year = datetime.now().year
    prefix = f"R-{year}-"
    try:
        ws = get_sheet(SHEET_RENTALS)
        rows = ws.get_all_values()
    except Exception as e:
        print(f"get_next_rental_id error: {e}")
        return f"{prefix}001"
    max_num = 0
    for row in rows[1:]:
        if not row:
            continue
        rid = str(row[RENT_COL_ID]).strip()
        if not rid.startswith(prefix):
            continue
        try:
            max_num = max(max_num, int(rid.rsplit("-", 1)[-1]))
        except ValueError:
            continue
    return f"{prefix}{max_num + 1:03d}"


def _append_rental_sync(data: dict):
    try:
        ws = get_sheet(SHEET_RENTALS)
        row = [""] * len(RENTAL_HEADERS)
        mapping = {
            RENT_COL_ID: "rental_id",
            RENT_COL_DATE_BOOKED: "date_booked",
            RENT_COL_ADDED_BY: "added_by",
            RENT_COL_BIKE: "bike",
            RENT_COL_STATUS: "status",
            RENT_COL_SOURCE: "source",
            RENT_COL_CLIENT: "client_name",
            RENT_COL_PASSPORT: "passport",
            RENT_COL_CONTACT_PLATFORM: "contact_platform",
            RENT_COL_CONTACT_INFO: "contact_info",
            RENT_COL_DELIVERY_DATE: "delivery_date",
            RENT_COL_DELIVERY_TIME: "delivery_time",
            RENT_COL_RETURN_DATE: "return_date",
            RENT_COL_DURATION: "duration_days",
            RENT_COL_INSTRUCTOR: "instructor",
            RENT_COL_LOCATION: "location",
            RENT_COL_HELMETS: "helmets",
            RENT_COL_INSURANCE: "insurance",
            RENT_COL_INSURANCE_COST: "insurance_cost",
            RENT_COL_RENTAL_PRICE: "rental_price",
            RENT_COL_EXTRA_CHARGES: "extra_charges",
            RENT_COL_TOTAL: "total",
            RENT_COL_PAYMENT_METHOD: "payment_method",
            RENT_COL_COMMENT: "comment",
            RENT_COL_TG_MSG_ID: "tg_message_id",
        }
        for col, key in mapping.items():
            row[col] = str(data.get(key, "") or "")
        ws.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        reset_sheet_cache()
        raise e


async def append_rental(data: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_append_rental_sync, data))


def _pad_rental_row(row):
    if len(row) < len(RENTAL_HEADERS):
        row = row + [""] * (len(RENTAL_HEADERS) - len(row))
    return row


def rental_row_to_dict(row):
    row = _pad_rental_row(list(row or []))
    keys = (
        "rental_id", "date_booked", "added_by", "bike", "status", "source", "client_name",
        "passport", "contact_platform", "contact_info", "delivery_date", "delivery_time",
        "return_date", "duration_days", "instructor", "location", "helmets", "insurance",
        "insurance_cost", "rental_price", "extra_charges", "total", "payment_method",
        "odometer_out", "fuel_out", "odometer_in", "fuel_in", "video_out", "video_in",
        "damages", "damage_photos", "comment", "tg_message_id",
    )
    data = {}
    for i, key in enumerate(keys):
        if i < len(row):
            data[key] = row[i]
    return data


def _find_rental_sheet_row(rental_id: str):
    ws = get_sheet(SHEET_RENTALS)
    for i, row in enumerate(ws.get_all_values()):
        if row and str(row[0]).strip() == str(rental_id).strip():
            return ws, i + 1, _pad_rental_row(row)
    return None, None, None


def get_booked_rentals_for_date(date_str: str = None):
    """Return booked rentals with delivery_date matching date_str (default today)."""
    date_str = date_str or now_date()
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_booked_rentals_for_date error: {e}")
        return []
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        if str(row[RENT_COL_STATUS]).strip().lower() != "booked":
            continue
        if str(row[RENT_COL_DELIVERY_DATE]).strip() != date_str:
            continue
        result.append(rental_row_to_dict(row))
    return result


def get_all_booked_rentals():
    """All rentals with status booked (any delivery date)."""
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_all_booked_rentals error: {e}")
        return []
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        if str(row[RENT_COL_STATUS]).strip().lower() != "booked":
            continue
        result.append(rental_row_to_dict(row))
    return result


def get_manager_active_rentals():
    """Return booked + active rentals for manager view."""
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_manager_active_rentals error: {e}")
        return []
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        status = str(row[RENT_COL_STATUS]).strip().lower()
        if status not in ("booked", "active"):
            continue
        result.append(rental_row_to_dict(row))
    result.sort(key=lambda r: (r.get("delivery_date") or "", r.get("delivery_time") or ""))
    return result


def get_active_rentals():
    """Return all rentals with status active."""
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_active_rentals error: {e}")
        return []
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        if str(row[RENT_COL_STATUS]).strip().lower() != "active":
            continue
        result.append(rental_row_to_dict(row))
    return result


def get_rental_by_id(rental_id: str):
    _, _, row = _find_rental_sheet_row(rental_id)
    if not row:
        return None
    return rental_row_to_dict(row)


RENTAL_HISTORY_STATUSES = frozenset({"returned", "completed", "cancelled", "closed"})
RENTAL_REVENUE_STATUSES = frozenset({"returned", "completed", "closed"})


def _rental_reference_date(rental: dict):
    for key in ("return_date", "delivery_date", "date_booked"):
        d = parse_date(rental.get(key, ""))
        if d:
            return d
    return None


def get_rental_history(days: int = 30):
    """Return completed/returned rentals, optionally within last N days (0 = all)."""
    from datetime import datetime, timedelta
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_rental_history error: {e}")
        return []
    cutoff = None
    if days and days > 0:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        status = str(row[RENT_COL_STATUS]).strip().lower()
        if status not in RENTAL_HISTORY_STATUSES:
            continue
        rental = rental_row_to_dict(row)
        ref_dt = _rental_reference_date(rental)
        if cutoff:
            if not ref_dt or ref_dt < cutoff:
                continue
        rental["_sort_date"] = ref_dt or datetime.min
        result.append(rental)
    result.sort(key=lambda r: r.get("_sort_date") or datetime.min, reverse=True)
    for r in result:
        r.pop("_sort_date", None)
    return result


def get_checklists_for_rental(rental_id: str):
    if not rental_id:
        return []
    try:
        rows = get_sheet(SHEET_BIKE_CHECKLIST).get_all_values()[1:]
    except Exception as e:
        print(f"get_checklists_for_rental error: {e}")
        return []
    rid = str(rental_id).strip()
    result = []
    for row in rows:
        if len(row) <= CHK_COL_RENTAL_ID:
            continue
        if str(row[CHK_COL_RENTAL_ID]).strip() != rid:
            continue
        result.append({
            "date": row[CHK_COL_DATE] if len(row) > CHK_COL_DATE else "",
            "time": row[CHK_COL_TIME] if len(row) > CHK_COL_TIME else "",
            "type": row[CHK_COL_TYPE] if len(row) > CHK_COL_TYPE else "",
            "phone_holder": row[CHK_COL_PHONE_HOLDER] if len(row) > CHK_COL_PHONE_HOLDER else "",
            "phone_charger": row[CHK_COL_PHONE_CHARGER] if len(row) > CHK_COL_PHONE_CHARGER else "",
            "first_aid": row[CHK_COL_FIRST_AID] if len(row) > CHK_COL_FIRST_AID else "",
            "bike_papers": row[CHK_COL_BIKE_PAPERS] if len(row) > CHK_COL_BIKE_PAPERS else "",
            "adjuster": row[CHK_COL_ADJUSTER] if len(row) > CHK_COL_ADJUSTER else "",
            "helmets_count": row[CHK_COL_HELMETS_COUNT] if len(row) > CHK_COL_HELMETS_COUNT else "",
            "odometer": row[CHK_COL_ODOMETER] if len(row) > CHK_COL_ODOMETER else "",
            "fuel_bar": row[CHK_COL_FUEL_BAR] if len(row) > CHK_COL_FUEL_BAR else "",
            "photo": row[CHK_COL_PHOTO] if len(row) > CHK_COL_PHOTO else "",
            "instructor": row[CHK_COL_INSTRUCTOR] if len(row) > CHK_COL_INSTRUCTOR else "",
            "notes": row[CHK_COL_NOTES] if len(row) > CHK_COL_NOTES else "",
        })
    return result


def get_last_bike_checklist(bike_name: str):
    if not bike_name:
        return None
    try:
        rows = get_sheet(SHEET_BIKE_CHECKLIST).get_all_values()[1:]
    except Exception as e:
        print(f"get_last_bike_checklist error: {e}")
        return None
    bike_lower = bike_name.lower().strip()
    for row in reversed(rows):
        if len(row) <= CHK_COL_BIKE:
            continue
        if str(row[CHK_COL_BIKE]).strip().lower() == bike_lower:
            return row
    return None


def get_last_bike_video_link(bike_name: str):
    if not bike_name:
        return ""
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_last_bike_video_link error: {e}")
        return ""
    bike_lower = bike_name.lower().strip()
    for row in reversed(rows):
        row = _pad_rental_row(row)
        if str(row[RENT_COL_BIKE]).strip().lower() != bike_lower:
            continue
        for col in (RENT_COL_VIDEO_OUT, RENT_COL_VIDEO_IN):
            link = str(row[col]).strip() if len(row) > col else ""
            if link.startswith("http"):
                return link
    chk = get_last_bike_checklist(bike_name)
    if chk and len(chk) > CHK_COL_PHOTO:
        link = str(chk[CHK_COL_PHOTO]).strip()
        if link.startswith("http"):
            return link
    return ""


def _update_rental_sync(rental_id: str, updates: dict):
    col_map = {
        "status": RENT_COL_STATUS,
        "payment_method": RENT_COL_PAYMENT_METHOD,
        "helmets": RENT_COL_HELMETS,
        "insurance": RENT_COL_INSURANCE,
        "insurance_cost": RENT_COL_INSURANCE_COST,
        "rental_price": RENT_COL_RENTAL_PRICE,
        "total": RENT_COL_TOTAL,
        "odometer_out": RENT_COL_ODOMETER_OUT,
        "fuel_out": RENT_COL_FUEL_OUT,
        "odometer_in": RENT_COL_ODOMETER_IN,
        "fuel_in": RENT_COL_FUEL_IN,
        "video_out": RENT_COL_VIDEO_OUT,
        "video_in": RENT_COL_VIDEO_IN,
        "damages": RENT_COL_DAMAGES,
        "damage_photos": RENT_COL_DAMAGE_PHOTOS,
        "comment": RENT_COL_COMMENT,
        "instructor": RENT_COL_INSTRUCTOR,
        "location": RENT_COL_LOCATION,
        "delivery_date": RENT_COL_DELIVERY_DATE,
        "delivery_time": RENT_COL_DELIVERY_TIME,
        "return_date": RENT_COL_RETURN_DATE,
        "duration_days": RENT_COL_DURATION,
        "extra_charges": RENT_COL_EXTRA_CHARGES,
    }
    ws, row_num, _ = _find_rental_sheet_row(rental_id)
    if not ws or not row_num:
        raise ValueError(f"Rental not found: {rental_id}")
    for key, val in updates.items():
        col = col_map.get(key)
        if col is not None:
            ws.update_cell(row_num, col + 1, str(val if val is not None else ""))
    reset_sheet_cache()


def _append_checklist_sync(data: dict):
    ws = get_sheet(SHEET_BIKE_CHECKLIST)
    row = [""] * len(CHECKLIST_HEADERS)
    mapping = {
        CHK_COL_DATE: "date",
        CHK_COL_TIME: "time",
        CHK_COL_RENTAL_ID: "rental_id",
        CHK_COL_BIKE: "bike",
        CHK_COL_TYPE: "type",
        CHK_COL_PHONE_HOLDER: "phone_holder",
        CHK_COL_PHONE_CHARGER: "phone_charger",
        CHK_COL_FIRST_AID: "first_aid",
        CHK_COL_BIKE_PAPERS: "bike_papers",
        CHK_COL_ADJUSTER: "adjuster",
        CHK_COL_HELMETS_COUNT: "helmets_count",
        CHK_COL_ODOMETER: "odometer",
        CHK_COL_FUEL_BAR: "fuel_bar",
        CHK_COL_PHOTO: "photo",
        CHK_COL_INSTRUCTOR: "instructor",
        CHK_COL_NOTES: "notes",
    }
    for col, key in mapping.items():
        row[col] = str(data.get(key, "") or "")
    ws.append_row(row, value_input_option="USER_ENTERED")


async def update_rental_fields(rental_id: str, updates: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_update_rental_sync, rental_id, updates))


async def append_checklist(data: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_append_checklist_sync, data))


def _append_bike_issue_sync(data: dict):
    ws = get_sheet(SHEET_BIKE_ISSUES)
    row = [""] * len(ISSUE_HEADERS)
    mapping = {
        ISS_COL_DATE: "date",
        ISS_COL_TIME: "time",
        ISS_COL_BIKE: "bike",
        ISS_COL_REPORTED_BY: "reported_by",
        ISS_COL_DESCRIPTION: "description",
        ISS_COL_PHOTOS: "photos",
        ISS_COL_STATUS: "status",
        ISS_COL_RESOLVED_DATE: "resolved_date",
        ISS_COL_COMMENT: "comment",
    }
    for col, key in mapping.items():
        row[col] = str(data.get(key, "") or "")
    ws.append_row(row, value_input_option="USER_ENTERED")


async def append_bike_issue(data: dict):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_append_bike_issue_sync, data))


def get_all_balances():
    from config import EMPLOYEES, MANAGERS
    result = {}
    try:
        ws_pay = get_sheet(SHEET_PAYOUTS)
        payout_rows = ws_pay.get_all_values()
    except:
        payout_rows = []

    try:
        ws_exp = get_sheet(SHEET_EXPENSES)
        exp_rows = ws_exp.get_all_values()
    except:
        exp_rows = []

    try:
        ws_inc = get_sheet(SHEET_INCOME)
        inc_rows = ws_inc.get_all_values()
    except:
        inc_rows = []

    all_users = {**EMPLOYEES, **MANAGERS}
    for uid, info in all_users.items():
        name = info["name"]

        last_exp_payout_row = _find_last_payout_row(payout_rows, name, "Expense payout")
        last_inc_handover_row = _find_last_payout_row(
            payout_rows, name, ("Income handover", "Transfer to colleague")
        )

        spendings = _sum_employee_expenses_since(exp_rows, name, last_exp_payout_row, "My pocket")
        overpayment_carry = 0
        if last_exp_payout_row and len(last_exp_payout_row) > PAYOUT_COL_OVERPAYMENT:
            overpayment_carry = _parse_amount(last_exp_payout_row[PAYOUT_COL_OVERPAYMENT]) or 0
        effective_spendings = max(0, spendings - overpayment_carry)
        cash_on_hand_expenses = _sum_employee_expenses_since(exp_rows, name, last_inc_handover_row, "Cash on hand")
        cash_on_hand = _sum_employee_income_since(inc_rows, name, last_inc_handover_row)

        total_exp = sum(
            amt for row in exp_rows
            if len(row) > EXP_COL_EMPLOYEE and row[EXP_COL_EMPLOYEE] == name and _is_sheet_data_row(row)
            for amt in [_parse_amount(row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else "")]
            if amt is not None
        )
        total_inc = sum(
            amt for row in inc_rows
            if len(row) > INC_COL_EMPLOYEE and row[INC_COL_EMPLOYEE] == name and _is_sheet_data_row(row)
            for amt in [_parse_amount(row[INC_COL_AMOUNT] if len(row) > INC_COL_AMOUNT else "")]
            if amt is not None
        )
        paid_out = _sum_payouts(payout_rows, name, "Expense payout")
        handed_over = _sum_payouts(payout_rows, name, ("Income handover", "Transfer to colleague"))

        result[name] = {
            "total_expenses": total_exp,
            "effective_spendings": effective_spendings,
            "paid_out": paid_out,
            "overpaid": max(0, overpayment_carry - spendings),
            "owed_to_employee": effective_spendings,
            "total_income": total_inc,
            "handed_over": handed_over,
            "held_by_employee": max(0, cash_on_hand - cash_on_hand_expenses),
            "last_exp_payout": _cutoff_label(last_exp_payout_row),
            "last_inc_handover": _cutoff_label(last_inc_handover_row),
        }
    return result

def format_idr(amount):
    try:
        s = str(int(amount)); r = ""; [r := r + ("." if (len(s)-i-1) % 3 == 0 and i != 0 else "") + s[i] for i in range(len(s))]; return "IDR " + r
    except:
        return f"IDR {amount}"

def get_total_since_last_payout(employee_name):
    """Total My pocket expenses since last expense payout (date + time)."""
    try:
        payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()
        exp_rows = get_sheet(SHEET_EXPENSES).get_all_values()
        last_payout_row = _find_last_payout_row(payout_rows, employee_name, "Expense payout")
        return _sum_employee_expenses_since(exp_rows, employee_name, last_payout_row, "My pocket")
    except Exception as e:
        print(f"get_total_since_last_payout error: {e}")
        return get_running_total_expenses(employee_name)


def get_total_since_last_handover(employee_name):
    """Total income recorded since last income handover (date + time)."""
    try:
        payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()
        inc_rows = get_sheet(SHEET_INCOME).get_all_values()
        last_handover_row = _find_last_payout_row(
            payout_rows, employee_name, ("Income handover", "Transfer to colleague")
        )
        return _sum_employee_income_since(inc_rows, employee_name, last_handover_row)
    except Exception as e:
        print(f"get_total_since_last_handover error: {e}")
        return get_running_total_income(employee_name)


def get_cash_on_hand_expenses_since_handover(employee_name):
    """Cash-on-hand expenses since last income handover."""
    try:
        payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()
        exp_rows = get_sheet(SHEET_EXPENSES).get_all_values()
        last_handover_row = _find_last_payout_row(
            payout_rows, employee_name, ("Income handover", "Transfer to colleague")
        )
        return _sum_employee_expenses_since(exp_rows, employee_name, last_handover_row, "Cash on hand")
    except Exception as e:
        print(f"get_cash_on_hand_expenses_since_handover error: {e}")
        return 0


def get_held_cash_on_hand(employee_name):
    """Net cash on hand held by employee since last handover."""
    income = get_total_since_last_handover(employee_name)
    spent = get_cash_on_hand_expenses_since_handover(employee_name)
    return max(0, income - spent)


def preview_spending_total(employee_name, amount, payment_source="My pocket"):
    """Projected My-pocket reimbursable total for confirm screens."""
    base = get_total_since_last_payout(employee_name)
    if str(payment_source or "").strip() == "My pocket":
        try:
            return base + int(amount or 0)
        except (ValueError, TypeError):
            return base
    return base


def fix_expense_times_after_payout(employee_name, date_str=None):
    """
    Move same-day expense timestamps to just after the latest expense payout on that date.
    Fixes rows saved before payout on the same calendar day (old date-only balance bug).
    """
    from datetime import timedelta
    target_date = date_str or now_date()
    ws_exp = get_sheet(SHEET_EXPENSES)
    exp_rows = ws_exp.get_all_values()
    payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()

    latest_payout_row = None
    latest_dt = None
    for row in payout_rows[1:]:
        if len(row) <= PAYOUT_COL_EMPLOYEE or not _is_sheet_data_row(row):
            continue
        if row[PAYOUT_COL_EMPLOYEE] != employee_name or row[PAYOUT_COL_TYPE] != "Expense payout":
            continue
        if str(row[PAYOUT_COL_DATE]).strip() != target_date:
            continue
        dt = _parse_row_datetime(row[PAYOUT_COL_DATE], row[1] if len(row) > 1 else "")
        if dt and (latest_dt is None or dt > latest_dt):
            latest_payout_row = row
            latest_dt = dt

    if not latest_payout_row or not latest_dt:
        print(f"fix_expense_times_after_payout: no payout for {employee_name} on {target_date}")
        return 0

    offset_min = 1
    fixed = 0
    for i, row in enumerate(exp_rows):
        if len(row) <= EXP_COL_EMPLOYEE or row[EXP_COL_EMPLOYEE] != employee_name or not _is_sheet_data_row(row):
            continue
        if str(row[0]).strip() != target_date:
            continue
        row_dt = _parse_row_datetime(row[0], row[1] if len(row) > 1 else "")
        if not row_dt or row_dt > latest_dt:
            continue
        new_dt = latest_dt + timedelta(minutes=offset_min)
        new_time = new_dt.strftime("%H:%M")
        ws_exp.update_cell(i + 1, EXP_COL_TIME + 1, new_time)
        print(f"Fixed expense row {i + 1}: {row[0]} {row[1]} -> {new_time} amount={row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else ''}")
        offset_min += 1
        fixed += 1

    if fixed:
        reset_sheet_cache()
        invalidate_balance_cache()
    return fixed


def fix_income_times_after_handover(employee_name, date_str=None):
    """
    Move same-day income timestamps to just after the latest income handover on that date.
    Only touches rows with missing/00:00 time (legacy date-only rows).
    """
    from datetime import timedelta
    target_date = date_str or now_date()
    ws_inc = get_sheet(SHEET_INCOME)
    inc_rows = ws_inc.get_all_values()
    payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()

    latest_handover_row = None
    latest_dt = None
    for row in payout_rows[1:]:
        if len(row) <= PAYOUT_COL_EMPLOYEE or not _is_sheet_data_row(row):
            continue
        if row[PAYOUT_COL_EMPLOYEE] != employee_name or row[PAYOUT_COL_TYPE] not in ("Income handover", "Transfer to colleague"):
            continue
        if str(row[PAYOUT_COL_DATE]).strip() != target_date:
            continue
        dt = _parse_row_datetime(row[PAYOUT_COL_DATE], row[1] if len(row) > 1 else "")
        if dt and (latest_dt is None or dt > latest_dt):
            latest_handover_row = row
            latest_dt = dt

    if not latest_handover_row or not latest_dt:
        return 0

    offset_min = 1
    fixed = 0
    for i, row in enumerate(inc_rows):
        if len(row) <= INC_COL_EMPLOYEE or row[INC_COL_EMPLOYEE] != employee_name or not _is_sheet_data_row(row):
            continue
        if str(row[0]).strip() != target_date:
            continue
        raw_time = row[1].strip() if len(row) > 1 and row[1] else ""
        if raw_time and raw_time not in ("00:00", "0:00"):
            continue
        row_dt = _parse_row_datetime(row[0], raw_time)
        if not row_dt or row_dt > latest_dt:
            continue
        new_dt = latest_dt + timedelta(minutes=offset_min)
        new_time = new_dt.strftime("%H:%M")
        ws_inc.update_cell(i + 1, INC_COL_TIME + 1, new_time)
        print(f"Fixed income row {i + 1}: {row[0]} {raw_time or '—'} -> {new_time} amount={row[INC_COL_AMOUNT] if len(row) > INC_COL_AMOUNT else ''}")
        offset_min += 1
        fixed += 1

    if fixed:
        reset_sheet_cache()
        invalidate_balance_cache()
    return fixed


def highlight_paid_rows(employee_name, payout_amount):
    """Highlight My pocket expense rows covered by the latest expense payout."""
    try:
        ws = get_sheet(SHEET_EXPENSES)
        all_rows = ws.get_all_values()
        payout_rows = get_sheet(SHEET_PAYOUTS).get_all_values()
        prev_cutoff = _find_nth_last_payout_row(payout_rows, employee_name, "Expense payout", n=2)
        current_payout = _find_nth_last_payout_row(payout_rows, employee_name, "Expense payout", n=1)
        payout_dt = _parse_row_datetime(
            current_payout[PAYOUT_COL_DATE], current_payout[1] if current_payout and len(current_payout) > 1 else ""
        ) if current_payout else None

        rows_to_color = []
        remaining = payout_amount
        for i, row in enumerate(all_rows):
            if len(row) <= EXP_COL_EMPLOYEE or row[EXP_COL_EMPLOYEE] != employee_name or not _is_sheet_data_row(row):
                continue
            if _expense_payment_source(row) != "My pocket":
                continue
            if not _row_after_cutoff(row, prev_cutoff):
                continue
            if payout_dt:
                row_dt = _parse_row_datetime(row[0], row[1] if len(row) > 1 else "")
                if row_dt and row_dt > payout_dt:
                    continue
            amount = _parse_amount(row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else "")
            if amount is None or remaining <= 0:
                continue
            rows_to_color.append(i + 1)
            remaining -= amount

        if rows_to_color:
            spreadsheet = get_spreadsheet()
            requests = []
            for row_num in rows_to_color:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": row_num - 1,
                            "endRowIndex": row_num,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 0.7, "green": 0.9, "blue": 0.7}
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor"
                    }
                })
            spreadsheet.batch_update({"requests": requests})
    except Exception as e:
        print(f"highlight_paid_rows error: {e}")

def get_all_pending(sheet_name):
    try:
        ws = get_sheet(sheet_name)
        return [r for r in ws.get_all_records() if r.get("Status") in ("New", "")]
    except:
        return []

def update_row_by_id(sheet_name, record_id, updates):
    try:
        ws = get_sheet(sheet_name)
        rows = ws.get_all_records()
        headers = ws.row_values(1)
        for i, row in enumerate(rows, start=2):
            if str(row.get("ID")) == str(record_id):
                for col, val in updates.items():
                    if col in headers:
                        ws.update_cell(i, headers.index(col) + 1, val)
                return True
    except Exception as e:
        print(f"update_row_by_id error: {e}")
    return False

def format_idr(amount):
    try:
        n = int(amount)
        s = f"{n:,}".replace(",", ".")
        return f"IDR {s}"
    except:
        return f"IDR {amount}"

_balance_cache = {}
_balance_cache_time = 0

def get_all_balances_cached():
    import time
    global _balance_cache, _balance_cache_time
    if time.time() - _balance_cache_time < 60:
        return _balance_cache
    _balance_cache = get_all_balances()
    _balance_cache_time = time.time()
    return _balance_cache

def invalidate_balance_cache():
    global _balance_cache_time
    _balance_cache_time = 0

async def async_get_all_balances():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_all_balances_cached)

async def async_get_running_total_expenses(name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(get_running_total_expenses, name))

async def async_get_running_total_income(name):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(get_running_total_income, name))

def build_grouped_buttons(rows, sheet, callback_prefix, all_rows=None):
    """Build inline buttons grouped by employee and date."""
    from aiogram.types import InlineKeyboardButton
    from collections import defaultdict
    from datetime import datetime, timedelta
    
    # Filter last 31 days
    cutoff = (datetime.now() - timedelta(days=31)).strftime("%d.%m.%Y")
    
    groups = defaultdict(lambda: defaultdict(list))
    for i, r in enumerate(rows):
        if len(r) < 3 or r[0] in ("", "Date", "TOTAL") or r[0].startswith("="):
            continue
        # Date filter
        try:
            rd = datetime.strptime(r[0], "%d.%m.%Y")
            cd = datetime.strptime(cutoff, "%d.%m.%Y")
            if rd < cd:
                continue
        except:
            continue
        
        if sheet == "Expenses":
            emp = r[EXP_COL_EMPLOYEE] if len(r) > EXP_COL_EMPLOYEE else "?"
            amt = r[EXP_COL_AMOUNT] if len(r) > EXP_COL_AMOUNT else ""
            label = f"{r[EXP_COL_CATEGORY]} | {amt}" if len(r) > EXP_COL_CATEGORY else f"{r[2]} | {amt}"
        elif sheet == "Income":
            emp = r[INC_COL_EMPLOYEE] if len(r) > INC_COL_EMPLOYEE else "?"
            amt = r[INC_COL_AMOUNT] if len(r) > INC_COL_AMOUNT else ""
            label = f"{r[INC_COL_CATEGORY]} | {amt}" if len(r) > INC_COL_CATEGORY else f"{r[2]} | {amt}"
        else:
            emp = r[3] if len(r) > 3 else "?"
            amt = r[4] if len(r) > 4 else ""
            label = f"{r[2]} | {amt}"
        
        row_idx = all_rows.index(r) if all_rows else i
        groups[emp][r[0]].append((row_idx, label))
    
    buttons = []
    for emp in sorted(groups.keys()):
        buttons.append([InlineKeyboardButton(text=f"👤 {emp}", callback_data=f"{callback_prefix}:noop")])
        for date in sorted(groups[emp].keys(), reverse=True):
            buttons.append([InlineKeyboardButton(text=f"📅 {date}", callback_data=f"{callback_prefix}:noop")])
            for row_idx, label in groups[emp][date]:
                buttons.append([InlineKeyboardButton(text=label[:50], callback_data=f"{callback_prefix}:{row_idx}")])
    return buttons


def record_picker_employee_names(selected_uids):
    from config import EMPLOYEES, MANAGERS
    all_users = {**EMPLOYEES, **MANAGERS}
    names = []
    for uid in selected_uids:
        try:
            uid_key = int(uid)
        except (TypeError, ValueError):
            continue
        info = all_users.get(uid_key)
        if info:
            names.append(info["name"])
    return names


def _record_row_employee(sheet, row):
    if sheet == SHEET_EXPENSES:
        return row[EXP_COL_EMPLOYEE] if len(row) > EXP_COL_EMPLOYEE else ""
    if sheet == SHEET_INCOME:
        return row[INC_COL_EMPLOYEE] if len(row) > INC_COL_EMPLOYEE else ""
    if sheet == SHEET_PAYOUTS:
        return row[PAYOUT_COL_EMPLOYEE] if len(row) > PAYOUT_COL_EMPLOYEE else ""
    return ""


def _record_row_label(sheet, row):
    if sheet == SHEET_EXPENSES:
        cat = row[EXP_COL_CATEGORY] if len(row) > EXP_COL_CATEGORY else (row[2] if len(row) > 2 else "")
        amt = row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else ""
        icon = "⛽" if cat == "Bensin" else "💸"
        return icon, f"{cat} | {amt}"
    if sheet == SHEET_INCOME:
        cat = row[INC_COL_CATEGORY] if len(row) > INC_COL_CATEGORY else (row[2] if len(row) > 2 else "")
        amt = row[INC_COL_AMOUNT] if len(row) > INC_COL_AMOUNT else ""
        return "💰", f"{cat} | {amt}"
    if sheet == SHEET_PAYOUTS:
        ptype = row[PAYOUT_COL_TYPE] if len(row) > PAYOUT_COL_TYPE else (row[2] if len(row) > 2 else "")
        amt = row[PAYOUT_COL_AMOUNT] if len(row) > PAYOUT_COL_AMOUNT else ""
        return "💳", f"{ptype} | {amt}"
    return "📋", "?"


def collect_record_dates_for_employees(employee_names):
    names = set(employee_names)
    dates = set()
    for sheet in (SHEET_EXPENSES, SHEET_INCOME, SHEET_PAYOUTS):
        try:
            rows = get_sheet(sheet).get_all_values()
        except Exception as e:
            print(f"collect_record_dates error ({sheet}): {e}")
            continue
        for row in rows:
            if not _is_sheet_data_row(row):
                continue
            if _record_row_employee(sheet, row) not in names:
                continue
            dates.add(row[0])
    return dates


def get_records_for_date_employees(date_str, employee_names, include_payouts=True, expenses_income_only=False):
    names = set(employee_names)
    sheets = [SHEET_EXPENSES, SHEET_INCOME]
    if include_payouts and not expenses_income_only:
        sheets.append(SHEET_PAYOUTS)
    records = []
    for sheet in sheets:
        try:
            rows = get_sheet(sheet).get_all_values()
        except Exception as e:
            print(f"get_records_for_date error ({sheet}): {e}")
            continue
        for i, row in enumerate(rows):
            if not _is_sheet_data_row(row):
                continue
            if row[0] != date_str:
                continue
            emp = _record_row_employee(sheet, row)
            if emp not in names:
                continue
            icon, label = _record_row_label(sheet, row)
            time_str = row[1] if len(row) > 1 else ""
            records.append({
                "sheet": sheet,
                "row_idx": i,
                "employee": emp,
                "icon": icon,
                "label": label,
                "time": time_str,
                "row": row,
                "key": f"{sheet}:{i}",
            })
    records.sort(key=lambda r: (r["employee"], r["time"]))
    return records


def _parse_mileage_km(value) -> int:
    digits = "".join(c for c in str(value) if c.isdigit())
    return int(digits) if digits else 0


def _parse_expense_datetime(date_str: str, time_str: str):
    try:
        return datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%d.%m.%Y %H:%M")
    except Exception:
        return None


def _row_matches_bike(row: list, bike_name: str) -> bool:
    place = row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else ""
    return bike_name.lower() in place.lower()


def get_last_mileage_with_date(bike_name: str, before_date: str, before_time: str):
    """Latest odometer record for bike strictly before before_date/before_time. Returns (mileage, datetime) or (0, None)."""
    try:
        before_dt = _parse_expense_datetime(before_date, before_time)
        if not before_dt:
            return 0, None
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        best_km = 0
        best_dt = None
        for row in rows:
            if len(row) <= EXP_COL_MILEAGE:
                continue
            if row[EXP_COL_CATEGORY] not in ODOMETER_CATEGORIES:
                continue
            if not _row_matches_bike(row, bike_name):
                continue
            km = _parse_mileage_km(row[EXP_COL_MILEAGE])
            if not km:
                continue
            row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "")
            if not row_dt or row_dt >= before_dt:
                continue
            if best_dt is None or row_dt > best_dt:
                best_km = km
                best_dt = row_dt
        return best_km, best_dt
    except Exception as e:
        print(f"get_last_mileage_with_date error: {e}")
        return 0, None


def _extract_bike_from_place(place: str) -> str:
    for sep in (" — ", " @ "):
        if sep in place:
            return place.split(sep, 1)[0].strip()
    return place.strip()


def _parse_gps_mileage_km(value) -> int:
    s = str(value).strip()
    if not s or s.lower() in ("gps error", "no gps", "no previous record"):
        return 0
    return _parse_mileage_km(value)


def get_mileage_discrepancies(threshold_pct: float = 5.0) -> list[dict]:
    """Latest expense per bike with manual + GPS mileage; return bikes where diff > threshold_pct."""
    try:
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        last_by_bike: dict[str, dict] = {}
        for row in rows:
            if len(row) <= EXP_COL_GPS_MILEAGE:
                continue
            if row[0] in ("", "Date", "TOTAL") or str(row[0]).startswith("="):
                continue
            manual = _parse_mileage_km(row[EXP_COL_MILEAGE])
            gps = _parse_gps_mileage_km(row[EXP_COL_GPS_MILEAGE])
            if not manual or not gps:
                continue
            place = row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else ""
            bike = _extract_bike_from_place(place)
            if not bike:
                continue
            row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "00:00")
            prev = last_by_bike.get(bike)
            if prev is None or (row_dt and (prev.get("dt") is None or row_dt >= prev["dt"])):
                last_by_bike[bike] = {"bike": bike, "manual": manual, "gps": gps, "dt": row_dt}
        result = []
        for rec in last_by_bike.values():
            gps = rec["gps"]
            manual = rec["manual"]
            diff_pct = abs(manual - gps) / gps * 100
            if diff_pct > threshold_pct:
                result.append({
                    "bike": rec["bike"],
                    "manual": manual,
                    "gps": gps,
                    "diff_pct": round(diff_pct, 1),
                })
        return sorted(result, key=lambda x: -x["diff_pct"])
    except Exception as e:
        print(f"get_mileage_discrepancies error: {e}")
        return []


def _bike_names_match(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    return a == b or a in b or b in a


def _place_matches_gps_bike(place: str, bike_filter: str, gps_bike_names: list[str]) -> bool:
    extracted = _extract_bike_from_place(place)
    if not extracted:
        return False
    if bike_filter == "ALL":
        return any(_bike_names_match(extracted, name) for name in gps_bike_names)
    return _bike_names_match(extracted, bike_filter)


def get_gps_odo_records(bike_filter: str, days: int) -> list[dict]:
    """Expense rows with manual + GPS mileage for GPS bikes within the last `days` days."""
    try:
        from config import BIKES_GPS
        from datetime import timedelta

        gps_bike_names = sorted({info["name"] for info in BIKES_GPS.values()})
        cutoff = datetime.now() - timedelta(days=days)
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        records = []
        for row in rows:
            if len(row) <= EXP_COL_GPS_MILEAGE:
                continue
            if row[0] in ("", "Date", "TOTAL") or str(row[0]).startswith("="):
                continue
            manual = _parse_mileage_km(row[EXP_COL_MILEAGE])
            gps = _parse_gps_mileage_km(row[EXP_COL_GPS_MILEAGE])
            if not manual or not gps:
                continue
            place = row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else ""
            if not _place_matches_gps_bike(place, bike_filter, gps_bike_names):
                continue
            row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "00:00")
            if not row_dt or row_dt < cutoff:
                continue
            bike = _extract_bike_from_place(place)
            diff_pct = abs(manual - gps) / gps * 100
            records.append({
                "date": row[0],
                "bike": bike,
                "manual": manual,
                "gps": gps,
                "diff_pct": round(diff_pct, 1),
                "dt": row_dt,
            })
        records.sort(key=lambda r: r["dt"], reverse=True)
        return records
    except Exception as e:
        print(f"get_gps_odo_records error: {e}")
        return []


def get_last_mileage(bike_name):
    """Latest odometer reading for a bike by date/time (not highest km ever)."""
    try:
        ws = get_sheet(SHEET_EXPENSES)
        rows = ws.get_all_values()
        best_km = 0
        best_dt = None
        for row in rows:
            if len(row) <= EXP_COL_MILEAGE:
                continue
            if row[EXP_COL_CATEGORY] not in ODOMETER_CATEGORIES:
                continue
            if not _row_matches_bike(row, bike_name):
                continue
            km = _parse_mileage_km(row[EXP_COL_MILEAGE])
            if not km:
                continue
            row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "")
            if best_dt is None or (row_dt and row_dt >= best_dt):
                best_km = km
                best_dt = row_dt
        return best_km
    except Exception as e:
        print(f"get_last_mileage error: {e}")
        return 0


def _rental_bike_matches(row_bike: str, bike_name: str) -> bool:
    return _bike_names_match(str(row_bike or ""), bike_name)


def get_rentals_for_bike(bike_name: str, limit: int = 20):
    if not bike_name:
        return []
    from datetime import datetime
    try:
        rows = get_sheet(SHEET_RENTALS).get_all_values()[1:]
    except Exception as e:
        print(f"get_rentals_for_bike error: {e}")
        return []
    result = []
    for row in rows:
        row = _pad_rental_row(row)
        rb = row[RENT_COL_BIKE] if len(row) > RENT_COL_BIKE else ""
        if not _rental_bike_matches(rb, bike_name):
            continue
        rental = rental_row_to_dict(row)
        rental["_sort"] = _rental_reference_date(rental) or datetime.min
        result.append(rental)
    result.sort(key=lambda r: r.get("_sort") or datetime.min, reverse=True)
    for r in result:
        r.pop("_sort", None)
    if limit and limit > 0:
        return result[:limit]
    return result


def get_current_rental_for_bike(bike_name: str):
    for rental in get_rentals_for_bike(bike_name, limit=0):
        if str(rental.get("status", "")).lower() in ("booked", "active"):
            return rental
    return None


def get_bike_rental_revenue(bike_name: str, days: int = 0):
    from datetime import datetime, timedelta
    cutoff = None
    if days and days > 0:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    total = 0
    count = 0
    for rental in get_rentals_for_bike(bike_name, limit=0):
        status = str(rental.get("status", "")).lower()
        if status not in RENTAL_REVENUE_STATUSES:
            continue
        if cutoff:
            ref_dt = _rental_reference_date(rental)
            if not ref_dt or ref_dt < cutoff:
                continue
        try:
            amount = int(str(rental.get("total") or rental.get("rental_price") or 0).replace(",", "") or 0)
        except ValueError:
            amount = 0
        total += amount
        count += 1
    return total, count


def get_bike_issues_for_bike(bike_name: str, limit: int = 8, open_only: bool = False):
    if not bike_name:
        return []
    try:
        rows = get_sheet(SHEET_BIKE_ISSUES).get_all_values()[1:]
    except Exception as e:
        print(f"get_bike_issues_for_bike error: {e}")
        return []
    result = []
    for row in rows:
        if len(row) <= ISS_COL_BIKE:
            continue
        if not _bike_names_match(str(row[ISS_COL_BIKE]), bike_name):
            continue
        status = str(row[ISS_COL_STATUS]).strip() if len(row) > ISS_COL_STATUS else ""
        if open_only and status.lower() in ("resolved", "closed", "done"):
            continue
        result.append({
            "date": row[ISS_COL_DATE] if len(row) > ISS_COL_DATE else "",
            "time": row[ISS_COL_TIME] if len(row) > ISS_COL_TIME else "",
            "bike": row[ISS_COL_BIKE] if len(row) > ISS_COL_BIKE else "",
            "reported_by": row[ISS_COL_REPORTED_BY] if len(row) > ISS_COL_REPORTED_BY else "",
            "description": row[ISS_COL_DESCRIPTION] if len(row) > ISS_COL_DESCRIPTION else "",
            "status": status,
            "photos": row[ISS_COL_PHOTOS] if len(row) > ISS_COL_PHOTOS else "",
        })
    result.sort(key=lambda r: (r.get("date") or "", r.get("time") or ""), reverse=True)
    return result[:limit] if limit else result


def get_expenses_for_bike(bike_name: str, categories: tuple = None, limit: int = 8, days: int = 0):
    if not bike_name:
        return []
    from datetime import timedelta
    cutoff = None
    if days and days > 0:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    try:
        rows = get_sheet(SHEET_EXPENSES).get_all_values()[1:]
    except Exception as e:
        print(f"get_expenses_for_bike error: {e}")
        return []
    result = []
    for row in rows:
        if not _is_sheet_data_row(row):
            continue
        cat = row[EXP_COL_CATEGORY] if len(row) > EXP_COL_CATEGORY else ""
        if categories and cat not in categories:
            continue
        if not _row_matches_bike(row, bike_name):
            continue
        row_dt = _parse_expense_datetime(row[0], row[1] if len(row) > 1 else "00:00")
        if cutoff and (not row_dt or row_dt < cutoff):
            continue
        result.append({
            "date": row[0],
            "time": row[1] if len(row) > 1 else "",
            "category": cat,
            "place": row[EXP_COL_PLACE] if len(row) > EXP_COL_PLACE else "",
            "amount": row[EXP_COL_AMOUNT] if len(row) > EXP_COL_AMOUNT else "",
            "mileage": row[EXP_COL_MILEAGE] if len(row) > EXP_COL_MILEAGE else "",
            "gps_mileage": row[EXP_COL_GPS_MILEAGE] if len(row) > EXP_COL_GPS_MILEAGE else "",
            "employee": row[EXP_COL_EMPLOYEE] if len(row) > EXP_COL_EMPLOYEE else "",
            "comment": row[EXP_COL_COMMENT] if len(row) > EXP_COL_COMMENT else "",
            "dt": row_dt,
        })
    result.sort(key=lambda r: r.get("dt") or datetime.min, reverse=True)
    if limit and limit > 0:
        result = result[:limit]
    for r in result:
        r.pop("dt", None)
    return result


def _bike_usage_from_rentals(bike_name: str, days: int = 0) -> dict:
    """Count rental deliveries by instructor for a bike in period."""
    from datetime import timedelta
    cutoff = None
    if days and days > 0:
        cutoff = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
    usage = {}
    for rental in get_rentals_for_bike(bike_name, limit=0):
        status = str(rental.get("status", "")).lower()
        if status not in RENTAL_REVENUE_STATUSES:
            continue
        if cutoff:
            ref = _rental_reference_date(rental)
            if not ref or ref < cutoff:
                continue
        instructor = str(rental.get("instructor") or "").strip()
        if instructor:
            usage[instructor] = usage.get(instructor, 0) + 1
    return usage


def _build_mileage_intervals(odo_points: list) -> dict:
    """Build km intervals between consecutive odometer records, split by category."""
    def _intervals_for(category: str):
        points = [p for p in odo_points if p.get("category") == category]
        result = []
        for i in range(1, len(points)):
            prev_p, cur_p = points[i - 1], points[i]
            if cur_p["km"] < prev_p["km"]:
                continue
            delta = cur_p["km"] - prev_p["km"]
            days = None
            if prev_p.get("dt") and cur_p.get("dt"):
                days = (cur_p["dt"] - prev_p["dt"]).days
            result.append({
                "from_date": prev_p.get("date"),
                "from_km": prev_p["km"],
                "from_employee": prev_p.get("employee") or "—",
                "to_date": cur_p.get("date"),
                "to_km": cur_p["km"],
                "to_employee": cur_p.get("employee") or "—",
                "delta_km": delta,
                "days": days,
            })
        return list(reversed(result))

    all_intervals = []
    for i in range(1, len(odo_points)):
        prev_p, cur_p = odo_points[i - 1], odo_points[i]
        if cur_p["km"] < prev_p["km"]:
            continue
        delta = cur_p["km"] - prev_p["km"]
        days = None
        if prev_p.get("dt") and cur_p.get("dt"):
            days = (cur_p["dt"] - prev_p["dt"]).days
        all_intervals.append({
            "from_date": prev_p.get("date"),
            "from_cat": prev_p.get("category"),
            "from_km": prev_p["km"],
            "from_employee": prev_p.get("employee") or "—",
            "to_date": cur_p.get("date"),
            "to_cat": cur_p.get("category"),
            "to_km": cur_p["km"],
            "to_employee": cur_p.get("employee") or "—",
            "delta_km": delta,
            "days": days,
        })

    return {
        "all": list(reversed(all_intervals)),
        "fuel": _intervals_for("Bensin"),
        "service": _intervals_for("Bike service") + _intervals_for("Tires pressure / Wheel repair"),
    }


def get_bike_statistics(bike_name: str, days: int = 30) -> dict:
    fuel_cats = ("Bensin",)
    service_cats = ("Bike service", "Tires pressure / Wheel repair")
    fuel_rows = get_expenses_for_bike(bike_name, fuel_cats, limit=0, days=days)
    service_rows = get_expenses_for_bike(bike_name, service_cats, limit=0, days=days)
    odometer_rows = get_expenses_for_bike(bike_name, ODOMETER_CATEGORIES, limit=0, days=days)

    fuel_total = sum(_parse_amount(r.get("amount")) for r in fuel_rows)
    service_total = sum(_parse_amount(r.get("amount")) for r in service_rows)
    service_breakdown = {}
    for row in service_rows:
        cat = row.get("category") or "Other"
        service_breakdown[cat] = service_breakdown.get(cat, 0) + _parse_amount(row.get("amount"))

    odo_points = []
    for row in odometer_rows:
        km = _parse_mileage_km(row.get("mileage"))
        if not km:
            continue
        dt = _parse_expense_datetime(row.get("date"), row.get("time") or "00:00")
        odo_points.append({
            "date": row.get("date"),
            "time": row.get("time"),
            "category": row.get("category"),
            "km": km,
            "gps_km": _parse_gps_mileage_km(row.get("gps_mileage")),
            "place": row.get("place"),
            "employee": row.get("employee") or "—",
            "amount": row.get("amount"),
            "dt": dt,
        })
    odo_points.sort(key=lambda x: x.get("dt") or datetime.min)

    users = {}
    for row in odometer_rows:
        emp = (row.get("employee") or "").strip()
        if emp:
            users[emp] = users.get(emp, 0) + 1
    for name, count in _bike_usage_from_rentals(bike_name, days).items():
        users[name] = users.get(name, 0) + count

    timeline = []
    prev_km = None
    for point in odo_points:
        delta = point["km"] - prev_km if prev_km is not None and point["km"] >= prev_km else None
        timeline.append({**point, "delta": delta})
        prev_km = point["km"]

    intervals = _build_mileage_intervals(odo_points)
    from utils.bike_maintenance import get_bike_service_log
    service_log = get_bike_service_log(bike_name, days=days)

    km_driven = None
    if len(odo_points) >= 2 and odo_points[-1]["km"] >= odo_points[0]["km"]:
        km_driven = odo_points[-1]["km"] - odo_points[0]["km"]

    fuel_points = [p for p in odo_points if p.get("category") == "Bensin"]
    fill_deltas = []
    for i in range(1, len(fuel_points)):
        if fuel_points[i]["km"] >= fuel_points[i - 1]["km"]:
            fill_deltas.append(fuel_points[i]["km"] - fuel_points[i - 1]["km"])
    avg_km_per_fill = round(sum(fill_deltas) / len(fill_deltas), 1) if fill_deltas else None

    cost_per_km = None
    if km_driven and km_driven > 0:
        cost_per_km = round((fuel_total + service_total) / km_driven)

    return {
        "fuel_count": len(fuel_rows),
        "fuel_total": fuel_total,
        "fuel_avg": round(fuel_total / len(fuel_rows)) if fuel_rows else 0,
        "service_count": len(service_rows),
        "service_total": service_total,
        "service_breakdown": service_breakdown,
        "odometer_records": len(odo_points),
        "km_driven": km_driven,
        "odo_start": odo_points[0]["km"] if odo_points else None,
        "odo_end": odo_points[-1]["km"] if odo_points else None,
        "avg_km_per_fill": avg_km_per_fill,
        "cost_per_km": cost_per_km,
        "users": dict(sorted(users.items(), key=lambda x: (-x[1], x[0]))),
        "timeline": list(reversed(timeline)),
        "intervals": intervals,
        "service_log": service_log,
    }


def _get_next_invoice_no_sync() -> str:
    from datetime import timezone, timedelta
    wita = timezone(timedelta(hours=8))
    today_prefix = datetime.now(wita).strftime("%y%m%d")
    try:
        ws = get_sheet(SHEET_INVOICES)
        rows = ws.get_all_values()
    except Exception:
        return f"{today_prefix}-01"
    max_seq = 0
    for row in rows[1:]:
        inv_no = (row[INV_COL_NO] if row else "").strip()
        if not inv_no.startswith(f"{today_prefix}-"):
            continue
        try:
            max_seq = max(max_seq, int(inv_no.split("-", 1)[1]))
        except (ValueError, IndexError):
            pass
    return f"{today_prefix}-{max_seq + 1:02d}"


async def get_next_invoice_no() -> str:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _get_next_invoice_no_sync)


def _format_invoice_items(items: list) -> str:
    parts = []
    for item in items or []:
        desc = str(item.get("description", "")).strip()
        rate = int(round(float(item.get("rate", 0))))
        qty = item.get("qty", 1)
        parts.append(f"{desc} x{qty} @ {rate}")
    return "; ".join(parts)


def _invoice_total(items: list) -> int:
    total = 0
    for item in items or []:
        total += int(round(float(item.get("rate", 0)) * float(item.get("qty", 1))))
    return total


def _append_invoice_sync(
    invoice_no, date_str, client_type, client_name, contact,
    items, total, sent_via, created_by,
):
    ws = get_sheet(SHEET_INVOICES)
    ws.append_row([
        invoice_no, date_str, client_type, client_name, contact,
        _format_invoice_items(items), total, sent_via, created_by,
    ], value_input_option="USER_ENTERED")


async def append_invoice(
    invoice_no, date_str, client_type, client_name, contact,
    items, total, sent_via, created_by,
):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        partial(
            _append_invoice_sync,
            invoice_no, date_str, client_type, client_name, contact,
            items, total, sent_via, created_by,
        ),
    )


def _update_invoice_sent_via_sync(invoice_no: str, sent_via: str):
    ws = get_sheet(SHEET_INVOICES)
    rows = ws.get_all_values()
    for i, row in enumerate(rows):
        if row and row[INV_COL_NO] == invoice_no:
            ws.update_cell(i + 1, INV_COL_SENT_VIA + 1, sent_via)
            return


async def update_invoice_sent_via(invoice_no: str, sent_via: str):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, partial(_update_invoice_sent_via_sync, invoice_no, sent_via))

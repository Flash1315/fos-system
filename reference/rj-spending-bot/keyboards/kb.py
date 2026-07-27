from datetime import datetime, timedelta
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from config import BIKES, EXPENSE_CATEGORIES, INCOME_CATEGORIES


def main_menu(is_manager: bool = False, user_id: int = None) -> ReplyKeyboardMarkup:
    buttons = []
    if user_id is not None:
        from utils.rental_progress import get_resume_label
        resume = get_resume_label(user_id)
        if resume:
            buttons.append([KeyboardButton(text=resume)])
    buttons.extend([
        [KeyboardButton(text="💸 Expenses"), KeyboardButton(text="🧾 Add expense (AI)")],
        [KeyboardButton(text="⛽ Fuel"), KeyboardButton(text="🧾 Fuel (AI)")],
        [KeyboardButton(text="💰 Income")],
        [KeyboardButton(text="📊 My balance"), KeyboardButton(text="📋 My records")],
        [KeyboardButton(text="🔄 Transfer to colleague")],
        [KeyboardButton(text="⏰ Alarm"), KeyboardButton(text="📅 Next lesson"), KeyboardButton(text="🗓 My schedule")],
        [KeyboardButton(text="🏍 Deliver bike"), KeyboardButton(text="🏁 Return bike")],
        [KeyboardButton(text="⚠️ Report bike issue")],
        [KeyboardButton(text="🆘 SOS")],
    ])
    if is_manager:
        buttons.append([KeyboardButton(text="👔 Manager")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )

def back_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True
    )


def pause_back_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="⏸ Pause")],
            [KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True,
    )

def numeric_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Cancel")]],
        resize_keyboard=True,
        input_field_placeholder="Enter amount..."
    )


def skip_cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip (no receipt)")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True
    )

def skip_comment_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Skip")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True
    )


def bikes_kb() -> ReplyKeyboardMarkup:
    from utils.bikes import get_work_bikes, get_rental_bikes
    rows = [[KeyboardButton(text="— 🔧 Work bikes —")]]
    rows += [[KeyboardButton(text=b)] for b in get_work_bikes()]
    rows += [[KeyboardButton(text="— 🏠 Rental bikes —")]]
    rows += [[KeyboardButton(text=b)] for b in get_rental_bikes()]
    rows.append([KeyboardButton(text="Other (enter manually)")])
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def expense_categories_kb() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=c)] for c in EXPENSE_CATEGORIES]
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def income_categories_kb() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=c)] for c in INCOME_CATEGORIES]
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def payment_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💵 Cash"), KeyboardButton(text="💳 Transfer")],
            [KeyboardButton(text="🔳 QRIS"), KeyboardButton(text="✅ Already paid")],
            [KeyboardButton(text="💳 Instructor's card")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True
    )

def pay_expense_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💵 Cash"), KeyboardButton(text="💳 Transfer")],
            [KeyboardButton(text="💰 Taken from revenue")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True
    )

def receive_income_type_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💵 Cash"), KeyboardButton(text="💳 Transfer")],
            [KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")],
        ],
        resize_keyboard=True
    )


def confirm_kb(show_remember: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="✅ Confirm"), KeyboardButton(text="✏️ Edit")],
    ]
    if show_remember:
        rows.append([KeyboardButton(text="✅ Remember fix")])
    rows.append([KeyboardButton(text="⬅️ Back"), KeyboardButton(text="❌ Cancel")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def calendar_kb(year: int = None, month: int = None, prefix: str = "cal") -> InlineKeyboardMarkup:
    now = datetime.now()
    if year is None: year = now.year
    if month is None: month = now.month

    import calendar
    month_name = datetime(year, month, 1).strftime("%B %Y")
    
    buttons = []
    # Header: prev / month name / next
    buttons.append([
        InlineKeyboardButton(text="◀", callback_data=f"{prefix}:prev:{year}:{month}"),
        InlineKeyboardButton(text=month_name, callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="▶", callback_data=f"{prefix}:next:{year}:{month}"),
    ])
    # Day names
    buttons.append([InlineKeyboardButton(text=d, callback_data=f"{prefix}:ignore") 
                    for d in ["Mo","Tu","We","Th","Fr","Sa","Su"]])
    # Days
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data=f"{prefix}:ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                marker = "🔵" if day == now.day and month == now.month and year == now.year else str(day)
                row.append(InlineKeyboardButton(text=marker, callback_data=f"{prefix}:day:{date_str}"))
        buttons.append(row)
    
    buttons.append([InlineKeyboardButton(text="📅 Today", callback_data=f"{prefix}:day:{now.strftime('%d.%m.%Y')}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"{prefix}:back"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def record_picker_calendar_kb(year: int = None, month: int = None, active_dates: set = None, prefix: str = "recpick_cal") -> InlineKeyboardMarkup:
    now = datetime.now()
    if year is None:
        year = now.year
    if month is None:
        month = now.month
    if active_dates is None:
        active_dates = set()

    import calendar
    month_name = datetime(year, month, 1).strftime("%B %Y")

    buttons = []
    buttons.append([
        InlineKeyboardButton(text="◀", callback_data=f"{prefix}:prev:{year}:{month}"),
        InlineKeyboardButton(text=month_name, callback_data=f"{prefix}:ignore"),
        InlineKeyboardButton(text="▶", callback_data=f"{prefix}:next:{year}:{month}"),
    ])
    buttons.append([InlineKeyboardButton(text=d, callback_data=f"{prefix}:ignore")
                    for d in ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]])
    cal = calendar.monthcalendar(year, month)
    for week in cal:
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data=f"{prefix}:ignore"))
            else:
                date_str = f"{day:02d}.{month:02d}.{year}"
                if date_str in active_dates:
                    marker = "🔵" if day == now.day and month == now.month and year == now.year else str(day)
                    row.append(InlineKeyboardButton(text=marker, callback_data=f"{prefix}:day:{date_str}"))
                else:
                    row.append(InlineKeyboardButton(text="·", callback_data=f"{prefix}:ignore"))
        buttons.append(row)

    today_str = now.strftime("%d.%m.%Y")
    if today_str in active_dates:
        buttons.append([InlineKeyboardButton(text="📅 Today", callback_data=f"{prefix}:day:{today_str}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"{prefix}:back"),
        InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def records_inline(records: list, sheet_type: str) -> InlineKeyboardMarkup:
    buttons = []
    for r in records:
        rec_id = r.get("ID", "?")
        label = f"{r.get('Date', '')} — {r.get('Note', r.get('Category', r.get('Note', '')))}"
        buttons.append([InlineKeyboardButton(
            text=label[:55],
            callback_data=f"edit:{sheet_type}:{rec_id}"
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def edit_fields_inline(sheet_type: str, record_id: str) -> InlineKeyboardMarkup:
    if sheet_type == "expenses":
        fields = [("Date","Date"),("Note","Note"),("Amount","Amount (IDR)"),("Purpose","Purpose"),("Place","Place")]
    elif sheet_type == "fuel":
        fields = [("Date","Date"),("Bike","Note"),("Station","Place"),("Mileage","Purpose")]
    else:
        fields = [("Date","Date"),("Category","Category"),("Client","Client name"),("Amount","Amount (IDR)"),("Payment","Cash / Transfer")]

    buttons = [[InlineKeyboardButton(text=l, callback_data=f"field:{sheet_type}:{record_id}:{f}")] for l,f in fields]
    buttons.append([InlineKeyboardButton(text="🗑 Delete", callback_data=f"delete:{sheet_type}:{record_id}")])
    buttons.append([InlineKeyboardButton(text="« Back", callback_data="my_records")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def rental_submenu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Book bike")],
            [KeyboardButton(text="📖 Active rentals"), KeyboardButton(text="📊 Rental history")],
            [KeyboardButton(text="⚠️ Bike issues")],
            [KeyboardButton(text="📚 Teach AI")],
            [KeyboardButton(text="« Back")],
        ],
        resize_keyboard=True,
    )


def manager_menu_kb(is_superadmin=False) -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text="📋 Pending expenses"), KeyboardButton(text="📋 Pending income")],
        [KeyboardButton(text="💼 All balances")],
        [KeyboardButton(text="💸 Pay expense"), KeyboardButton(text="💰 Receive income")],
    ]
    if is_superadmin:
        buttons.append([KeyboardButton(text="🗑 Delete record"), KeyboardButton(text="✏️ Edit record")])
        buttons.append([KeyboardButton(text="📍 GPS Status"), KeyboardButton(text="📊 Mileage today"), KeyboardButton(text="📅 Mileage month")])
        buttons.append([KeyboardButton(text="📊 GPS vs Odo")])
        buttons.append([KeyboardButton(text="✂️ Cut engine"), KeyboardButton(text="🔑 Restore engine")])
        buttons.append([KeyboardButton(text="🗺 Live map")])
        buttons.append([KeyboardButton(text="🏍 Manage bikes"), KeyboardButton(text="🏍 Bike profile")])
        buttons.append([KeyboardButton(text="📊 Bike statistics"), KeyboardButton(text="📈 Full statistics")])
        buttons.append([KeyboardButton(text="📅 Send schedule")])
        buttons.append([KeyboardButton(text="📆 Manage calendar")])
    buttons.append([KeyboardButton(text="💬 Add comment")])
    buttons.append([KeyboardButton(text="🧾 Invoice")])
    buttons.append([KeyboardButton(text="🏍 Bike Rental")])
    buttons.append([KeyboardButton(text="« Main menu")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def manager_record_inline(sheet_type: str, record_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Approve", callback_data=f"approve:{sheet_type}:{record_id}"),
            InlineKeyboardButton(text="❌ Reject", callback_data=f"reject:{sheet_type}:{record_id}"),
        ],
        [InlineKeyboardButton(text="💬 Comment", callback_data=f"comment:{sheet_type}:{record_id}")],
    ])


def employee_select_kb(include_all=False) -> InlineKeyboardMarkup:
    from config import EMPLOYEES, MANAGERS
    buttons = []
    for uid, info in EMPLOYEES.items():
        buttons.append([InlineKeyboardButton(text=info["name"], callback_data=f"emp:{uid}")])
    for uid, info in MANAGERS.items():
        buttons.append([InlineKeyboardButton(text=info["name"], callback_data=f"emp:{uid}")])
    if include_all:
        buttons.append([InlineKeyboardButton(text="👥 All employees", callback_data="emp:ALL")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="emp:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def employee_multiselect_kb(selected_uids: list = None, prefix: str = "empms") -> InlineKeyboardMarkup:
    from config import EMPLOYEES, MANAGERS
    if selected_uids is None:
        selected_uids = []
    selected_uids = [str(u) for u in selected_uids]
    buttons = []
    all_users = {**EMPLOYEES, **MANAGERS}
    for uid, info in all_users.items():
        check = "✅" if str(uid) in selected_uids else "☐"
        buttons.append([InlineKeyboardButton(
            text=f"{check} {info['name']}",
            callback_data=f"{prefix}:{uid}"
        )])
    if selected_uids:
        buttons.append([InlineKeyboardButton(text=f"✅ Confirm ({len(selected_uids)} selected)", callback_data=f"{prefix}:confirm")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def gps_bike_names() -> list[str]:
    from config import BIKES_GPS
    return sorted({info["name"] for info in BIKES_GPS.values()})


def gps_odo_bike_kb() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(text="👥 All bikes", callback_data="gpsodo_b:ALL")]]
    for i, name in enumerate(gps_bike_names()):
        buttons.append([InlineKeyboardButton(text=name, callback_data=f"gpsodo_b:{i}")])
    buttons.append([
        InlineKeyboardButton(text="⬅️ Back", callback_data="gpsodo_x:back_menu"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="gpsodo_x:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def gps_odo_period_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Last 7 days", callback_data="gpsodo_p:7")],
        [InlineKeyboardButton(text="Last 30 days", callback_data="gpsodo_p:30")],
        [InlineKeyboardButton(text="Last 90 days", callback_data="gpsodo_p:90")],
        [
            InlineKeyboardButton(text="⬅️ Back", callback_data="gpsodo_x:back_bike"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="gpsodo_x:cancel"),
        ],
    ])

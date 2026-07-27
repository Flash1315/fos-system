import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8167126107:AAEvVn4xtsplB420RLSUiKVZ9QrNb0FBZ7E")

EMPLOYEES = {
    6800509015: {"name": "Alex",  "group_chat_id": -5071749039, "username": "Numbingtone"},
    7987029435: {"name": "Ray",   "group_chat_id": -4948478042, "username": "RayyGz"},
}

MANAGERS = {
    472060158: {"name": "Flash", "superadmin": True, "all_groups": True, "group_chat_id": -5144779427},
    1628758447: {"name": "Valori", "superadmin": True, "all_groups": True, "group_chat_id": -5144779427},
    1324809502: {"name": "RJ manager", "superadmin": False, "all_groups": True, "group_chat_id": -5144779427},
}

MANAGER_GROUP_CHAT_ID = -5144779427

GOOGLE_CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_ID = "1zANZkMAyrA-EspsVu4KkTR5-WAbpI2q-dC_NbMsaHCk"

SHEET_EXPENSES = "Expenses"
SHEET_INCOME   = "Income"
SHEET_PAYOUTS  = "Payouts"

BIKES_WORK = [
    "NMAX 2620 R&J",
    "NMAX 2623 Orange",
    "SCOOPY 2718 White",
    "FAZZIO 5412 R&J",
    "Yamaha Vixion 3626",
]

BIKES_RENTAL = [
    "Nmax 5548",
    "SCOOPY 2719 Green",
    "Nmax 6166",
    "Nmax 2613",
    "FAZZIO 2618 White",
    "FAZZIO 2619 Black",
    "NMAX 2624 Silver",
    "NMAX 2621",
    "Nmax 5579",
    "Yamaha Lexi 4930",
    "Nmax 2622 Tim",
]

BIKES = BIKES_WORK + BIKES_RENTAL + ["Other (enter manually)"]

INCOME_CATEGORIES = [
    "Rental",
    "Lesson",
    "Other (sales equipment etc.)",
]

TRAINING_SITES = [
    "Pekenku",
    "Pura Sada",
    "Toll Road",
    "GWK",
    "Custom",
]

EXPENSE_CATEGORIES = [
    "Bike service",
    "Aqua",
    "Training area renting",
    "Toll road top up",
    "Taxi",
    "Tires pressure / Wheel repair",
    "Other",
]

LESSON_GROUP_CHAT_ID = -1002835658216
LESSON_GROUP_THREAD_ID = None

CALENDAR_ID = "ptrideandjoy@gmail.com"
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Calendar color emoji → employee name mapping
CALENDAR_INSTRUCTOR_MAP = {
    "💙": "Ray",
    "💛": "Alex",
}

# Superadmin alerts group (Flash + Valori only)
SUPERADMIN_GROUP_CHAT_ID = -5264041780
FUEL_WARNING_MULTIPLIER = 1.3

# WanWay GPS API
WANWAY_APPID = "Flash13"
WANWAY_KEY = "rf5p7nd63cn7vaexh6t11mfzz72n6u06"
WANWAY_BASE_URL = "https://open.iopgps.com/api"

# GPS Bike mapping (IMEI -> name)
BIKES_GPS = {
    "860465041760962": {"name": "NMAX 2620 R&J",        "type": "work"},
    "860465041761150": {"name": "NMAX 2623 Orange",      "type": "work"},
    "860320055854799": {"name": "SCOOPY 2718 White",     "type": "work"},
    "860465042503403": {"name": "FAZZIO 5412 R&J",       "type": "work"},
    "860465043689276": {"name": "Nmax 5548",             "type": "rental"},
    "860320055854765": {"name": "SCOOPY 2719 Green",     "type": "rental"},
    "860465042008510": {"name": "Nmax 6166",             "type": "rental"},
    "860465042009070": {"name": "Nmax 2613",             "type": "rental"},
    "860465041760335": {"name": "FAZZIO 2618 White",     "type": "rental"},
    "860465041760442": {"name": "FAZZIO 2619 Black",     "type": "rental"},
    "860465041762307": {"name": "NMAX 2624 Silver",      "type": "rental"},
    "860465041762489": {"name": "NMAX 2621",             "type": "rental"},
    "860465042507875": {"name": "Nmax 5579",             "type": "rental"},
}

# Bikes without GPS
BIKES_NO_GPS = ["Yamaha Lexi 4930", "Yamaha Vixion 3626", "Nmax 2622 Tim"]

# Tracker expiry alerts (days before expiry)
TRACKER_ALERT_DAYS = [30, 14, 7, 3]

# Prefer env var (systemd). Empty env must not override the fallback.
GEMINI_API_KEY = (os.getenv("GEMINI_API_KEY") or "AIzaSyA8aosd__XRORdbO5C16CbzF7wMjljtxOQ").strip()
GMAIL_ADDRESS = "ptrideandjoy@gmail.com"
GMAIL_APP_PASSWORD = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()

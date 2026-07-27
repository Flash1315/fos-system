# RJ Spending Bot — Full Context for Cursor

## PROJECT OVERVIEW
Telegram bot for RIDE&JOY motorcycle school in Bali, Indonesia.
Owner: Flash (Sanur area, Bali)
Company: PT Ride and Joy
Founded: 2023
Services: Scooter, motorcycle, large-displacement instruction + bike rental

## SERVER
- Host: 104.248.147.174 (DigitalOcean, Ubuntu 22.04)
- Path: /root/rjbot/
- Start: systemctl restart rjbot
- Logs: journalctl -u rjbot -f --no-pager
- Venv: cd /root/rjbot && source venv/bin/activate
- GitHub: https://github.com/Flash1315/RJ-Spending-bot (private)
- Deploy from Mac: `./deploy.sh "description"` → push to `dev` → GitHub Actions SSH deploy
- Deploy workflow: `.github/workflows/deploy.yml` (pull + pip + systemctl restart)

## TECH STACK
- Python + aiogram 3.x
- Google Sheets (gspread) — main DB
- Google Calendar API — schedule (write access)
- APScheduler — reminders and scheduled tasks
- FastAPI + uvicorn — GPS API server (port 8001)
- Nginx — reverse proxy with SSL
- Gemini 2.5 Flash — AI (receipts, odometer, passport reading, text parsing)
- OpenAI Whisper — voice transcription (whisper-1, language="ru")

## CONFIG (/root/rjbot/config.py)
```python
# Employees (instructors)
EMPLOYEES = {
    6800509015: {"name": "Alex", "username": "Numbingtone", "group_chat_id": -5071749039},
    7987029435: {"name": "Ray", "username": "RayyGz", "group_chat_id": -4948478042},
}

# Managers — superadmin = Flash + Valori only
MANAGERS = {
    472060158: {"name": "Flash", "superadmin": True, "group_chat_id": -5144779427},
    1628758447: {"name": "Valori", "superadmin": True, "group_chat_id": -5144779427},
    1324809502: {"name": "RJ manager", "superadmin": False, "group_chat_id": -5144779427},
}

MANAGER_GROUP_CHAT_ID = -5144779427
LESSON_GROUP_CHAT_ID = -1002835658216  # forum group
SUPERADMIN_GROUP_CHAT_ID = -5264041780

# Lesson group topics (message_thread_id)
BIKE_RENTAL_TOPIC_ID = 2        # /2 — bike rental notifications
BIKE_ISSUES_TOPIC_ID = 3775     # /3775 — bike issues/damage reports

SPREADSHEET_ID = "1zANZkMAyrA-EspsVu4KkTR5-WAbpI2q-dC_NbMsaHCk"
CALENDAR_ID = "ptrideandjoy@gmail.com"
GOOGLE_CREDENTIALS_FILE = "credentials.json"

# GPS (WanWay) — see BIKES_GPS in config.py (13 tracked bikes)
# Bikes without GPS: Lexi 4930, Vixion 3626, Nmax 2622 Tim

# Email (invoice PDF) — NOT stored in config.py; set in systemd only:
# Environment=GMAIL_APP_PASSWORD=...   (Gmail App Password for ptrideandjoy@gmail.com)
```

**Systemd env (not in config.py):**
- `GMAIL_APP_PASSWORD` — Gmail App Password for `ptrideandjoy@gmail.com` (invoice email send). Set in `/etc/systemd/system/rjbot.service`, never commit to git.

## FILE STRUCTURE
```
/root/rjbot/
├── bot.py
├── config.py
├── gps_api.py
├── deploy.sh
├── bikes_config.json          ← dynamic Work/Rental bike lists
├── rental_parse_rules.json    ← Teach AI custom rules
├── rental_progress.json       ← delivery/return FSM pause (gitignored locally)
├── lesson_snapshot.json
├── lesson_alerts.json
├── assets/
│   ├── logo.png               ← invoice header logo (optional; text fallback)
│   └── qris.png               ← invoice QRIS payment QR (optional; empty box fallback)
├── handlers/
│   ├── expenses.py, income.py, fuel.py, transfers.py
│   ├── manager.py, common.py
│   ├── lesson.py, gps_handler.py
│   ├── rental.py, ai_rules.py
│   ├── delivery.py, return_rental.py
│   ├── active_rentals.py, rental_history.py
│   ├── bike_issues.py, bike_profile.py, bike_stats.py, full_stats.py
│   ├── invoice.py             ← manager invoice FSM (🧾 Invoice)
├── utils/
│   ├── sheets.py              ← sheet DB + balances + bike/rental helpers
│   ├── invoice_pdf.py         ← PDF generation (reportlab)
│   ├── period_stats.py        ← full statistics (Calendar + finances)
│   ├── bike_maintenance.py    ← service/repair log from comments + issues
│   ├── notify.py, calendar.py, calendar_manager.py
│   ├── lesson_monitor.py, reminders.py, fuel_check.py
│   ├── bikes.py, gps.py, gemini.py, receipt_ai.py, drive_upload.py
│   ├── rental_progress.py, purpose_flow.py, rental_rules.py
└── keyboards/kb.py
```

## GOOGLE SHEETS STRUCTURE

### Expenses (16 cols):
Date | Time | Category | Purpose | Rental ID | Place | Amount (IDR) | Mileage (km) | GPS Mileage | Receipt | Item photo | Employee | Comment | Payment Source | TG Message ID | Group Chat ID

### Income (13 cols):
Date | Time | Category | Purpose | Rental ID | Client name | No. of lessons | Amount (IDR) | Employee | Comment | Photo | TG Message ID | Cash / Transfer

Column `Cash / Transfer` auto-added on bot startup via `setup_sheets()` migration if missing.

### Payouts:
Date | Time | Type | Employee | Amount (IDR) | Cash / Transfer | Overpayment | TG Message ID

Payout types: `Expense payout`, `Income handover`, `Transfer to colleague` (colleague transfer also writes Income for recipient).

### Rentals, Bike Checklist, Bike Issues — see RENTAL_HEADERS / CHECKLIST_HEADERS / ISSUE_HEADERS in `utils/sheets.py`

### Invoices (9 cols):
Invoice No | Date | Client type | Client name | Contact | Items | Total (IDR) | Sent via | Created by

Invoice No format: `YYMMDD-NN` (auto-increment per day from sheet). Created via `setup_sheets()` if missing.

## FINANCIAL LOGIC (utils/sheets.py → get_all_balances)

Two independent balance tracks, each with **date + time** cutoff (`_row_after_cutoff`):

| Metric | Sheet rows | Cutoff (Payouts) |
|--------|------------|------------------|
| **Spendings** (owed to employee) | Expenses, Payment Source = `My pocket` | Last `Expense payout` |
| **Cash on hand** | Income − Expenses with `Cash on hand` | Last `Income handover` or `Transfer to colleague` |

- **Overpayment** on expense payout row (col Overpayment) reduces next-cycle owed.
- **Delivery payment** (Cash/Transfer, not Already paid) → also `append_income` with purpose Rental.
- **Income handover** uses `resolve_time_after_cutoff` so same-day income after handover counts correctly.
- **Transfer to colleague**: sender `Income handover` + recipient `Income` row.

Fuel confirm / expense confirm use `mgr_record_name` when superadmin records for employee.

## WHAT'S ALREADY DONE

### Finance flows:
- Expenses, Income, Fuel — full FSM with Back/Cancel
- **🧾 Add expense (AI)** — full AI flow (receipt-first); **💸 Expenses / ⛽ Fuel** — receipt photo auto-fills Comment via Gemini when skipped
- Purpose (Rental/Lesson/Office/Other) + Rental ID auto-link
- Payment source: My pocket / Cash on hand
- Receipts + item photos → Google Drive async
- Bike selection for Bike service / Tires / Fuel
- Mileage validation (cannot decrease); `get_last_mileage` = latest by date, not max km ever
- GPS Mileage from WanWay on fuel/service save
- Income: `payment_type` saved to sheet; `mgr_record_name` on confirm
- Delete expense: TG messages incl. media groups (comma-separated IDs)

### Manager panel:
- All balances (grouped), Pay expense, Receive income
- **🧾 Invoice** — create client invoice PDF (Individual / Company)
- Delete / Edit record, Add comment
- Manage bikes (Work ↔ Rental)
- GPS vs Odo report (superadmin)
- **Superadmin only (Flash + Valori):** Delete/Edit, GPS tools, Bike profile, Bike statistics, Full statistics, Manage calendar

### Superadmin analytics:
- **📈 Full statistics** — Calendar lessons + Income/Expenses/Rentals for period (7/30/90/all)
- **📊 Bike statistics** — fuel, service, mileage, cost/km, who used bike, mileage intervals, service log
- **🏍 Bike profile** — GPS status, revenue, fuel/service/rentals/issues, service & repair log
- **Service & repair log** (`utils/bike_maintenance.py`) — from expense **Comment** + Bike Issues description; Comment auto-filled from receipt AI when skipped

### GPS:
- 13 bikes tracked; alerts to SUPERADMIN_GROUP only
- Status, mileage today/month, cut/restore engine, live map
- Geofence, offline/voltage, speed, night driving, daily odo vs manual report

### Calendar/Schedule:
- Daily tomorrow schedule 21:30 WITA per instructor
- Cancellations, changes, vacation handling — LESSON_GROUP only, not after 22:30 WITA
- Manage calendar, Send schedule, My schedule (superadmin)

### Bike Rental — DONE (core):
- ✅ Book bike — AI (voice/text) + manual → Rentals `booked` → notify topic /2
- ✅ Teach AI rules + Remember fix
- ✅ Delivery (instructor) — all booked rentals, pause/resume, odometer, checklist, video, payment → `active` + Income if Cash/Transfer
- ✅ Return (instructor) — video, checklist, damages → `returned`; auto Bike Issue if damages
- ✅ Active rentals (manager) — list, card, edit fields
- ✅ Rental history — period filter, full card
- ✅ Bike Issues — report from menu + from return; notify topic /3775
- ⚠️ Passport OCR + voice booking — **DEFERRED** (see below)

### Invoices:
- `handlers/invoice.py` — full invoice creation flow for managers (FSM with Back/Cancel)
- `utils/invoice_pdf.py` — PDF generation via reportlab
- Design: white background, black accents, orange `#f66000` for invoice number and total
- `assets/logo.png` — RIDE&JOY logo (circular OK; scales to 50pt height in header)
- `assets/qris.png` — QRIS QR code for payment (vertical rectangle OK)
- Server assets path: `/root/rjbot/assets/` (logo.png, qris.png)
- If assets missing: text "RIDE & JOY" instead of logo; empty bordered square instead of QR
- Sheet **Invoices** in Google Sheets (auto-created on startup)
- Email delivery via smtp.gmail.com from ptrideandjoy@gmail.com (`GMAIL_APP_PASSWORD` in systemd)
- After PDF: send in Telegram, optional WhatsApp link, optional email to client

### SOS:
- 🆘 → superadmin + lesson group; location or cancel

## AI INTEGRATION (utils/gemini.py)

### Gemini (gemini-2.5-flash):
- `read_odometer_photo` → {odometer, fuel_bar}
- `read_receipt_full` → {amount, place, items, receipt_date, currency} — used by 🧾 Add expense (AI) and receipt photo steps in 💸 Expenses / ⛽ Fuel
- `read_receipt_amount` → {amount} (legacy helper; prefer `read_receipt_full`)
- `read_passport` → {name, passport_number, dob, expiry} — unreliable, deferred
- `parse_rental_request` → structured booking fields

### Receipt AI helper (`utils/receipt_ai.py`):
- After receipt photo in manual Expense/Fuel: fills **Comment** from items if user skipped comment
- If user comment and receipt items differ → inline choice: **Keep mine / Use receipt / Append both**
- Warns if receipt total ≠ entered amount (does not overwrite amount)

### Whisper:
- `parse_voice_message` → Russian text for rental AI flow
- Requires OPENAI_API_KEY in systemd service + venv package `openai`

## NOTIFICATIONS ROUTING (CRITICAL — DO NOT CHANGE WITHOUT EXPLICIT INSTRUCTION)
- Lesson changes / reminders: ONLY LESSON_GROUP_CHAT_ID (+ instructor tag)
- GPS alerts: ONLY SUPERADMIN_GROUP_CHAT_ID
- Financial alerts: MANAGER_GROUP + employee groups
- SOS: SUPERADMIN + LESSON_GROUP
- Bike Rental: LESSON_GROUP topic /2
- Bike Issues: LESSON_GROUP topic /3775

## CODING RULES (MANDATORY)
1. SURGICAL CHANGES ONLY
2. Never change chat IDs or routing without explicit instruction
3. Every step MUST have Back and Cancel
4. Language: English only in bot UI
5. Superadmin = Flash + Valori (`MANAGERS[uid]["superadmin"]`)
6. New sheet columns → update ALL constants in `utils/sheets.py` + migration in `setup_sheets()` if needed

## KNOWN LIMITATIONS
1. Old delivery payments before Income-on-delivery fix are not in Income sheet (manual backfill if needed)
2. Service log quality still depends on receipt photo quality; user-entered comment is kept over AI if not skipped
3. Passport OCR on phone photos — unreliable (manual name entry)
4. Very old Expense rows may lack Group Chat ID → TG delete on delete may fail

## DEFERRED — Bike Rental AI
- Passport OCR — use manual client name or skip passport step
- Voice/Whisper edge cases — Teach AI rules or manual fill
- Debug passport: `journalctl -u rjbot | grep -i passport`

## TASK QUEUE (priority)

### NEXT (recommended):
1. **Backfill** old rental Cash payments into Income (one-time sheet fix if needed)
2. Passport / voice polish — when needed, not blocking

### DONE (recent):
- ✅ **AI receipt** — dedicated 🧾 Add expense (AI) flow + auto Comment from receipt in 💸 Expenses and ⛽ Fuel (`utils/receipt_ai.py`)
- ✅ **PDF invoices** — manager flow + reportlab PDF + Invoices sheet + email/WhatsApp send

### THEN (roadmap):
- Rental contract PDF
- Export for accountant / investor (auto 1st of month)
- Bank statement AI (Permata PDF/Excel)
- Weekly AI receipt report (Saturday)
- AI Calendar — voice/text schedule commands
- AI Flow — natural language instead of button FSM

## BIKE RENTAL FLOWS (summary)

### Book (manager): `handlers/rental.py`
AI or manual → confirm → Rental ID → Rentals `booked` → topic /2

### Delivery (instructor): `handlers/delivery.py`
Pick rental → odometer (AI/manual) → video → checklist → helmets/payment/insurance → confirm → `active`, checklist row, Drive uploads, Income if paid, notify

### Return (instructor): `handlers/return_rental.py`
Pick active → video → odometer → checklist → damages? → extras? → `returned`, Bike Issue if damages

### Active rentals: `handlers/active_rentals.py`
List → card → edit instructor, location, dates, price, extras

### Rental history: `handlers/rental_history.py`
Period → list → full card (videos, checklist, passport link)

### Bike Issues: `handlers/bike_issues.py`
Any authorized user → bike → description → photos → sheet + topic /3775

## EXPENSE/INCOME PURPOSE
- Rental → bike list, auto rental_id
- Lesson / Office / Other

For **Bike service / Tires** after mileage, comment prompt asks what was repaired (feeds service log).

## RENTAL SOURCES
Ride&Joy | TravelAsk (many aliases — see `normalize_source_value` in rental.py)

## IMPORTANT NOTES
- Duration: inclusive (7 days from May 1 = last day May 7)
- 1 month = calendar month
- All timestamps WITA (UTC+8)
- Rental ID: R-2026-001 auto-increment
- `bikes_config.json` — Work/Rental lists editable via bot
- Deploy: push `dev` branch; do not run `/root/rjbot` commands on Mac

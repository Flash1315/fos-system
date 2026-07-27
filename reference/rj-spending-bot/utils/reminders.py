from datetime import datetime, timedelta
from utils.sheets import get_sheet, SHEET_EXPENSES, SHEET_INCOME, EXP_COL_EMPLOYEE
from config import EMPLOYEES

async def check_and_remind(bot):
    try:
        now = datetime.now()
        cutoff = now - timedelta(hours=24)
        
        ws_exp = get_sheet(SHEET_EXPENSES)
        ws_inc = get_sheet(SHEET_INCOME)
        exp_rows = ws_exp.get_all_values()
        inc_rows = ws_inc.get_all_values()
        
        for uid, info in EMPLOYEES.items():
            name = info["name"]
            last_entry = None
            
            for row in reversed(exp_rows):
                if len(row) > EXP_COL_EMPLOYEE and row[EXP_COL_EMPLOYEE] == name and row[0] not in ("", "Date", "TOTAL") and not row[0].startswith("="):
                    try:
                        last_entry = datetime.strptime(row[0], "%d.%m.%Y")
                        break
                    except:
                        pass
            
            if last_entry is None or last_entry < cutoff:
                try:
                    await bot.send_message(
                        chat_id=uid,
                        text=(
                            "⏰ <b>Reminder!</b>\n\n"
                            "You haven't logged any expenses in the last 24 hours.\n"
                            "Please don't forget to record your spending!"
                        ),
                        parse_mode="HTML"
                    )
                except Exception as e:
                    print(f"Reminder error for {name}: {e}")
    except Exception as e:
        print(f"check_and_remind error: {e}")


async def send_odometer_report(bot):
    """Daily report: bikes where manual odometer differs from GPS total by more than 5%."""
    try:
        import asyncio
        from config import SUPERADMIN_GROUP_CHAT_ID
        from utils.sheets import get_mileage_discrepancies

        loop = asyncio.get_event_loop()
        discrepancies = await loop.run_in_executor(None, get_mileage_discrepancies)
        if not discrepancies:
            return

        lines = ["🔍 <b>Daily Odometer Report</b>\n"]
        for d in discrepancies:
            lines.append(
                f"⚠️ {d['bike']}: manual {d['manual']} km, GPS {d['gps']} km, diff {d['diff_pct']}%"
            )
        await bot.send_message(
            chat_id=SUPERADMIN_GROUP_CHAT_ID,
            text="\n".join(lines),
            parse_mode="HTML",
        )
    except Exception as e:
        print(f"send_odometer_report error: {e}")

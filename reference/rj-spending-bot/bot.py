import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
from handlers import expenses, fuel, income, manager, common, transfers, lesson, gps_handler, rental, ai_rules, delivery, return_rental, bike_issues, active_rentals, rental_history, bike_profile, bike_stats, full_stats, invoice
from utils import cal_handler
from utils.reminders import check_and_remind, send_odometer_report
from utils.gps import get_expiring_trackers, check_bikes_outside_bali, run_gps_checks, acknowledge_alert
from utils.calendar import get_events_for_date, format_schedule_message
from utils.lesson_monitor import check_lesson_cancellations, acknowledge_alert as ack_lesson_alert

logging.basicConfig(level=logging.INFO)

async def send_daily_schedule(bot):
    try:
        from datetime import datetime, timedelta, timezone
        from config import LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID, EMPLOYEES, MANAGERS, CALENDAR_INSTRUCTOR_MAP
        from utils.calendar import parse_event
        WITA = timezone(timedelta(hours=8))
        tomorrow = datetime.now(WITA) + timedelta(days=1)
        date_label = tomorrow.strftime("%d.%m.%Y")
        events = get_events_for_date(tomorrow)
        today_events = get_events_for_date(datetime.now(WITA))

        # Check vacation alerts
        from utils.lesson_monitor import is_instructor_off, get_vacation_end_date
        from config import SUPERADMIN_GROUP_CHAT_ID
        for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
            tag = f"@{next((i.get('username','') for i in EMPLOYEES.values() if i.get('name')==name), name)}"
            # Starting vacation tomorrow
            if is_instructor_off(events, name) and not is_instructor_off(today_events, name):
                end_dt = get_vacation_end_date(events, name)
                end_str = end_dt.strftime("%d.%m.%Y") if end_dt else "?"
                msg = f"🏖 {tag} starts vacation tomorrow. Returns: {end_str}"
                await bot.send_message(chat_id=SUPERADMIN_GROUP_CHAT_ID, text=msg)
            # Ending vacation in 2 days
            if is_instructor_off(today_events, name):
                end_dt = get_vacation_end_date(today_events, name)
                if end_dt:
                    days_left = (end_dt - datetime.now(WITA).replace(tzinfo=None)).days
                    if days_left <= 2:
                        msg = f"📅 {tag} vacation ends in {days_left} day(s). Back to work soon!"
                        await bot.send_message(chat_id=SUPERADMIN_GROUP_CHAT_ID, text=msg)

        # Determine which instructors have lessons
        instructor_has_lessons = {name: False for emoji, name in CALENDAR_INSTRUCTOR_MAP.items()}
        for e in events:
            parsed = parse_event(e)
            for name in parsed.get("instructors", []):
                instructor_has_lessons[name] = True

        # Build instructor tags: find TG usernames from EMPLOYEES
        instructor_tg = {}
        for uid, info in EMPLOYEES.items():
            name = info.get("name", "")
            username = info.get("username", "")
            if username:
                instructor_tg[name] = f"@{username}"
            else:
                instructor_tg[name] = f"<b>{name}</b>"

        # Send per-instructor messages
        from utils.lesson_monitor import is_instructor_off
        for name, has_lessons in instructor_has_lessons.items():
            tag = instructor_tg.get(name, f"<b>{name}</b>")
            if is_instructor_off(events, name):
                text = f"{tag}\n\n🏖 Vacation / Day off tomorrow. Rest well!"
            elif has_lessons:
                text = format_schedule_message(
                    [e for e in events if name in [p for p in [parse_event(e).get("instructors", [])] for p in p]],
                    date_label, instructor_filter=name
                )
                text = f"{tag}\n\n" + text
            else:
                text = f"{tag}, no lessons tomorrow. Stay on call."
            send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
            if LESSON_GROUP_THREAD_ID:
                send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
            await bot.send_message(**send_kwargs)

    except Exception as e:
        print(f"Schedule send error: {e}")


async def check_tracker_expiry(bot):
    """Alert managers about expiring trackers."""
    try:
        from config import SUPERADMIN_GROUP_CHAT_ID, TRACKER_ALERT_DAYS
        expiring = await get_expiring_trackers(days=max(TRACKER_ALERT_DAYS))
        if not expiring:
            return
        for tracker in expiring:
            if tracker["days_left"] in TRACKER_ALERT_DAYS:
                emoji = "🚨" if tracker["days_left"] <= 7 else "⚠️"
                text = (
                    f"{emoji} <b>Tracker expiring soon!</b>\n\n"
                    f"🏍 <b>{tracker['name']}</b>\n"
                    f"📅 Expires: {tracker['expires']}\n"
                    f"⏳ Days left: <b>{tracker['days_left']}</b>"
                )
                await bot.send_message(
                    chat_id=SUPERADMIN_GROUP_CHAT_ID,
                    text=text,
                    parse_mode="HTML"
                )
    except Exception as e:
        print(f"check_tracker_expiry error: {e}")


async def check_geofence(bot):
    """Run all GPS checks — geofence, offline, voltage, speed, night."""
    try:
        from config import SUPERADMIN_GROUP_CHAT_ID
        await run_gps_checks(bot, SUPERADMIN_GROUP_CHAT_ID)
    except Exception as e:
        print(f"check_geofence error: {e}")


async def gps_ack_callback(callback: types.CallbackQuery):
    """Handle GPS alert acknowledgement."""
    from config import SUPERADMIN_GROUP_CHAT_ID, MANAGERS
    user_id = callback.from_user.id
    if user_id not in MANAGERS:
        await callback.answer("No permission.", show_alert=True)
        return

    data = callback.data  # gps_ack:type:imei
    parts = data.split(":")
    if len(parts) != 3:
        await callback.answer("Invalid data.")
        return

    _, alert_type, imei = parts
    acknowledge_alert(f"{imei}_{alert_type}")

    name = callback.from_user.first_name or "Manager"
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.reply(
        f"✅ Acknowledged by <b>{name}</b>",
        parse_mode="HTML"
    )
    await callback.answer("Acknowledged!")


async def morning_bike_status(bot):
    try:
        import time as _time
        from config import SUPERADMIN_GROUP_CHAT_ID
        from utils.gps import get_all_device_status, is_in_bali
        from datetime import datetime, timezone, timedelta
        WITA = timezone(timedelta(hours=8))
        now = datetime.now(WITA).strftime("%d.%m.%Y")
        devices = await get_all_device_status()
        if not devices:
            return
        work = [d for d in devices if d["type"] == "work"]
        lines = ["<b>Morning Status " + now + "</b>\n"]
        lines.append("<b>Work bikes:</b>")
        for d in work:
            offline_min = int((_time.time() - d["signalTime"]) / 60) if d["signalTime"] else 9999
            status = "OK" if offline_min < 60 else ("OFFLINE " + str(offline_min//60) + "h")
            voltage = (str(d["extVoltage"]/10) + "V") if d["extVoltage"] else "?"
            bali = "" if is_in_bali(d["lat"], d["lng"]) else " OUTSIDE BALI"
            lines.append("- " + d["name"] + ": " + status + " | " + voltage + bali)
        rental = [d for d in devices if d["type"] == "rental"]
        online_r = sum(1 for d in rental if d["signalTime"] and (_time.time() - d["signalTime"]) < 3600)
        lines.append("\nRental bikes: " + str(online_r) + "/" + str(len(rental)) + " online")
        await bot.send_message(chat_id=SUPERADMIN_GROUP_CHAT_ID, text="\n".join(lines), parse_mode="HTML")
    except Exception as e:
        print(f"morning_bike_status error: {e}")


async def evening_bike_report(bot):
    try:
        from config import SUPERADMIN_GROUP_CHAT_ID
        from utils.gps import get_all_device_status, get_device_mileage
        from utils.sheets import get_sheet
        from datetime import datetime, timezone, timedelta
        WITA = timezone(timedelta(hours=8))
        now = datetime.now(WITA)
        date_label = now.strftime("%d.%m.%Y")
        start_ts = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        end_ts = int(now.timestamp())
        devices = await get_all_device_status()
        work = [d for d in devices if d["type"] == "work"]
        lines = ["<b>Daily Report " + date_label + "</b>\n<b>Mileage today:</b>"]
        total_km = 0.0
        for d in work:
            km = await get_device_mileage(d["imei"], start_ts, end_ts)
            km = km or 0.0
            total_km += km
            lines.append("- " + d["name"] + ": " + str(round(km, 1)) + " km")
        lines.append("Total: " + str(round(total_km, 1)) + " km\n")
        try:
            from utils.sheets import EXP_COL_EMPLOYEE, EXP_COL_PLACE, EXP_COL_AMOUNT, EXP_COL_CATEGORY
            ws = get_sheet("Expenses")
            rows = ws.get_all_values()
            today = now.strftime("%d.%m.%Y")
            fuel_today = [r for r in rows if len(r) > EXP_COL_AMOUNT and r[0] == today and len(r) > EXP_COL_CATEGORY and r[EXP_COL_CATEGORY] == "Bensin"]
            if fuel_today:
                lines.append("<b>Fuel today:</b>")
                for r in fuel_today:
                    lines.append("- " + (r[EXP_COL_EMPLOYEE] if len(r) > EXP_COL_EMPLOYEE else "?") + ": " + (r[EXP_COL_PLACE] if len(r) > EXP_COL_PLACE else "?") + " — " + (r[EXP_COL_AMOUNT] if len(r) > EXP_COL_AMOUNT else "?"))
            else:
                lines.append("No fuel entries today")
        except:
            pass
        await bot.send_message(chat_id=SUPERADMIN_GROUP_CHAT_ID, text="\n".join(lines), parse_mode="HTML")
    except Exception as e:
        print(f"evening_bike_report error: {e}")

async def main():
    from config import GEMINI_API_KEY, OPENAI_API_KEY
    print(
        "RJ bot starting — "
        f"BOT_TOKEN={'OK' if BOT_TOKEN else 'MISSING'}, "
        f"GEMINI={'OK' if GEMINI_API_KEY else 'MISSING'}, "
        f"OPENAI={'OK' if OPENAI_API_KEY else 'MISSING (Whisper/passport fallback off)'}"
    )

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    from utils.sheets import setup_sheets
    setup_sheets()

    dp.include_router(invoice.router)
    dp.include_router(common.router)
    dp.include_router(cal_handler.router)
    dp.include_router(expenses.router)
    dp.include_router(fuel.router)
    dp.include_router(income.router)
    dp.include_router(manager.router)
    dp.include_router(transfers.router)
    dp.include_router(lesson.router)
    dp.include_router(gps_handler.router)
    dp.include_router(ai_rules.router)
    dp.include_router(rental.router)
    dp.include_router(active_rentals.router)
    dp.include_router(rental_history.router)
    dp.include_router(bike_profile.router)
    dp.include_router(bike_stats.router)
    dp.include_router(full_stats.router)
    dp.include_router(delivery.router)
    dp.include_router(return_rental.router)
    dp.include_router(bike_issues.router)
    dp.callback_query.register(gps_ack_callback, F.data.startswith("gps_ack:"))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_remind, "cron", hour=12, minute=0, args=[bot])
    scheduler.add_job(send_daily_schedule, "cron", hour=13, minute=30, args=[bot])
    scheduler.add_job(check_tracker_expiry, "cron", hour=9, minute=0, args=[bot])
    scheduler.add_job(check_geofence, "interval", minutes=15, args=[bot])
    scheduler.add_job(check_lesson_cancellations, "interval", minutes=5, args=[bot])
    scheduler.add_job(morning_bike_status, "cron", hour=0, minute=0, args=[bot])
    scheduler.add_job(evening_bike_report, "cron", hour=13, minute=0, args=[bot])
    scheduler.add_job(send_odometer_report, "cron", hour=12, minute=0, args=[bot])  # 20:00 WITA (UTC+8)
    scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


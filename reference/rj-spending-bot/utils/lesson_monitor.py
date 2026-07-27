import json
import os
from datetime import datetime, timedelta, timezone

SNAPSHOT_FILE = "/root/rjbot/lesson_snapshot.json"
PENDING_ALERTS_FILE = "/root/rjbot/lesson_alerts.json"
WITA = timezone(timedelta(hours=8))

def load_snapshot():
    if os.path.exists(SNAPSHOT_FILE):
        with open(SNAPSHOT_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_snapshot(snapshot):
    with open(SNAPSHOT_FILE, 'w') as f:
        json.dump(snapshot, f, indent=2)

def load_alerts():
    if os.path.exists(PENDING_ALERTS_FILE):
        with open(PENDING_ALERTS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_alerts(alerts):
    with open(PENDING_ALERTS_FILE, 'w') as f:
        json.dump(alerts, f, indent=2)

def is_instructor_off(events, instructor_name):
    """Check if instructor has a vacation or day-off event."""
    from config import CALENDAR_INSTRUCTOR_MAP
    instructor_emoji = None
    for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
        if name == instructor_name:
            instructor_emoji = emoji
            break
    for e in events:
        summary = e.get('summary', '')
        start = e.get('start', {})
        is_allday = 'date' in start and 'dateTime' not in start
        if not is_allday:
            continue
        summary_lower = summary.lower()
        has_vacation = 'vacation' in summary_lower
        has_dof = 'day off' in summary_lower
        has_instructor = (instructor_emoji and instructor_emoji in summary) or instructor_name.lower() in summary_lower
        if (has_vacation or has_dof) and has_instructor:
            return True
    return False

def get_vacation_end_date(events, instructor_name):
    """Get end date of instructor vacation."""
    from datetime import datetime
    from config import CALENDAR_INSTRUCTOR_MAP
    instructor_emoji = None
    for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
        if name == instructor_name:
            instructor_emoji = emoji
            break
    for e in events:
        summary = e.get('summary', '')
        start = e.get('start', {})
        end = e.get('end', {})
        is_allday = 'date' in start and 'dateTime' not in start
        if not is_allday:
            continue
        summary_lower = summary.lower()
        has_vacation = 'vacation' in summary_lower
        has_dof = 'day off' in summary_lower
        has_instructor = (instructor_emoji and instructor_emoji in summary) or instructor_name.lower() in summary_lower
        if (has_vacation or has_dof) and has_instructor:
            end_date = end.get('date', '')
            if end_date:
                return datetime.strptime(end_date, '%Y-%m-%d')
    return None

def acknowledge_alert(event_id):
    alerts = load_alerts()
    if event_id in alerts:
        del alerts[event_id]
        save_alerts(alerts)


def _normalize_start(start_str):
    if not start_str:
        return ""
    try:
        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=WITA)
        return dt.astimezone(WITA).strftime("%Y-%m-%dT%H:%M")
    except Exception:
        return start_str


def _parse_start_dt(start_str):
    if not start_str:
        return None
    try:
        dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=WITA)
        return dt.astimezone(WITA).replace(second=0, microsecond=0)
    except Exception:
        return None


def _start_changed(old_start, new_start):
    old_dt = _parse_start_dt(old_start)
    new_dt = _parse_start_dt(new_start)
    if old_dt is None or new_dt is None:
        return old_start != new_start
    return old_dt != new_dt


SCHEDULE_QUIET_START = (21, 30)  # 21:30 WITA — no lesson alerts after this
SCHEDULE_QUIET_END = (7, 0)      # 07:00 WITA — alerts resume


def _is_after_schedule_cutoff(now):
    """True during quiet hours 21:30–06:59 WITA (blocks added/changed/cancelled alerts)."""
    mins = now.hour * 60 + now.minute
    quiet_from = SCHEDULE_QUIET_START[0] * 60 + SCHEDULE_QUIET_START[1]
    quiet_until = SCHEDULE_QUIET_END[0] * 60 + SCHEDULE_QUIET_END[1]
    return mins >= quiet_from or mins < quiet_until


def _get_instructors_from_summary(summary):
    from config import CALENDAR_INSTRUCTOR_MAP
    return [name for emoji, name in CALENDAR_INSTRUCTOR_MAP.items() if emoji in summary]


def _format_instructor_tags(summary):
    from config import EMPLOYEES
    tags = []
    for name in _get_instructors_from_summary(summary):
        for info in EMPLOYEES.values():
            if info.get("name") == name:
                username = info.get("username", "")
                tags.append(f"@{username}" if username else f"<b>{name}</b>")
                break
    return " ".join(tags)


async def _send_instructor_alerts(bot, summary, text, reply_markup=None):
    from config import LESSON_GROUP_CHAT_ID, LESSON_GROUP_THREAD_ID
    send_kwargs = {"chat_id": LESSON_GROUP_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        send_kwargs["reply_markup"] = reply_markup
    if LESSON_GROUP_THREAD_ID:
        send_kwargs["message_thread_id"] = LESSON_GROUP_THREAD_ID
    await bot.send_message(**send_kwargs)


def _schedule_alert_key(edata, change_type="added"):
    return f"sched_{edata.get('id', '')}_{change_type}_{_normalize_start(edata.get('start', ''))}"


def _should_send_schedule_alert(alerts, key, now):
    last_sent = alerts.get(key, {}).get("last_sent", 0)
    return (now.timestamp() - last_sent) >= 600


def events_to_snapshot(events):
    """Convert events list to dict keyed by event id."""
    result = {}
    for e in events:
        eid = e.get('id', '')
        if eid:
            raw_start = e.get('start', {}).get('dateTime', e.get('start', {}).get('date', ''))
            result[eid] = {
                'id': eid,
                'summary': e.get('summary', ''),
                'start': _normalize_start(raw_start) or raw_start,
                'end': e.get('end', {}).get('dateTime', e.get('end', {}).get('date', '')),
                'colorId': e.get('colorId', ''),
            }
    return result

async def check_lesson_cancellations(bot):
    try:
        from utils.calendar import get_events_for_date

        now = datetime.now(WITA)
        # Check today and tomorrow
        dates = [now, now + timedelta(days=1)]
        current_events = {}
        for d in dates:
            evts = get_events_for_date(d)
            current_events.update(events_to_snapshot(evts))

        snapshot_existed = os.path.exists(SNAPSHOT_FILE)
        old_snapshot = load_snapshot()

        # Find cancelled, new and changed events
        cancelled = []
        added = []
        changed = []

        for eid, edata in old_snapshot.items():
            if eid not in current_events:
                try:
                    start_str = edata.get('start', '')
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=WITA)
                    if start_dt > now:
                        cancelled.append(edata)
                except:
                    pass

        for eid, edata in current_events.items():
            if eid not in old_snapshot:
                try:
                    start_str = edata.get('start', '')
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=WITA)
                    if start_dt > now:
                        added.append(edata)
                except:
                    pass
            elif _start_changed(old_snapshot[eid].get('start'), edata.get('start')):
                try:
                    start_str = edata.get('start', '')
                    start_dt = datetime.fromisoformat(start_str)
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=WITA)
                    if start_dt > now:
                        changed.append({'old': old_snapshot[eid], 'new': edata})
                except:
                    pass

        # Save new snapshot
        save_snapshot(current_events)

        if not snapshot_existed:
            return

        alerts = load_alerts()
        quiet = _is_after_schedule_cutoff(now)

        # Send schedule change alerts (rate-limited, not during quiet hours)
        if not quiet:
            for edata in added:
                key = _schedule_alert_key(edata, "added")
                if _should_send_schedule_alert(alerts, key, now):
                    await send_schedule_change_alert(bot, edata, change_type='added')
                    alerts[key] = {"last_sent": now.timestamp()}
            for item in changed:
                edata = item['new']
                key = _schedule_alert_key(edata, "changed")
                if _should_send_schedule_alert(alerts, key, now):
                    await send_schedule_change_alert(bot, edata, change_type='changed', old_data=item['old'])
                    alerts[key] = {"last_sent": now.timestamp()}

            # Resend pending cancellation reminders (every 10 min)
            for eid, alert_data in list(alerts.items()):
                if not isinstance(alert_data, dict) or "event" not in alert_data:
                    continue
                last_sent = alert_data.get("last_sent", 0)
                if not last_sent:
                    await send_cancellation_alert(bot, alert_data["event"], resend=False)
                    alerts[eid]["last_sent"] = now.timestamp()
                elif (now.timestamp() - last_sent) >= 600:
                    await send_cancellation_alert(bot, alert_data["event"], resend=True)
                    alerts[eid]["last_sent"] = now.timestamp()

        for edata in cancelled:
            eid = edata['id']
            if quiet:
                if eid not in alerts or not isinstance(alerts.get(eid), dict) or "event" not in alerts[eid]:
                    alerts[eid] = {'event': edata, 'last_sent': 0}
                continue
            alerts[eid] = {
                'event': edata,
                'last_sent': now.timestamp()
            }
            await send_cancellation_alert(bot, edata, resend=False)
        save_alerts(alerts)

    except Exception as e:
        print(f"check_lesson_cancellations error: {e}")

async def send_schedule_change_alert(bot, edata, change_type='added', old_data=None):
    try:
        summary = edata.get('summary', 'Unknown lesson')
        start = edata.get('start', '')[:16].replace('T', ' ')

        instructor_tag = _format_instructor_tags(summary)

        if change_type == 'added':
            emoji = "➕"
            title = "New lesson added!"
            text = f"{emoji} <b>{title}</b>\n\n📌 {summary}\n🕐 {start}"
        else:
            old_start = old_data.get('start', '')[:16].replace('T', ' ') if old_data else '?'
            emoji = "🔄"
            title = "Lesson rescheduled!"
            text = f"{emoji} <b>{title}</b>\n\n📌 {summary}\n🕐 {old_start} → {start}"

        if instructor_tag:
            text += f"\n👤 {instructor_tag}"

        await _send_instructor_alerts(bot, summary, text)

    except Exception as e:
        print(f"send_schedule_change_alert error: {e}")

async def send_cancellation_alert(bot, edata, resend=False):
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

        summary = edata.get('summary', 'Unknown lesson')
        start = edata.get('start', '')
        eid = edata.get('id', '')

        instructor_tag = _format_instructor_tags(summary)

        prefix = "🔁 <b>Reminder:</b> " if resend else "❌ <b>Lesson cancelled!</b>\n\n"
        text = (
            f"{prefix}"
            f"📌 {summary}\n"
            f"🕐 {start[:16].replace('T', ' ') if start else '—'}\n"
        )
        if instructor_tag:
            text += f"👤 Instructor: {instructor_tag}\n"
        text += "\nPlease acknowledge."

        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Acknowledged", callback_data=f"lesson_ack:{eid}")
        ]])

        await _send_instructor_alerts(bot, summary, text, reply_markup=kb)

    except Exception as e:
        print(f"send_cancellation_alert error: {e}")

from datetime import datetime, timedelta, timezone
from utils.calendar import get_calendar_service, WITA, CALENDAR_ID

def get_upcoming_lessons(days_ahead=7):
    """Get upcoming lessons for the next N days."""
    try:
        service = get_calendar_service()
        now = datetime.now(WITA)
        end = now + timedelta(days=days_ahead)
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        items = events.get('items', [])
        # Filter out all-day events (vacations, day-offs)
        return [e for e in items if 'dateTime' in e.get('start', {})]
    except Exception as e:
        print(f"get_upcoming_lessons error: {e}")
        return []

def cancel_lesson(event_id):
    """Delete event from calendar."""
    try:
        service = get_calendar_service()
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        return True
    except Exception as e:
        print(f"cancel_lesson error: {e}")
        return False

def reschedule_lesson(event_id, new_start_dt, new_end_dt):
    """Update event start/end time."""
    try:
        service = get_calendar_service()
        event = service.events().get(calendarId=CALENDAR_ID, eventId=event_id).execute()
        tz_str = event['start'].get('timeZone', 'Asia/Makassar')
        event['start'] = {'dateTime': new_start_dt.isoformat(), 'timeZone': tz_str}
        event['end'] = {'dateTime': new_end_dt.isoformat(), 'timeZone': tz_str}
        updated = service.events().update(calendarId=CALENDAR_ID, eventId=event_id, body=event).execute()
        return True
    except Exception as e:
        print(f"reschedule_lesson error: {e}")
        return False

def add_lesson(summary, start_dt, end_dt, description="", color_id=None):
    """Create new event in calendar."""
    try:
        service = get_calendar_service()
        event = {
            'summary': summary,
            'description': description,
            'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Makassar'},
            'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Makassar'},
        }
        if color_id:
            event['colorId'] = color_id
        created = service.events().insert(calendarId=CALENDAR_ID, body=event).execute()
        return created.get('id')
    except Exception as e:
        print(f"add_lesson error: {e}")
        return None

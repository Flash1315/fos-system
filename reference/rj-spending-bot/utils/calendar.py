from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
from config import GOOGLE_CREDENTIALS_FILE, CALENDAR_ID, CALENDAR_SCOPES

# Bali timezone UTC+8
WITA = timezone(timedelta(hours=8))

_calendar_service = None

def get_calendar_service():
    global _calendar_service
    if _calendar_service is None:
        creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=CALENDAR_SCOPES)
        _calendar_service = build('calendar', 'v3', credentials=creds)
    return _calendar_service

def get_events_for_date(date: datetime):
    """Get all events for a specific date in Bali time."""
    try:
        service = get_calendar_service()
        start = datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=WITA)
        end = datetime(date.year, date.month, date.day, 23, 59, 59, tzinfo=WITA)
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events.get('items', [])
    except Exception as e:
        print(f"Calendar error: {e}")
        return []


def get_events_for_period(days: int = 30):
    """Get timed calendar events for the last N days (0 = since 2023-01-01)."""
    try:
        service = get_calendar_service()
        now = datetime.now(WITA)
        end = now.replace(hour=23, minute=59, second=59, microsecond=0)
        if days and days > 0:
            start = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = datetime(2023, 1, 1, tzinfo=WITA)
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=2500,
        ).execute()
        return [e for e in events.get('items', []) if 'dateTime' in e.get('start', {})]
    except Exception as e:
        print(f"get_events_for_period error: {e}")
        return []

def get_current_or_upcoming_event(minutes_ahead=30):
    """Get the next upcoming event regardless of time."""
    try:
        service = get_calendar_service()
        now = datetime.now(WITA)
        events = service.events().list(
            calendarId=CALENDAR_ID,
            timeMin=now.isoformat(),
            singleEvents=True,
            orderBy='startTime',
            maxResults=1
        ).execute()
        return events.get('items', [])
    except Exception as e:
        print(f"Calendar error: {e}")
        return []

def parse_event(event):
    """Parse event into readable dict."""
    summary = event.get('summary', 'No title')
    description = event.get('description', '')
    start = event.get('start', {})
    end = event.get('end', {})
    start_dt = start.get('dateTime', start.get('date', ''))
    end_dt = end.get('dateTime', end.get('date', ''))
    
    # Format times
    start_time = ""
    end_time = ""
    duration_min = 0
    try:
        s = datetime.fromisoformat(start_dt)
        e = datetime.fromisoformat(end_dt)
        start_time = s.strftime('%H:%M')
        end_time = e.strftime('%H:%M')
        duration_min = int((e - s).total_seconds() / 60)
    except:
        pass
    
    # Parse description fields
    lesson_number = ""
    pickup_info = ""
    pickup_link = ""
    training_site = ""
    bike = ""
    
    if description:
        lines = description.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Lesson number e.g. "3/4"
            if '/' in line and len(line) <= 5 and line.replace('/', '').isdigit():
                lesson_number = line
            # Pickup line
            elif 'picks up at' in line.lower() or 'pick up at' in line.lower():
                pickup_info = line
                # Extract link
                for word in line.split():
                    if word.startswith('http'):
                        pickup_link = word
            # Training site
            elif 'training site' in line.lower():
                training_site = line.split(':', 1)[-1].strip()
            # Bike
            elif 'bike' in line.lower():
                bike = line.split(':', 1)[-1].strip()
    
    # Detect instructors from emoji in summary
    from config import CALENDAR_INSTRUCTOR_MAP
    instructors = []
    for emoji, name in CALENDAR_INSTRUCTOR_MAP.items():
        if emoji in summary:
            instructors.append(name)
    
    return {
        'summary': summary,
        'start_time': start_time,
        'end_time': end_time,
        'duration_min': duration_min,
        'color_id': event.get('colorId', ''),
        'raw_start': start_dt,
        'raw_end': end_dt,
        'lesson_number': lesson_number,
        'pickup_info': pickup_info,
        'pickup_link': pickup_link,
        'training_site': training_site,
        'bike': bike,
        'description': description,
        'instructors': instructors,
    }

def format_schedule_message(events, date_label="tomorrow", instructor_filter=None):
    """Format events list into a readable schedule message.
    instructor_filter: if set, only show events for this instructor name.
    """
    parsed = [parse_event(e) for e in events]
    if instructor_filter:
        parsed = [p for p in parsed if not p['instructors'] or instructor_filter in p['instructors']]
    
    if not parsed:
        return f"📅 No lessons scheduled for {date_label}."
    
    text = f"📅 <b>Schedule for {date_label}</b>\n\n"
    for p in parsed:
        text += f"🕐 {p['start_time']}–{p['end_time']} ({p['duration_min']} min)\n"
        text += f"📌 {p['summary']}"
        if p['lesson_number']:
            text += f" — lesson {p['lesson_number']}"
        text += "\n"
        if p['pickup_info']:
            text += f"🚗 {p['pickup_info']}\n"
        if p['training_site']:
            text += f"📍 {p['training_site']}\n"
        if p['bike']:
            text += f"🏍 {p['bike']}\n"
        text += "\n"
    return text.strip()

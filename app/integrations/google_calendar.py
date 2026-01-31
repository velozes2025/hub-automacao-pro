"""Google Calendar integration — create, read, update, delete events in real-time.

The bot can:
- Create events with attendees
- List upcoming events
- Check availability (free/busy)
- Update existing events
- Delete/cancel events

For the service account to manage a SPECIFIC calendar, share it with:
    quantrexhubclaude@quantrex-486005.iam.gserviceaccount.com
Or use GOOGLE_CALENDAR_ID env var to set the default calendar.
"""

import os
import logging
from datetime import datetime, timedelta, timezone

from app.integrations.google_client import get_calendar_service

log = logging.getLogger('integrations.calendar')

# Default calendar ID — 'primary' uses the service account's own calendar.
# Set GOOGLE_CALENDAR_ID to use a shared calendar instead.
DEFAULT_CALENDAR_ID = os.getenv('GOOGLE_CALENDAR_ID', 'primary')
TIMEZONE = os.getenv('TIMEZONE', 'America/Sao_Paulo')


def create_event(summary, start_datetime, end_datetime=None, description='',
                 attendees=None, calendar_id=None):
    """Create a calendar event. Returns event ID and link.

    start_datetime/end_datetime: ISO format string or datetime object.
    attendees: list of email strings.
    """
    service = get_calendar_service()
    if not service:
        return None

    cal_id = calendar_id or DEFAULT_CALENDAR_ID

    if isinstance(start_datetime, str):
        start_dt = datetime.fromisoformat(start_datetime)
    else:
        start_dt = start_datetime

    if end_datetime is None:
        end_dt = start_dt + timedelta(hours=1)
    elif isinstance(end_datetime, str):
        end_dt = datetime.fromisoformat(end_datetime)
    else:
        end_dt = end_datetime

    event_body = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': TIMEZONE,
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': TIMEZONE,
        },
    }

    if attendees:
        event_body['attendees'] = [{'email': e} for e in attendees]

    try:
        event = service.events().insert(
            calendarId=cal_id, body=event_body,
        ).execute()
        event_id = event.get('id', '')
        link = event.get('htmlLink', '')
        log.info(f'[CALENDAR] Created event: {summary} at {start_dt} -> {event_id}')
        return {'id': event_id, 'link': link, 'summary': summary}
    except Exception as e:
        log.error(f'[CALENDAR] Create event failed: {e}')
        return None


def list_upcoming(max_results=10, calendar_id=None):
    """List upcoming events from now. Returns list of event dicts."""
    service = get_calendar_service()
    if not service:
        return None

    cal_id = calendar_id or DEFAULT_CALENDAR_ID
    now = datetime.now(timezone.utc).isoformat()

    try:
        result = service.events().list(
            calendarId=cal_id,
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime',
        ).execute()
        events = result.get('items', [])
        parsed = []
        for ev in events:
            start = ev.get('start', {}).get('dateTime', ev.get('start', {}).get('date', ''))
            parsed.append({
                'id': ev.get('id'),
                'summary': ev.get('summary', '(sem titulo)'),
                'start': start,
                'description': ev.get('description', ''),
                'attendees': [a.get('email') for a in ev.get('attendees', [])],
            })
        log.info(f'[CALENDAR] Listed {len(parsed)} upcoming events')
        return parsed
    except Exception as e:
        log.error(f'[CALENDAR] List events failed: {e}')
        return None


def check_availability(date_str, time_str, duration_minutes=60, calendar_id=None):
    """Check if a time slot is free. Returns True if available.

    date_str: DD/MM/YYYY
    time_str: HH:MM
    """
    service = get_calendar_service()
    if not service:
        return None

    cal_id = calendar_id or DEFAULT_CALENDAR_ID

    try:
        dt = datetime.strptime(f'{date_str} {time_str}', '%d/%m/%Y %H:%M')
    except ValueError:
        return None

    # Make timezone-aware (Sao Paulo = UTC-3)
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(TIMEZONE)
    start_dt = dt.replace(tzinfo=tz)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    try:
        body = {
            'timeMin': start_dt.isoformat(),
            'timeMax': end_dt.isoformat(),
            'items': [{'id': cal_id}],
        }
        result = service.freebusy().query(body=body).execute()
        busy = result.get('calendars', {}).get(cal_id, {}).get('busy', [])
        available = len(busy) == 0
        log.info(f'[CALENDAR] Availability {date_str} {time_str}: {"free" if available else "busy"}')
        return available
    except Exception as e:
        log.error(f'[CALENDAR] Availability check failed: {e}')
        return None


def update_event(event_id, calendar_id=None, **fields):
    """Update an existing event. Fields: summary, description, start, end."""
    service = get_calendar_service()
    if not service:
        return False

    cal_id = calendar_id or DEFAULT_CALENDAR_ID

    try:
        event = service.events().get(calendarId=cal_id, eventId=event_id).execute()

        if 'summary' in fields:
            event['summary'] = fields['summary']
        if 'description' in fields:
            event['description'] = fields['description']

        service.events().update(
            calendarId=cal_id, eventId=event_id, body=event,
        ).execute()
        log.info(f'[CALENDAR] Updated event: {event_id}')
        return True
    except Exception as e:
        log.error(f'[CALENDAR] Update event failed: {e}')
        return False


def delete_event(event_id, calendar_id=None):
    """Delete/cancel an event."""
    service = get_calendar_service()
    if not service:
        return False

    cal_id = calendar_id or DEFAULT_CALENDAR_ID

    try:
        service.events().delete(calendarId=cal_id, eventId=event_id).execute()
        log.info(f'[CALENDAR] Deleted event: {event_id}')
        return True
    except Exception as e:
        log.error(f'[CALENDAR] Delete event failed: {e}')
        return False


def find_event_by_phone(phone, calendar_id=None, max_results=50):
    """Find upcoming events that mention a phone number in description."""
    events = list_upcoming(max_results=max_results, calendar_id=calendar_id)
    if not events:
        return None
    matches = [e for e in events if phone in (e.get('description') or '')]
    return matches if matches else None

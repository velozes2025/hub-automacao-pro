"""Google Service Account authentication — shared by Sheets, Calendar, Gmail.

Usage:
    from app.integrations.google_client import get_sheets_service, get_calendar_service, get_gmail_service
"""

import os
import json
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger('integrations.google')

_CREDENTIALS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'credentials', 'google-service-account.json',
)

# Scopes for Sheets + Calendar (Gmail uses SMTP instead)
_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
]

_credentials = None
_sheets_service = None
_calendar_service = None


def _get_credentials():
    """Load service account credentials."""
    if not os.path.exists(_CREDENTIALS_PATH):
        log.error(f'Google credentials not found: {_CREDENTIALS_PATH}')
        return None
    try:
        creds = service_account.Credentials.from_service_account_file(
            _CREDENTIALS_PATH, scopes=_SCOPES,
        )
        return creds
    except Exception as e:
        log.error(f'Failed to load Google credentials: {e}')
        return None


def get_sheets_service():
    """Return Google Sheets API v4 service (singleton)."""
    global _sheets_service
    if _sheets_service:
        return _sheets_service
    creds = _get_credentials()
    if not creds:
        return None
    try:
        _sheets_service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
        log.info('[GOOGLE] Sheets service initialized')
        return _sheets_service
    except Exception as e:
        log.error(f'Failed to initialize Sheets service: {e}')
        return None


def get_calendar_service():
    """Return Google Calendar API v3 service (singleton)."""
    global _calendar_service
    if _calendar_service:
        return _calendar_service
    creds = _get_credentials()
    if not creds:
        return None
    try:
        _calendar_service = build('calendar', 'v3', credentials=creds, cache_discovery=False)
        log.info('[GOOGLE] Calendar service initialized')
        return _calendar_service
    except Exception as e:
        log.error(f'Failed to initialize Calendar service: {e}')
        return None


def is_configured():
    """Check if Google credentials file exists."""
    return os.path.exists(_CREDENTIALS_PATH)


def get_service_account_email():
    """Return the service account email for sharing instructions."""
    try:
        with open(_CREDENTIALS_PATH) as f:
            data = json.load(f)
        return data.get('client_email', '')
    except Exception:
        return ''

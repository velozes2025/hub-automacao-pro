"""Google Sheets integration — read, write, append, update in real-time.

The bot can:
- Create new spreadsheets
- Read data from any range
- Append rows (e.g., new leads)
- Update specific cells
- List all sheets in a spreadsheet

For the bot to access an EXISTING spreadsheet, share it with:
    quantrexhubclaude@quantrex-486005.iam.gserviceaccount.com
"""

import logging
from app.integrations.google_client import get_sheets_service

log = logging.getLogger('integrations.sheets')


def create_spreadsheet(title, sheet_names=None):
    """Create a new spreadsheet. Returns spreadsheet ID and URL."""
    service = get_sheets_service()
    if not service:
        return None

    body = {'properties': {'title': title}}
    if sheet_names:
        body['sheets'] = [
            {'properties': {'title': name}} for name in sheet_names
        ]

    try:
        result = service.spreadsheets().create(body=body).execute()
        spreadsheet_id = result['spreadsheetId']
        url = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}'
        log.info(f'[SHEETS] Created: {title} -> {url}')
        return {'id': spreadsheet_id, 'url': url, 'title': title}
    except Exception as e:
        log.error(f'[SHEETS] Create failed: {e}')
        return None


def read_range(spreadsheet_id, range_notation):
    """Read values from a range. Returns list of rows (each row is a list).

    range_notation examples: 'Sheet1!A1:D10', 'Leads!A:F', 'A1:Z'
    """
    service = get_sheets_service()
    if not service:
        return None

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_notation,
        ).execute()
        values = result.get('values', [])
        log.info(f'[SHEETS] Read {len(values)} rows from {range_notation}')
        return values
    except Exception as e:
        log.error(f'[SHEETS] Read failed: {e}')
        return None


def write_range(spreadsheet_id, range_notation, values):
    """Write values to a range (overwrites existing data).

    values: list of lists, e.g. [['Name', 'Phone'], ['John', '123']]
    """
    service = get_sheets_service()
    if not service:
        return False

    try:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_notation,
            valueInputOption='USER_ENTERED',
            body={'values': values},
        ).execute()
        log.info(f'[SHEETS] Wrote {len(values)} rows to {range_notation}')
        return True
    except Exception as e:
        log.error(f'[SHEETS] Write failed: {e}')
        return False


def append_rows(spreadsheet_id, range_notation, rows):
    """Append rows to the end of a range (auto-detects next empty row).

    rows: list of lists, e.g. [['John', '123', 'new']]
    """
    service = get_sheets_service()
    if not service:
        return False

    try:
        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_notation,
            valueInputOption='USER_ENTERED',
            insertDataOption='INSERT_ROWS',
            body={'values': rows},
        ).execute()
        updated = result.get('updates', {}).get('updatedRows', 0)
        log.info(f'[SHEETS] Appended {updated} rows to {range_notation}')
        return True
    except Exception as e:
        log.error(f'[SHEETS] Append failed: {e}')
        return False


def update_cell(spreadsheet_id, cell, value):
    """Update a single cell. cell example: 'Sheet1!B5'"""
    return write_range(spreadsheet_id, cell, [[value]])


def get_sheet_names(spreadsheet_id):
    """List all sheet/tab names in a spreadsheet."""
    service = get_sheets_service()
    if not service:
        return None

    try:
        result = service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields='sheets.properties.title',
        ).execute()
        names = [s['properties']['title'] for s in result.get('sheets', [])]
        return names
    except Exception as e:
        log.error(f'[SHEETS] Get sheet names failed: {e}')
        return None


def find_row(spreadsheet_id, range_notation, column_index, search_value):
    """Find a row where column_index matches search_value. Returns row number (1-based) or None."""
    values = read_range(spreadsheet_id, range_notation)
    if not values:
        return None

    for i, row in enumerate(values):
        if len(row) > column_index and str(row[column_index]).strip() == str(search_value).strip():
            return i + 1  # 1-based row number
    return None

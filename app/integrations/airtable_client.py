"""Airtable integration — CRM database for leads, meetings, follow-ups.

The bot can:
- Read records from any table
- Create new records (leads, meetings, etc.)
- Update existing records
- Search/filter records

Setup:
1. Create an Airtable account at https://airtable.com
2. Create a base (workspace) for Hub Automacao
3. Generate a Personal Access Token at https://airtable.com/create/tokens
   - Scopes needed: data.records:read, data.records:write, schema.bases:read
   - Access: the base you created
4. Set AIRTABLE_API_KEY and AIRTABLE_BASE_ID in .env
"""

import os
import logging
import requests

log = logging.getLogger('integrations.airtable')

_API_KEY = os.getenv('AIRTABLE_API_KEY', '')
_BASE_ID = os.getenv('AIRTABLE_BASE_ID', '')
_API_URL = 'https://api.airtable.com/v0'


def is_configured():
    """Check if Airtable credentials are set."""
    return bool(_API_KEY and _BASE_ID)


def _headers():
    return {
        'Authorization': f'Bearer {_API_KEY}',
        'Content-Type': 'application/json',
    }


def list_records(table_name, max_records=100, filter_formula=None, sort=None):
    """List records from a table.

    table_name: Name of the Airtable table (e.g., 'Leads', 'Reunioes')
    max_records: Maximum number of records to return
    filter_formula: Airtable formula filter (e.g., "{Status}='Novo'")
    sort: List of sort dicts (e.g., [{'field': 'Created', 'direction': 'desc'}])

    Returns list of records or None on error.
    """
    if not is_configured():
        log.warning('[AIRTABLE] Not configured')
        return None

    url = f'{_API_URL}/{_BASE_ID}/{requests.utils.quote(table_name)}'
    params = {'maxRecords': max_records}
    if filter_formula:
        params['filterByFormula'] = filter_formula
    if sort:
        for i, s in enumerate(sort):
            params[f'sort[{i}][field]'] = s['field']
            params[f'sort[{i}][direction]'] = s.get('direction', 'asc')

    try:
        resp = requests.get(url, headers=_headers(), params=params, timeout=15)
        resp.raise_for_status()
        records = resp.json().get('records', [])
        log.info(f'[AIRTABLE] Listed {len(records)} records from {table_name}')
        return [{'id': r['id'], **r.get('fields', {})} for r in records]
    except Exception as e:
        log.error(f'[AIRTABLE] List failed ({table_name}): {e}')
        return None


def get_record(table_name, record_id):
    """Get a single record by ID."""
    if not is_configured():
        return None

    url = f'{_API_URL}/{_BASE_ID}/{requests.utils.quote(table_name)}/{record_id}'
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        r = resp.json()
        return {'id': r['id'], **r.get('fields', {})}
    except Exception as e:
        log.error(f'[AIRTABLE] Get failed: {e}')
        return None


def create_record(table_name, fields):
    """Create a new record.

    fields: dict of field name -> value (e.g., {'Nome': 'John', 'Telefone': '123'})
    Returns the created record or None.
    """
    if not is_configured():
        log.warning('[AIRTABLE] Not configured')
        return None

    url = f'{_API_URL}/{_BASE_ID}/{requests.utils.quote(table_name)}'
    try:
        resp = requests.post(url, headers=_headers(), json={'fields': fields}, timeout=15)
        resp.raise_for_status()
        r = resp.json()
        log.info(f'[AIRTABLE] Created record in {table_name}: {r["id"]}')
        return {'id': r['id'], **r.get('fields', {})}
    except Exception as e:
        log.error(f'[AIRTABLE] Create failed ({table_name}): {e}')
        return None


def update_record(table_name, record_id, fields):
    """Update an existing record (partial update — only specified fields).

    Returns updated record or None.
    """
    if not is_configured():
        return None

    url = f'{_API_URL}/{_BASE_ID}/{requests.utils.quote(table_name)}/{record_id}'
    try:
        resp = requests.patch(url, headers=_headers(), json={'fields': fields}, timeout=15)
        resp.raise_for_status()
        r = resp.json()
        log.info(f'[AIRTABLE] Updated {record_id} in {table_name}')
        return {'id': r['id'], **r.get('fields', {})}
    except Exception as e:
        log.error(f'[AIRTABLE] Update failed: {e}')
        return None


def delete_record(table_name, record_id):
    """Delete a record. Returns True on success."""
    if not is_configured():
        return False

    url = f'{_API_URL}/{_BASE_ID}/{requests.utils.quote(table_name)}/{record_id}'
    try:
        resp = requests.delete(url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        log.info(f'[AIRTABLE] Deleted {record_id} from {table_name}')
        return True
    except Exception as e:
        log.error(f'[AIRTABLE] Delete failed: {e}')
        return False


def search_records(table_name, field_name, search_value, max_records=10):
    """Search records where a field matches a value.

    Uses Airtable formula: {field_name} = 'search_value'
    """
    escaped = str(search_value).replace("'", "\\'")
    formula = f"{{{field_name}}} = '{escaped}'"
    return list_records(table_name, max_records=max_records, filter_formula=formula)

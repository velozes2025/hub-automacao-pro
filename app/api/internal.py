"""Internal API endpoints for admin panel and debugging.

Secured with INTERNAL_API_KEY header to prevent unauthorized access.
These endpoints are meant to be called by the admin panel or internal services,
NOT by external clients or tenants.
"""

import logging
from functools import wraps
from flask import Blueprint, request, jsonify

from app.config import config
from app.db import leads as leads_db
from app.db import queue as queue_db
from app.db import lid as lid_db
from app.db import consumption as consumption_db
from app.db import conversations as conv_db
from app.db import tenants as tenants_db

log = logging.getLogger('api.internal')

internal_bp = Blueprint('internal', __name__, url_prefix='/api')


def require_internal_auth(f):
    """Require valid INTERNAL_API_KEY header for internal endpoints."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        # Check Authorization header
        auth = request.headers.get('Authorization', '')
        expected = getattr(config, 'INTERNAL_API_KEY', None)

        # If no key configured, allow only from Docker internal network
        if not expected:
            # Fall back to checking X-Internal-Token or allow localhost
            remote = request.remote_addr or ''
            if remote not in ('127.0.0.1', '::1') and not remote.startswith('172.'):
                log.warning(f'Internal API access denied from {remote} (no INTERNAL_API_KEY configured)')
                return jsonify({'error': 'unauthorized'}), 401
            return f(*args, **kwargs)

        # Validate Bearer token
        if auth != f'Bearer {expected}':
            log.warning(f'Internal API auth failed from {request.remote_addr}')
            return jsonify({'error': 'unauthorized'}), 401
        return f(*args, **kwargs)
    return wrapped


@internal_bp.route('/leads', methods=['GET'])
@require_internal_auth
def list_leads():
    """List leads, filtered by tenant. Tenant isolation enforced."""
    tenant_id = request.args.get('tenant_id')
    stage = request.args.get('stage')
    limit = int(request.args.get('limit', 100))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    rows = leads_db.list_leads(tenant_id, stage=stage, limit=limit)
    return jsonify(rows), 200


@internal_bp.route('/queue', methods=['GET'])
@require_internal_auth
def queue_status():
    """Get message queue statistics. Scoped to tenant if provided."""
    tenant_id = request.args.get('tenant_id')
    stats = queue_db.get_queue_stats(tenant_id)
    return jsonify(stats), 200


@internal_bp.route('/unresolved-lids', methods=['GET'])
@require_internal_auth
def unresolved_lids():
    """List unresolved LID entries for an account."""
    account_id = request.args.get('account_id')
    lids = lid_db.get_unresolved_lids(account_id)
    return jsonify(lids), 200


@internal_bp.route('/consumption', methods=['GET'])
@require_internal_auth
def consumption():
    """Get consumption stats for a tenant. Tenant isolation enforced."""
    tenant_id = request.args.get('tenant_id')
    days = int(request.args.get('days', 30))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    stats = consumption_db.get_tenant_consumption(tenant_id, days)
    return jsonify(stats), 200


@internal_bp.route('/conversations', methods=['GET'])
@require_internal_auth
def list_conversations():
    """List conversations for a tenant. Tenant isolation enforced."""
    tenant_id = request.args.get('tenant_id')
    limit = int(request.args.get('limit', 50))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    rows = conv_db.list_conversations(tenant_id, limit=limit)
    return jsonify(rows), 200


@internal_bp.route('/tenants', methods=['GET'])
@require_internal_auth
def list_tenants():
    """List all tenants. Super-admin level endpoint."""
    status = request.args.get('status', 'active')
    rows = tenants_db.list_tenants(status=status if status != 'all' else None)
    return jsonify(rows), 200

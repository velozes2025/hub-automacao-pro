"""Internal API endpoints for admin panel and debugging."""

import logging
from flask import Blueprint, request, jsonify

from app.db import leads as leads_db
from app.db import queue as queue_db
from app.db import lid as lid_db
from app.db import consumption as consumption_db
from app.db import conversations as conv_db
from app.db import tenants as tenants_db

log = logging.getLogger('api.internal')

internal_bp = Blueprint('internal', __name__, url_prefix='/api')


@internal_bp.route('/leads', methods=['GET'])
def list_leads():
    """List leads, optionally filtered by tenant."""
    tenant_id = request.args.get('tenant_id')
    stage = request.args.get('stage')
    limit = int(request.args.get('limit', 100))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    rows = leads_db.list_leads(tenant_id, stage=stage, limit=limit)
    return jsonify(rows), 200


@internal_bp.route('/queue', methods=['GET'])
def queue_status():
    """Get message queue statistics."""
    tenant_id = request.args.get('tenant_id')
    stats = queue_db.get_queue_stats(tenant_id)
    return jsonify(stats), 200


@internal_bp.route('/unresolved-lids', methods=['GET'])
def unresolved_lids():
    """List unresolved LID entries."""
    account_id = request.args.get('account_id')
    lids = lid_db.get_unresolved_lids(account_id)
    return jsonify(lids), 200


@internal_bp.route('/consumption', methods=['GET'])
def consumption():
    """Get consumption stats for a tenant."""
    tenant_id = request.args.get('tenant_id')
    days = int(request.args.get('days', 30))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    stats = consumption_db.get_tenant_consumption(tenant_id, days)
    return jsonify(stats), 200


@internal_bp.route('/conversations', methods=['GET'])
def list_conversations():
    """List conversations for a tenant."""
    tenant_id = request.args.get('tenant_id')
    limit = int(request.args.get('limit', 50))

    if not tenant_id:
        return jsonify({'error': 'tenant_id required'}), 400

    rows = conv_db.list_conversations(tenant_id, limit=limit)
    return jsonify(rows), 200


@internal_bp.route('/tenants', methods=['GET'])
def list_tenants():
    """List all tenants."""
    status = request.args.get('status', 'active')
    rows = tenants_db.list_tenants(status=status if status != 'all' else None)
    return jsonify(rows), 200

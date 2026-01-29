"""Webhook endpoint — receives Evolution API events.

Uses ThreadPoolExecutor with bounded workers to prevent
unbounded thread creation from burst messages.
"""

import logging
from concurrent.futures import ThreadPoolExecutor

from flask import Blueprint, request, jsonify

from app.config import config
from app.services.message_handler import handle_webhook

log = logging.getLogger('api.webhook')

webhook_bp = Blueprint('webhook', __name__)

_executor = ThreadPoolExecutor(
    max_workers=config.MAX_WEBHOOK_WORKERS,
    thread_name_prefix='webhook',
)


@webhook_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.json
    if not payload:
        return jsonify({'ok': False, 'error': 'empty payload'}), 400

    _executor.submit(_safe_handle, payload)
    return jsonify({'ok': True}), 200


def _safe_handle(payload):
    """Wrapper that catches all exceptions to prevent worker death."""
    try:
        handle_webhook(payload)
    except Exception as e:
        log.error(f'Unhandled webhook error: {e}', exc_info=True)

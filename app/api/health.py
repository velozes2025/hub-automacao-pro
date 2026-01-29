"""Health check endpoint."""

from flask import Blueprint, jsonify

health_bp = Blueprint('health', __name__)


@health_bp.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'hub-automacao-pro'}), 200

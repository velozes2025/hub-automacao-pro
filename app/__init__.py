import logging
from flask import Flask

from app.config import config


def create_app():
    """Flask application factory."""
    _configure_logging()

    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'hub-automacao-secret'

    # Register blueprints
    from app.api.webhook import webhook_bp
    from app.api.health import health_bp
    from app.api.internal import internal_bp

    app.register_blueprint(webhook_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(internal_bp)

    # Initialize database pool
    from app.db import init_pool
    init_pool()

    # Start background workers
    from app.workers.manager import start_all_workers
    start_all_workers()

    logging.getLogger('app').info('Hub Automacao Pro started')
    return app


def _configure_logging():
    level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )
    # Quiet noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

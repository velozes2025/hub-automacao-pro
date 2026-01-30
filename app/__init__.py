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
    from app.db import init_pool, run_migration
    init_pool()

    # Run pending migrations (idempotent — uses IF NOT EXISTS)
    import os
    _migration_dir = os.path.join(os.path.dirname(__file__), '..', 'migrations')
    if os.path.isdir(_migration_dir):
        for mig in sorted(os.listdir(_migration_dir)):
            if mig.endswith('.sql'):
                try:
                    run_migration(os.path.join(_migration_dir, mig))
                except Exception as e:
                    logging.getLogger('app').warning(f'Migration {mig}: {e}')

    # Initialize Redis (for dedup, health tracking)
    from app.db.redis_client import init_redis
    init_redis()

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

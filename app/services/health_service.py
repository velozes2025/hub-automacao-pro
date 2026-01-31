"""Webhook health monitoring and auto-recovery service.

Tracks instance health, counts consecutive failures, and alerts admin
when thresholds are exceeded. Uses Redis for failure counters and
health cache to avoid overwhelming the Evolution API.
"""

import logging
import requests

from app.config import config
from app.db.redis_client import get_redis
from app.db import queue as queue_db

log = logging.getLogger('services.health')

HEALTH_CACHE_TTL = 60  # Cache health check result for 60 seconds


def check_webhook_health(instance_name):
    """Check if a WhatsApp instance is connected and responding.

    Uses cached result (60s TTL) to avoid overwhelming Evolution API.
    Returns True if healthy or check unavailable (graceful degradation).
    """
    r = get_redis()
    if r:
        cache_key = f'health:{instance_name}'
        cached = r.get(cache_key)
        if cached is not None:
            return cached == '1'

    # Query Evolution API for connection state
    try:
        url = f'{config.EVOLUTION_URL}/instance/connectionState/{instance_name}'
        resp = requests.get(
            url,
            headers={'apikey': config.EVOLUTION_API_KEY},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            # Evolution API returns state: 'open', 'close', 'connecting'
            state = data.get('instance', {}).get('state', '')
            is_healthy = state == 'open'
        else:
            is_healthy = True  # Assume healthy on API error (don't block)
    except Exception as e:
        log.debug(f'[HEALTH] Check failed for {instance_name}: {e}')
        is_healthy = True  # Assume healthy on network error

    # Cache result
    if r:
        r.set(cache_key, '1' if is_healthy else '0', ex=HEALTH_CACHE_TTL)

    if not is_healthy:
        log.warning(f'[HEALTH] Instance {instance_name} is NOT connected')

    return is_healthy


def record_failure(instance_name):
    """Record a send failure for an instance. Returns failure count.

    Uses Redis atomic INCR for thread-safe counting.
    """
    r = get_redis()
    if not r:
        return 0

    key = f'webhook_failures:{instance_name}'
    count = r.incr(key)
    # Expire after 1 hour to auto-reset
    r.expire(key, 3600)

    log.warning(f'[HEALTH] Failure #{count} for {instance_name}')

    if count >= config.WEBHOOK_MAX_FAILURES:
        log.error(f'[HEALTH] Instance {instance_name} hit failure threshold ({count})')

    return count


def reset_failures(instance_name):
    """Reset failure counter after successful send."""
    r = get_redis()
    if r:
        r.delete(f'webhook_failures:{instance_name}')


def get_failure_count(instance_name):
    """Get current failure count for an instance."""
    r = get_redis()
    if not r:
        return 0
    count = r.get(f'webhook_failures:{instance_name}')
    return int(count) if count else 0


def alert_admin(tenant_id, instance_name, error_type):
    """Alert admin about critical webhook failure.

    Saves alert to message_queue and optionally sends to backup webhook.
    """
    log.error(f'[HEALTH-ALERT] TenantID:{tenant_id} | Instance:{instance_name} | '
              f'Error:{error_type}')

    # Save admin alert to queue
    try:
        import json
        queue_db.enqueue(
            tenant_id=tenant_id,
            whatsapp_account_id='',
            phone='admin',
            content=f'ALERT: {error_type} on instance {instance_name}',
            queue_type='admin_alert',
            metadata=json.dumps({
                'instance': instance_name,
                'error_type': error_type,
                'tenant_id': tenant_id,
            }),
        )
    except Exception as e:
        log.error(f'[HEALTH] Failed to queue admin alert: {e}')

    # Send to backup webhook if configured
    if config.WEBHOOK_BACKUP_URL:
        try:
            requests.post(
                config.WEBHOOK_BACKUP_URL,
                json={
                    'type': 'health_alert',
                    'tenant_id': tenant_id,
                    'instance': instance_name,
                    'error': error_type,
                    'failure_count': get_failure_count(instance_name),
                },
                timeout=5,
            )
            log.info(f'[HEALTH] Backup webhook notified: {config.WEBHOOK_BACKUP_URL}')
        except Exception as e:
            log.error(f'[HEALTH] Backup webhook failed: {e}')


def check_all_instances():
    """Check health of all active instances. Used by health monitor worker."""
    from app.db import tenants as tenants_db

    try:
        accounts = tenants_db.list_active_accounts()
        if not accounts:
            return

        unhealthy = 0
        for acc in accounts:
            instance = acc.get('instance_name', '')
            if instance and not check_webhook_health(instance):
                unhealthy += 1
                record_failure(instance)
                if get_failure_count(instance) >= config.WEBHOOK_MAX_FAILURES:
                    alert_admin(
                        str(acc.get('tenant_id', '')),
                        instance,
                        'instance_disconnected',
                    )

        if unhealthy:
            log.warning(f'[HEALTH] {unhealthy} unhealthy instances detected')
    except Exception as e:
        log.error(f'[HEALTH] Check all instances error: {e}')

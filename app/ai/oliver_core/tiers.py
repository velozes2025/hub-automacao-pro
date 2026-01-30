"""Multi-tenant tier configuration for OLIVER.CORE v5.1."""

import logging

log = logging.getLogger('oliver.tiers')

TIER_DEFAULTS = {
    'admin': {
        'cache_enabled': True,
        'max_history': 5,
        'preload_expanders': ['ABER', 'DIAG'],
        'analytics_enabled': True,
    },
    'tenant_free': {
        'cache_enabled': True,
        'max_history': 2,
        'preload_expanders': [],
        'analytics_enabled': False,
    },
    'tenant_pro': {
        'cache_enabled': True,
        'max_history': 4,
        'preload_expanders': ['ABER'],
        'analytics_enabled': True,
    },
}


def get_tier_config(tenant_settings):
    """Resolve tier configuration from tenant settings JSONB.

    Reads 'oliver_tier' key from settings. Merges any
    'oliver_overrides' on top of tier defaults.
    """
    if not tenant_settings or not isinstance(tenant_settings, dict):
        tenant_settings = {}

    tier_name = tenant_settings.get('oliver_tier', 'tenant_free')
    base = TIER_DEFAULTS.get(tier_name)
    if not base:
        log.warning(f'Unknown tier "{tier_name}", falling back to tenant_free')
        base = TIER_DEFAULTS['tenant_free']

    config = dict(base)

    overrides = tenant_settings.get('oliver_overrides', {})
    if isinstance(overrides, dict):
        config.update(overrides)

    return config


def resolve_max_history(tier_config, agent_config):
    """Resolve max history from tier and agent config (whichever is lower)."""
    tier_max = tier_config.get('max_history', 3)
    agent_max = agent_config.get('max_history_messages', 10)
    return min(tier_max, agent_max)

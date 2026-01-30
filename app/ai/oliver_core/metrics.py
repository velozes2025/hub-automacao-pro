"""Engine metrics for OLIVER.CORE v5.1.

Thread-safe in-memory counters for cache hits, token savings, and intent tracking.
"""

import threading
import logging

log = logging.getLogger('oliver.metrics')

_lock = threading.Lock()

_metrics = {
    'total_requests': 0,
    'cache_hits': 0,
    'cache_misses': 0,
    'tokens_saved': 0,
    'by_tenant': {},
    'by_intent': {},
}


def record(tenant_id, cache_hit, tokens_used=0, tokens_baseline=1800,
           phase='', intent_type=''):
    """Record a v5.1 engine request.

    Args:
        tenant_id: tenant UUID string
        cache_hit: whether the response came from cache
        tokens_used: actual input tokens used (0 for cache hits)
        tokens_baseline: estimated tokens if v5.0 was used
        phase: detected conversation phase
        intent_type: specific intent type
    """
    saved = tokens_baseline - tokens_used

    with _lock:
        _metrics['total_requests'] += 1
        if cache_hit:
            _metrics['cache_hits'] += 1
        else:
            _metrics['cache_misses'] += 1
        _metrics['tokens_saved'] += saved

        # Per-tenant
        tid = str(tenant_id) if tenant_id else 'unknown'
        if tid not in _metrics['by_tenant']:
            _metrics['by_tenant'][tid] = {'hits': 0, 'misses': 0, 'saved': 0}
        bucket = _metrics['by_tenant'][tid]
        if cache_hit:
            bucket['hits'] += 1
        else:
            bucket['misses'] += 1
        bucket['saved'] += saved

        # Per-intent
        ikey = intent_type or phase or 'unknown'
        if ikey not in _metrics['by_intent']:
            _metrics['by_intent'][ikey] = {'count': 0, 'cached': 0, 'llm': 0}
        ibucket = _metrics['by_intent'][ikey]
        ibucket['count'] += 1
        if cache_hit:
            ibucket['cached'] += 1
        else:
            ibucket['llm'] += 1


def get_metrics(tenant_id=None):
    """Return a snapshot of current metrics.

    Args:
        tenant_id: optional — if provided, returns tenant-scoped metrics.

    Returns:
        dict with counters and computed rates.
    """
    with _lock:
        total = _metrics['total_requests'] or 1
        result = {
            'total_requests': _metrics['total_requests'],
            'cache_hits': _metrics['cache_hits'],
            'cache_misses': _metrics['cache_misses'],
            'cache_hit_rate': _metrics['cache_hits'] / total,
            'tokens_saved': _metrics['tokens_saved'],
            'avg_tokens_saved_per_request': _metrics['tokens_saved'] / total,
        }

        if tenant_id:
            tid = str(tenant_id)
            tb = _metrics['by_tenant'].get(tid, {'hits': 0, 'misses': 0, 'saved': 0})
            t_total = (tb['hits'] + tb['misses']) or 1
            result['tenant'] = {
                'hits': tb['hits'],
                'misses': tb['misses'],
                'cache_hit_rate': tb['hits'] / t_total,
                'tokens_saved': tb['saved'],
            }

        result['by_intent'] = dict(_metrics['by_intent'])
        return result


def get_cache_hit_rate(tenant_id=None):
    """Convenience: return cache hit rate as float."""
    m = get_metrics(tenant_id)
    if tenant_id and 'tenant' in m:
        return m['tenant']['cache_hit_rate']
    return m['cache_hit_rate']

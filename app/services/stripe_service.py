"""Stripe metered billing service (structure only).

All functions are no-ops when STRIPE_API_KEY is not configured.
This allows deployment without Stripe integration.

Flow:
1. Tenant creation -> create_customer() + create_subscription()
2. Each AI response -> report_usage() (metered billing)
3. Before processing -> check_tenant_billing() (suspend if past_due)
"""

import logging
from app.config import config
from app.db import query, execute

log = logging.getLogger('services.stripe')

_stripe = None


def _get_stripe():
    """Lazy-load stripe module. Returns None if not configured."""
    global _stripe
    if not config.STRIPE_API_KEY:
        return None
    if _stripe is None:
        try:
            import stripe
            stripe.api_key = config.STRIPE_API_KEY
            _stripe = stripe
        except ImportError:
            log.warning('stripe package not installed')
            return None
    return _stripe


def create_customer(tenant_id, tenant_name, email=None):
    """Create a Stripe customer for a tenant. No-op without Stripe key."""
    stripe = _get_stripe()
    if not stripe:
        return None

    try:
        customer = stripe.Customer.create(
            name=tenant_name,
            email=email,
            metadata={'tenant_id': str(tenant_id)},
        )
        execute(
            "UPDATE tenants SET stripe_customer_id = %s WHERE id = %s",
            (customer.id, str(tenant_id)),
        )
        log.info(f'Stripe customer created: {customer.id} for tenant {tenant_id}')
        return customer.id
    except Exception as e:
        log.error(f'Stripe create_customer error: {e}')
        return None


def create_subscription(tenant_id):
    """Create a metered subscription for a tenant. No-op without Stripe key."""
    stripe = _get_stripe()
    if not stripe or not config.STRIPE_PRICE_ID:
        return None

    tenant = query(
        "SELECT stripe_customer_id FROM tenants WHERE id = %s",
        (str(tenant_id),),
        fetch='one',
    )
    if not tenant or not tenant.get('stripe_customer_id'):
        log.warning(f'No Stripe customer for tenant {tenant_id}')
        return None

    try:
        subscription = stripe.Subscription.create(
            customer=tenant['stripe_customer_id'],
            items=[{'price': config.STRIPE_PRICE_ID}],
            metadata={'tenant_id': str(tenant_id)},
        )
        execute(
            "UPDATE tenants SET stripe_subscription_id = %s WHERE id = %s",
            (subscription.id, str(tenant_id)),
        )
        log.info(f'Stripe subscription created: {subscription.id}')
        return subscription.id
    except Exception as e:
        log.error(f'Stripe create_subscription error: {e}')
        return None


def report_usage(tenant_id, quantity=1):
    """Report metered usage to Stripe. No-op without Stripe key.

    Called after each AI response. Quantity = 1 message unit.
    """
    stripe = _get_stripe()
    if not stripe:
        return

    tenant = query(
        "SELECT stripe_subscription_id FROM tenants WHERE id = %s",
        (str(tenant_id),),
        fetch='one',
    )
    if not tenant or not tenant.get('stripe_subscription_id'):
        return

    try:
        subscription = stripe.Subscription.retrieve(
            tenant['stripe_subscription_id']
        )
        items = subscription.get('items', {}).get('data', [])
        if items:
            stripe.SubscriptionItem.create_usage_record(
                items[0]['id'],
                quantity=quantity,
                action='increment',
            )
    except Exception as e:
        log.error(f'Stripe report_usage error: {e}')


def check_tenant_billing(tenant_id):
    """Check if tenant is in good billing standing.

    Returns True if OK to process, False if should be blocked.
    No-op (returns True) without Stripe key.
    """
    if not config.STRIPE_API_KEY:
        return True

    tenant = query(
        "SELECT billing_status FROM tenants WHERE id = %s",
        (str(tenant_id),),
        fetch='one',
    )
    if not tenant:
        return False

    status = tenant.get('billing_status', 'active')
    if status in ('active', 'trial'):
        return True
    if status == 'suspended':
        log.warning(f'Tenant {tenant_id} is suspended (billing)')
        return False
    if status == 'past_due':
        log.warning(f'Tenant {tenant_id} has past_due billing')
        return True  # Grace period
    return True


def suspend_tenant(tenant_id):
    """Suspend a tenant due to billing issues."""
    execute(
        "UPDATE tenants SET billing_status = 'suspended', status = 'suspended' WHERE id = %s",
        (str(tenant_id),),
    )
    log.warning(f'Tenant {tenant_id} suspended for billing')

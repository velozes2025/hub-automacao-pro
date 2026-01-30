"""Conversation state persistence for OLIVER.CORE v6.0 state machine."""

import json
import logging
from app.db import query, execute

log = logging.getLogger('db.states')


def get_or_create_state(conversation_id, tenant_id):
    """Get existing state or create default ABERTURA state.

    Returns dict with: id, conversation_id, tenant_id, current_node,
                       previous_node, active_agent, guard_data,
                       transition_count, updated_at.
    """
    row = query(
        """SELECT * FROM conversation_states
           WHERE conversation_id = %s AND tenant_id = %s""",
        (str(conversation_id), str(tenant_id)),
        fetch='one',
    )
    if row:
        # Parse guard_data if string
        gd = row.get('guard_data', {})
        if isinstance(gd, str):
            try:
                row['guard_data'] = json.loads(gd)
            except (ValueError, TypeError):
                row['guard_data'] = {}
        return row

    return execute(
        """INSERT INTO conversation_states
           (conversation_id, tenant_id, current_node, active_agent, guard_data)
           VALUES (%s, %s, 'ABERTURA', 'oliver', '{}')
           ON CONFLICT (conversation_id) DO UPDATE
               SET updated_at = CURRENT_TIMESTAMP
           RETURNING *""",
        (str(conversation_id), str(tenant_id)),
        returning=True,
    )


def get_state(conversation_id):
    """Get state by conversation_id (no tenant check)."""
    return query(
        "SELECT * FROM conversation_states WHERE conversation_id = %s",
        (str(conversation_id),),
        fetch='one',
    )


def update_state(conversation_id, tenant_id, **fields):
    """Update state fields with tenant isolation.

    Supported fields: current_node, previous_node, active_agent,
                     guard_data, transition_count.
    """
    allowed = {'current_node', 'previous_node', 'active_agent',
               'guard_data', 'transition_count'}
    sets = []
    vals = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == 'guard_data' and isinstance(v, dict):
            v = json.dumps(v)
        sets.append(f"{k} = %s")
        vals.append(v)

    if not sets:
        return

    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.extend([str(conversation_id), str(tenant_id)])

    execute(
        f"""UPDATE conversation_states
            SET {', '.join(sets)}
            WHERE conversation_id = %s AND tenant_id = %s""",
        tuple(vals),
    )


def transition(conversation_id, tenant_id, new_node, new_agent=None,
               guard_data=None):
    """Perform a state transition: update node, previous_node, increment count."""
    gd_json = json.dumps(guard_data) if guard_data else None

    sql_parts = [
        "previous_node = current_node",
        "current_node = %s",
        "transition_count = transition_count + 1",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    vals = [new_node]

    if new_agent:
        sql_parts.append("active_agent = %s")
        vals.append(new_agent)

    if gd_json:
        sql_parts.append("guard_data = %s")
        vals.append(gd_json)

    vals.extend([str(conversation_id), str(tenant_id)])

    execute(
        f"""UPDATE conversation_states
            SET {', '.join(sql_parts)}
            WHERE conversation_id = %s AND tenant_id = %s""",
        tuple(vals),
    )

"""OLIVER.CORE v6.0 — Adaptive Multi-Tenant Engine.

Token-efficient engine with intent detection, response caching,
compressed prompts, state machine, agent routing, client memory,
and reflection loop. Sits between message_handler and supervisor.
"""

from app.ai.oliver_core.engine import process_v51, process_v60

__all__ = ['process_v51', 'process_v60']

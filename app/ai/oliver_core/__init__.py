"""OLIVER.CORE v5.1 — Adaptive Multi-Tenant Engine.

Token-efficient engine with intent detection, response caching,
and compressed prompts. Sits between message_handler and supervisor.
"""

from app.ai.oliver_core.engine import process_v51

__all__ = ['process_v51']

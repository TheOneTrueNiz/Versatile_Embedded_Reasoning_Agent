"""
VERA 2.0 Hook System
=====================

Lightweight event interceptors that complement the existing EventBus.

EventBus = fire-and-forget notifications (observability, logging).
Hooks = inline interceptors with control flow (PASS/MODIFY/BLOCK).
"""

from core.hooks.types import HookEvent, HookEventType, HookResult
from core.hooks.registry import HookRegistry

__all__ = ["HookEvent", "HookEventType", "HookResult", "HookRegistry"]

"""
Hook Registry
==============

Registry for hook handlers. Supports both sync and async handlers.
Fires hooks in registration order, stopping on BLOCK.

Ported from Moltbot's internal-hooks pattern but simplified for Python:
- No frontmatter discovery (use decorators or direct registration)
- Supports event_type and event_type:action specificity
- Async-native
"""

import asyncio
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from core.hooks.types import HookEvent, HookEventType, HookHandler, HookResult

logger = logging.getLogger(__name__)


class HookRegistry:
    """Registry for event hook handlers.

    Handlers are called in registration order. If any handler returns
    BLOCK, subsequent handlers are skipped and BLOCK is returned.

    Supports two levels of specificity:
    - General: "before_message" matches all before_message events
    - Specific: "before_message:tool_call" only matches that sub-action

    When an event fires, both general and specific handlers run.
    General handlers run first.
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, List[HookHandler]] = defaultdict(list)
        self._handler_names: Dict[str, List[str]] = defaultdict(list)

    def register(
        self,
        event_key: str,
        handler: HookHandler,
        name: Optional[str] = None,
    ) -> None:
        """Register a handler for an event key.

        Args:
            event_key: Event to handle. Either "before_message" (general)
                       or "before_message:tool_call" (specific).
            handler: Sync or async callable(HookEvent) -> HookResult
            name: Optional name for logging/debugging
        """
        self._handlers[event_key].append(handler)
        self._handler_names[event_key].append(
            name or getattr(handler, "__name__", repr(handler))
        )
        logger.debug(f"Hook registered: {event_key} -> {name or handler}")

    def unregister(self, event_key: str, handler: HookHandler) -> bool:
        """Remove a handler. Returns True if found and removed."""
        handlers = self._handlers.get(event_key, [])
        for i, h in enumerate(handlers):
            if h is handler:
                handlers.pop(i)
                self._handler_names[event_key].pop(i)
                return True
        return False

    async def trigger(self, event: HookEvent) -> HookResult:
        """Trigger all handlers for an event.

        Calls handlers in this order:
        1. General type handlers (e.g., "before_message")
        2. Specific type:action handlers (e.g., "before_message:tool_call")

        Returns BLOCK if any handler blocks, otherwise PASS or MODIFY.
        """
        general_key = event.event_type.value
        specific_key = event.event_key  # includes action if present

        result = HookResult.PASS

        # Fire general handlers first
        general_result = await self._fire_handlers(general_key, event)
        if general_result == HookResult.BLOCK:
            return HookResult.BLOCK
        if general_result == HookResult.MODIFY:
            result = HookResult.MODIFY

        # Fire specific handlers if action is set
        if event.action and specific_key != general_key:
            specific_result = await self._fire_handlers(specific_key, event)
            if specific_result == HookResult.BLOCK:
                return HookResult.BLOCK
            if specific_result == HookResult.MODIFY:
                result = HookResult.MODIFY

        return result

    async def _fire_handlers(
        self, event_key: str, event: HookEvent
    ) -> HookResult:
        """Fire all handlers registered for a specific key."""
        handlers = self._handlers.get(event_key, [])
        if not handlers:
            return HookResult.PASS

        result = HookResult.PASS
        names = self._handler_names.get(event_key, [])

        for i, handler in enumerate(handlers):
            handler_name = names[i] if i < len(names) else "unknown"
            try:
                if asyncio.iscoroutinefunction(handler):
                    handler_result = await handler(event)
                else:
                    handler_result = handler(event)

                if handler_result == HookResult.BLOCK:
                    logger.debug(
                        f"Hook BLOCKED by {handler_name} on {event_key}"
                    )
                    return HookResult.BLOCK
                elif handler_result == HookResult.MODIFY:
                    result = HookResult.MODIFY

            except Exception as e:
                logger.warning(
                    f"Hook handler {handler_name} failed on {event_key}: {e}"
                )
                # Don't let hook failures break the main flow

        return result

    def clear(self, event_key: Optional[str] = None) -> None:
        """Clear handlers. If event_key is None, clear all."""
        if event_key:
            self._handlers.pop(event_key, None)
            self._handler_names.pop(event_key, None)
        else:
            self._handlers.clear()
            self._handler_names.clear()

    def list_handlers(self) -> Dict[str, List[str]]:
        """List all registered handler names by event key."""
        return dict(self._handler_names)

    @property
    def handler_count(self) -> int:
        """Total number of registered handlers."""
        return sum(len(h) for h in self._handlers.values())

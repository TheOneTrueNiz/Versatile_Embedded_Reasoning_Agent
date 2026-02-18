"""
Hook Types
===========

Event types, event objects, and result enums for the hook system.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, Union


class HookEventType(Enum):
    """Types of events that hooks can intercept."""
    BEFORE_MESSAGE = "before_message"
    AFTER_MESSAGE = "after_message"
    ON_TOOL_CALL = "on_tool_call"
    ON_TOOL_RESULT = "on_tool_result"
    ON_SESSION_START = "on_session_start"
    ON_SESSION_END = "on_session_end"
    ON_ERROR = "on_error"
    ON_PROVIDER_SWITCH = "on_provider_switch"
    ON_CHANNEL_MESSAGE = "on_channel_message"


class HookResult(Enum):
    """What the hook wants to do with the event."""
    PASS = "pass"       # Continue normally
    MODIFY = "modify"   # Event context was modified in place
    BLOCK = "block"     # Block the event from proceeding


@dataclass
class HookEvent:
    """Event passed to hook handlers.

    Handlers can modify `context` in place and return MODIFY,
    or return BLOCK to prevent the event from proceeding.
    """
    event_type: HookEventType
    action: str = ""          # Sub-action: "tool_call", "provider_switch", etc.
    session_key: str = ""     # Session this event belongs to
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def event_key(self) -> str:
        """Full event key for handler matching: 'before_message' or 'before_message:tool_call'."""
        if self.action:
            return f"{self.event_type.value}:{self.action}"
        return self.event_type.value


# Handler type: sync or async callable that takes HookEvent and returns HookResult
HookHandler = Callable[[HookEvent], Union[HookResult, Coroutine[Any, Any, HookResult]]]

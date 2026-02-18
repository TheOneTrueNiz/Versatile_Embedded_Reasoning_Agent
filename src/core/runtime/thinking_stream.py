#!/usr/bin/env python3
"""
Observable Thinking Stream
==========================

Makes VERA's reasoning process visible to users.

Emits structured thinking events that can be displayed in the UI,
similar to Google Gemini's "Show thinking" feature.

Event Types:
- analyzing: Initial query analysis
- routing: Tool/category selection reasoning
- memory: Memory retrieval steps
- tool: Tool execution status
- reasoning: Chain-of-thought reasoning
- decision: Final decision made

Usage:
    thinking = ThinkingStream()

    # Emit events
    thinking.emit("analyzing", "Parsing user query...")
    thinking.emit("routing", "Keywords detected: email, meeting")
    thinking.emit("tool", "Calling gmail_create_draft...")

    # Get events for streaming to UI
    events = thinking.drain()
"""

import logging
import time
import asyncio
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


class ThinkingEventType(Enum):
    """Types of thinking events"""
    ANALYZING = "analyzing"      # Initial query analysis
    ROUTING = "routing"          # Tool/category selection
    MEMORY = "memory"            # Memory retrieval steps
    TOOL = "tool"                # Tool execution status
    REASONING = "reasoning"      # Chain-of-thought
    DECISION = "decision"        # Final decision made
    QUORUM = "quorum"            # Swarm/quorum consultation
    ERROR = "error"              # Error during thinking


@dataclass
class ThinkingEvent:
    """A single thinking event"""
    event_type: ThinkingEventType
    message: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            "type": "thinking",
            "event_type": self.event_type.value,
            "message": self.message,
            "timestamp": self.timestamp,
            "metadata": self.metadata
        }

    def __str__(self) -> str:
        return f"[{self.event_type.value}] {self.message}"


class ThinkingStream:
    """
    Stream of observable thinking events.

    Thread-safe event queue that can be consumed by WebSocket handlers.
    """

    def __init__(self, max_events: int = 100) -> None:
        """
        Initialize thinking stream.

        Args:
            max_events: Maximum events to buffer (oldest dropped if exceeded)
        """
        self.max_events = max_events
        self._events: deque[ThinkingEvent] = deque(maxlen=max_events)
        self._async_queue: Optional[asyncio.Queue] = None
        self._listeners: List[Callable[[ThinkingEvent], None]] = []
        self._enabled = True

        # Statistics
        self.stats = {
            "total_events": 0,
            "events_by_type": {}
        }

    def enable(self) -> None:
        """Enable thinking stream"""
        self._enabled = True

    def disable(self) -> None:
        """Disable thinking stream (no events emitted)"""
        self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def emit(
        self,
        event_type: str | ThinkingEventType,
        message: str,
        **metadata
    ) -> Optional[ThinkingEvent]:
        """
        Emit a thinking event.

        Args:
            event_type: Type of event (string or enum)
            message: Human-readable message
            **metadata: Additional metadata

        Returns:
            ThinkingEvent if emitted, None if disabled
        """
        if not self._enabled:
            return None

        # Convert string to enum if needed
        if isinstance(event_type, str):
            try:
                event_type = ThinkingEventType(event_type)
            except ValueError:
                event_type = ThinkingEventType.REASONING

        # Create event
        event = ThinkingEvent(
            event_type=event_type,
            message=message,
            metadata=metadata
        )

        # Add to buffer
        self._events.append(event)

        # Update stats
        self.stats["total_events"] += 1
        type_key = event_type.value
        self.stats["events_by_type"][type_key] = \
            self.stats["events_by_type"].get(type_key, 0) + 1

        # Notify async queue if set
        if self._async_queue is not None:
            try:
                self._async_queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Suppressed Exception in thinking_stream")
                pass  # Drop if queue full

        # Notify listeners
        for listener in self._listeners:
            try:
                listener(event)
            except Exception:
                logger.debug("Suppressed Exception in thinking_stream")
                pass  # Don't let listener errors break the stream

        return event

    def emit_analyzing(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit an analyzing event"""
        return self.emit(ThinkingEventType.ANALYZING, message, **metadata)

    def emit_routing(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a routing event"""
        return self.emit(ThinkingEventType.ROUTING, message, **metadata)

    def emit_memory(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a memory event"""
        return self.emit(ThinkingEventType.MEMORY, message, **metadata)

    def emit_tool(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a tool event"""
        return self.emit(ThinkingEventType.TOOL, message, **metadata)

    def emit_reasoning(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a reasoning event"""
        return self.emit(ThinkingEventType.REASONING, message, **metadata)

    def emit_decision(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a decision event"""
        return self.emit(ThinkingEventType.DECISION, message, **metadata)

    def emit_quorum(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit a quorum/swarm event"""
        return self.emit(ThinkingEventType.QUORUM, message, **metadata)

    def emit_error(self, message: str, **metadata) -> Optional[ThinkingEvent]:
        """Emit an error event"""
        return self.emit(ThinkingEventType.ERROR, message, **metadata)

    def get_recent(self, n: int = 10) -> List[ThinkingEvent]:
        """Get N most recent events"""
        return list(self._events)[-n:]

    def drain(self) -> List[ThinkingEvent]:
        """
        Drain all events from buffer.

        Returns:
            List of all buffered events (clears buffer)
        """
        events = list(self._events)
        self._events.clear()
        return events

    def drain_as_dicts(self) -> List[Dict[str, Any]]:
        """Drain events as dictionaries for JSON serialization"""
        return [e.to_dict() for e in self.drain()]

    def clear(self) -> None:
        """Clear all buffered events"""
        self._events.clear()

    def add_listener(self, callback: Callable[[ThinkingEvent], None]) -> None:
        """
        Add a listener for real-time event notifications.

        Args:
            callback: Function called with each new event
        """
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[ThinkingEvent], None]) -> None:
        """Remove a listener"""
        if callback in self._listeners:
            self._listeners.remove(callback)

    def create_async_queue(self) -> asyncio.Queue:
        """
        Create an async queue for WebSocket streaming.

        Returns:
            asyncio.Queue that receives all new events
        """
        self._async_queue = asyncio.Queue(maxsize=self.max_events)
        return self._async_queue

    def get_stats(self) -> Dict[str, Any]:
        """Get stream statistics"""
        return {
            **self.stats,
            "buffered_events": len(self._events),
            "enabled": self._enabled
        }


# Global thinking stream instance (singleton pattern)
_global_stream: Optional[ThinkingStream] = None


def get_thinking_stream() -> ThinkingStream:
    """Get the global thinking stream instance"""
    global _global_stream
    if _global_stream is None:
        _global_stream = ThinkingStream()
    return _global_stream


def emit_thinking(
    event_type: str | ThinkingEventType,
    message: str,
    **metadata
) -> Optional[ThinkingEvent]:
    """
    Convenience function to emit to the global thinking stream.

    Usage:
        from core.runtime.thinking_stream import emit_thinking

        emit_thinking("routing", "Keywords detected: email")
    """
    return get_thinking_stream().emit(event_type, message, **metadata)


# Shorthand functions for common event types
def thinking_analyzing(message: str, **metadata):
    """Emit analyzing event"""
    return emit_thinking(ThinkingEventType.ANALYZING, message, **metadata)

def thinking_routing(message: str, **metadata):
    """Emit routing event"""
    return emit_thinking(ThinkingEventType.ROUTING, message, **metadata)

def thinking_memory(message: str, **metadata):
    """Emit memory event"""
    return emit_thinking(ThinkingEventType.MEMORY, message, **metadata)

def thinking_tool(message: str, **metadata):
    """Emit tool event"""
    return emit_thinking(ThinkingEventType.TOOL, message, **metadata)

def thinking_decision(message: str, **metadata):
    """Emit decision event"""
    return emit_thinking(ThinkingEventType.DECISION, message, **metadata)


# Example usage
if __name__ == "__main__":
    print("=== Thinking Stream Demo ===\n")

    stream = ThinkingStream()

    # Simulate a query flow
    stream.emit_analyzing("Parsing user query: 'send email to john about meeting'")
    stream.emit_routing("Keywords detected: email, meeting → workspace category")
    stream.emit_routing("Tools selected: gmail_send_email, gmail_create_draft")
    stream.emit_memory("Searching for previous emails to John...")
    stream.emit_memory("Found 3 relevant conversations")
    stream.emit_tool("Calling gmail_create_draft...")
    stream.emit_tool("Draft created successfully", draft_id="draft_123")
    stream.emit_decision("Created draft email for user review")

    # Print events
    print("Events emitted:")
    print("-" * 60)
    for event in stream.get_recent(10):
        print(event)

    print(f"\nStats: {stream.get_stats()}")

    # Test drain
    print(f"\nDrained {len(stream.drain())} events")
    print(f"Remaining: {len(stream.get_recent(10))} events")

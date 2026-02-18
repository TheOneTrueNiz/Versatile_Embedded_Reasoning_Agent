"""
Event Bus for VERA.

Provides decoupled communication between modules.
Enables reactive patterns and loose coupling.

Based on patterns from:
- Intrinsic Memory Agents (arxiv:2508.08997)
- Multi-agent coordination patterns
"""

import logging
import time
import threading
import queue
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import weakref

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    """Event priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """An event in the system."""
    event_type: str
    payload: Dict[str, Any]
    source: str
    timestamp: float = field(default_factory=time.time)
    priority: EventPriority = EventPriority.NORMAL
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"{self.event_type}-{int(self.timestamp * 1000)}"


@dataclass
class Subscription:
    """A subscription to events."""
    event_pattern: str  # Supports wildcards: "task.*", "*"
    callback: Callable[[Event], None]
    subscriber_id: str
    priority: int = 0  # Higher = called first
    async_handler: bool = False
    filters: Dict[str, Any] = field(default_factory=dict)


class EventBus:
    """
    Central event bus for VERA module communication.

    Features:
    - Pattern-based subscriptions (e.g., "task.*")
    - Priority ordering
    - Async and sync handlers
    - Event filtering
    - Event history
    - Dead letter queue for failed events
    """

    # Standard VERA event types
    EVENT_TYPES = {
        # Task events
        "task.created": "A new task was created",
        "task.updated": "A task was updated",
        "task.completed": "A task was completed",
        "task.blocked": "A task became blocked",

        # Session events
        "session.started": "Session started",
        "session.ended": "Session ended",
        "session.activity": "User activity detected",

        # Message events
        "message.assistant": "Assistant message emitted",

        # Tool events
        "tool.completed": "Tool execution completed",
        "tool.failed": "Tool execution failed",

        # Error events
        "error.message": "Message processing error",

        # System events
        "system.startup": "System is starting up",
        "system.shutdown": "System is shutting down",
        "system.health.degraded": "System health degraded",
        "system.health.recovered": "System health recovered",

        # Decision events
        "decision.made": "A decision was logged",
        "decision.reversed": "A decision was reversed",

        # Memory events
        "memory.context.added": "Context was added",
        "memory.context.pruned": "Context was pruned",
        "memory.bookmark.created": "Bookmark was created",

        # Voice events
        "voice.session.started": "Voice session started",
        "voice.session.ended": "Voice session ended",
        "voice.speech.detected": "Speech was detected",

        # Cost events
        "cost.threshold.warning": "Cost threshold warning",
        "cost.threshold.exceeded": "Cost threshold exceeded",

        # Inner life events
        "innerlife.internal": "Inner reflection completed (journal only)",
        "innerlife.reached_out": "VERA proactively reached out to user",
        "innerlife.self_prompted": "VERA chained a follow-up thought",
        "innerlife.action": "VERA took autonomous action from reflection",
        "innerlife.personality_update": "Personality state evolved",
        "innerlife.error": "Inner life reflection failed",
        "innerlife.outside_hours": "Reflection skipped (outside active hours)",
    }

    def __init__(
        self,
        max_history: int = 1000,
        enable_async: bool = True
    ):
        """
        Initialize event bus.

        Args:
            max_history: Maximum events to keep in history
            enable_async: Enable async event processing
        """
        self.max_history = max_history
        self.enable_async = enable_async

        # Subscriptions by pattern
        self._subscriptions: Dict[str, List[Subscription]] = defaultdict(list)
        self._subscription_lock = threading.RLock()

        # Event history
        self._history: List[Event] = []
        self._history_lock = threading.Lock()

        # Dead letter queue
        self._dead_letters: List[tuple] = []  # (event, error, timestamp)

        # Stats
        self._events_published = 0
        self._events_delivered = 0
        self._events_failed = 0

        # Async processing
        self._event_queue: queue.Queue = queue.Queue()
        self._async_running = False
        self._async_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start async event processing."""
        if self._async_running or not self.enable_async:
            return

        self._async_running = True
        self._async_thread = threading.Thread(
            target=self._async_processor,
            daemon=True,
            name="EventBusAsync"
        )
        self._async_thread.start()

    def stop(self) -> None:
        """Stop async event processing."""
        self._async_running = False
        if self._async_thread:
            self._event_queue.put(None)  # Poison pill
            self._async_thread.join(timeout=2.0)

    def _async_processor(self) -> None:
        """Background thread for async event processing."""
        while self._async_running:
            try:
                item = self._event_queue.get(timeout=0.5)
                if item is None:
                    break

                event, subscription = item
                self._deliver_event(event, subscription)

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Async processor error: {e}")

    def subscribe(
        self,
        event_pattern: str,
        callback: Callable[[Event], None],
        subscriber_id: Optional[str] = None,
        priority: int = 0,
        async_handler: bool = False,
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Subscribe to events matching a pattern.

        Args:
            event_pattern: Pattern to match (e.g., "task.*", "system.health.*")
            callback: Function to call when event matches
            subscriber_id: Optional subscriber ID
            priority: Higher priority handlers called first
            async_handler: Process in background thread
            filters: Additional filters on payload

        Returns:
            Subscription ID
        """
        sub_id = subscriber_id or f"sub-{len(self._subscriptions)}-{time.time()}"

        subscription = Subscription(
            event_pattern=event_pattern,
            callback=callback,
            subscriber_id=sub_id,
            priority=priority,
            async_handler=async_handler,
            filters=filters or {}
        )

        with self._subscription_lock:
            self._subscriptions[event_pattern].append(subscription)
            # Sort by priority (descending)
            self._subscriptions[event_pattern].sort(
                key=lambda s: -s.priority
            )

        logger.debug(f"Subscribed {sub_id} to {event_pattern}")
        return sub_id

    def unsubscribe(self, subscriber_id: str) -> int:
        """
        Unsubscribe a subscriber from all events.

        Args:
            subscriber_id: Subscriber ID to remove

        Returns:
            Number of subscriptions removed
        """
        removed = 0
        with self._subscription_lock:
            for pattern in list(self._subscriptions.keys()):
                original_len = len(self._subscriptions[pattern])
                self._subscriptions[pattern] = [
                    s for s in self._subscriptions[pattern]
                    if s.subscriber_id != subscriber_id
                ]
                removed += original_len - len(self._subscriptions[pattern])

        return removed

    def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        source: str = "unknown",
        priority: EventPriority = EventPriority.NORMAL,
        sync: bool = False
    ) -> Event:
        """
        Publish an event.

        Args:
            event_type: Event type (e.g., "task.created")
            payload: Event data
            source: Source module name
            priority: Event priority
            sync: Force synchronous delivery

        Returns:
            The published Event
        """
        event = Event(
            event_type=event_type,
            payload=payload,
            source=source,
            priority=priority
        )

        self._events_published += 1

        # Add to history
        with self._history_lock:
            self._history.append(event)
            if len(self._history) > self.max_history:
                self._history = self._history[-self.max_history:]

        # Find matching subscriptions
        matching = self._find_matching_subscriptions(event_type)

        for subscription in matching:
            # Check filters
            if not self._matches_filters(event, subscription.filters):
                continue

            if subscription.async_handler and self.enable_async and not sync:
                self._event_queue.put((event, subscription))
            else:
                self._deliver_event(event, subscription)

        return event

    def _find_matching_subscriptions(self, event_type: str) -> List[Subscription]:
        """Find subscriptions matching an event type."""
        matching = []

        with self._subscription_lock:
            for pattern, subs in self._subscriptions.items():
                if self._pattern_matches(pattern, event_type):
                    matching.extend(subs)

        # Sort by priority
        matching.sort(key=lambda s: -s.priority)
        return matching

    def _pattern_matches(self, pattern: str, event_type: str) -> bool:
        """Check if a pattern matches an event type."""
        if pattern == "*":
            return True

        if pattern == event_type:
            return True

        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return event_type.startswith(prefix + ".")

        if "*" in pattern:
            # Simple glob matching
            parts = pattern.split("*")
            pos = 0
            for part in parts:
                if part:
                    idx = event_type.find(part, pos)
                    if idx < 0:
                        return False
                    pos = idx + len(part)
            return True

        return False

    def _matches_filters(self, event: Event, filters: Dict[str, Any]) -> bool:
        """Check if event matches subscription filters."""
        for key, value in filters.items():
            if key not in event.payload:
                return False
            if event.payload[key] != value:
                return False
        return True

    def _deliver_event(self, event: Event, subscription: Subscription) -> bool:
        """Deliver an event to a subscription."""
        try:
            subscription.callback(event)
            self._events_delivered += 1
            return True

        except Exception as e:
            logger.error(
                f"Event delivery failed: {event.event_type} -> "
                f"{subscription.subscriber_id}: {e}"
            )
            self._events_failed += 1
            self._dead_letters.append((event, str(e), time.time()))

            # Limit dead letter queue
            if len(self._dead_letters) > 100:
                self._dead_letters = self._dead_letters[-100:]

            return False

    def emit(
        self,
        event_type: str,
        source: str = "unknown",
        **kwargs
    ) -> Event:
        """
        Convenience method to emit an event.

        Args:
            event_type: Event type
            source: Source module
            **kwargs: Payload fields

        Returns:
            The published Event
        """
        return self.publish(event_type, kwargs, source)

    def get_history(
        self,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 50
    ) -> List[Event]:
        """Get event history with optional filtering."""
        with self._history_lock:
            events = list(self._history)

        if event_type:
            events = [e for e in events if self._pattern_matches(event_type, e.event_type)]

        if source:
            events = [e for e in events if e.source == source]

        return events[-limit:]

    def get_dead_letters(self) -> List[tuple]:
        """Get failed event deliveries."""
        return list(self._dead_letters)

    def clear_dead_letters(self) -> int:
        """Clear dead letter queue."""
        count = len(self._dead_letters)
        self._dead_letters.clear()
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics."""
        with self._subscription_lock:
            total_subs = sum(len(subs) for subs in self._subscriptions.values())
            patterns = list(self._subscriptions.keys())

        return {
            "events_published": self._events_published,
            "events_delivered": self._events_delivered,
            "events_failed": self._events_failed,
            "delivery_rate": (
                self._events_delivered / self._events_published
                if self._events_published > 0 else 1.0
            ),
            "total_subscriptions": total_subs,
            "subscription_patterns": patterns,
            "history_size": len(self._history),
            "dead_letters": len(self._dead_letters),
            "async_enabled": self.enable_async,
            "async_running": self._async_running
        }


# === Global Instance ===

_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create global event bus."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
        _global_bus.start()
    return _global_bus


# === Decorator for event handlers ===

def on_event(event_pattern: str, priority: int = 0, async_handler: bool = False):
    """
    Decorator for event handlers.

    Usage:
        @on_event("task.created")
        def handle_task_created(event):
            print(f"Task created: {event.payload}")
    """
    def decorator(func: Callable[[Event], None]):
        bus = get_event_bus()
        bus.subscribe(
            event_pattern=event_pattern,
            callback=func,
            subscriber_id=func.__name__,
            priority=priority,
            async_handler=async_handler
        )
        return func
    return decorator


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_event_bus():
        """Test event bus."""
        print("Testing Event Bus...")
        print("=" * 60)

        # Test 1: Create bus
        print("Test 1: Create bus...", end=" ")
        bus = EventBus(enable_async=False)
        print("PASS")

        # Test 2: Subscribe
        print("Test 2: Subscribe...", end=" ")
        events_received = []

        def handler(event) -> None:
            events_received.append(event)

        sub_id = bus.subscribe("task.*", handler)
        assert sub_id is not None
        print("PASS")

        # Test 3: Publish and receive
        print("Test 3: Publish and receive...", end=" ")
        event = bus.publish("task.created", {"title": "Test"}, source="test")
        assert len(events_received) == 1
        assert events_received[0].event_type == "task.created"
        print("PASS")

        # Test 4: Pattern matching
        print("Test 4: Pattern matching...", end=" ")
        bus.publish("task.updated", {"id": "123"}, source="test")
        assert len(events_received) == 2  # Matched "task.*"

        bus.publish("system.health.degraded", {}, source="test")
        assert len(events_received) == 2  # Didn't match
        print("PASS")

        # Test 5: Wildcard subscription
        print("Test 5: Wildcard subscription...", end=" ")
        all_events = []
        bus.subscribe("*", lambda e: all_events.append(e))
        bus.publish("anything.here", {}, source="test")
        assert len(all_events) == 1
        print("PASS")

        # Test 6: Filters
        print("Test 6: Filters...", end=" ")
        high_priority = []
        bus.subscribe(
            "task.*",
            lambda e: high_priority.append(e),
            filters={"priority": "high"}
        )
        bus.publish("task.created", {"priority": "low"}, source="test")
        bus.publish("task.created", {"priority": "high"}, source="test")
        assert len(high_priority) == 1
        print("PASS")

        # Test 7: Unsubscribe
        print("Test 7: Unsubscribe...", end=" ")
        removed = bus.unsubscribe(sub_id)
        assert removed == 1
        print("PASS")

        # Test 8: History
        print("Test 8: History...", end=" ")
        history = bus.get_history(limit=5)
        assert len(history) >= 3
        print("PASS")

        # Test 9: Priority ordering
        print("Test 9: Priority ordering...", end=" ")
        order = []
        bus.subscribe("order.*", lambda e: order.append(1), priority=1)
        bus.subscribe("order.*", lambda e: order.append(3), priority=3)
        bus.subscribe("order.*", lambda e: order.append(2), priority=2)
        bus.publish("order.test", {}, source="test")
        assert order == [3, 2, 1]  # Highest priority first
        print("PASS")

        # Test 10: Stats
        print("Test 10: Stats...", end=" ")
        stats = bus.get_stats()
        assert stats["events_published"] > 0
        assert stats["delivery_rate"] > 0
        print("PASS")

        print("=" * 60)
        print("\nAll tests passed!")
        return True

    success = test_event_bus()
    sys.exit(0 if success else 1)

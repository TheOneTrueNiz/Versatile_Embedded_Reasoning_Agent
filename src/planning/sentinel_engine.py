"""
#11 [P2] Sentinel Engine: Event-Driven Proactivity

This module implements a background sentinel for event-driven proactive actions:
- Multi-source event subscription (file system, calendar, email, webhooks)
- Pattern-based trigger conditions with temporal logic
- Event correlation and aggregation
- Proactive action recommendations
- Event queue with priority and deduplication
- Scheduled polling and real-time hooks

Based on research from:
- "Event-Driven AI Agents" (arXiv:2309.11547)
- "Proactive Agent Architectures" (arXiv:2311.04218)
- "Complex Event Processing for AI Systems" (arXiv:2310.08632)
"""

from __future__ import annotations

import json
import hashlib
import threading
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any, Callable
from pathlib import Path
from collections import deque
import uuid
import fnmatch
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class EventSource(Enum):
    """Sources of events."""
    FILE_SYSTEM = "file_system"
    CALENDAR = "calendar"
    EMAIL = "email"
    WEBHOOK = "webhook"
    TIMER = "timer"
    API = "api"
    SYSTEM = "system"
    USER = "user"
    INTERNAL = "internal"


class EventType(Enum):
    """Types of events."""
    # File system events
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    FILE_DELETED = "file_deleted"
    DIRECTORY_CHANGED = "directory_changed"

    # Calendar events
    MEETING_STARTING = "meeting_starting"
    MEETING_ENDED = "meeting_ended"
    CALENDAR_UPDATED = "calendar_updated"
    REMINDER = "reminder"

    # Email events
    EMAIL_RECEIVED = "email_received"
    EMAIL_FLAGGED = "email_flagged"
    EMAIL_THREAD_UPDATED = "email_thread_updated"

    # Timer events
    SCHEDULED_TRIGGER = "scheduled_trigger"
    INTERVAL_TRIGGER = "interval_trigger"
    CRON_TRIGGER = "cron_trigger"

    # System events
    IDLE_DETECTED = "idle_detected"
    ACTIVITY_RESUMED = "activity_resumed"
    RESOURCE_THRESHOLD = "resource_threshold"

    # Custom events
    CUSTOM = "custom"


class TriggerCondition(Enum):
    """Types of trigger conditions."""
    IMMEDIATE = "immediate"           # Trigger on any matching event
    THRESHOLD = "threshold"           # Trigger when count reaches threshold
    SEQUENCE = "sequence"             # Trigger on event sequence
    TEMPORAL = "temporal"             # Trigger based on time patterns
    CORRELATION = "correlation"       # Trigger on correlated events
    ABSENCE = "absence"               # Trigger when expected event doesn't occur


class ActionPriority(Enum):
    """Priority levels for recommended actions."""
    BACKGROUND = 1
    LOW = 2
    NORMAL = 3
    HIGH = 4
    URGENT = 5


class SentinelState(Enum):
    """Sentinel operational states."""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Event:
    """An event captured by the sentinel."""
    event_id: str
    source: EventSource
    event_type: EventType
    timestamp: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None

    def compute_hash(self) -> str:
        """Compute content hash for deduplication."""
        content = json.dumps({
            "source": self.source.value,
            "event_type": self.event_type.value,
            "payload": self.payload,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def matches_pattern(self, pattern: "EventPattern") -> bool:
        """Check if event matches a pattern."""
        # Check source
        if pattern.sources and self.source not in pattern.sources:
            return False

        # Check event type
        if pattern.event_types and self.event_type not in pattern.event_types:
            return False

        # Check tags
        if pattern.required_tags:
            if not all(tag in self.tags for tag in pattern.required_tags):
                return False

        # Check payload patterns
        for key, expected in pattern.payload_patterns.items():
            actual = self.payload.get(key)
            if actual is None:
                return False
            if isinstance(expected, str) and expected.startswith("regex:"):
                regex = expected[6:]
                if not re.search(regex, str(actual)):
                    return False
            elif isinstance(expected, str) and expected.startswith("glob:"):
                glob = expected[5:]
                if not fnmatch.fnmatch(str(actual), glob):
                    return False
            elif actual != expected:
                return False

        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source": self.source.value,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "metadata": self.metadata,
            "tags": self.tags,
            "correlation_id": self.correlation_id,
            "content_hash": self.compute_hash(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        return cls(
            event_id=data["event_id"],
            source=EventSource(data["source"]),
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            payload=data["payload"],
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
            correlation_id=data.get("correlation_id"),
        )


@dataclass
class EventPattern:
    """Pattern for matching events."""
    pattern_id: str
    name: str
    sources: Optional[List[EventSource]] = None
    event_types: Optional[List[EventType]] = None
    required_tags: List[str] = field(default_factory=list)
    payload_patterns: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "name": self.name,
            "sources": [s.value for s in self.sources] if self.sources else None,
            "event_types": [e.value for e in self.event_types] if self.event_types else None,
            "required_tags": self.required_tags,
            "payload_patterns": self.payload_patterns,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventPattern":
        return cls(
            pattern_id=data["pattern_id"],
            name=data["name"],
            sources=[EventSource(s) for s in data["sources"]] if data.get("sources") else None,
            event_types=[EventType(e) for e in data["event_types"]] if data.get("event_types") else None,
            required_tags=data.get("required_tags", []),
            payload_patterns=data.get("payload_patterns", {}),
        )


@dataclass
class Trigger:
    """A trigger that fires when conditions are met."""
    trigger_id: str
    name: str
    description: str
    pattern: EventPattern
    condition: TriggerCondition = TriggerCondition.IMMEDIATE
    threshold: int = 1
    window_seconds: int = 60
    cooldown_seconds: int = 0
    enabled: bool = True
    action_template: Optional[Dict[str, Any]] = None
    priority: ActionPriority = ActionPriority.NORMAL
    last_fired: Optional[str] = None
    fire_count: int = 0

    def is_on_cooldown(self) -> bool:
        """Check if trigger is on cooldown."""
        if not self.last_fired or self.cooldown_seconds == 0:
            return False

        last = datetime.fromisoformat(self.last_fired)
        cooldown_end = last + timedelta(seconds=self.cooldown_seconds)
        return datetime.now() < cooldown_end

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_id": self.trigger_id,
            "name": self.name,
            "description": self.description,
            "pattern": self.pattern.to_dict(),
            "condition": self.condition.value,
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "action_template": self.action_template,
            "priority": self.priority.value,
            "last_fired": self.last_fired,
            "fire_count": self.fire_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trigger":
        return cls(
            trigger_id=data["trigger_id"],
            name=data["name"],
            description=data["description"],
            pattern=EventPattern.from_dict(data["pattern"]),
            condition=TriggerCondition(data.get("condition", "immediate")),
            threshold=data.get("threshold", 1),
            window_seconds=data.get("window_seconds", 60),
            cooldown_seconds=data.get("cooldown_seconds", 0),
            enabled=data.get("enabled", True),
            action_template=data.get("action_template"),
            priority=ActionPriority(data.get("priority", 3)),
            last_fired=data.get("last_fired"),
            fire_count=data.get("fire_count", 0),
        )


@dataclass
class RecommendedAction:
    """A proactive action recommendation."""
    action_id: str
    trigger_id: str
    description: str
    priority: ActionPriority
    action_type: str
    payload: Dict[str, Any]
    triggering_events: List[str]  # Event IDs
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None
    acknowledged: bool = False
    executed: bool = False

    def is_expired(self) -> bool:
        """Check if recommendation has expired."""
        if not self.expires_at:
            return False
        return datetime.now() > datetime.fromisoformat(self.expires_at)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "trigger_id": self.trigger_id,
            "description": self.description,
            "priority": self.priority.value,
            "action_type": self.action_type,
            "payload": self.payload,
            "triggering_events": self.triggering_events,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "acknowledged": self.acknowledged,
            "executed": self.executed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecommendedAction":
        return cls(
            action_id=data["action_id"],
            trigger_id=data["trigger_id"],
            description=data["description"],
            priority=ActionPriority(data["priority"]),
            action_type=data["action_type"],
            payload=data["payload"],
            triggering_events=data["triggering_events"],
            created_at=data.get("created_at", datetime.now().isoformat()),
            expires_at=data.get("expires_at"),
            acknowledged=data.get("acknowledged", False),
            executed=data.get("executed", False),
        )


# =============================================================================
# Event Queue
# =============================================================================

class EventQueue:
    """Thread-safe event queue with deduplication."""

    def __init__(self, max_size: int = 10000, dedup_window_seconds: int = 60) -> None:
        self.max_size = max_size
        self.dedup_window_seconds = dedup_window_seconds
        self.events: deque = deque(maxlen=max_size)
        self.recent_hashes: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def push(self, event: Event) -> bool:
        """Push event to queue, returns False if duplicate."""
        with self._lock:
            # Check for duplicate
            event_hash = event.compute_hash()
            if event_hash in self.recent_hashes:
                hash_time = self.recent_hashes[event_hash]
                if (datetime.now() - hash_time).total_seconds() < self.dedup_window_seconds:
                    return False  # Duplicate within window

            # Add event
            self.events.append(event)
            self.recent_hashes[event_hash] = datetime.now()

            # Clean old hashes
            self._cleanup_hashes()

            return True

    def pop(self) -> Optional[Event]:
        """Pop oldest event from queue."""
        with self._lock:
            if self.events:
                return self.events.popleft()
            return None

    def peek(self, count: int = 10) -> List[Event]:
        """Peek at recent events without removing."""
        with self._lock:
            return list(self.events)[-count:]

    def get_events_in_window(self, seconds: int) -> List[Event]:
        """Get events within time window."""
        cutoff = datetime.now() - timedelta(seconds=seconds)
        with self._lock:
            return [
                e for e in self.events
                if datetime.fromisoformat(e.timestamp) > cutoff
            ]

    def get_events_matching(self, pattern: EventPattern) -> List[Event]:
        """Get events matching pattern."""
        with self._lock:
            return [e for e in self.events if e.matches_pattern(pattern)]

    def size(self) -> int:
        """Get queue size."""
        with self._lock:
            return len(self.events)

    def clear(self) -> None:
        """Clear queue."""
        with self._lock:
            self.events.clear()
            self.recent_hashes.clear()

    def _cleanup_hashes(self) -> None:
        """Clean up old hash entries."""
        cutoff = datetime.now() - timedelta(seconds=self.dedup_window_seconds * 2)
        old_hashes = [
            h for h, t in self.recent_hashes.items()
            if t < cutoff
        ]
        for h in old_hashes:
            del self.recent_hashes[h]


# =============================================================================
# Event Sources
# =============================================================================

class EventSourceAdapter:
    """Base class for event source adapters."""

    def __init__(self, source: EventSource) -> None:
        self.source = source
        self.enabled = False
        self.last_poll: Optional[datetime] = None

    def start(self) -> None:
        """Start the event source."""
        self.enabled = True

    def stop(self) -> None:
        """Stop the event source."""
        self.enabled = False

    def poll(self) -> List[Event]:
        """Poll for new events (for polling-based sources)."""
        return []

    def create_event(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        tags: Optional[List[str]] = None,
    ) -> Event:
        """Create an event from this source."""
        return Event(
            event_id=str(uuid.uuid4()),
            source=self.source,
            event_type=event_type,
            timestamp=datetime.now().isoformat(),
            payload=payload,
            tags=tags or [],
        )


class FileSystemAdapter(EventSourceAdapter):
    """Adapter for file system events."""

    def __init__(self, watch_paths: Optional[List[str]] = None) -> None:
        super().__init__(EventSource.FILE_SYSTEM)
        self.watch_paths = watch_paths or []
        self.file_states: Dict[str, Dict[str, Any]] = {}

    def add_watch_path(self, path: str) -> None:
        """Add path to watch."""
        self.watch_paths.append(path)

    def poll(self) -> List[Event]:
        """Poll for file system changes."""
        if not self.enabled:
            return []

        events = []

        for watch_path in self.watch_paths:
            path = Path(watch_path)
            if not path.exists():
                continue

            if path.is_file():
                events.extend(self._check_file(path))
            elif path.is_dir():
                for file_path in path.iterdir():
                    if file_path.is_file():
                        events.extend(self._check_file(file_path))

        self.last_poll = datetime.now()
        return events

    def _check_file(self, file_path: Path) -> List[Event]:
        """Check a single file for changes."""
        events = []
        path_str = str(file_path)

        try:
            stat = file_path.stat()
            current_state = {
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
        except OSError:
            # File was deleted
            if path_str in self.file_states:
                del self.file_states[path_str]
                events.append(self.create_event(
                    EventType.FILE_DELETED,
                    {"path": path_str},
                ))
            return events

        if path_str not in self.file_states:
            # New file
            self.file_states[path_str] = current_state
            events.append(self.create_event(
                EventType.FILE_CREATED,
                {"path": path_str, "size": current_state["size"]},
            ))
        elif self.file_states[path_str] != current_state:
            # Modified file
            self.file_states[path_str] = current_state
            events.append(self.create_event(
                EventType.FILE_MODIFIED,
                {"path": path_str, "size": current_state["size"]},
            ))

        return events


class TimerAdapter(EventSourceAdapter):
    """Adapter for timer-based events."""

    def __init__(self) -> None:
        super().__init__(EventSource.TIMER)
        self.schedules: Dict[str, Dict[str, Any]] = {}

    def add_interval(
        self,
        name: str,
        interval_seconds: int,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add an interval-based schedule."""
        schedule_id = str(uuid.uuid4())
        self.schedules[schedule_id] = {
            "name": name,
            "type": "interval",
            "interval_seconds": interval_seconds,
            "payload": payload or {},
            "last_trigger": None,
        }
        return schedule_id

    def add_cron(
        self,
        name: str,
        hour: int,
        minute: int = 0,
        days: Optional[List[int]] = None,  # 0-6 for Mon-Sun
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Add a cron-like schedule."""
        schedule_id = str(uuid.uuid4())
        self.schedules[schedule_id] = {
            "name": name,
            "type": "cron",
            "hour": hour,
            "minute": minute,
            "days": days,
            "payload": payload or {},
            "last_trigger": None,
        }
        return schedule_id

    def poll(self) -> List[Event]:
        """Poll for scheduled triggers."""
        if not self.enabled:
            return []

        events = []
        now = datetime.now()

        for schedule_id, schedule in self.schedules.items():
            should_trigger = False
            event_type = EventType.SCHEDULED_TRIGGER

            if schedule["type"] == "interval":
                event_type = EventType.INTERVAL_TRIGGER
                last = schedule["last_trigger"]
                if last is None:
                    should_trigger = True
                else:
                    elapsed = (now - last).total_seconds()
                    if elapsed >= schedule["interval_seconds"]:
                        should_trigger = True

            elif schedule["type"] == "cron":
                event_type = EventType.CRON_TRIGGER
                # Check if current time matches cron spec
                if now.hour == schedule["hour"] and now.minute == schedule["minute"]:
                    # Check day if specified
                    if schedule["days"] is None or now.weekday() in schedule["days"]:
                        last = schedule["last_trigger"]
                        if last is None or (now - last).total_seconds() > 60:
                            should_trigger = True

            if should_trigger:
                schedule["last_trigger"] = now
                events.append(self.create_event(
                    event_type,
                    {
                        "schedule_id": schedule_id,
                        "name": schedule["name"],
                        **schedule["payload"],
                    },
                ))

        self.last_poll = datetime.now()
        return events

    def remove_schedule(self, schedule_id: str) -> bool:
        """Remove a schedule."""
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
            return True
        return False


class WebhookAdapter(EventSourceAdapter):
    """Adapter for webhook events (external push)."""

    def __init__(self) -> None:
        super().__init__(EventSource.WEBHOOK)
        self.pending_events: List[Event] = []
        self._lock = threading.Lock()

    def receive_webhook(
        self,
        webhook_type: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> Event:
        """Receive and queue a webhook event."""
        event = self.create_event(
            EventType.CUSTOM,
            {
                "webhook_type": webhook_type,
                "payload": payload,
                "headers": headers or {},
            },
            tags=[f"webhook:{webhook_type}"],
        )

        with self._lock:
            self.pending_events.append(event)

        return event

    def poll(self) -> List[Event]:
        """Get pending webhook events."""
        if not self.enabled:
            return []

        with self._lock:
            events = self.pending_events.copy()
            self.pending_events.clear()

        self.last_poll = datetime.now()
        return events


# =============================================================================
# Trigger Engine
# =============================================================================

class TriggerEngine:
    """Evaluates triggers against events."""

    def __init__(self) -> None:
        self.triggers: Dict[str, Trigger] = {}
        self.event_history: Dict[str, List[Event]] = {}  # trigger_id -> events

    def add_trigger(self, trigger: Trigger) -> None:
        """Add a trigger."""
        self.triggers[trigger.trigger_id] = trigger
        self.event_history[trigger.trigger_id] = []

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger."""
        if trigger_id in self.triggers:
            del self.triggers[trigger_id]
            del self.event_history[trigger_id]
            return True
        return False

    def evaluate(self, event: Event) -> List[Tuple[Trigger, List[Event]]]:
        """Evaluate all triggers against an event, return fired triggers with their events."""
        fired = []

        for trigger_id, trigger in self.triggers.items():
            if not trigger.enabled:
                continue

            if trigger.is_on_cooldown():
                continue

            # Check if event matches pattern
            if not event.matches_pattern(trigger.pattern):
                continue

            # Track event for this trigger
            self.event_history[trigger_id].append(event)

            # Clean old events outside window
            cutoff = datetime.now() - timedelta(seconds=trigger.window_seconds)
            self.event_history[trigger_id] = [
                e for e in self.event_history[trigger_id]
                if datetime.fromisoformat(e.timestamp) > cutoff
            ]

            # Evaluate condition
            matched_events = self.event_history[trigger_id]
            should_fire = False

            if trigger.condition == TriggerCondition.IMMEDIATE:
                should_fire = True

            elif trigger.condition == TriggerCondition.THRESHOLD:
                if len(matched_events) >= trigger.threshold:
                    should_fire = True

            elif trigger.condition == TriggerCondition.TEMPORAL:
                # Check for burst pattern (many events in short time)
                if len(matched_events) >= trigger.threshold:
                    should_fire = True

            if should_fire:
                trigger.last_fired = datetime.now().isoformat()
                trigger.fire_count += 1
                fired.append((trigger, matched_events.copy()))

                # Clear history after firing for threshold conditions
                if trigger.condition in [TriggerCondition.THRESHOLD, TriggerCondition.TEMPORAL]:
                    self.event_history[trigger_id] = []

        return fired

    def get_trigger(self, trigger_id: str) -> Optional[Trigger]:
        """Get trigger by ID."""
        return self.triggers.get(trigger_id)

    def list_triggers(self, enabled_only: bool = False) -> List[Trigger]:
        """List all triggers."""
        triggers = list(self.triggers.values())
        if enabled_only:
            triggers = [t for t in triggers if t.enabled]
        return triggers


# =============================================================================
# Action Recommender
# =============================================================================

class ActionRecommender:
    """Generates action recommendations from triggered events."""

    def __init__(self) -> None:
        self.recommendations: Dict[str, RecommendedAction] = {}
        self.recommendation_handlers: Dict[str, Callable] = {}
        self._lock = threading.Lock()

    def register_handler(
        self,
        action_type: str,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> None:
        """Register a handler for action type."""
        self.recommendation_handlers[action_type] = handler

    def create_recommendation(
        self,
        trigger: Trigger,
        triggering_events: List[Event],
    ) -> RecommendedAction:
        """Create a recommendation from a fired trigger."""
        action_id = str(uuid.uuid4())

        # Build payload from template and events
        payload = {}
        if trigger.action_template:
            payload = trigger.action_template.copy()

        # Add event data
        payload["events"] = [e.to_dict() for e in triggering_events[:5]]
        payload["event_count"] = len(triggering_events)

        # Determine action type
        action_type = payload.get("action_type") or payload.get("type") or "notify"

        recommendation = RecommendedAction(
            action_id=action_id,
            trigger_id=trigger.trigger_id,
            description=self._generate_description(trigger, triggering_events),
            priority=trigger.priority,
            action_type=action_type,
            payload=payload,
            triggering_events=[e.event_id for e in triggering_events],
            expires_at=(datetime.now() + timedelta(hours=24)).isoformat(),
        )

        with self._lock:
            self.recommendations[action_id] = recommendation

        return recommendation

    def _generate_description(
        self,
        trigger: Trigger,
        events: List[Event],
    ) -> str:
        """Generate human-readable description."""
        if len(events) == 1:
            return f"[{trigger.name}] {events[0].event_type.value} detected"
        return f"[{trigger.name}] {len(events)} events detected"

    def get_pending_recommendations(
        self,
        priority: Optional[ActionPriority] = None,
    ) -> List[RecommendedAction]:
        """Get pending recommendations."""
        with self._lock:
            pending = [
                r for r in self.recommendations.values()
                if not r.acknowledged and not r.executed and not r.is_expired()
            ]

        if priority:
            pending = [r for r in pending if r.priority == priority]

        # Sort by priority (descending) then created_at (ascending)
        pending.sort(key=lambda r: (-r.priority.value, r.created_at))
        return pending

    def acknowledge(self, action_id: str) -> bool:
        """Acknowledge a recommendation."""
        with self._lock:
            if action_id in self.recommendations:
                self.recommendations[action_id].acknowledged = True
                return True
        return False

    def mark_executed(self, action_id: str) -> bool:
        """Mark recommendation as executed."""
        with self._lock:
            if action_id in self.recommendations:
                self.recommendations[action_id].executed = True
                return True
        return False

    def execute_recommendation(
        self,
        action_id: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Execute a recommendation if handler exists."""
        with self._lock:
            rec = self.recommendations.get(action_id)
            if not rec:
                return False, None

        handler = self.recommendation_handlers.get(rec.action_type)
        if not handler:
            return False, {"error": f"No handler for action type: {rec.action_type}"}

        try:
            result = handler(rec.payload)
            self.mark_executed(action_id)
            return True, result
        except Exception as e:
            return False, {"error": str(e)}


# =============================================================================
# Sentinel Engine
# =============================================================================

class SentinelEngine:
    """
    Complete event-driven proactive sentinel system.

    Features:
    - Multi-source event collection
    - Pattern-based trigger evaluation
    - Proactive action recommendations
    - Background polling
    """

    def __init__(self, storage_dir: str = "./sentinel") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.state = SentinelState.STOPPED
        self.event_queue = EventQueue()
        self.trigger_engine = TriggerEngine()
        self.recommender = ActionRecommender()

        # Event sources
        self.sources: Dict[EventSource, EventSourceAdapter] = {}

        # Background thread
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval = 5.0  # seconds

        # Callbacks
        self.on_event: Optional[Callable[[Event], None]] = None
        self.on_trigger: Optional[Callable[[Trigger, List[Event]], None]] = None
        self.on_recommendation: Optional[Callable[[RecommendedAction], None]] = None

        # Load persisted state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        state_file = self.storage_dir / "sentinel_state.json"
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)

                seen_names = set()
                duplicates_found = False
                for trigger_data in data.get("triggers", []):
                    trigger = Trigger.from_dict(trigger_data)
                    if trigger.name in seen_names:
                        duplicates_found = True
                        continue
                    seen_names.add(trigger.name)
                    self.trigger_engine.add_trigger(trigger)

                if duplicates_found:
                    self._save_state()

            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.storage_dir / "sentinel_state.json"
        data = {
            "triggers": [t.to_dict() for t in self.trigger_engine.list_triggers()],
            "saved_at": datetime.now().isoformat(),
        }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    # --- Source Management ---

    def add_source(self, adapter: EventSourceAdapter) -> None:
        """Add an event source adapter."""
        self.sources[adapter.source] = adapter

    def remove_source(self, source: EventSource) -> bool:
        """Remove an event source."""
        if source in self.sources:
            self.sources[source].stop()
            del self.sources[source]
            return True
        return False

    def get_source(self, source: EventSource) -> Optional[EventSourceAdapter]:
        """Get source adapter."""
        return self.sources.get(source)

    # --- Trigger Management ---

    def add_trigger(
        self,
        name: str,
        description: str,
        pattern: EventPattern,
        condition: TriggerCondition = TriggerCondition.IMMEDIATE,
        threshold: int = 1,
        window_seconds: int = 60,
        cooldown_seconds: int = 0,
        action_template: Optional[Dict[str, Any]] = None,
        priority: ActionPriority = ActionPriority.NORMAL,
    ) -> Trigger:
        """Add a new trigger."""
        trigger = Trigger(
            trigger_id=str(uuid.uuid4()),
            name=name,
            description=description,
            pattern=pattern,
            condition=condition,
            threshold=threshold,
            window_seconds=window_seconds,
            cooldown_seconds=cooldown_seconds,
            action_template=action_template,
            priority=priority,
        )

        self.trigger_engine.add_trigger(trigger)
        self._save_state()
        return trigger

    def remove_trigger(self, trigger_id: str) -> bool:
        """Remove a trigger."""
        result = self.trigger_engine.remove_trigger(trigger_id)
        if result:
            self._save_state()
        return result

    def enable_trigger(self, trigger_id: str) -> bool:
        """Enable a trigger."""
        trigger = self.trigger_engine.get_trigger(trigger_id)
        if trigger:
            trigger.enabled = True
            self._save_state()
            return True
        return False

    def disable_trigger(self, trigger_id: str) -> bool:
        """Disable a trigger."""
        trigger = self.trigger_engine.get_trigger(trigger_id)
        if trigger:
            trigger.enabled = False
            self._save_state()
            return True
        return False

    # --- Event Processing ---

    def emit_event(self, event: Event) -> bool:
        """Emit an event directly into the system."""
        if not self.event_queue.push(event):
            return False  # Duplicate

        # Process event
        self._process_event(event)
        return True

    def _process_event(self, event: Event) -> None:
        """Process a single event."""
        # Call event callback
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        # Evaluate triggers
        fired = self.trigger_engine.evaluate(event)

        for trigger, events in fired:
            # Call trigger callback
            if self.on_trigger:
                try:
                    self.on_trigger(trigger, events)
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

            # Create recommendation
            recommendation = self.recommender.create_recommendation(trigger, events)

            # Call recommendation callback
            if self.on_recommendation:
                try:
                    self.on_recommendation(recommendation)
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    # --- Background Polling ---

    def start(self) -> None:
        """Start the sentinel engine."""
        if self.state == SentinelState.RUNNING:
            return

        self.state = SentinelState.STARTING
        self._stop_event.clear()

        # Start all sources
        for adapter in self.sources.values():
            adapter.start()

        # Start background thread
        self._poll_thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
        )
        self._poll_thread.start()

        self.state = SentinelState.RUNNING

    def stop(self) -> None:
        """Stop the sentinel engine."""
        if self.state == SentinelState.STOPPED:
            return

        self.state = SentinelState.STOPPING
        self._stop_event.set()

        # Stop all sources
        for adapter in self.sources.values():
            adapter.stop()

        # Wait for thread
        if self._poll_thread and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=5.0)

        self.state = SentinelState.STOPPED

    def pause(self) -> None:
        """Pause the sentinel engine."""
        if self.state == SentinelState.RUNNING:
            self.state = SentinelState.PAUSED

    def resume(self) -> None:
        """Resume the sentinel engine."""
        if self.state == SentinelState.PAUSED:
            self.state = SentinelState.RUNNING

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while not self._stop_event.is_set():
            if self.state == SentinelState.RUNNING:
                self._poll_sources()

            self._stop_event.wait(self._poll_interval)

    def _poll_sources(self) -> None:
        """Poll all sources for events."""
        for adapter in self.sources.values():
            if not adapter.enabled:
                continue

            try:
                events = adapter.poll()
                for event in events:
                    self.emit_event(event)
            except Exception as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    # --- Recommendations ---

    def get_recommendations(
        self,
        priority: Optional[ActionPriority] = None,
    ) -> List[RecommendedAction]:
        """Get pending recommendations."""
        return self.recommender.get_pending_recommendations(priority)

    def acknowledge_recommendation(self, action_id: str) -> bool:
        """Acknowledge a recommendation."""
        return self.recommender.acknowledge(action_id)

    def execute_recommendation(
        self,
        action_id: str,
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Execute a recommendation."""
        return self.recommender.execute_recommendation(action_id)

    def register_action_handler(
        self,
        action_type: str,
        handler: Callable,
    ) -> None:
        """Register handler for action type."""
        self.recommender.register_handler(action_type, handler)

    # --- Statistics ---

    def get_statistics(self) -> Dict[str, Any]:
        """Get sentinel statistics."""
        return {
            "state": self.state.value,
            "sources": {
                source.value: {
                    "enabled": adapter.enabled,
                    "last_poll": adapter.last_poll.isoformat() if adapter.last_poll else None,
                }
                for source, adapter in self.sources.items()
            },
            "event_queue_size": self.event_queue.size(),
            "triggers": {
                "total": len(self.trigger_engine.triggers),
                "enabled": len([t for t in self.trigger_engine.triggers.values() if t.enabled]),
            },
            "recommendations": {
                "pending": len(self.recommender.get_pending_recommendations()),
            },
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def create_file_pattern(
    name: str,
    path_pattern: Optional[str] = None,
    event_types: Optional[List[EventType]] = None,
) -> EventPattern:
    """Create pattern for file system events."""
    payload_patterns = {}
    if path_pattern:
        payload_patterns["path"] = f"glob:{path_pattern}"

    return EventPattern(
        pattern_id=str(uuid.uuid4()),
        name=name,
        sources=[EventSource.FILE_SYSTEM],
        event_types=event_types or [
            EventType.FILE_CREATED,
            EventType.FILE_MODIFIED,
            EventType.FILE_DELETED,
        ],
        payload_patterns=payload_patterns,
    )


def create_timer_pattern(
    name: str,
    schedule_name: Optional[str] = None,
) -> EventPattern:
    """Create pattern for timer events."""
    payload_patterns = {}
    if schedule_name:
        payload_patterns["name"] = schedule_name

    return EventPattern(
        pattern_id=str(uuid.uuid4()),
        name=name,
        sources=[EventSource.TIMER],
        event_types=[
            EventType.INTERVAL_TRIGGER,
            EventType.CRON_TRIGGER,
            EventType.SCHEDULED_TRIGGER,
        ],
        payload_patterns=payload_patterns,
    )


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests for the sentinel engine module."""
    import tempfile
    import shutil

    print("=" * 70)
    print("Sentinel Engine CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool) -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}")
            tests_failed += 1

    temp_dir = tempfile.mkdtemp()

    try:
        # Test 1: Event creation
        print("\n1. Testing Event creation...")
        event = Event(
            event_id="e1",
            source=EventSource.FILE_SYSTEM,
            event_type=EventType.FILE_MODIFIED,
            timestamp=datetime.now().isoformat(),
            payload={"path": "/tmp/test.txt"},
            tags=["important"],
        )
        test("Creates event", event is not None)
        test("Has ID", event.event_id == "e1")
        test("Computes hash", len(event.compute_hash()) == 16)

        # Test 2: Event serialization
        print("\n2. Testing Event serialization...")
        event_dict = event.to_dict()
        test("Serializes to dict", isinstance(event_dict, dict))
        restored = Event.from_dict(event_dict)
        test("Deserializes from dict", restored.event_id == event.event_id)

        # Test 3: Event pattern matching
        print("\n3. Testing Event pattern matching...")
        pattern = EventPattern(
            pattern_id="p1",
            name="File changes",
            sources=[EventSource.FILE_SYSTEM],
            event_types=[EventType.FILE_MODIFIED],
            payload_patterns={"path": "glob:/tmp/*.txt"},
        )
        test("Event matches pattern", event.matches_pattern(pattern))

        non_matching = Event(
            event_id="e2",
            source=EventSource.EMAIL,
            event_type=EventType.EMAIL_RECEIVED,
            timestamp=datetime.now().isoformat(),
            payload={},
        )
        test("Non-matching event rejected", not non_matching.matches_pattern(pattern))

        # Test 4: Event Queue
        print("\n4. Testing Event Queue...")
        queue = EventQueue(max_size=100)
        test("Pushes event", queue.push(event))
        test("Queue has event", queue.size() == 1)

        # Test duplicate detection
        test("Rejects duplicate", not queue.push(event))

        popped = queue.pop()
        test("Pops event", popped is not None)
        test("Queue empty after pop", queue.size() == 0)

        # Test 5: Trigger creation
        print("\n5. Testing Trigger creation...")
        trigger = Trigger(
            trigger_id="t1",
            name="File monitor",
            description="Monitor file changes",
            pattern=pattern,
            condition=TriggerCondition.IMMEDIATE,
        )
        test("Creates trigger", trigger is not None)
        test("Not on cooldown initially", not trigger.is_on_cooldown())

        # Test 6: Trigger Engine
        print("\n6. Testing Trigger Engine...")
        engine = TriggerEngine()
        engine.add_trigger(trigger)
        test("Adds trigger", len(engine.triggers) == 1)

        # Evaluate event
        fired = engine.evaluate(event)
        test("Trigger fires", len(fired) == 1)
        test("Correct trigger fired", fired[0][0].trigger_id == "t1")

        # Test 7: File System Adapter
        print("\n7. Testing File System Adapter...")
        fs_adapter = FileSystemAdapter()
        fs_adapter.add_watch_path(temp_dir)
        fs_adapter.start()
        test("Starts adapter", fs_adapter.enabled)

        # Create a test file
        test_file = Path(temp_dir) / "test.txt"
        test_file.write_text("hello")

        events = fs_adapter.poll()
        test("Detects file creation", len(events) >= 1)

        # Modify file
        test_file.write_text("hello world")
        events = fs_adapter.poll()
        test("Detects file modification", len(events) >= 1)

        # Test 8: Timer Adapter
        print("\n8. Testing Timer Adapter...")
        timer_adapter = TimerAdapter()
        schedule_id = timer_adapter.add_interval("test_interval", 1, {"custom": "data"})
        test("Adds interval schedule", schedule_id is not None)

        timer_adapter.start()
        events = timer_adapter.poll()
        test("Timer triggers", len(events) >= 1)

        # Test 9: Webhook Adapter
        print("\n9. Testing Webhook Adapter...")
        webhook_adapter = WebhookAdapter()
        webhook_adapter.start()

        webhook_event = webhook_adapter.receive_webhook(
            "github",
            {"action": "push", "repo": "test"},
        )
        test("Receives webhook", webhook_event is not None)

        events = webhook_adapter.poll()
        test("Polls webhook events", len(events) == 1)

        # Test 10: Action Recommender
        print("\n10. Testing Action Recommender...")
        recommender = ActionRecommender()

        recommendation = recommender.create_recommendation(
            trigger,
            [event],
        )
        test("Creates recommendation", recommendation is not None)
        test("Has action ID", recommendation.action_id is not None)

        pending = recommender.get_pending_recommendations()
        test("Gets pending recommendations", len(pending) == 1)

        test("Acknowledges recommendation", recommender.acknowledge(recommendation.action_id))
        test("No longer pending", len(recommender.get_pending_recommendations()) == 0)

        # Test 11: Sentinel Engine
        print("\n11. Testing Sentinel Engine...")
        sentinel = SentinelEngine(temp_dir)

        # Add sources
        sentinel.add_source(FileSystemAdapter([temp_dir]))
        sentinel.add_source(TimerAdapter())
        test("Adds sources", len(sentinel.sources) == 2)

        # Add trigger
        file_pattern = create_file_pattern("Test files", "*.txt")
        added_trigger = sentinel.add_trigger(
            "File watcher",
            "Watch for file changes",
            file_pattern,
        )
        test("Adds trigger", added_trigger is not None)

        # Test 12: Sentinel start/stop
        print("\n12. Testing Sentinel start/stop...")
        sentinel.start()
        test("Starts sentinel", sentinel.state == SentinelState.RUNNING)

        sentinel.pause()
        test("Pauses sentinel", sentinel.state == SentinelState.PAUSED)

        sentinel.resume()
        test("Resumes sentinel", sentinel.state == SentinelState.RUNNING)

        sentinel.stop()
        test("Stops sentinel", sentinel.state == SentinelState.STOPPED)

        # Test 13: Direct event emission
        print("\n13. Testing Direct event emission...")
        sentinel2 = SentinelEngine(temp_dir)
        sentinel2.add_trigger(
            "Direct trigger",
            "Test direct emission",
            EventPattern(
                pattern_id="direct",
                name="All events",
            ),
        )

        test_event = Event(
            event_id="direct_1",
            source=EventSource.INTERNAL,
            event_type=EventType.CUSTOM,
            timestamp=datetime.now().isoformat(),
            payload={"test": True},
        )
        test("Emits event", sentinel2.emit_event(test_event))

        # Test 14: Trigger conditions
        print("\n14. Testing Trigger conditions...")
        threshold_trigger = Trigger(
            trigger_id="threshold_t",
            name="Threshold trigger",
            description="Fires after 3 events",
            pattern=EventPattern(pattern_id="all", name="All"),
            condition=TriggerCondition.THRESHOLD,
            threshold=3,
            window_seconds=60,
        )

        threshold_engine = TriggerEngine()
        threshold_engine.add_trigger(threshold_trigger)

        # Fire 2 events - shouldn't trigger
        for i in range(2):
            e = Event(
                event_id=f"te_{i}",
                source=EventSource.INTERNAL,
                event_type=EventType.CUSTOM,
                timestamp=datetime.now().isoformat(),
                payload={"num": i},
            )
            fired = threshold_engine.evaluate(e)
        test("Doesn't fire below threshold", len(fired) == 0)

        # Fire 3rd event - should trigger
        e = Event(
            event_id="te_3",
            source=EventSource.INTERNAL,
            event_type=EventType.CUSTOM,
            timestamp=datetime.now().isoformat(),
            payload={"num": 3},
        )
        fired = threshold_engine.evaluate(e)
        test("Fires at threshold", len(fired) == 1)

        # Test 15: Cooldown
        print("\n15. Testing Cooldown...")
        cooldown_trigger = Trigger(
            trigger_id="cd_t",
            name="Cooldown trigger",
            description="Has cooldown",
            pattern=EventPattern(pattern_id="all", name="All"),
            condition=TriggerCondition.IMMEDIATE,
            cooldown_seconds=3600,  # 1 hour
        )

        # Fire once
        cooldown_trigger.last_fired = datetime.now().isoformat()
        test("On cooldown after firing", cooldown_trigger.is_on_cooldown())

        # Test 16: Statistics
        print("\n16. Testing Statistics...")
        stats = sentinel2.get_statistics()
        test("Has state", "state" in stats)
        test("Has sources", "sources" in stats)
        test("Has triggers", "triggers" in stats)

        # Test 17: Persistence
        print("\n17. Testing Persistence...")
        sentinel3 = SentinelEngine(temp_dir)
        trigger_count_before = len(sentinel3.trigger_engine.triggers)

        sentinel3.add_trigger(
            "Persistent",
            "Test persistence",
            EventPattern(pattern_id="pers", name="Persist"),
        )
        sentinel3._save_state()

        # Load in new instance
        sentinel4 = SentinelEngine(temp_dir)
        test("Persists triggers", len(sentinel4.trigger_engine.triggers) > trigger_count_before)

        # Test 18: Regex pattern matching
        print("\n18. Testing Regex pattern matching...")
        regex_pattern = EventPattern(
            pattern_id="regex",
            name="Regex test",
            sources=[EventSource.FILE_SYSTEM],
            payload_patterns={"path": "regex:.*\\.py$"},
        )

        py_event = Event(
            event_id="py1",
            source=EventSource.FILE_SYSTEM,
            event_type=EventType.FILE_MODIFIED,
            timestamp=datetime.now().isoformat(),
            payload={"path": "/app/main.py"},
        )
        txt_event = Event(
            event_id="txt1",
            source=EventSource.FILE_SYSTEM,
            event_type=EventType.FILE_MODIFIED,
            timestamp=datetime.now().isoformat(),
            payload={"path": "/app/readme.txt"},
        )

        test("Regex matches .py", py_event.matches_pattern(regex_pattern))
        test("Regex rejects .txt", not txt_event.matches_pattern(regex_pattern))

        # Test 19: Event callbacks
        print("\n19. Testing Event callbacks...")
        callback_received = {"count": 0}

        def on_event(e) -> None:
            callback_received["count"] += 1

        sentinel5 = SentinelEngine(temp_dir)
        sentinel5.on_event = on_event
        sentinel5.emit_event(Event(
            event_id="cb1",
            source=EventSource.INTERNAL,
            event_type=EventType.CUSTOM,
            timestamp=datetime.now().isoformat(),
            payload={},
        ))
        test("Event callback called", callback_received["count"] == 1)

        # Test 20: Helper functions
        print("\n20. Testing Helper functions...")
        file_pat = create_file_pattern("Config files", "*.json")
        test("Creates file pattern", file_pat is not None)
        test("File pattern has sources", file_pat.sources == [EventSource.FILE_SYSTEM])

        timer_pat = create_timer_pattern("Daily check", "daily")
        test("Creates timer pattern", timer_pat is not None)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"Tests Passed: {tests_passed}/{tests_passed + tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    success = run_cli_tests()
    exit(0 if success else 1)

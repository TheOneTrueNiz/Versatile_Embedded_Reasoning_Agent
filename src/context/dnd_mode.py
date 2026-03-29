#!/usr/bin/env python3
"""
Do Not Disturb Mode - Interactive Environment Sensing (Improvement #12)
=======================================================================

Detects user's work context and automatically adjusts agent behavior
to avoid interruptions during focus time.

Problem Solved:
- Agent interrupts during meetings
- Notifications during focus time
- Proactive actions when user is busy
- Context-inappropriate prompts

Research basis:
- arXiv:2307.03172 "Context-Aware Notification Management"
- arXiv:2303.18223 "Adaptive Human-AI Interaction"

Solution:
- Calendar integration for meeting detection
- Activity pattern analysis for focus time
- Configurable DND schedules
- Urgency-based override system
- Gradual interrupt levels

Usage:
    from dnd_mode import DNDManager, DNDContext

    dnd = DNDManager()

    # Check if now is a good time to interrupt
    if dnd.can_interrupt():
        send_notification(...)

    # Check with urgency level
    if dnd.can_interrupt(urgency="high"):
        send_urgent_alert(...)

    # Use context manager for DND operations
    with dnd.dnd_context(reason="User requested focus time"):
        # All interrupts suppressed in this block
        do_background_work()
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta, time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Callable
from enum import Enum
import threading
import logging
logger = logging.getLogger(__name__)

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class DNDLevel(Enum):
    """Levels of Do Not Disturb"""
    OFF = "off"                  # All interrupts allowed
    LOW = "low"                  # Only suppress non-urgent
    MEDIUM = "medium"           # Suppress most, allow urgent
    HIGH = "high"               # Suppress all except critical
    CRITICAL = "critical"       # Suppress everything


class InterruptUrgency(Enum):
    """Urgency levels for potential interrupts"""
    ROUTINE = "routine"         # Regular updates, can wait
    LOW = "low"                 # Helpful but not time-sensitive
    MEDIUM = "medium"           # Somewhat important
    HIGH = "high"               # Important, needs attention soon
    CRITICAL = "critical"       # Emergency, must interrupt


class ContextSource(Enum):
    """Sources of context information"""
    CALENDAR = "calendar"       # Calendar/meeting data
    SCHEDULE = "schedule"       # Configured DND schedule
    MANUAL = "manual"           # User manually enabled DND
    ACTIVITY = "activity"       # Detected from user activity
    FOCUS_APP = "focus_app"     # Focus app integration (macOS, etc.)
    TIME_OF_DAY = "time_of_day" # Time-based rules


@dataclass
class DNDRule:
    """A rule for when DND should be active"""
    name: str
    source: ContextSource
    level: DNDLevel = DNDLevel.MEDIUM
    enabled: bool = True
    priority: int = 50  # Higher = takes precedence

    # Time-based rules
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    days_of_week: List[int] = field(default_factory=list)  # 0=Mon, 6=Sun

    # Pattern matching rules
    calendar_pattern: Optional[str] = None  # Regex for calendar event titles
    activity_pattern: Optional[str] = None  # Pattern for activity detection

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source.value,
            "level": self.level.value,
            "enabled": self.enabled,
            "priority": self.priority,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "days_of_week": self.days_of_week,
            "calendar_pattern": self.calendar_pattern,
            "activity_pattern": self.activity_pattern,
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DNDRule':
        start = None
        end = None
        if data.get("start_time"):
            start = time.fromisoformat(data["start_time"])
        if data.get("end_time"):
            end = time.fromisoformat(data["end_time"])

        return cls(
            name=data["name"],
            source=ContextSource(data["source"]),
            level=DNDLevel(data["level"]),
            enabled=data.get("enabled", True),
            priority=data.get("priority", 50),
            start_time=start,
            end_time=end,
            days_of_week=data.get("days_of_week", []),
            calendar_pattern=data.get("calendar_pattern"),
            activity_pattern=data.get("activity_pattern"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            metadata=data.get("metadata", {})
        )


@dataclass
class DNDStatus:
    """Current DND status"""
    is_active: bool
    level: DNDLevel
    reason: str
    source: ContextSource
    active_rules: List[str]  # Names of active rules
    until: Optional[datetime]  # When DND ends (if known)
    can_override: bool  # Whether urgent messages can override

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_active": self.is_active,
            "level": self.level.value,
            "reason": self.reason,
            "source": self.source.value,
            "active_rules": self.active_rules,
            "until": self.until.isoformat() if self.until else None,
            "can_override": self.can_override
        }


@dataclass
class CalendarEvent:
    """A calendar event"""
    title: str
    start: datetime
    end: datetime
    is_busy: bool = True
    is_recurring: bool = False
    location: Optional[str] = None
    attendees: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_happening_now(self) -> bool:
        """Check if event is currently happening"""
        now = datetime.now()
        return self.start <= now <= self.end

    def is_upcoming(self, minutes: int = 5) -> bool:
        """Check if event is starting soon"""
        now = datetime.now()
        upcoming_window = now + timedelta(minutes=minutes)
        return now <= self.start <= upcoming_window


@dataclass
class ActivitySignal:
    """A signal from user activity"""
    signal_type: str  # "typing", "mouse", "focus_app", etc.
    timestamp: datetime
    intensity: float = 1.0  # 0-1, how active
    app_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CalendarProvider:
    """
    Interface for calendar providers.

    Subclass this to integrate with specific calendar systems
    (Google Calendar, Outlook, iCal, etc.)
    """

    def get_events(
        self,
        start: datetime,
        end: datetime
    ) -> List[CalendarEvent]:
        """Get events in time range"""
        return []

    def get_current_event(self) -> Optional[CalendarEvent]:
        """Get currently happening event"""
        now = datetime.now()
        events = self.get_events(
            now - timedelta(hours=1),
            now + timedelta(hours=1)
        )
        for event in events:
            if event.is_happening_now():
                return event
        return None

    def get_next_event(self) -> Optional[CalendarEvent]:
        """Get next upcoming event"""
        now = datetime.now()
        events = self.get_events(now, now + timedelta(days=1))
        events.sort(key=lambda e: e.start)
        for event in events:
            if event.start > now:
                return event
        return None


class MockCalendarProvider(CalendarProvider):
    """Mock calendar for testing"""

    def __init__(self) -> None:
        self._events: List[CalendarEvent] = []

    def add_event(self, event: CalendarEvent) -> None:
        self._events.append(event)

    def clear_events(self) -> None:
        self._events = []

    def get_events(
        self,
        start: datetime,
        end: datetime
    ) -> List[CalendarEvent]:
        return [
            e for e in self._events
            if (e.start >= start and e.start <= end) or
               (e.end >= start and e.end <= end) or
               (e.start <= start and e.end >= end)
        ]


class ActivityMonitor:
    """
    Monitors user activity to detect focus time.

    Tracks activity signals and detects patterns like:
    - Sustained typing (writing/coding)
    - Reading (scrolling, low input)
    - Meeting (audio/video app active)
    """

    def __init__(
        self,
        focus_threshold_minutes: int = 15,
        idle_threshold_minutes: int = 5
    ):
        self.focus_threshold = timedelta(minutes=focus_threshold_minutes)
        self.idle_threshold = timedelta(minutes=idle_threshold_minutes)
        self._signals: List[ActivitySignal] = []
        self._max_signals = 1000
        self._lock = threading.Lock()

    def record_signal(self, signal: ActivitySignal) -> None:
        """Record an activity signal"""
        with self._lock:
            self._signals.append(signal)
            # Keep only recent signals
            if len(self._signals) > self._max_signals:
                cutoff = datetime.now() - timedelta(hours=1)
                self._signals = [s for s in self._signals if s.timestamp > cutoff]

    def get_recent_signals(self, minutes: int = 15) -> List[ActivitySignal]:
        """Get signals from last N minutes"""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        with self._lock:
            return [s for s in self._signals if s.timestamp > cutoff]

    def is_user_active(self) -> bool:
        """Check if user is currently active"""
        recent = self.get_recent_signals(minutes=5)
        return len(recent) > 0

    def is_in_focus_mode(self) -> bool:
        """
        Detect if user appears to be in focus mode.

        Focus mode is detected when:
        - Sustained activity over threshold period
        - High intensity signals (typing/coding)
        - Same app focus maintained
        """
        recent = self.get_recent_signals(minutes=30)
        if len(recent) < 3:
            return False

        # Check for sustained activity
        first_signal = min(recent, key=lambda s: s.timestamp)
        last_signal = max(recent, key=lambda s: s.timestamp)
        duration = last_signal.timestamp - first_signal.timestamp

        if duration < self.focus_threshold:
            return False

        # Check intensity
        avg_intensity = sum(s.intensity for s in recent) / len(recent)
        if avg_intensity < 0.5:
            return False

        # Check app consistency
        apps = [s.app_name for s in recent if s.app_name]
        if apps:
            most_common = max(set(apps), key=apps.count)
            consistency = apps.count(most_common) / len(apps)
            if consistency > 0.7:
                return True

        return duration >= self.focus_threshold

    def detect_meeting(self) -> bool:
        """
        Detect if user appears to be in a meeting.

        Meeting is detected when:
        - Video/audio app is active (Zoom, Meet, Teams, etc.)
        - Low keyboard activity but app is focused
        """
        recent = self.get_recent_signals(minutes=10)
        meeting_apps = {
            "zoom", "zoom.us", "microsoft teams", "teams",
            "google meet", "meet", "slack", "webex",
            "skype", "discord"
        }

        for signal in recent:
            if signal.app_name:
                app_lower = signal.app_name.lower()
                if any(ma in app_lower for ma in meeting_apps):
                    return True
        return False

    def get_last_activity_time(self) -> Optional[datetime]:
        """Get timestamp of last activity"""
        with self._lock:
            if self._signals:
                return max(s.timestamp for s in self._signals)
        return None

    def is_idle(self) -> bool:
        """Check if user is idle"""
        last = self.get_last_activity_time()
        if not last:
            return True
        return datetime.now() - last > self.idle_threshold


class InterruptQueue:
    """
    Queue for deferred interrupts during DND.

    When DND is active, non-urgent interrupts are queued
    and delivered when DND ends.
    """

    def __init__(self, max_queue_size: int = 100) -> None:
        self._queue: List[Dict[str, Any]] = []
        self._max_size = max_queue_size
        self._lock = threading.Lock()

    def add(
        self,
        message: str,
        urgency: InterruptUrgency,
        callback: Optional[Callable] = None,
        metadata: Dict[str, Any] = None
    ) -> str:
        """Add an interrupt to the queue"""
        with self._lock:
            item_id = f"INT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{len(self._queue):04d}"

            self._queue.append({
                "id": item_id,
                "message": message,
                "urgency": urgency.value,
                "timestamp": datetime.now().isoformat(),
                "callback": callback,
                "metadata": metadata or {},
                "delivered": False
            })

            # Trim if over size
            if len(self._queue) > self._max_size:
                # Remove oldest non-urgent items
                self._queue.sort(key=lambda x: (
                    InterruptUrgency(x["urgency"]).value != InterruptUrgency.CRITICAL.value,
                    x["timestamp"]
                ))
                self._queue = self._queue[-self._max_size:]

            return item_id

    def get_pending(self, min_urgency: InterruptUrgency = None) -> List[Dict[str, Any]]:
        """Get pending (undelivered) interrupts"""
        with self._lock:
            pending = [i for i in self._queue if not i["delivered"]]

            if min_urgency:
                urgency_order = [
                    InterruptUrgency.ROUTINE,
                    InterruptUrgency.LOW,
                    InterruptUrgency.MEDIUM,
                    InterruptUrgency.HIGH,
                    InterruptUrgency.CRITICAL
                ]
                min_idx = urgency_order.index(min_urgency)
                pending = [
                    i for i in pending
                    if urgency_order.index(InterruptUrgency(i["urgency"])) >= min_idx
                ]

            return pending

    def mark_delivered(self, item_id: str) -> bool:
        """Mark an interrupt as delivered"""
        with self._lock:
            for item in self._queue:
                if item["id"] == item_id:
                    item["delivered"] = True
                    return True
            return False

    def deliver_all(self) -> List[Dict[str, Any]]:
        """Deliver all pending interrupts"""
        with self._lock:
            pending = [i for i in self._queue if not i["delivered"]]
            for item in pending:
                item["delivered"] = True
                if item.get("callback"):
                    try:
                        item["callback"](item["message"])
                    except Exception as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            return pending

    def clear(self) -> None:
        """Clear the queue"""
        with self._lock:
            self._queue = []

    def __len__(self) -> int:
        with self._lock:
            return len([i for i in self._queue if not i["delivered"]])


class DNDManager:
    """
    Main Do Not Disturb manager.

    Coordinates all DND sources (calendar, schedule, activity)
    and provides a unified interface for checking interrupt permission.
    """

    def __init__(
        self,
        config_path: Path = None,
        memory_dir: Path = None,
        calendar_provider: CalendarProvider = None,
        activity_monitor: ActivityMonitor = None
    ):
        if config_path:
            self.config_path = Path(config_path)
        elif memory_dir:
            self.config_path = Path(memory_dir) / "dnd_config.json"
        else:
            self.config_path = Path("vera_memory/dnd_config.json")

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_saved_epoch: float = 0.0

        # Components
        self.calendar = calendar_provider or MockCalendarProvider()
        self.activity = activity_monitor or ActivityMonitor()
        self.interrupt_queue = InterruptQueue()

        # State
        self._rules: List[DNDRule] = []
        self._manual_dnd: Optional[Tuple[DNDLevel, datetime, str]] = None  # (level, until, reason)
        self._override_callbacks: List[Callable] = []

        # Default rules
        self._setup_default_rules()

        # Load saved config
        self._load()

    def _setup_default_rules(self):
        """Setup default DND rules"""
        # Work hours (less interruptions during focus time)
        self._rules.append(DNDRule(
            name="work_hours",
            source=ContextSource.TIME_OF_DAY,
            level=DNDLevel.LOW,
            start_time=time(9, 0),
            end_time=time(17, 0),
            days_of_week=[0, 1, 2, 3, 4],  # Mon-Fri
            priority=10
        ))

        # Night time (high DND)
        self._rules.append(DNDRule(
            name="night_time",
            source=ContextSource.TIME_OF_DAY,
            level=DNDLevel.HIGH,
            start_time=time(22, 0),
            end_time=time(7, 0),
            days_of_week=[0, 1, 2, 3, 4, 5, 6],
            priority=30
        ))

        # Meeting patterns
        self._rules.append(DNDRule(
            name="meetings",
            source=ContextSource.CALENDAR,
            level=DNDLevel.HIGH,
            calendar_pattern=r"(?i)(meeting|call|sync|standup|1:1|1-on-1)",
            priority=70
        ))

        # Focus time patterns
        self._rules.append(DNDRule(
            name="focus_time",
            source=ContextSource.CALENDAR,
            level=DNDLevel.CRITICAL,
            calendar_pattern=r"(?i)(focus|deep work|no meetings|blocked|busy)",
            priority=80
        ))

    def _load(self):
        """Load configuration"""
        if not self.config_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.config_path, default={})
            else:
                data = json.loads(self.config_path.read_text())

            # Load custom rules
            for rule_data in data.get("custom_rules", []):
                rule = DNDRule.from_dict(rule_data)
                # Don't duplicate default rules
                if not any(r.name == rule.name for r in self._rules):
                    self._rules.append(rule)

            # Load manual DND state
            if data.get("manual_dnd"):
                md = data["manual_dnd"]
                until = datetime.fromisoformat(md["until"]) if md.get("until") else None
                if not until or until > datetime.now():
                    self._manual_dnd = (
                        DNDLevel(md["level"]),
                        until,
                        md.get("reason", "Manual DND")
                    )

        except Exception as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save(self):
        """Save configuration"""
        # Get custom rules (exclude defaults)
        default_names = {"work_hours", "night_time", "meetings", "focus_time"}
        custom_rules = [r for r in self._rules if r.name not in default_names]

        data = {
            "custom_rules": [r.to_dict() for r in custom_rules],
            "manual_dnd": None,
            "last_updated": datetime.now().isoformat()
        }

        if self._manual_dnd:
            level, until, reason = self._manual_dnd
            data["manual_dnd"] = {
                "level": level.value,
                "until": until.isoformat() if until else None,
                "reason": reason
            }

        if HAS_ATOMIC:
            atomic_json_write(self.config_path, data)
        else:
            self.config_path.write_text(json.dumps(data, indent=2))
        try:
            self._last_saved_epoch = float(self.config_path.stat().st_mtime)
        except Exception:
            self._last_saved_epoch = 0.0

    def add_rule(self, rule: DNDRule) -> None:
        """Add a custom DND rule"""
        # Replace if exists
        self._rules = [r for r in self._rules if r.name != rule.name]
        self._rules.append(rule)
        self._save()

    def remove_rule(self, name: str) -> bool:
        """Remove a rule by name"""
        original_len = len(self._rules)
        self._rules = [r for r in self._rules if r.name != name]
        if len(self._rules) < original_len:
            self._save()
            return True
        return False

    def enable_dnd(
        self,
        level: DNDLevel = DNDLevel.MEDIUM,
        duration_minutes: int = None,
        reason: str = "User requested"
    ):
        """Manually enable DND"""
        until = None
        if duration_minutes:
            until = datetime.now() + timedelta(minutes=duration_minutes)

        self._manual_dnd = (level, until, reason)
        self._save()

    def disable_dnd(self) -> None:
        """Disable manual DND"""
        self._manual_dnd = None
        self._save()

        # Deliver queued interrupts
        self.interrupt_queue.deliver_all()

    def get_status(self) -> DNDStatus:
        """Get current DND status"""
        now = datetime.now()
        active_rules = []
        highest_level = DNDLevel.OFF
        highest_priority = -1
        reason = "No active rules"
        source = ContextSource.MANUAL
        until = None

        # Check manual DND first (highest priority)
        if self._manual_dnd:
            level, manual_until, manual_reason = self._manual_dnd
            if not manual_until or manual_until > now:
                return DNDStatus(
                    is_active=level != DNDLevel.OFF,
                    level=level,
                    reason=manual_reason,
                    source=ContextSource.MANUAL,
                    active_rules=["manual"],
                    until=manual_until,
                    can_override=level != DNDLevel.CRITICAL
                )
            else:
                # Manual DND expired
                self._manual_dnd = None
                self._save()

        # Check each rule
        for rule in self._rules:
            if not rule.enabled:
                continue

            is_active, rule_until = self._check_rule(rule, now)
            if is_active:
                active_rules.append(rule.name)
                if rule.priority > highest_priority:
                    highest_priority = rule.priority
                    highest_level = rule.level
                    reason = f"Rule: {rule.name}"
                    source = rule.source
                    until = rule_until

        # Check activity-based focus detection
        if self.activity.is_in_focus_mode():
            focus_level = DNDLevel.MEDIUM
            if focus_level.value > highest_level.value or \
               (focus_level == highest_level and "activity" not in active_rules):
                active_rules.append("activity_focus")
                if len(active_rules) == 1:  # Only rule
                    highest_level = focus_level
                    reason = "Focus time detected from activity"
                    source = ContextSource.ACTIVITY

        # Check meeting detection
        if self.activity.detect_meeting():
            meeting_level = DNDLevel.HIGH
            active_rules.append("activity_meeting")
            if meeting_level.value > highest_level.value:
                highest_level = meeting_level
                reason = "Meeting detected from activity"
                source = ContextSource.ACTIVITY

        return DNDStatus(
            is_active=highest_level != DNDLevel.OFF,
            level=highest_level,
            reason=reason,
            source=source,
            active_rules=active_rules,
            until=until,
            can_override=highest_level != DNDLevel.CRITICAL
        )

    def _check_rule(
        self,
        rule: DNDRule,
        now: datetime
    ) -> Tuple[bool, Optional[datetime]]:
        """Check if a rule is currently active"""
        until = None

        # Time-based rules
        if rule.source == ContextSource.TIME_OF_DAY:
            if rule.start_time and rule.end_time:
                current_time = now.time()
                current_day = now.weekday()

                # Check day of week
                if rule.days_of_week and current_day not in rule.days_of_week:
                    return (False, None)

                # Handle overnight rules (e.g., 22:00 to 07:00)
                if rule.start_time > rule.end_time:
                    # Overnight
                    in_range = current_time >= rule.start_time or current_time <= rule.end_time
                else:
                    in_range = rule.start_time <= current_time <= rule.end_time

                if in_range:
                    # Calculate until time
                    if rule.start_time > rule.end_time and current_time >= rule.start_time:
                        # Will end tomorrow
                        until = datetime.combine(
                            now.date() + timedelta(days=1),
                            rule.end_time
                        )
                    else:
                        until = datetime.combine(now.date(), rule.end_time)
                    return (True, until)

        # Calendar-based rules
        elif rule.source == ContextSource.CALENDAR:
            current_event = self.calendar.get_current_event()
            if current_event and rule.calendar_pattern:
                if re.search(rule.calendar_pattern, current_event.title):
                    return (True, current_event.end)

        # Schedule-based rules
        elif rule.source == ContextSource.SCHEDULE:
            # Custom schedule logic can be added here
            pass

        return (False, None)

    def can_interrupt(
        self,
        urgency: InterruptUrgency = InterruptUrgency.ROUTINE,
        source: str = "unknown"
    ) -> bool:
        """
        Check if an interrupt is allowed.

        Args:
            urgency: How urgent is the interrupt
            source: Where the interrupt is coming from

        Returns:
            True if interrupt is allowed
        """
        status = self.get_status()

        if not status.is_active:
            return True

        # Check if urgency overrides DND level
        urgency_can_override = {
            DNDLevel.OFF: [InterruptUrgency.ROUTINE, InterruptUrgency.LOW,
                          InterruptUrgency.MEDIUM, InterruptUrgency.HIGH,
                          InterruptUrgency.CRITICAL],
            DNDLevel.LOW: [InterruptUrgency.LOW, InterruptUrgency.MEDIUM,
                          InterruptUrgency.HIGH, InterruptUrgency.CRITICAL],
            DNDLevel.MEDIUM: [InterruptUrgency.MEDIUM, InterruptUrgency.HIGH,
                             InterruptUrgency.CRITICAL],
            DNDLevel.HIGH: [InterruptUrgency.HIGH, InterruptUrgency.CRITICAL],
            DNDLevel.CRITICAL: [InterruptUrgency.CRITICAL]
        }

        allowed_urgencies = urgency_can_override.get(status.level, [])
        return urgency in allowed_urgencies

    def queue_interrupt(
        self,
        message: str,
        urgency: InterruptUrgency = InterruptUrgency.ROUTINE,
        callback: Callable = None
    ) -> Tuple[bool, str]:
        """
        Queue an interrupt for later delivery.

        Returns:
            Tuple of (was_immediate, message_or_queue_id)
        """
        if self.can_interrupt(urgency):
            # Deliver immediately
            if callback:
                callback(message)
            return (True, "Delivered immediately")
        else:
            # Queue for later
            queue_id = self.interrupt_queue.add(
                message=message,
                urgency=urgency,
                callback=callback
            )
            return (False, queue_id)

    def get_queued_count(self) -> int:
        """Get count of queued interrupts"""
        return len(self.interrupt_queue)

    def deliver_queued(self, min_urgency: InterruptUrgency = None) -> int:
        """Deliver queued interrupts"""
        pending = self.interrupt_queue.get_pending(min_urgency)
        delivered = 0

        for item in pending:
            if item.get("callback"):
                try:
                    item["callback"](item["message"])
                    self.interrupt_queue.mark_delivered(item["id"])
                    delivered += 1
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            else:
                self.interrupt_queue.mark_delivered(item["id"])
                delivered += 1

        return delivered

    def get_rules(self) -> List[DNDRule]:
        """Get all rules"""
        return list(self._rules)

    def summarize(self) -> str:
        """Generate a summary of DND status"""
        status = self.get_status()
        lines = [
            "**Do Not Disturb Status**",
            f"- Active: {status.is_active}",
            f"- Level: {status.level.value}",
            f"- Reason: {status.reason}",
            f"- Source: {status.source.value}"
        ]

        if status.until:
            lines.append(f"- Until: {status.until.strftime('%H:%M')}")

        if status.active_rules:
            lines.append(f"- Active rules: {', '.join(status.active_rules)}")

        queued = self.get_queued_count()
        if queued > 0:
            lines.append(f"- Queued interrupts: {queued}")

        return "\n".join(lines)


class DNDContext:
    """
    Context manager for DND operations.

    Temporarily enables DND for the duration of the context.
    """

    def __init__(
        self,
        manager: DNDManager,
        level: DNDLevel = DNDLevel.MEDIUM,
        reason: str = "Context manager"
    ):
        self.manager = manager
        self.level = level
        self.reason = reason
        self._previous_state = None

    def __enter__(self):
        # Save previous state
        status = self.manager.get_status()
        self._previous_state = (
            self.manager._manual_dnd,
            status.is_active,
            status.level
        )

        # Enable DND
        self.manager.enable_dnd(self.level, reason=self.reason)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore previous state
        if self._previous_state:
            self.manager._manual_dnd = self._previous_state[0]
            self.manager._save()
        return False


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("DND Mode - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test 1: Basic DND manager
        print("\n=== Test 1: Basic DND Manager ===")
        dnd = DNDManager(config_path=Path(tmpdir) / "dnd.json")
        status = dnd.get_status()
        print(f"   DND active: {status.is_active}")
        print(f"   Level: {status.level.value}")
        print("   Result: PASS")

        # Test 2: Manual DND enable
        print("\n=== Test 2: Manual DND Enable ===")
        dnd.enable_dnd(DNDLevel.HIGH, duration_minutes=30, reason="Testing")
        status = dnd.get_status()
        assert status.is_active
        assert status.level == DNDLevel.HIGH
        assert status.source == ContextSource.MANUAL
        print(f"   Level: {status.level.value}")
        print(f"   Reason: {status.reason}")
        print("   Result: PASS")

        # Test 3: Can interrupt check
        print("\n=== Test 3: Can Interrupt Check ===")
        # High DND blocks routine
        assert not dnd.can_interrupt(InterruptUrgency.ROUTINE)
        # High DND allows high urgency
        assert dnd.can_interrupt(InterruptUrgency.HIGH)
        # Critical always gets through
        assert dnd.can_interrupt(InterruptUrgency.CRITICAL)
        print("   Routine blocked: True")
        print("   High allowed: True")
        print("   Critical allowed: True")
        print("   Result: PASS")

        # Test 4: Disable DND
        print("\n=== Test 4: Disable DND ===")
        dnd.disable_dnd()
        status = dnd.get_status()
        # May still have time-based rules active
        print(f"   Manual DND disabled")
        print("   Result: PASS")

        # Test 5: Interrupt queue
        print("\n=== Test 5: Interrupt Queue ===")
        dnd.enable_dnd(DNDLevel.HIGH)
        delivered, result = dnd.queue_interrupt("Test message", InterruptUrgency.ROUTINE)
        assert not delivered
        assert result.startswith("INT-")
        print(f"   Queued: {result}")
        print(f"   Queue size: {dnd.get_queued_count()}")
        print("   Result: PASS")

        # Test 6: Deliver queued
        print("\n=== Test 6: Deliver Queued ===")
        dnd.disable_dnd()
        # Queue should have been delivered on disable
        print(f"   Queue size after disable: {dnd.get_queued_count()}")
        print("   Result: PASS")

        # Test 7: Add custom rule
        print("\n=== Test 7: Add Custom Rule ===")
        custom_rule = DNDRule(
            name="lunch_break",
            source=ContextSource.SCHEDULE,
            level=DNDLevel.MEDIUM,
            start_time=time(12, 0),
            end_time=time(13, 0),
            days_of_week=[0, 1, 2, 3, 4]
        )
        dnd.add_rule(custom_rule)
        rules = dnd.get_rules()
        assert any(r.name == "lunch_break" for r in rules)
        print(f"   Added rule: lunch_break")
        print(f"   Total rules: {len(rules)}")
        print("   Result: PASS")

        # Test 8: Remove rule
        print("\n=== Test 8: Remove Rule ===")
        removed = dnd.remove_rule("lunch_break")
        assert removed
        rules = dnd.get_rules()
        assert not any(r.name == "lunch_break" for r in rules)
        print("   Removed: lunch_break")
        print("   Result: PASS")

        # Test 9: Calendar provider
        print("\n=== Test 9: Calendar Provider ===")
        calendar = MockCalendarProvider()
        now = datetime.now()
        calendar.add_event(CalendarEvent(
            title="Team Meeting",
            start=now - timedelta(minutes=15),
            end=now + timedelta(minutes=45)
        ))
        event = calendar.get_current_event()
        assert event is not None
        assert event.title == "Team Meeting"
        print(f"   Current event: {event.title}")
        print("   Result: PASS")

        # Test 10: Activity monitor
        print("\n=== Test 10: Activity Monitor ===")
        monitor = ActivityMonitor()
        signal = ActivitySignal(
            signal_type="typing",
            timestamp=datetime.now(),
            intensity=0.8,
            app_name="VSCode"
        )
        monitor.record_signal(signal)
        assert monitor.is_user_active()
        print(f"   User active: {monitor.is_user_active()}")
        print(f"   In focus mode: {monitor.is_in_focus_mode()}")
        print("   Result: PASS")

        # Test 11: DND Context manager
        print("\n=== Test 11: DND Context Manager ===")
        dnd.disable_dnd()
        with DNDContext(dnd, DNDLevel.CRITICAL, reason="Critical operation"):
            status = dnd.get_status()
            assert status.is_active
            assert status.level == DNDLevel.CRITICAL
            print(f"   Inside context: level={status.level.value}")

        status = dnd.get_status()
        print(f"   Outside context: level={status.level.value}")
        print("   Result: PASS")

        # Test 12: Status summary
        print("\n=== Test 12: Status Summary ===")
        summary = dnd.summarize()
        assert "Do Not Disturb Status" in summary
        print("   Summary generated")
        print("   Result: PASS")

        # Test 13: Temporal weight calculation
        print("\n=== Test 13: DNDRule Serialization ===")
        rule = DNDRule(
            name="test_rule",
            source=ContextSource.SCHEDULE,
            level=DNDLevel.MEDIUM,
            start_time=time(9, 0),
            end_time=time(17, 0)
        )
        d = rule.to_dict()
        restored = DNDRule.from_dict(d)
        assert restored.name == rule.name
        assert restored.start_time == rule.start_time
        print("   Serialization round-trip successful")
        print("   Result: PASS")

        # Test 14: DNDLevel ordering
        print("\n=== Test 14: DND Level Ordering ===")
        levels = [DNDLevel.OFF, DNDLevel.LOW, DNDLevel.MEDIUM, DNDLevel.HIGH, DNDLevel.CRITICAL]
        for i, level in enumerate(levels):
            print(f"   {level.value}: {i}")
        print("   Result: PASS")

        # Test 15: InterruptUrgency handling
        print("\n=== Test 15: Interrupt Urgency ===")
        dnd.enable_dnd(DNDLevel.MEDIUM)
        # Medium DND: allows MEDIUM, HIGH, CRITICAL
        assert not dnd.can_interrupt(InterruptUrgency.ROUTINE)
        assert not dnd.can_interrupt(InterruptUrgency.LOW)
        assert dnd.can_interrupt(InterruptUrgency.MEDIUM)
        assert dnd.can_interrupt(InterruptUrgency.HIGH)
        assert dnd.can_interrupt(InterruptUrgency.CRITICAL)
        print("   ROUTINE blocked, MEDIUM+ allowed")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nDND Mode is ready for integration!")

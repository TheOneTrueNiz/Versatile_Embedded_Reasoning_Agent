#!/usr/bin/env python3
"""
Rabbit Hole Detector (Anti-Spiral Protection)
==============================================

Detects when VERA is stuck in unproductive loops and intervenes.

Source: Ported from GROKSTAR's anti-spiral protection

Problem Solved:
- AI agents can get stuck repeating the same failing approaches
- Without detection, they waste time/tokens on dead ends
- "Rabbit holes" drain resources and frustrate users

Solution:
- Track action patterns and detect repetition
- Monitor time/token spend on task families
- Detect diminishing returns (effort vs. progress)
- Force strategy changes when spiraling detected

Usage:
    from anti_spiral import RabbitHoleDetector, SpiralStatus

    detector = RabbitHoleDetector()

    # Before each action
    status = detector.check_action(
        action_type="web_search",
        target="python async tutorial",
        context={"task_id": "TASK-001"}
    )

    if status.is_spiraling:
        print(f"WARNING: {status.message}")
        print(f"Suggestion: {status.suggestion}")
        # Force strategy change

    # After action completes
    detector.record_outcome(
        action_id=status.action_id,
        success=False,
        result="No new information found"
    )
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import logging
logger = logging.getLogger(__name__)

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class SpiralType(Enum):
    """Types of spiraling behavior"""
    NONE = "none"                          # No spiral detected
    REPETITION = "repetition"              # Same action repeated
    SIMILAR_FAILURE = "similar_failure"    # Similar actions all failing
    DIMINISHING_RETURNS = "diminishing"    # Effort increasing, progress decreasing
    TIME_SINK = "time_sink"                # Too much time on one task
    TOKEN_DRAIN = "token_drain"            # Too many tokens on one approach


class SpiralSeverity(Enum):
    """How serious the spiral is"""
    NONE = "none"
    WARNING = "warning"      # Alert but don't block
    SERIOUS = "serious"      # Strongly suggest change
    CRITICAL = "critical"    # Force strategy change


@dataclass
class SpiralStatus:
    """Result of spiral detection check"""
    is_spiraling: bool
    spiral_type: SpiralType
    severity: SpiralSeverity
    message: str
    suggestion: str
    action_id: str
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_spiraling": self.is_spiraling,
            "spiral_type": self.spiral_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "suggestion": self.suggestion,
            "action_id": self.action_id,
            "metrics": self.metrics
        }


@dataclass
class ActionRecord:
    """Record of an action for pattern detection"""
    id: str
    timestamp: str
    action_type: str
    target: str
    fingerprint: str
    context: Dict[str, Any]
    outcome: Optional[str] = None
    success: Optional[bool] = None
    duration_ms: Optional[int] = None
    tokens_used: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionRecord':
        return cls(**data)


@dataclass
class TaskMetrics:
    """Metrics for a task family"""
    task_id: str
    first_action: str  # ISO timestamp
    last_action: str
    total_actions: int
    successful_actions: int
    failed_actions: int
    total_tokens: int
    total_duration_ms: int
    unique_approaches: int
    repeated_approaches: int

    @property
    def success_rate(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.successful_actions / self.total_actions

    @property
    def avg_tokens_per_action(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.total_tokens / self.total_actions

    @property
    def repetition_ratio(self) -> float:
        if self.total_actions == 0:
            return 0.0
        return self.repeated_approaches / self.total_actions


# Default thresholds
DEFAULT_THRESHOLDS = {
    # Repetition detection
    "max_identical_actions": 3,           # Same exact action
    "max_similar_actions": 5,             # Similar actions (same type + target pattern)
    "similarity_window_minutes": 30,       # Time window for similarity check

    # Failure patterns
    "max_consecutive_failures": 4,
    "min_success_rate": 0.2,              # Below this = spiraling
    "failure_window_actions": 10,          # Check last N actions

    # Resource limits per task
    "max_actions_per_task": 20,
    "max_tokens_per_task": 50000,
    "max_time_per_task_minutes": 60,

    # Diminishing returns
    "progress_check_interval": 5,          # Check every N actions
    "min_progress_per_interval": 0.1,      # Minimum progress (0-1)
}


class RabbitHoleDetector:
    """
    Detects and prevents unproductive spiraling behavior.

    Monitors:
    - Action repetition patterns
    - Failure rates and patterns
    - Time and token consumption
    - Progress vs effort ratio
    """

    def __init__(
        self,
        storage_path: Path = None,
        memory_dir: Path = None,
        thresholds: Dict[str, Any] = None
    ):
        """
        Initialize rabbit hole detector.

        Args:
            storage_path: Path to store action history
            memory_dir: Base memory directory
            thresholds: Custom thresholds (merged with defaults)
        """
        if storage_path:
            self.storage_path = Path(storage_path)
        elif memory_dir:
            self.storage_path = Path(memory_dir) / "spiral_detection.json"
        else:
            self.storage_path = Path("vera_memory/spiral_detection.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Merge thresholds
        self.thresholds = {**DEFAULT_THRESHOLDS}
        if thresholds:
            self.thresholds.update(thresholds)

        # Action history (in-memory for speed, persisted periodically)
        self._actions: List[ActionRecord] = []
        self._task_metrics: Dict[str, TaskMetrics] = {}
        self._action_count = 0

        # Load existing state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state"""
        if not self.storage_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path, default={})
            else:
                data = json.loads(self.storage_path.read_text())

            self._actions = [
                ActionRecord.from_dict(a) for a in data.get("actions", [])
            ]
            self._action_count = data.get("action_count", len(self._actions))

            # Rebuild task metrics
            for action in self._actions:
                task_id = action.context.get("task_id", "unknown")
                self._update_task_metrics(task_id, action)

        except Exception:
            self._actions = []
            self._task_metrics = {}

    def _save_state(self) -> None:
        """Persist state to disk"""
        # Keep only recent actions (last 1000)
        recent_actions = self._actions[-1000:]

        data = {
            "actions": [a.to_dict() for a in recent_actions],
            "action_count": self._action_count,
            "last_updated": datetime.now().isoformat()
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2))

    def _generate_id(self) -> str:
        """Generate unique action ID"""
        self._action_count += 1
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"ACT-{timestamp}-{self._action_count:05d}"

    def _generate_fingerprint(self, action_type: str, target: str) -> str:
        """Generate fingerprint for action similarity detection"""
        # Normalize target for similarity matching
        normalized = target.lower().strip()
        # Remove numbers and specific IDs for pattern matching
        import re
        normalized = re.sub(r'\d+', 'N', normalized)
        normalized = re.sub(r'[a-f0-9]{8,}', 'ID', normalized)

        content = f"{action_type}:{normalized}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def check_action(
        self,
        action_type: str,
        target: str,
        context: Dict[str, Any] = None
    ) -> SpiralStatus:
        """
        Check if an action would indicate spiraling.

        Args:
            action_type: Type of action (e.g., "web_search", "file_read")
            target: Target of the action (e.g., search query, file path)
            context: Additional context (task_id, etc.)

        Returns:
            SpiralStatus with detection results
        """
        context = context or {}
        task_id = context.get("task_id", "unknown")
        fingerprint = self._generate_fingerprint(action_type, target)

        # Create action record
        action = ActionRecord(
            id=self._generate_id(),
            timestamp=datetime.now().isoformat(),
            action_type=action_type,
            target=target,
            fingerprint=fingerprint,
            context=context
        )

        # Check for various spiral patterns
        checks = [
            self._check_repetition(action, fingerprint),
            self._check_failure_pattern(task_id),
            self._check_resource_limits(task_id),
            self._check_diminishing_returns(task_id)
        ]

        # Find the most severe issue
        worst = max(checks, key=lambda s: list(SpiralSeverity).index(s.severity))

        # Store action for tracking
        self._actions.append(action)
        self._update_task_metrics(task_id, action)

        # Persist periodically
        if len(self._actions) % 10 == 0:
            self._save_state()

        # Return status with action ID
        worst.action_id = action.id
        return worst

    def _check_repetition(self, action: ActionRecord, fingerprint: str) -> SpiralStatus:
        """Check for repeated identical or similar actions"""
        window_start = datetime.now() - timedelta(
            minutes=self.thresholds["similarity_window_minutes"]
        )

        # Count identical actions (exact match)
        identical_count = sum(
            1 for a in self._actions
            if a.action_type == action.action_type
            and a.target == action.target
            and datetime.fromisoformat(a.timestamp) > window_start
        )

        if identical_count >= self.thresholds["max_identical_actions"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.REPETITION,
                severity=SpiralSeverity.SERIOUS,
                message=f"Repeated identical action {identical_count} times: {action.action_type} on '{action.target[:50]}'",
                suggestion="Try a different approach. Consider: different search terms, different data source, or breaking down the problem differently.",
                action_id="",
                metrics={"identical_count": identical_count}
            )

        # Count similar actions (same fingerprint)
        similar_count = sum(
            1 for a in self._actions
            if a.fingerprint == fingerprint
            and datetime.fromisoformat(a.timestamp) > window_start
        )

        if similar_count >= self.thresholds["max_similar_actions"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.REPETITION,
                severity=SpiralSeverity.WARNING,
                message=f"Similar actions attempted {similar_count} times without success",
                suggestion="The current approach may not be working. Consider stepping back and trying a fundamentally different strategy.",
                action_id="",
                metrics={"similar_count": similar_count}
            )

        return SpiralStatus(
            is_spiraling=False,
            spiral_type=SpiralType.NONE,
            severity=SpiralSeverity.NONE,
            message="No repetition detected",
            suggestion="",
            action_id=""
        )

    def _check_failure_pattern(self, task_id: str) -> SpiralStatus:
        """Check for consecutive failures or low success rate"""
        task_actions = [
            a for a in self._actions
            if a.context.get("task_id") == task_id and a.outcome is not None
        ]

        if len(task_actions) < 3:
            return SpiralStatus(
                is_spiraling=False,
                spiral_type=SpiralType.NONE,
                severity=SpiralSeverity.NONE,
                message="Insufficient data",
                suggestion="",
                action_id=""
            )

        # Check consecutive failures
        recent = task_actions[-self.thresholds["failure_window_actions"]:]
        consecutive_failures = 0
        for action in reversed(recent):
            if action.success is False:
                consecutive_failures += 1
            else:
                break

        if consecutive_failures >= self.thresholds["max_consecutive_failures"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.SIMILAR_FAILURE,
                severity=SpiralSeverity.SERIOUS,
                message=f"{consecutive_failures} consecutive failures on task {task_id}",
                suggestion="Multiple attempts have failed. Stop and analyze: What's the root cause? Is this task achievable with current tools? Consider asking for help or marking as blocked.",
                action_id="",
                metrics={"consecutive_failures": consecutive_failures}
            )

        # Check overall success rate
        success_count = sum(1 for a in recent if a.success is True)
        success_rate = success_count / len(recent)

        if success_rate < self.thresholds["min_success_rate"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.SIMILAR_FAILURE,
                severity=SpiralSeverity.WARNING,
                message=f"Low success rate ({success_rate:.0%}) for task {task_id}",
                suggestion="Most attempts are failing. Review the approach and consider whether the goal is clearly defined.",
                action_id="",
                metrics={"success_rate": success_rate}
            )

        return SpiralStatus(
            is_spiraling=False,
            spiral_type=SpiralType.NONE,
            severity=SpiralSeverity.NONE,
            message="Failure pattern OK",
            suggestion="",
            action_id=""
        )

    def _check_resource_limits(self, task_id: str) -> SpiralStatus:
        """Check if task is consuming too many resources"""
        metrics = self._task_metrics.get(task_id)

        if not metrics:
            return SpiralStatus(
                is_spiraling=False,
                spiral_type=SpiralType.NONE,
                severity=SpiralSeverity.NONE,
                message="No metrics yet",
                suggestion="",
                action_id=""
            )

        # Check action count
        if metrics.total_actions >= self.thresholds["max_actions_per_task"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.TIME_SINK,
                severity=SpiralSeverity.CRITICAL,
                message=f"Task {task_id} has consumed {metrics.total_actions} actions (limit: {self.thresholds['max_actions_per_task']})",
                suggestion="STOP. This task has consumed too many actions. Either complete it now, break it into subtasks, or defer it.",
                action_id="",
                metrics={"total_actions": metrics.total_actions}
            )

        # Check token usage
        if metrics.total_tokens >= self.thresholds["max_tokens_per_task"]:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.TOKEN_DRAIN,
                severity=SpiralSeverity.CRITICAL,
                message=f"Task {task_id} has used {metrics.total_tokens} tokens (limit: {self.thresholds['max_tokens_per_task']})",
                suggestion="STOP. Token budget exceeded for this task. Simplify the approach or get user input.",
                action_id="",
                metrics={"total_tokens": metrics.total_tokens}
            )

        # Check time
        try:
            first = datetime.fromisoformat(metrics.first_action)
            elapsed = datetime.now() - first
            max_time = timedelta(minutes=self.thresholds["max_time_per_task_minutes"])

            if elapsed > max_time:
                return SpiralStatus(
                    is_spiraling=True,
                    spiral_type=SpiralType.TIME_SINK,
                    severity=SpiralSeverity.SERIOUS,
                    message=f"Task {task_id} has been active for {elapsed.total_seconds() / 60:.0f} minutes",
                    suggestion="This task is taking too long. Consider whether it's blocked or needs to be approached differently.",
                    action_id="",
                    metrics={"elapsed_minutes": elapsed.total_seconds() / 60}
                )
        except (ValueError, TypeError) as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        return SpiralStatus(
            is_spiraling=False,
            spiral_type=SpiralType.NONE,
            severity=SpiralSeverity.NONE,
            message="Resource usage OK",
            suggestion="",
            action_id=""
        )

    def _check_diminishing_returns(self, task_id: str) -> SpiralStatus:
        """Check if effort is increasing but progress is not"""
        metrics = self._task_metrics.get(task_id)

        if not metrics or metrics.total_actions < self.thresholds["progress_check_interval"]:
            return SpiralStatus(
                is_spiraling=False,
                spiral_type=SpiralType.NONE,
                severity=SpiralSeverity.NONE,
                message="Insufficient data for progress check",
                suggestion="",
                action_id=""
            )

        # Check if repetition ratio is high (same approaches being tried)
        if metrics.repetition_ratio > 0.5:
            return SpiralStatus(
                is_spiraling=True,
                spiral_type=SpiralType.DIMINISHING_RETURNS,
                severity=SpiralSeverity.WARNING,
                message=f"High repetition ratio ({metrics.repetition_ratio:.0%}) - same approaches being retried",
                suggestion="You're repeating approaches without progress. Try something completely different.",
                action_id="",
                metrics={"repetition_ratio": metrics.repetition_ratio}
            )

        return SpiralStatus(
            is_spiraling=False,
            spiral_type=SpiralType.NONE,
            severity=SpiralSeverity.NONE,
            message="Progress OK",
            suggestion="",
            action_id=""
        )

    def _update_task_metrics(self, task_id: str, action: ActionRecord) -> None:
        """Update metrics for a task"""
        if task_id not in self._task_metrics:
            self._task_metrics[task_id] = TaskMetrics(
                task_id=task_id,
                first_action=action.timestamp,
                last_action=action.timestamp,
                total_actions=0,
                successful_actions=0,
                failed_actions=0,
                total_tokens=0,
                total_duration_ms=0,
                unique_approaches=0,
                repeated_approaches=0
            )

        metrics = self._task_metrics[task_id]
        metrics.last_action = action.timestamp
        metrics.total_actions += 1

        if action.tokens_used:
            metrics.total_tokens += action.tokens_used
        if action.duration_ms:
            metrics.total_duration_ms += action.duration_ms

        # Track approach uniqueness
        existing_fingerprints = set(
            a.fingerprint for a in self._actions
            if a.context.get("task_id") == task_id and a.id != action.id
        )
        if action.fingerprint in existing_fingerprints:
            metrics.repeated_approaches += 1
        else:
            metrics.unique_approaches += 1

    def record_outcome(
        self,
        action_id: str,
        success: bool,
        result: str = None,
        tokens_used: int = None,
        duration_ms: int = None
    ) -> None:
        """
        Record the outcome of an action.

        Args:
            action_id: ID from check_action()
            success: Whether the action succeeded
            result: Description of result
            tokens_used: Tokens consumed
            duration_ms: Time taken
        """
        for action in self._actions:
            if action.id == action_id:
                action.success = success
                action.outcome = result
                action.tokens_used = tokens_used
                action.duration_ms = duration_ms

                # Update task metrics
                task_id = action.context.get("task_id", "unknown")
                if task_id in self._task_metrics:
                    if success:
                        self._task_metrics[task_id].successful_actions += 1
                    else:
                        self._task_metrics[task_id].failed_actions += 1
                    if tokens_used:
                        self._task_metrics[task_id].total_tokens += tokens_used
                    if duration_ms:
                        self._task_metrics[task_id].total_duration_ms += duration_ms

                self._save_state()
                return

    def reset_task(self, task_id: str) -> None:
        """Reset tracking for a task (e.g., when strategy changes)"""
        if task_id in self._task_metrics:
            del self._task_metrics[task_id]

        # Remove task actions from history
        self._actions = [
            a for a in self._actions
            if a.context.get("task_id") != task_id
        ]
        self._save_state()

    def get_task_summary(self, task_id: str) -> Dict[str, Any]:
        """Get summary of a task's spiral metrics"""
        metrics = self._task_metrics.get(task_id)

        if not metrics:
            return {"task_id": task_id, "status": "no_data"}

        task_actions = [
            a for a in self._actions
            if a.context.get("task_id") == task_id
        ]

        return {
            "task_id": task_id,
            "total_actions": metrics.total_actions,
            "success_rate": f"{metrics.success_rate:.0%}",
            "repetition_ratio": f"{metrics.repetition_ratio:.0%}",
            "total_tokens": metrics.total_tokens,
            "unique_approaches": metrics.unique_approaches,
            "recent_outcomes": [
                {"action": a.action_type, "success": a.success}
                for a in task_actions[-5:]
            ]
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get overall spiral detection statistics"""
        total_actions = len(self._actions)
        tasks_tracked = len(self._task_metrics)

        spiraling_tasks = [
            task_id for task_id, metrics in self._task_metrics.items()
            if metrics.success_rate < self.thresholds["min_success_rate"]
            or metrics.repetition_ratio > 0.5
        ]

        return {
            "total_actions_tracked": total_actions,
            "tasks_tracked": tasks_tracked,
            "spiraling_tasks": len(spiraling_tasks),
            "spiraling_task_ids": spiraling_tasks[:5],  # Top 5
            "thresholds": self.thresholds
        }

    def format_warning(self, status: SpiralStatus) -> str:
        """Format a spiral status as a user-friendly warning"""
        if not status.is_spiraling:
            return ""

        severity_icons = {
            SpiralSeverity.WARNING: "WARNING",
            SpiralSeverity.SERIOUS: "SERIOUS",
            SpiralSeverity.CRITICAL: "CRITICAL"
        }

        icon = severity_icons.get(status.severity, "")

        return f"""
[RABBIT HOLE DETECTED - {icon}]
Type: {status.spiral_type.value}
{status.message}

Suggestion: {status.suggestion}

Action ID: {status.action_id}
""".strip()


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Rabbit Hole Detector - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        storage_path = Path(tmpdir) / "spiral_detection.json"
        detector = RabbitHoleDetector(storage_path=storage_path)

        # Test 1: Normal actions (no spiral)
        print("\n=== Test 1: Normal Actions ===")
        status = detector.check_action(
            action_type="web_search",
            target="python async tutorial",
            context={"task_id": "TASK-001"}
        )
        assert not status.is_spiraling
        print(f"   Status: {status.spiral_type.value}")
        print("   Result: PASS")

        # Test 2: Repeated identical actions
        print("\n=== Test 2: Repeated Identical Actions ===")
        for i in range(4):
            status = detector.check_action(
                action_type="web_search",
                target="same exact query",
                context={"task_id": "TASK-002"}
            )

        assert status.is_spiraling
        assert status.spiral_type == SpiralType.REPETITION
        print(f"   Spiral detected: {status.is_spiraling}")
        print(f"   Type: {status.spiral_type.value}")
        print(f"   Severity: {status.severity.value}")
        print("   Result: PASS")

        # Test 3: Consecutive failures
        print("\n=== Test 3: Consecutive Failures ===")
        detector2 = RabbitHoleDetector(
            storage_path=Path(tmpdir) / "spiral2.json"
        )

        for i in range(5):
            status = detector2.check_action(
                action_type="api_call",
                target=f"endpoint_{i}",
                context={"task_id": "TASK-003"}
            )
            detector2.record_outcome(status.action_id, success=False, result="Failed")

        status = detector2.check_action(
            action_type="api_call",
            target="endpoint_new",
            context={"task_id": "TASK-003"}
        )
        assert status.is_spiraling
        assert status.spiral_type == SpiralType.SIMILAR_FAILURE
        print(f"   Spiral detected after failures: {status.is_spiraling}")
        print(f"   Type: {status.spiral_type.value}")
        print("   Result: PASS")

        # Test 4: Resource limits
        print("\n=== Test 4: Resource Limits ===")
        detector3 = RabbitHoleDetector(
            storage_path=Path(tmpdir) / "spiral3.json",
            thresholds={"max_actions_per_task": 5}
        )

        for i in range(6):
            status = detector3.check_action(
                action_type="file_read",
                target=f"file_{i}.txt",
                context={"task_id": "TASK-004"}
            )

        assert status.is_spiraling
        assert status.spiral_type == SpiralType.TIME_SINK
        print(f"   Spiral detected at limit: {status.is_spiraling}")
        print(f"   Type: {status.spiral_type.value}")
        print(f"   Severity: {status.severity.value}")
        print("   Result: PASS")

        # Test 5: Task summary
        print("\n=== Test 5: Task Summary ===")
        summary = detector.get_task_summary("TASK-001")
        print(f"   Task: {summary['task_id']}")
        print(f"   Actions: {summary['total_actions']}")
        print("   Result: PASS")

        # Test 6: Statistics
        print("\n=== Test 6: Statistics ===")
        stats = detector.get_stats()
        print(f"   Total actions: {stats['total_actions_tracked']}")
        print(f"   Tasks tracked: {stats['tasks_tracked']}")
        print(f"   Spiraling tasks: {stats['spiraling_tasks']}")
        print("   Result: PASS")

        # Test 7: Warning format
        print("\n=== Test 7: Warning Format ===")
        warning = detector.format_warning(status)
        assert "RABBIT HOLE DETECTED" in warning
        print("   Warning formatted correctly")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nRabbit Hole Detector is ready for integration!")

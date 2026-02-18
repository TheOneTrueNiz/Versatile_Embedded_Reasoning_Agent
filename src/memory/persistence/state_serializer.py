#!/usr/bin/env python3
"""
Full Execution State Serialization for Crash Recovery (#7)

This module implements goal-state serialization to enable seamless
resumption after crashes or interruptions.

Features:
1. ExecutionState - Complete execution state representation
2. GoalStack - Hierarchical goal/subgoal management
3. Checkpoint - Automatic checkpointing at key points
4. StateSerializer - State persistence with atomic writes
5. RecoveryManager - Crash detection and recovery
6. ResumeSession - Context manager for resumable sessions

Research basis:
- Goal-Oriented Dialog Systems
- Process Checkpointing in Distributed Systems
- Transaction Logging for Recovery
"""

import os
import json
import hashlib
import shutil
import fcntl
from enum import Enum
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import threading
import atexit
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class GoalStatus(Enum):
    """Status of a goal"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ExecutionPhase(Enum):
    """Current execution phase"""
    INITIALIZING = "initializing"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING = "waiting"
    REVIEWING = "reviewing"
    FINALIZING = "finalizing"


class CheckpointType(Enum):
    """Types of checkpoints"""
    AUTO = "auto"           # Automatic periodic checkpoint
    MANUAL = "manual"       # Manually triggered
    PRE_ACTION = "pre_action"   # Before important action
    POST_ACTION = "post_action"  # After important action
    GOAL_COMPLETE = "goal_complete"  # Goal completed
    ERROR = "error"         # After error


class RecoveryStrategy(Enum):
    """Strategies for recovery after crash"""
    RESUME_EXACT = "resume_exact"      # Resume from exact checkpoint
    RESUME_GOAL = "resume_goal"        # Resume from last goal
    RESTART_GOAL = "restart_goal"      # Restart current goal
    ROLLBACK = "rollback"              # Rollback to previous checkpoint


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Goal:
    """Represents a goal or subgoal"""
    goal_id: str
    description: str
    status: GoalStatus = GoalStatus.PENDING
    parent_id: Optional[str] = None
    subgoal_ids: List[str] = field(default_factory=list)
    progress: float = 0.0  # 0-1
    priority: int = 1  # 1-5, higher is more important
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "description": self.description,
            "status": self.status.value,
            "parent_id": self.parent_id,
            "subgoal_ids": self.subgoal_ids,
            "progress": round(self.progress, 3),
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metadata": self.metadata,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        return cls(
            goal_id=data.get("goal_id", ""),
            description=data.get("description", ""),
            status=GoalStatus(data.get("status", "pending")),
            parent_id=data.get("parent_id"),
            subgoal_ids=data.get("subgoal_ids", []),
            progress=data.get("progress", 0.0),
            priority=data.get("priority", 1),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(),
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            metadata=data.get("metadata", {}),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
        )

    def is_complete(self) -> bool:
        return self.status in [GoalStatus.COMPLETED, GoalStatus.CANCELLED]

    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries


@dataclass
class ActionRecord:
    """Record of an action taken"""
    action_id: str
    action_type: str
    description: str
    goal_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    result: Optional[str] = None
    error: Optional[str] = None
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "description": self.description,
            "goal_id": self.goal_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "result": self.result[:200] if self.result and len(self.result) > 200 else self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionRecord":
        return cls(
            action_id=data.get("action_id", ""),
            action_type=data.get("action_type", ""),
            description=data.get("description", ""),
            goal_id=data.get("goal_id", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            success=data.get("success", True),
            result=data.get("result"),
            error=data.get("error"),
            duration_ms=data.get("duration_ms", 0.0),
        )


@dataclass
class Checkpoint:
    """A checkpoint of execution state"""
    checkpoint_id: str
    checkpoint_type: CheckpointType
    timestamp: datetime = field(default_factory=datetime.now)
    state_hash: str = ""
    goal_stack_snapshot: List[str] = field(default_factory=list)
    current_goal_id: Optional[str] = None
    phase: ExecutionPhase = ExecutionPhase.INITIALIZING
    context_summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "checkpoint_type": self.checkpoint_type.value,
            "timestamp": self.timestamp.isoformat(),
            "state_hash": self.state_hash,
            "goal_stack_snapshot": self.goal_stack_snapshot,
            "current_goal_id": self.current_goal_id,
            "phase": self.phase.value,
            "context_summary": self.context_summary,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        return cls(
            checkpoint_id=data.get("checkpoint_id", ""),
            checkpoint_type=CheckpointType(data.get("checkpoint_type", "auto")),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            state_hash=data.get("state_hash", ""),
            goal_stack_snapshot=data.get("goal_stack_snapshot", []),
            current_goal_id=data.get("current_goal_id"),
            phase=ExecutionPhase(data.get("phase", "initializing")),
            context_summary=data.get("context_summary", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ExecutionState:
    """Complete execution state"""
    session_id: str
    phase: ExecutionPhase = ExecutionPhase.INITIALIZING
    goals: Dict[str, Goal] = field(default_factory=dict)
    goal_stack: List[str] = field(default_factory=list)  # Stack of active goal IDs
    action_history: List[ActionRecord] = field(default_factory=list)
    checkpoints: List[Checkpoint] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)
    is_crashed: bool = False
    crash_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase": self.phase.value,
            "goals": {gid: g.to_dict() for gid, g in self.goals.items()},
            "goal_stack": self.goal_stack,
            "action_history": [a.to_dict() for a in self.action_history[-50:]],  # Last 50 actions
            "checkpoints": [c.to_dict() for c in self.checkpoints[-20:]],  # Last 20 checkpoints
            "context": self.context,
            "started_at": self.started_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "is_crashed": self.is_crashed,
            "crash_reason": self.crash_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionState":
        state = cls(
            session_id=data.get("session_id", ""),
            phase=ExecutionPhase(data.get("phase", "initializing")),
            context=data.get("context", {}),
            goal_stack=data.get("goal_stack", []),
            started_at=datetime.fromisoformat(data["started_at"]) if "started_at" in data else datetime.now(),
            last_activity=datetime.fromisoformat(data["last_activity"]) if "last_activity" in data else datetime.now(),
            is_crashed=data.get("is_crashed", False),
            crash_reason=data.get("crash_reason"),
        )

        # Reconstruct goals
        for gid, gdata in data.get("goals", {}).items():
            state.goals[gid] = Goal.from_dict(gdata)

        # Reconstruct actions
        for adata in data.get("action_history", []):
            state.action_history.append(ActionRecord.from_dict(adata))

        # Reconstruct checkpoints
        for cdata in data.get("checkpoints", []):
            state.checkpoints.append(Checkpoint.from_dict(cdata))

        return state

    def get_current_goal(self) -> Optional[Goal]:
        """Get the current active goal"""
        if self.goal_stack:
            return self.goals.get(self.goal_stack[-1])
        return None

    def compute_hash(self) -> str:
        """Compute hash of current state"""
        state_str = json.dumps({
            "goals": [g.goal_id for g in self.goals.values()],
            "stack": self.goal_stack,
            "phase": self.phase.value,
        }, sort_keys=True)
        return hashlib.sha256(state_str.encode()).hexdigest()[:16]


# =============================================================================
# Goal Stack Manager
# =============================================================================

class GoalStack:
    """
    Manages hierarchical goal execution with stack-based tracking.
    """

    def __init__(self) -> None:
        self.goals: Dict[str, Goal] = {}
        self.stack: List[str] = []
        self._next_goal_num: int = 0
        self._lock = threading.Lock()

    def push_goal(
        self,
        description: str,
        parent_id: Optional[str] = None,
        priority: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Goal:
        """Push a new goal onto the stack"""
        with self._lock:
            goal_id = f"G{self._next_goal_num:04d}"
            self._next_goal_num += 1

            goal = Goal(
                goal_id=goal_id,
                description=description,
                parent_id=parent_id,
                priority=priority,
                metadata=metadata or {},
            )

            self.goals[goal_id] = goal
            self.stack.append(goal_id)

            # Update parent's subgoal list
            if parent_id and parent_id in self.goals:
                self.goals[parent_id].subgoal_ids.append(goal_id)

            return goal

    def pop_goal(self) -> Optional[Goal]:
        """Pop the current goal from stack"""
        with self._lock:
            if self.stack:
                goal_id = self.stack.pop()
                return self.goals.get(goal_id)
            return None

    def peek(self) -> Optional[Goal]:
        """Get current goal without popping"""
        with self._lock:
            if self.stack:
                return self.goals.get(self.stack[-1])
            return None

    def start_goal(self, goal_id: str) -> bool:
        """Mark goal as started"""
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal and goal.status == GoalStatus.PENDING:
                goal.status = GoalStatus.IN_PROGRESS
                goal.started_at = datetime.now()
                return True
            return False

    def complete_goal(self, goal_id: str, success: bool = True) -> bool:
        """Mark goal as completed"""
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal:
                goal.status = GoalStatus.COMPLETED if success else GoalStatus.FAILED
                goal.completed_at = datetime.now()
                goal.progress = 1.0 if success else goal.progress

                # Pop from stack if it's current
                if self.stack and self.stack[-1] == goal_id:
                    self.stack.pop()

                return True
            return False

    def update_progress(self, goal_id: str, progress: float) -> bool:
        """Update goal progress"""
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal:
                goal.progress = max(0.0, min(1.0, progress))
                return True
            return False

    def fail_goal(self, goal_id: str, error: str) -> bool:
        """Mark goal as failed"""
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal:
                goal.status = GoalStatus.FAILED
                goal.error_message = error
                goal.retry_count += 1

                if self.stack and self.stack[-1] == goal_id:
                    self.stack.pop()

                return True
            return False

    def retry_goal(self, goal_id: str) -> bool:
        """Retry a failed goal"""
        with self._lock:
            goal = self.goals.get(goal_id)
            if goal and goal.can_retry():
                goal.status = GoalStatus.PENDING
                goal.error_message = None
                goal.progress = 0.0
                if goal_id not in self.stack:
                    self.stack.append(goal_id)
                return True
            return False

    def get_incomplete_goals(self) -> List[Goal]:
        """Get all incomplete goals"""
        with self._lock:
            return [
                g for g in self.goals.values()
                if g.status not in [GoalStatus.COMPLETED, GoalStatus.CANCELLED]
            ]

    def to_state(self) -> Tuple[Dict[str, Goal], List[str]]:
        """Export state for serialization"""
        with self._lock:
            return self.goals.copy(), self.stack.copy()

    def from_state(self, goals: Dict[str, Goal], stack: List[str]) -> None:
        """Import state from serialization"""
        with self._lock:
            self.goals = goals
            self.stack = stack
            if goals:
                self._next_goal_num = max(
                    int(gid[1:]) for gid in goals.keys()
                ) + 1


# =============================================================================
# State Serializer
# =============================================================================

class StateSerializer:
    """
    Handles serialization and persistence of execution state.
    Uses atomic writes to prevent corruption.
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        max_checkpoints: int = 20,
        auto_checkpoint_interval: float = 60.0,  # seconds
    ):
        self.state_dir = state_dir or Path(".vera_state")
        self.max_checkpoints = max_checkpoints
        self.auto_checkpoint_interval = auto_checkpoint_interval
        self._lock = threading.Lock()

        # Ensure directory exists
        self.state_dir.mkdir(parents=True, exist_ok=True)

    @property
    def state_file(self) -> Path:
        return self.state_dir / "execution_state.json"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / ".state.lock"

    @property
    def crash_marker(self) -> Path:
        return self.state_dir / ".crashed"

    def save_state(self, state: ExecutionState) -> bool:
        """Save execution state atomically"""
        with self._lock:
            try:
                state.last_activity = datetime.now()
                data = state.to_dict()

                # Write to temp file first
                temp_file = self.state_file.with_suffix(".tmp")
                with open(temp_file, 'w') as f:
                    json.dump(data, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename
                temp_file.rename(self.state_file)

                return True
            except Exception as e:
                return False

    def load_state(self) -> Optional[ExecutionState]:
        """Load execution state from disk"""
        with self._lock:
            if not self.state_file.exists():
                return None

            try:
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                return ExecutionState.from_dict(data)
            except Exception:
                return None

    def create_checkpoint(
        self,
        state: ExecutionState,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        context_summary: str = "",
    ) -> Checkpoint:
        """Create a checkpoint of current state"""
        checkpoint_id = f"CP{len(state.checkpoints):04d}"

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            checkpoint_type=checkpoint_type,
            state_hash=state.compute_hash(),
            goal_stack_snapshot=state.goal_stack.copy(),
            current_goal_id=state.goal_stack[-1] if state.goal_stack else None,
            phase=state.phase,
            context_summary=context_summary,
        )

        state.checkpoints.append(checkpoint)

        # Trim old checkpoints
        if len(state.checkpoints) > self.max_checkpoints:
            state.checkpoints = state.checkpoints[-self.max_checkpoints:]

        return checkpoint

    def mark_crashed(self, reason: str = "") -> None:
        """Mark session as crashed"""
        with self._lock:
            with open(self.crash_marker, 'w') as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "reason": reason,
                }, f)

    def clear_crash_marker(self) -> None:
        """Clear crash marker"""
        with self._lock:
            if self.crash_marker.exists():
                self.crash_marker.unlink()

    def check_crashed(self) -> Tuple[bool, Optional[str]]:
        """Check if previous session crashed"""
        with self._lock:
            if not self.crash_marker.exists():
                return False, None

            try:
                with open(self.crash_marker, 'r') as f:
                    data = json.load(f)
                return True, data.get("reason", "Unknown")
            except Exception:
                return True, "Unknown"

    def cleanup_old_states(self, max_age_hours: float = 24.0) -> int:
        """Clean up old state files"""
        with self._lock:
            cleaned = 0
            cutoff = datetime.now() - timedelta(hours=max_age_hours)

            for path in self.state_dir.glob("*.bak"):
                try:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime)
                    if mtime < cutoff:
                        path.unlink()
                        cleaned += 1
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

            return cleaned

    def backup_state(self) -> Optional[Path]:
        """Create backup of current state"""
        with self._lock:
            if not self.state_file.exists():
                return None

            backup_name = f"state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            backup_path = self.state_dir / backup_name

            shutil.copy2(self.state_file, backup_path)
            return backup_path


# =============================================================================
# Recovery Manager
# =============================================================================

class RecoveryManager:
    """
    Manages crash detection and recovery.
    """

    def __init__(
        self,
        serializer: StateSerializer,
        default_strategy: RecoveryStrategy = RecoveryStrategy.RESUME_GOAL,
    ):
        self.serializer = serializer
        self.default_strategy = default_strategy

    def check_for_recovery(self) -> Tuple[bool, Optional[ExecutionState]]:
        """Check if recovery is needed and load state"""
        crashed, reason = self.serializer.check_crashed()

        if crashed:
            state = self.serializer.load_state()
            if state:
                state.is_crashed = True
                state.crash_reason = reason
                return True, state

        return False, None

    def recover(
        self,
        state: ExecutionState,
        strategy: Optional[RecoveryStrategy] = None,
    ) -> ExecutionState:
        """Recover from crashed state using specified strategy"""
        strategy = strategy or self.default_strategy

        if strategy == RecoveryStrategy.RESUME_EXACT:
            # Resume from exact checkpoint state
            return self._resume_exact(state)

        elif strategy == RecoveryStrategy.RESUME_GOAL:
            # Resume from current goal
            return self._resume_goal(state)

        elif strategy == RecoveryStrategy.RESTART_GOAL:
            # Restart current goal from beginning
            return self._restart_goal(state)

        elif strategy == RecoveryStrategy.ROLLBACK:
            # Rollback to previous checkpoint
            return self._rollback(state)

        return state

    def _resume_exact(self, state: ExecutionState) -> ExecutionState:
        """Resume from exact state"""
        state.is_crashed = False
        state.crash_reason = None
        self.serializer.clear_crash_marker()
        return state

    def _resume_goal(self, state: ExecutionState) -> ExecutionState:
        """Resume from current goal"""
        current = state.get_current_goal()
        if current:
            # Keep goal in progress
            current.status = GoalStatus.IN_PROGRESS

        state.is_crashed = False
        state.crash_reason = None
        self.serializer.clear_crash_marker()
        return state

    def _restart_goal(self, state: ExecutionState) -> ExecutionState:
        """Restart current goal from beginning"""
        current = state.get_current_goal()
        if current:
            current.status = GoalStatus.PENDING
            current.progress = 0.0
            current.started_at = None

        state.is_crashed = False
        state.crash_reason = None
        self.serializer.clear_crash_marker()
        return state

    def _rollback(self, state: ExecutionState) -> ExecutionState:
        """Rollback to previous checkpoint"""
        if state.checkpoints:
            # Find last successful checkpoint
            for checkpoint in reversed(state.checkpoints):
                if checkpoint.checkpoint_type != CheckpointType.ERROR:
                    # Restore goal stack from checkpoint
                    state.goal_stack = checkpoint.goal_stack_snapshot.copy()
                    state.phase = checkpoint.phase
                    break

        state.is_crashed = False
        state.crash_reason = None
        self.serializer.clear_crash_marker()
        return state

    def get_recovery_recommendation(self, state: ExecutionState) -> RecoveryStrategy:
        """Get recommended recovery strategy based on state"""
        if not state.checkpoints:
            return RecoveryStrategy.RESTART_GOAL

        last_checkpoint = state.checkpoints[-1]

        # If last checkpoint was an error, rollback
        if last_checkpoint.checkpoint_type == CheckpointType.ERROR:
            return RecoveryStrategy.ROLLBACK

        # If goal was almost complete, resume exact
        current = state.get_current_goal()
        if current and current.progress > 0.8:
            return RecoveryStrategy.RESUME_EXACT

        # Default to resume from goal
        return RecoveryStrategy.RESUME_GOAL


# =============================================================================
# Resume Session Context Manager
# =============================================================================

class ResumeSession:
    """
    Context manager for resumable execution sessions.
    Handles automatic checkpointing and crash detection.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        state_dir: Optional[Path] = None,
        auto_checkpoint: bool = True,
        checkpoint_interval: float = 60.0,
    ):
        self.session_id = session_id or self._generate_session_id()
        self.serializer = StateSerializer(state_dir)
        self.recovery_manager = RecoveryManager(self.serializer)
        self.auto_checkpoint = auto_checkpoint
        self.checkpoint_interval = checkpoint_interval

        self.state: Optional[ExecutionState] = None
        self.goal_stack = GoalStack()
        self._checkpoint_thread: Optional[threading.Thread] = None
        self._stop_checkpoint = threading.Event()

    def _generate_session_id(self) -> str:
        return f"S{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def __enter__(self) -> "ResumeSession":
        """Enter session context"""
        # Check for recovery
        needs_recovery, crashed_state = self.recovery_manager.check_for_recovery()

        if needs_recovery and crashed_state:
            # Recover from crash
            strategy = self.recovery_manager.get_recovery_recommendation(crashed_state)
            self.state = self.recovery_manager.recover(crashed_state, strategy)
            self.goal_stack.from_state(self.state.goals, self.state.goal_stack)
        else:
            # Fresh session
            self.state = ExecutionState(session_id=self.session_id)

        # Set crash marker (will be cleared on clean exit)
        self.serializer.mark_crashed("Session in progress")

        # Start auto-checkpoint thread
        if self.auto_checkpoint:
            self._start_checkpoint_thread()

        # Register cleanup on exit
        atexit.register(self._emergency_save)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit session context"""
        # Stop checkpoint thread
        self._stop_checkpoint.set()
        if self._checkpoint_thread:
            self._checkpoint_thread.join(timeout=2.0)

        # Update state from goal stack
        goals, stack = self.goal_stack.to_state()
        self.state.goals = goals
        self.state.goal_stack = stack

        if exc_type:
            # Exception occurred - save with error checkpoint
            self.state.is_crashed = True
            self.state.crash_reason = str(exc_val)
            self.serializer.create_checkpoint(
                self.state,
                CheckpointType.ERROR,
                f"Error: {exc_val}"
            )
            self.serializer.save_state(self.state)
            # Keep crash marker
        else:
            # Clean exit
            self.serializer.create_checkpoint(
                self.state,
                CheckpointType.MANUAL,
                "Clean session exit"
            )
            self.serializer.save_state(self.state)
            self.serializer.clear_crash_marker()

        # Unregister cleanup
        atexit.unregister(self._emergency_save)

        return False  # Don't suppress exceptions

    def _start_checkpoint_thread(self) -> None:
        """Start background checkpoint thread"""
        def checkpoint_loop() -> None:
            while not self._stop_checkpoint.wait(self.checkpoint_interval):
                self.checkpoint(CheckpointType.AUTO)

        self._checkpoint_thread = threading.Thread(target=checkpoint_loop, daemon=True)
        self._checkpoint_thread.start()

    def _emergency_save(self) -> None:
        """Emergency save on unexpected exit"""
        if self.state:
            goals, stack = self.goal_stack.to_state()
            self.state.goals = goals
            self.state.goal_stack = stack
            self.state.is_crashed = True
            self.state.crash_reason = "Unexpected exit"
            self.serializer.save_state(self.state)

    def checkpoint(
        self,
        checkpoint_type: CheckpointType = CheckpointType.MANUAL,
        context_summary: str = "",
    ) -> Checkpoint:
        """Create a checkpoint"""
        # Update state from goal stack
        goals, stack = self.goal_stack.to_state()
        self.state.goals = goals
        self.state.goal_stack = stack

        checkpoint = self.serializer.create_checkpoint(
            self.state,
            checkpoint_type,
            context_summary,
        )
        self.serializer.save_state(self.state)
        return checkpoint

    def push_goal(self, description: str, **kwargs) -> Goal:
        """Push a new goal"""
        goal = self.goal_stack.push_goal(description, **kwargs)
        self.checkpoint(CheckpointType.PRE_ACTION, f"New goal: {description[:50]}")
        return goal

    def complete_goal(self, goal_id: str, success: bool = True) -> bool:
        """Complete a goal"""
        result = self.goal_stack.complete_goal(goal_id, success)
        if result:
            self.checkpoint(CheckpointType.GOAL_COMPLETE, f"Completed: {goal_id}")
        return result

    def record_action(
        self,
        action_type: str,
        description: str,
        success: bool = True,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> ActionRecord:
        """Record an action"""
        current = self.goal_stack.peek()
        goal_id = current.goal_id if current else "none"

        action = ActionRecord(
            action_id=f"A{len(self.state.action_history):04d}",
            action_type=action_type,
            description=description,
            goal_id=goal_id,
            success=success,
            result=result,
            error=error,
        )

        self.state.action_history.append(action)
        return action

    def set_phase(self, phase: ExecutionPhase) -> None:
        """Set current execution phase"""
        self.state.phase = phase

    def get_state(self) -> ExecutionState:
        """Get current state"""
        goals, stack = self.goal_stack.to_state()
        self.state.goals = goals
        self.state.goal_stack = stack
        return self.state

    def get_stats(self) -> Dict[str, Any]:
        """Get session statistics"""
        return {
            "session_id": self.session_id,
            "phase": self.state.phase.value,
            "total_goals": len(self.goal_stack.goals),
            "active_goals": len(self.goal_stack.stack),
            "actions_recorded": len(self.state.action_history),
            "checkpoints": len(self.state.checkpoints),
            "was_recovered": self.state.is_crashed,
        }

    def summarize(self) -> str:
        """Generate human-readable summary"""
        stats = self.get_stats()
        lines = [
            "Resume Session Status",
            "=" * 40,
            f"Session ID: {stats['session_id']}",
            f"Phase: {stats['phase']}",
            f"Total goals: {stats['total_goals']}",
            f"Active goals: {stats['active_goals']}",
            f"Actions: {stats['actions_recorded']}",
            f"Checkpoints: {stats['checkpoints']}",
        ]

        if stats['was_recovered']:
            lines.append(f"Recovered from crash: Yes")

        return "\n".join(lines)


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests"""
    print("=" * 70)
    print("State Serializer CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool, detail: str = "") -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"✓ {name}")
            tests_passed += 1
        else:
            print(f"✗ {name}: {detail}")
            tests_failed += 1

    import tempfile
    tmpdir = tempfile.mkdtemp()

    try:
        # Test 1: Create Goal
        print("\n--- Test 1: Create Goal ---")
        goal = Goal(
            goal_id="G001",
            description="Test goal",
            status=GoalStatus.PENDING,
        )
        test("Goal created", goal.goal_id == "G001")
        test("Goal pending", goal.status == GoalStatus.PENDING)

        # Test 2: Goal Stack
        print("\n--- Test 2: Goal Stack ---")
        stack = GoalStack()
        g1 = stack.push_goal("First goal")
        g2 = stack.push_goal("Second goal", parent_id=g1.goal_id)
        test("Goals pushed", len(stack.goals) == 2)
        test("Stack order", stack.peek().goal_id == g2.goal_id)

        # Test 3: Start and Complete Goal
        print("\n--- Test 3: Goal Lifecycle ---")
        stack.start_goal(g2.goal_id)
        test("Goal started", g2.status == GoalStatus.IN_PROGRESS)
        stack.complete_goal(g2.goal_id)
        test("Goal completed", g2.status == GoalStatus.COMPLETED)

        # Test 4: State Serializer
        print("\n--- Test 4: State Serializer ---")
        serializer = StateSerializer(state_dir=Path(tmpdir))
        state = ExecutionState(session_id="test-session")
        saved = serializer.save_state(state)
        test("State saved", saved)
        test("State file exists", serializer.state_file.exists())

        # Test 5: Load State
        print("\n--- Test 5: Load State ---")
        loaded = serializer.load_state()
        test("State loaded", loaded is not None)
        test("Session ID matches", loaded.session_id == "test-session")

        # Test 6: Create Checkpoint
        print("\n--- Test 6: Checkpoint ---")
        checkpoint = serializer.create_checkpoint(state, CheckpointType.MANUAL)
        test("Checkpoint created", checkpoint is not None)
        test("Checkpoint ID", checkpoint.checkpoint_id.startswith("CP"))

        # Test 7: Crash Detection
        print("\n--- Test 7: Crash Detection ---")
        serializer.mark_crashed("Test crash")
        crashed, reason = serializer.check_crashed()
        test("Crash detected", crashed)
        test("Crash reason", reason == "Test crash")
        serializer.clear_crash_marker()

        # Test 8: Recovery Manager
        print("\n--- Test 8: Recovery Manager ---")
        recovery = RecoveryManager(serializer)
        state.is_crashed = True
        recovered = recovery.recover(state, RecoveryStrategy.RESUME_EXACT)
        test("State recovered", not recovered.is_crashed)

        # Test 9: Resume Session
        print("\n--- Test 9: Resume Session ---")
        with ResumeSession(state_dir=Path(tmpdir), auto_checkpoint=False) as session:
            goal = session.push_goal("Test goal in session")
            test("Session goal created", goal is not None)
            action = session.record_action("test", "Test action")
            test("Action recorded", action is not None)

        # Test 10: Session Recovery
        print("\n--- Test 10: Session Recovery ---")
        # Simulate crash by not using context manager
        serializer2 = StateSerializer(state_dir=Path(tmpdir))
        serializer2.mark_crashed("Simulated crash")
        recovery2 = RecoveryManager(serializer2)
        needs_recovery, _ = recovery2.check_for_recovery()
        test("Recovery needed detected", needs_recovery)

        # Test 11: Action Record
        print("\n--- Test 11: Action Record ---")
        action = ActionRecord(
            action_id="A001",
            action_type="file_read",
            description="Read config file",
            goal_id="G001",
            success=True,
        )
        d = action.to_dict()
        test("Action serializes", d["action_id"] == "A001")

        # Test 12: Execution State Hash
        print("\n--- Test 12: State Hash ---")
        state1 = ExecutionState(session_id="s1")
        hash1 = state1.compute_hash()
        state1.phase = ExecutionPhase.EXECUTING
        hash2 = state1.compute_hash()
        test("Hash computed", len(hash1) == 16)
        test("Hash changes", hash1 != hash2)

        # Test 13: Goal Retry
        print("\n--- Test 13: Goal Retry ---")
        stack2 = GoalStack()
        g = stack2.push_goal("Retry test")
        stack2.fail_goal(g.goal_id, "First attempt failed")
        test("Goal failed", g.status == GoalStatus.FAILED)
        retried = stack2.retry_goal(g.goal_id)
        test("Goal retried", retried and g.status == GoalStatus.PENDING)

        # Test 14: Recovery Strategy
        print("\n--- Test 14: Recovery Strategy ---")
        test_state = ExecutionState(session_id="test")
        strategy = recovery.get_recovery_recommendation(test_state)
        test("Strategy recommended", strategy is not None)

        # Test 15: Session Stats
        print("\n--- Test 15: Session Stats ---")
        with ResumeSession(state_dir=Path(tmpdir), auto_checkpoint=False) as session:
            session.push_goal("Stats test")
            stats = session.get_stats()
            test("Stats available", "session_id" in stats)
            test("Goal counted", stats["total_goals"] >= 1)

    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Summary
    print("\n" + "=" * 70)
    print(f"Tests passed: {tests_passed}")
    print(f"Tests failed: {tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    import sys
    success = run_cli_tests()
    sys.exit(0 if success else 1)

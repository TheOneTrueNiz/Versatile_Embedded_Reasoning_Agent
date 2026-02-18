#!/usr/bin/env python3
"""
Action Reversibility Tracking
=============================

Tracks whether actions can be undone and provides reversal mechanisms.

Source: Ported from GROKSTAR's action tracking concept

Problem Solved:
- VERA performs actions that may or may not be reversible
- Users need to know if something can be undone before/after it happens
- "Oops, undo that" should work when possible, with clear feedback when not

Solution:
- Every action is tagged with reversibility status before execution
- Reversible actions store undo instructions/snapshots
- Time-limited reversals tracked with deadlines
- Clear feedback when reversal is impossible

Usage:
    from reversibility import ReversibilityTracker, ActionType

    tracker = ReversibilityTracker()

    # Before action: check reversibility
    status = tracker.check_reversibility(ActionType.FILE_WRITE, target="config.json")
    # Returns: ("reversible", "File can be restored from backup")

    # Track an action for potential reversal
    action_id = tracker.track_action(
        action_type=ActionType.FILE_WRITE,
        target="config.json",
        description="Updated API endpoint",
        undo_data={"original_content": "..."},
        deadline_minutes=60  # Can undo for 60 minutes
    )

    # Attempt reversal
    result = tracker.undo(action_id)
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any, Tuple, Callable
from enum import Enum
import hashlib
import logging
logger = logging.getLogger(__name__)

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read, atomic_write, safe_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class ActionType(Enum):
    """Types of actions VERA can perform"""
    # File operations
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    FILE_RENAME = "file_rename"
    FILE_MOVE = "file_move"
    FILE_CREATE = "file_create"

    # Directory operations
    DIR_CREATE = "dir_create"
    DIR_DELETE = "dir_delete"

    # Task operations
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_DELETE = "task_delete"
    TASK_COMPLETE = "task_complete"

    # Communication
    EMAIL_SEND = "email_send"
    MESSAGE_SEND = "message_send"

    # Calendar
    CALENDAR_CREATE = "calendar_create"
    CALENDAR_UPDATE = "calendar_update"
    CALENDAR_DELETE = "calendar_delete"

    # System
    COMMAND_RUN = "command_run"
    PROCESS_START = "process_start"
    PROCESS_KILL = "process_kill"

    # Other
    API_CALL = "api_call"
    OTHER = "other"


class ReversibilityLevel(Enum):
    """How reversible an action is"""
    FULLY_REVERSIBLE = "fully_reversible"      # Can be completely undone
    PARTIALLY_REVERSIBLE = "partially"          # Some effects can be undone
    TIME_LIMITED = "time_limited"               # Can be undone within a window
    IRREVERSIBLE = "irreversible"               # Cannot be undone
    UNKNOWN = "unknown"                          # Reversibility not determined


class UndoStatus(Enum):
    """Status of an undo attempt"""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    ALREADY_UNDONE = "already_undone"


@dataclass
class TrackedAction:
    """A tracked reversible action"""
    id: str
    action_type: str
    target: str
    description: str
    timestamp: str
    reversibility: str
    undo_data: Dict[str, Any]
    deadline: Optional[str]  # ISO format
    undone: bool = False
    undone_at: Optional[str] = None
    undo_result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TrackedAction':
        return cls(**data)

    def is_expired(self) -> bool:
        """Check if the undo window has expired"""
        if not self.deadline:
            return False
        try:
            deadline_dt = datetime.fromisoformat(self.deadline)
            return datetime.now() > deadline_dt
        except ValueError:
            return False

    def time_remaining(self) -> Optional[timedelta]:
        """Get time remaining for undo"""
        if not self.deadline:
            return None
        try:
            deadline_dt = datetime.fromisoformat(self.deadline)
            remaining = deadline_dt - datetime.now()
            return remaining if remaining.total_seconds() > 0 else timedelta(0)
        except ValueError:
            return None


# Default reversibility for action types
DEFAULT_REVERSIBILITY = {
    ActionType.FILE_WRITE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.FILE_DELETE: ReversibilityLevel.FULLY_REVERSIBLE,  # If we save backup
    ActionType.FILE_RENAME: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.FILE_MOVE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.FILE_CREATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.DIR_CREATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.DIR_DELETE: ReversibilityLevel.FULLY_REVERSIBLE,  # If we save backup
    ActionType.TASK_CREATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.TASK_UPDATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.TASK_DELETE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.TASK_COMPLETE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.EMAIL_SEND: ReversibilityLevel.TIME_LIMITED,  # Some email systems allow recall
    ActionType.MESSAGE_SEND: ReversibilityLevel.PARTIALLY_REVERSIBLE,
    ActionType.CALENDAR_CREATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.CALENDAR_UPDATE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.CALENDAR_DELETE: ReversibilityLevel.FULLY_REVERSIBLE,
    ActionType.COMMAND_RUN: ReversibilityLevel.IRREVERSIBLE,  # Generally can't undo commands
    ActionType.PROCESS_START: ReversibilityLevel.PARTIALLY_REVERSIBLE,  # Can kill
    ActionType.PROCESS_KILL: ReversibilityLevel.IRREVERSIBLE,  # Can't resurrect
    ActionType.API_CALL: ReversibilityLevel.UNKNOWN,  # Depends on API
    ActionType.OTHER: ReversibilityLevel.UNKNOWN,
}


class ReversibilityTracker:
    """
    Tracks actions and their reversibility.

    Provides mechanisms to:
    - Check if an action is reversible before performing it
    - Track actions with undo data for later reversal
    - Execute reversals when requested
    """

    def __init__(self, storage_path: Path = None, memory_dir: Path = None) -> None:
        """
        Initialize reversibility tracker.

        Args:
            storage_path: Path to action storage file
            memory_dir: Base memory directory
        """
        if storage_path:
            self.storage_path = Path(storage_path)
        elif memory_dir:
            self.storage_path = Path(memory_dir) / "reversible_actions.json"
        else:
            self.storage_path = Path("vera_memory/reversible_actions.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Backup directory for file operations
        self.backup_dir = self.storage_path.parent / ".undo_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        # Load existing actions
        self._actions: Dict[str, TrackedAction] = {}
        self._load_actions()

        # Action counter
        self._action_count = len(self._actions)

        # Register undo handlers
        self._undo_handlers: Dict[str, Callable] = {
            ActionType.FILE_WRITE.value: self._undo_file_write,
            ActionType.FILE_DELETE.value: self._undo_file_delete,
            ActionType.FILE_RENAME.value: self._undo_file_rename,
            ActionType.FILE_MOVE.value: self._undo_file_move,
            ActionType.FILE_CREATE.value: self._undo_file_create,
            ActionType.DIR_CREATE.value: self._undo_dir_create,
            ActionType.TASK_UPDATE.value: self._undo_task_update,
        }

    def _load_actions(self) -> None:
        """Load tracked actions from storage"""
        if not self.storage_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path, default={})
            else:
                data = json.loads(self.storage_path.read_text())

            for action_id, action_data in data.get("actions", {}).items():
                self._actions[action_id] = TrackedAction.from_dict(action_data)
        except Exception:
            self._actions = {}

    def _save_actions(self) -> None:
        """Save tracked actions to storage"""
        data = {
            "actions": {k: v.to_dict() for k, v in self._actions.items()},
            "last_updated": datetime.now().isoformat()
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2, default=str))

    def _generate_id(self) -> str:
        """Generate unique action ID"""
        self._action_count += 1
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"ACT-{timestamp}-{self._action_count:04d}"

    def check_reversibility(
        self,
        action_type: ActionType,
        target: str = None,
        context: Dict[str, Any] = None
    ) -> Tuple[ReversibilityLevel, str]:
        """
        Check reversibility before performing an action.

        Args:
            action_type: Type of action to perform
            target: Target of the action (file path, task ID, etc.)
            context: Additional context for the check

        Returns:
            Tuple of (reversibility level, explanation)
        """
        default = DEFAULT_REVERSIBILITY.get(action_type, ReversibilityLevel.UNKNOWN)

        # Special handling for file operations
        if action_type in (ActionType.FILE_WRITE, ActionType.FILE_DELETE):
            if target:
                path = Path(target)
                if path.exists():
                    size_mb = path.stat().st_size / (1024 * 1024)
                    if size_mb > 100:
                        return (
                            ReversibilityLevel.PARTIALLY_REVERSIBLE,
                            f"Large file ({size_mb:.1f}MB) - backup may be truncated"
                        )

        # Command execution
        if action_type == ActionType.COMMAND_RUN:
            if context and context.get("command", "").startswith("rm "):
                return (
                    ReversibilityLevel.IRREVERSIBLE,
                    "File deletion via rm cannot be undone"
                )

        # Generate explanation
        explanations = {
            ReversibilityLevel.FULLY_REVERSIBLE: "Action can be completely undone",
            ReversibilityLevel.PARTIALLY_REVERSIBLE: "Some effects can be reversed",
            ReversibilityLevel.TIME_LIMITED: "Can be undone within a time window",
            ReversibilityLevel.IRREVERSIBLE: "Action cannot be undone once performed",
            ReversibilityLevel.UNKNOWN: "Reversibility depends on external factors",
        }

        return (default, explanations.get(default, ""))

    def track_action(
        self,
        action_type: ActionType,
        target: str,
        description: str,
        undo_data: Dict[str, Any] = None,
        deadline_minutes: int = None,
        reversibility: ReversibilityLevel = None
    ) -> str:
        """
        Track an action for potential reversal.

        Args:
            action_type: Type of action performed
            target: Target of the action
            description: Human-readable description
            undo_data: Data needed to reverse the action
            deadline_minutes: How long the action can be undone (None = forever)
            reversibility: Override default reversibility level

        Returns:
            Action ID for later reference
        """
        if reversibility is None:
            reversibility = DEFAULT_REVERSIBILITY.get(action_type, ReversibilityLevel.UNKNOWN)

        deadline = None
        if deadline_minutes:
            deadline = (datetime.now() + timedelta(minutes=deadline_minutes)).isoformat()

        action = TrackedAction(
            id=self._generate_id(),
            action_type=action_type.value,
            target=target,
            description=description,
            timestamp=datetime.now().isoformat(),
            reversibility=reversibility.value,
            undo_data=undo_data or {},
            deadline=deadline
        )

        self._actions[action.id] = action
        self._save_actions()

        return action.id

    def track_file_write(
        self,
        filepath: Path,
        description: str = None,
        deadline_minutes: int = 60
    ) -> str:
        """
        Track a file write with automatic backup.

        Saves the original content for potential reversal.
        """
        filepath = Path(filepath)
        original_content = None
        existed = filepath.exists()

        if existed:
            try:
                original_content = filepath.read_text()
            except Exception:
                try:
                    original_content = filepath.read_bytes().decode('latin-1')
                except Exception as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        # Create backup
        backup_path = None
        if original_content is not None:
            backup_name = f"{filepath.name}.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            backup_path = self.backup_dir / backup_name
            backup_path.write_text(original_content)

        return self.track_action(
            action_type=ActionType.FILE_WRITE,
            target=str(filepath),
            description=description or f"Modified {filepath.name}",
            undo_data={
                "original_existed": existed,
                "backup_path": str(backup_path) if backup_path else None,
                "original_content_hash": hashlib.md5(original_content.encode()).hexdigest() if original_content else None
            },
            deadline_minutes=deadline_minutes
        )

    def track_file_delete(
        self,
        filepath: Path,
        description: str = None,
        deadline_minutes: int = 1440  # 24 hours default for deletes
    ) -> str:
        """
        Track a file deletion with backup for recovery.
        """
        filepath = Path(filepath)

        if not filepath.exists():
            return self.track_action(
                action_type=ActionType.FILE_DELETE,
                target=str(filepath),
                description=description or f"Attempted to delete non-existent {filepath.name}",
                undo_data={"file_existed": False},
                deadline_minutes=deadline_minutes,
                reversibility=ReversibilityLevel.IRREVERSIBLE
            )

        # Create backup before delete
        try:
            content = filepath.read_bytes()
            backup_name = f"{filepath.name}.deleted.{datetime.now().strftime('%Y%m%d%H%M%S')}.bak"
            backup_path = self.backup_dir / backup_name
            backup_path.write_bytes(content)
        except Exception:
            backup_path = None

        return self.track_action(
            action_type=ActionType.FILE_DELETE,
            target=str(filepath),
            description=description or f"Deleted {filepath.name}",
            undo_data={
                "file_existed": True,
                "backup_path": str(backup_path) if backup_path else None,
                "original_path": str(filepath)
            },
            deadline_minutes=deadline_minutes,
            reversibility=ReversibilityLevel.FULLY_REVERSIBLE if backup_path else ReversibilityLevel.IRREVERSIBLE
        )

    def get_action(self, action_id: str) -> Optional[TrackedAction]:
        """Get a tracked action by ID"""
        return self._actions.get(action_id)

    def get_recent(self, limit: int = 10, undoable_only: bool = False) -> List[TrackedAction]:
        """Get recent tracked actions"""
        actions = sorted(
            self._actions.values(),
            key=lambda a: a.timestamp,
            reverse=True
        )

        if undoable_only:
            actions = [
                a for a in actions
                if not a.undone and not a.is_expired() and
                a.reversibility != ReversibilityLevel.IRREVERSIBLE.value
            ]

        return actions[:limit]

    def get_by_target(self, target: str, limit: int = 10) -> List[TrackedAction]:
        """Get actions for a specific target"""
        matches = [a for a in self._actions.values() if a.target == target]
        return sorted(matches, key=lambda a: a.timestamp, reverse=True)[:limit]

    def undo(self, action_id: str) -> Tuple[UndoStatus, str]:
        """
        Attempt to undo an action.

        Args:
            action_id: ID of the action to undo

        Returns:
            Tuple of (status, message)
        """
        action = self._actions.get(action_id)

        if not action:
            return (UndoStatus.NOT_FOUND, f"Action {action_id} not found")

        if action.undone:
            return (UndoStatus.ALREADY_UNDONE, f"Action {action_id} was already undone at {action.undone_at}")

        if action.is_expired():
            return (UndoStatus.EXPIRED, f"Undo window for action {action_id} has expired")

        if action.reversibility == ReversibilityLevel.IRREVERSIBLE.value:
            return (UndoStatus.FAILED, f"Action {action_id} is irreversible")

        # Try to execute the undo
        handler = self._undo_handlers.get(action.action_type)

        if handler:
            try:
                status, message = handler(action)
                action.undone = status == UndoStatus.SUCCESS
                action.undone_at = datetime.now().isoformat() if action.undone else None
                action.undo_result = message
                self._save_actions()
                return (status, message)
            except Exception as e:
                return (UndoStatus.FAILED, f"Undo failed: {str(e)}")
        else:
            return (UndoStatus.FAILED, f"No undo handler for action type {action.action_type}")

    # === Undo Handlers ===

    def _undo_file_write(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a file write by restoring backup"""
        backup_path = action.undo_data.get("backup_path")
        target_path = Path(action.target)

        if not backup_path:
            if not action.undo_data.get("original_existed"):
                # File didn't exist before, delete it
                if target_path.exists():
                    target_path.unlink()
                    return (UndoStatus.SUCCESS, f"Deleted newly created file {target_path.name}")
                return (UndoStatus.SUCCESS, "File already removed")
            return (UndoStatus.FAILED, "No backup available to restore")

        backup_path = Path(backup_path)
        if not backup_path.exists():
            return (UndoStatus.FAILED, f"Backup file {backup_path} not found")

        # Restore from backup
        try:
            content = backup_path.read_text()
            if HAS_ATOMIC:
                atomic_write(target_path, content)
            else:
                target_path.write_text(content)
            return (UndoStatus.SUCCESS, f"Restored {target_path.name} from backup")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to restore: {str(e)}")

    def _undo_file_delete(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a file deletion by restoring backup"""
        backup_path = action.undo_data.get("backup_path")
        original_path = action.undo_data.get("original_path", action.target)

        if not backup_path:
            return (UndoStatus.FAILED, "No backup available to restore deleted file")

        backup_path = Path(backup_path)
        original_path = Path(original_path)

        if not backup_path.exists():
            return (UndoStatus.FAILED, f"Backup file {backup_path} not found")

        if original_path.exists():
            return (UndoStatus.FAILED, f"Cannot restore - {original_path} already exists")

        try:
            content = backup_path.read_bytes()
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(content)
            return (UndoStatus.SUCCESS, f"Restored deleted file {original_path.name}")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to restore: {str(e)}")

    def _undo_file_rename(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a file rename"""
        old_name = action.undo_data.get("old_name")
        new_path = Path(action.target)

        if not old_name:
            return (UndoStatus.FAILED, "Original filename not recorded")

        old_path = new_path.parent / old_name

        if not new_path.exists():
            return (UndoStatus.FAILED, f"Renamed file {new_path} no longer exists")

        if old_path.exists():
            return (UndoStatus.FAILED, f"Cannot restore - {old_path} already exists")

        try:
            new_path.rename(old_path)
            return (UndoStatus.SUCCESS, f"Renamed {new_path.name} back to {old_name}")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to rename: {str(e)}")

    def _undo_file_move(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a file move"""
        original_path = action.undo_data.get("original_path")
        current_path = Path(action.target)

        if not original_path:
            return (UndoStatus.FAILED, "Original path not recorded")

        original_path = Path(original_path)

        if not current_path.exists():
            return (UndoStatus.FAILED, f"Moved file {current_path} no longer exists")

        if original_path.exists():
            return (UndoStatus.FAILED, f"Cannot restore - {original_path} already exists")

        try:
            original_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current_path), str(original_path))
            return (UndoStatus.SUCCESS, f"Moved {current_path.name} back to {original_path}")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to move: {str(e)}")

    def _undo_file_create(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a file creation by deleting it"""
        target_path = Path(action.target)

        if not target_path.exists():
            return (UndoStatus.SUCCESS, f"File {target_path.name} already removed")

        try:
            target_path.unlink()
            return (UndoStatus.SUCCESS, f"Deleted created file {target_path.name}")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to delete: {str(e)}")

    def _undo_dir_create(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a directory creation"""
        target_path = Path(action.target)

        if not target_path.exists():
            return (UndoStatus.SUCCESS, f"Directory {target_path.name} already removed")

        if not target_path.is_dir():
            return (UndoStatus.FAILED, f"{target_path} is not a directory")

        # Only delete if empty (safe)
        if any(target_path.iterdir()):
            return (UndoStatus.PARTIAL, f"Directory {target_path.name} is not empty, cannot safely delete")

        try:
            target_path.rmdir()
            return (UndoStatus.SUCCESS, f"Removed empty directory {target_path.name}")
        except Exception as e:
            return (UndoStatus.FAILED, f"Failed to remove: {str(e)}")

    def _undo_task_update(self, action: TrackedAction) -> Tuple[UndoStatus, str]:
        """Undo a task update"""
        # This would need integration with the task system
        original_state = action.undo_data.get("original_state")

        if not original_state:
            return (UndoStatus.FAILED, "Original task state not recorded")

        return (UndoStatus.PARTIAL, f"Task restoration requires manual action: {original_state}")

    def cleanup_expired(self, also_delete_backups: bool = False) -> int:
        """
        Clean up expired undo records.

        Args:
            also_delete_backups: If True, also delete backup files for expired actions

        Returns:
            Number of records cleaned up
        """
        cleaned = 0
        to_remove = []

        for action_id, action in self._actions.items():
            if action.is_expired() or action.undone:
                to_remove.append(action_id)

                if also_delete_backups:
                    backup_path = action.undo_data.get("backup_path")
                    if backup_path:
                        try:
                            Path(backup_path).unlink(missing_ok=True)
                        except Exception as exc:
                            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        for action_id in to_remove:
            del self._actions[action_id]
            cleaned += 1

        if cleaned > 0:
            self._save_actions()

        return cleaned

    def get_stats(self) -> Dict[str, Any]:
        """Get reversibility statistics"""
        total = len(self._actions)
        undone = sum(1 for a in self._actions.values() if a.undone)
        expired = sum(1 for a in self._actions.values() if a.is_expired() and not a.undone)
        active = total - undone - expired

        by_type = {}
        for action in self._actions.values():
            by_type[action.action_type] = by_type.get(action.action_type, 0) + 1

        return {
            "total_tracked": total,
            "active": active,
            "undone": undone,
            "expired": expired,
            "by_type": by_type,
            "backup_dir": str(self.backup_dir),
            "backup_size_mb": sum(
                f.stat().st_size for f in self.backup_dir.iterdir() if f.is_file()
            ) / (1024 * 1024) if self.backup_dir.exists() else 0
        }

    def summarize_undoable(self) -> str:
        """Generate a summary of actions that can be undone"""
        undoable = self.get_recent(limit=20, undoable_only=True)

        if not undoable:
            return "No reversible actions available."

        lines = [f"**Reversible Actions** ({len(undoable)} available)"]
        lines.append("")

        for action in undoable[:10]:  # Show top 10
            remaining = action.time_remaining()
            if remaining:
                time_str = f"({int(remaining.total_seconds() / 60)}m remaining)"
            else:
                time_str = "(no expiry)"

            lines.append(f"- [{action.id}] {action.description[:50]} {time_str}")

        if len(undoable) > 10:
            lines.append(f"- ... and {len(undoable) - 10} more")

        return '\n'.join(lines)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Reversibility Tracker - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        storage_path = tmpdir / "reversible_actions.json"
        tracker = ReversibilityTracker(storage_path=storage_path)

        # Test 1: Check reversibility
        print("\n=== Test 1: Check Reversibility ===")
        level, explanation = tracker.check_reversibility(ActionType.FILE_WRITE)
        print(f"   FILE_WRITE: {level.value}")
        print(f"   Explanation: {explanation}")

        level, explanation = tracker.check_reversibility(ActionType.COMMAND_RUN)
        print(f"   COMMAND_RUN: {level.value}")
        print("   Result: PASS")

        # Test 2: Track file write with backup
        print("\n=== Test 2: Track File Write ===")
        test_file = tmpdir / "test.txt"
        test_file.write_text("Original content")

        action_id = tracker.track_file_write(test_file, "Test modification")
        print(f"   Tracked: {action_id}")

        # Modify the file
        test_file.write_text("Modified content")
        print("   Modified file content")
        print("   Result: PASS")

        # Test 3: Undo file write
        print("\n=== Test 3: Undo File Write ===")
        status, message = tracker.undo(action_id)
        print(f"   Status: {status.value}")
        print(f"   Message: {message}")

        restored_content = test_file.read_text()
        assert restored_content == "Original content", f"Expected 'Original content', got '{restored_content}'"
        print(f"   Restored content: {restored_content}")
        print("   Result: PASS")

        # Test 4: Track file delete
        print("\n=== Test 4: Track File Delete ===")
        delete_file = tmpdir / "to_delete.txt"
        delete_file.write_text("Delete me")

        delete_id = tracker.track_file_delete(delete_file, "Deleting test file")
        delete_file.unlink()  # Actually delete it
        print(f"   Tracked: {delete_id}")
        print("   File deleted")
        print("   Result: PASS")

        # Test 5: Undo file delete
        print("\n=== Test 5: Undo File Delete ===")
        status, message = tracker.undo(delete_id)
        print(f"   Status: {status.value}")
        print(f"   Message: {message}")

        assert delete_file.exists(), "File should be restored"
        assert delete_file.read_text() == "Delete me"
        print(f"   File restored: {delete_file.read_text()}")
        print("   Result: PASS")

        # Test 6: Expired action
        print("\n=== Test 6: Expired Action ===")
        expired_id = tracker.track_action(
            action_type=ActionType.FILE_WRITE,
            target="/tmp/expired.txt",
            description="Already expired",
            deadline_minutes=-1  # Already expired
        )

        status, message = tracker.undo(expired_id)
        assert status == UndoStatus.EXPIRED
        print(f"   Status: {status.value}")
        print(f"   Message: {message}")
        print("   Result: PASS")

        # Test 7: Statistics
        print("\n=== Test 7: Statistics ===")
        stats = tracker.get_stats()
        print(f"   Total tracked: {stats['total_tracked']}")
        print(f"   Active: {stats['active']}")
        print(f"   Undone: {stats['undone']}")
        print(f"   Expired: {stats['expired']}")
        print("   Result: PASS")

        # Test 8: Summary
        print("\n=== Test 8: Summary ===")
        summary = tracker.summarize_undoable()
        print("   Summary generated:")
        for line in summary.split('\n')[:5]:
            print(f"   {line}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nReversibility Tracker is ready for integration!")

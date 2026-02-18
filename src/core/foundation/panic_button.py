#!/usr/bin/env python3
"""
Panic Button - Emergency Shutdown Controller
=============================================

Provides graceful cancellation of all VERA operations.

Source: Ported from GROKSTAR's kill_all_experiments() and signal handling

Problem Solved:
- VERA may launch multiple async operations (web searches, file writes, API calls)
- If user needs to abort, simply stopping text generation leaves orphans
- Partial file writes can corrupt data

Solution:
- Track all spawned subprocesses by PID
- Track temp files and in-progress writes
- On /stop or SIGINT, clean everything up gracefully

Usage:
    from panic_button import get_panic_button, init_panic_button

    # At startup
    panic = init_panic_button()

    # Track a subprocess
    panic.track_process(pid, "web_search query='test'")

    # Track a temp file
    panic.register_temp_file(Path("/tmp/vera_temp.json"))

    # Track a file write in progress
    panic.begin_write(Path("output.txt"), backup_path=Path("output.txt.backup"))

    # On completion
    panic.complete_write(Path("output.txt"))

    # EMERGENCY STOP
    summary = panic.panic("User requested stop")
"""

import os
import signal
import asyncio
import threading
import shutil
from pathlib import Path
from typing import Set, Dict, Optional, List, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
logger = logging.getLogger(__name__)


class PanicReason(Enum):
    """Reasons for panic"""
    USER_REQUEST = "user_request"
    SIGNAL = "signal"
    ERROR = "error"
    BUDGET_EXCEEDED = "budget_exceeded"
    TIMEOUT = "timeout"


@dataclass
class TrackedProcess:
    """A subprocess being tracked for cleanup"""
    pid: int
    command: str
    started: datetime
    temp_files: Set[Path] = field(default_factory=set)
    description: str = ""

    def is_alive(self) -> bool:
        """Check if process is still running"""
        try:
            os.kill(self.pid, 0)  # Signal 0 just checks existence
            return True
        except (ProcessLookupError, PermissionError):
            return False


@dataclass
class PendingWrite:
    """A file write in progress"""
    filepath: Path
    backup_path: Optional[Path]
    started: datetime
    temp_path: Optional[Path] = None


@dataclass
class PanicSummary:
    """Summary of panic cleanup actions"""
    reason: str
    timestamp: str
    processes_killed: List[Dict[str, Any]]
    temp_files_deleted: List[str]
    writes_reverted: List[str]
    errors: List[str]
    duration_ms: float


class PanicButton:
    """
    Emergency shutdown controller for VERA.

    Tracks:
    - Spawned subprocesses (by PID)
    - Temp files to clean up
    - In-progress file writes to revert

    On panic:
    - Kills all tracked processes
    - Deletes temp files
    - Reverts partial writes
    """

    def __init__(self) -> None:
        self._processes: Dict[int, TrackedProcess] = {}
        self._pending_writes: Dict[Path, PendingWrite] = {}
        self._temp_files: Set[Path] = set()
        self._lock = threading.RLock()
        self._panic_triggered = False
        self._panic_summary: Optional[PanicSummary] = None

        # Async cancellation support
        self._cancel_event: Optional[asyncio.Event] = None
        self._cancellation_callbacks: List[callable] = []

    def _get_cancel_event(self) -> asyncio.Event:
        """Get or create async cancel event"""
        if self._cancel_event is None:
            try:
                self._cancel_event = asyncio.Event()
            except RuntimeError as exc:
                # No event loop
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        return self._cancel_event

    # === Process Tracking ===

    def track_process(
        self,
        pid: int,
        command: str,
        description: str = ""
    ) -> None:
        """
        Register a subprocess for tracking.

        Args:
            pid: Process ID
            command: Command that was run
            description: Human-readable description
        """
        with self._lock:
            self._processes[pid] = TrackedProcess(
                pid=pid,
                command=command,
                started=datetime.now(),
                description=description
            )

    def untrack_process(self, pid: int) -> None:
        """
        Remove a subprocess from tracking (completed normally).

        Args:
            pid: Process ID to untrack
        """
        with self._lock:
            self._processes.pop(pid, None)

    def get_tracked_processes(self) -> List[Dict[str, Any]]:
        """Get list of currently tracked processes"""
        with self._lock:
            return [
                {
                    "pid": p.pid,
                    "command": p.command[:100],
                    "description": p.description,
                    "started": p.started.isoformat(),
                    "alive": p.is_alive()
                }
                for p in self._processes.values()
            ]

    # === Temp File Tracking ===

    def register_temp_file(self, filepath: Path) -> None:
        """
        Register a temp file for cleanup on panic.

        Args:
            filepath: Path to temp file
        """
        with self._lock:
            self._temp_files.add(Path(filepath).resolve())

    def unregister_temp_file(self, filepath: Path) -> None:
        """
        Remove temp file from tracking (cleaned up normally).

        Args:
            filepath: Path to temp file
        """
        with self._lock:
            self._temp_files.discard(Path(filepath).resolve())

    # === Write Tracking ===

    def begin_write(
        self,
        filepath: Path,
        backup_path: Optional[Path] = None,
        temp_path: Optional[Path] = None
    ) -> None:
        """
        Record that a file write is starting.

        Args:
            filepath: File being written
            backup_path: Backup of original content (for revert)
            temp_path: Temp file being written to (for cleanup)
        """
        with self._lock:
            filepath = Path(filepath).resolve()
            self._pending_writes[filepath] = PendingWrite(
                filepath=filepath,
                backup_path=Path(backup_path).resolve() if backup_path else None,
                temp_path=Path(temp_path).resolve() if temp_path else None,
                started=datetime.now()
            )

    def complete_write(self, filepath: Path) -> None:
        """
        Record that a file write completed successfully.

        Args:
            filepath: File that was written
        """
        with self._lock:
            self._pending_writes.pop(Path(filepath).resolve(), None)

    # === Cancellation Support ===

    def is_cancelled(self) -> bool:
        """Check if panic has been triggered"""
        return self._panic_triggered

    async def wait_for_cancel(self, timeout: float = None) -> bool:
        """
        Async wait for cancellation signal.

        Args:
            timeout: Max seconds to wait (None = forever)

        Returns:
            True if cancelled, False if timeout
        """
        event = self._get_cancel_event()
        if event is None:
            return self._panic_triggered

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def register_cancellation_callback(self, callback: callable) -> None:
        """
        Register a callback to be called on panic.

        Callback receives PanicReason as argument.
        """
        self._cancellation_callbacks.append(callback)

    # === PANIC ===

    def panic(
        self,
        reason: str = "User requested stop",
        reason_type: PanicReason = PanicReason.USER_REQUEST
    ) -> PanicSummary:
        """
        PANIC! Execute emergency shutdown.

        Kills processes, deletes temp files, reverts partial writes.

        Args:
            reason: Human-readable reason for panic
            reason_type: Categorized reason

        Returns:
            Summary of cleanup actions taken
        """
        start_time = datetime.now()

        with self._lock:
            if self._panic_triggered:
                return self._panic_summary

            self._panic_triggered = True

            # Trigger async cancellation
            if self._cancel_event:
                self._cancel_event.set()

            summary_data = {
                "reason": reason,
                "timestamp": start_time.isoformat(),
                "processes_killed": [],
                "temp_files_deleted": [],
                "writes_reverted": [],
                "errors": []
            }

            print(f"\n[PANIC] {'=' * 50}")
            print(f"[PANIC] EMERGENCY STOP: {reason}")
            print(f"[PANIC] {'=' * 50}")

            # 1. Kill all tracked processes
            for pid, proc in list(self._processes.items()):
                try:
                    if proc.is_alive():
                        print(f"[PANIC] Killing PID {pid}: {proc.command[:50]}")
                        os.kill(pid, signal.SIGTERM)
                        summary_data.get("processes_killed", "").append({
                            "pid": pid,
                            "command": proc.command[:100]
                        })
                except Exception as e:
                    summary_data.get("errors", "").append(f"Failed to kill PID {pid}: {e}")

            # 2. Delete temp files
            for temp_file in list(self._temp_files):
                try:
                    if temp_file.exists():
                        print(f"[PANIC] Deleting temp file: {temp_file}")
                        temp_file.unlink()
                        summary_data.get("temp_files_deleted", "").append(str(temp_file))
                except Exception as e:
                    summary_data.get("errors", "").append(f"Failed to delete {temp_file}: {e}")

            # 3. Revert partial writes
            for filepath, pending in list(self._pending_writes.items()):
                try:
                    # Delete temp file if exists
                    if pending.temp_path and pending.temp_path.exists():
                        pending.temp_path.unlink()

                    # Restore from backup if available
                    if pending.backup_path and pending.backup_path.exists():
                        print(f"[PANIC] Restoring: {filepath}")
                        shutil.copy2(pending.backup_path, filepath)
                        summary_data.get("writes_reverted", "").append(str(filepath))
                    elif filepath.exists():
                        # No backup - file might be corrupted, note it
                        summary_data.get("errors", "").append(
                            f"Partial write to {filepath} - no backup available"
                        )
                except Exception as e:
                    summary_data.get("errors", "").append(f"Failed to revert {filepath}: {e}")

            # Clear tracking
            self._processes.clear()
            self._temp_files.clear()
            self._pending_writes.clear()

            # Calculate duration
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000

            self._panic_summary = PanicSummary(
                reason=reason,
                timestamp=start_time.isoformat(),
                processes_killed=summary_data.get("processes_killed", ""),
                temp_files_deleted=summary_data.get("temp_files_deleted", ""),
                writes_reverted=summary_data.get("writes_reverted", ""),
                errors=summary_data.get("errors", ""),
                duration_ms=duration_ms
            )

            print(f"[PANIC] {'=' * 50}")
            print(f"[PANIC] Cleanup complete in {duration_ms:.1f}ms")
            print(f"[PANIC]   Processes killed: {len(summary_data.get('processes_killed', ''))}")
            print(f"[PANIC]   Temp files deleted: {len(summary_data.get('temp_files_deleted', ''))}")
            print(f"[PANIC]   Writes reverted: {len(summary_data.get('writes_reverted', ''))}")
            print(f"[PANIC]   Errors: {len(summary_data.get('errors', ''))}")
            print(f"[PANIC] {'=' * 50}\n")

            # Call registered callbacks
            for callback in self._cancellation_callbacks:
                try:
                    callback(reason_type)
                except Exception as e:
                    print(f"[PANIC] Callback error: {e}")

            return self._panic_summary

    def reset(self) -> None:
        """Reset panic button for reuse (e.g., after recovery)"""
        with self._lock:
            self._panic_triggered = False
            self._panic_summary = None
            self._processes.clear()
            self._temp_files.clear()
            self._pending_writes.clear()
            if self._cancel_event:
                self._cancel_event.clear()

    def get_status(self) -> Dict[str, Any]:
        """Get current tracking status"""
        with self._lock:
            return {
                "panic_triggered": self._panic_triggered,
                "tracked_processes": len(self._processes),
                "temp_files": len(self._temp_files),
                "pending_writes": len(self._pending_writes),
                "process_list": self.get_tracked_processes(),
                "last_panic": self._panic_summary.reason if self._panic_summary else None
            }


# Global instance
_PANIC_BUTTON: Optional[PanicButton] = None


def get_panic_button() -> PanicButton:
    """Get global panic button instance (creates if needed)"""
    global _PANIC_BUTTON
    if _PANIC_BUTTON is None:
        _PANIC_BUTTON = PanicButton()
    return _PANIC_BUTTON


def init_panic_button() -> PanicButton:
    """Initialize fresh global panic button"""
    global _PANIC_BUTTON
    _PANIC_BUTTON = PanicButton()
    return _PANIC_BUTTON


def install_signal_handlers(panic_button: PanicButton = None) -> None:
    """
    Install signal handlers for graceful shutdown.

    Handles SIGINT (Ctrl+C) and SIGTERM.
    """
    if panic_button is None:
        panic_button = get_panic_button()

    def handler(signum, frame) -> None:
        sig_name = signal.Signals(signum).name
        panic_button.panic(
            reason=f"Signal received: {sig_name}",
            reason_type=PanicReason.SIGNAL
        )
        # Exit after cleanup
        import sys
        sys.exit(128 + signum)

    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile
    import subprocess
    import time

    print("=" * 60)
    print("Panic Button - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Test 1: Basic initialization
        print("\n=== Test 1: Initialization ===")
        panic = init_panic_button()
        status = panic.get_status()
        assert not status["panic_triggered"]
        assert status["tracked_processes"] == 0
        print("   Panic button initialized")
        print("   Result: PASS")

        # Test 2: Process tracking
        print("\n=== Test 2: Process Tracking ===")
        # Start a sleep process
        proc = subprocess.Popen(["sleep", "60"])
        panic.track_process(proc.pid, "sleep 60", "Test sleep process")

        status = panic.get_status()
        assert status["tracked_processes"] == 1
        assert status["process_list"][0]["pid"] == proc.pid
        print(f"   Tracking PID {proc.pid}")
        print("   Result: PASS")

        # Test 3: Temp file tracking
        print("\n=== Test 3: Temp File Tracking ===")
        temp_file = tmpdir / "temp_test.txt"
        temp_file.write_text("temporary content")
        panic.register_temp_file(temp_file)

        status = panic.get_status()
        assert status["temp_files"] == 1
        print(f"   Tracking temp file: {temp_file}")
        print("   Result: PASS")

        # Test 4: Write tracking
        print("\n=== Test 4: Write Tracking ===")
        target_file = tmpdir / "output.txt"
        backup_file = tmpdir / "output.txt.backup"

        # Create "original" content
        target_file.write_text("original content")
        shutil.copy2(target_file, backup_file)

        # Start a "write"
        target_file.write_text("partial write in progress")
        panic.begin_write(target_file, backup_path=backup_file)

        status = panic.get_status()
        assert status["pending_writes"] == 1
        print("   Tracking pending write")
        print("   Result: PASS")

        # Test 5: PANIC!
        print("\n=== Test 5: PANIC! ===")
        summary = panic.panic("Test panic")

        # Verify process killed
        time.sleep(0.1)
        try:
            os.kill(proc.pid, 0)
            print("   WARNING: Process still alive")
        except ProcessLookupError:
            print("   Process killed successfully")

        # Verify temp file deleted
        assert not temp_file.exists(), "Temp file should be deleted"
        print("   Temp file deleted")

        # Verify write reverted
        content = target_file.read_text()
        assert content == "original content", f"Expected 'original content', got '{content}'"
        print("   Write reverted to original")

        # Verify summary
        assert len(summary.processes_killed) == 1
        assert len(summary.temp_files_deleted) == 1
        assert len(summary.writes_reverted) == 1
        print(f"   Summary: {summary.processes_killed[0]['pid']} killed, 1 temp deleted, 1 reverted")
        print("   Result: PASS")

        # Test 6: Reset
        print("\n=== Test 6: Reset ===")
        panic.reset()
        status = panic.get_status()
        assert not status["panic_triggered"]
        assert status["tracked_processes"] == 0
        print("   Panic button reset")
        print("   Result: PASS")

        # Test 7: Cancellation check
        print("\n=== Test 7: Cancellation Check ===")
        panic = init_panic_button()
        assert not panic.is_cancelled()
        panic.panic("Test")
        assert panic.is_cancelled()
        print("   Cancellation state correct")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nPanic button module is ready for integration!")

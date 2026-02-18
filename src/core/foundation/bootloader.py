#!/usr/bin/env python3
"""
Safe Mode Bootloader
====================

Detects crash loops and automatically recovers from bad self-modifications.

Source: Ported from GROKSTAR's _maybe_recover_from_bad_self_mod()

Problem Solved:
- If VERA modifies her own config or critical files and introduces errors,
  she "bricks" herself and requires manual intervention.

Solution:
- Track boot times and modified files
- Detect if previous run crashed within 15 seconds of start
- Automatically restore .backup files if crash detected

Usage:
    from core.foundation.bootloader import safe_boot

    # At very start of VERA, before other imports
    bootloader = safe_boot(Path("."))

    # Before modifying critical files
    bootloader.record_file_modification(Path("src/core/runtime/vera.py"))

    # On clean exit
    bootloader.record_clean_shutdown()
"""

import os
import json
import time
import shutil
import atexit
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict


# Configuration
CRASH_THRESHOLD_SECONDS = 15
BOOT_STATE_FILENAME = ".boot_state.json"

# Critical files that should trigger backup on modification
CRITICAL_FILES = [
    "run_vera.py",
    "src/core/runtime/vera.py",
    "src/core/runtime/config.py",
    "src/core/runtime/prompts.py",
    "src/safety/safety_validator.py",
    "src/core/foundation/bootloader.py",
    "src/core/atomic_io.py",
    "dangerous_patterns.json",
]


@dataclass
class BootState:
    """State persisted between boots"""
    boot_time: float
    boot_time_iso: str
    pid: int
    clean_shutdown: bool
    modified_files: List[str]
    shutdown_time: Optional[float] = None
    shutdown_time_iso: Optional[str] = None
    crash_count: int = 0
    last_crash_recovery: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BootState':
        return cls(
            boot_time=data.get("boot_time", 0),
            boot_time_iso=data.get("boot_time_iso", ""),
            pid=data.get("pid", 0),
            clean_shutdown=data.get("clean_shutdown", True),
            modified_files=data.get("modified_files", []),
            shutdown_time=data.get("shutdown_time"),
            shutdown_time_iso=data.get("shutdown_time_iso"),
            crash_count=data.get("crash_count", 0),
            last_crash_recovery=data.get("last_crash_recovery"),
        )


class Bootloader:
    """
    Safe mode bootloader for VERA.

    Detects crash loops and automatically recovers from bad modifications.
    """

    def __init__(self, project_root: Path, memory_dir: str = "vera_memory") -> None:
        """
        Initialize bootloader.

        Args:
            project_root: Root directory of VERA project
            memory_dir: Directory for VERA memory (where boot state is stored)
        """
        self.project_root = Path(project_root).resolve()
        self.memory_dir = self.project_root / memory_dir
        self.boot_state_file = self.memory_dir / BOOT_STATE_FILENAME
        self.boot_time = time.time()
        self._state: Optional[BootState] = None
        self._registered_atexit = False

    def _load_boot_state(self) -> Optional[BootState]:
        """Load previous boot state from disk"""
        if not self.boot_state_file.exists():
            return None

        try:
            with open(self.boot_state_file, 'r') as f:
                data = json.load(f)
            return BootState.from_dict(data)
        except (json.JSONDecodeError, IOError, KeyError) as e:
            print(f"[BOOTLOADER] Warning: Could not load boot state: {e}")
            return None

    def _save_boot_state(self, state: BootState) -> None:
        """Save boot state atomically"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Write to temp file then rename (atomic)
        tmp_file = self.boot_state_file.with_suffix('.tmp')
        try:
            with open(tmp_file, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            os.rename(tmp_file, self.boot_state_file)
        except Exception as e:
            print(f"[BOOTLOADER] Warning: Could not save boot state: {e}")
            if tmp_file.exists():
                tmp_file.unlink()

    def check_for_crash_loop(self) -> Optional[List[Path]]:
        """
        Check if previous run crashed shortly after start.

        A crash loop is detected if:
        1. Previous run did not record clean shutdown
        2. Previous run crashed within CRASH_THRESHOLD_SECONDS of start

        Returns:
            List of files to restore if crash detected, None otherwise
        """
        previous_state = self._load_boot_state()

        if previous_state is None:
            return None

        # Check for crash indicators
        if previous_state.clean_shutdown:
            return None  # Previous run ended cleanly

        # Calculate time between previous boot and this boot
        time_since_previous_boot = self.boot_time - previous_state.boot_time

        if time_since_previous_boot < CRASH_THRESHOLD_SECONDS:
            # Crash loop detected!
            print(f"[BOOTLOADER] Crash loop detected!")
            print(f"[BOOTLOADER] Previous run lasted only {time_since_previous_boot:.1f}s")
            print(f"[BOOTLOADER] Modified files: {previous_state.modified_files}")

            return [Path(f) for f in previous_state.modified_files]

        # Previous run crashed, but not immediately - might be unrelated
        if previous_state.modified_files:
            print(f"[BOOTLOADER] Warning: Previous run did not exit cleanly")
            print(f"[BOOTLOADER] Modified files were: {previous_state.modified_files}")
            print(f"[BOOTLOADER] Not restoring (crash was not immediate)")

        return None

    def recover_from_crash(self, files_to_restore: List[Path]) -> Dict[str, Any]:
        """
        Restore backup files after crash.

        Args:
            files_to_restore: List of file paths to restore

        Returns:
            Recovery summary
        """
        summary = {
            "files_checked": len(files_to_restore),
            "restored": [],
            "no_backup": [],
            "failed": [],
        }

        for filepath in files_to_restore:
            # Resolve path relative to project root if needed
            if not filepath.is_absolute():
                filepath = self.project_root / filepath

            backup_path = filepath.with_suffix(filepath.suffix + '.backup')

            if not backup_path.exists():
                summary["no_backup"].append(str(filepath))
                print(f"[BOOTLOADER] No backup for: {filepath}")
                continue

            try:
                shutil.copy2(backup_path, filepath)
                summary["restored"].append(str(filepath))
                print(f"[BOOTLOADER] Restored: {filepath}")
            except Exception as e:
                summary["failed"].append({"file": str(filepath), "error": str(e)})
                print(f"[BOOTLOADER] Failed to restore {filepath}: {e}")

        # Update crash count
        previous_state = self._load_boot_state()
        if previous_state:
            previous_state.crash_count += 1
            previous_state.last_crash_recovery = datetime.now().isoformat()
            self._save_boot_state(previous_state)

        return summary

    def record_boot(self) -> None:
        """Record that we're starting up (called after crash check)"""
        previous_state = self._load_boot_state()
        crash_count = previous_state.crash_count if previous_state else 0

        self._state = BootState(
            boot_time=self.boot_time,
            boot_time_iso=datetime.now().isoformat(),
            pid=os.getpid(),
            clean_shutdown=False,  # Will be set True on clean exit
            modified_files=[],
            crash_count=crash_count,
        )

        self._save_boot_state(self._state)

        # Register atexit handler for clean shutdown
        if not self._registered_atexit:
            atexit.register(self.record_clean_shutdown)
            self._registered_atexit = True

    def record_file_modification(self, filepath: Path) -> None:
        """
        Record that a critical file is about to be modified.

        Should be called BEFORE modifying the file.
        Creates a backup of the current file.

        Args:
            filepath: Path to file being modified
        """
        if self._state is None:
            print("[BOOTLOADER] Warning: record_file_modification called before record_boot")
            return

        filepath = Path(filepath).resolve()
        filepath_str = str(filepath)

        # Create backup if file exists
        if filepath.exists():
            backup_path = filepath.with_suffix(filepath.suffix + '.backup')
            try:
                shutil.copy2(filepath, backup_path)
                print(f"[BOOTLOADER] Backed up: {filepath} -> {backup_path}")
            except Exception as e:
                print(f"[BOOTLOADER] Warning: Could not backup {filepath}: {e}")

        # Record modification
        if filepath_str not in self._state.modified_files:
            self._state.modified_files.append(filepath_str)
            self._save_boot_state(self._state)

    def record_clean_shutdown(self) -> None:
        """Record that we're shutting down cleanly"""
        if self._state is None:
            return

        self._state.clean_shutdown = True
        self._state.shutdown_time = time.time()
        self._state.shutdown_time_iso = datetime.now().isoformat()
        self._state.modified_files = []  # Clear modifications on clean exit

        self._save_boot_state(self._state)
        print("[BOOTLOADER] Clean shutdown recorded")

    def is_critical_file(self, filepath: Path) -> bool:
        """Check if a file is in the critical files list"""
        filepath = Path(filepath)

        for critical in CRITICAL_FILES:
            critical_path = Path(critical)
            if filepath.name == critical_path.name:
                return True
            if str(filepath).endswith(critical):
                return True

        return False

    def get_status(self) -> Dict[str, Any]:
        """Get current bootloader status"""
        return {
            "boot_time": datetime.fromtimestamp(self.boot_time).isoformat(),
            "uptime_seconds": time.time() - self.boot_time,
            "modified_files": self._state.modified_files if self._state else [],
            "crash_count": self._state.crash_count if self._state else 0,
            "project_root": str(self.project_root),
        }


def safe_boot(project_root: Path, memory_dir: str = "vera_memory") -> Bootloader:
    """
    Execute safe boot sequence.

    Call this at the very start of VERA, before other imports that might fail.

    Process:
    1. Check for crash loop
    2. Recover if needed
    3. Record this boot

    Args:
        project_root: Root directory of VERA project
        memory_dir: Directory for VERA memory

    Returns:
        Bootloader instance for ongoing use
    """
    bootloader = Bootloader(project_root, memory_dir)

    # Check for crash loop
    files_to_restore = bootloader.check_for_crash_loop()

    if files_to_restore:
        print("[BOOTLOADER] " + "=" * 50)
        print("[BOOTLOADER] CRASH LOOP DETECTED - ENTERING SAFE MODE")
        print("[BOOTLOADER] " + "=" * 50)
        print(f"[BOOTLOADER] Previous run crashed within {CRASH_THRESHOLD_SECONDS}s of start")
        print(f"[BOOTLOADER] Attempting to restore {len(files_to_restore)} file(s)...")

        summary = bootloader.recover_from_crash(files_to_restore)

        if summary["restored"]:
            print(f"[BOOTLOADER] Restored {len(summary['restored'])} file(s)")
            for f in summary["restored"]:
                print(f"[BOOTLOADER]   - {f}")

        if summary["no_backup"]:
            print(f"[BOOTLOADER] No backup available for {len(summary['no_backup'])} file(s)")

        if summary["failed"]:
            print(f"[BOOTLOADER] Failed to restore {len(summary['failed'])} file(s)")

        print("[BOOTLOADER] " + "=" * 50)
        print("[BOOTLOADER] Safe mode recovery complete")
        print("[BOOTLOADER] " + "=" * 50)

    # Record this boot
    bootloader.record_boot()

    return bootloader


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Bootloader - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        memory_dir = project_root / "vera_memory"
        memory_dir.mkdir()

        # Test 1: Normal boot sequence
        print("\n=== Test 1: Normal Boot Sequence ===")
        bootloader = safe_boot(project_root)
        print(f"   Boot recorded at: {bootloader.get_status()['boot_time']}")
        print("   Result: PASS")

        # Test 2: Clean shutdown
        print("\n=== Test 2: Clean Shutdown ===")
        bootloader.record_clean_shutdown()
        state = json.loads((memory_dir / BOOT_STATE_FILENAME).read_text())
        assert state["clean_shutdown"] == True
        print("   Clean shutdown recorded")
        print("   Result: PASS")

        # Test 3: File modification tracking
        print("\n=== Test 3: File Modification Tracking ===")
        bootloader2 = safe_boot(project_root)
        test_file = project_root / "test_critical.py"
        test_file.write_text("original content")

        bootloader2.record_file_modification(test_file)
        assert (test_file.with_suffix(".py.backup")).exists()
        print("   Backup created for modified file")
        print("   Result: PASS")

        # Test 4: Crash detection (simulate crash by not recording clean shutdown)
        print("\n=== Test 4: Crash Detection ===")
        # Don't call record_clean_shutdown - simulate crash

        # Create new bootloader with same boot time (simulates rapid restart)
        bootloader3 = Bootloader(project_root)
        bootloader3.boot_time = bootloader2.boot_time + 5  # 5 seconds later

        files = bootloader3.check_for_crash_loop()
        assert files is not None, "Should detect crash"
        assert len(files) == 1, f"Should have 1 modified file, got {len(files)}"
        print(f"   Crash detected, files to restore: {files}")
        print("   Result: PASS")

        # Test 5: Recovery
        print("\n=== Test 5: Recovery ===")
        test_file.write_text("corrupted content")  # Simulate corruption
        summary = bootloader3.recover_from_crash(files)
        restored_content = test_file.read_text()
        assert restored_content == "original content", f"Expected 'original content', got '{restored_content}'"
        print(f"   Restored {len(summary['restored'])} file(s)")
        print(f"   Content restored to: '{restored_content}'")
        print("   Result: PASS")

        # Test 6: Critical file detection
        print("\n=== Test 6: Critical File Detection ===")
        assert bootloader.is_critical_file(Path("run_vera.py"))
        assert bootloader.is_critical_file(Path("/some/path/src/core/runtime/vera.py"))
        assert not bootloader.is_critical_file(Path("random_file.txt"))
        print("   Critical file detection working")
        print("   Result: PASS")

        # Clean up
        bootloader3.record_boot()
        bootloader3.record_clean_shutdown()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nBootloader module is ready for integration!")

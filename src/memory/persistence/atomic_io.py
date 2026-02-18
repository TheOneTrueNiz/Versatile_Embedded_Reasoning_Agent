#!/usr/bin/env python3
"""
Atomic File Operations
======================

Provides atomic file write operations that guarantee files are never
left in a corrupted state, even during crashes or power failures.

Source: Ported from GROKSTAR's _atomic_write() function

Guarantees:
- File is never left in corrupted/partial state
- Either old content or new content, never in-between
- Survives power failure mid-write
- Uses file locking to prevent concurrent write corruption

Improvement #4 (2025-12-26): Transactional Concurrency Management
- Read-modify-write transaction support
- Conflict detection using timestamps and content hashes
- CRDT-style merge for compatible data types (counters, sets, lists, NDJSON)
- Rollback capability for failed transactions

Research basis:
- arXiv:2409.14252 (EGWalker CRDT for collaborative editing)

Usage:
    from atomic_io import atomic_write, atomic_append, atomic_json_write

    # Write text file
    atomic_write("/path/to/file.txt", "content here")

    # Append to log file
    atomic_append("/path/to/log.ndjson", '{"event": "test"}\n')

    # Write JSON with formatting
    atomic_json_write("/path/to/config.json", {"key": "value"})

    # Transactional read-modify-write (Improvement #4)
    with FileTransaction("/path/to/data.json") as tx:
        data = tx.read_json()
        data["counter"] += 1
        tx.write_json(data)
    # Automatically handles conflicts and rollback
"""

import os
import json
import fcntl
import hashlib
import tempfile
import time
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Union, Any, Optional, Dict, List, Callable
from contextlib import contextmanager
import logging
logger = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    """Raised when atomic write fails"""
    pass


def atomic_write(
    filepath: Union[str, Path],
    content: Union[str, bytes],
    mode: str = 'w',
    encoding: str = 'utf-8'
) -> None:
    """
    Write content to file atomically.

    Process:
    1. Write to temporary file in same directory
    2. Acquire exclusive lock
    3. Flush and fsync to ensure durability
    4. Atomic rename to target path
    5. Fsync directory to persist the rename

    Args:
        filepath: Target file path
        content: Content to write (str or bytes)
        mode: Write mode ('w' for text, 'wb' for binary)
        encoding: Text encoding (ignored for binary mode)

    Raises:
        AtomicWriteError: If write fails
        PermissionError: If write not permitted
        OSError: For other filesystem errors
    """
    filepath = Path(filepath).resolve()

    # Create parent directory if needed
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Create temp file in same directory (required for atomic rename)
    tmp_path = filepath.with_suffix(filepath.suffix + '.tmp.' + str(os.getpid()))

    try:
        # Determine if binary mode
        is_binary = 'b' in mode

        # Open temp file
        open_kwargs = {'mode': mode}
        if not is_binary:
            open_kwargs['encoding'] = encoding

        with open(tmp_path, **open_kwargs) as f:
            # Acquire exclusive lock
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                # Write content
                f.write(content)

                # Force to kernel buffers
                f.flush()

                # Force to disk
                os.fsync(f.fileno())

            finally:
                # Release lock
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Atomic rename (POSIX guarantees atomicity on same filesystem)
        os.rename(tmp_path, filepath)

        # Sync directory to ensure rename is persisted
        # This is the often-forgotten step that prevents data loss
        dir_fd = os.open(str(filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception as e:
        # Clean up temp file on any failure
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        raise AtomicWriteError(f"Atomic write to {filepath} failed: {e}") from e


def atomic_append(
    filepath: Union[str, Path],
    content: str,
    encoding: str = 'utf-8'
) -> None:
    """
    Append content to file atomically with locking.

    For append-only logs like decision_ledger.ndjson or activity_log.ndjson.
    Uses file locking to prevent concurrent append corruption.

    Note: This doesn't rewrite the entire file, so it's faster than
    atomic_write for append operations, but provides weaker guarantees
    (partial append possible on crash, but no corruption of existing data).

    Args:
        filepath: Target file path
        content: Content to append
        encoding: Text encoding

    Raises:
        AtomicWriteError: If append fails
    """
    filepath = Path(filepath).resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(filepath, 'a', encoding=encoding) as f:
            # Acquire exclusive lock
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)

            try:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        raise AtomicWriteError(f"Atomic append to {filepath} failed: {e}") from e


def atomic_json_write(
    filepath: Union[str, Path],
    data: Any,
    indent: int = 2,
    sort_keys: bool = False
) -> None:
    """
    Write JSON data to file atomically.

    Convenience wrapper around atomic_write for JSON data.

    Args:
        filepath: Target file path
        data: JSON-serializable data
        indent: JSON indentation (default 2)
        sort_keys: Whether to sort keys

    Raises:
        AtomicWriteError: If write fails
        TypeError: If data is not JSON-serializable
    """
    content = json.dumps(data, indent=indent, sort_keys=sort_keys, default=str)
    atomic_write(filepath, content)


def atomic_ndjson_append(
    filepath: Union[str, Path],
    record: dict
) -> None:
    """
    Append a single record to NDJSON file atomically.

    Args:
        filepath: Target NDJSON file path
        record: Dictionary to append as JSON line

    Raises:
        AtomicWriteError: If append fails
    """
    line = json.dumps(record, default=str) + '\n'
    atomic_append(filepath, line)


@contextmanager
def atomic_write_context(
    filepath: Union[str, Path],
    mode: str = 'w',
    encoding: str = 'utf-8'
):
    """
    Context manager for atomic file writing.

    Usage:
        with atomic_write_context("/path/to/file.txt") as f:
            f.write("content")
            f.write("more content")
        # File is atomically committed when context exits

    If an exception occurs inside the context, the file is not modified.

    Args:
        filepath: Target file path
        mode: Write mode
        encoding: Text encoding

    Yields:
        File-like object for writing
    """
    filepath = Path(filepath).resolve()
    filepath.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = filepath.with_suffix(filepath.suffix + '.tmp.' + str(os.getpid()))
    is_binary = 'b' in mode

    open_kwargs = {'mode': mode}
    if not is_binary:
        open_kwargs['encoding'] = encoding

    f = None
    try:
        f = open(tmp_path, **open_kwargs)
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)

        yield f

        # If we get here, no exception occurred
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()
        f = None

        # Atomic rename
        os.rename(tmp_path, filepath)

        # Sync directory
        dir_fd = os.open(str(filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    except Exception:
        # Exception occurred, clean up and re-raise
        if f is not None:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except (OSError, ValueError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            f.close()

        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        raise


def safe_read(
    filepath: Union[str, Path],
    default: str = "",
    encoding: str = 'utf-8'
) -> str:
    """
    Read file with shared lock to prevent reading during write.

    Args:
        filepath: File path to read
        default: Default value if file doesn't exist
        encoding: Text encoding

    Returns:
        File contents or default
    """
    filepath = Path(filepath)

    if not filepath.exists():
        return default

    try:
        with open(filepath, 'r', encoding=encoding) as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return f.read()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        return default


def safe_json_read(
    filepath: Union[str, Path],
    default: Any = None
) -> Any:
    """
    Read JSON file with locking.

    Args:
        filepath: JSON file path
        default: Default value if file doesn't exist or is invalid

    Returns:
        Parsed JSON or default
    """
    content = safe_read(filepath, "")

    if not content:
        return default

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return default


# ============================================================================
# Transactional Concurrency Management (Improvement #4)
# ============================================================================

class ConflictError(Exception):
    """Raised when a transaction conflicts with concurrent modification"""
    def __init__(self, message: str, original_hash: str, current_hash: str) -> None:
        super().__init__(message)
        self.original_hash = original_hash
        self.current_hash = current_hash


class MergeStrategy(Enum):
    """Strategies for merging conflicting changes"""
    FAIL = auto()           # Raise ConflictError
    LAST_WRITE_WINS = auto()  # Overwrite with our changes
    FIRST_WRITE_WINS = auto()  # Keep original, discard our changes
    MERGE_JSON = auto()     # Merge JSON objects
    MERGE_NDJSON = auto()   # Merge NDJSON (append-style)
    MERGE_COUNTERS = auto()  # CRDT-style counter merge
    MERGE_SETS = auto()     # CRDT-style set merge
    CUSTOM = auto()         # Use custom merge function


@dataclass
class FileSnapshot:
    """Snapshot of file state at transaction start"""
    filepath: Path
    exists: bool
    content: Optional[str] = None
    content_hash: Optional[str] = None
    mtime: Optional[float] = None
    size: Optional[int] = None

    @classmethod
    def capture(cls, filepath: Union[str, Path]) -> 'FileSnapshot':
        """Capture current file state"""
        filepath = Path(filepath).resolve()

        if not filepath.exists():
            return cls(filepath=filepath, exists=False)

        try:
            stat = filepath.stat()
            content = filepath.read_text(encoding='utf-8')
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            return cls(
                filepath=filepath,
                exists=True,
                content=content,
                content_hash=content_hash,
                mtime=stat.st_mtime,
                size=stat.st_size
            )
        except Exception:
            return cls(filepath=filepath, exists=False)

    def has_changed(self) -> bool:
        """Check if file has changed since snapshot"""
        current = FileSnapshot.capture(self.filepath)

        # File was created
        if not self.exists and current.exists:
            return True

        # File was deleted
        if self.exists and not current.exists:
            return True

        # Neither exists
        if not self.exists and not current.exists:
            return False

        # Compare hashes
        return self.content_hash != current.content_hash


@dataclass
class TransactionResult:
    """Result of a file transaction"""
    success: bool
    filepath: Path
    had_conflict: bool = False
    merge_applied: bool = False
    original_content: Optional[str] = None
    final_content: Optional[str] = None
    error: Optional[str] = None


class FileTransaction:
    """
    Transactional file operations with conflict detection.

    Provides read-modify-write semantics with automatic conflict detection
    and configurable merge strategies.

    Usage:
        with FileTransaction("/path/to/file.json") as tx:
            data = tx.read_json()
            data["count"] += 1
            tx.write_json(data)

        # Or with explicit merge strategy:
        with FileTransaction("/path/to/file.json", merge_strategy=MergeStrategy.MERGE_JSON) as tx:
            ...

    The transaction will:
    1. Capture file state at start
    2. Detect conflicts before commit
    3. Apply merge strategy if conflict occurs
    4. Rollback on failure
    """

    def __init__(
        self,
        filepath: Union[str, Path],
        merge_strategy: MergeStrategy = MergeStrategy.FAIL,
        custom_merge: Optional[Callable[[str, str, str], str]] = None,
        max_retries: int = 3,
        retry_delay: float = 0.1
    ):
        """
        Initialize file transaction.

        Args:
            filepath: Path to the file
            merge_strategy: How to handle conflicts
            custom_merge: Custom merge function (original, ours, theirs) -> merged
            max_retries: Max retries on conflict with merge
            retry_delay: Delay between retries in seconds
        """
        self.filepath = Path(filepath).resolve()
        self.merge_strategy = merge_strategy
        self.custom_merge = custom_merge
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._snapshot: Optional[FileSnapshot] = None
        self._pending_content: Optional[str] = None
        self._pending_json: Optional[Any] = None
        self._committed = False
        self._rolled_back = False
        # Track original values for CRDT merges
        self._original_snapshot_content: Optional[str] = None
        self._original_pending_content: Optional[str] = None

    def __enter__(self) -> 'FileTransaction':
        """Start transaction by capturing file state"""
        self._snapshot = FileSnapshot.capture(self.filepath)
        # Save original for CRDT merges
        self._original_snapshot_content = self._snapshot.content
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit or rollback transaction"""
        if exc_type is not None:
            # Exception occurred, don't commit
            self._rolled_back = True
            return False

        if self._pending_content is not None or self._pending_json is not None:
            self._commit()

        return False

    def read(self) -> str:
        """Read file content"""
        if self._snapshot is None:
            raise RuntimeError("Transaction not started (use 'with' statement)")

        if self._snapshot.exists:
            return self._snapshot.content or ""
        return ""

    def read_json(self, default: Any = None) -> Any:
        """Read file as JSON"""
        content = self.read()
        if not content:
            return default
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return default

    def read_ndjson(self) -> List[Dict]:
        """Read file as NDJSON (newline-delimited JSON)"""
        content = self.read()
        if not content:
            return []

        records = []
        for line in content.strip().split('\n'):
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        return records

    def write(self, content: str) -> None:
        """Stage content for write on commit"""
        self._pending_content = content
        self._pending_json = None
        # Save original for CRDT merges (only on first write)
        if self._original_pending_content is None:
            self._original_pending_content = content

    def write_json(self, data: Any, indent: int = 2) -> None:
        """Stage JSON data for write on commit"""
        self._pending_json = data
        content = json.dumps(data, indent=indent, default=str)
        self._pending_content = content
        # Save original for CRDT merges (only on first write)
        if self._original_pending_content is None:
            self._original_pending_content = content

    def write_ndjson(self, records: List[Dict]) -> None:
        """Stage NDJSON records for write on commit"""
        lines = [json.dumps(r, default=str) for r in records]
        self._pending_content = '\n'.join(lines) + '\n'
        self._pending_json = None

    def append_ndjson(self, record: Dict) -> None:
        """Append a single record to NDJSON"""
        current = self.read_ndjson()
        current.append(record)
        self.write_ndjson(current)

    def _commit(self) -> TransactionResult:
        """Commit the transaction with conflict detection using compare-and-swap"""
        if self._snapshot is None:
            raise RuntimeError("Transaction not started")

        if self._pending_content is None:
            # Nothing to write
            return TransactionResult(
                success=True,
                filepath=self.filepath,
                original_content=self._snapshot.content
            )

        for attempt in range(self.max_retries):
            # Use file locking for atomic compare-and-swap
            result = self._try_atomic_commit()
            if result is not None:
                return result
            # Commit failed due to conflict, retry after merge
            time.sleep(self.retry_delay * (1 + attempt * 0.5))  # Exponential backoff

        # Max retries exceeded
        return TransactionResult(
            success=False,
            filepath=self.filepath,
            had_conflict=True,
            error=f"Max retries ({self.max_retries}) exceeded due to conflicts"
        )

    def _try_atomic_commit(self) -> Optional[TransactionResult]:
        """
        Attempt atomic commit with lock-held conflict check.
        Returns TransactionResult on success or terminal failure, None to retry.
        """
        # Ensure parent directory exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        # Create a lock file for coordination
        lock_path = self.filepath.with_suffix(self.filepath.suffix + '.lock')

        try:
            # Open lock file (create if needed)
            with open(lock_path, 'w') as lock_file:
                # Acquire exclusive lock
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)

                try:
                    # Re-check for conflicts while holding the lock
                    if self._snapshot.has_changed():
                        # Conflict detected! Handle it while still holding lock
                        result = self._handle_conflict()
                        if result is not None:
                            return result
                        # Merge succeeded, but we need to retry the write
                        # (another process might write before we can)
                        return None

                    # No conflict, write the file
                    tmp_path = self.filepath.with_suffix(self.filepath.suffix + '.tmp.' + str(os.getpid()))

                    try:
                        with open(tmp_path, 'w', encoding='utf-8') as f:
                            f.write(self._pending_content)
                            f.flush()
                            os.fsync(f.fileno())

                        os.rename(tmp_path, self.filepath)

                        # Sync directory
                        dir_fd = os.open(str(self.filepath.parent), os.O_RDONLY | os.O_DIRECTORY)
                        try:
                            os.fsync(dir_fd)
                        finally:
                            os.close(dir_fd)

                        self._committed = True

                        return TransactionResult(
                            success=True,
                            filepath=self.filepath,
                            original_content=self._original_snapshot_content,
                            final_content=self._pending_content
                        )

                    except Exception as e:
                        # Clean up temp file
                        try:
                            if tmp_path.exists():
                                tmp_path.unlink()
                        except OSError as exc:
                            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
                        return TransactionResult(
                            success=False,
                            filepath=self.filepath,
                            error=str(e)
                        )

                finally:
                    # Release lock
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

        except ConflictError:
            # Re-raise conflict errors to be handled by caller
            raise
        except Exception as e:
            return TransactionResult(
                success=False,
                filepath=self.filepath,
                error=f"Lock acquisition failed: {e}"
            )

    def _handle_conflict(self) -> Optional[TransactionResult]:
        """
        Handle a detected conflict based on merge strategy.

        Returns:
            TransactionResult if conflict cannot be resolved, None if merge succeeded
        """
        current_snapshot = FileSnapshot.capture(self.filepath)

        if self.merge_strategy == MergeStrategy.FAIL:
            raise ConflictError(
                f"File {self.filepath} was modified during transaction",
                self._snapshot.content_hash or "",
                current_snapshot.content_hash or ""
            )

        elif self.merge_strategy == MergeStrategy.LAST_WRITE_WINS:
            # Update snapshot to current state and proceed with our write
            self._snapshot = current_snapshot
            return None

        elif self.merge_strategy == MergeStrategy.FIRST_WRITE_WINS:
            # Keep the current version, discard our changes
            return TransactionResult(
                success=True,
                filepath=self.filepath,
                had_conflict=True,
                original_content=self._snapshot.content,
                final_content=current_snapshot.content
            )

        elif self.merge_strategy == MergeStrategy.MERGE_JSON:
            merged = self._merge_json(
                self._snapshot.content or "{}",
                self._pending_content or "{}",
                current_snapshot.content or "{}"
            )
            self._pending_content = merged
            self._snapshot = current_snapshot
            return None

        elif self.merge_strategy == MergeStrategy.MERGE_NDJSON:
            merged = self._merge_ndjson(
                self._snapshot.content or "",
                self._pending_content or "",
                current_snapshot.content or ""
            )
            self._pending_content = merged
            self._snapshot = current_snapshot
            return None

        elif self.merge_strategy == MergeStrategy.MERGE_COUNTERS:
            # Use ORIGINAL values for delta calculation, not merged values
            merged = self._merge_counters(
                self._original_snapshot_content or "{}",
                self._original_pending_content or "{}",
                current_snapshot.content or "{}"
            )
            self._pending_content = merged
            self._snapshot = current_snapshot
            return None

        elif self.merge_strategy == MergeStrategy.MERGE_SETS:
            merged = self._merge_sets(
                self._snapshot.content or "{}",
                self._pending_content or "{}",
                current_snapshot.content or "{}"
            )
            self._pending_content = merged
            self._snapshot = current_snapshot
            return None

        elif self.merge_strategy == MergeStrategy.CUSTOM:
            if self.custom_merge is None:
                raise ValueError("Custom merge strategy requires custom_merge function")
            merged = self.custom_merge(
                self._snapshot.content or "",
                self._pending_content or "",
                current_snapshot.content or ""
            )
            self._pending_content = merged
            self._snapshot = current_snapshot
            return None

        return None

    def _merge_json(self, original: str, ours: str, theirs: str) -> str:
        """
        Merge JSON objects using simple field-level merge.

        Strategy: Fields modified in 'ours' win over 'theirs'.
        """
        try:
            orig_obj = json.loads(original) if original else {}
            our_obj = json.loads(ours) if ours else {}
            their_obj = json.loads(theirs) if theirs else {}
        except json.JSONDecodeError:
            # Fall back to last-write-wins
            return ours

        # Start with theirs, overlay our changes
        merged = their_obj.copy()

        # Find what we changed from original
        for key, value in our_obj.items():
            orig_value = orig_obj.get(key)
            if value != orig_value:
                # We changed this field
                merged[key] = value

        return json.dumps(merged, indent=2, default=str)

    def _merge_ndjson(self, original: str, ours: str, theirs: str) -> str:
        """
        Merge NDJSON by combining unique records.

        Uses record content hash for deduplication.
        """
        def parse_ndjson(content: str) -> List[Dict]:
            records = []
            for line in content.strip().split('\n'):
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
            return records

        def record_hash(record: Dict) -> str:
            return hashlib.md5(json.dumps(record, sort_keys=True).encode()).hexdigest()

        orig_records = parse_ndjson(original)
        our_records = parse_ndjson(ours)
        their_records = parse_ndjson(theirs)

        # Get original hashes
        orig_hashes = {record_hash(r) for r in orig_records}

        # Find new records in ours (not in original)
        our_new = [r for r in our_records if record_hash(r) not in orig_hashes]

        # Combine: their records + our new records
        merged = their_records + our_new

        # Deduplicate by hash
        seen = set()
        unique = []
        for r in merged:
            h = record_hash(r)
            if h not in seen:
                seen.add(h)
                unique.append(r)

        return '\n'.join(json.dumps(r, default=str) for r in unique) + '\n'

    def _merge_counters(self, original: str, ours: str, theirs: str) -> str:
        """
        CRDT-style counter merge.

        For each counter field, take max(ours, theirs) if both increased,
        or compute delta-based merge.
        """
        try:
            orig_obj = json.loads(original) if original else {}
            our_obj = json.loads(ours) if ours else {}
            their_obj = json.loads(theirs) if theirs else {}
        except json.JSONDecodeError:
            return ours

        merged = {}

        # Get all keys
        all_keys = set(orig_obj.keys()) | set(our_obj.keys()) | set(their_obj.keys())

        for key in all_keys:
            orig_val = orig_obj.get(key, 0)
            our_val = our_obj.get(key, 0)
            their_val = their_obj.get(key, 0)

            # Check if values are numeric (counters)
            if isinstance(orig_val, (int, float)) and isinstance(our_val, (int, float)) and isinstance(their_val, (int, float)):
                # Delta-based merge: base + our_delta + their_delta
                our_delta = our_val - orig_val
                their_delta = their_val - orig_val
                merged[key] = orig_val + our_delta + their_delta
            else:
                # Non-counter: last-write wins (ours)
                merged[key] = our_val

        return json.dumps(merged, indent=2, default=str)

    def _merge_sets(self, original: str, ours: str, theirs: str) -> str:
        """
        CRDT-style set merge (OR-Set semantics).

        Union of all added items, respecting removals.
        """
        try:
            orig_obj = json.loads(original) if original else {}
            our_obj = json.loads(ours) if ours else {}
            their_obj = json.loads(theirs) if theirs else {}
        except json.JSONDecodeError:
            return ours

        merged = {}

        # Get all keys
        all_keys = set(orig_obj.keys()) | set(our_obj.keys()) | set(their_obj.keys())

        for key in all_keys:
            orig_val = orig_obj.get(key, [])
            our_val = our_obj.get(key, [])
            their_val = their_obj.get(key, [])

            # Check if values are lists (sets)
            if isinstance(orig_val, list) and isinstance(our_val, list) and isinstance(their_val, list):
                # Union with duplicate removal
                merged_set = set(orig_val) | set(our_val) | set(their_val)

                # Check for removals
                our_removed = set(orig_val) - set(our_val)
                their_removed = set(orig_val) - set(their_val)

                # Apply removals
                merged_set -= our_removed
                merged_set -= their_removed

                merged[key] = list(merged_set)
            else:
                # Non-set: ours wins
                merged[key] = our_val

        return json.dumps(merged, indent=2, default=str)


class TransactionManager:
    """
    Manages multiple file transactions with coordinated commit.

    For operations that span multiple files.
    """

    def __init__(self) -> None:
        self.transactions: List[FileTransaction] = []
        self._snapshots: Dict[Path, FileSnapshot] = {}

    def add(self, filepath: Union[str, Path], **kwargs) -> FileTransaction:
        """Add a file to the transaction set"""
        tx = FileTransaction(filepath, **kwargs)
        self.transactions.append(tx)
        return tx

    def begin(self) -> None:
        """Begin all transactions"""
        for tx in self.transactions:
            tx._snapshot = FileSnapshot.capture(tx.filepath)
            self._snapshots[tx.filepath] = tx._snapshot

    def check_conflicts(self) -> List[Path]:
        """Check all files for conflicts"""
        conflicts = []
        for tx in self.transactions:
            if tx._snapshot and tx._snapshot.has_changed():
                conflicts.append(tx.filepath)
        return conflicts

    def commit_all(self) -> Dict[Path, TransactionResult]:
        """Commit all transactions"""
        results = {}

        # First check for conflicts
        conflicts = self.check_conflicts()
        if conflicts and any(tx.merge_strategy == MergeStrategy.FAIL for tx in self.transactions):
            for tx in self.transactions:
                results[tx.filepath] = TransactionResult(
                    success=False,
                    filepath=tx.filepath,
                    had_conflict=tx.filepath in conflicts,
                    error="Conflict detected in multi-file transaction"
                )
            return results

        # Commit each transaction
        for tx in self.transactions:
            try:
                result = tx._commit()
                results[tx.filepath] = result
            except Exception as e:
                results[tx.filepath] = TransactionResult(
                    success=False,
                    filepath=tx.filepath,
                    error=str(e)
                )

        return results


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile
    import time

    print("=" * 60)
    print("Atomic I/O - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.txt"
        test_json = Path(tmpdir) / "test.json"
        test_ndjson = Path(tmpdir) / "test.ndjson"

        # Test 1: Basic atomic write
        print("\n=== Test 1: Basic Atomic Write ===")
        atomic_write(test_file, "Hello, World!")
        content = test_file.read_text()
        assert content == "Hello, World!", f"Expected 'Hello, World!', got '{content}'"
        print("   Wrote: 'Hello, World!'")
        print("   Read:  '{}'".format(content))
        print("   Result: PASS")

        # Test 2: Overwrite
        print("\n=== Test 2: Overwrite ===")
        atomic_write(test_file, "New content")
        content = test_file.read_text()
        assert content == "New content", f"Expected 'New content', got '{content}'"
        print("   Overwrote with: 'New content'")
        print("   Result: PASS")

        # Test 3: JSON write
        print("\n=== Test 3: JSON Write ===")
        data = {"key": "value", "number": 42, "nested": {"a": 1}}
        atomic_json_write(test_json, data)
        loaded = json.loads(test_json.read_text())
        assert loaded == data, f"JSON mismatch: {loaded}"
        print("   Wrote:", data)
        print("   Loaded:", loaded)
        print("   Result: PASS")

        # Test 4: NDJSON append
        print("\n=== Test 4: NDJSON Append ===")
        for i in range(3):
            atomic_ndjson_append(test_ndjson, {"event": f"test_{i}", "index": i})
        lines = test_ndjson.read_text().strip().split('\n')
        assert len(lines) == 3, f"Expected 3 lines, got {len(lines)}"
        print(f"   Appended 3 records")
        for line in lines:
            print(f"   - {line}")
        print("   Result: PASS")

        # Test 5: Context manager
        print("\n=== Test 5: Context Manager ===")
        ctx_file = Path(tmpdir) / "context.txt"
        with atomic_write_context(ctx_file) as f:
            f.write("Line 1\n")
            f.write("Line 2\n")
        content = ctx_file.read_text()
        assert "Line 1" in content and "Line 2" in content
        print("   Wrote via context manager")
        print("   Result: PASS")

        # Test 6: Context manager with exception (file should not be modified)
        print("\n=== Test 6: Context Manager Exception Safety ===")
        atomic_write(ctx_file, "Original")
        try:
            with atomic_write_context(ctx_file) as f:
                f.write("Modified")
                raise ValueError("Simulated error")
        except ValueError as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        content = ctx_file.read_text()
        assert content == "Original", f"Expected 'Original', got '{content}'"
        print("   Exception during write - file unchanged")
        print("   Result: PASS")

        # Test 7: Safe read with locking
        print("\n=== Test 7: Safe Read ===")
        content = safe_read(test_file)
        assert content == "New content"
        nonexistent = safe_read(Path(tmpdir) / "nonexistent.txt", default="default")
        assert nonexistent == "default"
        print("   Read existing file: OK")
        print("   Read nonexistent with default: OK")
        print("   Result: PASS")

        # Test 8: Safe JSON read
        print("\n=== Test 8: Safe JSON Read ===")
        loaded = safe_json_read(test_json)
        assert loaded == data
        nonexistent = safe_json_read(Path(tmpdir) / "nope.json", default={})
        assert nonexistent == {}
        print("   Read existing JSON: OK")
        print("   Read nonexistent with default: OK")
        print("   Result: PASS")

        # Test 9: Directory creation
        print("\n=== Test 9: Directory Creation ===")
        deep_file = Path(tmpdir) / "a" / "b" / "c" / "deep.txt"
        atomic_write(deep_file, "Deep content")
        assert deep_file.exists()
        assert deep_file.read_text() == "Deep content"
        print(f"   Created nested directory structure")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nAtomic I/O module is ready for integration!")

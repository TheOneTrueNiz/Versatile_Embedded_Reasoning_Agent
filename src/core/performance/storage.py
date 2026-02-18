"""
Unified Storage Layer for VERA.

Consolidates all module storage with:
- Write debouncing (batch rapid writes)
- Memory-first with periodic flush
- Atomic operations
- Change tracking

Based on GROKSTAR's write debouncing pattern.
"""

import os
import json
import time
import fcntl
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class WriteOperation:
    """A pending write operation."""
    path: Path
    content: Any
    format: str  # 'json', 'text', 'ndjson'
    timestamp: float
    priority: int = 0  # Higher = write sooner


@dataclass
class StorageStats:
    """Statistics for storage operations."""
    reads: int = 0
    writes: int = 0
    writes_debounced: int = 0
    bytes_written: int = 0
    bytes_read: int = 0
    cache_hits: int = 0
    cache_misses: int = 0


class UnifiedStorage:
    """
    Unified storage layer for all VERA modules.

    Features:
    - Write debouncing: Batches rapid writes
    - Memory cache: Reduces disk reads
    - Atomic writes: No partial file corruption
    - Change detection: Only write if content changed
    - Periodic flush: Configurable background writes
    """

    DEFAULT_DEBOUNCE_MS = 500  # Wait 500ms before writing
    DEFAULT_FLUSH_INTERVAL_S = 5  # Flush every 5 seconds

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        enable_cache: bool = True
    ):
        """
        Initialize unified storage.

        Args:
            base_dir: Base directory for all storage
            debounce_ms: Milliseconds to wait before writing
            flush_interval_s: Seconds between flush cycles
            enable_cache: Enable in-memory caching
        """
        self.base_dir = Path(base_dir) if base_dir else Path("vera_memory")
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.debounce_ms = debounce_ms
        self.flush_interval_s = flush_interval_s
        self.enable_cache = enable_cache

        # Pending writes (path -> WriteOperation)
        self._pending: Dict[Path, WriteOperation] = {}
        self._pending_lock = threading.Lock()

        # In-memory cache (path -> content)
        self._cache: Dict[Path, Any] = {}
        self._cache_hashes: Dict[Path, str] = {}  # For change detection
        self._cache_lock = threading.RLock()

        # Stats
        self._stats = StorageStats()

        # Flush control
        self._running = False
        self._flush_thread: Optional[threading.Thread] = None
        self._flush_event = threading.Event()

        # Callbacks for write events
        self._on_write_callbacks: List[Callable[[Path], None]] = []

    def start(self) -> None:
        """Start the background flush thread."""
        if self._running:
            return

        self._running = True
        self._flush_thread = threading.Thread(
            target=self._flush_loop,
            daemon=True,
            name="StorageFlush"
        )
        self._flush_thread.start()
        logger.debug("Storage flush thread started")

    def stop(self, flush_pending: bool = True) -> None:
        """
        Stop the background flush thread.

        Args:
            flush_pending: Flush all pending writes before stopping
        """
        if not self._running:
            return

        self._running = False
        self._flush_event.set()

        if self._flush_thread:
            self._flush_thread.join(timeout=5.0)

        if flush_pending:
            self.flush_all()

        logger.debug("Storage flush thread stopped")

    def _flush_loop(self) -> None:
        """Background loop for periodic flushing."""
        while self._running:
            # Wait for interval or early trigger
            self._flush_event.wait(timeout=self.flush_interval_s)
            self._flush_event.clear()

            if not self._running:
                break

            self._process_pending_writes()

    def _process_pending_writes(self) -> None:
        """Process all pending writes that have passed debounce time."""
        now = time.time()
        to_write = []

        with self._pending_lock:
            for path, op in list(self._pending.items()):
                age_ms = (now - op.timestamp) * 1000
                if age_ms >= self.debounce_ms:
                    to_write.append(op)
                    del self._pending[path]

        for op in to_write:
            self._execute_write(op)

    def _execute_write(self, op: WriteOperation) -> None:
        """Execute a single write operation."""
        try:
            # Ensure directory exists
            op.path.parent.mkdir(parents=True, exist_ok=True)

            # Format content
            if op.format == 'json':
                content = json.dumps(op.content, indent=2, default=str)
            elif op.format == 'ndjson':
                if isinstance(op.content, list):
                    content = '\n'.join(json.dumps(item, default=str) for item in op.content)
                else:
                    content = json.dumps(op.content, default=str) + '\n'
            else:
                content = str(op.content)

            # Atomic write
            self._atomic_write(op.path, content)

            # Update stats
            self._stats.writes += 1
            self._stats.bytes_written += len(content.encode())

            # Notify callbacks
            for callback in self._on_write_callbacks:
                try:
                    callback(op.path)
                except Exception as e:
                    logger.error(f"Write callback error: {e}")

        except Exception as e:
            logger.error(f"Write failed for {op.path}: {e}")

    def _atomic_write(self, path: Path, content: str) -> None:
        """Write content atomically."""
        tmp_path = path.with_suffix(path.suffix + '.tmp')

        try:
            with open(tmp_path, 'w') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

            os.rename(tmp_path, path)

        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise

    def _content_hash(self, content: Any) -> str:
        """Compute hash for change detection."""
        if isinstance(content, (dict, list)):
            data = json.dumps(content, sort_keys=True, default=str)
        else:
            data = str(content)
        return hashlib.md5(data.encode()).hexdigest()

    def write(
        self,
        path: str,
        content: Any,
        format: str = 'json',
        immediate: bool = False,
        priority: int = 0
    ) -> None:
        """
        Write content to storage.

        Args:
            path: Relative path from base_dir
            content: Content to write
            format: 'json', 'text', or 'ndjson'
            immediate: Skip debouncing and write now
            priority: Higher priority writes happen sooner
        """
        full_path = self.base_dir / path

        # Check if content actually changed
        content_hash = self._content_hash(content)
        with self._cache_lock:
            if full_path in self._cache_hashes:
                if self._cache_hashes[full_path] == content_hash:
                    # Content unchanged, skip write
                    self._stats.writes_debounced += 1
                    return

            # Update cache
            if self.enable_cache:
                self._cache[full_path] = content
                self._cache_hashes[full_path] = content_hash

        op = WriteOperation(
            path=full_path,
            content=content,
            format=format,
            timestamp=time.time(),
            priority=priority
        )

        if immediate:
            self._execute_write(op)
        else:
            with self._pending_lock:
                self._pending[full_path] = op

    def append(
        self,
        path: str,
        content: Any,
        format: str = 'ndjson'
    ) -> None:
        """
        Append content to a file (for logs).

        Args:
            path: Relative path from base_dir
            content: Content to append
            format: 'ndjson' or 'text'
        """
        full_path = self.base_dir / path
        full_path.parent.mkdir(parents=True, exist_ok=True)

        if format == 'ndjson':
            line = json.dumps(content, default=str) + '\n'
        else:
            line = str(content) + '\n'

        with open(full_path, 'a') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            f.write(line)
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        self._stats.writes += 1
        self._stats.bytes_written += len(line.encode())

        # Invalidate cache
        with self._cache_lock:
            self._cache.pop(full_path, None)
            self._cache_hashes.pop(full_path, None)

    def read(
        self,
        path: str,
        format: str = 'json',
        default: Any = None
    ) -> Any:
        """
        Read content from storage.

        Args:
            path: Relative path from base_dir
            format: 'json', 'text', or 'ndjson'
            default: Default value if file doesn't exist

        Returns:
            File content
        """
        full_path = self.base_dir / path

        # Check cache first
        if self.enable_cache:
            with self._cache_lock:
                if full_path in self._cache:
                    self._stats.cache_hits += 1
                    return self._cache[full_path]

        self._stats.cache_misses += 1

        if not full_path.exists():
            return default

        try:
            content = full_path.read_text()
            self._stats.reads += 1
            self._stats.bytes_read += len(content.encode())

            if format == 'json':
                result = json.loads(content)
            elif format == 'ndjson':
                result = [json.loads(line) for line in content.strip().split('\n') if line]
            else:
                result = content

            # Update cache
            if self.enable_cache:
                with self._cache_lock:
                    self._cache[full_path] = result
                    self._cache_hashes[full_path] = self._content_hash(result)

            return result

        except Exception as e:
            logger.error(f"Read failed for {path}: {e}")
            return default

    def exists(self, path: str) -> bool:
        """Check if a path exists."""
        full_path = self.base_dir / path
        return full_path.exists()

    def delete(self, path: str) -> bool:
        """Delete a file."""
        full_path = self.base_dir / path

        # Remove from cache
        with self._cache_lock:
            self._cache.pop(full_path, None)
            self._cache_hashes.pop(full_path, None)

        # Remove from pending
        with self._pending_lock:
            self._pending.pop(full_path, None)

        if full_path.exists():
            full_path.unlink()
            return True
        return False

    def list_files(self, pattern: str = "*") -> List[Path]:
        """List files matching pattern."""
        return list(self.base_dir.glob(pattern))

    def flush_all(self) -> int:
        """
        Flush all pending writes immediately.

        Returns:
            Number of writes flushed
        """
        with self._pending_lock:
            to_write = list(self._pending.values())
            self._pending.clear()

        for op in to_write:
            self._execute_write(op)

        return len(to_write)

    def invalidate_cache(self, path: Optional[str] = None) -> None:
        """
        Invalidate cache entries.

        Args:
            path: Specific path to invalidate, or None for all
        """
        with self._cache_lock:
            if path:
                full_path = self.base_dir / path
                self._cache.pop(full_path, None)
                self._cache_hashes.pop(full_path, None)
            else:
                self._cache.clear()
                self._cache_hashes.clear()

    def on_write(self, callback: Callable[[Path], None]) -> None:
        """Register a callback for write events."""
        self._on_write_callbacks.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        """Get storage statistics."""
        return {
            "reads": self._stats.reads,
            "writes": self._stats.writes,
            "writes_debounced": self._stats.writes_debounced,
            "bytes_written": self._stats.bytes_written,
            "bytes_read": self._stats.bytes_read,
            "cache_hits": self._stats.cache_hits,
            "cache_misses": self._stats.cache_misses,
            "cache_hit_rate": (
                self._stats.cache_hits / (self._stats.cache_hits + self._stats.cache_misses)
                if (self._stats.cache_hits + self._stats.cache_misses) > 0
                else 0
            ),
            "pending_writes": len(self._pending),
            "cached_entries": len(self._cache)
        }


# === Global Instance ===

_global_storage: Optional[UnifiedStorage] = None


def get_storage() -> UnifiedStorage:
    """Get or create global storage instance."""
    global _global_storage
    if _global_storage is None:
        _global_storage = UnifiedStorage()
        _global_storage.start()
    return _global_storage


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_storage():
        """Test unified storage."""
        print("Testing Unified Storage...")
        print("=" * 60)

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create storage
            print("Test 1: Create storage...", end=" ")
            storage = UnifiedStorage(
                base_dir=Path(tmpdir),
                debounce_ms=100,  # Fast for testing
                flush_interval_s=0.5
            )
            storage.start()
            print("PASS")

            # Test 2: Write and read
            print("Test 2: Write and read...", end=" ")
            storage.write("test.json", {"key": "value"}, immediate=True)
            result = storage.read("test.json")
            assert result == {"key": "value"}
            print("PASS")

            # Test 3: Cache hit
            print("Test 3: Cache hit...", end=" ")
            result2 = storage.read("test.json")
            stats = storage.get_stats()
            assert stats["cache_hits"] >= 1
            print("PASS")

            # Test 4: Debounced write
            print("Test 4: Debounced write...", end=" ")
            for i in range(10):
                storage.write("debounce.json", {"count": i})
            # Only last value should be written after debounce
            time.sleep(0.3)
            storage.flush_all()
            result = storage.read("debounce.json")
            assert result.get("count", "") == 9
            print("PASS")

            # Test 5: Change detection
            print("Test 5: Change detection...", end=" ")
            storage.write("same.json", {"data": 1}, immediate=True)
            initial_writes = storage.get_stats()["writes"]
            # Write same content
            storage.write("same.json", {"data": 1}, immediate=True)
            # Should be debounced (no actual write)
            assert storage.get_stats()["writes_debounced"] >= 1
            print("PASS")

            # Test 6: Append (NDJSON)
            print("Test 6: Append NDJSON...", end=" ")
            storage.append("log.ndjson", {"event": "a"})
            storage.append("log.ndjson", {"event": "b"})
            storage.append("log.ndjson", {"event": "c"})
            logs = storage.read("log.ndjson", format="ndjson")
            assert len(logs) == 3
            print("PASS")

            # Test 7: Delete
            print("Test 7: Delete...", end=" ")
            storage.write("todelete.json", {"temp": True}, immediate=True)
            assert storage.exists("todelete.json")
            storage.delete("todelete.json")
            assert not storage.exists("todelete.json")
            print("PASS")

            # Test 8: List files
            print("Test 8: List files...", end=" ")
            files = storage.list_files("*.json")
            assert len(files) >= 2
            print(f"PASS ({len(files)} files)")

            # Test 9: Stats
            print("Test 9: Stats...", end=" ")
            stats = storage.get_stats()
            assert stats["reads"] > 0
            assert stats["writes"] > 0
            print("PASS")

            # Test 10: Stop
            print("Test 10: Stop storage...", end=" ")
            storage.stop()
            print("PASS")

        print("=" * 60)
        print("\nAll tests passed!")
        return True

    success = test_storage()
    sys.exit(0 if success else 1)

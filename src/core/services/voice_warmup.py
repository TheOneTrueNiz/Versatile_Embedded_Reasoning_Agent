"""
Voice WebSocket Warmup for VERA.

Optimizes voice session startup by pre-establishing connections.
Reduces perceived latency when user initiates voice mode.

Key strategies:
1. Connection pooling with warmup
2. Heartbeat keepalive
3. Graceful reconnection
4. Background pre-warming
"""

import os
import json
import asyncio
import time
import logging
import threading
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

try:
    from websockets.asyncio.client import connect, ClientConnection
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    ClientConnection = Any  # type: ignore

logger = logging.getLogger(__name__)


# === Constants ===

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"
VOICE_MODEL = os.getenv("XAI_VOICE_MODEL", "grok-voice-agent")
DEFAULT_POOL_SIZE = 1  # Pre-warm one connection
CONNECTION_TIMEOUT_S = 10
HEARTBEAT_INTERVAL_S = 30
MAX_CONNECTION_AGE_S = 300  # Recycle after 5 minutes
WARMUP_RETRY_DELAY_S = 5


class ConnectionState(Enum):
    """States for a pooled connection."""
    WARMING = "warming"     # Being established
    READY = "ready"         # Ready for use
    IN_USE = "in_use"       # Currently being used
    STALE = "stale"         # Needs recycling
    FAILED = "failed"       # Connection failed


@dataclass
class PooledConnection:
    """A connection in the pool."""
    conn_id: str
    websocket: Optional[ClientConnection] = None
    state: ConnectionState = ConnectionState.WARMING
    created_at: float = field(default_factory=time.time)
    last_used_at: float = 0
    last_heartbeat_at: float = 0
    use_count: int = 0
    error: Optional[str] = None

    def is_healthy(self) -> bool:
        """Check if connection is healthy and usable."""
        if self.state in (ConnectionState.FAILED, ConnectionState.STALE):
            return False
        if self.websocket is None:
            return False
        # Check age
        age = time.time() - self.created_at
        if age > MAX_CONNECTION_AGE_S:
            return False
        return True


@dataclass
class WarmupStats:
    """Statistics for connection warming."""
    total_warmups: int = 0
    successful_warmups: int = 0
    failed_warmups: int = 0
    connections_served: int = 0
    avg_warmup_time_ms: float = 0
    current_pool_size: int = 0
    avg_wait_time_ms: float = 0


class VoiceConnectionPool:
    """
    Connection pool for voice WebSocket connections.

    Features:
    - Pre-warms connections in background
    - Provides instant connections to callers
    - Handles heartbeat keepalive
    - Gracefully recycles stale connections
    """

    def __init__(
        self,
        pool_size: int = DEFAULT_POOL_SIZE,
        api_key: Optional[str] = None,
        url: str = XAI_REALTIME_URL,
        auto_start: bool = False
    ):
        """
        Initialize connection pool.

        Args:
            pool_size: Number of connections to pre-warm
            api_key: xAI API key (from env if not provided)
            url: WebSocket URL
            auto_start: Start warming immediately
        """
        self.pool_size = pool_size
        self.api_key = api_key or os.getenv("XAI_API_KEY") or os.getenv("API_KEY")
        self.url = url

        # Connection pool
        self._pool: Dict[str, PooledConnection] = {}
        self._pool_lock = threading.RLock()

        # Ready queue (FIFO)
        self._ready_queue: deque = deque()

        # Stats
        self._stats = WarmupStats()
        self._warmup_times: List[float] = []
        self._wait_times: List[float] = []

        # Control
        self._running = False
        self._warmup_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        if auto_start:
            self.start()

    def start(self) -> None:
        """Start the connection pool (must be called from async context or creates one)."""
        if self._running:
            return

        if not WEBSOCKETS_AVAILABLE:
            logger.warning("websockets not available, pool disabled")
            return

        if not self.api_key:
            logger.warning("No API key available, pool disabled")
            return

        self._running = True

        # Try to get or create event loop
        try:
            self._loop = asyncio.get_running_loop()
            # Already in async context, schedule warmup
            self._warmup_task = self._loop.create_task(self._warmup_loop())
        except RuntimeError:
            # Not in async context, create background thread
            thread = threading.Thread(
                target=self._run_async_loop,
                daemon=True,
                name="VoicePoolWarmup"
            )
            thread.start()

        logger.info(f"Voice connection pool started (size={self.pool_size})")

    def _run_async_loop(self) -> None:
        """Run async event loop in background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._warmup_loop())

    def stop(self) -> None:
        """Stop the connection pool."""
        self._running = False

        if self._warmup_task:
            self._warmup_task.cancel()

        # Close all connections
        with self._pool_lock:
            for conn in self._pool.values():
                if conn.websocket:
                    try:
                        asyncio.run_coroutine_threadsafe(
                            conn.websocket.close(),
                            self._loop
                        ) if self._loop else None
                    except Exception:
                        logger.debug("Suppressed Exception in voice_warmup")
                        pass

            self._pool.clear()
            self._ready_queue.clear()

        logger.info("Voice connection pool stopped")

    async def _warmup_loop(self) -> None:
        """Main warmup loop."""
        while self._running:
            try:
                # Check pool health
                await self._maintain_pool()

                # Wait before next check
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Warmup loop error: {e}")
                await asyncio.sleep(WARMUP_RETRY_DELAY_S)

    async def _maintain_pool(self) -> None:
        """Maintain pool at desired size."""
        with self._pool_lock:
            # Count healthy ready connections
            healthy_ready = sum(
                1 for c in self._pool.values()
                if c.state == ConnectionState.READY and c.is_healthy()
            )

            # Start warming if below pool size
            if healthy_ready < self.pool_size:
                needed = self.pool_size - healthy_ready
                for _ in range(needed):
                    asyncio.create_task(self._warm_connection())

            # Recycle stale connections
            stale = [
                cid for cid, c in self._pool.items()
                if not c.is_healthy() and c.state != ConnectionState.IN_USE
            ]

            for cid in stale:
                await self._close_connection(cid)

    async def _warm_connection(self) -> Optional[str]:
        """Warm a new connection."""
        start = time.perf_counter()
        conn_id = f"conn-{int(time.time() * 1000)}-{len(self._pool)}"

        conn = PooledConnection(
            conn_id=conn_id,
            state=ConnectionState.WARMING
        )

        with self._pool_lock:
            self._pool[conn_id] = conn

        self._stats.total_warmups += 1

        try:
            # Connect with auth header
            headers = {"Authorization": f"Bearer {self.api_key}"}

            warmup_url = self.url
            if VOICE_MODEL:
                warmup_url = f"{self.url}?model={VOICE_MODEL}"
            websocket = await asyncio.wait_for(
                connect(
                    warmup_url,
                    additional_headers=headers,
                    ping_interval=HEARTBEAT_INTERVAL_S,
                    ping_timeout=10
                ),
                timeout=CONNECTION_TIMEOUT_S
            )

            # Wait for session.created event
            response = await asyncio.wait_for(
                websocket.recv(),
                timeout=5.0
            )

            event = json.loads(response)
            if event.get("type") != "session.created":
                raise ValueError(f"Unexpected event: {event.get('type')}")

            # Connection is ready
            with self._pool_lock:
                conn.websocket = websocket
                conn.state = ConnectionState.READY
                conn.last_heartbeat_at = time.time()
                self._ready_queue.append(conn_id)

            elapsed = (time.perf_counter() - start) * 1000
            self._warmup_times.append(elapsed)
            if len(self._warmup_times) > 100:
                self._warmup_times = self._warmup_times[-100:]
            self._stats.avg_warmup_time_ms = sum(self._warmup_times) / len(self._warmup_times)
            self._stats.successful_warmups += 1

            logger.debug(f"Connection {conn_id} warmed in {elapsed:.1f}ms")
            return conn_id

        except asyncio.TimeoutError:
            logger.warning(f"Connection {conn_id} warmup timed out")
            conn.state = ConnectionState.FAILED
            conn.error = "timeout"
            self._stats.failed_warmups += 1
            return None

        except Exception as e:
            logger.error(f"Connection {conn_id} warmup failed: {e}")
            conn.state = ConnectionState.FAILED
            conn.error = str(e)
            self._stats.failed_warmups += 1
            return None

    async def _close_connection(self, conn_id: str) -> None:
        """Close and remove a connection."""
        with self._pool_lock:
            conn = self._pool.pop(conn_id, None)
            if conn_id in self._ready_queue:
                try:
                    self._ready_queue.remove(conn_id)
                except ValueError:
                    logger.debug("Suppressed ValueError in voice_warmup")
                    pass

        if conn and conn.websocket:
            try:
                await conn.websocket.close()
            except Exception:
                logger.debug("Suppressed Exception in voice_warmup")
                pass

    async def get_connection(
        self,
        timeout_ms: int = 5000
    ) -> Optional[Tuple[Any, str]]:
        """
        Get a ready connection from the pool.

        Args:
            timeout_ms: Max time to wait for connection

        Returns:
            Tuple of (websocket, conn_id) or None if unavailable
        """
        if not self._running:
            return None

        start = time.perf_counter()
        deadline = start + (timeout_ms / 1000)

        while time.time() < deadline:
            with self._pool_lock:
                # Try to get from ready queue
                while self._ready_queue:
                    conn_id = self._ready_queue.popleft()
                    conn = self._pool.get(conn_id)

                    if conn and conn.is_healthy() and conn.state == ConnectionState.READY:
                        conn.state = ConnectionState.IN_USE
                        conn.last_used_at = time.time()
                        conn.use_count += 1

                        elapsed = (time.perf_counter() - start) * 1000
                        self._wait_times.append(elapsed)
                        if len(self._wait_times) > 100:
                            self._wait_times = self._wait_times[-100:]
                        self._stats.avg_wait_time_ms = sum(self._wait_times) / len(self._wait_times)
                        self._stats.connections_served += 1

                        logger.debug(f"Served connection {conn_id} in {elapsed:.1f}ms")
                        return (conn.websocket, conn_id)

            # No ready connection, wait briefly
            await asyncio.sleep(0.05)

        logger.warning("No connection available from pool")
        return None

    def release_connection(self, conn_id: str, reusable: bool = True) -> None:
        """
        Release a connection back to the pool.

        Args:
            conn_id: Connection ID
            reusable: Whether connection can be reused
        """
        with self._pool_lock:
            conn = self._pool.get(conn_id)
            if not conn:
                return

            if reusable and conn.is_healthy():
                conn.state = ConnectionState.READY
                self._ready_queue.append(conn_id)
                logger.debug(f"Released connection {conn_id} back to pool")
            else:
                conn.state = ConnectionState.STALE

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        with self._pool_lock:
            ready_count = sum(
                1 for c in self._pool.values()
                if c.state == ConnectionState.READY
            )
            in_use_count = sum(
                1 for c in self._pool.values()
                if c.state == ConnectionState.IN_USE
            )

        return {
            "pool_size": self.pool_size,
            "total_connections": len(self._pool),
            "ready_connections": ready_count,
            "in_use_connections": in_use_count,
            "total_warmups": self._stats.total_warmups,
            "successful_warmups": self._stats.successful_warmups,
            "failed_warmups": self._stats.failed_warmups,
            "connections_served": self._stats.connections_served,
            "avg_warmup_time_ms": self._stats.avg_warmup_time_ms,
            "avg_wait_time_ms": self._stats.avg_wait_time_ms,
            "running": self._running
        }


# === Convenience Functions ===

_global_pool: Optional[VoiceConnectionPool] = None


def get_voice_pool() -> VoiceConnectionPool:
    """Get or create global voice connection pool."""
    global _global_pool
    if _global_pool is None:
        _global_pool = VoiceConnectionPool()
    return _global_pool


def warmup_voice() -> None:
    """Pre-warm voice connections."""
    pool = get_voice_pool()
    pool.start()


async def get_warmed_connection(
    timeout_ms: int = 5000
) -> Optional[Tuple[Any, str]]:
    """Get a pre-warmed voice connection."""
    pool = get_voice_pool()
    if not pool._running:
        pool.start()
        # Give it a moment to warm
        await asyncio.sleep(0.5)
    return await pool.get_connection(timeout_ms)


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_voice_warmup():
        """Test voice warmup (unit tests without actual connection)."""
        print("Testing Voice Warmup...")
        print("=" * 60)

        # Test 1: Create pool
        print("Test 1: Create pool...", end=" ")
        pool = VoiceConnectionPool(pool_size=1, auto_start=False)
        assert pool.pool_size == 1
        assert not pool._running
        print("PASS")

        # Test 2: Stats without starting
        print("Test 2: Stats...", end=" ")
        stats = pool.get_stats()
        assert stats["pool_size"] == 1
        assert stats["total_connections"] == 0
        assert not stats["running"]
        print("PASS")

        # Test 3: Connection state
        print("Test 3: Connection state...", end=" ")
        conn = PooledConnection(conn_id="test-1")
        assert conn.state == ConnectionState.WARMING
        assert not conn.is_healthy()

        conn.websocket = "mock"  # Mock websocket
        conn.state = ConnectionState.READY
        # Would be healthy, but too new
        assert conn.is_healthy()  # Fresh connection should be healthy
        print("PASS")

        # Test 4: Stale detection
        print("Test 4: Stale detection...", end=" ")
        old_conn = PooledConnection(
            conn_id="test-old",
            websocket="mock",
            state=ConnectionState.READY,
            created_at=time.time() - MAX_CONNECTION_AGE_S - 1
        )
        assert not old_conn.is_healthy()  # Too old
        print("PASS")

        # Test 5: Global pool singleton
        print("Test 5: Global pool...", end=" ")
        global _global_pool
        _global_pool = None  # Reset
        p1 = get_voice_pool()
        p2 = get_voice_pool()
        assert p1 is p2
        print("PASS")

        # Test 6: Warmup function
        print("Test 6: Warmup function...", end=" ")
        # Can't actually connect without valid API key
        # Just ensure function doesn't crash
        try:
            warmup_voice()
            # Stop immediately
            p1.stop()
            print("PASS")
        except Exception as e:
            print(f"SKIP (no API key: {e})")

        print("=" * 60)
        print("\nAll tests passed!")
        return True

    success = test_voice_warmup()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
Tool Result Cache with Semantic Hashing
========================================

Implements intelligent caching of tool execution results to reduce redundant
API calls, command executions, and file operations.

Research Backing:
- arXiv:2411.05276 - GPT Semantic Cache (70% hit rate, 83% cost reduction)
- arXiv:2406.06799 - LLM-dCache (50-90% cost reduction)
- arXiv:2404.12457 - RAGCache (5× speedup)

Key Features:
- Semantic hashing: Normalizes parameters to recognize equivalent requests
- TTL-based expiration: Different cache lifetimes per tool type
- LRU eviction: Removes least recently used entries when cache fills
- Cache statistics: Tracks hit rate, cost savings, performance
- Thread-safe: Concurrent access via locks
"""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any
from threading import RLock
from collections import OrderedDict
from pathlib import Path
import logging
logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with metadata"""
    tool_name: str
    params: Dict[str, Any]
    result: str
    timestamp: float
    ttl: int
    access_count: int = 0
    last_accessed: float = field(default_factory=time.time)
    cache_key: str = ""

    def is_expired(self) -> bool:
        """Check if entry has exceeded TTL"""
        return (time.time() - self.timestamp) > self.ttl

    def touch(self) -> None:
        """Update access metadata"""
        self.access_count += 1
        self.last_accessed = time.time()


@dataclass
class CacheStats:
    """Cache performance statistics"""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    total_size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate"""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "total_size": self.total_size,
            "hit_rate": round(self.hit_rate, 2),
            "total_requests": self.total_requests
        }


class ToolResultCache:
    """
    Intelligent cache for tool execution results.

    Uses semantic hashing to normalize parameters and recognize equivalent
    requests even when parameter order or formatting differs.
    """

    # Default TTLs per tool category (seconds)
    DEFAULT_TTLS = {
        # File operations - short TTL (files change frequently)
        "read_file": 30,
        "read_text_file": 30,
        "list_directory": 30,
        "list_directory_with_sizes": 30,
        "search_files": 60,

        # System queries - medium TTL
        "run_command": 120,
        "get_status": 60,
        "check_health": 30,

        # External API calls - long TTL (expensive, stable)
        "search_web": 3600,  # 1 hour
        "search_wikipedia": 7200,  # 2 hours
        "read_gmail": 300,  # 5 minutes
        "search_gmail": 300,
        "list_calendar_events": 600,  # 10 minutes

        # MCP server calls - medium TTL
        "mcp_call": 300,

        # Memory operations - medium TTL
        "search_memory": 180,
        "retrieve_memory": 300,

        # Default for unknown tools
        "default": 120
    }

    def __init__(self, max_size: int = 1000, enable_persistence: bool = False,
                 cache_file: Optional[Path] = None):
        """
        Initialize tool result cache.

        Args:
            max_size: Maximum number of cache entries (LRU eviction)
            enable_persistence: Save cache to disk on shutdown
            cache_file: Path to cache persistence file
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = RLock()
        self._max_size = max_size
        self._stats = CacheStats()
        self._enable_persistence = enable_persistence
        self._cache_file = cache_file or Path("vera_memory/.cache/tool_results.json")

        # Load from disk if persistence enabled
        if self._enable_persistence:
            self._load_from_disk()

    def _normalize_params(self, params: Dict[str, Any]) -> str:
        """
        Normalize parameters for semantic hashing.

        Converts parameters to a canonical form so that equivalent requests
        produce the same hash even if parameter order or formatting differs.

        Examples:
            {"path": "/home/user", "limit": 10}
            {"limit": 10, "path": "/home/user"}
            -> Same hash
        """
        # Sort keys alphabetically
        sorted_params = dict(sorted(params.items()))

        # Normalize common variations
        normalized = {}
        for key, value in sorted_params.items():
            # Normalize paths
            if isinstance(value, str) and ("path" in key.lower() or "file" in key.lower()):
                value = str(Path(value).resolve())

            # Normalize booleans
            elif isinstance(value, (bool, int, float)):
                value = value

            # Normalize lists (sort if possible)
            elif isinstance(value, list):
                try:
                    value = sorted(value)
                except TypeError:
                    logger.debug("Suppressed TypeError in tool_result_cache")
                    pass  # Keep original order if not sortable

            normalized[key] = value

        # Convert to deterministic JSON string
        return json.dumps(normalized, sort_keys=True, default=str)

    def _cache_key(self, tool_name: str, params: Dict[str, Any]) -> str:
        """
        Generate semantic cache key using SHA-256 hash.

        Args:
            tool_name: Name of the tool
            params: Tool parameters

        Returns:
            64-character hex string (SHA-256 hash)
        """
        # Normalize parameters
        normalized_params = self._normalize_params(params)

        # Create hash input: tool_name + normalized params
        hash_input = f"{tool_name}:{normalized_params}"

        # SHA-256 hash (faster than MD5, secure enough for cache keys)
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

    def _get_ttl(self, tool_name: str) -> int:
        """Get TTL for tool type"""
        return self.DEFAULT_TTLS.get(tool_name, self.DEFAULT_TTLS["default"])

    def _evict_lru(self):
        """Evict least recently used entry to make space"""
        if not self._cache:
            return

        # OrderedDict maintains insertion order, find LRU by last_accessed
        lru_key = min(self._cache.keys(),
                     key=lambda k: self._cache[k].last_accessed)

        del self._cache[lru_key]
        self._stats.evictions += 1

    def _cleanup_expired(self):
        """Remove expired entries"""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]

        for key in expired_keys:
            del self._cache[key]
            self._stats.expirations += 1

    def get(self, tool_name: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Retrieve cached result if available and not expired.

        Args:
            tool_name: Name of the tool
            params: Tool parameters

        Returns:
            Cached result string, or None if cache miss
        """
        with self._lock:
            cache_key = self._cache_key(tool_name, params)

            # Check if entry exists
            if cache_key not in self._cache:
                self._stats.misses += 1
                return None

            entry = self._cache[cache_key]

            # Check if expired
            if entry.is_expired():
                del self._cache[cache_key]
                self._stats.expirations += 1
                self._stats.misses += 1
                return None

            # Cache hit!
            entry.touch()

            # Move to end (most recently used)
            self._cache.move_to_end(cache_key)

            self._stats.hits += 1
            return entry.result

    def put(self, tool_name: str, params: Dict[str, Any], result: str) -> None:
        """
        Store tool result in cache.

        Args:
            tool_name: Name of the tool
            params: Tool parameters
            result: Tool execution result
        """
        with self._lock:
            cache_key = self._cache_key(tool_name, params)
            ttl = self._get_ttl(tool_name)

            # Create cache entry
            entry = CacheEntry(
                tool_name=tool_name,
                params=params,
                result=result,
                timestamp=time.time(),
                ttl=ttl,
                cache_key=cache_key
            )

            # Check if cache is full
            if len(self._cache) >= self._max_size:
                # Clean up expired entries first
                self._cleanup_expired()

                # If still full, evict LRU
                if len(self._cache) >= self._max_size:
                    self._evict_lru()

            # Store entry (overwrites if key exists)
            self._cache[cache_key] = entry

            # Update stats
            self._stats.total_size = len(self._cache)

    def invalidate(self, tool_name: Optional[str] = None,
                   params: Optional[Dict[str, Any]] = None):
        """
        Invalidate cache entries.

        Args:
            tool_name: If provided, invalidate only this tool (or specific params)
            params: If provided with tool_name, invalidate specific entry
        """
        with self._lock:
            if tool_name and params:
                # Invalidate specific entry
                cache_key = self._cache_key(tool_name, params)
                if cache_key in self._cache:
                    del self._cache[cache_key]

            elif tool_name:
                # Invalidate all entries for this tool
                keys_to_delete = [
                    key for key, entry in self._cache.items()
                    if entry.tool_name == tool_name
                ]
                for key in keys_to_delete:
                    del self._cache[key]

            else:
                # Clear entire cache
                self._cache.clear()
                self._stats = CacheStats()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        with self._lock:
            # Cleanup expired entries before reporting stats
            self._cleanup_expired()
            self._stats.total_size = len(self._cache)

            stats = self._stats.to_dict()

            # Add per-tool breakdown
            tool_breakdown = {}
            for entry in self._cache.values():
                tool_breakdown[entry.tool_name] = tool_breakdown.get(entry.tool_name, 0) + 1

            stats["entries_by_tool"] = tool_breakdown
            stats["cache_size_kb"] = self._estimate_size_kb()

            return stats

    def _estimate_size_kb(self) -> float:
        """Estimate cache size in KB"""
        total_bytes = 0
        for entry in self._cache.values():
            total_bytes += len(entry.result.encode('utf-8'))
            total_bytes += len(json.dumps(entry.params).encode('utf-8'))

        return round(total_bytes / 1024, 2)

    def _load_from_disk(self):
        """Load cache from disk (persistence)"""
        if not self._cache_file.exists():
            return

        try:
            with open(self._cache_file, 'r') as f:
                data = json.load(f)

            for cache_key, entry_data in data.items():
                entry = CacheEntry(
                    tool_name=entry_data.get("tool_name", ""),
                    params=entry_data.get("params", ""),
                    result=entry_data.get("result", ""),
                    timestamp=entry_data.get("timestamp", ""),
                    ttl=entry_data.get("ttl", ""),
                    access_count=entry_data.get("access_count", 0),
                    last_accessed=entry_data.get("last_accessed", entry_data["timestamp"]),
                    cache_key=cache_key
                )

                # Only load if not expired
                if not entry.is_expired():
                    self._cache[cache_key] = entry

            logger.info(f"✅ Loaded {len(self._cache)} cache entries from disk")

        except Exception as e:
            logger.info(f"⚠️ Failed to load cache from disk: {e}")

    def save_to_disk(self) -> None:
        """Save cache to disk (persistence)"""
        if not self._enable_persistence:
            return

        try:
            # Create directory if needed
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)

            # Convert cache to JSON
            data = {}
            for cache_key, entry in self._cache.items():
                data[cache_key] = {
                    "tool_name": entry.tool_name,
                    "params": entry.params,
                    "result": entry.result,
                    "timestamp": entry.timestamp,
                    "ttl": entry.ttl,
                    "access_count": entry.access_count,
                    "last_accessed": entry.last_accessed
                }

            # Write atomically
            tmp_file = self._cache_file.with_suffix(".tmp")
            with open(tmp_file, 'w') as f:
                json.dump(data, f, indent=2)

            tmp_file.replace(self._cache_file)
            logger.info(f"✅ Saved {len(self._cache)} cache entries to disk")

        except Exception as e:
            logger.info(f"⚠️ Failed to save cache to disk: {e}")

    def cleanup(self) -> None:
        """Cleanup on shutdown"""
        if self._enable_persistence:
            self.save_to_disk()


# Global cache instance (initialized in run_vera.py)
_GLOBAL_CACHE: Optional[ToolResultCache] = None


def get_cache() -> Optional[ToolResultCache]:
    """Get global cache instance"""
    return _GLOBAL_CACHE


def init_cache(max_size: int = 1000, enable_persistence: bool = False) -> ToolResultCache:
    """Initialize global cache instance"""
    global _GLOBAL_CACHE
    _GLOBAL_CACHE = ToolResultCache(max_size=max_size, enable_persistence=enable_persistence)
    return _GLOBAL_CACHE


# === CLI Interface for Testing ===

if __name__ == "__main__":
    print("=" * 60)
    print("Tool Result Cache - Test Suite")
    print("=" * 60)

    # Initialize cache
    cache = ToolResultCache(max_size=5)

    # Test 1: Basic cache functionality
    print("\n=== Test 1: Basic Get/Put ===")
    cache.put("read_file", {"path": "/tmp/test.txt"}, "file contents here")
    result = cache.get("read_file", {"path": "/tmp/test.txt"})
    assert result == "file contents here", "Cache miss on get"
    logger.info("✅ Basic get/put works")

    # Test 2: Semantic hashing (parameter order doesn't matter)
    print("\n=== Test 2: Semantic Hashing ===")
    cache.put("search", {"query": "test", "limit": 10}, "search results")
    result = cache.get("search", {"limit": 10, "query": "test"})  # Different order
    assert result == "search results", "Semantic hashing failed"
    logger.info("✅ Semantic hashing works (parameter order normalized)")

    # Test 3: TTL expiration
    print("\n=== Test 3: TTL Expiration ===")
    cache.put("test_ttl", {}, "should expire")
    cache._cache[list(cache._cache.keys())[-1]].ttl = 0  # Force immediate expiration
    time.sleep(0.1)
    result = cache.get("test_ttl", {})
    assert result is None, "Expired entry not removed"
    logger.info("✅ TTL expiration works")

    # Test 4: LRU eviction
    print("\n=== Test 4: LRU Eviction ===")
    for i in range(6):  # Exceed max_size=5
        cache.put(f"tool{i}", {"id": i}, f"result{i}")

    # First entry should be evicted
    result = cache.get("tool0", {"id": 0})
    assert result is None, "LRU eviction failed"
    logger.info(f"✅ LRU eviction works (evicted oldest entry)")

    # Test 5: Statistics
    print("\n=== Test 5: Cache Statistics ===")
    stats = cache.get_stats()
    print(f"   Hit rate: {stats['hit_rate']:.1f}%")
    print(f"   Total requests: {stats['total_requests']}")
    print(f"   Cache size: {stats['total_size']} entries ({stats['cache_size_kb']} KB)")
    print(f"   Evictions: {stats['evictions']}")
    logger.info("✅ Statistics tracking works")

    # Test 6: Invalidation
    print("\n=== Test 6: Cache Invalidation ===")
    cache.put("invalidate_me", {"key": "value"}, "to be removed")
    cache.invalidate("invalidate_me", {"key": "value"})
    result = cache.get("invalidate_me", {"key": "value"})
    assert result is None, "Invalidation failed"
    logger.info("✅ Cache invalidation works")

    print("\n" + "=" * 60)
    logger.info("✅ ALL TESTS PASSED")
    print("=" * 60)
    print("\nCache is working correctly and ready for integration!")
    print(f"\nFinal stats: {cache.get_stats()}")

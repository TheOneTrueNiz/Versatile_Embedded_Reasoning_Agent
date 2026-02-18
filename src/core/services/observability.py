#!/usr/bin/env python3
"""
VERA Observability
==================

Monitoring and metrics collection for VERA system.

Based on:
- AgentSight: <3% overhead
- AgentOps: Production monitoring
- OpenTelemetry standards
"""

import time
from typing import Dict, Any
import logging
logger = logging.getLogger(__name__)


class VERAObservability:
    """
    Observability and monitoring

    Tracks:
    - Event pipeline metrics
    - Tool execution stats
    - Cache performance
    - System health indicators
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.metrics = {}
        self.traces = []
        self.start_time = time.time()

        if enabled:
            self._init_metrics()

    def _init_metrics(self):
        """Initialize metrics collectors"""
        self.metrics = {
            # Event pipeline
            "events_total": 0,
            "events_fast_network": 0,
            "events_slow_network": 0,
            "events_archived": 0,

            # Tool execution
            "tools_invoked": 0,
            "tools_succeeded": 0,
            "tools_failed": 0,

            # Cache
            "cache_lookups": 0,
            "cache_hits": 0,
            "cache_misses": 0,

            # Performance
            "avg_event_latency_ms": 0.0,
            "avg_consolidation_time_ms": 0.0,
            "avg_cache_lookup_ms": 0.0,

            # Health
            "errors_total": 0,
            "warnings_total": 0,
        }

    def record_event(self, event_type: str, **kwargs) -> None:
        """Record an event"""
        if not self.enabled:
            return

        self.metrics["events_total"] += 1

        if event_type == "fast_network":
            self.metrics["events_fast_network"] += 1
        elif event_type == "slow_network":
            self.metrics["events_slow_network"] += 1
        elif event_type == "archived":
            self.metrics["events_archived"] += 1

    def record_tool(self, tool_name: str, success: bool, duration_ms: float) -> None:
        """Record tool execution"""
        if not self.enabled:
            return

        self.metrics["tools_invoked"] += 1

        if success:
            self.metrics["tools_succeeded"] += 1
        else:
            self.metrics["tools_failed"] += 1

    def record_cache(self, hit: bool, duration_ms: float = 0.0) -> None:
        """Record cache lookup"""
        if not self.enabled:
            return

        self.metrics["cache_lookups"] += 1

        if hit:
            self.metrics["cache_hits"] += 1
        else:
            self.metrics["cache_misses"] += 1

        # Update avg
        lookups = self.metrics["cache_lookups"]
        current_avg = self.metrics["avg_cache_lookup_ms"]
        self.metrics["avg_cache_lookup_ms"] = (current_avg * (lookups - 1) + duration_ms) / lookups

    def record_cache_lookup(self, hit: bool, duration_ms: float = 0.0) -> None:
        """Alias for record_cache"""
        self.record_cache(hit, duration_ms)

    def get_stats(self) -> Dict[str, Any]:
        """Get current statistics"""
        if not self.enabled:
            return {}

        stats = self.metrics.copy()

        # Add derived metrics
        if stats["cache_lookups"] > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / stats["cache_lookups"]
        else:
            stats["cache_hit_rate"] = 0.0

        if stats["tools_invoked"] > 0:
            stats["tool_success_rate"] = stats["tools_succeeded"] / stats["tools_invoked"]
        else:
            stats["tool_success_rate"] = 0.0

        stats["uptime_seconds"] = time.time() - self.start_time

        return stats

    def print_stats(self) -> None:
        """Print statistics summary"""
        if not self.enabled:
            return

        stats = self.get_stats()

        print("\n" + "=" * 60)
        print("VERA Observability Statistics")
        print("=" * 60)

        print(f"\nEvents:")
        print(f"  Total: {stats['events_total']}")
        print(f"  FastNetwork: {stats['events_fast_network']}")
        print(f"  SlowNetwork: {stats['events_slow_network']}")
        print(f"  Archived: {stats['events_archived']}")

        print(f"\nTools:")
        print(f"  Invoked: {stats['tools_invoked']}")
        print(f"  Success rate: {stats['tool_success_rate']:.1%}")

        print(f"\nCache:")
        print(f"  Lookups: {stats['cache_lookups']}")
        print(f"  Hit rate: {stats['cache_hit_rate']:.1%}")
        print(f"  Avg latency: {stats['avg_cache_lookup_ms']:.2f}ms")

        print(f"\nHealth:")
        logger.error(f"  Errors: {stats['errors_total']}")
        logger.warning(f"  Warnings: {stats['warnings_total']}")
        print(f"  Uptime: {stats['uptime_seconds']:.0f}s")

        print("=" * 60 + "\n")

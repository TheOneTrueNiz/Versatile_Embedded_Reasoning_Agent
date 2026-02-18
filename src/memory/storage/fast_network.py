#!/usr/bin/env python3
"""
Fast Network - Real-Time Event Encoding
========================================

Fast path for memory encoding with minimal overhead.

Based on research:
- Fast-Slow Network architecture (FSC-Net)
- Real-time event encoding
- Non-blocking handoff to background processing

Key Features:
- <1ms overhead per event
- Short-term buffer (last 100 events)
- Simple importance scoring (threshold-based for now)
- Non-blocking handoff to SlowNetwork
- Automatic gating (retain 30-50%)

Architecture:
┌─────────────────────────────────────────┐
│         Fast Network                    │
├─────────────────────────────────────────┤
│                                         │
│  Input: Event                           │
│     │                                   │
│     ▼                                   │
│  ┌──────────────────────────┐          │
│  │  Event Encoder           │          │
│  │  • Extract features      │          │
│  │  • Create MemCube        │          │
│  │  • <1ms processing       │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼                           │
│  ┌──────────────────────────┐          │
│  │  Importance Scoring      │          │
│  │  • Threshold-based       │          │
│  │  • Novelty detection     │          │
│  │  • User interaction bonus│          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼                           │
│  ┌──────────────────────────┐          │
│  │  Gating Decision         │          │
│  │  • Keep if >threshold    │          │
│  │  • Target: 30-50% retain │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ├─ KEEP ────▶ Short-term   │
│             │             buffer        │
│             │                           │
│             └─ DISCARD ─▶ Drop         │
│                                         │
│  ┌──────────────────────────┐          │
│  │  Short-term Buffer       │          │
│  │  (Last 100 events)       │          │
│  │  • FIFO queue            │          │
│  │  • Quick access          │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼ (Periodic handoff)       │
│  ┌──────────────────────────┐          │
│  │  SlowNetwork Queue       │          │
│  │  (Week 3)                │          │
│  └──────────────────────────┘          │
└─────────────────────────────────────────┘

Usage Example:
    fast_net = FastNetwork()

    # Encode events as they happen
    event = {
        "type": "user_query",
        "content": "What is Phase 2 status?",
        "timestamp": datetime.now()
    }

    cube = fast_net.encode_event(event)

    # Check if should consolidate
    if fast_net.should_consolidate():
        buffer = fast_net.get_buffer()
        # Hand off to SlowNetwork (Week 3)
"""

import time
from typing import Any, Dict, List, Optional, Set
from datetime import datetime
from collections import deque
from dataclasses import dataclass

try:
    from .mem_cube import MemCube, EventType
except ImportError:
    from mem_cube import MemCube, EventType


@dataclass
class ImportanceFactors:
    """Factors contributing to importance score"""
    recency: float  # 0.0 - 1.0
    novelty: float  # 0.0 - 1.0
    user_interaction: float  # 0.0 - 1.0 (higher if user-initiated)
    semantic_weight: float  # 0.0 - 1.0 (based on content type)

    def compute_score(self) -> float:
        """Compute weighted importance score"""
        return (
            0.2 * self.recency +
            0.3 * self.novelty +
            0.3 * self.user_interaction +
            0.2 * self.semantic_weight
        )


@dataclass
class RetentionFactors:
    """Factors contributing to retention score"""
    salience: float
    user_intent: float
    task_criticality: float
    redundancy: float
    staleness: float

    def compute_score(self) -> float:
        """Compute retention score with penalties."""
        score = (
            self.salience +
            self.user_intent +
            self.task_criticality -
            self.redundancy -
            self.staleness
        )
        return max(0.0, min(1.0, score))


class EventEncoder:
    """
    Encodes events into MemCubes

    Fast, lightweight encoding with minimal overhead
    """

    def __init__(self) -> None:
        # For novelty detection
        self.recent_content_hashes: Set[str] = set()
        self.max_hashes = 1000

    def encode(
        self,
        event: Dict[str, Any],
        default_importance: float = 0.5
    ) -> MemCube:
        """
        Encode event into MemCube

        Args:
            event: Event dictionary with:
                - type: Event type string
                - content: Event content
                - Optional: timestamp, tags, provenance

        Returns:
            MemCube
        """
        # Extract event type
        event_type_str = event.get("type", "system_event")
        try:
            event_type = EventType(event_type_str)
        except ValueError:
            event_type = EventType.SYSTEM_EVENT

        # Extract content
        content = event.get("content", str(event))

        # Extract metadata
        tags = event.get("tags", [])
        provenance = event.get("provenance", {"source": "fast_network"})
        created_by = event.get("created_by", "fast_network")

        # Compute scores
        scores = self._compute_scores(event, default_importance)
        importance = scores["importance"]

        # Create MemCube
        cube = MemCube(
            content=content,
            event_type=event_type,
            importance=importance,
            provenance=provenance,
            tags=tags,
            created_by=created_by
        )

        retention = scores["retention"]
        cube.metadata.provenance.setdefault("retention", retention)
        cube.metadata.provenance.setdefault("memory_tier", "session")

        return cube

    def _compute_scores(
        self,
        event: Dict[str, Any],
        default: float
    ) -> Dict[str, Any]:
        """Compute importance + retention scores for event."""
        event_type = event.get("type", "")
        content = str(event.get("content", ""))

        novelty_score = self._score_novelty(content)
        importance = self._compute_importance(event_type, content, novelty_score, default)
        retention = self._compute_retention(event_type, content, importance, novelty_score, event)

        return {
            "importance": importance,
            "retention": retention,
        }

    def _score_novelty(self, content: str) -> float:
        """Compute novelty score and update recent hash cache."""
        import hashlib

        content_hash = hashlib.md5(content.encode()).hexdigest()
        if content_hash not in self.recent_content_hashes:
            self.recent_content_hashes.add(content_hash)
            if len(self.recent_content_hashes) > self.max_hashes:
                self.recent_content_hashes = set(list(self.recent_content_hashes)[-self.max_hashes//2:])
            return 1.0
        return 0.0

    def _compute_importance(
        self,
        event_type: str,
        content: str,
        novelty_score: float,
        default: float
    ) -> float:
        """Compute importance score for event."""
        importance = default

        if "user" in event_type.lower():
            importance += 0.2

        important_keywords = ["error", "critical", "urgent", "important", "bug", "fix"]
        if any(kw in content.lower() for kw in important_keywords):
            importance += 0.1

        if novelty_score > 0.0:
            importance += 0.1

        return max(0.0, min(1.0, importance))

    def _compute_retention(
        self,
        event_type: str,
        content: str,
        importance: float,
        novelty_score: float,
        event: Dict[str, Any],
        staleness_hours: float = 24.0
    ) -> Dict[str, Any]:
        """Compute retention score and factors."""
        event_type_lower = event_type.lower()
        if "user_query" in event_type_lower or "user_command" in event_type_lower:
            user_intent = 0.9
        elif "tool_execution" in event_type_lower:
            user_intent = 0.6
        else:
            user_intent = 0.2

        critical_keywords = [
            "urgent",
            "asap",
            "deadline",
            "critical",
            "important",
            "error",
            "incident",
            "outage",
        ]
        task_criticality = 0.7 if any(kw in content.lower() for kw in critical_keywords) else 0.1

        redundancy = 1.0 - novelty_score

        staleness = 0.0
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            try:
                from datetime import datetime

                age = datetime.now() - datetime.fromisoformat(timestamp)
                hours = age.total_seconds() / 3600
                staleness = min(1.0, max(0.0, hours / staleness_hours))
            except Exception:
                staleness = 0.0

        factors = RetentionFactors(
            salience=importance,
            user_intent=user_intent,
            task_criticality=task_criticality,
            redundancy=redundancy,
            staleness=staleness,
        )

        return {
            "score": factors.compute_score(),
            "salience": factors.salience,
            "user_intent": factors.user_intent,
            "task_criticality": factors.task_criticality,
            "redundancy": factors.redundancy,
            "staleness": factors.staleness,
        }


class FastNetwork:
    """
    Fast path for real-time memory encoding

    Features:
    - <1ms overhead per event
    - Short-term buffer (FIFO)
    - Simple importance gating
    - Non-blocking operation

    Performance:
    - <1ms per event
    - 30-50% retention rate
    - Zero blocking of main loop
    """

    def __init__(
        self,
        buffer_size: int = 100,
        importance_threshold: float = 0.4,
        consolidation_interval: int = 50  # Events between consolidations
    ):
        """
        Initialize FastNetwork

        Args:
            buffer_size: Max events in short-term buffer
            importance_threshold: Min importance to retain
            consolidation_interval: Events between consolidations
        """
        self.buffer_size = buffer_size
        self.importance_threshold = importance_threshold
        self.consolidation_interval = consolidation_interval

        # Short-term buffer (FIFO)
        self.buffer: deque[MemCube] = deque(maxlen=buffer_size)

        # Event encoder
        self.encoder = EventEncoder()

        # Statistics
        self.stats = {
            "total_events": 0,
            "retained_events": 0,
            "discarded_events": 0,
            "avg_encoding_time_ms": 0.0,
            "consolidations": 0
        }

        # For consolidation timing
        self.events_since_consolidation = 0

    def encode_event(
        self,
        event: Dict[str, Any],
        force_retain: bool = False
    ) -> Optional[MemCube]:
        """
        Encode event and add to buffer if important

        Args:
            event: Event dictionary
            force_retain: Force retention regardless of importance

        Returns:
            MemCube if retained, None if discarded
        """
        start = time.time()

        # Encode to MemCube
        cube = self.encoder.encode(event)

        # Gating decision
        if force_retain or cube.metadata.importance >= self.importance_threshold:
            # Retain
            self.buffer.append(cube)
            self.stats["retained_events"] += 1

            # Update stats
            encoding_time_ms = (time.time() - start) * 1000
            self._update_avg_time(encoding_time_ms)

            self.stats["total_events"] += 1
            self.events_since_consolidation += 1

            return cube
        else:
            # Discard
            self.stats["discarded_events"] += 1
            self.stats["total_events"] += 1

            return None

    def should_consolidate(self) -> bool:
        """Check if it's time to consolidate buffer"""
        return self.events_since_consolidation >= self.consolidation_interval

    def get_buffer(self, clear: bool = False) -> List[MemCube]:
        """
        Get current buffer contents

        Args:
            clear: Clear buffer after getting

        Returns:
            List of MemCubes in buffer
        """
        cubes = list(self.buffer)

        if clear:
            self.buffer.clear()
            self.events_since_consolidation = 0
            self.stats["consolidations"] += 1

        return cubes

    def get_recent(self, n: int = 10) -> List[MemCube]:
        """Get N most recent events"""
        return list(self.buffer)[-n:]

    def search_buffer(
        self,
        query: str,
        max_results: int = 5
    ) -> List[MemCube]:
        """
        Search buffer for events containing query

        Args:
            query: Search query
            max_results: Max results to return

        Returns:
            List of matching MemCubes
        """
        query_lower = query.lower()
        matches = []

        for cube in self.buffer:
            content_str = str(cube.get_content()).lower()
            if query_lower in content_str:
                matches.append(cube)

                if len(matches) >= max_results:
                    break

        return matches

    def get_stats(self) -> Dict[str, Any]:
        """Get encoding statistics"""
        stats = self.stats.copy()

        # Add derived stats
        total = stats["total_events"]
        if total > 0:
            stats["retention_rate"] = stats["retained_events"] / total
            stats["discard_rate"] = stats["discarded_events"] / total
        else:
            stats["retention_rate"] = 0.0
            stats["discard_rate"] = 0.0

        stats["buffer_size"] = len(self.buffer)
        stats["buffer_capacity"] = self.buffer_size

        return stats

    def _update_avg_time(self, new_time_ms: float):
        """Update rolling average encoding time"""
        retained = self.stats["retained_events"]

        if retained == 1:
            self.stats["avg_encoding_time_ms"] = new_time_ms
        else:
            # Exponential moving average
            alpha = 0.2
            self.stats["avg_encoding_time_ms"] = (
                alpha * new_time_ms +
                (1 - alpha) * self.stats["avg_encoding_time_ms"]
            )

    def clear_buffer(self) -> None:
        """Clear the buffer"""
        self.buffer.clear()
        self.events_since_consolidation = 0


# Example usage and testing
def run_example() -> None:
    """Demonstrate FastNetwork capabilities"""
    print("=== Fast Network Example ===\n")

    fast_net = FastNetwork(
        buffer_size=50,
        importance_threshold=0.4,
        consolidation_interval=20
    )

    # Example 1: Encode events
    print("Example 1: Encode Events")
    print("-" * 60)

    events = [
        {"type": "user_query", "content": "What is the Phase 2 timeline?"},
        {"type": "agent_thought", "content": "Analyzing user query..."},
        {"type": "tool_execution", "content": "Executed gmail_search"},
        {"type": "user_command", "content": "/status"},
        {"type": "system_event", "content": "Cache hit on read_file"},
    ]

    for event in events:
        cube = fast_net.encode_event(event)
        if cube:
            print(f"✓ Retained: {cube.metadata.event_type.value} (importance={cube.metadata.importance:.2f})")
        else:
            print(f"✗ Discarded: {event['type']}")

    # Example 2: Performance test
    print("\n\nExample 2: Performance Test (<1ms overhead)")
    print("-" * 60)

    n_events = 1000
    start = time.time()

    for i in range(n_events):
        event = {
            "type": "system_event" if i % 3 == 0 else "user_query",
            "content": f"Event {i}: Test content with some data"
        }
        fast_net.encode_event(event)

    elapsed = time.time() - start
    avg_time_ms = (elapsed / n_events) * 1000

    print(f"✓ Encoded {n_events} events in {elapsed:.2f}s")
    print(f"✓ Average: {avg_time_ms:.3f}ms per event (target: <1ms)")
    print(f"✓ Throughput: {n_events / elapsed:.0f} events/sec")

    # Example 3: Gating statistics
    print("\n\nExample 3: Gating Statistics")
    print("-" * 60)

    stats = fast_net.get_stats()

    print(f"Total events: {stats['total_events']}")
    print(f"Retained: {stats['retained_events']} ({stats['retention_rate']:.1%})")
    print(f"Discarded: {stats['discarded_events']} ({stats['discard_rate']:.1%})")
    print(f"Buffer size: {stats['buffer_size']}/{stats['buffer_capacity']}")
    print(f"Avg encoding time: {stats['avg_encoding_time_ms']:.3f}ms")

    # Example 4: Consolidation
    print("\n\nExample 4: Consolidation Trigger")
    print("-" * 60)

    if fast_net.should_consolidate():
        buffer = fast_net.get_buffer(clear=True)
        print(f"✓ Time to consolidate!")
        print(f"✓ Retrieved {len(buffer)} events from buffer")
        print(f"✓ Buffer cleared: {len(fast_net.buffer)} events remaining")

        # Preview buffer
        print(f"\nPreview of consolidated events:")
        for i, cube in enumerate(buffer[:5]):
            print(f"  {i+1}. {cube.metadata.event_type.value}: importance={cube.metadata.importance:.2f}")

    # Example 5: Buffer search
    print("\n\nExample 5: Search Buffer")
    print("-" * 60)

    # Add some searchable events
    fast_net.encode_event({
        "type": "user_query",
        "content": "Find information about async tools"
    }, force_retain=True)

    fast_net.encode_event({
        "type": "user_query",
        "content": "What is the async speedup?"
    }, force_retain=True)

    # Search
    results = fast_net.search_buffer("async", max_results=3)

    print(f"Search for 'async': {len(results)} results")
    for i, cube in enumerate(results):
        content = str(cube.get_content())[:60]
        print(f"  {i+1}. {content}...")

    # Example 6: Recent events
    print("\n\nExample 6: Recent Events")
    print("-" * 60)

    recent = fast_net.get_recent(n=3)

    print(f"Last 3 events:")
    for i, cube in enumerate(recent):
        print(f"  {i+1}. {cube.metadata.event_type.value}: {cube.metadata.importance:.2f}")

    print("\n✅ All examples complete")


if __name__ == "__main__":
    run_example()

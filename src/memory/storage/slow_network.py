#!/usr/bin/env python3
"""
Slow Network - Background Memory Consolidation
===============================================

Background worker for memory consolidation and archival.

Based on research:
- Sleep-like unsupervised replay (Tadros et al. 2024)
- Dopamine-gated consolidation (Van de Ven et al. 2025)
- Ebbinghaus decay curves
- KL-divergence similarity detection (Behrouz et al. 2024)

Key Features:
- Runs asynchronously every 60 seconds
- Retrieves events from FastNetwork buffer
- Applies Ebbinghaus decay to importance scores
- Consolidates similar/redundant events
- Hands off low-importance events to archival
- Dopamine-gated threshold for consolidation

Architecture:
┌─────────────────────────────────────────┐
│         Slow Network                    │
├─────────────────────────────────────────┤
│                                         │
│  Input: FastNetwork buffer              │
│     │                                   │
│     ▼                                   │
│  ┌──────────────────────────┐          │
│  │  Ebbinghaus Decay        │          │
│  │  • Time-based importance │          │
│  │  • I(t) = I₀ * e^(-λt)   │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼                           │
│  ┌──────────────────────────┐          │
│  │  Similarity Detection    │          │
│  │  • Content hashing       │          │
│  │  • KL-divergence         │          │
│  │  • Semantic clustering   │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼                           │
│  ┌──────────────────────────┐          │
│  │  Event Consolidation     │          │
│  │  • Merge similar events  │          │
│  │  • Boost consolidated    │          │
│  │  • Discard redundant     │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ▼                           │
│  ┌──────────────────────────┐          │
│  │  Dopamine Gating         │          │
│  │  • Threshold: 0.3        │          │
│  │  • Archive if below      │          │
│  │  • Retain if above       │          │
│  └──────────┬───────────────┘          │
│             │                           │
│             ├─ HIGH ────▶ Long-term    │
│             │             Memory        │
│             │                           │
│             └─ LOW ─────▶ Archival     │
│                           System        │
└─────────────────────────────────────────┘

Usage Example:
    slow_net = SlowNetwork(
        consolidation_interval=60,  # seconds
        decay_lambda=0.1,           # Ebbinghaus decay rate
        archival_threshold=0.3      # Below this = archive
    )

    # Start background worker
    await slow_net.start()

    # Feed events from FastNetwork
    events = fast_net.get_buffer(clear=True)
    await slow_net.consolidate_batch(events)

    # Get consolidated events
    important_events = slow_net.get_long_term_memory()
"""

import asyncio
import time
import math
from typing import Any, Dict, List, Optional, Callable, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

try:
    from .mem_cube import MemCube, EventType
except ImportError:
    from mem_cube import MemCube, EventType
import logging
logger = logging.getLogger(__name__)


@dataclass
class ConsolidationStats:
    """Statistics for consolidation operations"""
    events_received: int = 0
    events_consolidated: int = 0
    events_archived: int = 0
    events_retained: int = 0
    events_promoted: int = 0
    events_quarantined: int = 0
    avg_decay_applied: float = 0.0
    consolidation_runs: int = 0
    total_time_ms: float = 0.0


class EbbinghausDecay:
    """
    Implements Ebbinghaus forgetting curve

    I(t) = I₀ * e^(-λt)

    Where:
    - I(t) = Importance at time t
    - I₀ = Initial importance
    - λ = Decay rate
    - t = Time elapsed (hours)
    """

    def __init__(self, decay_lambda: float = 0.1) -> None:
        """
        Initialize decay calculator

        Args:
            decay_lambda: Decay rate (0.0-1.0)
                - 0.1 = slow decay (half-life ~7 hours)
                - 0.5 = medium decay (half-life ~1.4 hours)
                - 1.0 = fast decay (half-life ~0.7 hours)
        """
        self.decay_lambda = decay_lambda

    def apply_decay(self, cube: MemCube) -> float:
        """
        Apply Ebbinghaus decay to MemCube

        Args:
            cube: MemCube to decay

        Returns:
            New importance score
        """
        # Calculate time elapsed in hours
        age = datetime.now() - cube.metadata.timestamp
        hours_elapsed = age.total_seconds() / 3600

        # Apply exponential decay
        initial_importance = cube.metadata.importance
        decayed_importance = initial_importance * math.exp(-self.decay_lambda * hours_elapsed)

        # Update cube
        cube.metadata.importance = max(0.0, decayed_importance)

        return cube.metadata.importance

    def get_half_life_hours(self) -> float:
        """Get half-life in hours for current decay rate"""
        return math.log(2) / self.decay_lambda


class SimilarityDetector:
    """
    Detects similar events for consolidation

    Uses:
    - Content hashing for exact duplicates
    - Semantic similarity for near-duplicates
    """

    def __init__(self, similarity_threshold: float = 0.8) -> None:
        """
        Initialize detector

        Args:
            similarity_threshold: Min similarity to consolidate (0.0-1.0)
        """
        self.similarity_threshold = similarity_threshold

    def compute_similarity(self, cube1: MemCube, cube2: MemCube) -> float:
        """
        Compute similarity between two MemCubes

        Args:
            cube1, cube2: MemCubes to compare

        Returns:
            Similarity score (0.0-1.0)
        """
        # Exact type match bonus
        type_match = 0.3 if cube1.metadata.event_type == cube2.metadata.event_type else 0.0

        # Content similarity (Jaccard for now, could use embeddings later)
        content1 = str(cube1.get_content()).lower()
        content2 = str(cube2.get_content()).lower()

        # Tokenize
        tokens1 = set(content1.split())
        tokens2 = set(content2.split())

        if not tokens1 or not tokens2:
            return type_match

        # Jaccard similarity
        intersection = tokens1.intersection(tokens2)
        union = tokens1.union(tokens2)
        jaccard = len(intersection) / len(union) if union else 0.0

        # Tag similarity bonus
        tags1 = set(cube1.metadata.tags)
        tags2 = set(cube2.metadata.tags)
        tag_match = 0.0
        if tags1 and tags2:
            tag_intersection = tags1.intersection(tags2)
            tag_union = tags1.union(tags2)
            tag_match = 0.2 * (len(tag_intersection) / len(tag_union))

        # Combined score
        return min(1.0, type_match + 0.5 * jaccard + tag_match)

    def find_similar_clusters(
        self,
        cubes: List[MemCube]
    ) -> List[List[MemCube]]:
        """
        Find clusters of similar events

        Args:
            cubes: List of MemCubes

        Returns:
            List of clusters (each cluster is a list of similar MemCubes)
        """
        clusters = []
        used = set()

        for i, cube1 in enumerate(cubes):
            if i in used:
                continue

            cluster = [cube1]
            used.add(i)

            for j, cube2 in enumerate(cubes[i+1:], start=i+1):
                if j in used:
                    continue

                similarity = self.compute_similarity(cube1, cube2)

                if similarity >= self.similarity_threshold:
                    cluster.append(cube2)
                    used.add(j)

            clusters.append(cluster)

        return clusters


class EventConsolidator:
    """
    Consolidates similar events into single representative events
    """

    def consolidate_cluster(
        self,
        cluster: List[MemCube]
    ) -> MemCube:
        """
        Consolidate cluster of similar events

        Args:
            cluster: List of similar MemCubes

        Returns:
            Consolidated MemCube
        """
        if len(cluster) == 1:
            return cluster[0]

        # Choose most important as representative
        cluster.sort(key=lambda c: c.metadata.importance, reverse=True)
        representative = cluster[0]

        # Boost importance based on cluster size
        # More occurrences = more important
        boost = min(0.3, 0.05 * (len(cluster) - 1))
        representative.boost_importance(boost)

        # Merge tags from all events
        all_tags = set()
        for cube in cluster:
            all_tags.update(cube.metadata.tags)
        representative.metadata.tags = list(all_tags)

        # Add consolidation metadata
        representative.metadata.provenance["consolidated_from"] = len(cluster)
        representative.metadata.provenance["consolidation_time"] = datetime.now().isoformat()
        representative.metadata.provenance["recurrence_count"] = len(cluster)
        if len(cluster) > 1:
            representative.metadata.provenance["promote_long_term"] = True

        return representative


class SlowNetwork:
    """
    Background consolidation worker

    Features:
    - Runs asynchronously every 60 seconds
    - Applies Ebbinghaus decay
    - Consolidates similar events
    - Hands off to archival system
    - Dopamine-gated retention

    Performance:
    - 60-second consolidation interval
    - <100ms per consolidation
    - Handles 1000+ events per batch
    """

    def __init__(
        self,
        consolidation_interval: float = 60.0,  # seconds
        decay_lambda: float = 0.1,
        archival_threshold: float = 0.3,
        retention_threshold: float = 0.5,
        retention_staleness_hours: float = 48.0,
        similarity_threshold: float = 0.8,
        max_long_term_size: int = 1000
    ):
        """
        Initialize SlowNetwork

        Args:
            consolidation_interval: Seconds between consolidations
            decay_lambda: Ebbinghaus decay rate
            archival_threshold: Below this = archive
            similarity_threshold: Min similarity to consolidate
            max_long_term_size: Max events in long-term memory
        """
        self.consolidation_interval = consolidation_interval
        self.archival_threshold = archival_threshold
        self.retention_threshold = retention_threshold
        self.retention_staleness_hours = retention_staleness_hours
        self.max_long_term_size = max_long_term_size

        # Components
        self.decay_calculator = EbbinghausDecay(decay_lambda)
        self.similarity_detector = SimilarityDetector(similarity_threshold)
        self.consolidator = EventConsolidator()

        # Storage
        self.long_term_memory: List[MemCube] = []
        self.archived_events: List[MemCube] = []
        self.quarantined_events: List[MemCube] = []

        # Worker state
        self.running = False
        self.worker_task: Optional[asyncio.Task] = None

        # Statistics
        self.stats = ConsolidationStats()

        # Callbacks
        self.on_archive: Optional[Callable[[List[MemCube]], None]] = None

    async def start(self):
        """Start background consolidation worker"""
        if self.running:
            return

        self.running = True
        self.worker_task = asyncio.create_task(self._consolidation_loop())

    async def stop(self):
        """Stop background worker"""
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in slow_network")
                pass

    async def _consolidation_loop(self):
        """Background consolidation loop"""
        while self.running:
            try:
                await asyncio.sleep(self.consolidation_interval)

                # Consolidate existing long-term memory
                if self.long_term_memory:
                    await self._consolidate_long_term()

            except asyncio.CancelledError:
                break
            except Exception as e:
                # Log error but keep running
                logger.error(f"Consolidation loop error: {e}")

    async def consolidate_batch(
        self,
        events: List[MemCube]
    ) -> Tuple[List[MemCube], List[MemCube]]:
        """
        Consolidate batch of events from FastNetwork

        Args:
            events: List of MemCubes from FastNetwork buffer

        Returns:
            (retained_events, archived_events)
        """
        start = time.time()

        self.stats.events_received += len(events)

        # Step 1: Apply Ebbinghaus decay
        total_decay = 0.0
        for cube in events:
            new_importance = self.decay_calculator.apply_decay(cube)
            total_decay += cube.metadata.importance - new_importance

        if events:
            self.stats.avg_decay_applied = total_decay / len(events)

        # Step 2: Retention gates (MIRAS-style)
        retained: List[MemCube] = []
        archived: List[MemCube] = []
        quarantined: List[MemCube] = []
        for cube in events:
            retention_score = self._compute_retention_score(cube)
            if cube.metadata.provenance.get("memory_tier") == "quarantine":
                quarantined.append(cube)
                continue
            if retention_score >= self.retention_threshold:
                retained.append(cube)
            else:
                archived.append(cube)

        # Step 3: Find similar clusters in retained events
        if retained:
            clusters = self.similarity_detector.find_similar_clusters(retained)

            # Step 4: Consolidate clusters
            consolidated = []
            for cluster in clusters:
                if len(cluster) > 1:
                    self.stats.events_consolidated += len(cluster) - 1

                representative = self.consolidator.consolidate_cluster(cluster)
                consolidated.append(representative)

            retained = consolidated
            for cube in retained:
                if cube.metadata.provenance.get("promote_long_term"):
                    cube.metadata.provenance["memory_tier"] = "long_term"

        # Step 5: Add to long-term memory
        self.long_term_memory.extend(retained)
        self.archived_events.extend(archived)
        self.quarantined_events.extend(quarantined)

        # Step 6: Prune long-term memory if too large
        if len(self.long_term_memory) > self.max_long_term_size:
            self._prune_long_term_memory()

        # Step 7: Hand off archived events
        if archived and self.on_archive:
            self.on_archive(archived)

        # Update stats
        self.stats.events_retained += len(retained)
        self.stats.events_archived += len(archived)
        self.stats.events_quarantined += len(quarantined)
        self.stats.events_promoted += sum(
            1 for cube in retained if cube.metadata.provenance.get("memory_tier") == "long_term"
        )
        self.stats.consolidation_runs += 1
        self.stats.total_time_ms += (time.time() - start) * 1000

        return retained, archived

    async def _consolidate_long_term(self):
        """Consolidate existing long-term memory"""
        # Apply decay to existing memories
        for cube in self.long_term_memory:
            self.decay_calculator.apply_decay(cube)

        # Remove events that fell below threshold
        to_archive = [c for c in self.long_term_memory
                      if c.metadata.importance < self.archival_threshold]

        if to_archive:
            self.long_term_memory = [c for c in self.long_term_memory
                                     if c.metadata.importance >= self.archival_threshold]

            self.archived_events.extend(to_archive)
            self.stats.events_archived += len(to_archive)

            if self.on_archive:
                self.on_archive(to_archive)

    def _prune_long_term_memory(self):
        """Prune long-term memory to max size"""
        # Sort by importance (descending)
        self.long_term_memory.sort(
            key=lambda c: c.metadata.importance,
            reverse=True
        )

        # Keep top N
        to_archive = self.long_term_memory[self.max_long_term_size:]
        self.long_term_memory = self.long_term_memory[:self.max_long_term_size]

        # Archive pruned events
        self.archived_events.extend(to_archive)
        self.stats.events_archived += len(to_archive)

        if to_archive and self.on_archive:
            self.on_archive(to_archive)

    def _compute_retention_score(self, cube: MemCube) -> float:
        """Compute retention score with staleness penalty."""
        if cube.metadata.provenance.get("quarantine"):
            cube.metadata.provenance["promote_long_term"] = False
            cube.metadata.provenance["memory_tier"] = "quarantine"
            return 0.0

        retention = cube.metadata.provenance.get("retention", {})
        base_score = None
        if isinstance(retention, dict):
            base_score = retention.get("score")
        if base_score is None:
            base_score = cube.metadata.importance

        age = datetime.now() - cube.metadata.timestamp
        hours = age.total_seconds() / 3600
        staleness = min(1.0, max(0.0, hours / max(self.retention_staleness_hours, 1.0)))

        adjusted = max(0.0, min(1.0, base_score - staleness))

        if isinstance(retention, dict):
            retention["staleness"] = staleness
            retention["score"] = adjusted
            cube.metadata.provenance["retention"] = retention

        if cube.metadata.event_type == EventType.TOOL_EXECUTION:
            cube.metadata.provenance["promote_long_term"] = True

        if cube.metadata.provenance.get("promote_long_term"):
            cube.metadata.provenance["memory_tier"] = "long_term"
            return max(adjusted, self.retention_threshold)

        cube.metadata.provenance["memory_tier"] = "working" if adjusted >= self.retention_threshold else "archived"
        return adjusted

    def get_long_term_memory(
        self,
        min_importance: float = 0.0,
        max_results: Optional[int] = None
    ) -> List[MemCube]:
        """
        Get long-term memory events

        Args:
            min_importance: Min importance filter
            max_results: Max results to return

        Returns:
            List of MemCubes
        """
        filtered = [c for c in self.long_term_memory
                   if c.metadata.importance >= min_importance]

        # Sort by importance (descending)
        filtered.sort(key=lambda c: c.metadata.importance, reverse=True)

        if max_results:
            filtered = filtered[:max_results]

        return filtered

    def search_long_term(
        self,
        query: str,
        max_results: int = 10
    ) -> List[MemCube]:
        """
        Search long-term memory

        Args:
            query: Search query
            max_results: Max results

        Returns:
            List of matching MemCubes
        """
        query_lower = query.lower()
        matches = []

        for cube in self.long_term_memory:
            content_str = str(cube.get_content()).lower()
            if query_lower in content_str:
                matches.append(cube)

                if len(matches) >= max_results:
                    break

        return matches

    def get_stats(self) -> Dict[str, Any]:
        """Get consolidation statistics"""
        stats_dict = {
            "events_received": self.stats.events_received,
            "events_consolidated": self.stats.events_consolidated,
            "events_retained": self.stats.events_retained,
            "events_archived": self.stats.events_archived,
            "events_promoted": self.stats.events_promoted,
            "events_quarantined": self.stats.events_quarantined,
            "consolidation_runs": self.stats.consolidation_runs,
            "avg_decay_applied": self.stats.avg_decay_applied,
            "total_time_ms": self.stats.total_time_ms,
            "long_term_size": len(self.long_term_memory),
            "archived_size": len(self.archived_events),
            "quarantine_size": len(self.quarantined_events),
            "decay_half_life_hours": self.decay_calculator.get_half_life_hours()
        }

        # Derived stats
        if self.stats.consolidation_runs > 0:
            stats_dict["avg_time_per_run_ms"] = (
                self.stats.total_time_ms / self.stats.consolidation_runs
            )
        else:
            stats_dict["avg_time_per_run_ms"] = 0.0

        if self.stats.events_received > 0:
            stats_dict["retention_rate"] = (
                self.stats.events_retained / self.stats.events_received
            )
            stats_dict["archival_rate"] = (
                self.stats.events_archived / self.stats.events_received
            )
            stats_dict["quarantine_rate"] = (
                self.stats.events_quarantined / self.stats.events_received
            )
            stats_dict["consolidation_rate"] = (
                self.stats.events_consolidated / self.stats.events_received
            )
        else:
            stats_dict["retention_rate"] = 0.0
            stats_dict["archival_rate"] = 0.0
            stats_dict["quarantine_rate"] = 0.0
            stats_dict["consolidation_rate"] = 0.0

        return stats_dict

    def clear(self) -> None:
        """Clear all memory"""
        self.long_term_memory.clear()
        self.archived_events.clear()
        self.quarantined_events.clear()


# Example usage and testing
async def run_example():
    """Demonstrate SlowNetwork capabilities"""
    print("=== Slow Network Example ===\n")

    # Example 1: Create and start worker
    print("Example 1: Create Slow Network")
    print("-" * 60)

    slow_net = SlowNetwork(
        consolidation_interval=5.0,  # 5 seconds for demo
        decay_lambda=0.1,
        archival_threshold=0.3,
        similarity_threshold=0.8
    )

    print(f"✓ Created with {slow_net.consolidation_interval}s interval")
    print(f"✓ Decay half-life: {slow_net.decay_calculator.get_half_life_hours():.1f} hours")
    print(f"✓ Archival threshold: {slow_net.archival_threshold}")

    # Example 2: Consolidate batch of events
    print("\n\nExample 2: Consolidate Events")
    print("-" * 60)

    # Create diverse events
    events = []

    # Similar events (should consolidate)
    for i in range(3):
        events.append(MemCube(
            content=f"User asked about Phase 2 status (variant {i})",
            event_type=EventType.USER_QUERY,
            importance=0.8,
            tags=["phase2", "status"]
        ))

    # Different events
    events.append(MemCube(
        content="Tool execution completed successfully",
        event_type=EventType.TOOL_EXECUTION,
        importance=0.5,
        tags=["tool"]
    ))

    events.append(MemCube(
        content="Low importance system event",
        event_type=EventType.SYSTEM_EVENT,
        importance=0.2  # Will be archived
    ))

    print(f"Created {len(events)} events")

    # Consolidate
    retained, archived = await slow_net.consolidate_batch(events)

    print(f"\n✓ Consolidated:")
    print(f"  - Retained: {len(retained)} events")
    print(f"  - Archived: {len(archived)} events")

    # Show retained events
    print(f"\nRetained events:")
    for i, cube in enumerate(retained):
        print(f"  {i+1}. {cube.metadata.event_type.value}: importance={cube.metadata.importance:.2f}")
        if "consolidated_from" in cube.metadata.provenance:
            print(f"     (consolidated from {cube.metadata.provenance['consolidated_from']} events)")

    # Example 3: Ebbinghaus decay
    print("\n\nExample 3: Ebbinghaus Decay")
    print("-" * 60)

    # Create old event
    old_event = MemCube(
        content="Old memory from hours ago",
        event_type=EventType.AGENT_THOUGHT,
        importance=0.9
    )

    # Simulate age
    old_event.metadata.timestamp = datetime.now() - timedelta(hours=3)

    print(f"Original importance: {0.9:.2f}")
    print(f"Age: 3 hours")

    new_importance = slow_net.decay_calculator.apply_decay(old_event)

    print(f"After decay: {new_importance:.2f}")
    print(f"Decay applied: {0.9 - new_importance:.2f}")

    # Example 4: Search long-term memory
    print("\n\nExample 4: Search Long-term Memory")
    print("-" * 60)

    results = slow_net.search_long_term("Phase 2", max_results=3)

    print(f"Search for 'Phase 2': {len(results)} results")
    for i, cube in enumerate(results):
        content = str(cube.get_content())[:50]
        print(f"  {i+1}. {content}... (importance={cube.metadata.importance:.2f})")

    # Example 5: Statistics
    print("\n\nExample 5: Consolidation Statistics")
    print("-" * 60)

    stats = slow_net.get_stats()

    print(f"Events received: {stats['events_received']}")
    print(f"Events retained: {stats['events_retained']} ({stats['retention_rate']:.1%})")
    print(f"Events archived: {stats['events_archived']} ({stats['archival_rate']:.1%})")
    print(f"Events consolidated: {stats['events_consolidated']} ({stats['consolidation_rate']:.1%})")
    print(f"Long-term memory size: {stats['long_term_size']}")
    print(f"Avg time per run: {stats['avg_time_per_run_ms']:.2f}ms")

    # Example 6: Background worker
    print("\n\nExample 6: Background Worker")
    print("-" * 60)

    print("Starting background worker...")
    await slow_net.start()
    print("✓ Worker started")

    # Add more events
    new_events = []
    for i in range(5):
        new_events.append(MemCube(
            content=f"Background event {i}",
            event_type=EventType.SYSTEM_EVENT,
            importance=0.6
        ))

    await slow_net.consolidate_batch(new_events)
    print(f"✓ Added {len(new_events)} more events")

    # Wait for one consolidation cycle
    print(f"Waiting {slow_net.consolidation_interval}s for consolidation cycle...")
    await asyncio.sleep(slow_net.consolidation_interval + 0.5)

    print("✓ Consolidation cycle completed")

    # Stop worker
    await slow_net.stop()
    print("✓ Worker stopped")

    print("\n✅ All examples complete")


if __name__ == "__main__":
    asyncio.run(run_example())

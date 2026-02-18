#!/usr/bin/env python3
"""
Archival System - Hierarchical Memory Storage
==============================================

Implements 3-tier hierarchical archival system for long-term memory.

Based on research:
- MemOS 3-tier architecture (STM/MTM/LPM)
- Time-based migration
- Importance-weighted retrieval
- Compressed storage

Key Features:
- Recent tier (last 24 hours)
- Weekly tier (last 7 days)
- Monthly tier (30+ days)
- Automatic migration between tiers
- Compressed storage (CommVQ)
- Importance-weighted search

Architecture:
┌─────────────────────────────────────────┐
│         Archival System                 │
├─────────────────────────────────────────┤
│                                         │
│  ┌────────────────────────────┐        │
│  │  Recent Tier (24h)         │        │
│  │  • Uncompressed            │        │
│  │  • Fast access             │        │
│  │  • 1000 events max         │        │
│  └──────────┬─────────────────┘        │
│             │ migrate (24h+)           │
│             ▼                           │
│  ┌────────────────────────────┐        │
│  │  Weekly Tier (7d)          │        │
│  │  • Compressed (CommVQ)     │        │
│  │  • Medium access           │        │
│  │  • 5000 events max         │        │
│  └──────────┬─────────────────┘        │
│             │ migrate (7d+)            │
│             ▼                           │
│  ┌────────────────────────────┐        │
│  │  Monthly Tier (30d+)       │        │
│  │  • Highly compressed       │        │
│  │  • Slow access             │        │
│  │  • Unlimited                │        │
│  └────────────────────────────┘        │
│                                         │
│  Search across all tiers                │
│  • Importance-weighted ranking          │
│  • Recency boost                        │
│  • Automatic decompression              │
│                                         │
└─────────────────────────────────────────┘

Usage Example:
    archive = ArchivalSystem(
        recent_max=1000,
        weekly_max=5000
    )

    # Archive low-importance events
    archive.archive(events)

    # Search across all tiers
    results = archive.search("Phase 2", max_results=10)

    # Periodic migration
    archive.migrate_tiers()
"""

from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict

try:
    from .mem_cube import MemCube, EventType
    from .commvq_compression import CommVQCompressor, CompressionMetadata
except ImportError:
    from mem_cube import MemCube, EventType
    from commvq_compression import CommVQCompressor, CompressionMetadata


@dataclass
class TierStats:
    """Statistics for a storage tier"""
    tier_name: str
    event_count: int = 0
    total_bytes: int = 0
    compressed_bytes: int = 0
    oldest_event: Optional[datetime] = None
    newest_event: Optional[datetime] = None


class StorageTier:
    """
    Single tier in archival system

    Manages events within specific time window
    """

    def __init__(
        self,
        name: str,
        max_events: Optional[int] = None,
        compression_enabled: bool = False
    ):
        """
        Initialize storage tier

        Args:
            name: Tier name
            max_events: Max events (None = unlimited)
            compression_enabled: Whether to compress events
        """
        self.name = name
        self.max_events = max_events
        self.compression_enabled = compression_enabled

        # Storage (cube_id -> MemCube)
        self.events: Dict[str, MemCube] = {}

        # Compression
        if compression_enabled:
            self.compressor = CommVQCompressor()
        else:
            self.compressor = None

        # Stats
        self.total_bytes = 0
        self.compressed_bytes = 0

    def add(self, cube: MemCube) -> None:
        """
        Add event to tier

        Args:
            cube: MemCube to archive
        """
        # Compress if enabled and not already compressed
        if self.compression_enabled and not cube._compressed and self.compressor:
            cube.compress()

        # Add to storage
        self.events[cube.cube_id] = cube

        # Update stats
        self.total_bytes += cube.size_bytes()

        if cube._compressed:
            self.compressed_bytes += cube.size_bytes()

        # Evict if over max
        if self.max_events and len(self.events) > self.max_events:
            self._evict_oldest()

    def _evict_oldest(self):
        """Evict oldest event"""
        if not self.events:
            return

        # Find oldest
        oldest_id = min(
            self.events.keys(),
            key=lambda cid: self.events[cid].metadata.timestamp
        )

        # Remove
        cube = self.events[oldest_id]
        del self.events[oldest_id]

        # Update stats
        self.total_bytes -= cube.size_bytes()
        if cube._compressed:
            self.compressed_bytes -= cube.size_bytes()

    def search(self, query: str, max_results: int = 10) -> List[Tuple[MemCube, float]]:
        """
        Search tier for query

        Args:
            query: Search query
            max_results: Max results

        Returns:
            List of (MemCube, score) tuples
        """
        query_lower = query.lower()
        matches = []

        for cube in self.events.values():
            content_str = str(cube.get_content()).lower()

            if query_lower in content_str:
                # Score based on importance and recency
                age = (datetime.now() - cube.metadata.timestamp).total_seconds() / 3600
                recency_factor = 1.0 / (1.0 + age / 24)  # Decay over days

                score = cube.metadata.importance * 0.7 + recency_factor * 0.3

                matches.append((cube, score))

        # Sort by score
        matches.sort(key=lambda x: x[1], reverse=True)

        return matches[:max_results]

    def get_events_older_than(self, hours: float) -> List[MemCube]:
        """
        Get events older than specified hours

        Args:
            hours: Age threshold

        Returns:
            List of MemCubes
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        old_events = [
            cube for cube in self.events.values()
            if cube.metadata.timestamp < cutoff
        ]

        return old_events

    def remove(self, cube_id: str) -> bool:
        """
        Remove event from tier

        Args:
            cube_id: Cube ID to remove

        Returns:
            True if removed, False if not found
        """
        if cube_id in self.events:
            cube = self.events[cube_id]
            del self.events[cube_id]

            # Update stats
            self.total_bytes -= cube.size_bytes()
            if cube._compressed:
                self.compressed_bytes -= cube.size_bytes()

            return True

        return False

    def get_stats(self) -> TierStats:
        """Get tier statistics"""
        if not self.events:
            return TierStats(tier_name=self.name)

        timestamps = [c.metadata.timestamp for c in self.events.values()]

        return TierStats(
            tier_name=self.name,
            event_count=len(self.events),
            total_bytes=self.total_bytes,
            compressed_bytes=self.compressed_bytes,
            oldest_event=min(timestamps),
            newest_event=max(timestamps)
        )

    def clear(self) -> None:
        """Clear all events"""
        self.events.clear()
        self.total_bytes = 0
        self.compressed_bytes = 0


class ArchivalSystem:
    """
    3-tier hierarchical archival system

    Tiers:
    - Recent: Last 24 hours, uncompressed, fast
    - Weekly: Last 7 days, compressed, medium
    - Monthly: 30+ days, compressed, slow

    Features:
    - Automatic tier migration
    - Compressed storage
    - Cross-tier search
    - Importance-weighted ranking
    """

    def __init__(
        self,
        recent_max: int = 1000,
        weekly_max: int = 5000,
        monthly_max: Optional[int] = None  # Unlimited
    ):
        """
        Initialize archival system

        Args:
            recent_max: Max events in recent tier
            weekly_max: Max events in weekly tier
            monthly_max: Max events in monthly tier (None = unlimited)
        """
        # Tiers
        self.recent = StorageTier(
            name="Recent",
            max_events=recent_max,
            compression_enabled=False
        )

        self.weekly = StorageTier(
            name="Weekly",
            max_events=weekly_max,
            compression_enabled=True
        )

        self.monthly = StorageTier(
            name="Monthly",
            max_events=monthly_max,
            compression_enabled=True
        )

        # Migration thresholds (hours)
        self.recent_to_weekly_hours = 24
        self.weekly_to_monthly_hours = 24 * 7  # 7 days

        # Stats
        self.total_archived = 0
        self.total_migrations = 0

    def archive(self, cubes: List[MemCube]) -> None:
        """
        Archive events (add to recent tier)

        Args:
            cubes: MemCubes to archive
        """
        for cube in cubes:
            self.recent.add(cube)
            self.total_archived += 1

    def migrate_tiers(self):
        """
        Migrate events between tiers based on age

        Recent (24h+) → Weekly
        Weekly (7d+) → Monthly
        """
        migrations = 0

        # Recent → Weekly
        old_recent = self.recent.get_events_older_than(self.recent_to_weekly_hours)

        for cube in old_recent:
            self.weekly.add(cube)
            self.recent.remove(cube.cube_id)
            migrations += 1

        # Weekly → Monthly
        old_weekly = self.weekly.get_events_older_than(self.weekly_to_monthly_hours)

        for cube in old_weekly:
            self.monthly.add(cube)
            self.weekly.remove(cube.cube_id)
            migrations += 1

        self.total_migrations += migrations

        return migrations

    def search(
        self,
        query: str,
        max_results: int = 10,
        tiers: Optional[List[str]] = None
    ) -> List[Tuple[MemCube, float, str]]:
        """
        Search across all tiers

        Args:
            query: Search query
            max_results: Max results
            tiers: Specific tiers to search (None = all)

        Returns:
            List of (MemCube, score, tier_name) tuples
        """
        # Determine which tiers to search
        search_tiers = []

        if tiers is None or "Recent" in tiers:
            search_tiers.append(("Recent", self.recent))

        if tiers is None or "Weekly" in tiers:
            search_tiers.append(("Weekly", self.weekly))

        if tiers is None or "Monthly" in tiers:
            search_tiers.append(("Monthly", self.monthly))

        # Search all tiers
        all_matches = []

        for tier_name, tier in search_tiers:
            tier_matches = tier.search(query, max_results=max_results * 2)

            # Add tier name
            for cube, score in tier_matches:
                all_matches.append((cube, score, tier_name))

        # Sort by score
        all_matches.sort(key=lambda x: x[1], reverse=True)

        return all_matches[:max_results]

    def get_by_importance(
        self,
        min_importance: float = 0.5,
        max_results: int = 10
    ) -> List[Tuple[MemCube, str]]:
        """
        Get events by importance across all tiers

        Args:
            min_importance: Minimum importance
            max_results: Max results

        Returns:
            List of (MemCube, tier_name) tuples
        """
        matches = []

        # Search all tiers
        for tier_name, tier in [
            ("Recent", self.recent),
            ("Weekly", self.weekly),
            ("Monthly", self.monthly)
        ]:
            for cube in tier.events.values():
                if cube.metadata.importance >= min_importance:
                    matches.append((cube, tier_name))

        # Sort by importance
        matches.sort(key=lambda x: x[0].metadata.importance, reverse=True)

        return matches[:max_results]

    def get_recent_events(self, hours: float = 24) -> List[MemCube]:
        """
        Get events from last N hours

        Args:
            hours: Time window

        Returns:
            List of MemCubes
        """
        cutoff = datetime.now() - timedelta(hours=hours)
        events = []

        # Check all tiers
        for tier in [self.recent, self.weekly, self.monthly]:
            for cube in tier.events.values():
                if cube.metadata.timestamp >= cutoff:
                    events.append(cube)

        # Sort by timestamp
        events.sort(key=lambda c: c.metadata.timestamp, reverse=True)

        return events

    def get_stats(self) -> Dict[str, Any]:
        """Get archival statistics"""
        recent_stats = self.recent.get_stats()
        weekly_stats = self.weekly.get_stats()
        monthly_stats = self.monthly.get_stats()

        total_events = (
            recent_stats.event_count +
            weekly_stats.event_count +
            monthly_stats.event_count
        )

        total_bytes = (
            recent_stats.total_bytes +
            weekly_stats.total_bytes +
            monthly_stats.total_bytes
        )

        compressed_bytes = (
            recent_stats.compressed_bytes +
            weekly_stats.compressed_bytes +
            monthly_stats.compressed_bytes
        )

        return {
            "total_archived": self.total_archived,
            "total_migrations": self.total_migrations,
            "total_events": total_events,
            "total_bytes": total_bytes,
            "compressed_bytes": compressed_bytes,
            "compression_ratio": compressed_bytes / total_bytes if total_bytes > 0 else 0,
            "tiers": {
                "recent": asdict(recent_stats),
                "weekly": asdict(weekly_stats),
                "monthly": asdict(monthly_stats)
            }
        }

    def clear(self) -> None:
        """Clear all tiers"""
        self.recent.clear()
        self.weekly.clear()
        self.monthly.clear()
        self.total_archived = 0
        self.total_migrations = 0


# Example usage and testing
def run_example() -> None:
    """Demonstrate archival system capabilities"""
    print("=== Archival System Example ===\n")

    # Example 1: Create archival system
    print("Example 1: Create Archival System")
    print("-" * 60)

    archive = ArchivalSystem(
        recent_max=100,
        weekly_max=500
    )

    print(f"✓ Created 3-tier system:")
    print(f"  - Recent: max {archive.recent.max_events} events")
    print(f"  - Weekly: max {archive.weekly.max_events} events")
    print(f"  - Monthly: unlimited")

    # Example 2: Archive events
    print("\n\nExample 2: Archive Events")
    print("-" * 60)

    events = []

    # Create diverse events
    for i in range(10):
        cube = MemCube(
            content=f"Event {i}: Phase 2 Week 3 implementation",
            event_type=EventType.SYSTEM_EVENT if i % 2 == 0 else EventType.USER_QUERY,
            importance=0.3 + (i / 20),
            tags=["phase2", "week3"]
        )

        # Simulate different ages
        hours_ago = i * 0.5
        cube.metadata.timestamp = datetime.now() - timedelta(hours=hours_ago)

        events.append(cube)

    archive.archive(events)

    print(f"✓ Archived {len(events)} events")

    stats = archive.get_stats()
    print(f"✓ Total events: {stats['total_events']}")
    print(f"✓ Recent tier: {stats['tiers']['recent']['event_count']} events")

    # Example 3: Search across tiers
    print("\n\nExample 3: Search Across Tiers")
    print("-" * 60)

    results = archive.search("Phase 2", max_results=5)

    print(f"Search for 'Phase 2': {len(results)} results")

    for i, (cube, score, tier) in enumerate(results):
        content = str(cube.get_content())[:40]
        print(f"  {i+1}. [{tier}] {content}... (score={score:.2f})")

    # Example 4: Tier migration
    print("\n\nExample 4: Tier Migration")
    print("-" * 60)

    # Create old events for recent tier
    old_events = []

    for i in range(5):
        cube = MemCube(
            content=f"Old event {i} from 25 hours ago",
            event_type=EventType.SYSTEM_EVENT,
            importance=0.4
        )

        # 25 hours ago (should migrate to weekly)
        cube.metadata.timestamp = datetime.now() - timedelta(hours=25)

        old_events.append(cube)

    archive.archive(old_events)

    print(f"Added {len(old_events)} old events to Recent tier")

    # Migrate
    migrations = archive.migrate_tiers()

    print(f"✓ Migrated {migrations} events")

    stats = archive.get_stats()
    print(f"✓ Recent tier: {stats['tiers']['recent']['event_count']} events")
    print(f"✓ Weekly tier: {stats['tiers']['weekly']['event_count']} events")

    # Example 5: Importance-based retrieval
    print("\n\nExample 5: Importance-Based Retrieval")
    print("-" * 60)

    # Add high-importance events
    important_events = []

    for i in range(3):
        cube = MemCube(
            content=f"Important event {i}",
            event_type=EventType.USER_QUERY,
            importance=0.9,
            tags=["important"]
        )

        important_events.append(cube)

    archive.archive(important_events)

    # Retrieve by importance
    high_importance = archive.get_by_importance(min_importance=0.8, max_results=5)

    print(f"Events with importance ≥ 0.8: {len(high_importance)}")

    for i, (cube, tier) in enumerate(high_importance):
        print(f"  {i+1}. [{tier}] importance={cube.metadata.importance:.2f}")

    # Example 6: Statistics
    print("\n\nExample 6: Archival Statistics")
    print("-" * 60)

    stats = archive.get_stats()

    print(f"Total archived: {stats['total_archived']} events")
    print(f"Total migrations: {stats['total_migrations']}")
    print(f"Total events: {stats['total_events']}")
    print(f"Total bytes: {stats['total_bytes']}")
    print(f"Compressed bytes: {stats['compressed_bytes']}")

    if stats['total_bytes'] > 0:
        compression = (1 - stats['compression_ratio']) * 100
        print(f"Overall compression: {compression:.1f}%")

    print(f"\nTier breakdown:")
    for tier_name in ['recent', 'weekly', 'monthly']:
        tier_stats = stats['tiers'][tier_name]
        print(f"  {tier_name.capitalize()}: {tier_stats['event_count']} events")

    print("\n✅ All examples complete")


if __name__ == "__main__":
    run_example()

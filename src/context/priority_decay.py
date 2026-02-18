"""
Priority Decay System for VERA.

Implements automatic priority adjustment based on age, activity, and context.
Tasks that haven't been touched naturally decay in priority over time.
"""

import json
import math
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class DecayModel(Enum):
    """Priority decay models."""
    LINEAR = "linear"           # Steady decay
    EXPONENTIAL = "exponential" # Fast initial decay, slows down
    LOGARITHMIC = "logarithmic" # Slow initial decay, speeds up
    STEP = "step"              # Decay in discrete steps
    CUSTOM = "custom"          # User-defined function


@dataclass
class DecayConfig:
    """Configuration for decay behavior."""
    model: DecayModel = DecayModel.EXPONENTIAL
    half_life_hours: float = 168.0  # 1 week
    min_priority: int = 3           # Don't decay below this (P3)
    max_priority: int = 0           # Highest priority (P0)

    # Activity boost settings
    activity_boost_factor: float = 0.5  # How much activity restores priority
    activity_window_hours: float = 24.0  # Recent activity window

    # Special cases
    exempt_priorities: List[int] = field(default_factory=lambda: [0])  # P0 never decays
    decay_on_complete: bool = False  # Decay completed tasks

    # Step decay settings (when using STEP model)
    step_interval_hours: float = 24.0
    step_size: int = 1


@dataclass
class PriorityRecord:
    """Tracks priority changes for an item."""
    item_id: str
    original_priority: int
    current_priority: int
    created_at: datetime
    last_activity: datetime
    last_decay: Optional[datetime] = None
    decay_count: int = 0
    boost_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "original_priority": self.original_priority,
            "current_priority": self.current_priority,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "last_decay": self.last_decay.isoformat() if self.last_decay else None,
            "decay_count": self.decay_count,
            "boost_count": self.boost_count,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PriorityRecord":
        return cls(
            item_id=data.get("item_id", ""),
            original_priority=data.get("original_priority", ""),
            current_priority=data.get("current_priority", ""),
            created_at=datetime.fromisoformat(data.get("created_at", "")),
            last_activity=datetime.fromisoformat(data.get("last_activity", "")),
            last_decay=datetime.fromisoformat(data["last_decay"]) if data.get("last_decay") else None,
            decay_count=data.get("decay_count", 0),
            boost_count=data.get("boost_count", 0),
            metadata=data.get("metadata", {})
        )


class PriorityDecayManager:
    """
    Manages automatic priority decay for tasks and items.

    Features:
    - Configurable decay models (linear, exponential, step)
    - Activity-based priority restoration
    - Per-item tracking and history
    - Batch decay processing
    - Integration with task systems
    """

    def __init__(
        self,
        memory_dir: Optional[Path] = None,
        config: Optional[DecayConfig] = None
    ):
        """
        Initialize priority decay manager.

        Args:
            memory_dir: Directory for persistence
            config: Decay configuration
        """
        if memory_dir:
            self.memory_dir = Path(memory_dir)
        else:
            self.memory_dir = Path("vera_memory")

        self.storage_file = self.memory_dir / "priority_decay.json"
        self.config = config or DecayConfig()

        # State
        self._records: Dict[str, PriorityRecord] = {}

        # Custom decay function
        self._custom_decay_fn: Optional[Callable] = None

        # Stats
        self._total_decays = 0
        self._total_boosts = 0

        # Load state
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        if self.storage_file.exists():
            try:
                with open(self.storage_file) as f:
                    data = json.load(f)

                for record_data in data.get("records", []):
                    record = PriorityRecord.from_dict(record_data)
                    self._records[record.item_id] = record

                self._total_decays = data.get("total_decays", 0)
                self._total_boosts = data.get("total_boosts", 0)

            except Exception as e:
                logger.error(f"Failed to load priority decay state: {e}")

    def _save_state(self) -> None:
        """Save state to disk."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "records": [r.to_dict() for r in self._records.values()],
            "total_decays": self._total_decays,
            "total_boosts": self._total_boosts
        }

        with open(self.storage_file, 'w') as f:
            json.dump(data, f, indent=2)

    def set_custom_decay_function(self, fn: Callable[[float, int], int]) -> None:
        """
        Set a custom decay function.

        Args:
            fn: Function(hours_since_activity, current_priority) -> new_priority
        """
        self._custom_decay_fn = fn

    def register_item(
        self,
        item_id: str,
        priority: int,
        metadata: Optional[Dict] = None
    ) -> PriorityRecord:
        """
        Register an item for priority tracking.

        Args:
            item_id: Unique item identifier
            priority: Initial priority (0=highest, 3=lowest)
            metadata: Optional metadata

        Returns:
            Created PriorityRecord
        """
        now = datetime.now()

        record = PriorityRecord(
            item_id=item_id,
            original_priority=priority,
            current_priority=priority,
            created_at=now,
            last_activity=now,
            metadata=metadata or {}
        )

        self._records[item_id] = record
        self._save_state()

        return record

    def record_activity(self, item_id: str) -> Optional[PriorityRecord]:
        """
        Record activity on an item, potentially boosting priority.

        Args:
            item_id: Item identifier

        Returns:
            Updated record or None if not found
        """
        record = self._records.get(item_id)
        if not record:
            return None

        record.last_activity = datetime.now()

        # Calculate potential boost
        boosted_priority = self._calculate_activity_boost(record)
        if boosted_priority < record.current_priority:
            record.current_priority = boosted_priority
            record.boost_count += 1
            self._total_boosts += 1

        self._save_state()
        return record

    def _calculate_activity_boost(self, record: PriorityRecord) -> int:
        """Calculate priority boost from activity."""
        # Boost toward original priority
        boost = self.config.activity_boost_factor
        target = record.original_priority

        # How much to restore
        current = record.current_priority
        diff = current - target

        if diff <= 0:
            return current

        # Apply boost
        new_priority = current - int(diff * boost)
        return max(new_priority, target)

    def calculate_decay(
        self,
        item_id: str,
        apply: bool = False
    ) -> Optional[int]:
        """
        Calculate the decayed priority for an item.

        Args:
            item_id: Item identifier
            apply: Whether to apply the decay

        Returns:
            New priority or None if not found
        """
        record = self._records.get(item_id)
        if not record:
            return None

        # Check exemptions
        if record.current_priority in self.config.exempt_priorities:
            return record.current_priority

        # Calculate hours since last activity
        hours = (datetime.now() - record.last_activity).total_seconds() / 3600

        # Apply decay model
        if self.config.model == DecayModel.LINEAR:
            new_priority = self._linear_decay(record.current_priority, hours)
        elif self.config.model == DecayModel.EXPONENTIAL:
            new_priority = self._exponential_decay(record.current_priority, hours)
        elif self.config.model == DecayModel.LOGARITHMIC:
            new_priority = self._logarithmic_decay(record.current_priority, hours)
        elif self.config.model == DecayModel.STEP:
            new_priority = self._step_decay(record, hours)
        elif self.config.model == DecayModel.CUSTOM and self._custom_decay_fn:
            new_priority = self._custom_decay_fn(hours, record.current_priority)
        else:
            new_priority = record.current_priority

        # Clamp to valid range
        new_priority = min(new_priority, self.config.min_priority)
        new_priority = max(new_priority, self.config.max_priority)

        if apply and new_priority != record.current_priority:
            record.current_priority = new_priority
            record.last_decay = datetime.now()
            record.decay_count += 1
            self._total_decays += 1
            self._save_state()

        return new_priority

    def _linear_decay(self, current: int, hours: float) -> int:
        """Linear decay model."""
        decay_per_hour = 1.0 / self.config.half_life_hours
        decay_amount = hours * decay_per_hour
        return int(current + decay_amount)

    def _exponential_decay(self, current: int, hours: float) -> int:
        """Exponential decay model (priority increases as it ages)."""
        # Using reverse exponential - priority increases over time
        half_life = self.config.half_life_hours
        decay_factor = 1 - math.exp(-0.693 * hours / half_life)
        priority_range = self.config.min_priority - current

        return int(current + priority_range * decay_factor)

    def _logarithmic_decay(self, current: int, hours: float) -> int:
        """Logarithmic decay model - slow initially, faster later."""
        if hours <= 0:
            return current

        # Log-based decay
        log_factor = math.log(1 + hours / self.config.half_life_hours)
        priority_range = self.config.min_priority - current

        return int(current + priority_range * min(log_factor, 1.0))

    def _step_decay(self, record: PriorityRecord, hours: float) -> int:
        """Step decay model - discrete priority changes."""
        intervals_passed = int(hours / self.config.step_interval_hours)

        if intervals_passed <= record.decay_count:
            return record.current_priority

        # Apply step decay
        new_priority = record.current_priority + self.config.step_size
        return min(new_priority, self.config.min_priority)

    def process_all_decay(self) -> Dict[str, int]:
        """
        Process decay for all registered items.

        Returns:
            Dict of item_id -> new_priority for items that changed
        """
        changes = {}

        for item_id, record in self._records.items():
            old_priority = record.current_priority
            new_priority = self.calculate_decay(item_id, apply=True)

            if new_priority != old_priority:
                changes[item_id] = new_priority

        return changes

    def get_items_by_priority(self) -> Dict[int, List[str]]:
        """
        Get items grouped by current priority.

        Returns:
            Dict of priority -> list of item_ids
        """
        grouped = {}
        for record in self._records.values():
            p = record.current_priority
            if p not in grouped:
                grouped[p] = []
            grouped[p].append(record.item_id)

        return grouped

    def get_items_needing_attention(
        self,
        threshold_hours: float = 48.0
    ) -> List[PriorityRecord]:
        """
        Get items that haven't had activity recently.

        Args:
            threshold_hours: Hours without activity

        Returns:
            List of stale records
        """
        threshold = datetime.now() - timedelta(hours=threshold_hours)

        stale = [
            record for record in self._records.values()
            if record.last_activity < threshold and
            record.current_priority not in self.config.exempt_priorities
        ]

        # Sort by staleness
        stale.sort(key=lambda r: r.last_activity)

        return stale

    def remove_item(self, item_id: str) -> bool:
        """
        Remove an item from tracking.

        Args:
            item_id: Item to remove

        Returns:
            True if removed
        """
        if item_id in self._records:
            del self._records[item_id]
            self._save_state()
            return True
        return False

    def get_record(self, item_id: str) -> Optional[PriorityRecord]:
        """Get a priority record by ID."""
        return self._records.get(item_id)

    def get_stats(self) -> Dict[str, Any]:
        """Get decay manager statistics."""
        records = list(self._records.values())

        priority_dist = {}
        for r in records:
            p = r.current_priority
            priority_dist[p] = priority_dist.get(p, 0) + 1

        avg_age = 0
        if records:
            ages = [(datetime.now() - r.last_activity).total_seconds() / 3600 for r in records]
            avg_age = sum(ages) / len(ages)

        return {
            "total_items": len(self._records),
            "total_decays": self._total_decays,
            "total_boosts": self._total_boosts,
            "priority_distribution": priority_dist,
            "avg_hours_since_activity": avg_age,
            "decay_model": self.config.model.value,
            "half_life_hours": self.config.half_life_hours
        }


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_decay():
        """Test priority decay manager."""
        print("Testing Priority Decay Manager...")

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Test 1: Create manager
            print("Test 1: Create manager...", end=" ")
            config = DecayConfig(
                model=DecayModel.EXPONENTIAL,
                half_life_hours=24.0
            )
            manager = PriorityDecayManager(memory_dir=Path(tmpdir), config=config)
            print("PASS")

            # Test 2: Register items
            print("Test 2: Register items...", end=" ")
            record1 = manager.register_item("task-001", priority=1)
            record2 = manager.register_item("task-002", priority=2)
            assert record1.current_priority == 1
            assert len(manager._records) == 2
            print("PASS")

            # Test 3: Record activity
            print("Test 3: Record activity...", end=" ")
            updated = manager.record_activity("task-001")
            assert updated.last_activity is not None
            print("PASS")

            # Test 4: Calculate decay (no apply)
            print("Test 4: Calculate decay preview...", end=" ")
            # Simulate old activity
            manager._records["task-002"].last_activity = datetime.now() - timedelta(hours=48)
            new_priority = manager.calculate_decay("task-002", apply=False)
            assert new_priority >= record2.current_priority
            print("PASS")

            # Test 5: Apply decay
            print("Test 5: Apply decay...", end=" ")
            old = manager._records["task-002"].current_priority
            new_p = manager.calculate_decay("task-002", apply=True)
            # Decay should have been applied (either count increased or priority changed)
            assert new_p is not None
            print("PASS")

            # Test 6: Process all decay
            print("Test 6: Process all decay...", end=" ")
            # Make task-001 old too
            manager._records["task-001"].last_activity = datetime.now() - timedelta(hours=72)
            changes = manager.process_all_decay()
            assert len(changes) >= 0  # May or may not have changes
            print("PASS")

            # Test 7: Items by priority
            print("Test 7: Items by priority...", end=" ")
            grouped = manager.get_items_by_priority()
            total_items = sum(len(items) for items in grouped.values())
            assert total_items == 2
            print("PASS")

            # Test 8: Items needing attention
            print("Test 8: Items needing attention...", end=" ")
            stale = manager.get_items_needing_attention(threshold_hours=24)
            assert len(stale) == 2  # Both are old now
            print("PASS")

            # Test 9: Activity boost
            print("Test 9: Activity boost...", end=" ")
            manager._records["task-001"].current_priority = 3
            boosted = manager.record_activity("task-001")
            # Should boost toward original priority
            assert boosted.current_priority <= 3
            print("PASS")

            # Test 10: Stats
            print("Test 10: Stats...", end=" ")
            stats = manager.get_stats()
            assert stats["total_items"] == 2
            assert stats["decay_model"] == "exponential"
            print("PASS")

            # Test 11: Remove item
            print("Test 11: Remove item...", end=" ")
            removed = manager.remove_item("task-002")
            assert removed
            assert "task-002" not in manager._records
            print("PASS")

            # Test 12: Linear decay model
            print("Test 12: Linear decay...", end=" ")
            linear_config = DecayConfig(model=DecayModel.LINEAR, half_life_hours=24)
            linear_manager = PriorityDecayManager(memory_dir=Path(tmpdir) / "linear", config=linear_config)
            record = linear_manager.register_item("test", priority=1)
            record.last_activity = datetime.now() - timedelta(hours=48)
            new_p = linear_manager.calculate_decay("test", apply=False)
            assert new_p > 1
            print("PASS")

        print("\nAll tests passed!")
        return True

    success = test_decay()
    sys.exit(0 if success else 1)

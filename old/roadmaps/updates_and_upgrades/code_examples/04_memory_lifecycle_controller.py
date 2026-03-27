"""Example: memory lifecycle policy under footprint pressure.

Integration target:
- src/core/services/memory_service.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class MemoryFootprint:
    total_bytes: int
    budget_bytes: int


def utilization(fp: MemoryFootprint) -> float:
    if fp.budget_bytes <= 0:
        return 0.0
    return max(0.0, fp.total_bytes / fp.budget_bytes)


def lifecycle_actions(fp: MemoryFootprint) -> List[str]:
    u = utilization(fp)
    actions: List[str] = []

    if u < 0.70:
        actions.append("normal_ingest")
        return actions

    if u < 0.85:
        actions.extend([
            "summarize_recent_episodes",
            "compress_low_value_context",
            "seal_memvid_segments",
        ])
        return actions

    if u < 1.00:
        actions.extend([
            "aggressive_summarize",
            "archive_older_low_access_memories",
            "promote_structured_facts_to_graph_only",
        ])
        return actions

    actions.extend([
        "stop_nonessential_ingest",
        "archive_low_importance_chunks",
        "forget_expired_ephemeral_items",
        "emit_memory_pressure_alert",
    ])
    return actions


def lifecycle_event(fp: MemoryFootprint) -> Dict[str, object]:
    u = utilization(fp)
    return {
        "utilization": round(u, 4),
        "total_bytes": fp.total_bytes,
        "budget_bytes": fp.budget_bytes,
        "actions": lifecycle_actions(fp),
    }


if __name__ == "__main__":
    sample = MemoryFootprint(total_bytes=900_000_000, budget_bytes=1_073_741_824)
    print(lifecycle_event(sample))

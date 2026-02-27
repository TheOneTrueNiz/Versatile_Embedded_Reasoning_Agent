"""Example: predictive tool-chain scoring before execution.

Integration targets:
- src/orchestration/llm_bridge.py
- src/core/runtime/tool_orchestrator.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


@dataclass
class ChainCandidate:
    tools: List[str]
    estimated_steps: int


@dataclass
class ChainStats:
    success_rate: float
    avg_latency_s: float
    timeout_rate: float


def score_chain(candidate: ChainCandidate, stats: ChainStats) -> float:
    """Higher is better.

    Basic score: favor high success, low latency, low timeout, short chains.
    """
    reliability = max(0.0, min(1.0, stats.success_rate))
    timeout_penalty = max(0.0, min(1.0, stats.timeout_rate))
    latency_penalty = min(1.0, stats.avg_latency_s / 60.0)
    step_penalty = min(1.0, max(0, candidate.estimated_steps - 1) / 6.0)
    return reliability - (0.45 * timeout_penalty) - (0.25 * latency_penalty) - (0.15 * step_penalty)


def pick_best_chain(candidates: Iterable[Tuple[ChainCandidate, ChainStats]]) -> Tuple[ChainCandidate, float]:
    best: Tuple[ChainCandidate, float] | None = None
    for candidate, stats in candidates:
        value = score_chain(candidate, stats)
        if best is None or value > best[1]:
            best = (candidate, value)
    if best is None:
        raise ValueError("no chain candidates")
    return best


if __name__ == "__main__":
    options = [
        (
            ChainCandidate(tools=["search_web", "extract_structured_data"], estimated_steps=2),
            ChainStats(success_rate=0.79, avg_latency_s=8.4, timeout_rate=0.03),
        ),
        (
            ChainCandidate(tools=["search_web", "browser_automation", "extract_structured_data"], estimated_steps=3),
            ChainStats(success_rate=0.69, avg_latency_s=19.2, timeout_rate=0.11),
        ),
    ]
    chain, score = pick_best_chain(options)
    print({"chain": chain.tools, "score": round(score, 4)})

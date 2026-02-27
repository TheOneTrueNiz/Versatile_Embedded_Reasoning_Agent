"""Example: explainable budget-guard reason formatting.

Integration targets:
- src/observability/self_improvement_budget.py
- src/core/runtime/proactive_manager.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass
class BudgetSnapshot:
    calls: int
    tokens_used: int
    spent_usd: float


@dataclass
class BudgetLimit:
    daily_call_budget: int
    daily_token_budget: int
    daily_budget_usd: float


def explain_budget_guard(snapshot: BudgetSnapshot, limit: BudgetLimit) -> Tuple[bool, str]:
    if snapshot.calls >= limit.daily_call_budget:
        return False, f"daily_call_budget_exceeded({snapshot.calls}/{limit.daily_call_budget})"
    if snapshot.tokens_used >= limit.daily_token_budget:
        return False, f"daily_token_budget_exceeded({snapshot.tokens_used}/{limit.daily_token_budget})"
    if snapshot.spent_usd >= limit.daily_budget_usd:
        return False, f"daily_budget_usd_exceeded({snapshot.spent_usd:.3f}/{limit.daily_budget_usd:.3f})"
    return True, "ok"


def status_payload(snapshot: BudgetSnapshot, limit: BudgetLimit) -> Dict[str, object]:
    allowed, reason = explain_budget_guard(snapshot, limit)
    return {
        "allowed": allowed,
        "reason": reason,
        "budget_snapshot": {
            "calls": snapshot.calls,
            "tokens_used": snapshot.tokens_used,
            "spent_usd": round(snapshot.spent_usd, 6),
        },
        "budget_limit": {
            "daily_call_budget": limit.daily_call_budget,
            "daily_token_budget": limit.daily_token_budget,
            "daily_budget_usd": round(limit.daily_budget_usd, 6),
        },
    }


if __name__ == "__main__":
    snap = BudgetSnapshot(calls=7, tokens_used=5089, spent_usd=0.033651)
    lim = BudgetLimit(daily_call_budget=24, daily_token_budget=50000, daily_budget_usd=3.0)
    print(status_payload(snap, lim))

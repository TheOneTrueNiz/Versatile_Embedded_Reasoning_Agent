"""Example: autonomy kernel orchestrator with recovery-first execution policy.

Integration targets:
- src/core/runtime/proactive_manager.py
- src/core/runtime/vera.py
- src/planning/sentinel_engine.py
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionType(str, Enum):
    REACHOUT = "reachout"
    FOLLOWTHROUGH = "followthrough"
    REFLECT = "reflect"
    DEFER = "defer"


@dataclass
class RuntimeSignals:
    budget_remaining: int
    cooldown_active: bool
    recent_failures: int
    recovery_failures: int
    stale_commitments: int
    quiet_hours_active: bool


@dataclass
class AutonomyDecision:
    action: ActionType
    reason: str
    workflow_id: str = ""
    metadata: Optional[Dict[str, Any]] = None


def choose_action(signals: RuntimeSignals) -> AutonomyDecision:
    # Hard safety gates first.
    if signals.quiet_hours_active:
        return AutonomyDecision(action=ActionType.DEFER, reason="quiet_hours")
    if signals.budget_remaining <= 0:
        return AutonomyDecision(action=ActionType.DEFER, reason="daily_budget_exhausted")
    if signals.cooldown_active:
        return AutonomyDecision(action=ActionType.DEFER, reason="cooldown_active")

    # Recovery path takes precedence over fresh initiatives.
    if signals.stale_commitments > 0:
        return AutonomyDecision(
            action=ActionType.FOLLOWTHROUGH,
            reason="stale_commitment_recovery",
            workflow_id="followthrough.recover_next",
        )

    if signals.recent_failures >= 2:
        return AutonomyDecision(
            action=ActionType.REFLECT,
            reason="failure_cluster_detected",
            workflow_id="reflection.failure_analysis",
        )

    return AutonomyDecision(
        action=ActionType.REACHOUT,
        reason="initiative_window_open",
        workflow_id="initiative.partner_checkin",
    )


def execute_with_fallback(decision: AutonomyDecision, context: Dict[str, Any]) -> Dict[str, Any]:
    """Stub execution contract.

    Real implementation should map workflow_id to the existing orchestrator hooks.
    """

    result: Dict[str, Any] = {
        "ok": False,
        "action": decision.action.value,
        "reason": decision.reason,
        "workflow_id": decision.workflow_id,
        "fallback_used": False,
        "error": "",
    }

    try:
        if decision.action == ActionType.DEFER:
            result["ok"] = True
            result["error"] = ""
            return result

        # Replace with actual orchestrator call.
        primary_ok = bool(context.get("primary_executor_ok", True))
        if primary_ok:
            result["ok"] = True
            return result

        # Recovery branch: swap to a conservative workflow.
        result["fallback_used"] = True
        result["workflow_id"] = "reflection.stabilize_then_retry"
        fallback_ok = bool(context.get("fallback_executor_ok", True))
        result["ok"] = fallback_ok
        if not fallback_ok:
            result["error"] = "fallback_failed"
        return result
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
        return result


def run_once(signals: RuntimeSignals, context: Dict[str, Any]) -> Dict[str, Any]:
    decision = choose_action(signals)
    outcome = execute_with_fallback(decision, context)
    outcome["decision_reason"] = decision.reason
    return outcome


if __name__ == "__main__":
    sample = RuntimeSignals(
        budget_remaining=3,
        cooldown_active=False,
        recent_failures=0,
        recovery_failures=0,
        stale_commitments=1,
        quiet_hours_active=False,
    )
    print(run_once(sample, {"primary_executor_ok": True}))

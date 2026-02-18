"""
Safety Manager
==============

Encapsulates decision logging, cost tracking, reversibility, provenance, and
response critique/post-processing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from observability.cost_tracker import CostTracker
from observability.decision_ledger import DecisionLedger, DecisionType
from observability.provenance import ProvenanceTracker, SourceType
from observability.reversibility import ReversibilityTracker
from safety.internal_critic import InternalCritic, CritiqueResult

logger = logging.getLogger(__name__)


class SafetyManager:
    """Safety subsystem extracted from VERA."""

    def __init__(self, owner: Any, memory_dir: Path, config: Any) -> None:
        self._owner = owner

        self.decision_ledger = DecisionLedger(memory_dir=memory_dir)
        owner.decision_ledger = self.decision_ledger

        self.provenance = ProvenanceTracker(storage_path=memory_dir / "provenance.ndjson")
        owner.provenance = self.provenance

        configured_budget = getattr(config, "session_budget", None)
        budget_env = os.getenv("VERA_SESSION_BUDGET_USD", "25.0").strip()
        soft_env = os.getenv("VERA_SESSION_BUDGET_SOFT_RATIO", "0.6").strip()
        hard_env = os.getenv("VERA_SESSION_BUDGET_HARD_RATIO", "0.95").strip()
        try:
            session_budget = float(configured_budget) if configured_budget is not None else float(budget_env)
        except Exception:
            session_budget = 25.0
        try:
            soft_limit_ratio = float(soft_env)
        except Exception:
            soft_limit_ratio = 0.6
        try:
            hard_limit_ratio = float(hard_env)
        except Exception:
            hard_limit_ratio = 0.95
        if session_budget <= 0:
            session_budget = 25.0
        self.cost_tracker = CostTracker(
            session_budget=session_budget,
            soft_limit_ratio=soft_limit_ratio,
            hard_limit_ratio=hard_limit_ratio,
        )
        owner.cost_tracker = self.cost_tracker

        self.reversibility = ReversibilityTracker(memory_dir=memory_dir)
        owner.reversibility = self.reversibility

        self.critic = InternalCritic(
            strictness="balanced",
            target_tone="professional",
        )
        owner.critic = self.critic

    def __getattr__(self, name: str) -> Any:
        return getattr(self._owner, name)

    def log_decision(
        self,
        decision_type: DecisionType,
        action: str,
        reasoning: str,
        alternatives: list | None = None,
        confidence: float = 0.8,
        context: dict | None = None,
    ) -> str:
        """Log a decision to the decision ledger."""
        return self.decision_ledger.log_decision(
            decision_type=decision_type,
            action=action,
            reasoning=reasoning,
            alternatives=alternatives or [],
            confidence=confidence,
            context=context or {},
        )

    def record_tool_cost(
        self,
        tool_name: str,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cached: bool = False,
    ) -> dict:
        """Record tool usage cost and return budget status."""
        if tokens_in is None:
            tokens_in = input_tokens or 0
        if tokens_out is None:
            tokens_out = output_tokens or 0

        self.cost_tracker.record_usage(
            tool_name=tool_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cached=cached,
        )
        return self.cost_tracker.check_budget()

    def track_file_operation(self, filepath: Path, operation: str = "write") -> Optional[str]:
        """Track a file operation for potential reversal."""
        if operation == "write":
            return self.reversibility.track_file_write(filepath)
        if operation == "delete":
            return self.reversibility.track_file_delete(filepath)
        return None

    def stamp_source(
        self,
        source_type: SourceType,
        source_id: str,
        content: str,
        confidence: float = 0.9,
    ) -> str:
        """Stamp information with provenance."""
        stamp = self.provenance.stamp(
            source_type=source_type,
            source_id=source_id,
            content=content,
            confidence=confidence,
        )
        return stamp.id

    def critique_response(self, response: str, context: dict | None = None) -> CritiqueResult:
        """Self-critique a response before sending."""
        return self.critic.review(response, context or {})

    def postprocess_response(self, response: str, context: dict | None = None) -> str:
        """Run internal post-processing on a response before delivery."""
        if not response:
            return response
        if os.getenv("VERA_CRITIC_ENABLED", "1").lower() not in {"1", "true", "yes", "on"}:
            return response
        try:
            critique = self.critique_response(response, context or {})
        except Exception as exc:
            logger.debug("Internal critic failed: %s", exc)
            return response
        if critique.needs_revision and critique.improved_response:
            return critique.improved_response
        if critique.needs_revision:
            logger.debug("Internal critic flagged issues but produced no rewrite.")
        return response

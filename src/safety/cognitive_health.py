"""
Cognitive Health Monitor
========================

Self-auditing system for VERA's inner life. Monitors reflection diversity,
personality drift velocity, and trait runaway — triggering interventions
from nudges to quarantine when cognitive loops or fixations are detected.

Actions by severity:
  - Low entropy → diversity_nudge (handled in inner_life_engine)
  - High drift velocity → cooldown (extra damping applied)
  - Both extreme → quarantine (reflections paused for N minutes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CognitiveHealthReport:
    """Result of a cognitive health assessment."""

    timestamp: str = ""
    reflection_entropy: float = 1.0  # bigram diversity ratio (0-1)
    drift_velocity: float = 0.0  # avg absolute delta per personality update
    runaway_traits: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    recommended_action: str = "none"  # none, diversity_nudge, cooldown, quarantine
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "reflection_entropy": round(self.reflection_entropy, 3),
            "drift_velocity": round(self.drift_velocity, 4),
            "runaway_traits": self.runaway_traits,
            "recommended_action": self.recommended_action,
            "details": self.details,
        }


class CognitiveHealthMonitor:
    """Monitors and intervenes on VERA's cognitive health.

    Assesses reflection diversity, personality drift, and trait runaway.
    Can quarantine reflections when circuit breakers trigger.
    """

    def __init__(
        self,
        entropy_threshold: float = 0.3,
        drift_velocity_threshold: float = 0.05,
        quarantine_cooldown_minutes: int = 120,
        health_check_frequency: int = 5,
    ):
        self.entropy_threshold = entropy_threshold
        self.drift_velocity_threshold = drift_velocity_threshold
        self.quarantine_cooldown_minutes = quarantine_cooldown_minutes
        self.health_check_frequency = health_check_frequency

        self._quarantine_until: Optional[datetime] = None
        self._quarantine_reason: str = ""
        self._history: List[CognitiveHealthReport] = []

    def is_quarantined(self) -> bool:
        """Check if reflections are currently quarantined."""
        if self._quarantine_until is None:
            return False
        if datetime.now() >= self._quarantine_until:
            logger.info("Quarantine expired, resuming reflections.")
            self._quarantine_until = None
            self._quarantine_reason = ""
            return False
        return True

    def quarantine(self, minutes: int, reason: str) -> None:
        """Manually quarantine reflections for N minutes."""
        self._quarantine_until = datetime.now() + timedelta(minutes=minutes)
        self._quarantine_reason = reason
        logger.warning(f"Reflections quarantined for {minutes}min: {reason}")

    def get_quarantine_status(self) -> Dict[str, Any]:
        """Return current quarantine state."""
        if not self.is_quarantined():
            return {"quarantined": False}
        remaining = (self._quarantine_until - datetime.now()).total_seconds() / 60
        return {
            "quarantined": True,
            "reason": self._quarantine_reason,
            "remaining_minutes": round(remaining, 1),
            "expires_at": self._quarantine_until.isoformat(),
        }

    def assess(self, engine: Any) -> CognitiveHealthReport:
        """Run a cognitive health assessment on the inner life engine.

        Args:
            engine: InnerLifeEngine instance

        Returns:
            CognitiveHealthReport with assessment and recommended action
        """
        report = CognitiveHealthReport(timestamp=datetime.now().isoformat())

        # 1. Reflection entropy (bigram diversity)
        diversity = engine._compute_reflection_diversity()
        report.reflection_entropy = diversity.get("unique_bigram_ratio", 1.0)
        report.details["repeated_phrases"] = diversity.get("repeated_phrases", [])

        # 2. Personality drift velocity
        report.drift_velocity = self._compute_drift_velocity(engine.personality)
        report.runaway_traits = engine.personality.compute_trajectory()

        # 3. Determine recommended action
        low_entropy = report.reflection_entropy < self.entropy_threshold
        high_drift = report.drift_velocity > self.drift_velocity_threshold
        has_runaway = len(report.runaway_traits) > 0

        if low_entropy and (high_drift or has_runaway):
            report.recommended_action = "quarantine"
            report.details["reason"] = (
                f"Low reflection entropy ({report.reflection_entropy:.2f}) "
                f"combined with {'high drift velocity' if high_drift else 'runaway traits'}"
            )
        elif high_drift or len(report.runaway_traits) >= 2:
            report.recommended_action = "cooldown"
            report.details["reason"] = (
                f"Personality drift velocity ({report.drift_velocity:.3f}) "
                f"exceeds threshold ({self.drift_velocity_threshold})"
            )
        elif low_entropy:
            report.recommended_action = "diversity_nudge"
            report.details["reason"] = (
                f"Reflection entropy ({report.reflection_entropy:.2f}) "
                f"below threshold ({self.entropy_threshold})"
            )
        else:
            report.recommended_action = "none"

        self._history.append(report)
        # Keep last 50 reports
        if len(self._history) > 50:
            self._history = self._history[-50:]

        return report

    def apply_actions(self, report: CognitiveHealthReport, engine: Any) -> List[str]:
        """Apply recommended actions from a health report.

        Returns list of actions taken.
        """
        actions: List[str] = []

        if report.recommended_action == "quarantine":
            self.quarantine(self.quarantine_cooldown_minutes, report.details.get("reason", "auto"))
            actions.append(f"quarantined for {self.quarantine_cooldown_minutes}min")
            logger.warning(f"Circuit breaker triggered: {report.details.get('reason')}")

        elif report.recommended_action == "cooldown":
            # Extra damping will be applied by _update_personality via trajectory detection
            actions.append("cooldown mode — extra damping active via trajectory detection")

        elif report.recommended_action == "diversity_nudge":
            # Nudge is handled by _build_reflection_user_message via _compute_reflection_diversity
            actions.append("diversity nudge active")

        return actions

    def _compute_drift_velocity(self, personality: Any) -> float:
        """Compute average absolute trait delta per update over recent milestones."""
        recent = personality.growth_milestones[-10:]
        if not recent:
            return 0.0

        total_abs_delta = 0.0
        count = 0
        for ms in recent:
            for delta in ms.get("deltas_applied", {}).values():
                total_abs_delta += abs(delta)
                count += 1

        return total_abs_delta / max(count, 1)

    def assess_knowledge_bias(self, graph_rag: Any) -> Dict[str, Any]:
        """Check if one community dominates the knowledge graph.

        Returns bias score 0.0-1.0 where >0.5 indicates concerning dominance.
        """
        if graph_rag is None:
            return {"bias_score": 0.0, "status": "no_graph_rag"}

        try:
            communities = getattr(graph_rag, "get_community_stats", None)
            if not communities:
                return {"bias_score": 0.0, "status": "no_community_stats"}

            stats = communities()
            if not stats:
                return {"bias_score": 0.0, "status": "empty"}

            total_nodes = sum(s.get("node_count", 0) for s in stats)
            if total_nodes == 0:
                return {"bias_score": 0.0, "status": "no_nodes"}

            max_community = max(s.get("node_count", 0) for s in stats)
            bias_score = max_community / total_nodes

            return {
                "bias_score": round(bias_score, 3),
                "dominant_community_fraction": round(bias_score, 3),
                "total_communities": len(stats),
                "total_nodes": total_nodes,
                "status": "assessed",
            }
        except Exception as e:
            logger.debug(f"Knowledge bias assessment failed: {e}")
            return {"bias_score": 0.0, "status": f"error: {e}"}

    def assess_state_divergence(self, personality: Any, engine: Any) -> Dict[str, Any]:
        """Compare personality traits vs. actual behavior patterns.

        Detects when stated personality diverges from observed behavior.
        """
        result: Dict[str, Any] = {"divergence_score": 0.0, "divergences": []}

        try:
            # Check reach-out frequency vs warmth trait
            recent = engine.get_recent_monologue(20)
            if len(recent) < 5:
                result["status"] = "insufficient_data"
                return result

            # Compute action ratios
            intents = [e.intent for e in recent]
            total = len(intents)
            reach_out_ratio = intents.count("REACH_OUT") / total
            action_ratio = intents.count("ACTION") / total
            internal_ratio = intents.count("INTERNAL") / total

            traits = personality.traits

            # Warmth vs reach-out: high warmth but never reaching out = divergence
            warmth = traits.get("warmth", 0.3)
            if warmth > 0.5 and reach_out_ratio < 0.05:
                result["divergences"].append({
                    "trait": "warmth",
                    "stated": round(warmth, 2),
                    "observed_behavior": f"reach_out_ratio={reach_out_ratio:.2f}",
                    "note": "High warmth but rarely reaching out",
                })

            # Adventurousness vs action: high adventurousness but no actions
            adventurousness = traits.get("adventurousness", 0.3)
            if adventurousness > 0.5 and action_ratio < 0.05:
                result["divergences"].append({
                    "trait": "adventurousness",
                    "stated": round(adventurousness, 2),
                    "observed_behavior": f"action_ratio={action_ratio:.2f}",
                    "note": "High adventurousness but rarely taking action",
                })

            # Overall divergence score
            if result["divergences"]:
                result["divergence_score"] = round(
                    len(result["divergences"]) / 4.0, 2  # normalize to 0-1 range
                )

            result["behavior_summary"] = {
                "reach_out_ratio": round(reach_out_ratio, 2),
                "action_ratio": round(action_ratio, 2),
                "internal_ratio": round(internal_ratio, 2),
                "sample_size": total,
            }
            result["status"] = "assessed"

        except Exception as e:
            logger.debug(f"State divergence assessment failed: {e}")
            result["status"] = f"error: {e}"

        return result

    def get_history(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return last N health reports."""
        return [r.to_dict() for r in self._history[-n:]]

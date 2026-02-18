#!/usr/bin/env python3
"""
Consensus Engine - VERA Quorum System
======================================

Implements 5 consensus algorithms for aggregating agent outputs:

1. Majority Vote - Simple 50%+ approval (Secretarial, Integration)
2. Weighted Scoring - Weighted average with threshold (Todo/Task)
3. Synthesis - Merge all contributions (Creative, Research)
4. Veto Authority - One agent can block unilaterally (Safety)
5. Threshold Consensus - Variable threshold by risk (Custom quorums)

Each algorithm optimized for specific decision contexts.
"""

from enum import Enum
from typing import Dict, Any
from dataclasses import dataclass


class Vote(Enum):
    """Agent vote options"""
    APPROVE = "approve"
    REJECT = "reject"
    ABSTAIN = "abstain"


class Decision(Enum):
    """Final decision outcomes"""
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATE = "escalate"  # Tie or unclear -> ask user


@dataclass
class ConsensusResult:
    """
    Result of consensus process

    Attributes:
        decision: Final decision (approved/rejected/escalate)
        algorithm: Which algorithm was used
        details: Algorithm-specific details (vote counts, scores, etc.)
        explanation: Human-readable explanation
        agent_contributions: Individual agent inputs
    """
    decision: Decision
    algorithm: str
    details: Dict[str, Any]
    explanation: str
    agent_contributions: Dict[str, Any]


class ConsensusAlgorithm(Enum):
    """Available consensus algorithms"""
    MAJORITY_VOTE = "majority_vote"
    WEIGHTED_SCORING = "weighted_scoring"
    SYNTHESIS = "synthesis"
    VETO_AUTHORITY = "veto_authority"
    THRESHOLD_CONSENSUS = "threshold_consensus"


class ConsensusEngine:
    """
    Aggregates agent outputs using various consensus algorithms

    Usage:
        engine = ConsensusEngine()

        # Majority vote
        votes = {"Planner": Vote.APPROVE, "Optimizer": Vote.APPROVE, "Safety": Vote.ABSTAIN}
        result = engine.majority_vote(votes)

        # Weighted scoring
        scores = {"Planner": 80, "Optimizer": 70, "Skeptic": 50}
        weights = {"Planner": 0.4, "Optimizer": 0.4, "Skeptic": 0.2}
        result = engine.weighted_scoring(scores, weights, threshold=60)

        # Veto authority
        votes = {"Safety": Vote.REJECT, "Planner": Vote.APPROVE}
        result = engine.veto_authority(votes, veto_agent="Safety")
    """

    # ========================================================================
    # ALGORITHM 1: MAJORITY VOTE
    # ========================================================================

    def majority_vote(self, votes: Dict[str, Vote]) -> ConsensusResult:
        """
        Simple majority: 50%+ approvals required

        Used by: Secretarial, Integration quorums

        Logic:
        - Count approve/reject votes (abstain excluded)
        - Approve if approvals > rejections
        - Reject if rejections > approvals
        - Escalate if tie or all abstained

        Args:
            votes: Agent name -> Vote

        Returns:
            ConsensusResult with decision
        """
        approvals = sum(1 for v in votes.values() if v == Vote.APPROVE)
        rejections = sum(1 for v in votes.values() if v == Vote.REJECT)
        abstentions = sum(1 for v in votes.values() if v == Vote.ABSTAIN)

        total_voting = approvals + rejections

        # Decision logic
        if total_voting == 0:
            decision = Decision.ESCALATE
            explanation = "All agents abstained - escalating to user"
        elif approvals > rejections:
            decision = Decision.APPROVED
            explanation = f"Majority vote: {approvals} approve vs {rejections} reject"
        elif rejections > approvals:
            decision = Decision.REJECTED
            explanation = f"Majority vote: {rejections} reject vs {approvals} approve"
        else:
            decision = Decision.ESCALATE
            explanation = f"Tie vote: {approvals}-{rejections} - escalating to user"

        return ConsensusResult(
            decision=decision,
            algorithm="majority_vote",
            details={
                "approvals": approvals,
                "rejections": rejections,
                "abstentions": abstentions,
                "total_voting": total_voting,
                "votes": {agent: vote.value for agent, vote in votes.items()}
            },
            explanation=explanation,
            agent_contributions=votes
        )

    # ========================================================================
    # ALGORITHM 2: WEIGHTED SCORING
    # ========================================================================

    def weighted_scoring(
        self,
        scores: Dict[str, float],
        weights: Dict[str, float],
        threshold: float = 60.0
    ) -> ConsensusResult:
        """
        Weighted average with threshold

        Used by: Todo/Task quorum

        Logic:
        - Each agent assigns score 0-100
        - Multiply by agent weight (sum to 1.0)
        - Approve if weighted_sum >= threshold

        Args:
            scores: Agent name -> score (0-100)
            weights: Agent name -> weight (should sum to ~1.0)
            threshold: Approval threshold (default 60)

        Returns:
            ConsensusResult with decision
        """
        # Validate weights sum to ~1.0
        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > 0.01:
            # Normalize if needed
            weights = {agent: w / weight_sum for agent, w in weights.items()}

        # Calculate weighted score
        weighted_sum = sum(scores[agent] * weights[agent] for agent in scores)

        # Decision
        if weighted_sum >= threshold:
            decision = Decision.APPROVED
            explanation = f"Weighted score {weighted_sum:.1f} >= threshold {threshold}"
        else:
            decision = Decision.REJECTED
            explanation = f"Weighted score {weighted_sum:.1f} < threshold {threshold}"

        # Breakdown by agent
        contributions = {
            agent: {
                "score": scores[agent],
                "weight": weights[agent],
                "contribution": scores[agent] * weights[agent]
            }
            for agent in scores
        }

        return ConsensusResult(
            decision=decision,
            algorithm="weighted_scoring",
            details={
                "weighted_sum": weighted_sum,
                "threshold": threshold,
                "weights": weights,
                "scores": scores,
                "contributions": contributions
            },
            explanation=explanation,
            agent_contributions=contributions
        )

    # ========================================================================
    # ALGORITHM 3: SYNTHESIS (NO VOTING)
    # ========================================================================

    def synthesis(self, outputs: Dict[str, str]) -> ConsensusResult:
        """
        Merge all agent contributions (no voting)

        Used by: Creative, Research quorums

        Logic:
        - All contributions are valuable
        - No rejection possible
        - Combine into single output

        Args:
            outputs: Agent name -> output text

        Returns:
            ConsensusResult with synthesized output
        """
        # Combine all outputs
        combined_sections = []
        for agent, output in outputs.items():
            combined_sections.append(f"## {agent} Perspective\n\n{output}")

        synthesized = "\n\n".join(combined_sections)

        explanation = f"Synthesized {len(outputs)} agent perspectives (no voting)"

        return ConsensusResult(
            decision=Decision.APPROVED,  # Always approved in synthesis
            algorithm="synthesis",
            details={
                "num_agents": len(outputs),
                "agents": list(outputs.keys()),
                "synthesized_output": synthesized
            },
            explanation=explanation,
            agent_contributions=outputs
        )

    # ========================================================================
    # ALGORITHM 4: VETO AUTHORITY
    # ========================================================================

    def veto_authority(
        self,
        votes: Dict[str, Vote],
        veto_agent: str
    ) -> ConsensusResult:
        """
        One agent can unilaterally block

        Used by: Safety quorum

        Logic:
        - If veto_agent votes REJECT -> entire quorum rejects
        - Otherwise proceed with majority vote
        - Prevents catastrophic decisions

        Args:
            votes: Agent name -> Vote
            veto_agent: Name of agent with veto power

        Returns:
            ConsensusResult with decision
        """
        if veto_agent not in votes:
            raise ValueError(f"Veto agent '{veto_agent}' not in votes")

        # Check for veto
        if votes[veto_agent] == Vote.REJECT:
            decision = Decision.REJECTED
            explanation = f"VETO by {veto_agent} - decision blocked regardless of other votes"

            return ConsensusResult(
                decision=decision,
                algorithm="veto_authority",
                details={
                    "veto_exercised": True,
                    "veto_agent": veto_agent,
                    "votes": {agent: vote.value for agent, vote in votes.items()}
                },
                explanation=explanation,
                agent_contributions=votes
            )

        # No veto -> use majority vote on remaining agents
        other_votes = {agent: vote for agent, vote in votes.items() if agent != veto_agent}
        majority_result = self.majority_vote(other_votes)

        # Enhance explanation
        explanation = f"No veto by {veto_agent}. {majority_result.explanation}"

        return ConsensusResult(
            decision=majority_result.decision,
            algorithm="veto_authority",
            details={
                "veto_exercised": False,
                "veto_agent": veto_agent,
                "veto_vote": votes[veto_agent].value,
                "majority_result": majority_result.details
            },
            explanation=explanation,
            agent_contributions=votes
        )

    # ========================================================================
    # ALGORITHM 5: THRESHOLD CONSENSUS
    # ========================================================================

    def threshold_consensus(
        self,
        votes: Dict[str, Vote],
        risk_level: int
    ) -> ConsensusResult:
        """
        Variable threshold based on risk level

        Used by: Custom quorums

        Logic:
        - Risk 1-2: Simple majority (K = ceil(N/2))
        - Risk 3-4: Supermajority (K = ceil(2N/3))
        - Risk 5: Unanimous (K = N) or escalate

        Args:
            votes: Agent name -> Vote
            risk_level: 1-5 (1=safe, 5=catastrophic)

        Returns:
            ConsensusResult with decision
        """
        approvals = sum(1 for v in votes.values() if v == Vote.APPROVE)
        rejections = sum(1 for v in votes.values() if v == Vote.REJECT)
        total = len(votes)

        # Determine threshold based on risk
        if risk_level <= 2:
            # Simple majority
            required = (total + 1) // 2
            threshold_desc = "simple majority"
        elif risk_level <= 4:
            # Supermajority (2/3)
            required = (2 * total + 2) // 3
            threshold_desc = "supermajority (2/3)"
        else:
            # Unanimous or escalate
            required = total
            threshold_desc = "unanimous"

        # Decision
        if approvals >= required:
            decision = Decision.APPROVED
            explanation = f"Risk {risk_level}: {approvals}/{total} approvals meets {threshold_desc} ({required} required)"
        elif risk_level == 5 and approvals > 0:
            # High risk but not unanimous -> escalate to user
            decision = Decision.ESCALATE
            explanation = f"Risk {risk_level}: {approvals}/{total} approvals insufficient for unanimous - escalating to user"
        else:
            decision = Decision.REJECTED
            explanation = f"Risk {risk_level}: {approvals}/{total} approvals fails {threshold_desc} ({required} required)"

        return ConsensusResult(
            decision=decision,
            algorithm="threshold_consensus",
            details={
                "risk_level": risk_level,
                "approvals": approvals,
                "rejections": rejections,
                "total": total,
                "required": required,
                "threshold_type": threshold_desc,
                "votes": {agent: vote.value for agent, vote in votes.items()}
            },
            explanation=explanation,
            agent_contributions=votes
        )

    # ========================================================================
    # DISPATCHER
    # ========================================================================

    def apply(
        self,
        algorithm: ConsensusAlgorithm,
        agent_outputs: Dict[str, Any],
        **kwargs
    ) -> ConsensusResult:
        """
        Apply specified consensus algorithm

        Args:
            algorithm: Which algorithm to use
            agent_outputs: Agent contributions (votes, scores, or text)
            **kwargs: Algorithm-specific parameters

        Returns:
            ConsensusResult

        Raises:
            ValueError: If algorithm unknown or invalid parameters
        """
        if algorithm == ConsensusAlgorithm.MAJORITY_VOTE:
            return self.majority_vote(agent_outputs)

        elif algorithm == ConsensusAlgorithm.WEIGHTED_SCORING:
            weights = kwargs.get("weights")
            threshold = kwargs.get("threshold", 60.0)
            if weights is None:
                raise ValueError("weighted_scoring requires 'weights' parameter")
            return self.weighted_scoring(agent_outputs, weights, threshold)

        elif algorithm == ConsensusAlgorithm.SYNTHESIS:
            return self.synthesis(agent_outputs)

        elif algorithm == ConsensusAlgorithm.VETO_AUTHORITY:
            veto_agent = kwargs.get("veto_agent")
            if veto_agent is None:
                raise ValueError("veto_authority requires 'veto_agent' parameter")
            return self.veto_authority(agent_outputs, veto_agent)

        elif algorithm == ConsensusAlgorithm.THRESHOLD_CONSENSUS:
            risk_level = kwargs.get("risk_level")
            if risk_level is None:
                raise ValueError("threshold_consensus requires 'risk_level' parameter")
            return self.threshold_consensus(agent_outputs, risk_level)

        else:
            raise ValueError(f"Unknown consensus algorithm: {algorithm}")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def parse_vote(text: str) -> Vote:
    """
    Parse agent response into Vote

    Args:
        text: Agent output text

    Returns:
        Vote (APPROVE/REJECT/ABSTAIN)

    Logic:
        - Look for keywords: approve, reject, abstain
        - Case-insensitive
        - Default to ABSTAIN if unclear
    """
    text_lower = text.lower()

    if "approve" in text_lower or "yes" in text_lower or "agree" in text_lower:
        return Vote.APPROVE
    elif "reject" in text_lower or "no" in text_lower or "disagree" in text_lower or "veto" in text_lower:
        return Vote.REJECT
    else:
        return Vote.ABSTAIN


def parse_score(text: str) -> float:
    """
    Parse agent response into numeric score

    Args:
        text: Agent output text

    Returns:
        Score (0-100)

    Logic:
        - Look for "score: XX" or "rating: XX"
        - Extract first number found
        - Clamp to 0-100 range
        - Default to 50 if unclear
    """
    import re

    # Look for score/rating patterns
    patterns = [
        r"score:\s*(\d+)",
        r"rating:\s*(\d+)",
        r"(\d+)/100",
        r"(\d+)\s*out\s*of\s*100",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            score = float(match.group(1))
            return max(0, min(100, score))  # Clamp to 0-100

    # No clear score found -> default to neutral
    return 50.0

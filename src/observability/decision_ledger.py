#!/usr/bin/env python3
"""
Decision Ledger
===============

Immutable, append-only log of significant decisions made by VERA.

Source: Ported from GROKSTAR's research ledger concept

Problem Solved:
- VERA makes decisions on behalf of the user (filtering, prioritizing, suggesting)
- Users need to trust and audit these decisions
- "Why did you do that?" should always have an answer

Solution:
- Append-only NDJSON log capturing every significant decision
- Records: what, why, alternatives considered, confidence, context
- Enables auditing and trust-building

Usage:
    from decision_ledger import DecisionLedger, DecisionType

    ledger = DecisionLedger()

    # Log a decision
    decision_id = ledger.log_decision(
        decision_type=DecisionType.TASK_PRIORITIZATION,
        action="Moved 'Review Q4' to top priority",
        reasoning="Due date is tomorrow, marked as P0 by user",
        alternatives=["Keep current order", "Ask user for confirmation"],
        confidence=0.92,
        context={"due_date": "2025-12-26", "original_priority": "P2"}
    )

    # Query decisions
    recent = ledger.get_recent(limit=10)
    by_type = ledger.get_by_type(DecisionType.EMAIL_FILTER)
"""

import json
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
import logging
logger = logging.getLogger(__name__)

# Import atomic operations
try:
    from atomic_io import atomic_ndjson_append, safe_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class DecisionType(Enum):
    """Categories of decisions VERA can make"""
    # Task management
    TASK_PRIORITIZATION = "task_prioritization"
    TASK_CREATION = "task_creation"
    TASK_COMPLETION = "task_completion"
    TASK_DELEGATION = "task_delegation"

    # Communication
    EMAIL_FILTER = "email_filter"
    EMAIL_DRAFT = "email_draft"
    MESSAGE_RESPONSE = "message_response"
    NOTIFICATION_SUPPRESS = "notification_suppress"

    # File operations
    FILE_MODIFICATION = "file_modification"
    FILE_ORGANIZATION = "file_organization"

    # Scheduling
    CALENDAR_CHANGE = "calendar_change"
    MEETING_RESCHEDULE = "meeting_reschedule"
    REMINDER_SET = "reminder_set"

    # System
    TOOL_SELECTION = "tool_selection"
    MODEL_ROUTING = "model_routing"
    QUORUM_CONSULTATION = "quorum_consultation"
    SAFETY_BLOCK = "safety_block"
    ERROR_RECOVERY = "error_recovery"

    # General
    RECOMMENDATION = "recommendation"
    INFORMATION_RETRIEVAL = "information_retrieval"
    OTHER = "other"


class ReversibilityStatus(Enum):
    """Whether a decision can be undone"""
    REVERSIBLE = "reversible"           # Can be fully undone
    PARTIALLY_REVERSIBLE = "partial"    # Some effects can be undone
    IRREVERSIBLE = "irreversible"       # Cannot be undone
    TIME_LIMITED = "time_limited"       # Can be undone within a window
    UNKNOWN = "unknown"


@dataclass
class Decision:
    """A logged decision"""
    id: str
    timestamp: str
    decision_type: str
    action: str
    reasoning: str
    alternatives: List[str]
    chosen_reason: str
    confidence: float
    context: Dict[str, Any]
    reversibility: str
    reverse_deadline: Optional[str]
    outcome: Optional[str] = None
    user_feedback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Decision':
        return cls(**data)


class DecisionLedger:
    """
    Immutable, append-only decision log.

    Stores decisions in NDJSON format for easy querying and auditing.
    """

    def __init__(self, ledger_path: Path = None, memory_dir: Path = None) -> None:
        """
        Initialize decision ledger.

        Args:
            ledger_path: Path to ledger file
            memory_dir: Base memory directory
        """
        if ledger_path:
            self.ledger_path = Path(ledger_path)
        elif memory_dir:
            self.ledger_path = Path(memory_dir) / "decisions.ndjson"
        else:
            self.ledger_path = Path("vera_memory/decisions.ndjson")

        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)

        # Decision counter for ID generation
        self._decision_count = self._count_existing_decisions()

    def _count_existing_decisions(self) -> int:
        """Count existing decisions in ledger"""
        if not self.ledger_path.exists():
            return 0

        try:
            content = self.ledger_path.read_text()
            return len([l for l in content.strip().split('\n') if l])
        except Exception:
            return 0

    def _generate_id(self) -> str:
        """Generate unique decision ID"""
        self._decision_count += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"DEC-{date_str}-{self._decision_count:04d}"

    def log_decision(
        self,
        decision_type: DecisionType,
        action: str,
        reasoning: str,
        alternatives: List[str] = None,
        chosen_reason: str = None,
        confidence: float = 0.8,
        context: Dict[str, Any] = None,
        reversibility: ReversibilityStatus = ReversibilityStatus.UNKNOWN,
        reverse_deadline: datetime = None
    ) -> str:
        """
        Log a decision to the ledger.

        Args:
            decision_type: Category of decision
            action: What was done
            reasoning: Why this action was chosen
            alternatives: Other options that were considered
            chosen_reason: Why this option was selected over alternatives
            confidence: Confidence level (0.0 - 1.0)
            context: Additional context (user state, relevant data)
            reversibility: Whether the action can be undone
            reverse_deadline: Deadline for reversal (if time-limited)

        Returns:
            Decision ID
        """
        decision = Decision(
            id=self._generate_id(),
            timestamp=datetime.now().isoformat(),
            decision_type=decision_type.value,
            action=action,
            reasoning=reasoning,
            alternatives=alternatives or [],
            chosen_reason=chosen_reason or reasoning,
            confidence=confidence,
            context=context or {},
            reversibility=reversibility.value,
            reverse_deadline=reverse_deadline.isoformat() if reverse_deadline else None
        )

        # Append to ledger
        self._append_decision(decision)

        return decision.id

    def _append_decision(self, decision: Decision) -> None:
        """Append decision to ledger file"""
        line = json.dumps(decision.to_dict(), default=str) + '\n'

        if HAS_ATOMIC:
            atomic_ndjson_append(self.ledger_path, decision.to_dict())
        else:
            with open(self.ledger_path, 'a') as f:
                f.write(line)

    def get_by_id(self, decision_id: str) -> Optional[Decision]:
        """Get a specific decision by ID"""
        for decision in self._iter_decisions():
            if decision.id == decision_id:
                return decision
        return None

    def get_recent(self, limit: int = 10) -> List[Decision]:
        """Get most recent decisions"""
        decisions = list(self._iter_decisions())
        return decisions[-limit:][::-1]  # Most recent first

    def get_by_type(
        self,
        decision_type: DecisionType,
        limit: int = 50
    ) -> List[Decision]:
        """Get decisions of a specific type"""
        matches = []
        for decision in self._iter_decisions():
            if decision.decision_type == decision_type.value:
                matches.append(decision)
                if len(matches) >= limit:
                    break
        return matches[::-1]  # Most recent first

    def get_by_date_range(
        self,
        start: datetime,
        end: datetime = None
    ) -> List[Decision]:
        """Get decisions within a date range"""
        end = end or datetime.now()
        matches = []

        for decision in self._iter_decisions():
            try:
                dt = datetime.fromisoformat(decision.timestamp)
                if start <= dt <= end:
                    matches.append(decision)
            except ValueError as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        return matches[::-1]

    def search(self, query: str, limit: int = 20) -> List[Decision]:
        """Search decisions by keyword"""
        query_lower = query.lower()
        matches = []

        for decision in self._iter_decisions():
            # Search in action, reasoning, and context
            searchable = (
                decision.action.lower() +
                decision.reasoning.lower() +
                json.dumps(decision.context).lower()
            )
            if query_lower in searchable:
                matches.append(decision)
                if len(matches) >= limit:
                    break

        return matches[::-1]

    def record_outcome(
        self,
        decision_id: str,
        outcome: str,
        user_feedback: str = None
    ) -> bool:
        """
        Record the outcome of a decision.

        Note: This doesn't modify the original entry (immutable),
        but appends a follow-up entry linking to the original.
        """
        original = self.get_by_id(decision_id)
        if not original:
            return False

        # Log outcome as a new decision referencing the original
        self.log_decision(
            decision_type=DecisionType.OTHER,
            action=f"Outcome recorded for {decision_id}",
            reasoning=outcome,
            context={
                "original_decision_id": decision_id,
                "original_action": original.action,
                "user_feedback": user_feedback
            },
            confidence=1.0
        )

        return True

    def _iter_decisions(self):
        """Iterate over all decisions in the ledger"""
        if not self.ledger_path.exists():
            return

        try:
            content = self.ledger_path.read_text()
            for line in content.strip().split('\n'):
                if line:
                    try:
                        data = json.loads(line)
                        yield Decision.from_dict(data)
                    except (json.JSONDecodeError, TypeError, KeyError) as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)
        except Exception as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def get_stats(self) -> Dict[str, Any]:
        """Get ledger statistics"""
        decisions = list(self._iter_decisions())

        by_type = {}
        confidence_sum = 0
        reversible_count = 0

        for d in decisions:
            by_type[d.decision_type] = by_type.get(d.decision_type, 0) + 1
            confidence_sum += d.confidence
            if d.reversibility == ReversibilityStatus.REVERSIBLE.value:
                reversible_count += 1

        return {
            "total_decisions": len(decisions),
            "by_type": by_type,
            "avg_confidence": round(confidence_sum / len(decisions), 3) if decisions else 0,
            "reversible_ratio": round(reversible_count / len(decisions), 3) if decisions else 0,
            "ledger_path": str(self.ledger_path)
        }

    def summarize_recent(self, hours: int = 24) -> str:
        """Generate a human-readable summary of recent decisions"""
        cutoff = datetime.now().replace(
            hour=datetime.now().hour - hours if datetime.now().hour >= hours else 0
        )

        recent = self.get_by_date_range(cutoff)

        if not recent:
            return "No decisions logged in the last 24 hours."

        lines = [f"**Decision Log Summary** (last {hours} hours, {len(recent)} decisions)"]
        lines.append("")

        # Group by type
        by_type = {}
        for d in recent:
            by_type.setdefault(d.decision_type, []).append(d)

        for dtype, decisions in sorted(by_type.items()):
            lines.append(f"**{dtype.replace('_', ' ').title()}** ({len(decisions)})")
            for d in decisions[:3]:  # Show max 3 per type
                conf_pct = int(d.confidence * 100)
                lines.append(f"  - [{d.id}] {d.action[:60]}... ({conf_pct}% confidence)")
            if len(decisions) > 3:
                lines.append(f"  - ... and {len(decisions) - 3} more")
            lines.append("")

        return '\n'.join(lines)


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Decision Ledger - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        ledger_path = Path(tmpdir) / "decisions.ndjson"
        ledger = DecisionLedger(ledger_path=ledger_path)

        # Test 1: Log decisions
        print("\n=== Test 1: Log Decisions ===")
        id1 = ledger.log_decision(
            decision_type=DecisionType.TASK_PRIORITIZATION,
            action="Moved 'Review Q4 reports' to P0",
            reasoning="Due date is tomorrow",
            alternatives=["Keep at P2", "Ask user"],
            confidence=0.95,
            reversibility=ReversibilityStatus.REVERSIBLE
        )
        print(f"   Logged: {id1}")

        id2 = ledger.log_decision(
            decision_type=DecisionType.EMAIL_FILTER,
            action="Archived newsletter from 'TechDaily'",
            reasoning="User previously archived 5 similar emails",
            alternatives=["Keep in inbox", "Mark as spam"],
            confidence=0.82,
            context={"sender": "TechDaily", "similar_archived": 5}
        )
        print(f"   Logged: {id2}")

        id3 = ledger.log_decision(
            decision_type=DecisionType.SAFETY_BLOCK,
            action="Blocked command: rm -rf /",
            reasoning="Matched dangerous pattern 'recursive_delete'",
            confidence=1.0,
            reversibility=ReversibilityStatus.IRREVERSIBLE
        )
        print(f"   Logged: {id3}")
        print("   Result: PASS")

        # Test 2: Get by ID
        print("\n=== Test 2: Get by ID ===")
        decision = ledger.get_by_id(id1)
        assert decision is not None
        assert decision.action == "Moved 'Review Q4 reports' to P0"
        print(f"   Retrieved: {decision.id} - {decision.action[:40]}...")
        print("   Result: PASS")

        # Test 3: Get recent
        print("\n=== Test 3: Get Recent ===")
        recent = ledger.get_recent(limit=10)
        assert len(recent) == 3
        assert recent[0].id == id3  # Most recent first
        print(f"   Got {len(recent)} recent decisions")
        print("   Result: PASS")

        # Test 4: Get by type
        print("\n=== Test 4: Get by Type ===")
        email_decisions = ledger.get_by_type(DecisionType.EMAIL_FILTER)
        assert len(email_decisions) == 1
        assert email_decisions[0].id == id2
        print(f"   Found {len(email_decisions)} email filter decision(s)")
        print("   Result: PASS")

        # Test 5: Search
        print("\n=== Test 5: Search ===")
        results = ledger.search("Q4")
        assert len(results) == 1
        print(f"   Found {len(results)} decision(s) matching 'Q4'")
        print("   Result: PASS")

        # Test 6: Stats
        print("\n=== Test 6: Statistics ===")
        stats = ledger.get_stats()
        assert stats["total_decisions"] == 3
        print(f"   Total: {stats['total_decisions']}")
        print(f"   By type: {stats['by_type']}")
        print(f"   Avg confidence: {stats['avg_confidence']}")
        print("   Result: PASS")

        # Test 7: Summary
        print("\n=== Test 7: Summary ===")
        summary = ledger.summarize_recent(hours=24)
        assert "Decision Log Summary" in summary
        print("   Summary generated:")
        for line in summary.split('\n')[:6]:
            print(f"   {line}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nDecision Ledger is ready for integration!")

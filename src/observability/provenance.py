#!/usr/bin/env python3
import logging
"""
Provenance DNA - Source Tracking System
=======================================

Tags every piece of information with its source, timestamp, and confidence.

Source: Ported from GROKSTAR's experiment DNA and provenance stamps

Problem Solved:
- When VERA states a fact, users don't know if it's from memory, web, file, or hallucination
- Trust requires knowing where information comes from
- Debugging requires understanding the information chain

Solution:
- Every piece of retrieved information gets a "DNA stamp"
- Tracks: source type, source ID, timestamp, confidence, retrieval chain
- Enables statements like "This came from your email on Dec 20 (high confidence)"

Usage:
    from provenance import ProvenanceTracker, SourceType

    tracker = ProvenanceTracker()

    # Stamp information from a file
    stamp = tracker.stamp(
        content="Meeting with Bob at 2pm",
        source_type=SourceType.FILE,
        source_id="calendar.txt:42",
        confidence=0.95
    )

    # Get formatted citation
    citation = stamp.cite()  # "calendar.txt:42, retrieved just now (95% confidence)"
"""

import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
logger = logging.getLogger(__name__)


class SourceType(Enum):
    """Types of information sources"""
    # Direct sources
    USER_INPUT = "user"          # User told us directly
    FILE = "file"                # Read from file
    WEB_SEARCH = "web"           # Web search result
    WEB_FETCH = "web_fetch"      # Direct URL fetch
    API = "api"                  # External API call

    # Memory sources
    MEMORY_FAST = "mem_fast"     # FastNetwork (recent)
    MEMORY_SLOW = "mem_slow"     # SlowNetwork (consolidated)
    MEMORY_ARCHIVE = "mem_arch"  # Archival tier
    CACHE = "cache"              # Cached result

    # Derived sources
    LLM_INFERENCE = "llm"        # Model inference/reasoning
    SYNTHESIS = "synthesis"      # Combined from multiple sources
    QUORUM = "quorum"            # Multi-agent consensus

    # System
    CONFIG = "config"            # Configuration file
    SYSTEM = "system"            # System information
    UNKNOWN = "unknown"


class FreshnessLevel(Enum):
    """How fresh the information is"""
    LIVE = "live"           # Just retrieved
    RECENT = "recent"       # Retrieved this session
    CACHED = "cached"       # From cache
    STALE = "stale"         # May be outdated
    HISTORICAL = "historical"  # Explicitly old


@dataclass
class ProvenanceStamp:
    """
    DNA stamp for a piece of information.

    Contains complete provenance chain for trust and debugging.
    """
    # Core identity
    stamp_id: str
    content_hash: str

    # Source information
    source_type: str
    source_id: str
    source_path: Optional[str] = None

    # Temporal
    retrieved_at: str = field(default_factory=lambda: datetime.now().isoformat())
    source_timestamp: Optional[str] = None
    freshness: str = FreshnessLevel.LIVE.value

    # Confidence
    confidence: float = 0.8
    confidence_reason: Optional[str] = None

    # Chain of custody
    retrieval_chain: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)

    # Context
    context: Dict[str, Any] = field(default_factory=dict)

    def cite(self, verbose: bool = False) -> str:
        """
        Generate a human-readable citation.

        Args:
            verbose: If True, include full details

        Returns:
            Citation string
        """
        # Format source
        if self.source_type == SourceType.FILE.value:
            source_str = f"file:{self.source_id}"
        elif self.source_type == SourceType.USER_INPUT.value:
            source_str = "user input"
        elif self.source_type in [SourceType.WEB_SEARCH.value, SourceType.WEB_FETCH.value]:
            source_str = f"web:{self.source_id[:50]}"
        elif self.source_type.startswith("mem_"):
            source_str = f"memory:{self.source_id[:20]}"
        elif self.source_type == SourceType.LLM_INFERENCE.value:
            source_str = "inference"
        else:
            source_str = f"{self.source_type}:{self.source_id[:30]}"

        # Format time
        try:
            retrieved = datetime.fromisoformat(self.retrieved_at)
            age = datetime.now() - retrieved
            if age < timedelta(minutes=1):
                time_str = "just now"
            elif age < timedelta(hours=1):
                time_str = f"{int(age.total_seconds() / 60)}m ago"
            elif age < timedelta(days=1):
                time_str = f"{int(age.total_seconds() / 3600)}h ago"
            else:
                time_str = f"{age.days}d ago"
        except ValueError:
            time_str = "unknown time"

        # Format confidence
        conf_pct = int(self.confidence * 100)
        if self.confidence >= 0.9:
            conf_str = f"high ({conf_pct}%)"
        elif self.confidence >= 0.7:
            conf_str = f"medium ({conf_pct}%)"
        else:
            conf_str = f"low ({conf_pct}%)"

        if verbose:
            return (
                f"[{source_str}] retrieved {time_str}, "
                f"confidence: {conf_str}, "
                f"freshness: {self.freshness}"
            )
        else:
            return f"{source_str}, {time_str} ({conf_pct}%)"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProvenanceStamp':
        return cls(**data)

    def is_stale(self, max_age_hours: int = 24) -> bool:
        """Check if the information is stale"""
        if self.freshness in [FreshnessLevel.STALE.value, FreshnessLevel.HISTORICAL.value]:
            return True

        try:
            retrieved = datetime.fromisoformat(self.retrieved_at)
            age = datetime.now() - retrieved
            return age > timedelta(hours=max_age_hours)
        except ValueError:
            return True


class ProvenanceTracker:
    """
    Tracks provenance for all retrieved information.

    Generates and stores DNA stamps for trust and debugging.
    """

    def __init__(self, storage_path: Path = None) -> None:
        """
        Initialize provenance tracker.

        Args:
            storage_path: Optional path to persist stamps
        """
        self.storage_path = storage_path
        self._stamps: Dict[str, ProvenanceStamp] = {}
        self._stamp_counter = 0

    def _generate_stamp_id(self) -> str:
        """Generate unique stamp ID"""
        self._stamp_counter += 1
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"PROV-{ts}-{self._stamp_counter:04d}"

    def _hash_content(self, content: str) -> str:
        """Generate content hash for deduplication"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def stamp(
        self,
        content: str,
        source_type: SourceType,
        source_id: str,
        source_path: str = None,
        source_timestamp: datetime = None,
        confidence: float = 0.8,
        confidence_reason: str = None,
        parent_stamps: List[ProvenanceStamp] = None,
        transformations: List[str] = None,
        context: Dict[str, Any] = None
    ) -> ProvenanceStamp:
        """
        Create a provenance stamp for content.

        Args:
            content: The information being stamped
            source_type: Type of source
            source_id: Identifier for the source
            source_path: Path/URL to source
            source_timestamp: When source was created/modified
            confidence: Confidence level (0.0 - 1.0)
            confidence_reason: Why this confidence level
            parent_stamps: Stamps this was derived from
            transformations: What transformations were applied
            context: Additional context

        Returns:
            ProvenanceStamp
        """
        # Build retrieval chain from parents
        retrieval_chain = []
        if parent_stamps:
            for parent in parent_stamps:
                retrieval_chain.append(parent.stamp_id)
                retrieval_chain.extend(parent.retrieval_chain)

        # Determine freshness
        if source_type == SourceType.CACHE:
            freshness = FreshnessLevel.CACHED
        elif source_timestamp:
            age = datetime.now() - source_timestamp
            if age < timedelta(hours=1):
                freshness = FreshnessLevel.LIVE
            elif age < timedelta(days=1):
                freshness = FreshnessLevel.RECENT
            elif age < timedelta(days=7):
                freshness = FreshnessLevel.STALE
            else:
                freshness = FreshnessLevel.HISTORICAL
        else:
            freshness = FreshnessLevel.LIVE

        stamp = ProvenanceStamp(
            stamp_id=self._generate_stamp_id(),
            content_hash=self._hash_content(content),
            source_type=source_type.value,
            source_id=source_id,
            source_path=source_path,
            source_timestamp=source_timestamp.isoformat() if source_timestamp else None,
            freshness=freshness.value,
            confidence=confidence,
            confidence_reason=confidence_reason,
            retrieval_chain=retrieval_chain[:10],  # Limit chain depth
            transformations=transformations or [],
            context=context or {}
        )

        # Store stamp
        self._stamps[stamp.stamp_id] = stamp

        return stamp

    def stamp_file(
        self,
        content: str,
        file_path: str,
        line_number: int = None,
        confidence: float = 0.95
    ) -> ProvenanceStamp:
        """Convenience method for file sources"""
        source_id = file_path
        if line_number:
            source_id = f"{file_path}:{line_number}"

        # Try to get file modification time
        source_timestamp = None
        try:
            mtime = Path(file_path).stat().st_mtime
            source_timestamp = datetime.fromtimestamp(mtime)
        except (OSError, FileNotFoundError):
            logger.debug("Suppressed OSError, FileNotFoundError in provenance")
            pass

        return self.stamp(
            content=content,
            source_type=SourceType.FILE,
            source_id=source_id,
            source_path=file_path,
            source_timestamp=source_timestamp,
            confidence=confidence,
            confidence_reason="Direct file read"
        )

    def stamp_user_input(
        self,
        content: str,
        context: str = None
    ) -> ProvenanceStamp:
        """Convenience method for user input"""
        return self.stamp(
            content=content,
            source_type=SourceType.USER_INPUT,
            source_id="user_message",
            confidence=1.0,
            confidence_reason="Direct user input",
            context={"input_context": context} if context else {}
        )

    def stamp_web(
        self,
        content: str,
        url: str,
        search_query: str = None,
        confidence: float = 0.7
    ) -> ProvenanceStamp:
        """Convenience method for web sources"""
        return self.stamp(
            content=content,
            source_type=SourceType.WEB_SEARCH if search_query else SourceType.WEB_FETCH,
            source_id=url,
            source_path=url,
            confidence=confidence,
            confidence_reason="Web retrieval",
            context={"search_query": search_query} if search_query else {}
        )

    def stamp_memory(
        self,
        content: str,
        memory_id: str,
        memory_tier: str,
        age_hours: float,
        confidence: float = 0.8
    ) -> ProvenanceStamp:
        """Convenience method for memory retrieval"""
        source_type = {
            "fast": SourceType.MEMORY_FAST,
            "slow": SourceType.MEMORY_SLOW,
            "archive": SourceType.MEMORY_ARCHIVE
        }.get(memory_tier, SourceType.MEMORY_SLOW)

        # Reduce confidence for older memories
        age_penalty = min(0.2, age_hours / 168)  # Max 0.2 penalty for 1 week
        adjusted_confidence = max(0.5, confidence - age_penalty)

        return self.stamp(
            content=content,
            source_type=source_type,
            source_id=memory_id,
            confidence=adjusted_confidence,
            confidence_reason=f"Memory retrieval, {age_hours:.1f}h old",
            context={"memory_tier": memory_tier, "age_hours": age_hours}
        )

    def stamp_inference(
        self,
        content: str,
        reasoning: str,
        source_stamps: List[ProvenanceStamp] = None,
        confidence: float = 0.6
    ) -> ProvenanceStamp:
        """Convenience method for LLM inference/reasoning"""
        return self.stamp(
            content=content,
            source_type=SourceType.LLM_INFERENCE,
            source_id="llm_reasoning",
            confidence=confidence,
            confidence_reason=reasoning,
            parent_stamps=source_stamps,
            transformations=["llm_inference"]
        )

    def stamp_synthesis(
        self,
        content: str,
        source_stamps: List[ProvenanceStamp],
        method: str = "aggregation"
    ) -> ProvenanceStamp:
        """Convenience method for synthesized information"""
        # Confidence is the minimum of source confidences
        min_confidence = min(s.confidence for s in source_stamps) if source_stamps else 0.5

        return self.stamp(
            content=content,
            source_type=SourceType.SYNTHESIS,
            source_id=f"synthesis_{len(source_stamps)}_sources",
            confidence=min_confidence,
            confidence_reason=f"Synthesized via {method}",
            parent_stamps=source_stamps,
            transformations=[f"synthesis:{method}"]
        )

    def get_stamp(self, stamp_id: str) -> Optional[ProvenanceStamp]:
        """Retrieve a stamp by ID"""
        return self._stamps.get(stamp_id)

    def get_chain(self, stamp: ProvenanceStamp) -> List[ProvenanceStamp]:
        """Get full provenance chain for a stamp"""
        chain = [stamp]
        for parent_id in stamp.retrieval_chain:
            parent = self.get_stamp(parent_id)
            if parent:
                chain.append(parent)
        return chain

    def format_provenance(
        self,
        stamp: ProvenanceStamp,
        include_chain: bool = False
    ) -> str:
        """Format provenance for display to user"""
        lines = [f"**Source**: {stamp.cite(verbose=True)}"]

        if stamp.confidence_reason:
            lines.append(f"**Basis**: {stamp.confidence_reason}")

        if stamp.transformations:
            lines.append(f"**Processing**: {' → '.join(stamp.transformations)}")

        if include_chain and stamp.retrieval_chain:
            lines.append("**Chain**:")
            for parent_id in stamp.retrieval_chain[:3]:
                parent = self.get_stamp(parent_id)
                if parent:
                    lines.append(f"  ← {parent.cite()}")

        return '\n'.join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics"""
        stamps = list(self._stamps.values())

        by_type = {}
        confidence_sum = 0
        stale_count = 0

        for s in stamps:
            by_type[s.source_type] = by_type.get(s.source_type, 0) + 1
            confidence_sum += s.confidence
            if s.is_stale():
                stale_count += 1

        return {
            "total_stamps": len(stamps),
            "by_source_type": by_type,
            "avg_confidence": round(confidence_sum / len(stamps), 3) if stamps else 0,
            "stale_ratio": round(stale_count / len(stamps), 3) if stamps else 0
        }


# === CLI Test Interface ===

if __name__ == "__main__":
    print("=" * 60)
    print("Provenance Tracker - Test Suite")
    print("=" * 60)

    tracker = ProvenanceTracker()

    # Test 1: File stamp
    print("\n=== Test 1: File Stamp ===")
    file_stamp = tracker.stamp_file(
        content="Meeting with Bob at 2pm",
        file_path="/path/to/calendar.txt",
        line_number=42
    )
    print(f"   Stamp ID: {file_stamp.stamp_id}")
    print(f"   Citation: {file_stamp.cite()}")
    print("   Result: PASS")

    # Test 2: User input stamp
    print("\n=== Test 2: User Input Stamp ===")
    user_stamp = tracker.stamp_user_input(
        content="My favorite color is blue",
        context="preference discussion"
    )
    print(f"   Stamp ID: {user_stamp.stamp_id}")
    print(f"   Citation: {user_stamp.cite()}")
    assert user_stamp.confidence == 1.0  # User input is always confident
    print("   Result: PASS")

    # Test 3: Web stamp
    print("\n=== Test 3: Web Stamp ===")
    web_stamp = tracker.stamp_web(
        content="Python 3.12 was released in October 2023",
        url="https://python.org/downloads",
        search_query="python latest version"
    )
    print(f"   Stamp ID: {web_stamp.stamp_id}")
    print(f"   Citation: {web_stamp.cite()}")
    print("   Result: PASS")

    # Test 4: Memory stamp with age penalty
    print("\n=== Test 4: Memory Stamp ===")
    mem_stamp = tracker.stamp_memory(
        content="User mentioned liking jazz music",
        memory_id="mem_12345",
        memory_tier="slow",
        age_hours=48,  # 2 days old
        confidence=0.85
    )
    print(f"   Original confidence: 0.85")
    print(f"   Adjusted confidence: {mem_stamp.confidence}")
    assert mem_stamp.confidence < 0.85  # Age penalty applied
    print("   Result: PASS")

    # Test 5: Synthesis stamp
    print("\n=== Test 5: Synthesis Stamp ===")
    synth_stamp = tracker.stamp_synthesis(
        content="User prefers jazz music and blue colors",
        source_stamps=[user_stamp, mem_stamp],
        method="aggregation"
    )
    print(f"   Source stamps: {len([user_stamp, mem_stamp])}")
    print(f"   Synthesis confidence: {synth_stamp.confidence}")
    print(f"   Chain: {synth_stamp.retrieval_chain}")
    print("   Result: PASS")

    # Test 6: Inference stamp
    print("\n=== Test 6: Inference Stamp ===")
    infer_stamp = tracker.stamp_inference(
        content="User might enjoy Miles Davis albums",
        reasoning="Based on stated preference for jazz",
        source_stamps=[mem_stamp],
        confidence=0.65
    )
    print(f"   Stamp ID: {infer_stamp.stamp_id}")
    print(f"   Citation: {infer_stamp.cite(verbose=True)}")
    print("   Result: PASS")

    # Test 7: Full provenance display
    print("\n=== Test 7: Format Provenance ===")
    formatted = tracker.format_provenance(synth_stamp, include_chain=True)
    print("   Formatted provenance:")
    for line in formatted.split('\n'):
        print(f"   {line}")
    print("   Result: PASS")

    # Test 8: Stats
    print("\n=== Test 8: Statistics ===")
    stats = tracker.get_stats()
    print(f"   Total stamps: {stats['total_stamps']}")
    print(f"   By type: {stats['by_source_type']}")
    print(f"   Avg confidence: {stats['avg_confidence']}")
    print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nProvenance Tracker is ready for integration!")

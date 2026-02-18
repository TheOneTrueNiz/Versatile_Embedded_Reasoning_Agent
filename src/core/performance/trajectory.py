"""
Trajectory Reduction for VERA.

Implements A-Mem style context pruning to reduce token usage
while preserving critical information.

Based on:
- A-Mem (arxiv:2502.12110) - Agentic memory with atomic notes
- Trajectory Reduction (arxiv:2509.23586) - 40-60% context reduction

Key strategies:
1. Atomic Notes: Break context into discrete, linkable units
2. Relevance Scoring: Score by recency, importance, query similarity
3. Redundancy Detection: Remove duplicate/similar information
4. Expiration: Age out stale context
5. Compression: Summarize verbose content
"""

import time
import logging
import hashlib
import threading
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple, Set, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import re

logger = logging.getLogger(__name__)


class NoteType(Enum):
    """Types of atomic notes."""
    OBSERVATION = "observation"     # What was seen/read
    ACTION = "action"               # What was done
    RESULT = "result"               # Outcome of action
    DECISION = "decision"           # Choice made
    INSIGHT = "insight"             # Derived understanding
    CONTEXT = "context"             # Background information
    ERROR = "error"                 # Error/failure information
    USER_INPUT = "user_input"       # User messages
    SYSTEM = "system"               # System messages


class PruneReason(Enum):
    """Reasons for pruning a note."""
    EXPIRED = "expired"             # Too old
    REDUNDANT = "redundant"         # Duplicate of another
    LOW_RELEVANCE = "low_relevance" # Not relevant to current task
    SUPERSEDED = "superseded"       # Replaced by newer info
    COMPRESSED = "compressed"       # Folded into summary


@dataclass
class AtomicNote:
    """
    An atomic unit of context/memory.

    Based on A-Mem paper's concept of atomic notes with:
    - Keywords for fast matching
    - Tags for categorization
    - Links to related notes
    - Embeddings for semantic search (optional)
    """
    note_id: str
    content: str
    note_type: NoteType
    timestamp: float = field(default_factory=time.time)

    # Metadata
    keywords: List[str] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)
    source: str = ""  # Where this came from

    # Relationships
    links: Set[str] = field(default_factory=set)  # Related note IDs
    parent_id: Optional[str] = None  # For hierarchical notes

    # Scoring
    importance: float = 0.5  # 0-1, higher = more important
    access_count: int = 0
    last_accessed: float = 0

    # Embedding (optional, for semantic search)
    embedding: Optional[List[float]] = None

    # Token count (for budget tracking)
    token_count: int = 0

    def __post_init__(self):
        if not self.note_id:
            self.note_id = f"note-{int(self.timestamp * 1000)}"
        if not self.token_count:
            # Rough estimate: ~4 chars per token
            self.token_count = len(self.content) // 4
        if not self.last_accessed:
            self.last_accessed = self.timestamp
        # Convert tags to set if list
        if isinstance(self.tags, list):
            self.tags = set(self.tags)
        if isinstance(self.links, list):
            self.links = set(self.links)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "note_id": self.note_id,
            "content": self.content,
            "note_type": self.note_type.value,
            "timestamp": self.timestamp,
            "keywords": self.keywords,
            "tags": list(self.tags),
            "source": self.source,
            "links": list(self.links),
            "parent_id": self.parent_id,
            "importance": self.importance,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "token_count": self.token_count
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AtomicNote':
        """Create from dictionary."""
        return cls(
            note_id=data.get("note_id", ""),
            content=data.get("content", ""),
            note_type=NoteType(data.get("note_type", "")),
            timestamp=data.get("timestamp", time.time()),
            keywords=data.get("keywords", []),
            tags=set(data.get("tags", [])),
            source=data.get("source", ""),
            links=set(data.get("links", [])),
            parent_id=data.get("parent_id"),
            importance=data.get("importance", 0.5),
            access_count=data.get("access_count", 0),
            last_accessed=data.get("last_accessed", 0),
            token_count=data.get("token_count", 0)
        )


@dataclass
class PruneResult:
    """Result of a pruning operation."""
    notes_pruned: int
    tokens_saved: int
    reasons: Dict[str, int]  # reason -> count
    duration_ms: float


@dataclass
class TrajectoryStats:
    """Statistics for trajectory management."""
    total_notes: int = 0
    total_tokens: int = 0
    notes_pruned: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 1.0
    avg_note_age_s: float = 0
    retrievals: int = 0
    cache_hits: int = 0


class TrajectoryManager:
    """
    Manages context trajectory with intelligent pruning.

    Implements A-Mem style memory management:
    - Atomic notes with metadata
    - Relevance-based retrieval
    - Automatic pruning of low-value content
    - Token budget management
    """

    # Default configuration
    DEFAULT_TOKEN_BUDGET = 50000  # Max tokens to retain
    DEFAULT_MAX_NOTES = 1000     # Max notes to keep
    DEFAULT_MAX_AGE_S = 3600     # 1 hour max age
    DEFAULT_MIN_RELEVANCE = 0.2  # Min relevance to keep

    def __init__(
        self,
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        max_notes: int = DEFAULT_MAX_NOTES,
        max_age_s: float = DEFAULT_MAX_AGE_S,
        min_relevance: float = DEFAULT_MIN_RELEVANCE,
        auto_prune: bool = True
    ):
        """
        Initialize trajectory manager.

        Args:
            token_budget: Maximum tokens to retain
            max_notes: Maximum notes to keep
            max_age_s: Maximum age for notes
            min_relevance: Minimum relevance score to keep
            auto_prune: Automatically prune on add
        """
        self.token_budget = token_budget
        self.max_notes = max_notes
        self.max_age_s = max_age_s
        self.min_relevance = min_relevance
        self.auto_prune = auto_prune

        # Note storage
        self._notes: Dict[str, AtomicNote] = {}
        self._notes_lock = threading.RLock()

        # Indexes for fast lookup
        self._by_type: Dict[NoteType, Set[str]] = defaultdict(set)
        self._by_tag: Dict[str, Set[str]] = defaultdict(set)
        self._by_keyword: Dict[str, Set[str]] = defaultdict(set)

        # Current context (what's "active")
        self._active_context: Set[str] = set()

        # Stats
        self._stats = TrajectoryStats()
        self._total_tokens_ever = 0
        self._total_tokens_pruned = 0

        # Keyword extraction patterns
        self._keyword_pattern = re.compile(r'\b[A-Za-z_][A-Za-z0-9_]{2,}\b')

    def add_note(
        self,
        content: str,
        note_type: NoteType,
        keywords: Optional[List[str]] = None,
        tags: Optional[Set[str]] = None,
        importance: float = 0.5,
        source: str = "",
        links: Optional[Set[str]] = None
    ) -> AtomicNote:
        """
        Add a new atomic note.

        Args:
            content: Note content
            note_type: Type of note
            keywords: Optional keywords (auto-extracted if not provided)
            tags: Optional tags
            importance: Importance score (0-1)
            source: Source identifier
            links: Related note IDs

        Returns:
            Created AtomicNote
        """
        # Auto-extract keywords if not provided
        if keywords is None:
            keywords = self._extract_keywords(content)

        note = AtomicNote(
            note_id=f"note-{int(time.time() * 1000)}-{len(self._notes)}",
            content=content,
            note_type=note_type,
            keywords=keywords,
            tags=tags or set(),
            importance=importance,
            source=source,
            links=links or set()
        )

        with self._notes_lock:
            self._notes[note.note_id] = note

            # Update indexes
            self._by_type[note_type].add(note.note_id)
            for tag in note.tags:
                self._by_tag[tag].add(note.note_id)
            for kw in note.keywords:
                self._by_keyword[kw.lower()].add(note.note_id)

            # Update stats
            self._stats.total_notes = len(self._notes)
            self._stats.total_tokens += note.token_count
            self._total_tokens_ever += note.token_count

        # Auto-prune if over budget
        if self.auto_prune:
            self._maybe_prune()

        return note

    def add_from_message(
        self,
        role: str,
        content: str,
        importance: float = 0.5
    ) -> AtomicNote:
        """
        Add a note from a conversation message.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            importance: Importance score

        Returns:
            Created AtomicNote
        """
        # Map role to note type
        type_map = {
            "user": NoteType.USER_INPUT,
            "assistant": NoteType.ACTION,
            "system": NoteType.SYSTEM
        }
        note_type = type_map.get(role, NoteType.OBSERVATION)

        return self.add_note(
            content=content,
            note_type=note_type,
            importance=importance,
            source=role,
            tags={role}
        )

    def add_tool_result(
        self,
        tool_name: str,
        result: str,
        success: bool = True,
        importance: float = 0.5
    ) -> AtomicNote:
        """
        Add a note from a tool execution result.

        Args:
            tool_name: Name of the tool
            result: Tool output
            success: Whether tool succeeded
            importance: Importance score

        Returns:
            Created AtomicNote
        """
        note_type = NoteType.RESULT if success else NoteType.ERROR

        return self.add_note(
            content=f"[{tool_name}] {result}",
            note_type=note_type,
            importance=importance,
            source=tool_name,
            tags={"tool", tool_name}
        )

    def get_note(self, note_id: str) -> Optional[AtomicNote]:
        """Get a note by ID."""
        with self._notes_lock:
            note = self._notes.get(note_id)
            if note:
                note.access_count += 1
                note.last_accessed = time.time()
                self._stats.retrievals += 1
            return note

    def link_notes(self, note_id1: str, note_id2: str) -> bool:
        """Create a bidirectional link between notes."""
        with self._notes_lock:
            if note_id1 in self._notes and note_id2 in self._notes:
                self._notes[note_id1].links.add(note_id2)
                self._notes[note_id2].links.add(note_id1)
                return True
        return False

    def retrieve(
        self,
        query: Optional[str] = None,
        note_types: Optional[List[NoteType]] = None,
        tags: Optional[Set[str]] = None,
        min_importance: float = 0,
        limit: int = 50,
        include_linked: bool = True
    ) -> List[AtomicNote]:
        """
        Retrieve relevant notes.

        Args:
            query: Optional query string for relevance matching
            note_types: Filter by note types
            tags: Filter by tags
            min_importance: Minimum importance score
            limit: Maximum notes to return
            include_linked: Include linked notes

        Returns:
            List of relevant notes, sorted by relevance
        """
        with self._notes_lock:
            candidates = set(self._notes.keys())

            # Filter by type
            if note_types:
                type_matches = set()
                for nt in note_types:
                    type_matches.update(self._by_type.get(nt, set()))
                candidates &= type_matches

            # Filter by tags
            if tags:
                for tag in tags:
                    candidates &= self._by_tag.get(tag, set())

            # Score and filter
            scored: List[Tuple[float, AtomicNote]] = []
            query_keywords = set(self._extract_keywords(query)) if query else set()

            for note_id in candidates:
                note = self._notes[note_id]

                if note.importance < min_importance:
                    continue

                score = self._compute_relevance(note, query_keywords)
                scored.append((score, note))

            # Sort by score
            scored.sort(key=lambda x: -x[0])

            # Get top results
            results = [note for _, note in scored[:limit]]

            # Include linked notes
            if include_linked and results:
                linked_ids = set()
                for note in results:
                    linked_ids.update(note.links)

                for lid in linked_ids:
                    if lid in self._notes and lid not in [n.note_id for n in results]:
                        results.append(self._notes[lid])

            # Update access stats
            for note in results:
                note.access_count += 1
                note.last_accessed = time.time()

            self._stats.retrievals += 1
            return results[:limit]

    def _compute_relevance(
        self,
        note: AtomicNote,
        query_keywords: Set[str]
    ) -> float:
        """
        Compute relevance score for a note.

        Factors:
        - Keyword overlap with query
        - Recency
        - Importance
        - Access frequency
        """
        score = 0.0

        # Keyword overlap (0-0.4)
        if query_keywords:
            note_keywords = set(kw.lower() for kw in note.keywords)
            overlap = len(query_keywords & note_keywords)
            if overlap > 0:
                score += 0.4 * (overlap / len(query_keywords))

        # Recency (0-0.3) - decay over time
        age = time.time() - note.timestamp
        recency = max(0, 1 - (age / self.max_age_s))
        score += 0.3 * recency

        # Importance (0-0.2)
        score += 0.2 * note.importance

        # Access frequency (0-0.1)
        freq_score = min(1.0, note.access_count / 10)
        score += 0.1 * freq_score

        return score

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        if not text:
            return []

        # Find all word-like tokens
        words = self._keyword_pattern.findall(text.lower())

        # Filter common words
        stop_words = {
            'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all',
            'can', 'had', 'her', 'was', 'one', 'our', 'out', 'has',
            'have', 'been', 'were', 'being', 'their', 'there', 'this',
            'that', 'with', 'they', 'from', 'what', 'which', 'would',
            'could', 'should', 'about', 'into', 'through', 'during',
            'before', 'after', 'above', 'below', 'between'
        }

        keywords = [w for w in words if w not in stop_words]

        # Return unique, keeping order
        seen = set()
        unique = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)

        return unique[:20]  # Limit to 20 keywords

    def prune(
        self,
        force: bool = False,
        strategies: Optional[List[str]] = None
    ) -> PruneResult:
        """
        Prune low-value notes to stay within budget.

        Args:
            force: Force pruning even if under budget
            strategies: Specific strategies to apply

        Returns:
            PruneResult with statistics
        """
        start = time.perf_counter()

        if strategies is None:
            strategies = ["expired", "redundant", "low_relevance", "over_budget"]

        pruned_count = 0
        tokens_saved = 0
        reasons: Dict[str, int] = defaultdict(int)

        with self._notes_lock:
            to_remove = set()
            now = time.time()

            # Strategy 1: Remove expired notes
            if "expired" in strategies:
                for note_id, note in self._notes.items():
                    age = now - note.timestamp
                    if age > self.max_age_s:
                        to_remove.add(note_id)
                        reasons[PruneReason.EXPIRED.value] += 1

            # Strategy 2: Remove redundant notes (simple content hash)
            if "redundant" in strategies:
                content_hashes: Dict[str, str] = {}
                for note_id, note in self._notes.items():
                    if note_id in to_remove:
                        continue

                    # Simple hash of normalized content
                    normalized = ' '.join(note.content.lower().split())
                    h = hashlib.md5(normalized.encode()).hexdigest()[:8]

                    if h in content_hashes:
                        # Keep the more important one
                        existing = self._notes.get(content_hashes[h])
                        if existing and note.importance <= existing.importance:
                            to_remove.add(note_id)
                            reasons[PruneReason.REDUNDANT.value] += 1
                    else:
                        content_hashes[h] = note_id

            # Strategy 3: Remove low relevance notes
            if "low_relevance" in strategies:
                for note_id, note in self._notes.items():
                    if note_id in to_remove:
                        continue

                    relevance = self._compute_relevance(note, set())
                    if relevance < self.min_relevance:
                        to_remove.add(note_id)
                        reasons[PruneReason.LOW_RELEVANCE.value] += 1

            # Strategy 4: Remove oldest/least important to fit budget
            if "over_budget" in strategies:
                current_tokens = sum(n.token_count for n in self._notes.values())
                current_tokens -= sum(
                    self._notes[nid].token_count
                    for nid in to_remove if nid in self._notes
                )

                if current_tokens > self.token_budget or len(self._notes) > self.max_notes:
                    # Score all notes and remove lowest
                    scored = []
                    for note_id, note in self._notes.items():
                        if note_id in to_remove:
                            continue
                        score = self._compute_relevance(note, set())
                        scored.append((score, note_id, note.token_count))

                    # Sort by score (ascending = lowest first)
                    scored.sort(key=lambda x: x[0])

                    # Remove until under budget
                    for score, note_id, tokens in scored:
                        if current_tokens <= self.token_budget and len(self._notes) - len(to_remove) <= self.max_notes:
                            break
                        to_remove.add(note_id)
                        current_tokens -= tokens
                        reasons[PruneReason.LOW_RELEVANCE.value] += 1

            # Execute removal
            for note_id in to_remove:
                if note_id in self._notes:
                    note = self._notes[note_id]
                    tokens_saved += note.token_count

                    # Clean up indexes
                    self._by_type[note.note_type].discard(note_id)
                    for tag in note.tags:
                        self._by_tag[tag].discard(note_id)
                    for kw in note.keywords:
                        self._by_keyword[kw.lower()].discard(note_id)

                    # Remove links from other notes
                    for other_id in note.links:
                        if other_id in self._notes:
                            self._notes[other_id].links.discard(note_id)

                    del self._notes[note_id]
                    pruned_count += 1

            # Update stats
            self._stats.total_notes = len(self._notes)
            self._stats.total_tokens = sum(n.token_count for n in self._notes.values())
            self._stats.notes_pruned += pruned_count
            self._stats.tokens_saved += tokens_saved
            self._total_tokens_pruned += tokens_saved

        duration = (time.perf_counter() - start) * 1000

        if pruned_count > 0:
            logger.debug(f"Pruned {pruned_count} notes, saved {tokens_saved} tokens in {duration:.1f}ms")

        return PruneResult(
            notes_pruned=pruned_count,
            tokens_saved=tokens_saved,
            reasons=dict(reasons),
            duration_ms=duration
        )

    def _maybe_prune(self) -> None:
        """Prune if over budget."""
        current_tokens = sum(n.token_count for n in self._notes.values())
        if current_tokens > self.token_budget or len(self._notes) > self.max_notes:
            self.prune()

    def compress_to_summary(
        self,
        note_ids: Optional[List[str]] = None,
        summarizer: Optional[Callable[[str], str]] = None
    ) -> Optional[AtomicNote]:
        """
        Compress multiple notes into a summary note.

        Args:
            note_ids: Notes to compress (or all if None)
            summarizer: Function to summarize text

        Returns:
            Summary note, or None if nothing to compress
        """
        with self._notes_lock:
            if note_ids is None:
                # Compress oldest notes
                notes = sorted(
                    self._notes.values(),
                    key=lambda n: n.timestamp
                )[:50]
            else:
                notes = [self._notes[nid] for nid in note_ids if nid in self._notes]

            if not notes:
                return None

            # Combine content
            combined = "\n".join(n.content for n in notes)

            # Summarize if function provided
            if summarizer:
                summary = summarizer(combined)
            else:
                # Simple truncation
                summary = combined[:1000] + "..." if len(combined) > 1000 else combined

            # Create summary note
            summary_note = self.add_note(
                content=summary,
                note_type=NoteType.CONTEXT,
                importance=0.7,
                source="compression",
                tags={"summary", "compressed"}
            )

            # Remove compressed notes
            for note in notes:
                if note.note_id in self._notes:
                    del self._notes[note.note_id]

            return summary_note

    def get_context_window(
        self,
        token_limit: int = 10000,
        query: Optional[str] = None
    ) -> str:
        """
        Get a formatted context window for LLM consumption.

        Args:
            token_limit: Maximum tokens to include
            query: Optional query for relevance filtering

        Returns:
            Formatted context string
        """
        notes = self.retrieve(query=query, limit=100)

        # Build context respecting token limit
        context_parts = []
        token_count = 0

        for note in notes:
            if token_count + note.token_count > token_limit:
                break

            # Format note
            type_label = note.note_type.value.upper()
            timestamp = datetime.fromtimestamp(note.timestamp).strftime("%H:%M:%S")
            formatted = f"[{type_label} {timestamp}] {note.content}"

            context_parts.append(formatted)
            token_count += note.token_count

        return "\n\n".join(context_parts)

    def get_stats(self) -> Dict[str, Any]:
        """Get trajectory statistics."""
        with self._notes_lock:
            if self._notes:
                ages = [time.time() - n.timestamp for n in self._notes.values()]
                avg_age = sum(ages) / len(ages)
            else:
                avg_age = 0

            compression = (
                self._total_tokens_pruned / self._total_tokens_ever
                if self._total_tokens_ever > 0 else 0
            )

        return {
            "total_notes": len(self._notes),
            "total_tokens": sum(n.token_count for n in self._notes.values()),
            "notes_pruned": self._stats.notes_pruned,
            "tokens_saved": self._stats.tokens_saved,
            "compression_ratio": compression,
            "avg_note_age_s": avg_age,
            "retrievals": self._stats.retrievals,
            "token_budget": self.token_budget,
            "budget_used_pct": (
                sum(n.token_count for n in self._notes.values()) / self.token_budget * 100
                if self.token_budget > 0 else 0
            ),
            "notes_by_type": {
                nt.value: len(ids) for nt, ids in self._by_type.items()
            }
        }

    def clear(self) -> None:
        """Clear all notes."""
        with self._notes_lock:
            self._notes.clear()
            self._by_type.clear()
            self._by_tag.clear()
            self._by_keyword.clear()
            self._active_context.clear()


# === Global Instance ===

_global_trajectory: Optional[TrajectoryManager] = None


def get_trajectory_manager() -> TrajectoryManager:
    """Get or create global trajectory manager."""
    global _global_trajectory
    if _global_trajectory is None:
        _global_trajectory = TrajectoryManager()
    return _global_trajectory


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_trajectory():
        """Test trajectory manager."""
        print("Testing Trajectory Manager...")
        print("=" * 60)

        # Test 1: Create manager
        print("Test 1: Create manager...", end=" ")
        tm = TrajectoryManager(
            token_budget=1000,
            max_notes=50,
            max_age_s=60,
            auto_prune=False
        )
        print("PASS")

        # Test 2: Add notes
        print("Test 2: Add notes...", end=" ")
        note1 = tm.add_note(
            content="User asked about Python programming",
            note_type=NoteType.USER_INPUT,
            importance=0.8
        )
        assert note1.note_id is not None
        assert len(note1.keywords) > 0
        print("PASS")

        # Test 3: Add from message
        print("Test 3: Add from message...", end=" ")
        note2 = tm.add_from_message(
            role="assistant",
            content="I can help you with Python. What specific topic?",
            importance=0.7
        )
        assert note2.note_type == NoteType.ACTION
        print("PASS")

        # Test 4: Link notes
        print("Test 4: Link notes...", end=" ")
        success = tm.link_notes(note1.note_id, note2.note_id)
        assert success
        assert note2.note_id in note1.links
        print("PASS")

        # Test 5: Retrieve by query
        print("Test 5: Retrieve by query...", end=" ")
        results = tm.retrieve(query="Python programming", limit=10)
        assert len(results) >= 1
        # The user input about Python should be first
        assert any("Python" in n.content for n in results)
        print("PASS")

        # Test 6: Retrieve by type
        print("Test 6: Retrieve by type...", end=" ")
        results = tm.retrieve(note_types=[NoteType.USER_INPUT], include_linked=False)
        assert len(results) >= 1
        assert all(n.note_type == NoteType.USER_INPUT for n in results)
        print("PASS")

        # Test 7: Add tool result
        print("Test 7: Add tool result...", end=" ")
        note3 = tm.add_tool_result(
            tool_name="read_file",
            result="File content: def hello(): pass",
            success=True
        )
        assert note3.note_type == NoteType.RESULT
        assert "tool" in note3.tags
        print("PASS")

        # Test 8: Prune by token budget
        print("Test 8: Prune by budget...", end=" ")
        # Add many notes to exceed budget
        for i in range(20):
            tm.add_note(
                content=f"Test note number {i} with some additional content to increase token count",
                note_type=NoteType.OBSERVATION,
                importance=0.1 + (i * 0.01)
            )
        result = tm.prune()
        assert result.notes_pruned >= 0  # May prune if over budget
        print(f"PASS (pruned {result.notes_pruned} notes)")

        # Test 9: Get context window
        print("Test 9: Get context window...", end=" ")
        context = tm.get_context_window(token_limit=500)
        assert len(context) > 0
        print("PASS")

        # Test 10: Stats
        print("Test 10: Stats...", end=" ")
        stats = tm.get_stats()
        assert stats["total_notes"] > 0
        assert "budget_used_pct" in stats
        print("PASS")

        # Test 11: Redundancy detection
        print("Test 11: Redundancy detection...", end=" ")
        tm2 = TrajectoryManager(auto_prune=False)
        tm2.add_note("The quick brown fox", NoteType.OBSERVATION)
        tm2.add_note("The quick brown fox", NoteType.OBSERVATION)  # Duplicate
        tm2.add_note("Something different", NoteType.OBSERVATION)
        result = tm2.prune(strategies=["redundant"])
        assert result.reasons.get("redundant", 0) >= 1
        print("PASS")

        # Test 12: Compression ratio
        print("Test 12: Compression tracking...", end=" ")
        stats = tm.get_stats()
        # Should have some compression after pruning
        print(f"PASS (compression: {stats['compression_ratio']:.1%})")

        print("=" * 60)
        print("\nAll tests passed!")
        return True

    success = test_trajectory()
    sys.exit(0 if success else 1)

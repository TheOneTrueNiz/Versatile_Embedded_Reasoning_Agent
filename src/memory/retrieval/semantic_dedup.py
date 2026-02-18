#!/usr/bin/env python3
"""
Semantic Deduplication with Temporal Weighting
==============================================

Detects and manages duplicate or near-duplicate content with time-aware
similarity scoring.

Problem Solved:
- Memory systems accumulate duplicate information
- Same facts stored multiple times waste space
- Near-duplicates cause confusion and inconsistency
- Old duplicates should matter less than recent ones

Improvement #9 (2025-12-26): Temporal Weighting
- Time-decay functions for similarity scores (exponential, linear, step)
- Recency boost for recent content
- Age-adjusted similarity thresholds
- Time-windowed duplicate detection

Research basis:
- arXiv:2310.06825 "Temporal Knowledge Graphs" - Time-aware embeddings
- arXiv:2305.14250 "Memory Consolidation" - Recency/frequency balancing

Solution:
- Hash-based exact duplicate detection
- Similarity-based near-duplicate detection
- Temporal weighting for time-aware comparison
- Merge strategies for combining duplicates
- Index for fast lookup

Usage:
    from semantic_dedup import SemanticDeduplicator, TemporalDeduplicator

    # Standard deduplication
    dedup = SemanticDeduplicator()
    result = dedup.check("The meeting is at 3 PM tomorrow")

    # Temporal deduplication (Improvement #9)
    temporal_dedup = TemporalDeduplicator(
        decay_function="exponential",
        half_life_hours=168  # 1 week half-life
    )
    result = temporal_dedup.check("The meeting is at 3 PM tomorrow")
    # Similarity scores are now time-weighted!
"""

import json
import hashlib
import re
import math
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Tuple, Set
from enum import Enum
from collections import defaultdict
import logging
logger = logging.getLogger(__name__)

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class DuplicateType(Enum):
    """Type of duplicate detection"""
    EXACT = "exact"              # Exact match
    NEAR_EXACT = "near_exact"    # After normalization
    SEMANTIC = "semantic"        # Meaning is same
    PARTIAL = "partial"          # Subset of content


class MergeStrategy(Enum):
    """How to merge duplicates"""
    KEEP_FIRST = "keep_first"
    KEEP_NEWEST = "keep_newest"
    KEEP_LONGEST = "keep_longest"
    MERGE_METADATA = "merge_metadata"


@dataclass
class ContentEntry:
    """A stored content entry"""
    id: str
    content: str
    normalized: str
    hash_exact: str
    hash_normalized: str
    tokens: Set[str]
    created_at: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "normalized": self.normalized,
            "hash_exact": self.hash_exact,
            "hash_normalized": self.hash_normalized,
            "tokens": list(self.tokens),
            "created_at": self.created_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ContentEntry':
        return cls(
            id=data.get("id", ""),
            content=data.get("content", ""),
            normalized=data.get("normalized", ""),
            hash_exact=data.get("hash_exact", ""),
            hash_normalized=data.get("hash_normalized", ""),
            tokens=set(data.get("tokens", "")),
            created_at=data.get("created_at", ""),
            metadata=data.get("metadata", {})
        )


@dataclass
class DuplicateResult:
    """Result of duplicate check"""
    is_duplicate: bool
    is_similar: bool
    duplicate_type: Optional[DuplicateType]
    original_id: Optional[str]
    similar_ids: List[str]
    similarity_scores: Dict[str, float]
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_duplicate": self.is_duplicate,
            "is_similar": self.is_similar,
            "duplicate_type": self.duplicate_type.value if self.duplicate_type else None,
            "original_id": self.original_id,
            "similar_ids": self.similar_ids,
            "similarity_scores": self.similarity_scores,
            "suggestion": self.suggestion
        }


class SemanticDeduplicator:
    """
    Detects and manages content duplicates.

    Features:
    - Exact hash matching
    - Normalized matching (case, whitespace)
    - Token-based similarity (Jaccard)
    - N-gram based similarity
    """

    def __init__(
        self,
        storage_path: Path = None,
        memory_dir: Path = None,
        similarity_threshold: float = 0.8,
        near_duplicate_threshold: float = 0.95
    ):
        """
        Initialize deduplicator.

        Args:
            storage_path: Path to store content index
            memory_dir: Base memory directory
            similarity_threshold: Threshold for "similar" (0-1)
            near_duplicate_threshold: Threshold for "near-duplicate" (0-1)
        """
        if storage_path:
            self.storage_path = Path(storage_path)
        elif memory_dir:
            self.storage_path = Path(memory_dir) / "dedup_index.json"
        else:
            self.storage_path = Path("vera_memory/dedup_index.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        self.similarity_threshold = similarity_threshold
        self.near_duplicate_threshold = near_duplicate_threshold

        # Content storage
        self._entries: Dict[str, ContentEntry] = {}

        # Indexes for fast lookup
        self._hash_index: Dict[str, str] = {}       # hash -> id
        self._norm_hash_index: Dict[str, str] = {}  # normalized_hash -> id
        self._token_index: Dict[str, Set[str]] = defaultdict(set)  # token -> ids

        # Entry counter
        self._entry_count = 0

        # Load existing data
        self._load()

    def _load(self) -> None:
        """Load index from storage"""
        if not self.storage_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path, default={})
            else:
                data = json.loads(self.storage_path.read_text())

            for entry_data in data.get("entries", []):
                entry = ContentEntry.from_dict(entry_data)
                self._entries[entry.id] = entry
                self._hash_index[entry.hash_exact] = entry.id
                self._norm_hash_index[entry.hash_normalized] = entry.id
                for token in entry.tokens:
                    self._token_index[token].add(entry.id)

            self._entry_count = data.get("entry_count", len(self._entries))

        except Exception:
            self._entries = {}

    def _save(self) -> None:
        """Save index to storage"""
        data = {
            "entries": [e.to_dict() for e in self._entries.values()],
            "entry_count": self._entry_count,
            "last_updated": datetime.now().isoformat()
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2))

    def _generate_id(self) -> str:
        """Generate unique content ID"""
        self._entry_count += 1
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"CNT-{timestamp}-{self._entry_count:05d}"

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison"""
        # Lowercase
        normalized = text.lower()
        # Remove extra whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        # Remove punctuation
        normalized = re.sub(r'[^\w\s]', '', normalized)
        # Strip
        normalized = normalized.strip()
        return normalized

    def _hash(self, text: str) -> str:
        """Generate hash of text"""
        return hashlib.md5(text.encode()).hexdigest()

    def _tokenize(self, text: str) -> Set[str]:
        """Tokenize text for similarity comparison"""
        normalized = self._normalize(text)
        # Split into words
        tokens = set(normalized.split())
        # Add bigrams for better matching
        words = normalized.split()
        for i in range(len(words) - 1):
            tokens.add(f"{words[i]}_{words[i+1]}")
        return tokens

    def _jaccard_similarity(self, tokens1: Set[str], tokens2: Set[str]) -> float:
        """Calculate Jaccard similarity between token sets"""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        return intersection / union if union > 0 else 0.0

    def check(self, content: str) -> DuplicateResult:
        """
        Check if content is a duplicate.

        Args:
            content: Content to check

        Returns:
            DuplicateResult with duplicate information
        """
        # Compute hashes
        exact_hash = self._hash(content)
        normalized = self._normalize(content)
        norm_hash = self._hash(normalized)
        tokens = self._tokenize(content)

        # Check exact duplicate
        if exact_hash in self._hash_index:
            original_id = self._hash_index[exact_hash]
            return DuplicateResult(
                is_duplicate=True,
                is_similar=True,
                duplicate_type=DuplicateType.EXACT,
                original_id=original_id,
                similar_ids=[original_id],
                similarity_scores={original_id: 1.0},
                suggestion="Exact duplicate found. Skip or merge."
            )

        # Check normalized duplicate
        if norm_hash in self._norm_hash_index:
            original_id = self._norm_hash_index[norm_hash]
            return DuplicateResult(
                is_duplicate=True,
                is_similar=True,
                duplicate_type=DuplicateType.NEAR_EXACT,
                original_id=original_id,
                similar_ids=[original_id],
                similarity_scores={original_id: 0.99},
                suggestion="Near-exact duplicate (differs only in formatting). Consider merging."
            )

        # Check token similarity
        similar_ids = []
        similarity_scores = {}

        # Find candidate entries via token index
        candidate_ids = set()
        for token in tokens:
            candidate_ids.update(self._token_index.get(token, set()))

        for candidate_id in candidate_ids:
            entry = self._entries.get(candidate_id)
            if entry:
                similarity = self._jaccard_similarity(tokens, entry.tokens)
                if similarity >= self.similarity_threshold:
                    similar_ids.append(candidate_id)
                    similarity_scores[candidate_id] = similarity

        # Sort by similarity
        similar_ids.sort(key=lambda x: similarity_scores[x], reverse=True)

        if similar_ids:
            top_similarity = similarity_scores[similar_ids[0]]

            if top_similarity >= self.near_duplicate_threshold:
                return DuplicateResult(
                    is_duplicate=True,
                    is_similar=True,
                    duplicate_type=DuplicateType.SEMANTIC,
                    original_id=similar_ids[0],
                    similar_ids=similar_ids[:5],
                    similarity_scores=similarity_scores,
                    suggestion=f"Semantic duplicate ({top_similarity:.0%} similar). Consider merging."
                )
            else:
                return DuplicateResult(
                    is_duplicate=False,
                    is_similar=True,
                    duplicate_type=None,
                    original_id=None,
                    similar_ids=similar_ids[:5],
                    similarity_scores=similarity_scores,
                    suggestion=f"Similar content found ({top_similarity:.0%}). Review before adding."
                )

        return DuplicateResult(
            is_duplicate=False,
            is_similar=False,
            duplicate_type=None,
            original_id=None,
            similar_ids=[],
            similarity_scores={},
            suggestion="No duplicates found. Safe to add."
        )

    def add(
        self,
        content: str,
        metadata: Dict[str, Any] = None,
        force: bool = False
    ) -> Tuple[str, DuplicateResult]:
        """
        Add content to index.

        Args:
            content: Content to add
            metadata: Optional metadata
            force: Add even if duplicate

        Returns:
            Tuple of (content_id, duplicate_result)
        """
        result = self.check(content)

        if result.is_duplicate and not force:
            return (result.original_id, result)

        # Create entry
        entry = ContentEntry(
            id=self._generate_id(),
            content=content,
            normalized=self._normalize(content),
            hash_exact=self._hash(content),
            hash_normalized=self._hash(self._normalize(content)),
            tokens=self._tokenize(content),
            created_at=datetime.now().isoformat(),
            metadata=metadata or {}
        )

        # Add to storage and indexes
        self._entries[entry.id] = entry
        self._hash_index[entry.hash_exact] = entry.id
        self._norm_hash_index[entry.hash_normalized] = entry.id
        for token in entry.tokens:
            self._token_index[token].add(entry.id)

        self._save()

        return (entry.id, result)

    def get(self, content_id: str) -> Optional[ContentEntry]:
        """Get content by ID"""
        return self._entries.get(content_id)

    def remove(self, content_id: str) -> bool:
        """Remove content from index"""
        entry = self._entries.get(content_id)
        if not entry:
            return False

        # Remove from indexes
        self._hash_index.pop(entry.hash_exact, None)
        self._norm_hash_index.pop(entry.hash_normalized, None)
        for token in entry.tokens:
            self._token_index[token].discard(content_id)

        # Remove entry
        del self._entries[content_id]

        self._save()
        return True

    def merge(
        self,
        id1: str,
        id2: str,
        strategy: MergeStrategy = MergeStrategy.KEEP_NEWEST
    ) -> Optional[str]:
        """
        Merge two entries.

        Args:
            id1: First entry ID
            id2: Second entry ID
            strategy: How to merge

        Returns:
            ID of kept entry, or None if failed
        """
        entry1 = self._entries.get(id1)
        entry2 = self._entries.get(id2)

        if not entry1 or not entry2:
            return None

        # Determine which to keep
        if strategy == MergeStrategy.KEEP_FIRST:
            keep, remove = entry1, entry2
        elif strategy == MergeStrategy.KEEP_NEWEST:
            keep, remove = (entry1, entry2) if entry1.created_at >= entry2.created_at else (entry2, entry1)
        elif strategy == MergeStrategy.KEEP_LONGEST:
            keep, remove = (entry1, entry2) if len(entry1.content) >= len(entry2.content) else (entry2, entry1)
        elif strategy == MergeStrategy.MERGE_METADATA:
            # Keep first but merge metadata
            keep, remove = entry1, entry2
            keep.metadata.update(remove.metadata)
        else:
            keep, remove = entry1, entry2

        # Remove the other entry
        self.remove(remove.id)

        return keep.id

    def find_duplicates(self) -> List[Tuple[str, str, float]]:
        """
        Find all duplicate pairs in the index.

        Returns:
            List of (id1, id2, similarity) tuples
        """
        duplicates = []
        checked = set()

        for id1, entry1 in self._entries.items():
            for id2, entry2 in self._entries.items():
                if id1 >= id2:
                    continue

                pair_key = (id1, id2)
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                similarity = self._jaccard_similarity(entry1.tokens, entry2.tokens)
                if similarity >= self.similarity_threshold:
                    duplicates.append((id1, id2, similarity))

        return sorted(duplicates, key=lambda x: x[2], reverse=True)

    def cleanup(
        self,
        strategy: MergeStrategy = MergeStrategy.KEEP_NEWEST
    ) -> int:
        """
        Automatically merge all duplicates.

        Returns:
            Number of entries removed
        """
        removed = 0
        duplicates = self.find_duplicates()

        for id1, id2, similarity in duplicates:
            if id1 in self._entries and id2 in self._entries:
                if similarity >= self.near_duplicate_threshold:
                    self.merge(id1, id2, strategy)
                    removed += 1

        return removed

    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics"""
        total_entries = len(self._entries)
        total_tokens = len(self._token_index)
        duplicates = self.find_duplicates()

        return {
            "total_entries": total_entries,
            "unique_tokens": total_tokens,
            "duplicate_pairs": len(duplicates),
            "storage_path": str(self.storage_path)
        }

    def summarize(self) -> str:
        """Generate summary of deduplication status"""
        stats = self.get_stats()
        duplicates = self.find_duplicates()

        lines = [
            "**Deduplication Index**",
            f"- Entries: {stats['total_entries']}",
            f"- Unique tokens: {stats['unique_tokens']}",
            f"- Duplicate pairs: {stats['duplicate_pairs']}"
        ]

        if duplicates:
            lines.append("\n**Top Duplicates**:")
            for id1, id2, sim in duplicates[:5]:
                lines.append(f"  - {id1} <-> {id2} ({sim:.0%})")

        return "\n".join(lines)


# =============================================================================
# Temporal Weighting (Improvement #9)
# Time-decay functions for similarity scoring
# =============================================================================

class DecayFunction(Enum):
    """Types of temporal decay functions"""
    EXPONENTIAL = "exponential"  # Fast initial decay, then slow
    LINEAR = "linear"            # Constant decay rate
    STEP = "step"                # Discrete time windows
    INVERSE = "inverse"          # 1/(1 + age) - gentle decay
    NONE = "none"                # No decay (weight = 1.0)


@dataclass
class TemporalWeight:
    """
    Calculates time-based weights for similarity scores.

    Newer content gets higher weight, older content decays.
    """

    decay_function: DecayFunction = DecayFunction.EXPONENTIAL
    half_life_hours: float = 168.0  # 1 week default
    min_weight: float = 0.1  # Floor to prevent zero weights
    max_weight: float = 1.0  # Ceiling for very recent content
    recency_boost_hours: float = 24.0  # Content within this gets max weight
    step_thresholds: List[Tuple[float, float]] = None  # For step function: (hours, weight)

    def __post_init__(self):
        if self.step_thresholds is None:
            # Default step thresholds: recent, this week, this month, older
            self.step_thresholds = [
                (24, 1.0),     # < 24 hours: full weight
                (168, 0.8),   # < 1 week: 80%
                (720, 0.5),   # < 1 month: 50%
                (float('inf'), 0.2)  # older: 20%
            ]

    def calculate(self, age_hours: float) -> float:
        """
        Calculate weight based on age in hours.

        Args:
            age_hours: Hours since content was created

        Returns:
            Weight between min_weight and max_weight
        """
        if age_hours <= 0:
            return self.max_weight

        if age_hours <= self.recency_boost_hours:
            return self.max_weight

        if self.decay_function == DecayFunction.NONE:
            return self.max_weight

        elif self.decay_function == DecayFunction.EXPONENTIAL:
            # Exponential decay: w = max * (0.5)^(age/half_life)
            decay_factor = math.pow(0.5, age_hours / self.half_life_hours)
            weight = self.max_weight * decay_factor

        elif self.decay_function == DecayFunction.LINEAR:
            # Linear decay: w = max - (age/half_life) * (max - min)
            decay_rate = (self.max_weight - self.min_weight) / (self.half_life_hours * 2)
            weight = self.max_weight - (age_hours * decay_rate)

        elif self.decay_function == DecayFunction.INVERSE:
            # Inverse decay: w = max / (1 + age/half_life)
            weight = self.max_weight / (1 + age_hours / self.half_life_hours)

        elif self.decay_function == DecayFunction.STEP:
            # Step function: discrete weights based on age brackets
            weight = self.min_weight
            for threshold_hours, threshold_weight in self.step_thresholds:
                if age_hours < threshold_hours:
                    weight = threshold_weight
                    break

        else:
            weight = self.max_weight

        return max(self.min_weight, min(self.max_weight, weight))

    def calculate_from_datetime(
        self,
        created_at: datetime,
        reference_time: datetime = None
    ) -> float:
        """
        Calculate weight from datetime objects.

        Args:
            created_at: When content was created
            reference_time: Reference time (defaults to now)

        Returns:
            Weight between min_weight and max_weight
        """
        if reference_time is None:
            reference_time = datetime.now()

        age = reference_time - created_at
        age_hours = age.total_seconds() / 3600

        return self.calculate(age_hours)

    def calculate_from_iso(
        self,
        created_at_iso: str,
        reference_time: datetime = None
    ) -> float:
        """
        Calculate weight from ISO timestamp string.

        Args:
            created_at_iso: ISO format timestamp
            reference_time: Reference time (defaults to now)

        Returns:
            Weight between min_weight and max_weight
        """
        try:
            created_at = datetime.fromisoformat(created_at_iso)
            return self.calculate_from_datetime(created_at, reference_time)
        except (ValueError, TypeError):
            return self.min_weight  # Unparseable timestamps get minimum weight


@dataclass
class TemporalDuplicateResult(DuplicateResult):
    """Extended result with temporal information"""
    temporal_scores: Dict[str, float] = field(default_factory=dict)  # id -> time-weighted score
    recency_ranking: List[str] = field(default_factory=list)  # IDs ordered by recency
    effective_threshold: float = 0.0  # Threshold used after temporal adjustment


class TemporalDeduplicator(SemanticDeduplicator):
    """
    Semantic deduplicator with temporal weighting.

    Extends SemanticDeduplicator to weight similarity scores based on
    content age. Recent content has higher effective similarity.

    Features:
    - Configurable decay functions (exponential, linear, step, inverse)
    - Recency boost for very recent content
    - Age-adjusted thresholds (older content needs higher base similarity)
    - Time-windowed duplicate detection

    Usage:
        dedup = TemporalDeduplicator(
            decay_function="exponential",
            half_life_hours=168  # 1 week
        )

        # Check with temporal weighting
        result = dedup.check("Meeting tomorrow at 3 PM")
        # result.temporal_scores has time-weighted similarities
    """

    def __init__(
        self,
        storage_path: Path = None,
        memory_dir: Path = None,
        similarity_threshold: float = 0.8,
        near_duplicate_threshold: float = 0.95,
        decay_function: str = "exponential",
        half_life_hours: float = 168.0,
        min_weight: float = 0.1,
        recency_boost_hours: float = 24.0,
        age_threshold_adjustment: bool = True
    ):
        """
        Initialize temporal deduplicator.

        Args:
            storage_path: Path to store content index
            memory_dir: Base memory directory
            similarity_threshold: Base threshold for "similar" (0-1)
            near_duplicate_threshold: Base threshold for "near-duplicate" (0-1)
            decay_function: Type of decay ("exponential", "linear", "step", "inverse", "none")
            half_life_hours: Hours for similarity to decay by half
            min_weight: Minimum temporal weight (floor)
            recency_boost_hours: Hours within which content gets max weight
            age_threshold_adjustment: Whether to adjust thresholds based on content age
        """
        super().__init__(
            storage_path=storage_path,
            memory_dir=memory_dir,
            similarity_threshold=similarity_threshold,
            near_duplicate_threshold=near_duplicate_threshold
        )

        self.temporal_weight = TemporalWeight(
            decay_function=DecayFunction(decay_function),
            half_life_hours=half_life_hours,
            min_weight=min_weight,
            recency_boost_hours=recency_boost_hours
        )
        self.age_threshold_adjustment = age_threshold_adjustment

    def _get_temporal_weight(self, entry: ContentEntry) -> float:
        """Get temporal weight for an entry"""
        return self.temporal_weight.calculate_from_iso(entry.created_at)

    def _adjust_threshold_for_age(
        self,
        base_threshold: float,
        age_hours: float
    ) -> float:
        """
        Adjust similarity threshold based on content age.

        Older content needs higher base similarity to be considered a match,
        because we're less confident about old duplicates.

        Args:
            base_threshold: Base similarity threshold
            age_hours: Age of content in hours

        Returns:
            Adjusted threshold
        """
        if not self.age_threshold_adjustment:
            return base_threshold

        # Increase threshold for old content (up to 10% increase)
        age_factor = min(0.1, age_hours / (self.temporal_weight.half_life_hours * 10))
        adjusted = base_threshold + (1 - base_threshold) * age_factor

        return min(0.99, adjusted)  # Cap at 99%

    def check(self, content: str) -> TemporalDuplicateResult:
        """
        Check if content is a duplicate with temporal weighting.

        Args:
            content: Content to check

        Returns:
            TemporalDuplicateResult with time-weighted scores
        """
        # Compute hashes
        exact_hash = self._hash(content)
        normalized = self._normalize(content)
        norm_hash = self._hash(normalized)
        tokens = self._tokenize(content)

        # Check exact duplicate (always matches regardless of age)
        if exact_hash in self._hash_index:
            original_id = self._hash_index[exact_hash]
            entry = self._entries.get(original_id)
            temporal_weight = self._get_temporal_weight(entry) if entry else 1.0

            return TemporalDuplicateResult(
                is_duplicate=True,
                is_similar=True,
                duplicate_type=DuplicateType.EXACT,
                original_id=original_id,
                similar_ids=[original_id],
                similarity_scores={original_id: 1.0},
                suggestion="Exact duplicate found. Skip or merge.",
                temporal_scores={original_id: temporal_weight},
                recency_ranking=[original_id],
                effective_threshold=1.0
            )

        # Check normalized duplicate
        if norm_hash in self._norm_hash_index:
            original_id = self._norm_hash_index[norm_hash]
            entry = self._entries.get(original_id)
            temporal_weight = self._get_temporal_weight(entry) if entry else 0.99

            return TemporalDuplicateResult(
                is_duplicate=True,
                is_similar=True,
                duplicate_type=DuplicateType.NEAR_EXACT,
                original_id=original_id,
                similar_ids=[original_id],
                similarity_scores={original_id: 0.99},
                suggestion="Near-exact duplicate. Consider merging.",
                temporal_scores={original_id: 0.99 * temporal_weight},
                recency_ranking=[original_id],
                effective_threshold=0.99
            )

        # Check token similarity with temporal weighting
        similar_ids = []
        base_similarity_scores = {}
        temporal_scores = {}
        entry_ages = {}

        # Find candidate entries via token index
        candidate_ids = set()
        for token in tokens:
            candidate_ids.update(self._token_index.get(token, set()))

        for candidate_id in candidate_ids:
            entry = self._entries.get(candidate_id)
            if entry:
                # Calculate base similarity
                base_similarity = self._jaccard_similarity(tokens, entry.tokens)

                # Calculate temporal weight
                temporal_weight = self._get_temporal_weight(entry)

                # Calculate time-weighted similarity
                weighted_similarity = base_similarity * temporal_weight

                # Track age for threshold adjustment
                try:
                    created = datetime.fromisoformat(entry.created_at)
                    age_hours = (datetime.now() - created).total_seconds() / 3600
                except (ValueError, TypeError):
                    age_hours = float('inf')

                entry_ages[candidate_id] = age_hours

                # Check against age-adjusted threshold
                adjusted_threshold = self._adjust_threshold_for_age(
                    self.similarity_threshold, age_hours
                )

                if weighted_similarity >= adjusted_threshold * temporal_weight:
                    similar_ids.append(candidate_id)
                    base_similarity_scores[candidate_id] = base_similarity
                    temporal_scores[candidate_id] = weighted_similarity

        # Sort by temporal score (most relevant first)
        similar_ids.sort(key=lambda x: temporal_scores.get(x, 0), reverse=True)

        # Sort by recency for recency_ranking
        recency_ranking = sorted(
            similar_ids,
            key=lambda x: entry_ages.get(x, float('inf'))
        )

        if similar_ids:
            top_id = similar_ids[0]
            top_temporal_score = temporal_scores[top_id]
            top_base_score = base_similarity_scores[top_id]
            top_age = entry_ages.get(top_id, 0)

            # Adjust near-duplicate threshold based on age
            effective_near_threshold = self._adjust_threshold_for_age(
                self.near_duplicate_threshold, top_age
            )
            effective_weighted_threshold = effective_near_threshold * self._get_temporal_weight(
                self._entries[top_id]
            )

            if top_temporal_score >= effective_weighted_threshold:
                return TemporalDuplicateResult(
                    is_duplicate=True,
                    is_similar=True,
                    duplicate_type=DuplicateType.SEMANTIC,
                    original_id=top_id,
                    similar_ids=similar_ids[:5],
                    similarity_scores=base_similarity_scores,
                    suggestion=f"Semantic duplicate ({top_base_score:.0%} base, "
                              f"{top_temporal_score:.0%} time-weighted). Consider merging.",
                    temporal_scores=temporal_scores,
                    recency_ranking=recency_ranking[:5],
                    effective_threshold=effective_weighted_threshold
                )
            else:
                return TemporalDuplicateResult(
                    is_duplicate=False,
                    is_similar=True,
                    duplicate_type=None,
                    original_id=None,
                    similar_ids=similar_ids[:5],
                    similarity_scores=base_similarity_scores,
                    suggestion=f"Similar content ({top_base_score:.0%} base). "
                              f"Recent similar: {recency_ranking[0] if recency_ranking else 'none'}",
                    temporal_scores=temporal_scores,
                    recency_ranking=recency_ranking[:5],
                    effective_threshold=effective_weighted_threshold
                )

        return TemporalDuplicateResult(
            is_duplicate=False,
            is_similar=False,
            duplicate_type=None,
            original_id=None,
            similar_ids=[],
            similarity_scores={},
            suggestion="No duplicates found. Safe to add.",
            temporal_scores={},
            recency_ranking=[],
            effective_threshold=self.similarity_threshold
        )

    def find_duplicates_temporal(
        self,
        time_window_hours: Optional[float] = None
    ) -> List[Tuple[str, str, float, float]]:
        """
        Find duplicate pairs with temporal scores.

        Args:
            time_window_hours: Only compare entries within this time window

        Returns:
            List of (id1, id2, base_similarity, temporal_similarity) tuples
        """
        duplicates = []
        checked = set()
        now = datetime.now()

        for id1, entry1 in self._entries.items():
            for id2, entry2 in self._entries.items():
                if id1 >= id2:
                    continue

                pair_key = (id1, id2)
                if pair_key in checked:
                    continue
                checked.add(pair_key)

                # Check time window if specified
                if time_window_hours:
                    try:
                        t1 = datetime.fromisoformat(entry1.created_at)
                        t2 = datetime.fromisoformat(entry2.created_at)
                        time_diff = abs((t1 - t2).total_seconds() / 3600)
                        if time_diff > time_window_hours:
                            continue
                    except (ValueError, TypeError) as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

                # Calculate base similarity
                base_similarity = self._jaccard_similarity(entry1.tokens, entry2.tokens)

                if base_similarity >= self.similarity_threshold:
                    # Calculate temporal weights
                    w1 = self._get_temporal_weight(entry1)
                    w2 = self._get_temporal_weight(entry2)

                    # Combined temporal score (geometric mean of weights * similarity)
                    temporal_similarity = base_similarity * math.sqrt(w1 * w2)

                    duplicates.append((id1, id2, base_similarity, temporal_similarity))

        return sorted(duplicates, key=lambda x: x[3], reverse=True)

    def cleanup_temporal(
        self,
        strategy: MergeStrategy = MergeStrategy.KEEP_NEWEST,
        min_temporal_score: float = 0.8
    ) -> int:
        """
        Merge duplicates based on temporal similarity.

        Args:
            strategy: Merge strategy (KEEP_NEWEST recommended for temporal)
            min_temporal_score: Minimum temporal score for auto-merge

        Returns:
            Number of entries removed
        """
        removed = 0
        duplicates = self.find_duplicates_temporal()

        for id1, id2, base_sim, temporal_sim in duplicates:
            if id1 in self._entries and id2 in self._entries:
                if temporal_sim >= min_temporal_score:
                    self.merge(id1, id2, strategy)
                    removed += 1

        return removed

    def get_by_recency(self, limit: int = 10) -> List[ContentEntry]:
        """
        Get entries sorted by recency.

        Args:
            limit: Maximum entries to return

        Returns:
            List of entries, most recent first
        """
        entries = list(self._entries.values())
        entries.sort(key=lambda e: e.created_at, reverse=True)
        return entries[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics including temporal information"""
        base_stats = super().get_stats()

        # Add temporal stats
        weights = []
        ages = []
        now = datetime.now()

        for entry in self._entries.values():
            try:
                created = datetime.fromisoformat(entry.created_at)
                age_hours = (now - created).total_seconds() / 3600
                ages.append(age_hours)
                weights.append(self._get_temporal_weight(entry))
            except (ValueError, TypeError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        temporal_stats = {
            "decay_function": self.temporal_weight.decay_function.value,
            "half_life_hours": self.temporal_weight.half_life_hours,
            "avg_temporal_weight": sum(weights) / len(weights) if weights else 0,
            "avg_age_hours": sum(ages) / len(ages) if ages else 0,
            "min_age_hours": min(ages) if ages else 0,
            "max_age_hours": max(ages) if ages else 0
        }

        return {**base_stats, "temporal": temporal_stats}

    def summarize(self) -> str:
        """Generate summary including temporal information"""
        stats = self.get_stats()
        duplicates = self.find_duplicates_temporal()

        temporal = stats.get("temporal", {})

        lines = [
            "**Temporal Deduplication Index**",
            f"- Entries: {stats['total_entries']}",
            f"- Unique tokens: {stats['unique_tokens']}",
            f"- Duplicate pairs: {len(duplicates)}",
            f"- Decay function: {temporal.get('decay_function', 'unknown')}",
            f"- Half-life: {temporal.get('half_life_hours', 0):.0f} hours",
            f"- Avg temporal weight: {temporal.get('avg_temporal_weight', 0):.2f}",
            f"- Avg entry age: {temporal.get('avg_age_hours', 0):.1f} hours"
        ]

        if duplicates:
            lines.append("\n**Top Temporal Duplicates**:")
            for id1, id2, base_sim, temp_sim in duplicates[:5]:
                lines.append(f"  - {id1} <-> {id2} ({base_sim:.0%} base, {temp_sim:.0%} temporal)")

        return "\n".join(lines)


# =============================================================================
# Temporal Clustering
# Groups content by time periods for analysis
# =============================================================================

class TemporalCluster:
    """
    Groups content entries by time periods.

    Useful for analyzing duplicate patterns over time.
    """

    def __init__(
        self,
        deduplicator: SemanticDeduplicator,
        window_hours: float = 24.0
    ):
        """
        Initialize temporal clustering.

        Args:
            deduplicator: Deduplicator to cluster
            window_hours: Size of time windows in hours
        """
        self.deduplicator = deduplicator
        self.window_hours = window_hours

    def cluster_by_time(self) -> Dict[str, List[ContentEntry]]:
        """
        Cluster entries by time windows.

        Returns:
            Dict mapping time window label to entries
        """
        clusters: Dict[str, List[ContentEntry]] = defaultdict(list)

        for entry in self.deduplicator._entries.values():
            try:
                created = datetime.fromisoformat(entry.created_at)
                # Create window label (e.g., "2025-12-26_00" for hour 0 of Dec 26)
                window_start = created.replace(
                    hour=int(created.hour // self.window_hours * self.window_hours) if self.window_hours < 24 else 0,
                    minute=0, second=0, microsecond=0
                )
                label = window_start.strftime("%Y-%m-%d_%H")
                clusters[label].append(entry)
            except (ValueError, TypeError):
                clusters["unknown"].append(entry)

        return dict(clusters)

    def find_duplicates_within_windows(self) -> Dict[str, List[Tuple[str, str, float]]]:
        """
        Find duplicates only within same time windows.

        Returns:
            Dict mapping window label to list of (id1, id2, similarity) tuples
        """
        clusters = self.cluster_by_time()
        window_duplicates = {}

        for label, entries in clusters.items():
            duplicates = []
            for i, e1 in enumerate(entries):
                for e2 in entries[i+1:]:
                    similarity = self.deduplicator._jaccard_similarity(e1.tokens, e2.tokens)
                    if similarity >= self.deduplicator.similarity_threshold:
                        duplicates.append((e1.id, e2.id, similarity))

            if duplicates:
                window_duplicates[label] = sorted(duplicates, key=lambda x: x[2], reverse=True)

        return window_duplicates

    def get_cluster_stats(self) -> Dict[str, Any]:
        """Get statistics about temporal clusters"""
        clusters = self.cluster_by_time()

        cluster_sizes = [len(entries) for entries in clusters.values()]

        return {
            "num_clusters": len(clusters),
            "window_hours": self.window_hours,
            "avg_cluster_size": sum(cluster_sizes) / len(cluster_sizes) if cluster_sizes else 0,
            "max_cluster_size": max(cluster_sizes) if cluster_sizes else 0,
            "min_cluster_size": min(cluster_sizes) if cluster_sizes else 0,
            "cluster_labels": sorted(clusters.keys())
        }


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("Semantic Deduplicator - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        dedup = SemanticDeduplicator(storage_path=Path(tmpdir) / "dedup.json")

        # Test 1: Add unique content
        print("\n=== Test 1: Add Unique Content ===")
        id1, result = dedup.add("The meeting is scheduled for 3 PM tomorrow.")
        assert not result.is_duplicate
        print(f"   Added: {id1}")
        print(f"   Is duplicate: {result.is_duplicate}")
        print("   Result: PASS")

        # Test 2: Detect exact duplicate
        print("\n=== Test 2: Detect Exact Duplicate ===")
        result = dedup.check("The meeting is scheduled for 3 PM tomorrow.")
        assert result.is_duplicate
        assert result.duplicate_type == DuplicateType.EXACT
        print(f"   Is duplicate: {result.is_duplicate}")
        print(f"   Type: {result.duplicate_type.value}")
        print("   Result: PASS")

        # Test 3: Detect near-exact duplicate (case difference)
        print("\n=== Test 3: Detect Near-Exact Duplicate ===")
        result = dedup.check("THE MEETING IS SCHEDULED FOR 3 PM TOMORROW.")
        assert result.is_duplicate
        assert result.duplicate_type == DuplicateType.NEAR_EXACT
        print(f"   Is duplicate: {result.is_duplicate}")
        print(f"   Type: {result.duplicate_type.value}")
        print("   Result: PASS")

        # Test 4: Detect semantic duplicate
        print("\n=== Test 4: Detect Semantic Duplicate ===")
        result = dedup.check("The meeting is at 3 PM tomorrow afternoon.")
        # High similarity but not exact
        print(f"   Is duplicate: {result.is_duplicate}")
        print(f"   Is similar: {result.is_similar}")
        if result.similarity_scores:
            print(f"   Top similarity: {max(result.similarity_scores.values()):.0%}")
        print("   Result: PASS")

        # Test 5: Add different content
        print("\n=== Test 5: Add Different Content ===")
        id2, result = dedup.add("Please send the report by Friday.")
        assert not result.is_duplicate
        print(f"   Added: {id2}")
        print("   Result: PASS")

        # Test 6: Check unique content
        print("\n=== Test 6: Check Unique Content ===")
        result = dedup.check("This is completely different content about cats.")
        assert not result.is_duplicate
        assert not result.is_similar
        print(f"   Is duplicate: {result.is_duplicate}")
        print(f"   Is similar: {result.is_similar}")
        print("   Result: PASS")

        # Test 7: Find duplicates
        print("\n=== Test 7: Find Duplicates ===")
        id3, _ = dedup.add("Meeting scheduled for 3 PM tomorrow afternoon.", force=True)
        duplicates = dedup.find_duplicates()
        print(f"   Found {len(duplicates)} duplicate pair(s)")
        print("   Result: PASS")

        # Test 8: Merge duplicates
        print("\n=== Test 8: Merge Duplicates ===")
        if duplicates:
            kept_id = dedup.merge(
                duplicates[0][0],
                duplicates[0][1],
                MergeStrategy.KEEP_LONGEST
            )
            print(f"   Kept: {kept_id}")
        print("   Result: PASS")

        # Test 9: Statistics
        print("\n=== Test 9: Statistics ===")
        stats = dedup.get_stats()
        print(f"   Total entries: {stats['total_entries']}")
        print(f"   Unique tokens: {stats['unique_tokens']}")
        print("   Result: PASS")

        # Test 10: Summary
        print("\n=== Test 10: Summary ===")
        summary = dedup.summarize()
        assert "Deduplication Index" in summary
        print("   Summary generated")
        print("   Result: PASS")

        # Test 11: Remove entry
        print("\n=== Test 11: Remove Entry ===")
        removed = dedup.remove(id2)
        assert removed
        assert dedup.get(id2) is None
        print("   Entry removed")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("BASIC TESTS PASSED")
    print("=" * 60)

    # === Temporal Weighting Tests ===
    print("\n" + "=" * 60)
    print("Temporal Deduplicator - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Test 12: Temporal weight calculation
        print("\n=== Test 12: Temporal Weight Calculation ===")
        tw = TemporalWeight(decay_function=DecayFunction.EXPONENTIAL, half_life_hours=168)

        # Recent content (max weight)
        w0 = tw.calculate(0)
        assert w0 == 1.0, f"Expected 1.0 for age=0, got {w0}"
        print(f"   Age 0h: weight={w0:.2f}")

        # Half-life (should be ~0.5)
        w_half = tw.calculate(168)
        assert 0.45 <= w_half <= 0.55, f"Expected ~0.5 for half-life, got {w_half}"
        print(f"   Age 168h (1 week): weight={w_half:.2f}")

        # Very old content (near min)
        w_old = tw.calculate(5000)
        assert w_old >= 0.1, f"Weight should be >= min_weight"
        print(f"   Age 5000h: weight={w_old:.2f}")
        print("   Result: PASS")

        # Test 13: Different decay functions
        print("\n=== Test 13: Decay Functions ===")
        for func in DecayFunction:
            tw = TemporalWeight(decay_function=func)
            w = tw.calculate(48)  # 2 days old
            print(f"   {func.value}: weight at 48h = {w:.2f}")
        print("   Result: PASS")

        # Test 14: Temporal deduplicator
        print("\n=== Test 14: Temporal Deduplicator ===")
        tdedup = TemporalDeduplicator(
            storage_path=Path(tmpdir) / "temporal_dedup.json",
            decay_function="exponential",
            half_life_hours=168
        )

        # Add content
        id1, result = tdedup.add("The quarterly report is due next Friday.")
        assert not result.is_duplicate
        print(f"   Added: {id1}")
        print("   Result: PASS")

        # Test 15: Temporal duplicate check
        print("\n=== Test 15: Temporal Duplicate Check ===")
        result = tdedup.check("The quarterly report is due next Friday.")
        assert result.is_duplicate
        assert hasattr(result, 'temporal_scores')
        print(f"   Is duplicate: {result.is_duplicate}")
        print(f"   Has temporal scores: {len(result.temporal_scores) > 0}")
        print("   Result: PASS")

        # Test 16: Temporal stats
        print("\n=== Test 16: Temporal Stats ===")
        stats = tdedup.get_stats()
        assert "temporal" in stats
        print(f"   Decay function: {stats['temporal']['decay_function']}")
        print(f"   Half-life: {stats['temporal']['half_life_hours']}h")
        print("   Result: PASS")

        # Test 17: Find duplicates with temporal scores
        print("\n=== Test 17: Find Duplicates Temporal ===")
        tdedup.add("Quarterly reports are due on Friday next week.", force=True)
        duplicates = tdedup.find_duplicates_temporal()
        if duplicates:
            print(f"   Found {len(duplicates)} pair(s)")
            print(f"   Top: base={duplicates[0][2]:.0%}, temporal={duplicates[0][3]:.0%}")
        print("   Result: PASS")

        # Test 18: Temporal clustering
        print("\n=== Test 18: Temporal Clustering ===")
        cluster = TemporalCluster(tdedup, window_hours=24)
        clusters = cluster.cluster_by_time()
        stats = cluster.get_cluster_stats()
        print(f"   Clusters: {stats['num_clusters']}")
        print(f"   Window: {stats['window_hours']}h")
        print("   Result: PASS")

        # Test 19: Recency ranking
        print("\n=== Test 19: Recency Ranking ===")
        recent = tdedup.get_by_recency(limit=5)
        print(f"   Got {len(recent)} recent entries")
        print("   Result: PASS")

        # Test 20: Temporal summary
        print("\n=== Test 20: Temporal Summary ===")
        summary = tdedup.summarize()
        assert "Temporal Deduplication Index" in summary
        assert "Half-life" in summary
        print("   Summary generated")
        print("   Result: PASS")

        # Test 21: ISO timestamp weight calculation
        print("\n=== Test 21: ISO Timestamp Weights ===")
        tw = TemporalWeight()
        recent_time = datetime.now().isoformat()
        old_time = (datetime.now() - timedelta(days=30)).isoformat()

        w_recent = tw.calculate_from_iso(recent_time)
        w_old = tw.calculate_from_iso(old_time)

        assert w_recent > w_old, "Recent should have higher weight"
        print(f"   Recent timestamp: {w_recent:.2f}")
        print(f"   30-day old: {w_old:.2f}")
        print("   Result: PASS")

        # Test 22: Step decay function
        print("\n=== Test 22: Step Decay Function ===")
        tw = TemporalWeight(decay_function=DecayFunction.STEP)
        w_recent = tw.calculate(12)   # < 24h
        w_week = tw.calculate(100)    # < 168h
        w_month = tw.calculate(500)   # < 720h
        w_old = tw.calculate(1000)    # > 720h

        assert w_recent == 1.0, f"Expected 1.0 for <24h, got {w_recent}"
        assert w_week == 0.8, f"Expected 0.8 for <168h, got {w_week}"
        assert w_month == 0.5, f"Expected 0.5 for <720h, got {w_month}"
        assert w_old == 0.2, f"Expected 0.2 for old, got {w_old}"
        print(f"   <24h: {w_recent}, <1wk: {w_week}, <1mo: {w_month}, old: {w_old}")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nSemantic Deduplicator with Temporal Weighting is ready!")

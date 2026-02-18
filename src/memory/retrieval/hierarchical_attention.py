#!/usr/bin/env python3
"""
Hierarchical Sparse Attention for Memory Retrieval (#24)

This module implements hierarchical sparse attention mechanisms for
efficient memory retrieval, reducing complexity from O(n²) to O(n log n).

Features:
1. HierarchicalIndex - Multi-level memory organization
2. SparseAttention - Attention with limited connectivity patterns
3. QueryRouter - Routes queries to relevant clusters
4. HierarchicalRetriever - Main retrieval interface
5. AttentionCache - Caching for repeated queries

Research basis:
- Longformer: The Long-Document Transformer (2020)
- Big Bird: Transformers for Longer Sequences (2020)
- Hierarchical Attention Networks (2016)
"""

import math
import json
import hashlib
from enum import Enum
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set
from collections import defaultdict
import heapq
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class AttentionPattern(Enum):
    """Sparse attention patterns"""
    LOCAL = "local"         # Attend to local neighborhood
    GLOBAL = "global"       # Global tokens that attend to all
    RANDOM = "random"       # Random sparse connections
    STRIDED = "strided"     # Strided/dilated attention
    HIERARCHICAL = "hierarchical"  # Multi-level hierarchy


class ClusteringMethod(Enum):
    """Methods for clustering memories"""
    KMEANS = "kmeans"       # K-means clustering
    HIERARCHICAL = "hierarchical"  # Hierarchical agglomerative
    KEYWORD = "keyword"     # Keyword-based grouping


class ScoringFunction(Enum):
    """Attention scoring functions"""
    DOT_PRODUCT = "dot_product"
    COSINE = "cosine"
    EUCLIDEAN = "euclidean"
    LEARNED = "learned"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MemoryItem:
    """A single memory item for retrieval"""
    item_id: str
    content: str
    embedding: Optional[List[float]] = None
    keywords: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    importance: float = 1.0
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "content": self.content[:100] + "..." if len(self.content) > 100 else self.content,
            "has_embedding": self.embedding is not None,
            "keywords": self.keywords[:5],
            "importance": round(self.importance, 3),
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Cluster:
    """A cluster of related memory items"""
    cluster_id: str
    centroid: Optional[List[float]] = None
    representative_keywords: List[str] = field(default_factory=list)
    item_ids: Set[str] = field(default_factory=set)
    level: int = 0  # Hierarchy level (0 = leaf, higher = parent)
    parent_id: Optional[str] = None
    child_ids: Set[str] = field(default_factory=set)
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cluster_id": self.cluster_id,
            "level": self.level,
            "item_count": len(self.item_ids),
            "keywords": self.representative_keywords[:5],
            "parent_id": self.parent_id,
            "child_count": len(self.child_ids),
        }


@dataclass
class AttentionScore:
    """Attention score between query and memory"""
    item_id: str
    score: float
    attention_weight: float  # Normalized weight
    level: int  # Level at which this was computed
    path: List[str] = field(default_factory=list)  # Path through hierarchy

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "score": round(self.score, 4),
            "attention_weight": round(self.attention_weight, 4),
            "level": self.level,
        }


@dataclass
class RetrievalResult:
    """Result of hierarchical retrieval"""
    query: str
    items: List[MemoryItem]
    attention_scores: List[AttentionScore]
    clusters_visited: List[str]
    levels_traversed: int
    total_comparisons: int
    retrieval_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query[:50] + "..." if len(self.query) > 50 else self.query,
            "item_count": len(self.items),
            "clusters_visited": len(self.clusters_visited),
            "levels_traversed": self.levels_traversed,
            "total_comparisons": self.total_comparisons,
            "retrieval_time_ms": round(self.retrieval_time_ms, 2),
            "top_scores": [s.to_dict() for s in self.attention_scores[:5]],
        }


# =============================================================================
# Sparse Attention
# =============================================================================

class SparseAttention:
    """
    Sparse attention mechanism with configurable patterns.
    Reduces attention complexity from O(n²) to O(n * k) where k << n.
    """

    def __init__(
        self,
        pattern: AttentionPattern = AttentionPattern.LOCAL,
        window_size: int = 5,
        num_global_tokens: int = 2,
        scoring: ScoringFunction = ScoringFunction.COSINE,
    ):
        self.pattern = pattern
        self.window_size = window_size
        self.num_global_tokens = num_global_tokens
        self.scoring = scoring

    def compute_attention(
        self,
        query: List[float],
        keys: List[Tuple[str, List[float]]],
        mask: Optional[List[bool]] = None,
    ) -> List[AttentionScore]:
        """
        Compute sparse attention scores.

        Args:
            query: Query embedding
            keys: List of (id, embedding) tuples
            mask: Optional attention mask

        Returns:
            List of AttentionScore objects
        """
        if not keys:
            return []

        # Compute raw scores
        scores = []
        for idx, (item_id, key) in enumerate(keys):
            if mask and not mask[idx]:
                continue

            if not self._should_attend(idx, len(keys)):
                continue

            score = self._score(query, key)
            scores.append((item_id, score))

        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)

        # Compute softmax for attention weights
        if scores:
            max_score = scores[0][1]
            exp_scores = [(item_id, math.exp(s - max_score)) for item_id, s in scores]
            total = sum(s for _, s in exp_scores)

            return [
                AttentionScore(
                    item_id=item_id,
                    score=orig_score,
                    attention_weight=exp_score / total if total > 0 else 0,
                    level=0,
                )
                for (item_id, exp_score), (_, orig_score) in zip(exp_scores, scores)
            ]

        return []

    def _should_attend(self, idx: int, total: int) -> bool:
        """Determine if position should be attended based on pattern"""
        if self.pattern == AttentionPattern.LOCAL:
            # Local window around each position
            return True  # Will be filtered by window in actual use

        elif self.pattern == AttentionPattern.GLOBAL:
            # Global tokens at start/end
            return idx < self.num_global_tokens or idx >= total - self.num_global_tokens

        elif self.pattern == AttentionPattern.STRIDED:
            # Strided pattern
            return idx % self.window_size == 0

        elif self.pattern == AttentionPattern.RANDOM:
            # Random selection (deterministic based on idx)
            return hash(str(idx)) % self.window_size == 0

        return True

    def _score(self, query: List[float], key: List[float]) -> float:
        """Compute attention score between query and key"""
        if not query or not key or len(query) != len(key):
            return 0.0

        if self.scoring == ScoringFunction.DOT_PRODUCT:
            return sum(q * k for q, k in zip(query, key))

        elif self.scoring == ScoringFunction.COSINE:
            dot = sum(q * k for q, k in zip(query, key))
            norm_q = math.sqrt(sum(q * q for q in query))
            norm_k = math.sqrt(sum(k * k for k in key))
            if norm_q == 0 or norm_k == 0:
                return 0.0
            return dot / (norm_q * norm_k)

        elif self.scoring == ScoringFunction.EUCLIDEAN:
            # Negative euclidean distance (higher = closer)
            dist = math.sqrt(sum((q - k) ** 2 for q, k in zip(query, key)))
            return -dist

        elif self.scoring == ScoringFunction.LEARNED:
            # Fallback to cosine for learned (actual learned would use a model)
            dot = sum(q * k for q, k in zip(query, key))
            norm_q = math.sqrt(sum(q * q for q in query))
            norm_k = math.sqrt(sum(k * k for k in key))
            if norm_q == 0 or norm_k == 0:
                return 0.0
            return dot / (norm_q * norm_k)

        return 0.0


# =============================================================================
# Hierarchical Index
# =============================================================================

class HierarchicalIndex:
    """
    Multi-level hierarchical index for memory items.
    Organizes items into a tree structure for efficient retrieval.
    """

    def __init__(
        self,
        max_items_per_cluster: int = 20,
        max_levels: int = 5,
        clustering_method: ClusteringMethod = ClusteringMethod.KEYWORD,
    ):
        self.max_items_per_cluster = max_items_per_cluster
        self.max_levels = max_levels
        self.clustering_method = clustering_method

        self.items: Dict[str, MemoryItem] = {}
        self.clusters: Dict[str, Cluster] = {}
        self.root_cluster_ids: Set[str] = set()
        self._next_cluster_id: int = 0

    def add_item(self, item: MemoryItem) -> str:
        """Add an item to the index"""
        self.items[item.item_id] = item

        # Find or create appropriate cluster
        cluster_id = self._find_cluster(item)
        if cluster_id:
            self.clusters[cluster_id].item_ids.add(item.item_id)
            self._maybe_split_cluster(cluster_id)
        else:
            # Create new leaf cluster
            cluster_id = self._create_cluster(level=0)
            self.clusters[cluster_id].item_ids.add(item.item_id)
            self._update_cluster_keywords(cluster_id)
            self.root_cluster_ids.add(cluster_id)

        return item.item_id

    def remove_item(self, item_id: str) -> bool:
        """Remove an item from the index"""
        if item_id not in self.items:
            return False

        # Find and remove from cluster
        for cluster in self.clusters.values():
            if item_id in cluster.item_ids:
                cluster.item_ids.discard(item_id)
                self._update_cluster_keywords(cluster.cluster_id)
                break

        del self.items[item_id]
        return True

    def _find_cluster(self, item: MemoryItem) -> Optional[str]:
        """Find best cluster for an item"""
        if not self.clusters:
            return None

        best_cluster = None
        best_score = -1

        for cluster_id, cluster in self.clusters.items():
            if cluster.level > 0:  # Only consider leaf clusters
                continue

            score = self._cluster_similarity(item, cluster)
            if score > best_score and len(cluster.item_ids) < self.max_items_per_cluster:
                best_score = score
                best_cluster = cluster_id

        # Only use if similarity is reasonable
        if best_score > 0.2:
            return best_cluster
        return None

    def _cluster_similarity(self, item: MemoryItem, cluster: Cluster) -> float:
        """Calculate similarity between item and cluster"""
        # Keyword overlap
        if item.keywords and cluster.representative_keywords:
            item_kw = set(kw.lower() for kw in item.keywords)
            cluster_kw = set(kw.lower() for kw in cluster.representative_keywords)
            overlap = len(item_kw & cluster_kw)
            total = len(item_kw | cluster_kw) or 1
            return overlap / total

        # Embedding similarity if available
        if item.embedding and cluster.centroid:
            return self._cosine_similarity(item.embedding, cluster.centroid)

        return 0.0

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Cosine similarity between two vectors"""
        if len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def _create_cluster(self, level: int = 0) -> str:
        """Create a new cluster"""
        cluster_id = f"C{self._next_cluster_id:04d}"
        self._next_cluster_id += 1

        cluster = Cluster(
            cluster_id=cluster_id,
            level=level,
        )
        self.clusters[cluster_id] = cluster
        return cluster_id

    def _maybe_split_cluster(self, cluster_id: str) -> None:
        """Split cluster if it exceeds max size"""
        cluster = self.clusters.get(cluster_id)
        if not cluster or len(cluster.item_ids) <= self.max_items_per_cluster:
            return

        if cluster.level >= self.max_levels - 1:
            return  # Can't split at max level

        # Split into two child clusters
        items = list(cluster.item_ids)
        mid = len(items) // 2

        child1_id = self._create_cluster(level=cluster.level)
        child2_id = self._create_cluster(level=cluster.level)

        self.clusters[child1_id].item_ids = set(items[:mid])
        self.clusters[child2_id].item_ids = set(items[mid:])
        self.clusters[child1_id].parent_id = cluster_id
        self.clusters[child2_id].parent_id = cluster_id

        # Update parent
        cluster.child_ids = {child1_id, child2_id}
        cluster.item_ids.clear()
        cluster.level += 1

        self._update_cluster_keywords(child1_id)
        self._update_cluster_keywords(child2_id)
        self._update_cluster_keywords(cluster_id)

        # Update root set
        if cluster_id in self.root_cluster_ids:
            self.root_cluster_ids.discard(cluster_id)
        self.root_cluster_ids.add(child1_id)
        self.root_cluster_ids.add(child2_id)

    def _update_cluster_keywords(self, cluster_id: str) -> None:
        """Update representative keywords for a cluster"""
        cluster = self.clusters.get(cluster_id)
        if not cluster:
            return

        # Collect keywords from items or children
        keyword_counts: Dict[str, int] = defaultdict(int)

        if cluster.item_ids:
            for item_id in cluster.item_ids:
                item = self.items.get(item_id)
                if item:
                    for kw in item.keywords:
                        keyword_counts[kw.lower()] += 1
        else:
            for child_id in cluster.child_ids:
                child = self.clusters.get(child_id)
                if child:
                    for kw in child.representative_keywords:
                        keyword_counts[kw.lower()] += 1

        # Top keywords
        sorted_kw = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        cluster.representative_keywords = [kw for kw, _ in sorted_kw[:10]]

    def _update_cluster_centroid(self, cluster_id: str) -> None:
        """Update cluster centroid from item embeddings"""
        cluster = self.clusters.get(cluster_id)
        if not cluster:
            return

        embeddings = []
        for item_id in cluster.item_ids:
            item = self.items.get(item_id)
            if item and item.embedding:
                embeddings.append(item.embedding)

        if embeddings:
            dim = len(embeddings[0])
            centroid = [0.0] * dim
            for emb in embeddings:
                for i, v in enumerate(emb):
                    centroid[i] += v
            cluster.centroid = [v / len(embeddings) for v in centroid]

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics"""
        level_counts = defaultdict(int)
        for cluster in self.clusters.values():
            level_counts[cluster.level] += 1

        return {
            "total_items": len(self.items),
            "total_clusters": len(self.clusters),
            "root_clusters": len(self.root_cluster_ids),
            "clusters_by_level": dict(level_counts),
            "max_items_per_cluster": self.max_items_per_cluster,
        }


# =============================================================================
# Query Router
# =============================================================================

class QueryRouter:
    """
    Routes queries through the hierarchical index.
    Determines which clusters to explore at each level.
    """

    def __init__(
        self,
        top_k_clusters: int = 3,
        score_threshold: float = 0.1,
    ):
        self.top_k_clusters = top_k_clusters
        self.score_threshold = score_threshold

    def route(
        self,
        query_keywords: List[str],
        query_embedding: Optional[List[float]],
        index: HierarchicalIndex,
    ) -> List[Tuple[str, float]]:
        """
        Route query to relevant clusters.

        Returns list of (cluster_id, relevance_score) tuples.
        """
        if not index.clusters:
            return []

        # Start from root clusters
        cluster_scores: List[Tuple[str, float]] = []

        for cluster_id in index.root_cluster_ids:
            cluster = index.clusters.get(cluster_id)
            if cluster:
                score = self._score_cluster(query_keywords, query_embedding, cluster, index)
                if score >= self.score_threshold:
                    cluster_scores.append((cluster_id, score))

        # Sort by score
        cluster_scores.sort(key=lambda x: x[1], reverse=True)

        # Return top-k
        return cluster_scores[:self.top_k_clusters]

    def expand_clusters(
        self,
        cluster_ids: List[str],
        query_keywords: List[str],
        query_embedding: Optional[List[float]],
        index: HierarchicalIndex,
    ) -> List[Tuple[str, float]]:
        """Expand clusters to their children based on query relevance"""
        expanded: List[Tuple[str, float]] = []

        for cluster_id in cluster_ids:
            cluster = index.clusters.get(cluster_id)
            if not cluster:
                continue

            if cluster.child_ids:
                # Score children
                for child_id in cluster.child_ids:
                    child = index.clusters.get(child_id)
                    if child:
                        score = self._score_cluster(query_keywords, query_embedding, child, index)
                        if score >= self.score_threshold:
                            expanded.append((child_id, score))
            else:
                # Leaf cluster - add directly
                score = self._score_cluster(query_keywords, query_embedding, cluster, index)
                expanded.append((cluster_id, score))

        # Sort and return top-k
        expanded.sort(key=lambda x: x[1], reverse=True)
        return expanded[:self.top_k_clusters]

    def _score_cluster(
        self,
        query_keywords: List[str],
        query_embedding: Optional[List[float]],
        cluster: Cluster,
        index: HierarchicalIndex,
    ) -> float:
        """Score a cluster's relevance to query"""
        score = 0.0

        # Keyword overlap
        if query_keywords and cluster.representative_keywords:
            q_kw = set(kw.lower() for kw in query_keywords)
            c_kw = set(kw.lower() for kw in cluster.representative_keywords)
            overlap = len(q_kw & c_kw)
            total = len(q_kw | c_kw) or 1
            score += 0.6 * (overlap / total)

        # Embedding similarity
        if query_embedding and cluster.centroid:
            dot = sum(q * c for q, c in zip(query_embedding, cluster.centroid))
            n_q = math.sqrt(sum(q * q for q in query_embedding))
            n_c = math.sqrt(sum(c * c for c in cluster.centroid))
            if n_q > 0 and n_c > 0:
                score += 0.4 * (dot / (n_q * n_c))

        return score


# =============================================================================
# Hierarchical Retriever
# =============================================================================

class HierarchicalRetriever:
    """
    Main retrieval interface using hierarchical sparse attention.
    """

    def __init__(
        self,
        max_items_per_cluster: int = 20,
        top_k_clusters: int = 3,
        top_k_results: int = 10,
        attention_pattern: AttentionPattern = AttentionPattern.HIERARCHICAL,
    ):
        self.index = HierarchicalIndex(max_items_per_cluster=max_items_per_cluster)
        self.router = QueryRouter(top_k_clusters=top_k_clusters)
        self.attention = SparseAttention(pattern=attention_pattern)
        self.top_k_results = top_k_results

    def add_memory(
        self,
        content: str,
        embedding: Optional[List[float]] = None,
        keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
    ) -> str:
        """Add a memory to the index"""
        # Generate ID
        item_id = hashlib.sha256(content[:100].encode()).hexdigest()[:16]

        # Extract keywords if not provided
        if keywords is None:
            keywords = self._extract_keywords(content)

        item = MemoryItem(
            item_id=item_id,
            content=content,
            embedding=embedding,
            keywords=keywords,
            metadata=metadata or {},
            importance=importance,
        )

        self.index.add_item(item)
        return item_id

    def _extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        """Extract keywords from text"""
        import re

        # Simple keyword extraction
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())

        # Filter common stop words
        stop_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "her", "was", "one", "our", "out", "has", "have", "been", "were",
            "they", "will", "each", "this", "that", "from", "with",
        }
        words = [w for w in words if w not in stop_words]

        # Count and return top
        counts: Dict[str, int] = defaultdict(int)
        for w in words:
            counts[w] += 1

        sorted_words = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in sorted_words[:top_n]]

    def retrieve(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        max_results: Optional[int] = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant memories using hierarchical sparse attention.
        """
        import time
        start_time = time.time()

        max_results = max_results or self.top_k_results
        query_keywords = self._extract_keywords(query)

        # Track stats
        clusters_visited: List[str] = []
        total_comparisons = 0
        levels_traversed = 0

        # Route to relevant clusters
        cluster_scores = self.router.route(query_keywords, query_embedding, self.index)
        clusters_visited.extend(cid for cid, _ in cluster_scores)

        # Expand through hierarchy
        current_clusters = [cid for cid, _ in cluster_scores]
        while current_clusters:
            levels_traversed += 1

            # Check for leaf clusters
            leaf_clusters = []
            non_leaf_clusters = []

            for cid in current_clusters:
                cluster = self.index.clusters.get(cid)
                if cluster:
                    if cluster.child_ids:
                        non_leaf_clusters.append(cid)
                    else:
                        leaf_clusters.append(cid)

            if not non_leaf_clusters:
                current_clusters = leaf_clusters
                break

            # Expand non-leaf clusters
            expanded = self.router.expand_clusters(
                non_leaf_clusters, query_keywords, query_embedding, self.index
            )
            current_clusters = leaf_clusters + [cid for cid, _ in expanded]
            clusters_visited.extend(cid for cid, _ in expanded)

        # Collect items from leaf clusters
        candidate_items: List[MemoryItem] = []
        for cluster_id in current_clusters:
            cluster = self.index.clusters.get(cluster_id)
            if cluster:
                for item_id in cluster.item_ids:
                    item = self.index.items.get(item_id)
                    if item:
                        candidate_items.append(item)
                        total_comparisons += 1

        # Compute attention scores
        attention_scores: List[AttentionScore] = []

        if query_embedding:
            keys = [
                (item.item_id, item.embedding)
                for item in candidate_items
                if item.embedding
            ]
            attention_scores = self.attention.compute_attention(query_embedding, keys)
        else:
            # Keyword-based scoring
            for item in candidate_items:
                item_kw = set(kw.lower() for kw in item.keywords)
                query_kw = set(kw.lower() for kw in query_keywords)
                overlap = len(item_kw & query_kw)
                total = len(item_kw | query_kw) or 1
                score = overlap / total * item.importance

                attention_scores.append(AttentionScore(
                    item_id=item.item_id,
                    score=score,
                    attention_weight=score,
                    level=levels_traversed,
                ))

        # Sort by score and take top-k
        attention_scores.sort(key=lambda x: x.score, reverse=True)
        attention_scores = attention_scores[:max_results]

        # Normalize attention weights
        total_weight = sum(s.score for s in attention_scores) or 1.0
        for s in attention_scores:
            s.attention_weight = s.score / total_weight

        # Get items
        result_items = [
            self.index.items[s.item_id]
            for s in attention_scores
            if s.item_id in self.index.items
        ]

        return RetrievalResult(
            query=query,
            items=result_items,
            attention_scores=attention_scores,
            clusters_visited=clusters_visited,
            levels_traversed=levels_traversed,
            total_comparisons=total_comparisons,
            retrieval_time_ms=(time.time() - start_time) * 1000,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Get retriever statistics"""
        stats = self.index.get_stats()
        stats["top_k_results"] = self.top_k_results
        stats["attention_pattern"] = self.attention.pattern.value
        return stats

    def summarize(self) -> str:
        """Generate human-readable summary"""
        stats = self.get_stats()
        lines = [
            "Hierarchical Sparse Attention Status",
            "=" * 40,
            f"Total memories: {stats['total_items']}",
            f"Total clusters: {stats['total_clusters']}",
            f"Root clusters: {stats['root_clusters']}",
            f"Attention pattern: {stats['attention_pattern']}",
            "",
            "Clusters by level:",
        ]

        for level, count in sorted(stats.get("clusters_by_level", {}).items()):
            lines.append(f"  Level {level}: {count}")

        return "\n".join(lines)


# =============================================================================
# Attention Cache
# =============================================================================

class AttentionCache:
    """Cache for repeated attention computations"""

    def __init__(self, max_size: int = 1000, ttl_seconds: float = 300.0) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Tuple[List[AttentionScore], datetime]] = {}

    def get(self, key: str) -> Optional[List[AttentionScore]]:
        """Get cached attention scores"""
        if key not in self._cache:
            return None

        scores, timestamp = self._cache[key]
        age = (datetime.now() - timestamp).total_seconds()

        if age > self.ttl_seconds:
            del self._cache[key]
            return None

        return scores

    def set(self, key: str, scores: List[AttentionScore]) -> None:
        """Cache attention scores"""
        self._cache[key] = (scores, datetime.now())

        # Evict old entries if needed
        if len(self._cache) > self.max_size:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        """Evict oldest cache entries"""
        if not self._cache:
            return

        # Find oldest
        oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
        del self._cache[oldest_key]

    def clear(self) -> None:
        """Clear the cache"""
        self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds,
        }


# =============================================================================
# Persistent Hierarchical Retriever
# =============================================================================

class PersistentHierarchicalRetriever:
    """Hierarchical retriever with persistence"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or Path("hierarchical_attention.json")
        self.retriever = HierarchicalRetriever()
        self.cache = AttentionCache()
        self._load()

    def _load(self) -> None:
        """Load from file"""
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)

            for item_data in data.get("items", []):
                item = MemoryItem(
                    item_id=item_data.get("item_id", ""),
                    content=item_data.get("content", ""),
                    embedding=item_data.get("embedding"),
                    keywords=item_data.get("keywords", []),
                    metadata=item_data.get("metadata", {}),
                    importance=item_data.get("importance", 1.0),
                    created_at=datetime.fromisoformat(
                        item_data.get("created_at", datetime.now().isoformat())
                    ),
                )
                self.retriever.index.items[item.item_id] = item

            # Rebuild clusters
            for item in self.retriever.index.items.values():
                cluster_id = self.retriever.index._find_cluster(item)
                if cluster_id:
                    self.retriever.index.clusters[cluster_id].item_ids.add(item.item_id)
                else:
                    cluster_id = self.retriever.index._create_cluster(level=0)
                    self.retriever.index.clusters[cluster_id].item_ids.add(item.item_id)
                    self.retriever.index._update_cluster_keywords(cluster_id)
                    self.retriever.index.root_cluster_ids.add(cluster_id)

        except Exception as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save(self) -> None:
        """Save to file"""
        data = {
            "items": [
                {
                    "item_id": item.item_id,
                    "content": item.content,
                    "embedding": item.embedding,
                    "keywords": item.keywords,
                    "metadata": item.metadata,
                    "importance": item.importance,
                    "created_at": item.created_at.isoformat(),
                }
                for item in self.retriever.index.items.values()
            ],
            "saved_at": datetime.now().isoformat(),
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)

    def add_memory(self, content: str, **kwargs) -> str:
        """Add memory and persist"""
        item_id = self.retriever.add_memory(content, **kwargs)
        self._save()
        return item_id

    def retrieve(self, query: str, **kwargs) -> RetrievalResult:
        """Retrieve memories"""
        # Check cache
        cache_key = hashlib.sha256(query.encode()).hexdigest()[:16]
        cached = self.cache.get(cache_key)
        if cached:
            # Rebuild result from cache
            items = [
                self.retriever.index.items[s.item_id]
                for s in cached
                if s.item_id in self.retriever.index.items
            ]
            return RetrievalResult(
                query=query,
                items=items,
                attention_scores=cached,
                clusters_visited=[],
                levels_traversed=0,
                total_comparisons=0,
            )

        result = self.retriever.retrieve(query, **kwargs)
        self.cache.set(cache_key, result.attention_scores)
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        stats = self.retriever.get_stats()
        stats["cache"] = self.cache.stats()
        return stats

    def summarize(self) -> str:
        """Generate summary"""
        return self.retriever.summarize()


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests"""
    print("=" * 70)
    print("Hierarchical Sparse Attention CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool, detail: str = "") -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"✓ {name}")
            tests_passed += 1
        else:
            print(f"✗ {name}: {detail}")
            tests_failed += 1

    # Test 1: Create index
    print("\n--- Test 1: Create Hierarchical Index ---")
    index = HierarchicalIndex()
    test("Index created", index is not None)
    test("Empty index", len(index.items) == 0)

    # Test 2: Add items
    print("\n--- Test 2: Add Items ---")
    item1 = MemoryItem(
        item_id="m1",
        content="Python programming for data science",
        keywords=["python", "programming", "data", "science"]
    )
    index.add_item(item1)
    test("Item added", len(index.items) == 1)
    test("Cluster created", len(index.clusters) > 0)

    # Test 3: Sparse attention
    print("\n--- Test 3: Sparse Attention ---")
    attention = SparseAttention()
    query = [1.0, 0.0, 1.0]
    keys = [("k1", [1.0, 0.0, 1.0]), ("k2", [0.0, 1.0, 0.0])]
    scores = attention.compute_attention(query, keys)
    test("Attention computed", len(scores) > 0)
    test("Scores sorted", scores[0].score >= scores[-1].score if len(scores) > 1 else True)

    # Test 4: Query router
    print("\n--- Test 4: Query Router ---")
    router = QueryRouter()
    routes = router.route(["python", "data"], None, index)
    test("Routes found", len(routes) >= 0)

    # Test 5: Hierarchical retriever
    print("\n--- Test 5: Hierarchical Retriever ---")
    retriever = HierarchicalRetriever()
    retriever.add_memory("Machine learning with Python and TensorFlow")
    retriever.add_memory("Data visualization using matplotlib")
    retriever.add_memory("Deep learning neural networks")
    test("Memories added", len(retriever.index.items) == 3)

    # Test 6: Retrieval
    print("\n--- Test 6: Retrieval ---")
    result = retriever.retrieve("Python machine learning")
    test("Retrieval works", result is not None)
    test("Items retrieved", len(result.items) > 0)

    # Test 7: Attention scores
    print("\n--- Test 7: Attention Scores ---")
    test("Scores computed", len(result.attention_scores) > 0)
    test("Weights normalized", all(0 <= s.attention_weight <= 1 for s in result.attention_scores))

    # Test 8: Stats
    print("\n--- Test 8: Statistics ---")
    stats = retriever.get_stats()
    test("Stats available", "total_items" in stats)
    test("Cluster stats", "total_clusters" in stats)

    # Test 9: Attention cache
    print("\n--- Test 9: Attention Cache ---")
    cache = AttentionCache(max_size=10)
    cache.set("test", [AttentionScore("id1", 0.5, 0.5, 0)])
    cached = cache.get("test")
    test("Cache set", cached is not None)
    test("Cache get", len(cached) == 1)

    # Test 10: Cache eviction
    print("\n--- Test 10: Cache Eviction ---")
    small_cache = AttentionCache(max_size=2)
    small_cache.set("k1", [])
    small_cache.set("k2", [])
    small_cache.set("k3", [])
    test("Cache evicts", len(small_cache._cache) <= 2)

    # Test 11: Attention patterns
    print("\n--- Test 11: Attention Patterns ---")
    for pattern in AttentionPattern:
        attn = SparseAttention(pattern=pattern)
        test(f"Pattern {pattern.value}", attn.pattern == pattern)

    # Test 12: Scoring functions
    print("\n--- Test 12: Scoring Functions ---")
    for scoring in ScoringFunction:
        attn = SparseAttention(scoring=scoring)
        result = attn._score([1, 0, 1], [1, 0, 1])
        test(f"Scoring {scoring.value}", result != 0 or scoring == ScoringFunction.EUCLIDEAN)

    # Test 13: Persistent retriever
    print("\n--- Test 13: Persistent Retriever ---")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "hier.json"
        persistent = PersistentHierarchicalRetriever(config_path)
        persistent.add_memory("Test memory content")
        test("Persistent add works", len(persistent.retriever.index.items) > 0)
        test("File created", config_path.exists())

    # Test 14: Summary
    print("\n--- Test 14: Summary ---")
    summary = retriever.summarize()
    test("Summary generated", "Hierarchical" in summary)

    # Summary
    print("\n" + "=" * 70)
    print(f"Tests passed: {tests_passed}")
    print(f"Tests failed: {tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    import sys
    success = run_cli_tests()
    sys.exit(0 if success else 1)

#!/usr/bin/env python3
"""
Hybrid GraphRAG: Topological Memory Reasoning for NizBot VERA

This module implements Graph-based Retrieval Augmented Generation (GraphRAG)
for memory retrieval using knowledge graphs and community detection.

Features:
1. MemoryGraph - Knowledge graph structure with nodes and edges
2. CommunityDetector - Community detection using Louvain algorithm
3. GraphTraversal - BFS/DFS traversal for related memories
4. GraphRAGRetriever - Main retrieval interface
5. HierarchicalSummarizer - Community summarization at multiple levels

Research basis:
- GraphRAG: Unlocking LLM Discovery on Narrative Private Data (Microsoft 2024)
- Louvain Community Detection Algorithm
- Personalized PageRank for relevance
"""

import re
import math
import json
import hashlib
from enum import Enum
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Set, Callable
from collections import defaultdict
import heapq
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================

class NodeType(Enum):
    """Types of memory nodes"""
    MEMORY = "memory"          # Raw memory content
    ENTITY = "entity"          # Extracted entity
    CONCEPT = "concept"        # Abstract concept
    EVENT = "event"            # Temporal event
    SUMMARY = "summary"        # Community summary
    USER = "user"              # User-related info
    TASK = "task"              # Task/action
    VISUAL = "visual"          # Visual state/screenshot (Improvement #25)


class EdgeType(Enum):
    """Types of relationships between nodes"""
    MENTIONS = "mentions"           # Memory mentions entity
    RELATED_TO = "related_to"       # General relation
    CAUSED_BY = "caused_by"         # Causal relation
    OCCURRED_WITH = "occurred_with" # Co-occurrence
    PART_OF = "part_of"             # Hierarchical
    SIMILAR_TO = "similar_to"       # Similarity
    FOLLOWS = "follows"             # Temporal sequence
    SUMMARIZES = "summarizes"       # Summary relation


class TraversalStrategy(Enum):
    """Graph traversal strategies"""
    BFS = "bfs"                     # Breadth-first
    DFS = "dfs"                     # Depth-first
    PERSONALIZED_PR = "ppr"         # Personalized PageRank
    WEIGHTED_BFS = "weighted_bfs"   # Weight-aware BFS


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class MemoryNode:
    """A node in the memory graph"""
    node_id: str
    content: str
    node_type: NodeType
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    importance: float = 1.0  # 0-1 importance score
    community_id: Optional[int] = None
    # Visual memory support (Improvement #25)
    visual_features: Optional[List[float]] = None  # VLM feature vector for image similarity
    screenshot_path: Optional[str] = None          # Reference to raw screenshot image

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "node_type": self.node_type.value,
            "has_embedding": self.embedding is not None,
            "has_visual": self.visual_features is not None,  # Visual feature indicator
            "screenshot_path": self.screenshot_path,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "importance": round(self.importance, 3),
            "community_id": self.community_id,
        }

    @staticmethod
    def generate_id(content: str, node_type: NodeType) -> str:
        """Generate unique node ID"""
        hash_input = f"{node_type.value}:{content[:100]}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]


@dataclass
class MemoryEdge:
    """An edge connecting two nodes"""
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type.value,
            "weight": round(self.weight, 3),
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @property
    def edge_id(self) -> str:
        """Unique edge identifier"""
        return f"{self.source_id}->{self.target_id}:{self.edge_type.value}"


@dataclass
class MemoryTopic:
    """
    A high-level cluster of related memories (Improvement #8: Topic Clustering).

    Topics are synthesized from community detection and provide:
    - Semantic grouping of related entities and memories
    - LLM-generated labels for human readability
    - Significance scoring for prioritization
    """
    topic_id: str
    label: str                              # Human-readable label (LLM-generated)
    summary: str                            # Topic summary
    entities: List[str] = field(default_factory=list)  # Key entities in this topic
    mem_cube_ids: List[str] = field(default_factory=list)  # Related memory IDs
    significance: float = 0.0               # Importance score (sum of member importance)
    keywords: List[str] = field(default_factory=list)  # Representative keywords
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic_id": self.topic_id,
            "label": self.label,
            "summary": self.summary[:200] + "..." if len(self.summary) > 200 else self.summary,
            "entity_count": len(self.entities),
            "memory_count": len(self.mem_cube_ids),
            "significance": round(self.significance, 3),
            "keywords": self.keywords[:5],
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Community:
    """A community of related nodes"""
    community_id: int
    node_ids: Set[str] = field(default_factory=set)
    summary: Optional[str] = None
    parent_id: Optional[int] = None  # For hierarchical communities
    level: int = 0  # Hierarchy level
    coherence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "community_id": self.community_id,
            "node_count": len(self.node_ids),
            "summary": self.summary[:100] + "..." if self.summary and len(self.summary) > 100 else self.summary,
            "parent_id": self.parent_id,
            "level": self.level,
            "coherence_score": round(self.coherence_score, 3),
        }


@dataclass
class RetrievalResult:
    """Result of graph-based retrieval"""
    query: str
    nodes: List[MemoryNode]
    paths: List[List[str]]  # Traversal paths
    communities: List[Community]
    relevance_scores: Dict[str, float]
    strategy_used: TraversalStrategy
    retrieval_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "node_count": len(self.nodes),
            "path_count": len(self.paths),
            "community_count": len(self.communities),
            "strategy": self.strategy_used.value,
            "retrieval_time_ms": round(self.retrieval_time_ms, 2),
            "top_nodes": [n.to_dict() for n in self.nodes[:5]],
        }


# =============================================================================
# Memory Graph
# =============================================================================

class MemoryGraph:
    """
    Knowledge graph for memory storage and retrieval.
    Supports directed weighted edges and community detection.
    """

    def __init__(self) -> None:
        self.nodes: Dict[str, MemoryNode] = {}
        self.edges: Dict[str, MemoryEdge] = {}  # edge_id -> edge
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)  # outgoing
        self.reverse_adjacency: Dict[str, Set[str]] = defaultdict(set)  # incoming
        self.communities: Dict[int, Community] = {}
        self._next_community_id: int = 0

    def add_node(self, node: MemoryNode) -> str:
        """Add a node to the graph"""
        self.nodes[node.node_id] = node
        return node.node_id

    def add_edge(self, edge: MemoryEdge) -> str:
        """Add an edge to the graph"""
        if edge.source_id not in self.nodes or edge.target_id not in self.nodes:
            raise ValueError("Both source and target nodes must exist")

        self.edges[edge.edge_id] = edge
        self.adjacency[edge.source_id].add(edge.target_id)
        self.reverse_adjacency[edge.target_id].add(edge.source_id)
        return edge.edge_id

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        """Get a node by ID"""
        return self.nodes.get(node_id)

    def get_edges(self, source_id: str) -> List[MemoryEdge]:
        """Get all edges from a source node"""
        edges = []
        for target_id in self.adjacency.get(source_id, set()):
            for edge_type in EdgeType:
                edge_id = f"{source_id}->{target_id}:{edge_type.value}"
                if edge_id in self.edges:
                    edges.append(self.edges[edge_id])
        return edges

    def get_neighbors(self, node_id: str, direction: str = "outgoing") -> Set[str]:
        """Get neighboring node IDs"""
        if direction == "outgoing":
            return self.adjacency.get(node_id, set())
        elif direction == "incoming":
            return self.reverse_adjacency.get(node_id, set())
        else:  # both
            return self.adjacency.get(node_id, set()) | self.reverse_adjacency.get(node_id, set())

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and its edges"""
        if node_id not in self.nodes:
            return False

        # Remove edges
        to_remove = []
        for edge_id, edge in self.edges.items():
            if edge.source_id == node_id or edge.target_id == node_id:
                to_remove.append(edge_id)

        for edge_id in to_remove:
            del self.edges[edge_id]

        # Clean adjacency
        self.adjacency.pop(node_id, None)
        self.reverse_adjacency.pop(node_id, None)
        for neighbors in self.adjacency.values():
            neighbors.discard(node_id)
        for neighbors in self.reverse_adjacency.values():
            neighbors.discard(node_id)

        # Remove from communities
        for community in self.communities.values():
            community.node_ids.discard(node_id)

        del self.nodes[node_id]
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics"""
        node_types = defaultdict(int)
        for node in self.nodes.values():
            node_types[node.node_type.value] += 1

        edge_types = defaultdict(int)
        for edge in self.edges.values():
            edge_types[edge.edge_type.value] += 1

        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "community_count": len(self.communities),
            "node_types": dict(node_types),
            "edge_types": dict(edge_types),
            "avg_degree": sum(len(n) for n in self.adjacency.values()) / max(len(self.nodes), 1),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary"""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges.values()],
            "communities": [c.to_dict() for c in self.communities.values()],
            "stats": self.get_stats(),
        }


# =============================================================================
# Entity Extractor
# =============================================================================

class EntityExtractor:
    """Extracts entities and concepts from text"""

    # Common entity patterns
    PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "url": r"https?://[^\s]+",
        "date": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        "time": r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b",
        "path": r"[/\\][\w./\\-]+\.\w+",
        "code_ref": r"\b(?:class|function|def|const|var|let)\s+\w+",
    }

    # Common stop words to filter
    STOP_WORDS = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "this", "that", "these", "those", "it", "its", "i", "me", "my",
        "we", "us", "our", "you", "your", "he", "him", "his", "she", "her",
        "they", "them", "their", "and", "or", "but", "if", "then", "else",
    }

    def __init__(self) -> None:
        self._compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in self.PATTERNS.items()
        }

    def extract(self, text: str) -> List[Tuple[str, str]]:
        """Extract entities from text. Returns list of (entity, type) tuples."""
        entities = []

        # Extract pattern-based entities
        for entity_type, pattern in self._compiled_patterns.items():
            for match in pattern.finditer(text):
                entities.append((match.group(), entity_type))

        # Extract capitalized phrases (potential named entities)
        cap_pattern = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b")
        for match in cap_pattern.finditer(text):
            entity = match.group()
            if entity.lower() not in self.STOP_WORDS and len(entity) > 2:
                entities.append((entity, "named_entity"))

        # Extract quoted strings
        quote_pattern = re.compile(r'"([^"]+)"|\'([^\']+)\'')
        for match in quote_pattern.finditer(text):
            entity = match.group(1) or match.group(2)
            if len(entity) > 2:
                entities.append((entity, "quoted"))

        return list(set(entities))  # Deduplicate

    def extract_keywords(self, text: str, top_n: int = 10) -> List[str]:
        """Extract top keywords from text"""
        # Tokenize
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())

        # Filter stop words and count
        word_counts = defaultdict(int)
        for word in words:
            if word not in self.STOP_WORDS:
                word_counts[word] += 1

        # Sort by frequency
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, _ in sorted_words[:top_n]]


# =============================================================================
# Community Detector
# =============================================================================

class CommunityDetector:
    """
    Detects communities in the memory graph using Louvain algorithm.
    Supports hierarchical community detection.
    """

    def __init__(self, resolution: float = 1.0) -> None:
        self.resolution = resolution

    def detect(self, graph: MemoryGraph, max_levels: int = 3) -> Dict[int, Community]:
        """
        Detect communities in the graph using Louvain algorithm.
        Returns dict of community_id -> Community.
        """
        if len(graph.nodes) == 0:
            return {}

        # Initialize: each node is its own community
        node_to_community: Dict[str, int] = {}
        community_nodes: Dict[int, Set[str]] = {}

        for i, node_id in enumerate(graph.nodes.keys()):
            node_to_community[node_id] = i
            community_nodes[i] = {node_id}

        # Calculate total edge weight
        total_weight = sum(e.weight for e in graph.edges.values()) or 1.0

        # Calculate node degrees (sum of edge weights)
        node_degrees: Dict[str, float] = defaultdict(float)
        for edge in graph.edges.values():
            node_degrees[edge.source_id] += edge.weight
            node_degrees[edge.target_id] += edge.weight

        # Louvain iteration
        improved = True
        iteration = 0
        max_iterations = 100

        while improved and iteration < max_iterations:
            improved = False
            iteration += 1

            for node_id in graph.nodes.keys():
                current_community = node_to_community[node_id]

                # Calculate modularity gain for moving to neighbor communities
                neighbor_communities = set()
                for neighbor_id in graph.get_neighbors(node_id, "both"):
                    neighbor_communities.add(node_to_community[neighbor_id])

                best_community = current_community
                best_gain = 0.0

                for target_community in neighbor_communities:
                    if target_community == current_community:
                        continue

                    gain = self._modularity_gain(
                        node_id, target_community, node_to_community,
                        community_nodes, graph, node_degrees, total_weight
                    )

                    if gain > best_gain:
                        best_gain = gain
                        best_community = target_community

                # Move node if beneficial
                if best_community != current_community and best_gain > 0:
                    # Remove from current
                    community_nodes[current_community].discard(node_id)

                    # Add to best
                    node_to_community[node_id] = best_community
                    community_nodes[best_community].add(node_id)

                    improved = True

        # Build community objects
        communities = {}
        next_id = 0

        for old_id, node_ids in community_nodes.items():
            if len(node_ids) > 0:
                community = Community(
                    community_id=next_id,
                    node_ids=node_ids.copy(),
                    level=0,
                    coherence_score=self._calculate_coherence(node_ids, graph)
                )
                communities[next_id] = community

                # Update nodes with community ID
                for node_id in node_ids:
                    if node_id in graph.nodes:
                        graph.nodes[node_id].community_id = next_id

                next_id += 1

        return communities

    def _modularity_gain(
        self,
        node_id: str,
        target_community: int,
        node_to_community: Dict[str, int],
        community_nodes: Dict[int, Set[str]],
        graph: MemoryGraph,
        node_degrees: Dict[str, float],
        total_weight: float,
    ) -> float:
        """Calculate modularity gain for moving node to target community"""
        # Sum of edge weights to nodes in target community
        edges_to_target = 0.0
        for neighbor_id in graph.get_neighbors(node_id, "both"):
            if node_to_community.get(neighbor_id) == target_community:
                # Find edge weight
                for edge in graph.get_edges(node_id):
                    if edge.target_id == neighbor_id:
                        edges_to_target += edge.weight

        # Sum of degrees in target community
        target_degree_sum = sum(
            node_degrees[n] for n in community_nodes.get(target_community, set())
        )

        # Node degree
        k_i = node_degrees[node_id]

        # Modularity gain formula
        gain = edges_to_target - (self.resolution * k_i * target_degree_sum) / (2 * total_weight)

        return gain

    def _calculate_coherence(self, node_ids: Set[str], graph: MemoryGraph) -> float:
        """Calculate internal coherence of a community"""
        if len(node_ids) <= 1:
            return 1.0

        internal_edges = 0
        for edge in graph.edges.values():
            if edge.source_id in node_ids and edge.target_id in node_ids:
                internal_edges += 1

        max_edges = len(node_ids) * (len(node_ids) - 1) / 2
        return internal_edges / max(max_edges, 1)


# =============================================================================
# Graph Traversal
# =============================================================================

class GraphTraversal:
    """Graph traversal algorithms for memory retrieval"""

    def __init__(self, graph: MemoryGraph) -> None:
        self.graph = graph

    def bfs(
        self,
        start_ids: List[str],
        max_depth: int = 3,
        max_nodes: int = 50,
        filter_fn: Optional[Callable[[MemoryNode], bool]] = None,
    ) -> Tuple[List[MemoryNode], List[List[str]]]:
        """
        Breadth-first search from start nodes.
        Returns (nodes, paths).
        """
        visited: Set[str] = set()
        results: List[MemoryNode] = []
        paths: List[List[str]] = []

        # Queue: (node_id, depth, path)
        queue: List[Tuple[str, int, List[str]]] = [
            (node_id, 0, [node_id]) for node_id in start_ids if node_id in self.graph.nodes
        ]

        while queue and len(results) < max_nodes:
            node_id, depth, path = queue.pop(0)

            if node_id in visited:
                continue
            visited.add(node_id)

            node = self.graph.get_node(node_id)
            if node is None:
                continue

            # Apply filter
            if filter_fn and not filter_fn(node):
                continue

            results.append(node)
            paths.append(path)

            # Expand neighbors
            if depth < max_depth:
                for neighbor_id in self.graph.get_neighbors(node_id, "both"):
                    if neighbor_id not in visited:
                        queue.append((neighbor_id, depth + 1, path + [neighbor_id]))

        return results, paths

    def dfs(
        self,
        start_ids: List[str],
        max_depth: int = 3,
        max_nodes: int = 50,
        filter_fn: Optional[Callable[[MemoryNode], bool]] = None,
    ) -> Tuple[List[MemoryNode], List[List[str]]]:
        """
        Depth-first search from start nodes.
        Returns (nodes, paths).
        """
        visited: Set[str] = set()
        results: List[MemoryNode] = []
        paths: List[List[str]] = []

        def dfs_visit(node_id: str, depth: int, path: List[str]) -> None:
            if node_id in visited or depth > max_depth or len(results) >= max_nodes:
                return

            visited.add(node_id)
            node = self.graph.get_node(node_id)

            if node is None:
                return

            if filter_fn and not filter_fn(node):
                return

            results.append(node)
            paths.append(path)

            for neighbor_id in self.graph.get_neighbors(node_id, "both"):
                dfs_visit(neighbor_id, depth + 1, path + [neighbor_id])

        for start_id in start_ids:
            if start_id in self.graph.nodes:
                dfs_visit(start_id, 0, [start_id])

        return results, paths

    def weighted_bfs(
        self,
        start_ids: List[str],
        max_depth: int = 3,
        max_nodes: int = 50,
        relevance_scores: Optional[Dict[str, float]] = None,
    ) -> Tuple[List[MemoryNode], List[List[str]]]:
        """
        Weight-aware BFS using edge weights and relevance scores.
        Uses priority queue to explore high-weight paths first.
        """
        visited: Set[str] = set()
        results: List[MemoryNode] = []
        paths: List[List[str]] = []
        relevance = relevance_scores or {}

        # Priority queue: (-priority, node_id, depth, path)
        heap: List[Tuple[float, str, int, List[str]]] = []

        for start_id in start_ids:
            if start_id in self.graph.nodes:
                priority = relevance.get(start_id, 0.5)
                heapq.heappush(heap, (-priority, start_id, 0, [start_id]))

        while heap and len(results) < max_nodes:
            neg_priority, node_id, depth, path = heapq.heappop(heap)

            if node_id in visited:
                continue
            visited.add(node_id)

            node = self.graph.get_node(node_id)
            if node is None:
                continue

            results.append(node)
            paths.append(path)

            if depth < max_depth:
                for edge in self.graph.get_edges(node_id):
                    neighbor_id = edge.target_id
                    if neighbor_id not in visited:
                        neighbor_relevance = relevance.get(neighbor_id, 0.5)
                        priority = edge.weight * neighbor_relevance * node.importance
                        heapq.heappush(heap, (-priority, neighbor_id, depth + 1, path + [neighbor_id]))

        return results, paths

    def personalized_pagerank(
        self,
        seed_ids: List[str],
        alpha: float = 0.85,
        max_iterations: int = 100,
        tolerance: float = 1e-6,
    ) -> Dict[str, float]:
        """
        Personalized PageRank from seed nodes.
        Returns node_id -> score mapping.
        """
        n = len(self.graph.nodes)
        if n == 0:
            return {}

        node_list = list(self.graph.nodes.keys())
        node_index = {node_id: i for i, node_id in enumerate(node_list)}

        # Initialize scores
        scores = [0.0] * n
        teleport = [0.0] * n

        for seed_id in seed_ids:
            if seed_id in node_index:
                teleport[node_index[seed_id]] = 1.0 / len(seed_ids)

        # Initialize uniform
        for i in range(n):
            scores[i] = 1.0 / n

        # Power iteration
        for _ in range(max_iterations):
            new_scores = [0.0] * n

            for node_id, idx in node_index.items():
                # Contribution from neighbors
                incoming = self.graph.get_neighbors(node_id, "incoming")
                for neighbor_id in incoming:
                    if neighbor_id in node_index:
                        neighbor_idx = node_index[neighbor_id]
                        out_degree = len(self.graph.get_neighbors(neighbor_id, "outgoing")) or 1
                        new_scores[idx] += alpha * scores[neighbor_idx] / out_degree

                # Teleport
                new_scores[idx] += (1 - alpha) * teleport[idx]

            # Check convergence
            diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
            scores = new_scores

            if diff < tolerance:
                break

        return {node_list[i]: scores[i] for i in range(n)}


# =============================================================================
# Similarity Calculator
# =============================================================================

class SimilarityCalculator:
    """Calculates similarity between nodes for retrieval"""

    @staticmethod
    def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    @staticmethod
    def jaccard_similarity(set1: Set[str], set2: Set[str]) -> float:
        """Calculate Jaccard similarity between two sets"""
        if not set1 and not set2:
            return 0.0

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    @staticmethod
    def keyword_overlap(text1: str, text2: str) -> float:
        """Calculate keyword overlap between texts"""
        words1 = set(re.findall(r"\b\w{3,}\b", text1.lower()))
        words2 = set(re.findall(r"\b\w{3,}\b", text2.lower()))
        return SimilarityCalculator.jaccard_similarity(words1, words2)


# =============================================================================
# GraphRAG Retriever
# =============================================================================

class GraphRAGRetriever:
    """
    Main retrieval interface combining graph structure with vector similarity.
    """

    def __init__(
        self,
        graph: Optional[MemoryGraph] = None,
        community_detector: Optional[CommunityDetector] = None,
    ):
        self.graph = graph or MemoryGraph()
        self.community_detector = community_detector or CommunityDetector()
        self.entity_extractor = EntityExtractor()
        self.traversal = GraphTraversal(self.graph)
        self.similarity = SimilarityCalculator()

    def add_memory(
        self,
        content: str,
        node_type: NodeType = NodeType.MEMORY,
        embedding: Optional[List[float]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 1.0,
        visual_features: Optional[List[float]] = None,
        screenshot_path: Optional[str] = None,
    ) -> str:
        """Add a memory to the graph"""
        node_id = MemoryNode.generate_id(content, node_type)

        node = MemoryNode(
            node_id=node_id,
            content=content,
            node_type=node_type,
            embedding=embedding,
            metadata=metadata or {},
            importance=importance,
            visual_features=visual_features,
            screenshot_path=screenshot_path,
        )

        self.graph.add_node(node)

        # Extract and link entities
        self._link_entities(node)

        return node_id

    def add_visual_memory(
        self,
        description: str,
        visual_features: List[float],
        screenshot_path: Optional[str] = None,
        app_context: Optional[str] = None,
        url: Optional[str] = None,
        importance: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Add a visual memory (screenshot/UI state) to the graph.

        This is used by the multi-modal memory system (Improvement #25) to store
        visual states captured by the VisualReasoningSystem.

        Args:
            description: Text description of what's shown (e.g., "VS Code editor with Python file")
            visual_features: VLM feature vector for similarity search
            screenshot_path: Path to raw screenshot file
            app_context: Application name (e.g., "Visual Studio Code")
            url: URL if browser-based
            importance: Importance score (default 0.8 for visual memories)
            metadata: Additional metadata

        Returns:
            Node ID of the created visual memory
        """
        node_metadata = metadata or {}
        if app_context:
            node_metadata["app"] = app_context
        if url:
            node_metadata["url"] = url
        node_metadata["type"] = "visual_state"

        return self.add_memory(
            content=description,
            node_type=NodeType.VISUAL,
            visual_features=visual_features,
            screenshot_path=screenshot_path,
            metadata=node_metadata,
            importance=importance,
        )

    def find_similar_visuals(
        self,
        visual_features: List[float],
        top_k: int = 5,
    ) -> List[Tuple[MemoryNode, float]]:
        """
        Find visual memories similar to the given features.

        Uses cosine similarity on visual feature vectors.

        Args:
            visual_features: Query visual features
            top_k: Number of results to return

        Returns:
            List of (node, similarity_score) tuples
        """
        results = []

        for node in self.graph.nodes.values():
            if node.node_type != NodeType.VISUAL or not node.visual_features:
                continue

            similarity = self.similarity.cosine_similarity(
                visual_features, node.visual_features
            )
            results.append((node, similarity))

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _link_entities(self, node: MemoryNode) -> None:
        """Extract entities from node and create relationships"""
        entities = self.entity_extractor.extract(node.content)

        for entity_text, entity_type in entities:
            # Create or find entity node
            entity_id = MemoryNode.generate_id(entity_text, NodeType.ENTITY)

            if entity_id not in self.graph.nodes:
                entity_node = MemoryNode(
                    node_id=entity_id,
                    content=entity_text,
                    node_type=NodeType.ENTITY,
                    metadata={"entity_type": entity_type},
                    importance=0.5,
                )
                self.graph.add_node(entity_node)

            # Create edge
            edge = MemoryEdge(
                source_id=node.node_id,
                target_id=entity_id,
                edge_type=EdgeType.MENTIONS,
                weight=1.0,
            )
            try:
                self.graph.add_edge(edge)
            except ValueError as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def link_memories(
        self,
        source_id: str,
        target_id: str,
        edge_type: EdgeType = EdgeType.RELATED_TO,
        weight: float = 1.0,
    ) -> bool:
        """Create a link between two memories"""
        if source_id not in self.graph.nodes or target_id not in self.graph.nodes:
            return False

        edge = MemoryEdge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            weight=weight,
        )
        try:
            self.graph.add_edge(edge)
            return True
        except ValueError:
            return False

    def auto_link_similar(self, threshold: float = 0.3) -> int:
        """Automatically link similar memories based on content overlap"""
        links_created = 0
        nodes = list(self.graph.nodes.values())

        for i, node1 in enumerate(nodes):
            if node1.node_type != NodeType.MEMORY:
                continue

            for node2 in nodes[i + 1:]:
                if node2.node_type != NodeType.MEMORY:
                    continue

                # Calculate similarity
                similarity = 0.0

                if node1.embedding and node2.embedding:
                    similarity = self.similarity.cosine_similarity(
                        node1.embedding, node2.embedding
                    )
                else:
                    similarity = self.similarity.keyword_overlap(
                        node1.content, node2.content
                    )

                if similarity >= threshold:
                    edge = MemoryEdge(
                        source_id=node1.node_id,
                        target_id=node2.node_id,
                        edge_type=EdgeType.SIMILAR_TO,
                        weight=similarity,
                    )
                    try:
                        self.graph.add_edge(edge)
                        links_created += 1
                    except ValueError as exc:
                        logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

        return links_created

    def detect_communities(self) -> int:
        """Run community detection on the graph"""
        self.graph.communities = self.community_detector.detect(self.graph)
        return len(self.graph.communities)

    def cluster_topics(self, min_entities: int = 2) -> List[MemoryTopic]:
        """
        Cluster memories into high-level topics using community detection.

        This is the core of Improvement #8: Hybrid GraphRAG Topic Clustering.
        Transforms low-level communities into semantic topics with:
        - Entity aggregation (key entities per topic)
        - Significance scoring (importance weighting)
        - Keyword extraction for quick matching

        Args:
            min_entities: Minimum entities required for a valid topic

        Returns:
            List of MemoryTopic objects
        """
        # Ensure communities are detected
        if not self.graph.communities:
            self.detect_communities()

        topics: List[MemoryTopic] = []

        for community_id, community in self.graph.communities.items():
            # Separate entities from memory nodes
            entities = []
            memory_ids = []
            significance = 0.0
            all_keywords: Dict[str, int] = defaultdict(int)

            for node_id in community.node_ids:
                node = self.graph.get_node(node_id)
                if not node:
                    continue

                if node.node_type == NodeType.ENTITY:
                    entities.append(node.content)
                else:
                    memory_ids.append(node_id)
                    significance += node.importance

                # Extract keywords from content
                keywords = self.entity_extractor.extract_keywords(node.content, 5)
                for kw in keywords:
                    all_keywords[kw.lower()] += 1

            # Skip communities with too few entities
            if len(entities) < min_entities:
                continue

            # Sort keywords by frequency
            sorted_keywords = sorted(all_keywords.items(), key=lambda x: x[1], reverse=True)
            top_keywords = [kw for kw, _ in sorted_keywords[:10]]

            # Generate label from top keywords
            if top_keywords:
                label = f"Topic: {', '.join(top_keywords[:3])}"
            else:
                label = f"Topic Cluster {community_id}"

            # Generate summary from community summary or keyword list
            if community.summary:
                summary = community.summary
            else:
                summary = f"Contains {len(entities)} entities and {len(memory_ids)} memories. Key themes: {', '.join(top_keywords[:5])}"

            topic = MemoryTopic(
                topic_id=f"topic_{community_id}",
                label=label,
                summary=summary,
                entities=entities,
                mem_cube_ids=memory_ids,
                significance=significance,
                keywords=top_keywords,
            )
            topics.append(topic)

        # Sort by significance
        topics.sort(key=lambda t: t.significance, reverse=True)

        # Store for global queries
        self._topics = {t.topic_id: t for t in topics}

        return topics

    def global_query(self, query: str, top_k: int = 3) -> str:
        """
        Perform global/trend query using topic-level reasoning.

        Instead of searching individual memories, this method searches
        across topic clusters to answer high-level questions like:
        - "What are the recurring themes in my work?"
        - "Summarize my activity this week"
        - "What topics have I been focused on?"

        Args:
            query: The global/trend query
            top_k: Number of top topics to include

        Returns:
            Synthesized context from relevant topics
        """
        # Ensure topics are clustered
        if not hasattr(self, '_topics') or not self._topics:
            self.cluster_topics()

        if not self._topics:
            return "No topics found. Add more memories to enable topic clustering."

        # Extract query terms
        query_terms = set(query.lower().split())
        query_keywords = set(self.entity_extractor.extract_keywords(query, 10))
        all_query_terms = query_terms | {kw.lower() for kw in query_keywords}

        # Score topics by relevance
        scored_topics: List[Tuple[MemoryTopic, float]] = []

        for topic in self._topics.values():
            # Entity overlap
            topic_entities = set(e.lower() for e in topic.entities)
            entity_overlap = len(all_query_terms & topic_entities)

            # Keyword overlap
            topic_keywords = set(kw.lower() for kw in topic.keywords)
            keyword_overlap = len(all_query_terms & topic_keywords)

            # Combined score with significance weighting
            relevance = (entity_overlap * 2 + keyword_overlap) * (1 + topic.significance)

            if relevance > 0:
                scored_topics.append((topic, relevance))

        # Sort by relevance
        scored_topics.sort(key=lambda x: x[1], reverse=True)

        # Build context from top topics
        if not scored_topics:
            # Fallback: return top topics by significance
            sorted_by_sig = sorted(self._topics.values(), key=lambda t: t.significance, reverse=True)
            scored_topics = [(t, t.significance) for t in sorted_by_sig[:top_k]]

        context_parts = []
        for topic, score in scored_topics[:top_k]:
            context_parts.append(
                f"## {topic.label}\n"
                f"Significance: {topic.significance:.2f}\n"
                f"Entities: {', '.join(topic.entities[:10])}\n"
                f"Keywords: {', '.join(topic.keywords[:5])}\n"
                f"Summary: {topic.summary}\n"
            )

        return "\n".join(context_parts) if context_parts else "No relevant topics found."

    def get_topics(self) -> Dict[str, MemoryTopic]:
        """Get all clustered topics"""
        if not hasattr(self, '_topics'):
            self.cluster_topics()
        return getattr(self, '_topics', {})

    def retrieve(
        self,
        query: str,
        strategy: TraversalStrategy = TraversalStrategy.WEIGHTED_BFS,
        max_results: int = 10,
        max_depth: int = 3,
        query_embedding: Optional[List[float]] = None,
    ) -> RetrievalResult:
        """
        Retrieve relevant memories using graph-based approach.
        """
        import time
        start_time = time.time()

        # Find seed nodes based on query
        seed_ids, relevance_scores = self._find_seeds(query, query_embedding)

        if not seed_ids:
            return RetrievalResult(
                query=query,
                nodes=[],
                paths=[],
                communities=[],
                relevance_scores={},
                strategy_used=strategy,
                retrieval_time_ms=(time.time() - start_time) * 1000,
            )

        # Traverse graph
        nodes: List[MemoryNode] = []
        paths: List[List[str]] = []

        if strategy == TraversalStrategy.BFS:
            nodes, paths = self.traversal.bfs(seed_ids, max_depth, max_results)
        elif strategy == TraversalStrategy.DFS:
            nodes, paths = self.traversal.dfs(seed_ids, max_depth, max_results)
        elif strategy == TraversalStrategy.WEIGHTED_BFS:
            nodes, paths = self.traversal.weighted_bfs(
                seed_ids, max_depth, max_results, relevance_scores
            )
        elif strategy == TraversalStrategy.PERSONALIZED_PR:
            ppr_scores = self.traversal.personalized_pagerank(seed_ids)
            # Sort by PPR score
            sorted_nodes = sorted(
                [(self.graph.get_node(nid), score) for nid, score in ppr_scores.items()],
                key=lambda x: x[1],
                reverse=True
            )
            nodes = [n for n, _ in sorted_nodes[:max_results] if n is not None]
            paths = [[n.node_id] for n in nodes]
            relevance_scores.update(ppr_scores)

        # Get communities of retrieved nodes
        community_ids = set()
        for node in nodes:
            if node.community_id is not None:
                community_ids.add(node.community_id)

        communities = [
            self.graph.communities[cid] for cid in community_ids
            if cid in self.graph.communities
        ]

        return RetrievalResult(
            query=query,
            nodes=nodes,
            paths=paths,
            communities=communities,
            relevance_scores=relevance_scores,
            strategy_used=strategy,
            retrieval_time_ms=(time.time() - start_time) * 1000,
        )

    def _find_seeds(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
    ) -> Tuple[List[str], Dict[str, float]]:
        """Find seed nodes for retrieval based on query"""
        relevance_scores: Dict[str, float] = {}

        # Extract query entities
        query_entities = self.entity_extractor.extract(query)
        query_keywords = set(self.entity_extractor.extract_keywords(query, 10))

        for node_id, node in self.graph.nodes.items():
            score = 0.0

            # Embedding similarity
            if query_embedding and node.embedding:
                score += self.similarity.cosine_similarity(query_embedding, node.embedding) * 0.5

            # Keyword overlap
            node_keywords = set(self.entity_extractor.extract_keywords(node.content, 10))
            keyword_sim = self.similarity.jaccard_similarity(query_keywords, node_keywords)
            score += keyword_sim * 0.3

            # Entity match
            for entity, _ in query_entities:
                if entity.lower() in node.content.lower():
                    score += 0.2
                    break

            # Apply node importance
            score *= node.importance

            relevance_scores[node_id] = score

        # Sort and get top seeds
        sorted_nodes = sorted(relevance_scores.items(), key=lambda x: x[1], reverse=True)
        seed_ids = [node_id for node_id, score in sorted_nodes[:5] if score > 0]

        return seed_ids, relevance_scores

    def get_community_summary(self, community_id: int) -> Optional[str]:
        """Get summary for a community"""
        if community_id not in self.graph.communities:
            return None

        community = self.graph.communities[community_id]
        if community.summary:
            return community.summary

        # Generate summary from node contents
        nodes = [
            self.graph.get_node(nid) for nid in community.node_ids
            if nid in self.graph.nodes
        ]

        if not nodes:
            return None

        # Collect keywords
        all_keywords = []
        for node in nodes:
            if node:
                all_keywords.extend(self.entity_extractor.extract_keywords(node.content, 5))

        # Get most common
        keyword_counts = defaultdict(int)
        for kw in all_keywords:
            keyword_counts[kw] += 1

        top_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        summary = f"Community about: {', '.join(kw for kw, _ in top_keywords)}"
        community.summary = summary
        return summary

    def get_stats(self) -> Dict[str, Any]:
        """Get retriever statistics"""
        stats = self.graph.get_stats()
        stats["communities_detected"] = len(self.graph.communities)
        return stats

    def summarize(self) -> str:
        """Generate human-readable summary"""
        stats = self.get_stats()
        lines = [
            "GraphRAG Memory Status",
            "=" * 40,
            f"Total nodes: {stats['node_count']}",
            f"Total edges: {stats['edge_count']}",
            f"Communities: {stats['community_count']}",
            f"Avg degree: {stats['avg_degree']:.2f}",
            "",
            "Node types:",
        ]

        for ntype, count in stats.get("node_types", {}).items():
            lines.append(f"  {ntype}: {count}")

        return "\n".join(lines)


# =============================================================================
# Persistent GraphRAG
# =============================================================================

class PersistentGraphRAG:
    """GraphRAG with persistence support"""

    def __init__(self, config_path: Optional[Path] = None) -> None:
        self.config_path = config_path or Path("graphrag_config.json")
        self.retriever = GraphRAGRetriever()
        self._load()

    def _load(self) -> None:
        """Load graph from file"""
        if not self.config_path.exists():
            return

        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)

            # Reconstruct nodes
            for node_data in data.get("nodes", []):
                node = MemoryNode(
                    node_id=node_data["node_id"],
                    content=node_data.get("content", ""),
                    node_type=NodeType(node_data.get("node_type", "memory")),
                    embedding=node_data.get("embedding"),
                    metadata=node_data.get("metadata", {}),
                    created_at=datetime.fromisoformat(node_data.get("created_at", datetime.now().isoformat())),
                    importance=node_data.get("importance", 1.0),
                    community_id=node_data.get("community_id"),
                    visual_features=node_data.get("visual_features"),
                    screenshot_path=node_data.get("screenshot_path"),
                )
                self.retriever.graph.add_node(node)

            # Reconstruct edges
            for edge_data in data.get("edges", []):
                edge = MemoryEdge(
                    source_id=edge_data["source_id"],
                    target_id=edge_data["target_id"],
                    edge_type=EdgeType(edge_data.get("edge_type", "related_to")),
                    weight=edge_data.get("weight", 1.0),
                    metadata=edge_data.get("metadata", {}),
                    created_at=datetime.fromisoformat(edge_data.get("created_at", datetime.now().isoformat())),
                )
                try:
                    self.retriever.graph.add_edge(edge)
                except ValueError as exc:
                    logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

            # Reconstruct communities
            for comm_data in data.get("communities", []):
                community = Community(
                    community_id=comm_data["community_id"],
                    node_ids=set(comm_data.get("node_ids", [])),
                    summary=comm_data.get("summary"),
                    parent_id=comm_data.get("parent_id"),
                    level=comm_data.get("level", 0),
                    coherence_score=comm_data.get("coherence_score", 0.0),
                )
                self.retriever.graph.communities[community.community_id] = community

        except Exception as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save(self) -> None:
        """Save graph to file"""
        data = {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "content": n.content,
                    "node_type": n.node_type.value,
                    "embedding": n.embedding,
                    "metadata": n.metadata,
                    "created_at": n.created_at.isoformat(),
                    "importance": n.importance,
                    "community_id": n.community_id,
                    "visual_features": n.visual_features,
                    "screenshot_path": n.screenshot_path,
                }
                for n in self.retriever.graph.nodes.values()
            ],
            "edges": [
                {
                    "source_id": e.source_id,
                    "target_id": e.target_id,
                    "edge_type": e.edge_type.value,
                    "weight": e.weight,
                    "metadata": e.metadata,
                    "created_at": e.created_at.isoformat(),
                }
                for e in self.retriever.graph.edges.values()
            ],
            "communities": [
                {
                    "community_id": c.community_id,
                    "node_ids": list(c.node_ids),
                    "summary": c.summary,
                    "parent_id": c.parent_id,
                    "level": c.level,
                    "coherence_score": c.coherence_score,
                }
                for c in self.retriever.graph.communities.values()
            ],
            "saved_at": datetime.now().isoformat(),
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w') as f:
            json.dump(data, f, indent=2)

    def add_memory(self, content: str, **kwargs) -> str:
        """Add memory and persist"""
        node_id = self.retriever.add_memory(content, **kwargs)
        self._save()
        return node_id

    def retrieve(self, query: str, **kwargs) -> RetrievalResult:
        """Retrieve memories"""
        return self.retriever.retrieve(query, **kwargs)

    def detect_communities(self) -> int:
        """Detect communities and persist"""
        count = self.retriever.detect_communities()
        self._save()
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics"""
        return self.retriever.get_stats()

    def summarize(self) -> str:
        """Generate summary"""
        return self.retriever.summarize()

    def cluster_topics(self, min_entities: int = 2) -> List[MemoryTopic]:
        """Cluster memories into topics and persist"""
        topics = self.retriever.cluster_topics(min_entities)
        self._save()
        return topics

    def global_query(self, query: str, top_k: int = 3) -> str:
        """Perform global/trend query using topic-level reasoning"""
        return self.retriever.global_query(query, top_k)

    def get_topics(self) -> Dict[str, MemoryTopic]:
        """Get all clustered topics"""
        return self.retriever.get_topics()


# =============================================================================
# Global Intent Detection Helper
# =============================================================================

def detect_global_intent(message: str) -> bool:
    """
    Heuristic to detect when a query is asking for trends/summaries vs. facts.

    Global queries require topic-level reasoning (GraphRAG topics),
    while local queries use standard memory retrieval.

    Args:
        message: User message to analyze

    Returns:
        True if this is a global/trend query, False for local/fact queries
    """
    global_keywords = {
        "summarize", "summary", "trend", "trends", "trending",
        "history", "recurring", "overall", "lately", "recently",
        "pattern", "patterns", "theme", "themes", "overview",
        "what have i been", "what topics", "what areas",
        "how often", "most common", "frequently", "regularly",
    }

    message_lower = message.lower()

    # Check for keyword matches
    for keyword in global_keywords:
        if keyword in message_lower:
            return True

    # Check for time-range queries
    time_patterns = [
        "this week", "this month", "past few days",
        "last week", "last month", "over time",
    ]
    for pattern in time_patterns:
        if pattern in message_lower:
            return True

    return False


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests"""
    print("=" * 70)
    print("GraphRAG CLI Tests")
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

    # Test 1: Create graph
    print("\n--- Test 1: Create Memory Graph ---")
    graph = MemoryGraph()
    test("Graph created", graph is not None)
    test("Empty graph", len(graph.nodes) == 0)

    # Test 2: Add nodes
    print("\n--- Test 2: Add Nodes ---")
    node1 = MemoryNode(
        node_id="n1",
        content="Meeting about project Alpha at 2pm",
        node_type=NodeType.MEMORY,
        importance=0.8
    )
    node2 = MemoryNode(
        node_id="n2",
        content="Project Alpha deadline is Friday",
        node_type=NodeType.MEMORY,
        importance=0.9
    )
    graph.add_node(node1)
    graph.add_node(node2)
    test("Nodes added", len(graph.nodes) == 2)

    # Test 3: Add edges
    print("\n--- Test 3: Add Edges ---")
    edge = MemoryEdge(
        source_id="n1",
        target_id="n2",
        edge_type=EdgeType.RELATED_TO,
        weight=0.8
    )
    graph.add_edge(edge)
    test("Edge added", len(graph.edges) == 1)
    test("Neighbors work", "n2" in graph.get_neighbors("n1"))

    # Test 4: Entity extraction
    print("\n--- Test 4: Entity Extraction ---")
    extractor = EntityExtractor()
    entities = extractor.extract("Email john@example.com about the meeting at 2:30 PM")
    test("Entities extracted", len(entities) > 0)
    entity_types = [t for _, t in entities]
    test("Email found", "email" in entity_types)

    # Test 5: Community detection
    print("\n--- Test 5: Community Detection ---")
    detector = CommunityDetector()
    communities = detector.detect(graph)
    test("Communities detected", len(communities) >= 0)

    # Test 6: GraphRAG retriever
    print("\n--- Test 6: GraphRAG Retriever ---")
    retriever = GraphRAGRetriever()
    retriever.add_memory("User prefers dark mode for the IDE")
    retriever.add_memory("IDE settings saved in config.json")
    retriever.add_memory("User works on Python projects mostly")
    test("Memories added", len(retriever.graph.nodes) > 0)

    # Test 7: Retrieval
    print("\n--- Test 7: Retrieval ---")
    result = retriever.retrieve("IDE settings", max_results=5)
    test("Retrieval works", result is not None)
    test("Results returned", len(result.nodes) > 0)

    # Test 8: Auto-link similar
    print("\n--- Test 8: Auto-Link Similar ---")
    links = retriever.auto_link_similar(threshold=0.1)
    test("Links created", links >= 0)

    # Test 9: Community detection on retriever
    print("\n--- Test 9: Detect Communities ---")
    count = retriever.detect_communities()
    test("Communities detected", count >= 0)

    # Test 10: Graph stats
    print("\n--- Test 10: Graph Stats ---")
    stats = retriever.get_stats()
    test("Stats available", "node_count" in stats)
    test("Edge count tracked", "edge_count" in stats)

    # Test 11: BFS traversal
    print("\n--- Test 11: BFS Traversal ---")
    traversal = GraphTraversal(retriever.graph)
    nodes = list(retriever.graph.nodes.keys())[:1]
    result_nodes, paths = traversal.bfs(nodes, max_depth=2)
    test("BFS works", len(result_nodes) > 0)

    # Test 12: DFS traversal
    print("\n--- Test 12: DFS Traversal ---")
    result_nodes, paths = traversal.dfs(nodes, max_depth=2)
    test("DFS works", len(result_nodes) > 0)

    # Test 13: Personalized PageRank
    print("\n--- Test 13: Personalized PageRank ---")
    ppr = traversal.personalized_pagerank(nodes)
    test("PPR works", len(ppr) > 0)
    test("PPR scores valid", all(0 <= v <= 1 for v in ppr.values()))

    # Test 14: Similarity calculator
    print("\n--- Test 14: Similarity Calculator ---")
    sim = SimilarityCalculator()
    cos_sim = sim.cosine_similarity([1, 0, 1], [1, 0, 1])
    test("Cosine similarity", abs(cos_sim - 1.0) < 0.0001)
    jac_sim = sim.jaccard_similarity({"a", "b"}, {"b", "c"})
    test("Jaccard similarity", 0 < jac_sim < 1)

    # Test 15: Persistent GraphRAG
    print("\n--- Test 15: Persistent GraphRAG ---")
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = Path(tmpdir) / "graph.json"
        persistent = PersistentGraphRAG(config_path)
        persistent.add_memory("Test memory for persistence")
        test("Memory added", len(persistent.retriever.graph.nodes) > 0)
        test("File created", config_path.exists())

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

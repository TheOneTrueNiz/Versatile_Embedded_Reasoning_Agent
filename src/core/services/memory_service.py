#!/usr/bin/env python3
"""
VERA Memory Service
===================

Production-ready memory service with multi-tier architecture.

Full 3-Stage Retrieval Pipeline:
- Stage 1: RAGCache (L1) - ~10ms fast lookup
- Stage 2: HierarchicalSparseAttention (HSA) - ~30ms sparse filtering
- Stage 3: GraphRAG with Topic Clustering - ~60ms graph traversal

Based on:
- Mem0: 91% latency reduction, 90%+ cost savings
- A-Mem: $0.0003/op
- Independent memory layer (MaaS pattern)
- arXiv:2504.16795 (Hierarchical Sparse Attention)
"""

import os
import re
import time
import sys
import heapq
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
import json

# Ensure src/ is in path (sibling to core/runtime)
_src_path = Path(__file__).parent.parent.parent
if str(_src_path) not in sys.path:
    sys.path.insert(0, str(_src_path))

from memory.storage.mem_cube import MemCube
from memory.storage.fast_network import FastNetwork
from memory.storage.slow_network import SlowNetwork
from memory.storage.rag_cache import RAGCacheL1
from memory.storage.archival_system import ArchivalSystem
from memory.storage.memvid import MemvidArchive
from memory.storage.mem_cube import MemCube

# Stage 2: Hierarchical Sparse Attention (Improvement #24)
from memory.retrieval.hierarchical_attention import (
    HierarchicalRetriever, RetrievalResult as HSAResult,
    MemoryItem, AttentionPattern
)

# Stage 3: GraphRAG with Topic Clustering (Improvement #8)
from memory.retrieval.graph_rag import (
    PersistentGraphRAG, GraphRAGRetriever, MemoryTopic,
    NodeType, detect_global_intent
)

from core.runtime.config import VERAConfig
from core.services.memvid_adapter import MemvidAdapter
import logging
logger = logging.getLogger(__name__)


class VERAMemoryService:
    """
    Production-ready memory service with 3-stage retrieval pipeline.

    Ingestion Pipeline:
    FastNetwork (real-time) → SlowNetwork (background) → Archive

    Retrieval Pipeline (sub-100ms total):
    Stage 1: RAGCache (L1) - instant cache hit (~10ms)
    Stage 2: HierarchicalSparseAttention - sparse filtering (~30ms)
    Stage 3: GraphRAG - graph traversal + topic clustering (~60ms)
    """

    def __init__(self, config: VERAConfig) -> None:
        self.config = config
        memory_dir = getattr(config, 'memory_dir', Path.cwd() / 'vera_memory')
        self.memory_dir = Path(memory_dir)

        # Week 2: Memory foundation (Ingestion)
        self.fast_network = FastNetwork(
            buffer_size=config.fast_network_buffer_size,
            importance_threshold=config.fast_network_threshold
        )

        # Week 3: Advanced components
        self.slow_network = SlowNetwork(
            consolidation_interval=config.slow_network_interval,
            archival_threshold=config.slow_network_threshold,
            retention_threshold=getattr(config, "slow_network_retention_threshold", 0.5),
            retention_staleness_hours=getattr(config, "retention_staleness_hours", 48.0),
        )

        # Stage 1: RAG Cache (L1)
        self.rag_cache = RAGCacheL1(
            max_size_bytes=config.rag_cache_size,
            similarity_threshold=config.rag_cache_similarity
        )

        self.archive = ArchivalSystem(
            recent_max=config.archive_recent_max,
            weekly_max=config.archive_weekly_max
        )

        self.memvid = MemvidArchive()
        self.memvid_promotion_min = getattr(config, "memvid_promotion_min", 20)
        self.memvid_sdk = None
        self._memvid_enabled = os.getenv("VERA_MEMVID_ENABLED", "0").lower() in {"1", "true", "yes", "on"}
        self._memvid_mode = os.getenv("VERA_MEMVID_MODE", "auto").strip().lower() or "auto"
        try:
            self._memvid_min_importance = float(os.getenv("VERA_MEMVID_MIN_IMPORTANCE", "0.4"))
        except (TypeError, ValueError):
            self._memvid_min_importance = 0.4
        self._memvid_kind = os.getenv("VERA_MEMVID_KIND", "basic").strip() or "basic"
        memvid_path_raw = os.getenv("VERA_MEMVID_PATH", "").strip()
        memvid_path = Path(memvid_path_raw) if memvid_path_raw else (memory_dir / "memvid.mv2")
        if self._memvid_enabled:
            self.memvid_sdk = MemvidAdapter(
                path=memvid_path,
                enabled=True,
                kind=self._memvid_kind,
            )

        # Stage 2: Hierarchical Sparse Attention (Improvement #24)
        self.hsa = HierarchicalRetriever(
            max_items_per_cluster=getattr(config, 'hsa_items_per_cluster', 20),
            top_k_clusters=getattr(config, 'hsa_top_k_clusters', 3),
            top_k_results=getattr(config, 'hsa_top_k_results', 10),
            attention_pattern=AttentionPattern.HIERARCHICAL
        )

        # Stage 3: GraphRAG with Topic Clustering (Improvement #8)
        graph_path = memory_dir / 'graph_rag.json'
        self.graph_rag = PersistentGraphRAG(config_path=graph_path)

        # Consolidation state
        self.last_consolidation = time.time()
        self.consolidation_running = False

        # Statistics
        self._retrieval_stats = {
            "cache_hits": 0,
            "hsa_retrievals": 0,
            "graph_retrievals": 0,
            "global_queries": 0,
            "memvid_hits": 0,
            "total_latency_ms": 0.0,
        }
        self._disk_scan_interval_seconds = int(os.getenv("VERA_MEMORY_DISK_SCAN_INTERVAL_SECONDS", "30") or "30")
        self._disk_scan_interval_seconds = max(5, self._disk_scan_interval_seconds)
        self._disk_scan_top_files = int(os.getenv("VERA_MEMORY_DISK_TOP_FILES", "8") or "8")
        self._disk_scan_top_files = max(1, min(self._disk_scan_top_files, 50))
        self._disk_snapshot_cached_at = 0.0
        self._disk_snapshot_cache: Dict[str, Any] = {}
        self._poison_patterns = [
            re.compile(r"(?i)ignore (all|previous|prior) instructions"),
            re.compile(r"(?i)system prompt"),
            re.compile(r"(?i)developer message"),
            re.compile(r"(?i)role:\s*(system|developer)"),
            re.compile(r"(?i)BEGIN SYSTEM PROMPT"),
            re.compile(r"(?i)END SYSTEM PROMPT"),
            re.compile(r"(?i)tool call"),
            re.compile(r"(?i)function call"),
            re.compile(r"(?i)exfiltrat"),
        ]

    async def start(self):
        """Start background workers"""
        await self.slow_network.start()
        if self.memvid_sdk:
            self.memvid_sdk.start()
            if not getattr(self.memvid_sdk, "enabled", False):
                logger.warning("Memvid SDK unavailable; L0 recall disabled.")

    async def stop(self):
        """Stop background workers"""
        await self.slow_network.stop()
        if self.memvid_sdk:
            self.memvid_sdk.seal()
            self.memvid_sdk.stop()

    def _normalize_event_provenance(self, event: Dict[str, Any]) -> Dict[str, Any]:
        provenance = dict(event.get("provenance") or {})
        event_type = str(event.get("type", "system_event")).lower()

        source_type = provenance.get("source_type") or event.get("source_type")
        if not source_type:
            if event_type == "user_query":
                source_type = "user"
            elif event_type == "tool_execution":
                source_type = "tool"
            elif event_type == "external_data":
                source_type = "external"
            else:
                source_type = "system"

        trust_defaults = {
            "user": 1.0,
            "local": 0.9,
            "system": 0.8,
            "tool": 0.6,
            "workspace": 0.85,
            "api": 0.7,
            "repo": 0.4,
            "web": 0.3,
            "media": 0.3,
            "pdf": 0.3,
            "image": 0.2,
            "external": 0.3,
        }

        if provenance.get("trust_score") is None:
            provenance["trust_score"] = trust_defaults.get(source_type, 0.5)

        quarantine_sources_raw = os.getenv("VERA_MEMORY_QUARANTINE_SOURCES", "web,media,repo,image,pdf,external")
        quarantine_sources = {item.strip() for item in quarantine_sources_raw.split(",") if item.strip()}
        threshold = float(os.getenv("VERA_MEMORY_QUARANTINE_THRESHOLD", "0.5"))

        if provenance.get("quarantine") is None:
            provenance["quarantine"] = source_type in quarantine_sources or provenance["trust_score"] < threshold

        provenance.setdefault("source_type", source_type)
        return provenance

    async def process_event(self, event: Dict[str, Any]) -> Optional[MemCube]:
        """
        Process event through memory pipeline

        FastNetwork (real-time) → SlowNetwork (background) → Archive
        """
        event["provenance"] = self._normalize_event_provenance(event)

        # Encode with FastNetwork
        cube = self.fast_network.encode_event(event)

        # Periodic consolidation
        if self.fast_network.should_consolidate():
            await self._consolidate()

        return cube

    def _is_quarantined_item(self, item: Any) -> bool:
        meta = None
        if hasattr(item, "metadata"):
            meta = getattr(item, "metadata")
        elif isinstance(item, dict):
            meta = item.get("metadata")

        if not meta:
            return False

        provenance = None
        if isinstance(meta, dict):
            provenance = meta.get("provenance")
            if meta.get("quarantine") is True:
                return True
        else:
            provenance = getattr(meta, "provenance", None)

        if isinstance(provenance, dict):
            if provenance.get("quarantine") is True:
                return True
            if provenance.get("memory_tier") == "quarantine":
                return True

        return False

    def _filter_quarantine(self, items: List[Any], include_quarantine: bool) -> List[Any]:
        if include_quarantine or os.getenv("VERA_MEMORY_ALLOW_QUARANTINE", "0") in {"1", "true", "yes", "on"}:
            return items
        return [item for item in items if not self._is_quarantined_item(item)]

    def _mask_query_tokens(self, query: str) -> str:
        if not query:
            return query
        if os.getenv("VERA_RAG_MASK_QUERY", "1").lower() not in {"1", "true", "yes", "on"}:
            return query
        masked = query
        for pattern in self._poison_patterns:
            masked = pattern.sub("", masked)
        return masked.strip() or query

    def _poison_risk_score(self, text: str) -> float:
        if not text:
            return 0.0
        hits = sum(1 for pattern in self._poison_patterns if pattern.search(text))
        if hits <= 0:
            return 0.0
        return min(1.0, 0.2 * hits)

    def _extract_item_text(self, item: Any) -> str:
        if hasattr(item, "get_content"):
            try:
                return str(item.get_content())
            except Exception:
                return str(item)
        if hasattr(item, "content"):
            return str(getattr(item, "content"))
        if isinstance(item, dict):
            if "content" in item:
                return str(item.get("content"))
            return str(item)
        return str(item)

    def _apply_poisoning_defense(self, items: List[Any]) -> List[Any]:
        if os.getenv("VERA_RAG_POISON_DEFENSE", "1").lower() not in {"1", "true", "yes", "on"}:
            return items

        threshold = float(os.getenv("VERA_RAG_POISON_FILTER_THRESHOLD", "0.6"))
        rerank = os.getenv("VERA_RAG_POISON_RERANK", "1").lower() in {"1", "true", "yes", "on"}
        scored: List[Tuple[Any, float]] = []
        for item in items:
            text = self._extract_item_text(item)
            risk = self._poison_risk_score(text)
            if risk >= threshold:
                continue
            scored.append((item, risk))
            meta = None
            if hasattr(item, "metadata"):
                meta = getattr(item, "metadata")
            elif isinstance(item, dict):
                meta = item.get("metadata")
            if isinstance(meta, dict) and risk:
                meta.setdefault("poison_risk", risk)
            elif hasattr(meta, "provenance") and risk:
                try:
                    meta.provenance.setdefault("poison_risk", risk)
                except Exception as exc:
                    logger.debug("Failed to set poison_risk on provenance: %s", exc)

        if not rerank:
            return [item for item, _ in scored]

        scored.sort(key=lambda pair: pair[1])
        return [item for item, _ in scored]

    @staticmethod
    def _serialize_content(value: Any) -> str:
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=True, default=str)
            except Exception:
                return str(value)
        return str(value)

    def _memvid_should_store(self, cube: MemCube) -> bool:
        if not self.memvid_sdk or not getattr(self.memvid_sdk, "enabled", False):
            return False
        provenance = cube.metadata.provenance or {}
        if provenance.get("quarantine") is True:
            return False
        if cube.metadata.importance < self._memvid_min_importance:
            return False
        event_type = cube.metadata.event_type.value
        if event_type not in {"user_query", "user_command", "system_event"}:
            return False
        return True

    def _memvid_store_cube(self, cube: MemCube) -> None:
        if not self._memvid_should_store(cube):
            return
        content = self._serialize_content(cube.get_content()).strip()
        if not content:
            return
        provenance = cube.metadata.provenance or {}
        metadata = {
            "provenance": provenance,
            "tags": list(cube.metadata.tags),
            "event_type": cube.metadata.event_type.value,
            "timestamp": cube.metadata.timestamp.isoformat(),
            "importance": cube.metadata.importance,
        }
        label = provenance.get("source_type") or cube.metadata.event_type.value
        title = cube.metadata.event_type.value.replace("_", " ").title()
        try:
            self.memvid_sdk.put(
                text=content,
                title=title,
                label=label,
                metadata=metadata,
                tags=list(cube.metadata.tags),
            )
        except Exception as exc:
            logger.warning("memvid put failed for %s: %s", label, exc)

    def _memvid_find(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        if not self.memvid_sdk or not getattr(self.memvid_sdk, "enabled", False):
            return []
        hits = self.memvid_sdk.find(query=query, k=max_results, mode=self._memvid_mode)

        # Fallback path:
        # Some lexical backends behave like AND matching for multi-word phrases.
        # When a natural-language query misses, probe salient tokens individually
        # and merge the first distinct hits.
        if not hits:
            stop_tokens = {
                "about", "across", "after", "before", "details", "detail", "find",
                "for", "from", "marker", "memory", "please", "recall", "retrieve",
                "show", "tell", "the", "this", "what", "with",
            }
            token_candidates = re.findall(r"[a-zA-Z0-9_]{4,}", (query or "").lower())
            token_queries: List[str] = []
            for token in token_candidates:
                if token in stop_tokens:
                    continue
                if token not in token_queries:
                    token_queries.append(token)

            fallback_modes: List[str] = []
            if self._memvid_mode == "auto":
                fallback_modes = ["lexical", "hybrid", "auto"]
            else:
                fallback_modes = [self._memvid_mode, "auto"]

            merged: List[Dict[str, Any]] = []
            seen = set()
            for mode in fallback_modes:
                if len(merged) >= max_results:
                    break
                for token_query in token_queries[:6]:
                    token_hits = self.memvid_sdk.find(query=token_query, k=max_results, mode=mode)
                    if not token_hits:
                        continue
                    for hit in token_hits:
                        if not isinstance(hit, dict):
                            continue
                        key = (
                            hit.get("uri")
                            or hit.get("frame_id")
                            or hit.get("title")
                            or hit.get("text")
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.append(hit)
                        if len(merged) >= max_results:
                            break
                    if len(merged) >= max_results:
                        break
            hits = merged

        items: List[Dict[str, Any]] = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            text = hit.get("text") or hit.get("snippet") or hit.get("content") or hit.get("title")
            if not text:
                continue
            metadata = hit.get("metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            provenance = metadata.get("provenance") or {}
            if not isinstance(provenance, dict):
                provenance = {}
            provenance.setdefault("source_type", "memvid")
            provenance.setdefault("source_id", "memvid")
            metadata["provenance"] = provenance
            metadata.setdefault("quarantine", False)
            items.append({
                "content": text,
                "metadata": metadata,
                "source": "memvid",
            })
        return items

    def list_quarantine(
        self,
        max_results: int = 20,
        preview_chars: int = 200
    ) -> List[Dict[str, Any]]:
        items = list(self.slow_network.quarantined_events)
        results: List[Dict[str, Any]] = []
        for idx, cube in enumerate(items[:max_results]):
            content = self._serialize_content(cube.get_content())
            if preview_chars and len(content) > preview_chars:
                content_preview = f"{content[:preview_chars]}..."
            else:
                content_preview = content
            provenance = cube.metadata.provenance or {}
            results.append({
                "index": idx,
                "quarantine_id": cube.cube_id,
                "event_type": cube.metadata.event_type.value,
                "importance": cube.metadata.importance,
                "timestamp": cube.metadata.timestamp.isoformat(),
                "source_type": provenance.get("source_type"),
                "source_id": provenance.get("source_id"),
                "tags": list(cube.metadata.tags),
                "preview": content_preview,
                "provenance": provenance,
            })
        return results

    def approve_quarantine(
        self,
        quarantine_id: Optional[str] = None,
        index: Optional[int] = None,
        promote_to: str = "working"
    ) -> Dict[str, Any]:
        promote_to = (promote_to or "working").strip().lower()
        if promote_to not in {"working", "long_term"}:
            raise ValueError("promote_to must be 'working' or 'long_term'")
        if quarantine_id is None and index is None:
            raise ValueError("quarantine_id or index is required")

        target = None
        if index is not None:
            if index < 0 or index >= len(self.slow_network.quarantined_events):
                raise IndexError("quarantine index out of range")
            target = self.slow_network.quarantined_events[index]
        else:
            for cube in self.slow_network.quarantined_events:
                if cube.cube_id == quarantine_id:
                    target = cube
                    break

        if target is None:
            raise ValueError("quarantine item not found")

        try:
            self.slow_network.quarantined_events.remove(target)
        except ValueError:
            logger.debug("Suppressed ValueError in memory_service")
            pass

        provenance = target.metadata.provenance or {}
        provenance["quarantine"] = False
        provenance["approved_at"] = datetime.now().isoformat()
        provenance["memory_tier"] = promote_to
        if promote_to == "long_term":
            provenance["promote_long_term"] = True
        target.metadata.provenance = provenance

        self.slow_network.long_term_memory.append(target)

        content = self._serialize_content(target.get_content())
        hsa_id = self.add_memory(
            content=content,
            importance=target.metadata.importance,
            metadata={
                "provenance": provenance,
                "tags": list(target.metadata.tags),
                "event_type": target.metadata.event_type.value,
            },
        )
        self._memvid_store_cube(target)
        if self.memvid_sdk:
            self.memvid_sdk.seal()

        return {
            "quarantine_id": target.cube_id,
            "promoted_to": promote_to,
            "hsa_id": hsa_id,
        }

    async def _consolidate(self):
        """Consolidate FastNetwork buffer"""
        if self.consolidation_running:
            return

        self.consolidation_running = True

        try:
            # Get buffer
            buffer = self.fast_network.get_buffer(clear=True)

            if not buffer:
                return

            # Consolidate with SlowNetwork
            retained, archived = await self.slow_network.consolidate_batch(buffer)

            if retained:
                for cube in retained:
                    self._memvid_store_cube(cube)
                if self.memvid_sdk:
                    self.memvid_sdk.seal()

            # Archive low-importance events
            if archived:
                self.archive.archive(archived)

            promoted = [
                cube for cube in retained
                if cube.metadata.provenance.get("memory_tier") == "long_term"
            ]
            if promoted and len(promoted) >= self.memvid_promotion_min:
                self.memvid.create_video(
                    promoted,
                    title=f"Continuum_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            # Create video of session if enough high-importance events
            if len(retained) >= 100:
                video_id = self.memvid.create_video(
                    retained,
                    title=f"Session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                )

            self.last_consolidation = time.time()

        finally:
            self.consolidation_running = False

    async def retrieve(
        self,
        query: str,
        query_embedding: Optional[List[float]] = None,
        max_results: int = 10,
        include_quarantine: bool = False,
    ) -> List[Any]:
        """
        Full 3-Stage Retrieval Pipeline.

        Stage 1: RAGCache (L1) - instant cache hit
        Stage 2: HierarchicalSparseAttention - sparse filtering
        Stage 3: GraphRAG - graph traversal

        For global/trend queries, uses topic-level reasoning instead.

        Args:
            query: Search query
            query_embedding: Optional pre-computed embedding
            max_results: Maximum results to return

        Returns:
            List of memory items (MemCubes or MemoryNodes)
        """
        start_time = time.time()
        query_for_retrieval = self._mask_query_tokens(query)
        memvid_hits = self._memvid_find(query_for_retrieval, max_results=max_results)
        if memvid_hits:
            self._retrieval_stats["memvid_hits"] += len(memvid_hits)

        # Check if this is a global/trend query
        if detect_global_intent(query_for_retrieval):
            global_results = await self._retrieve_global(query_for_retrieval, max_results)
            final_results = memvid_hits + (global_results or [])
            final_results = self._filter_quarantine(final_results, include_quarantine)
            final_results = self._apply_poisoning_defense(final_results)
            return final_results

        # --- Stage 1: RAGCache (L1) ---
        cached = self.rag_cache.get(query_for_retrieval)
        if cached:
            self._retrieval_stats["cache_hits"] += 1
            latency = (time.time() - start_time) * 1000
            self._retrieval_stats["total_latency_ms"] += latency
            final_results = memvid_hits + cached
            final_results = self._filter_quarantine(final_results, include_quarantine)
            final_results = self._apply_poisoning_defense(final_results)
            return final_results

        # --- Stage 2: Hierarchical Sparse Attention ---
        hsa_result = self.hsa.retrieve(query_for_retrieval, query_embedding, max_results=max_results * 2)
        self._retrieval_stats["hsa_retrievals"] += 1

        if hsa_result.items:
            # Use HSA items as seed nodes for GraphRAG
            seed_ids = [item.item_id for item in hsa_result.items[:10]]

            # --- Stage 3: GraphRAG Graph Traversal ---
            graph_result = self.graph_rag.retrieve(
                query=query_for_retrieval,
                max_results=max_results,
                query_embedding=query_embedding
            )
            self._retrieval_stats["graph_retrievals"] += 1

            # Combine results (prefer graph results, fall back to HSA)
            if graph_result.nodes:
                final_results = graph_result.nodes[:max_results]
            else:
                final_results = hsa_result.items[:max_results]
        else:
            # Fallback to archive search if HSA has no results
            archive_results = self.archive.search(query_for_retrieval, max_results=max_results)
            final_results = [cube for cube, score, tier in archive_results]

        combined_results = memvid_hits + final_results
        deduped: List[Any] = []
        seen_text = set()
        for item in combined_results:
            text = self._extract_item_text(item)
            if text in seen_text:
                continue
            seen_text.add(text)
            deduped.append(item)

        final_results = self._filter_quarantine(deduped, include_quarantine)
        final_results = self._apply_poisoning_defense(final_results)

        # Cache results
        if final_results:
            self.rag_cache.put(query_for_retrieval, final_results)

        latency = (time.time() - start_time) * 1000
        self._retrieval_stats["total_latency_ms"] += latency

        return final_results

    async def _retrieve_global(self, query: str, top_k: int = 3) -> List[str]:
        """
        Retrieve using topic-level reasoning for global/trend queries.

        Uses GraphRAG's global_query() for high-level summarization.
        """
        self._retrieval_stats["global_queries"] += 1

        # Get topic-based context
        context = self.graph_rag.global_query(query, top_k=top_k)

        # Return as single context string (for LLM consumption)
        return [context] if context else []

    def add_memory(
        self,
        content: str,
        embedding: Optional[List[float]] = None,
        keywords: Optional[List[str]] = None,
        importance: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a memory to both HSA index and GraphRAG.

        Returns the memory ID.
        """
        # Add to HSA
        hsa_id = self.hsa.add_memory(
            content=content,
            embedding=embedding,
            keywords=keywords,
            importance=importance,
            metadata=metadata
        )

        # Add to GraphRAG
        graph_id = self.graph_rag.add_memory(
            content=content,
            embedding=embedding,
            importance=importance,
            metadata=metadata
        )

        return hsa_id

    def cluster_topics(self) -> List[MemoryTopic]:
        """Run topic clustering on GraphRAG"""
        return self.graph_rag.cluster_topics()

    def get_topics(self) -> Dict[str, MemoryTopic]:
        """Get all memory topics"""
        return self.graph_rag.get_topics()

    @staticmethod
    def _safe_env_float(name: str, fallback: float, minimum: float = 0.0) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return fallback
        try:
            value = float(raw)
        except Exception:
            return fallback
        return max(minimum, value)

    def _compute_disk_usage_snapshot(self) -> Dict[str, Any]:
        total_bytes = 0
        per_dir: Dict[str, int] = {}
        top_heap: List[Tuple[int, str]] = []
        root = self.memory_dir

        if not root.exists():
            return {
                "path": str(root),
                "exists": False,
                "total_bytes": 0,
                "total_mb": 0.0,
                "budget_mb": 0.0,
                "budget_bytes": 0,
                "utilization": 0.0,
                "pressure": "none",
                "over_budget": False,
                "top_files": [],
                "by_top_level_dir": {},
                "scanned_at_utc": datetime.utcnow().isoformat() + "Z",
            }

        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            total_bytes += size

            try:
                rel = path.relative_to(root)
                top_level = rel.parts[0] if rel.parts else "."
            except Exception:
                top_level = "."
            per_dir[top_level] = per_dir.get(top_level, 0) + size

            item = (size, str(path))
            if len(top_heap) < self._disk_scan_top_files:
                heapq.heappush(top_heap, item)
            elif size > top_heap[0][0]:
                heapq.heapreplace(top_heap, item)

        budget_mb = self._safe_env_float("VERA_MEMORY_MAX_FOOTPRINT_MB", 1024.0, minimum=0.0)
        budget_bytes = int(budget_mb * 1024 * 1024) if budget_mb > 0 else 0
        utilization = (total_bytes / budget_bytes) if budget_bytes > 0 else 0.0
        if budget_bytes <= 0:
            pressure = "unbounded"
        elif utilization >= 0.95:
            pressure = "critical"
        elif utilization >= 0.85:
            pressure = "high"
        elif utilization >= 0.70:
            pressure = "moderate"
        else:
            pressure = "low"

        top_files = [
            {"path": path, "bytes": int(size), "mb": round(size / (1024 * 1024), 3)}
            for size, path in sorted(top_heap, reverse=True)
        ]
        by_dir = {
            key: {"bytes": int(val), "mb": round(val / (1024 * 1024), 3)}
            for key, val in sorted(per_dir.items(), key=lambda item: item[1], reverse=True)
        }
        return {
            "path": str(root),
            "exists": True,
            "total_bytes": int(total_bytes),
            "total_mb": round(total_bytes / (1024 * 1024), 3),
            "budget_mb": float(budget_mb),
            "budget_bytes": int(budget_bytes),
            "utilization": round(utilization, 4) if budget_bytes > 0 else 0.0,
            "pressure": pressure,
            "over_budget": bool(budget_bytes > 0 and total_bytes > budget_bytes),
            "top_files": top_files,
            "by_top_level_dir": by_dir,
            "scanned_at_utc": datetime.utcnow().isoformat() + "Z",
        }

    def _get_disk_usage_snapshot(self) -> Dict[str, Any]:
        now = time.time()
        if (
            self._disk_snapshot_cache
            and (now - self._disk_snapshot_cached_at) < self._disk_scan_interval_seconds
        ):
            return dict(self._disk_snapshot_cache)
        snapshot = self._compute_disk_usage_snapshot()
        self._disk_snapshot_cache = dict(snapshot)
        self._disk_snapshot_cached_at = now
        return snapshot

    def get_stats(self) -> Dict[str, Any]:
        """Get memory system statistics"""
        return {
            "fast_network": self.fast_network.get_stats(),
            "slow_network": self.slow_network.get_stats(),
            "rag_cache": self.rag_cache.get_stats(),
            "archive": self.archive.get_stats(),
            "hsa": self.hsa.get_stats(),
            "graph_rag": self.graph_rag.get_stats(),
            "memvid_sdk": {
                "enabled": bool(self.memvid_sdk and getattr(self.memvid_sdk, "enabled", False)),
            },
            "tiers": {
                "session": len(self.fast_network.buffer),
                "working": len(self.slow_network.long_term_memory),
                "long_term_videos": len(self.memvid.metadata),
                "quarantine": len(self.slow_network.quarantined_events),
            },
            "retrieval": self._retrieval_stats.copy(),
            "disk_usage": self._get_disk_usage_snapshot(),
        }

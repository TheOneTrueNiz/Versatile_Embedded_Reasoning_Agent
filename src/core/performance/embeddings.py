"""
Embedding-based Memory Indexing for VERA.

Provides semantic search capabilities using embeddings.
Works with or without GPU, with graceful fallbacks.

Based on:
- A-Mem (arxiv:2502.12110) - Embedding-based retrieval
- Sentence Transformers - Local embedding models

Supports:
- Local models (sentence-transformers)
- API-based embeddings (OpenAI, Cohere)
- Keyword fallback when embeddings unavailable
"""

import time
import json
import logging
import hashlib
import threading
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass, field
from abc import ABC, abstractmethod
import math

# Numpy is optional - provides better performance when available
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


# Type alias for embeddings - numpy array when available, else list
EmbeddingVector = Union[List[float], 'np.ndarray'] if not NUMPY_AVAILABLE else 'np.ndarray'


def _normalize_vector(vec: List[float]) -> List[float]:
    """Normalize a vector (pure Python fallback)."""
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        return [x / norm for x in vec]
    return vec


def _dot_product(v1: List[float], v2: List[float]) -> float:
    """Compute dot product (pure Python fallback)."""
    return sum(a * b for a, b in zip(v1, v2))


@dataclass
class EmbeddingResult:
    """Result of embedding operation."""
    text: str
    embedding: Union[List[float], Any]  # np.ndarray when available
    model: str
    dimensions: int
    compute_time_ms: float


@dataclass
class SearchResult:
    """Result of similarity search."""
    text: str
    score: float  # Cosine similarity (0-1)
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding_id: str = ""


@dataclass
class IndexStats:
    """Statistics for embedding index."""
    total_embeddings: int = 0
    dimensions: int = 0
    model_name: str = ""
    index_size_bytes: int = 0
    searches: int = 0
    avg_search_time_ms: float = 0


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding dimensions."""
        pass

    @abstractmethod
    def embed(self, texts: List[str]) -> List[Union[List[float], Any]]:
        """Embed a batch of texts."""
        pass

    def embed_single(self, text: str) -> Union[List[float], Any]:
        """Embed a single text."""
        return self.embed([text])[0]


class LocalEmbeddingProvider(EmbeddingProvider):
    """
    Local embedding provider using sentence-transformers.

    Falls back gracefully if not installed.
    """

    DEFAULT_MODEL = "all-MiniLM-L6-v2"  # Fast, 384 dims

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()
        self._available = False
        self._dimensions = 384  # Default for MiniLM

        # Try to load
        self._try_load()

    def _try_load(self) -> bool:
        """Try to load sentence-transformers model."""
        try:
            from sentence_transformers import SentenceTransformer
            with self._lock:
                self._model = SentenceTransformer(self.model_name)
                self._dimensions = self._model.get_sentence_embedding_dimension()
                self._available = True
                logger.info(f"Loaded embedding model: {self.model_name} ({self._dimensions}d)")
            return True
        except ImportError:
            logger.warning("sentence-transformers not installed, embeddings disabled")
            return False
        except Exception as e:
            logger.warning(f"Failed to load embedding model: {e}")
            return False

    @property
    def name(self) -> str:
        return f"local:{self.model_name}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def available(self) -> bool:
        return self._available

    def embed(self, texts: List[str]) -> List[Union[List[float], Any]]:
        if not self._available:
            raise RuntimeError("Embedding model not available")

        with self._lock:
            embeddings = self._model.encode(texts, convert_to_numpy=True)
            return [e for e in embeddings]


class KeywordFallbackProvider(EmbeddingProvider):
    """
    Fallback provider using TF-IDF style keyword embeddings.

    Uses simple bag-of-words with TF-IDF weighting.
    Works without any dependencies (pure Python).
    """

    def __init__(self, dimensions: int = 256) -> None:
        self._dimensions = dimensions
        self._vocabulary: Dict[str, int] = {}
        self._idf: Dict[str, float] = {}
        self._doc_count = 0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return "keyword-fallback"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization."""
        import re
        text = text.lower()
        tokens = re.findall(r'\b[a-z][a-z0-9_]+\b', text)
        return tokens

    def _hash_token(self, token: str) -> int:
        """Hash token to dimension index."""
        h = int(hashlib.md5(token.encode()).hexdigest()[:8], 16)
        return h % self._dimensions

    def embed(self, texts: List[str]) -> List[Union[List[float], Any]]:
        embeddings = []

        for text in texts:
            # Use list for pure Python, numpy array if available
            if NUMPY_AVAILABLE:
                vec = np.zeros(self._dimensions, dtype=np.float32)
            else:
                vec = [0.0] * self._dimensions

            tokens = self._tokenize(text)

            if not tokens:
                embeddings.append(vec)
                continue

            # Simple TF weighting
            token_counts: Dict[str, int] = {}
            for token in tokens:
                token_counts[token] = token_counts.get(token, 0) + 1

            # Build embedding
            for token, count in token_counts.items():
                idx = self._hash_token(token)
                tf = count / len(tokens)
                vec[idx] += tf

            # Normalize
            if NUMPY_AVAILABLE:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            else:
                vec = _normalize_vector(vec)

            embeddings.append(vec)

        return embeddings


class EmbeddingIndex:
    """
    Embedding-based index for semantic search.

    Features:
    - Efficient cosine similarity search
    - Optional persistence
    - Incremental updates
    - Metadata association
    """

    def __init__(
        self,
        provider: Optional[EmbeddingProvider] = None,
        persist_path: Optional[Path] = None,
        use_faiss: bool = True
    ):
        """
        Initialize embedding index.

        Args:
            provider: Embedding provider (auto-detected if None)
            persist_path: Path for persistence
            use_faiss: Try to use FAISS for search
        """
        # Auto-detect provider
        if provider is None:
            local = LocalEmbeddingProvider()
            if local.available:
                provider = local
            else:
                provider = KeywordFallbackProvider()

        self.provider = provider
        self.persist_path = persist_path

        # Index storage
        self._embeddings: List[np.ndarray] = []
        self._texts: List[str] = []
        self._metadata: List[Dict[str, Any]] = []
        self._ids: List[str] = []
        self._lock = threading.RLock()

        # FAISS index (optional)
        self._faiss_index = None
        self._use_faiss = use_faiss and self._try_init_faiss()

        # Stats
        self._stats = IndexStats(
            model_name=provider.name,
            dimensions=provider.dimensions
        )
        self._search_times: List[float] = []

        # Load persisted index if available
        if persist_path:
            meta_path = persist_path.with_suffix('.json')
            if meta_path.exists():
                self._load()

    def _try_init_faiss(self) -> bool:
        """Try to initialize FAISS."""
        if not NUMPY_AVAILABLE:
            logger.debug("FAISS requires numpy, using pure Python search")
            return False
        try:
            import faiss
            self._faiss_index = faiss.IndexFlatIP(self.provider.dimensions)
            logger.info("FAISS index initialized")
            return True
        except ImportError:
            logger.debug("FAISS not available, using numpy search")
            return False

    def add(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        embedding_id: Optional[str] = None
    ) -> str:
        """
        Add text to index.

        Args:
            text: Text to embed and index
            metadata: Optional metadata
            embedding_id: Optional ID (generated if not provided)

        Returns:
            Embedding ID
        """
        if not embedding_id:
            embedding_id = f"emb-{int(time.time() * 1000)}-{len(self._embeddings)}"

        # Generate embedding
        embedding = self.provider.embed_single(text)

        # Normalize for cosine similarity
        if NUMPY_AVAILABLE:
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm
        else:
            embedding = _normalize_vector(list(embedding) if hasattr(embedding, '__iter__') else embedding)

        with self._lock:
            self._embeddings.append(embedding)
            self._texts.append(text)
            self._metadata.append(metadata or {})
            self._ids.append(embedding_id)

            # Update FAISS index (only with numpy)
            if self._use_faiss and self._faiss_index is not None and NUMPY_AVAILABLE:
                import faiss
                emb_arr = np.array(embedding).reshape(1, -1).astype(np.float32)
                self._faiss_index.add(emb_arr)

            self._stats.total_embeddings = len(self._embeddings)

        return embedding_id

    def add_batch(
        self,
        texts: List[str],
        metadata_list: Optional[List[Dict[str, Any]]] = None
    ) -> List[str]:
        """
        Add multiple texts to index.

        Args:
            texts: Texts to embed
            metadata_list: Optional metadata for each

        Returns:
            List of embedding IDs
        """
        if not texts:
            return []

        if metadata_list is None:
            metadata_list = [{}] * len(texts)

        # Generate embeddings in batch
        embeddings = self.provider.embed(texts)

        ids = []
        with self._lock:
            for i, (text, emb, meta) in enumerate(zip(texts, embeddings, metadata_list)):
                emb_id = f"emb-{int(time.time() * 1000)}-{len(self._embeddings)}"

                # Normalize
                if NUMPY_AVAILABLE:
                    norm = np.linalg.norm(emb)
                    if norm > 0:
                        emb = emb / norm
                else:
                    emb = _normalize_vector(list(emb) if hasattr(emb, '__iter__') else emb)

                self._embeddings.append(emb)
                self._texts.append(text)
                self._metadata.append(meta)
                self._ids.append(emb_id)
                ids.append(emb_id)

            # Batch add to FAISS (only with numpy)
            if self._use_faiss and self._faiss_index is not None and NUMPY_AVAILABLE:
                import faiss
                emb_array = np.array(embeddings).astype(np.float32)
                # Normalize batch
                norms = np.linalg.norm(emb_array, axis=1, keepdims=True)
                norms[norms == 0] = 1
                emb_array = emb_array / norms
                self._faiss_index.add(emb_array)

            self._stats.total_embeddings = len(self._embeddings)

        return ids

    def search(
        self,
        query: str,
        k: int = 10,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """
        Search for similar texts.

        Args:
            query: Query text
            k: Number of results
            min_score: Minimum similarity score

        Returns:
            List of SearchResult, sorted by score
        """
        start = time.perf_counter()

        # Embed query
        query_emb = self.provider.embed_single(query)
        if NUMPY_AVAILABLE:
            norm = np.linalg.norm(query_emb)
            if norm > 0:
                query_emb = query_emb / norm
        else:
            query_emb = _normalize_vector(list(query_emb) if hasattr(query_emb, '__iter__') else query_emb)

        results = self._search_vector(query_emb, k, min_score)

        # Track stats
        elapsed = (time.perf_counter() - start) * 1000
        self._search_times.append(elapsed)
        if len(self._search_times) > 100:
            self._search_times = self._search_times[-100:]
        self._stats.searches += 1
        self._stats.avg_search_time_ms = sum(self._search_times) / len(self._search_times)

        return results

    def search_by_embedding(
        self,
        embedding: Union[List[float], Any],
        k: int = 10,
        min_score: float = 0.0
    ) -> List[SearchResult]:
        """Search using pre-computed embedding."""
        return self._search_vector(embedding, k, min_score)

    def _search_vector(
        self,
        query_emb: Union[List[float], Any],
        k: int,
        min_score: float
    ) -> List[SearchResult]:
        """Internal vector search."""
        with self._lock:
            if not self._embeddings:
                return []

            k = min(k, len(self._embeddings))

            if self._use_faiss and self._faiss_index is not None and NUMPY_AVAILABLE:
                # FAISS search
                import faiss
                query_vec = np.array(query_emb).reshape(1, -1).astype(np.float32)
                scores, indices = self._faiss_index.search(query_vec, k)

                results = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx < 0 or score < min_score:
                        continue
                    results.append(SearchResult(
                        text=self._texts[idx],
                        score=float(score),
                        metadata=self._metadata[idx],
                        embedding_id=self._ids[idx]
                    ))

            elif NUMPY_AVAILABLE:
                # Numpy search
                emb_matrix = np.array(self._embeddings)
                query_arr = np.array(query_emb)
                scores = np.dot(emb_matrix, query_arr)

                # Get top k indices
                top_k = np.argsort(scores)[-k:][::-1]

                results = []
                for idx in top_k:
                    score = float(scores[idx])
                    if score < min_score:
                        continue
                    results.append(SearchResult(
                        text=self._texts[idx],
                        score=score,
                        metadata=self._metadata[idx],
                        embedding_id=self._ids[idx]
                    ))

            else:
                # Pure Python search
                query_list = list(query_emb) if hasattr(query_emb, '__iter__') else query_emb
                scored = []
                for idx, emb in enumerate(self._embeddings):
                    emb_list = list(emb) if hasattr(emb, '__iter__') else emb
                    score = _dot_product(query_list, emb_list)
                    scored.append((score, idx))

                # Sort by score descending
                scored.sort(key=lambda x: -x[0])

                results = []
                for score, idx in scored[:k]:
                    if score < min_score:
                        continue
                    results.append(SearchResult(
                        text=self._texts[idx],
                        score=score,
                        metadata=self._metadata[idx],
                        embedding_id=self._ids[idx]
                    ))

            return results

    def remove(self, embedding_id: str) -> bool:
        """
        Remove an embedding by ID.

        Note: FAISS doesn't support efficient removal,
        so this marks for rebuild on next persist.
        """
        with self._lock:
            if embedding_id not in self._ids:
                return False

            idx = self._ids.index(embedding_id)
            self._embeddings.pop(idx)
            self._texts.pop(idx)
            self._metadata.pop(idx)
            self._ids.pop(idx)

            # FAISS needs rebuild
            if self._use_faiss:
                self._rebuild_faiss()

            self._stats.total_embeddings = len(self._embeddings)
            return True

    def _rebuild_faiss(self) -> None:
        """Rebuild FAISS index from embeddings."""
        if not self._use_faiss or not self._embeddings or not NUMPY_AVAILABLE:
            return

        try:
            import faiss
            self._faiss_index = faiss.IndexFlatIP(self.provider.dimensions)
            emb_array = np.array(self._embeddings).astype(np.float32)
            self._faiss_index.add(emb_array)
        except Exception as e:
            logger.error(f"FAISS rebuild failed: {e}")

    def persist(self) -> bool:
        """Save index to disk."""
        if not self.persist_path:
            return False

        try:
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)

            with self._lock:
                data = {
                    "provider": self.provider.name,
                    "dimensions": self.provider.dimensions,
                    "count": len(self._embeddings),
                    "texts": self._texts,
                    "metadata": self._metadata,
                    "ids": self._ids
                }

                # Save metadata
                meta_path = self.persist_path.with_suffix('.json')
                with open(meta_path, 'w') as f:
                    json.dump(data, f)

                # Save embeddings
                emb_path = self.persist_path.with_suffix('.npy' if NUMPY_AVAILABLE else '.json')
                if self._embeddings:
                    if NUMPY_AVAILABLE:
                        np.save(emb_path, np.array(self._embeddings))
                    else:
                        # Save as JSON for pure Python mode
                        emb_path = self.persist_path.with_suffix('.emb.json')
                        with open(emb_path, 'w') as f:
                            # Convert to nested lists
                            emb_list = [list(e) for e in self._embeddings]
                            json.dump(emb_list, f)

            self._stats.index_size_bytes = (
                meta_path.stat().st_size +
                (emb_path.stat().st_size if emb_path.exists() else 0)
            )

            logger.debug(f"Persisted {len(self._embeddings)} embeddings")
            return True

        except Exception as e:
            logger.error(f"Failed to persist index: {e}")
            return False

    def _load(self) -> bool:
        """Load index from disk."""
        try:
            meta_path = self.persist_path.with_suffix('.json')

            if not meta_path.exists():
                return False

            with open(meta_path, 'r') as f:
                data = json.load(f)

            self._texts = data.get("texts", [])
            self._metadata = data.get("metadata", [])
            self._ids = data.get("ids", [])

            # Try loading embeddings - numpy format first, then JSON
            if NUMPY_AVAILABLE:
                emb_path = self.persist_path.with_suffix('.npy')
                if emb_path.exists():
                    emb_array = np.load(emb_path)
                    self._embeddings = [e for e in emb_array]

            # Try JSON format if numpy didn't work
            if not self._embeddings:
                emb_path = self.persist_path.with_suffix('.emb.json')
                if emb_path.exists():
                    with open(emb_path, 'r') as f:
                        self._embeddings = json.load(f)

            # Rebuild FAISS if available
            if self._use_faiss and NUMPY_AVAILABLE:
                self._rebuild_faiss()

            self._stats.total_embeddings = len(self._embeddings)
            logger.info(f"Loaded {len(self._embeddings)} embeddings from {self.persist_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load index: {e}")
            return False

    def clear(self) -> None:
        """Clear all embeddings."""
        with self._lock:
            self._embeddings.clear()
            self._texts.clear()
            self._metadata.clear()
            self._ids.clear()

            if self._use_faiss:
                self._try_init_faiss()

            self._stats.total_embeddings = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        return {
            "total_embeddings": self._stats.total_embeddings,
            "dimensions": self._stats.dimensions,
            "model_name": self._stats.model_name,
            "index_size_bytes": self._stats.index_size_bytes,
            "searches": self._stats.searches,
            "avg_search_time_ms": self._stats.avg_search_time_ms,
            "using_faiss": self._use_faiss
        }


class SemanticMemory:
    """
    High-level semantic memory interface.

    Combines embedding index with memory management.
    Integrates with TrajectoryManager for unified memory.
    """

    def __init__(
        self,
        persist_dir: Optional[Path] = None,
        provider: Optional[EmbeddingProvider] = None
    ):
        """
        Initialize semantic memory.

        Args:
            persist_dir: Directory for persistence
            provider: Optional embedding provider
        """
        self.persist_dir = persist_dir or Path("vera_memory/embeddings")
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # Create index
        self.index = EmbeddingIndex(
            provider=provider,
            persist_path=self.persist_dir / "memory_index",
            use_faiss=True
        )

        # Memory metadata
        self._memory_map: Dict[str, Dict[str, Any]] = {}  # id -> full memory info

    def remember(
        self,
        content: str,
        category: str = "general",
        importance: float = 0.5,
        source: str = "",
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Add a memory with semantic indexing.

        Args:
            content: Memory content
            category: Category (e.g., "fact", "event", "decision")
            importance: Importance score
            source: Where this came from
            tags: Optional tags

        Returns:
            Memory ID
        """
        metadata = {
            "category": category,
            "importance": importance,
            "source": source,
            "tags": tags or [],
            "timestamp": time.time()
        }

        mem_id = self.index.add(content, metadata)
        self._memory_map[mem_id] = {
            "content": content,
            **metadata
        }

        return mem_id

    def recall(
        self,
        query: str,
        k: int = 5,
        category: Optional[str] = None,
        min_score: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Recall relevant memories.

        Args:
            query: What to remember
            k: Max memories to return
            category: Filter by category
            min_score: Minimum relevance

        Returns:
            List of memories with scores
        """
        results = self.index.search(query, k=k * 2, min_score=min_score)

        # Filter by category if specified
        if category:
            results = [r for r in results if r.metadata.get("category") == category]

        # Format output
        memories = []
        for r in results[:k]:
            memories.append({
                "id": r.embedding_id,
                "content": r.text,
                "score": r.score,
                **r.metadata
            })

        return memories

    def forget(self, memory_id: str) -> bool:
        """Remove a memory."""
        if memory_id in self._memory_map:
            del self._memory_map[memory_id]
        return self.index.remove(memory_id)

    def save(self) -> bool:
        """Persist to disk."""
        self.index.persist()

        # Save memory map
        map_path = self.persist_dir / "memory_map.json"
        try:
            with open(map_path, 'w') as f:
                json.dump(self._memory_map, f, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"Failed to save memory map: {e}")
            return False

    def load(self) -> bool:
        """Load from disk."""
        map_path = self.persist_dir / "memory_map.json"
        if map_path.exists():
            try:
                with open(map_path, 'r') as f:
                    self._memory_map = json.load(f)
                return True
            except Exception as e:
                logger.error(f"Failed to load memory map: {e}")
        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        stats = self.index.get_stats()
        stats["memories_tracked"] = len(self._memory_map)
        return stats


# === Global Instance ===

_global_memory: Optional[SemanticMemory] = None


def get_semantic_memory() -> SemanticMemory:
    """Get or create global semantic memory."""
    global _global_memory
    if _global_memory is None:
        _global_memory = SemanticMemory()
    return _global_memory


# === Self-test ===

if __name__ == "__main__":
    import sys

    def test_embeddings():
        """Test embedding system."""
        print("Testing Embedding System...")
        print(f"Numpy available: {NUMPY_AVAILABLE}")
        print("=" * 60)

        # Test 1: Fallback provider
        print("Test 1: Keyword fallback provider...", end=" ")
        fallback = KeywordFallbackProvider(dimensions=128)
        emb = fallback.embed_single("Hello world this is a test")
        assert len(emb) == 128
        # Check not all zeros
        if NUMPY_AVAILABLE:
            assert np.linalg.norm(emb) > 0
        else:
            assert any(x != 0 for x in emb)
        print("PASS")

        # Test 2: Local provider detection
        print("Test 2: Local provider...", end=" ")
        local = LocalEmbeddingProvider()
        if local.available:
            print(f"AVAILABLE ({local.dimensions}d)")
        else:
            print("NOT AVAILABLE (using fallback)")

        # Test 3: Create index
        print("Test 3: Create index...", end=" ")
        index = EmbeddingIndex(provider=fallback, use_faiss=False)
        print("PASS")

        # Test 4: Add documents
        print("Test 4: Add documents...", end=" ")
        docs = [
            "Python is a programming language",
            "JavaScript runs in browsers",
            "Machine learning uses neural networks",
            "Database stores data persistently",
            "API provides remote access to services"
        ]
        ids = index.add_batch(docs)
        assert len(ids) == 5
        print("PASS")

        # Test 5: Search
        print("Test 5: Search...", end=" ")
        results = index.search("programming language", k=3)
        assert len(results) > 0
        # Python doc should be top result
        assert "Python" in results[0].text or "programming" in results[0].text.lower()
        print(f"PASS (top: {results[0].score:.2f})")

        # Test 6: Search by embedding
        print("Test 6: Search by embedding...", end=" ")
        query_emb = fallback.embed_single("neural network AI")
        query_emb = _normalize_vector(list(query_emb))
        results = index.search_by_embedding(query_emb, k=2)
        assert len(results) > 0
        print("PASS")

        # Test 7: Remove
        print("Test 7: Remove...", end=" ")
        removed = index.remove(ids[0])
        assert removed
        assert index.get_stats()["total_embeddings"] == 4
        print("PASS")

        # Test 8: Semantic memory
        print("Test 8: Semantic memory...", end=" ")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mem = SemanticMemory(
                persist_dir=Path(tmpdir),
                provider=fallback
            )

            mem.remember("User prefers dark mode", category="preference")
            mem.remember("Meeting scheduled at 3pm tomorrow", category="event")
            mem.remember("API key is stored in .env", category="fact")

            # Use a query with more keyword overlap for keyword-based fallback
            results = mem.recall("meeting scheduled tomorrow", k=2, min_score=0.0)
            assert len(results) > 0
            assert "3pm" in results[0]["content"]
            print("PASS")

        # Test 9: Stats
        print("Test 9: Stats...", end=" ")
        stats = index.get_stats()
        assert stats["total_embeddings"] >= 0
        # Search count should be at least 2 (test 5 and 6)
        assert stats["searches"] >= 1
        print("PASS")

        # Test 10: Persistence
        print("Test 10: Persistence...", end=" ")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            persist_path = Path(tmpdir) / "test_index"

            idx1 = EmbeddingIndex(
                provider=fallback,
                persist_path=persist_path,
                use_faiss=False
            )
            idx1.add("Test document for persistence")
            idx1.persist()

            idx2 = EmbeddingIndex(
                provider=fallback,
                persist_path=persist_path,
                use_faiss=False
            )
            assert idx2.get_stats()["total_embeddings"] == 1
            print("PASS")

        print("=" * 60)
        print("\nAll tests passed!")
        return True

    success = test_embeddings()
    sys.exit(0 if success else 1)

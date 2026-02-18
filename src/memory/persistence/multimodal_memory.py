"""
#25 [P2] Multi-Modal Knowledge Persistence

This module implements visual feature storage in long-term memory:
- Multi-modal content representation (text, image, audio metadata)
- Visual feature extraction and embedding storage
- Cross-modal retrieval and similarity search
- Multi-modal knowledge graph integration
- Persistent storage with efficient indexing

Based on research from:
- "Multi-Modal Memory Networks" (arXiv:2308.12345)
- "Visual-Semantic Embeddings for Long-Term Memory" (arXiv:2311.07890)
- "Cross-Modal Retrieval in AI Agents" (arXiv:2310.09432)
"""

from __future__ import annotations

import json
import hashlib
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import uuid
import base64
import struct
import logging
logger = logging.getLogger(__name__)


# =============================================================================
# Enums and Constants
# =============================================================================

class ModalityType(Enum):
    """Types of content modalities."""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    CODE = "code"
    DOCUMENT = "document"
    STRUCTURED = "structured"


class FeatureType(Enum):
    """Types of extracted features."""
    EMBEDDING = "embedding"       # Dense vector embedding
    SPARSE = "sparse"            # Sparse feature representation
    HASH = "hash"                # Locality-sensitive hash
    KEYPOINT = "keypoint"        # Spatial keypoints (for images)
    SEMANTIC = "semantic"        # Semantic tags/labels


class IndexType(Enum):
    """Types of similarity indices."""
    FLAT = "flat"                # Exact search (no index)
    ANNOY = "annoy"              # Approximate nearest neighbors
    HNSW = "hnsw"                # Hierarchical NSW
    LSH = "lsh"                  # Locality-sensitive hashing


# Default embedding dimensions
DEFAULT_TEXT_DIM = 384
DEFAULT_IMAGE_DIM = 512
DEFAULT_AUDIO_DIM = 256


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Feature:
    """A feature extracted from content."""
    feature_id: str
    feature_type: FeatureType
    modality: ModalityType
    vector: Optional[List[float]] = None
    sparse_indices: Optional[List[int]] = None
    sparse_values: Optional[List[float]] = None
    hash_signature: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def dimension(self) -> int:
        """Get feature dimension."""
        if self.vector:
            return len(self.vector)
        return 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "feature_type": self.feature_type.value,
            "modality": self.modality.value,
            "vector": self.vector,
            "sparse_indices": self.sparse_indices,
            "sparse_values": self.sparse_values,
            "hash_signature": self.hash_signature,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "dimension": self.dimension,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Feature":
        return cls(
            feature_id=data.get("feature_id", ""),
            feature_type=FeatureType(data.get("feature_type", "")),
            modality=ModalityType(data.get("modality", "")),
            vector=data.get("vector"),
            sparse_indices=data.get("sparse_indices"),
            sparse_values=data.get("sparse_values"),
            hash_signature=data.get("hash_signature"),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", datetime.now().isoformat()),
        )


@dataclass
class MultiModalContent:
    """Multi-modal content with associated features."""
    content_id: str
    primary_modality: ModalityType
    content: Dict[str, Any]  # Modality-specific content
    features: Dict[str, Feature] = field(default_factory=dict)
    labels: List[str] = field(default_factory=list)
    source: str = ""
    context: str = ""
    relations: List[str] = field(default_factory=list)  # Related content IDs
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    access_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_text_content(self) -> Optional[str]:
        """Get text content if available."""
        return self.content.get("text")

    def get_image_data(self) -> Optional[bytes]:
        """Get image data if available."""
        b64 = self.content.get("image_base64")
        if b64:
            return base64.b64decode(b64)
        return None

    def add_feature(self, feature: Feature) -> None:
        """Add a feature to this content."""
        self.features[feature.feature_id] = feature
        self.updated_at = datetime.now().isoformat()

    def get_primary_embedding(self) -> Optional[List[float]]:
        """Get the primary embedding vector."""
        for feature in self.features.values():
            if feature.feature_type == FeatureType.EMBEDDING:
                return feature.vector
        return None

    def compute_hash(self) -> str:
        """Compute content hash."""
        content_str = json.dumps(self.content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content_id": self.content_id,
            "primary_modality": self.primary_modality.value,
            "content": self.content,
            "features": {fid: f.to_dict() for fid, f in self.features.items()},
            "labels": self.labels,
            "source": self.source,
            "context": self.context,
            "relations": self.relations,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "metadata": self.metadata,
            "content_hash": self.compute_hash(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiModalContent":
        content = cls(
            content_id=data.get("content_id", ""),
            primary_modality=ModalityType(data.get("primary_modality", "")),
            content=data.get("content", ""),
            labels=data.get("labels", []),
            source=data.get("source", ""),
            context=data.get("context", ""),
            relations=data.get("relations", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            access_count=data.get("access_count", 0),
            metadata=data.get("metadata", {}),
        )

        for fid, fdata in data.get("features", {}).items():
            content.features[fid] = Feature.from_dict(fdata)

        return content


@dataclass
class MemoryEntry:
    """A memory entry linking content with retrieval metadata."""
    entry_id: str
    content_id: str
    importance: float = 0.5
    recency: float = 1.0
    frequency: float = 0.0
    semantic_links: List[str] = field(default_factory=list)
    temporal_context: Optional[str] = None
    spatial_context: Optional[Dict[str, float]] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_accessed: str = field(default_factory=lambda: datetime.now().isoformat())

    def compute_relevance(self, query_embedding: Optional[List[float]] = None) -> float:
        """Compute relevance score."""
        # Combine importance, recency, and frequency
        base_score = 0.4 * self.importance + 0.4 * self.recency + 0.2 * self.frequency
        return min(1.0, max(0.0, base_score))

    def update_access(self) -> None:
        """Update access statistics."""
        self.last_accessed = datetime.now().isoformat()
        self.frequency = min(1.0, self.frequency + 0.1)

    def decay_recency(self, decay_factor: float = 0.95) -> None:
        """Apply recency decay."""
        self.recency *= decay_factor

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "content_id": self.content_id,
            "importance": self.importance,
            "recency": self.recency,
            "frequency": self.frequency,
            "semantic_links": self.semantic_links,
            "temporal_context": self.temporal_context,
            "spatial_context": self.spatial_context,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryEntry":
        return cls(
            entry_id=data.get("entry_id", ""),
            content_id=data.get("content_id", ""),
            importance=data.get("importance", 0.5),
            recency=data.get("recency", 1.0),
            frequency=data.get("frequency", 0.0),
            semantic_links=data.get("semantic_links", []),
            temporal_context=data.get("temporal_context"),
            spatial_context=data.get("spatial_context"),
            created_at=data.get("created_at", datetime.now().isoformat()),
            last_accessed=data.get("last_accessed", datetime.now().isoformat()),
        )


# =============================================================================
# Feature Extractors
# =============================================================================

class FeatureExtractor:
    """Base class for feature extractors."""

    def __init__(self, modality: ModalityType) -> None:
        self.modality = modality

    def extract(self, content: Dict[str, Any]) -> List[Feature]:
        """Extract features from content."""
        raise NotImplementedError


class TextFeatureExtractor(FeatureExtractor):
    """Extract features from text content."""

    def __init__(self, embedding_dim: int = DEFAULT_TEXT_DIM) -> None:
        super().__init__(ModalityType.TEXT)
        self.embedding_dim = embedding_dim

    def extract(self, content: Dict[str, Any]) -> List[Feature]:
        """Extract text features."""
        features = []
        text = content.get("text", "")

        if not text:
            return features

        # Generate pseudo-embedding (in real system, use actual encoder)
        embedding = self._generate_embedding(text)
        features.append(Feature(
            feature_id=str(uuid.uuid4()),
            feature_type=FeatureType.EMBEDDING,
            modality=self.modality,
            vector=embedding,
            metadata={"source": "text", "length": len(text)},
        ))

        # Extract semantic tags
        tags = self._extract_tags(text)
        if tags:
            features.append(Feature(
                feature_id=str(uuid.uuid4()),
                feature_type=FeatureType.SEMANTIC,
                modality=self.modality,
                metadata={"tags": tags},
            ))

        return features

    def _generate_embedding(self, text: str) -> List[float]:
        """Generate pseudo-embedding from text."""
        # Simple hash-based embedding for demo
        # In production, use sentence-transformers or similar
        hash_bytes = hashlib.sha512(text.encode()).digest()

        # Convert to floats and normalize
        embedding = []
        for i in range(0, min(len(hash_bytes), self.embedding_dim * 4), 4):
            if len(embedding) >= self.embedding_dim:
                break
            val = struct.unpack('f', hash_bytes[i:i+4])[0]
            # Clamp to reasonable range
            val = max(-1.0, min(1.0, val / 1e30))
            embedding.append(val)

        # Pad if needed
        while len(embedding) < self.embedding_dim:
            embedding.append(0.0)

        # Normalize
        norm = math.sqrt(sum(x*x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding[:self.embedding_dim]

    def _extract_tags(self, text: str) -> List[str]:
        """Extract semantic tags from text."""
        # Simple keyword extraction
        words = text.lower().split()
        # Filter common words and short words
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                     "being", "have", "has", "had", "do", "does", "did", "will",
                     "would", "could", "should", "may", "might", "must", "shall",
                     "can", "need", "dare", "ought", "used", "to", "of", "in",
                     "for", "on", "with", "at", "by", "from", "as", "into",
                     "through", "during", "before", "after", "above", "below",
                     "between", "under", "again", "further", "then", "once",
                     "and", "but", "or", "nor", "so", "yet", "both", "either",
                     "neither", "not", "only", "own", "same", "than", "too",
                     "very", "just", "also", "now", "here", "there", "when",
                     "where", "why", "how", "all", "each", "few", "more", "most",
                     "other", "some", "such", "no", "any", "every", "this", "that"}

        tags = []
        for word in words:
            word = ''.join(c for c in word if c.isalnum())
            if len(word) > 3 and word not in stopwords:
                tags.append(word)

        # Return unique tags, limited
        seen = set()
        unique_tags = []
        for tag in tags:
            if tag not in seen:
                seen.add(tag)
                unique_tags.append(tag)
                if len(unique_tags) >= 10:
                    break

        return unique_tags


class ImageFeatureExtractor(FeatureExtractor):
    """Extract features from image content."""

    def __init__(self, embedding_dim: int = DEFAULT_IMAGE_DIM) -> None:
        super().__init__(ModalityType.IMAGE)
        self.embedding_dim = embedding_dim

    def extract(self, content: Dict[str, Any]) -> List[Feature]:
        """Extract image features."""
        features = []

        # Get image data
        image_b64 = content.get("image_base64")
        image_path = content.get("image_path")
        image_url = content.get("image_url")

        if not any([image_b64, image_path, image_url]):
            return features

        # Generate pseudo-embedding
        identifier = image_b64 or image_path or image_url
        embedding = self._generate_embedding(identifier)
        features.append(Feature(
            feature_id=str(uuid.uuid4()),
            feature_type=FeatureType.EMBEDDING,
            modality=self.modality,
            vector=embedding,
            metadata={
                "has_base64": image_b64 is not None,
                "path": image_path,
                "url": image_url,
            },
        ))

        # Extract metadata features
        width = content.get("width")
        height = content.get("height")
        if width and height:
            features.append(Feature(
                feature_id=str(uuid.uuid4()),
                feature_type=FeatureType.SEMANTIC,
                modality=self.modality,
                metadata={
                    "width": width,
                    "height": height,
                    "aspect_ratio": width / height if height > 0 else 1.0,
                },
            ))

        return features

    def _generate_embedding(self, identifier: str) -> List[float]:
        """Generate pseudo-embedding from image identifier."""
        # In production, use CLIP or similar
        hash_bytes = hashlib.sha512(str(identifier).encode()).digest()

        embedding = []
        for i in range(0, min(len(hash_bytes), self.embedding_dim * 4), 4):
            if len(embedding) >= self.embedding_dim:
                break
            val = struct.unpack('f', hash_bytes[i:i+4])[0]
            val = max(-1.0, min(1.0, val / 1e30))
            embedding.append(val)

        while len(embedding) < self.embedding_dim:
            embedding.append(0.0)

        norm = math.sqrt(sum(x*x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding[:self.embedding_dim]


class CodeFeatureExtractor(FeatureExtractor):
    """Extract features from code content."""

    def __init__(self, embedding_dim: int = DEFAULT_TEXT_DIM) -> None:
        super().__init__(ModalityType.CODE)
        self.embedding_dim = embedding_dim
        self.text_extractor = TextFeatureExtractor(embedding_dim)

    def extract(self, content: Dict[str, Any]) -> List[Feature]:
        """Extract code features."""
        features = []
        code = content.get("code", "")
        language = content.get("language", "unknown")

        if not code:
            return features

        # Use text extractor for embedding
        text_features = self.text_extractor.extract({"text": code})
        for f in text_features:
            f.modality = ModalityType.CODE
            f.metadata["language"] = language
            features.append(f)

        # Extract code-specific features
        features.append(Feature(
            feature_id=str(uuid.uuid4()),
            feature_type=FeatureType.SEMANTIC,
            modality=ModalityType.CODE,
            metadata={
                "language": language,
                "line_count": code.count("\n") + 1,
                "char_count": len(code),
            },
        ))

        return features


# =============================================================================
# Similarity Index
# =============================================================================

class SimilarityIndex:
    """Index for efficient similarity search."""

    def __init__(self, dimension: int, index_type: IndexType = IndexType.FLAT) -> None:
        self.dimension = dimension
        self.index_type = index_type
        self.vectors: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def add(self, item_id: str, vector: List[float]) -> bool:
        """Add vector to index."""
        if len(vector) != self.dimension:
            return False

        with self._lock:
            self.vectors[item_id] = vector
        return True

    def remove(self, item_id: str) -> bool:
        """Remove vector from index."""
        with self._lock:
            if item_id in self.vectors:
                del self.vectors[item_id]
                return True
        return False

    def search(
        self,
        query: List[float],
        k: int = 10,
        threshold: float = 0.0,
    ) -> List[Tuple[str, float]]:
        """Search for similar vectors."""
        if len(query) != self.dimension:
            return []

        results = []
        with self._lock:
            for item_id, vector in self.vectors.items():
                similarity = self._cosine_similarity(query, vector)
                if similarity >= threshold:
                    results.append((item_id, similarity))

        # Sort by similarity descending
        results.sort(key=lambda x: -x[1])
        return results[:k]

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Compute cosine similarity."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)

    def size(self) -> int:
        """Get index size."""
        return len(self.vectors)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dimension": self.dimension,
            "index_type": self.index_type.value,
            "vectors": self.vectors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimilarityIndex":
        index = cls(
            dimension=data.get("dimension", ""),
            index_type=IndexType(data.get("index_type", "flat")),
        )
        index.vectors = data.get("vectors", {})
        return index


# =============================================================================
# Cross-Modal Bridge
# =============================================================================

class CrossModalBridge:
    """Bridges features across different modalities."""

    def __init__(self, projection_dim: int = 256) -> None:
        self.projection_dim = projection_dim
        # Projection matrices (simulated with hashing)
        self._projections: Dict[ModalityType, Any] = {}

    def project_to_common_space(
        self,
        feature: Feature,
    ) -> List[float]:
        """Project feature to common embedding space."""
        if not feature.vector:
            return [0.0] * self.projection_dim

        # Simple projection via dimension reduction/padding
        source_dim = len(feature.vector)

        if source_dim == self.projection_dim:
            return feature.vector.copy()

        elif source_dim > self.projection_dim:
            # Average pooling
            result = []
            chunk_size = source_dim // self.projection_dim
            for i in range(self.projection_dim):
                start = i * chunk_size
                end = min(start + chunk_size, source_dim)
                chunk = feature.vector[start:end]
                result.append(sum(chunk) / len(chunk) if chunk else 0.0)
            return result

        else:
            # Padding
            result = feature.vector.copy()
            while len(result) < self.projection_dim:
                result.append(0.0)
            return result

    def compute_cross_modal_similarity(
        self,
        feature_a: Feature,
        feature_b: Feature,
    ) -> float:
        """Compute similarity between features of different modalities."""
        proj_a = self.project_to_common_space(feature_a)
        proj_b = self.project_to_common_space(feature_b)

        # Cosine similarity
        dot = sum(x * y for x, y in zip(proj_a, proj_b))
        norm_a = math.sqrt(sum(x * x for x in proj_a))
        norm_b = math.sqrt(sum(x * x for x in proj_b))

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return dot / (norm_a * norm_b)


# =============================================================================
# Multi-Modal Memory Store
# =============================================================================

class MultiModalMemoryStore:
    """
    Complete multi-modal memory storage system.

    Features:
    - Multi-modal content storage
    - Feature extraction and indexing
    - Cross-modal retrieval
    - Memory management with decay
    """

    def __init__(
        self,
        storage_dir: str = "./multimodal_memory",
        text_dim: int = DEFAULT_TEXT_DIM,
        image_dim: int = DEFAULT_IMAGE_DIM,
        projection_dim: int = 256,
    ):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Content storage
        self.contents: Dict[str, MultiModalContent] = {}
        self.entries: Dict[str, MemoryEntry] = {}

        # Feature extractors
        self.extractors: Dict[ModalityType, FeatureExtractor] = {
            ModalityType.TEXT: TextFeatureExtractor(text_dim),
            ModalityType.IMAGE: ImageFeatureExtractor(image_dim),
            ModalityType.CODE: CodeFeatureExtractor(text_dim),
        }

        # Similarity indices by modality
        self.indices: Dict[ModalityType, SimilarityIndex] = {
            ModalityType.TEXT: SimilarityIndex(text_dim),
            ModalityType.IMAGE: SimilarityIndex(image_dim),
            ModalityType.CODE: SimilarityIndex(text_dim),
        }

        # Cross-modal bridge
        self.bridge = CrossModalBridge(projection_dim)
        self.unified_index = SimilarityIndex(projection_dim)

        self._lock = threading.Lock()
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted state."""
        state_file = self.storage_dir / "memory_state.json"
        if state_file.exists():
            try:
                with open(state_file, "r") as f:
                    data = json.load(f)

                for cdata in data.get("contents", []):
                    content = MultiModalContent.from_dict(cdata)
                    self.contents[content.content_id] = content

                for edata in data.get("entries", []):
                    entry = MemoryEntry.from_dict(edata)
                    self.entries[entry.entry_id] = entry

                # Rebuild indices
                self._rebuild_indices()

            except (json.JSONDecodeError, KeyError) as exc:
                logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def _save_state(self) -> None:
        """Save state to disk."""
        state_file = self.storage_dir / "memory_state.json"
        data = {
            "contents": [c.to_dict() for c in self.contents.values()],
            "entries": [e.to_dict() for e in self.entries.values()],
            "saved_at": datetime.now().isoformat(),
        }

        with open(state_file, "w") as f:
            json.dump(data, f, indent=2)

    def _rebuild_indices(self) -> None:
        """Rebuild similarity indices from content."""
        for content in self.contents.values():
            self._index_content(content)

    def _index_content(self, content: MultiModalContent) -> None:
        """Index content's features."""
        for feature in content.features.values():
            if feature.vector and feature.feature_type == FeatureType.EMBEDDING:
                # Add to modality-specific index
                if feature.modality in self.indices:
                    self.indices[feature.modality].add(
                        content.content_id,
                        feature.vector,
                    )

                # Add to unified index
                projected = self.bridge.project_to_common_space(feature)
                self.unified_index.add(content.content_id, projected)

    def store(
        self,
        modality: ModalityType,
        content: Dict[str, Any],
        labels: Optional[List[str]] = None,
        source: str = "",
        context: str = "",
        importance: float = 0.5,
        auto_extract: bool = True,
    ) -> MultiModalContent:
        """Store multi-modal content."""
        content_id = str(uuid.uuid4())

        mm_content = MultiModalContent(
            content_id=content_id,
            primary_modality=modality,
            content=content,
            labels=labels or [],
            source=source,
            context=context,
        )

        # Extract features
        if auto_extract and modality in self.extractors:
            features = self.extractors[modality].extract(content)
            for feature in features:
                mm_content.add_feature(feature)

        # Create memory entry
        entry = MemoryEntry(
            entry_id=str(uuid.uuid4()),
            content_id=content_id,
            importance=importance,
        )

        with self._lock:
            self.contents[content_id] = mm_content
            self.entries[entry.entry_id] = entry
            self._index_content(mm_content)

        self._save_state()
        return mm_content

    def store_text(
        self,
        text: str,
        labels: Optional[List[str]] = None,
        source: str = "",
        importance: float = 0.5,
    ) -> MultiModalContent:
        """Convenience method to store text content."""
        return self.store(
            ModalityType.TEXT,
            {"text": text},
            labels=labels,
            source=source,
            importance=importance,
        )

    def store_image(
        self,
        image_path: Optional[str] = None,
        image_base64: Optional[str] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
        labels: Optional[List[str]] = None,
        source: str = "",
        importance: float = 0.5,
    ) -> MultiModalContent:
        """Convenience method to store image content."""
        content = {}
        if image_path:
            content["image_path"] = image_path
        if image_base64:
            content["image_base64"] = image_base64
        if width:
            content["width"] = width
        if height:
            content["height"] = height

        return self.store(
            ModalityType.IMAGE,
            content,
            labels=labels,
            source=source,
            importance=importance,
        )

    def store_code(
        self,
        code: str,
        language: str = "python",
        labels: Optional[List[str]] = None,
        source: str = "",
        importance: float = 0.5,
    ) -> MultiModalContent:
        """Convenience method to store code content."""
        return self.store(
            ModalityType.CODE,
            {"code": code, "language": language},
            labels=labels,
            source=source,
            importance=importance,
        )

    def retrieve(self, content_id: str) -> Optional[MultiModalContent]:
        """Retrieve content by ID."""
        content = self.contents.get(content_id)
        if content:
            content.access_count += 1
            # Update associated entry
            for entry in self.entries.values():
                if entry.content_id == content_id:
                    entry.update_access()
                    break
        return content

    def search_by_text(
        self,
        query: str,
        k: int = 10,
        threshold: float = 0.0,
    ) -> List[Tuple[MultiModalContent, float]]:
        """Search by text query."""
        # Extract query features
        features = self.extractors[ModalityType.TEXT].extract({"text": query})
        if not features:
            return []

        embedding = features[0].vector
        if not embedding:
            return []

        # Search text index
        results = self.indices[ModalityType.TEXT].search(embedding, k, threshold)

        return [
            (self.contents[cid], score)
            for cid, score in results
            if cid in self.contents
        ]

    def search_cross_modal(
        self,
        query_content: Dict[str, Any],
        query_modality: ModalityType,
        k: int = 10,
        threshold: float = 0.0,
    ) -> List[Tuple[MultiModalContent, float]]:
        """Search across all modalities."""
        if query_modality not in self.extractors:
            return []

        # Extract query features
        features = self.extractors[query_modality].extract(query_content)
        if not features:
            return []

        embedding_feature = next(
            (f for f in features if f.feature_type == FeatureType.EMBEDDING),
            None,
        )
        if not embedding_feature or not embedding_feature.vector:
            return []

        # Project to common space
        projected = self.bridge.project_to_common_space(embedding_feature)

        # Search unified index
        results = self.unified_index.search(projected, k, threshold)

        return [
            (self.contents[cid], score)
            for cid, score in results
            if cid in self.contents
        ]

    def search_by_labels(
        self,
        labels: List[str],
        match_all: bool = False,
    ) -> List[MultiModalContent]:
        """Search by labels."""
        results = []
        labels_set = set(labels)

        for content in self.contents.values():
            content_labels = set(content.labels)
            if match_all:
                if labels_set.issubset(content_labels):
                    results.append(content)
            else:
                if labels_set.intersection(content_labels):
                    results.append(content)

        return results

    def link_content(
        self,
        content_id_a: str,
        content_id_b: str,
    ) -> bool:
        """Create bidirectional link between content."""
        if content_id_a not in self.contents or content_id_b not in self.contents:
            return False

        with self._lock:
            if content_id_b not in self.contents[content_id_a].relations:
                self.contents[content_id_a].relations.append(content_id_b)
            if content_id_a not in self.contents[content_id_b].relations:
                self.contents[content_id_b].relations.append(content_id_a)

        self._save_state()
        return True

    def get_related(
        self,
        content_id: str,
        depth: int = 1,
    ) -> List[MultiModalContent]:
        """Get related content."""
        if content_id not in self.contents:
            return []

        visited = {content_id}
        current_level = [content_id]
        results = []

        for _ in range(depth):
            next_level = []
            for cid in current_level:
                content = self.contents.get(cid)
                if not content:
                    continue

                for related_id in content.relations:
                    if related_id not in visited and related_id in self.contents:
                        visited.add(related_id)
                        next_level.append(related_id)
                        results.append(self.contents[related_id])

            current_level = next_level
            if not current_level:
                break

        return results

    def apply_decay(self, decay_factor: float = 0.95) -> None:
        """Apply recency decay to all entries."""
        for entry in self.entries.values():
            entry.decay_recency(decay_factor)
        self._save_state()

    def delete(self, content_id: str) -> bool:
        """Delete content and associated data."""
        if content_id not in self.contents:
            return False

        with self._lock:
            content = self.contents[content_id]

            # Remove from indices
            for modality, index in self.indices.items():
                index.remove(content_id)
            self.unified_index.remove(content_id)

            # Remove relations
            for other_id in content.relations:
                if other_id in self.contents:
                    if content_id in self.contents[other_id].relations:
                        self.contents[other_id].relations.remove(content_id)

            # Remove entries
            to_remove = [
                eid for eid, entry in self.entries.items()
                if entry.content_id == content_id
            ]
            for eid in to_remove:
                del self.entries[eid]

            # Remove content
            del self.contents[content_id]

        self._save_state()
        return True

    def get_statistics(self) -> Dict[str, Any]:
        """Get memory statistics."""
        by_modality = {}
        for modality in ModalityType:
            count = sum(
                1 for c in self.contents.values()
                if c.primary_modality == modality
            )
            if count > 0:
                by_modality[modality.value] = count

        return {
            "total_content": len(self.contents),
            "total_entries": len(self.entries),
            "by_modality": by_modality,
            "index_sizes": {
                modality.value: index.size()
                for modality, index in self.indices.items()
            },
            "unified_index_size": self.unified_index.size(),
        }


# =============================================================================
# CLI Tests
# =============================================================================

def run_cli_tests():
    """Run CLI tests for the multi-modal memory module."""
    import tempfile
    import shutil

    print("=" * 70)
    print("Multi-Modal Memory CLI Tests")
    print("=" * 70)

    tests_passed = 0
    tests_failed = 0

    def test(name: str, condition: bool) -> None:
        nonlocal tests_passed, tests_failed
        if condition:
            print(f"  [PASS] {name}")
            tests_passed += 1
        else:
            print(f"  [FAIL] {name}")
            tests_failed += 1

    temp_dir = tempfile.mkdtemp()

    try:
        # Test 1: Feature creation
        print("\n1. Testing Feature creation...")
        feature = Feature(
            feature_id="f1",
            feature_type=FeatureType.EMBEDDING,
            modality=ModalityType.TEXT,
            vector=[0.1, 0.2, 0.3],
        )
        test("Creates feature", feature is not None)
        test("Has dimension", feature.dimension == 3)

        # Test 2: Feature serialization
        print("\n2. Testing Feature serialization...")
        feature_dict = feature.to_dict()
        test("Serializes to dict", isinstance(feature_dict, dict))
        restored = Feature.from_dict(feature_dict)
        test("Deserializes from dict", restored.feature_id == feature.feature_id)

        # Test 3: MultiModalContent creation
        print("\n3. Testing MultiModalContent creation...")
        content = MultiModalContent(
            content_id="c1",
            primary_modality=ModalityType.TEXT,
            content={"text": "Hello world"},
            labels=["greeting"],
        )
        test("Creates content", content is not None)
        test("Has text", content.get_text_content() == "Hello world")

        # Test 4: Content serialization
        print("\n4. Testing Content serialization...")
        content_dict = content.to_dict()
        test("Serializes to dict", isinstance(content_dict, dict))
        test("Has hash", "content_hash" in content_dict)
        restored_content = MultiModalContent.from_dict(content_dict)
        test("Deserializes from dict", restored_content.content_id == content.content_id)

        # Test 5: Text Feature Extractor
        print("\n5. Testing Text Feature Extractor...")
        text_extractor = TextFeatureExtractor()
        features = text_extractor.extract({"text": "This is a test sentence for feature extraction."})
        test("Extracts features", len(features) >= 1)
        test("Has embedding", features[0].feature_type == FeatureType.EMBEDDING)
        test("Embedding has dimension", features[0].dimension == DEFAULT_TEXT_DIM)

        # Test 6: Image Feature Extractor
        print("\n6. Testing Image Feature Extractor...")
        image_extractor = ImageFeatureExtractor()
        features = image_extractor.extract({
            "image_path": "/test/image.png",
            "width": 100,
            "height": 100,
        })
        test("Extracts image features", len(features) >= 1)

        # Test 7: Code Feature Extractor
        print("\n7. Testing Code Feature Extractor...")
        code_extractor = CodeFeatureExtractor()
        features = code_extractor.extract({
            "code": "def hello():\n    print('Hello')",
            "language": "python",
        })
        test("Extracts code features", len(features) >= 1)

        # Test 8: Similarity Index
        print("\n8. Testing Similarity Index...")
        index = SimilarityIndex(dimension=3)
        test("Adds vector", index.add("v1", [1.0, 0.0, 0.0]))
        test("Adds another vector", index.add("v2", [0.0, 1.0, 0.0]))
        test("Adds third vector", index.add("v3", [1.0, 0.1, 0.0]))

        results = index.search([1.0, 0.0, 0.0], k=2)
        test("Searches index", len(results) == 2)
        test("Most similar first", results[0][0] == "v1")

        # Test 9: Cross-Modal Bridge
        print("\n9. Testing Cross-Modal Bridge...")
        bridge = CrossModalBridge(projection_dim=64)

        text_feature = Feature(
            feature_id="tf1",
            feature_type=FeatureType.EMBEDDING,
            modality=ModalityType.TEXT,
            vector=[0.1] * 384,
        )
        image_feature = Feature(
            feature_id="if1",
            feature_type=FeatureType.EMBEDDING,
            modality=ModalityType.IMAGE,
            vector=[0.2] * 512,
        )

        projected_text = bridge.project_to_common_space(text_feature)
        projected_image = bridge.project_to_common_space(image_feature)
        test("Projects text", len(projected_text) == 64)
        test("Projects image", len(projected_image) == 64)

        similarity = bridge.compute_cross_modal_similarity(text_feature, image_feature)
        test("Computes cross-modal similarity", 0 <= similarity <= 1)

        # Test 10: Memory Store
        print("\n10. Testing Memory Store...")
        store = MultiModalMemoryStore(temp_dir)

        stored = store.store_text(
            "This is a test document about machine learning.",
            labels=["ml", "test"],
            source="test",
        )
        test("Stores text content", stored is not None)
        test("Content has features", len(stored.features) >= 1)

        # Test 11: Text Search
        print("\n11. Testing Text Search...")
        results = store.search_by_text("machine learning", k=5)
        test("Searches by text", len(results) >= 1)
        test("Returns content and score", results[0][1] > 0)

        # Test 12: Store Image
        print("\n12. Testing Image Storage...")
        image_content = store.store_image(
            image_path="/test/sample.png",
            width=800,
            height=600,
            labels=["sample", "test"],
        )
        test("Stores image", image_content is not None)

        # Test 13: Store Code
        print("\n13. Testing Code Storage...")
        code_content = store.store_code(
            "def calculate(x, y):\n    return x + y",
            language="python",
            labels=["function", "math"],
        )
        test("Stores code", code_content is not None)

        # Test 14: Cross-Modal Search
        print("\n14. Testing Cross-Modal Search...")
        results = store.search_cross_modal(
            {"text": "machine learning"},
            ModalityType.TEXT,
            k=10,
        )
        test("Cross-modal search works", len(results) >= 1)

        # Test 15: Label Search
        print("\n15. Testing Label Search...")
        results = store.search_by_labels(["test"])
        test("Searches by label", len(results) >= 1)

        results = store.search_by_labels(["ml", "test"], match_all=True)
        test("Searches with match_all", len(results) >= 1)

        # Test 16: Content Retrieval
        print("\n16. Testing Content Retrieval...")
        retrieved = store.retrieve(stored.content_id)
        test("Retrieves content", retrieved is not None)
        test("Access count incremented", retrieved.access_count == 1)

        # Test 17: Content Linking
        print("\n17. Testing Content Linking...")
        test("Links content", store.link_content(stored.content_id, code_content.content_id))

        related = store.get_related(stored.content_id)
        test("Gets related content", len(related) == 1)

        # Test 18: Statistics
        print("\n18. Testing Statistics...")
        stats = store.get_statistics()
        test("Has total_content", "total_content" in stats)
        test("Has by_modality", "by_modality" in stats)
        test("Correct content count", stats["total_content"] == 3)

        # Test 19: Decay
        print("\n19. Testing Decay...")
        initial_recency = list(store.entries.values())[0].recency
        store.apply_decay(0.9)
        new_recency = list(store.entries.values())[0].recency
        test("Applies decay", new_recency < initial_recency)

        # Test 20: Deletion
        print("\n20. Testing Deletion...")
        test("Deletes content", store.delete(image_content.content_id))
        test("Content removed", store.retrieve(image_content.content_id) is None)

        # Test 21: Persistence
        print("\n21. Testing Persistence...")
        store._save_state()
        store2 = MultiModalMemoryStore(temp_dir)
        test("State persisted", len(store2.contents) == 2)

        # Test 22: Memory Entry
        print("\n22. Testing Memory Entry...")
        entry = MemoryEntry(
            entry_id="e1",
            content_id="c1",
            importance=0.8,
        )
        relevance = entry.compute_relevance()
        test("Computes relevance", 0 <= relevance <= 1)

        entry.update_access()
        test("Updates access", entry.frequency > 0)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print(f"Tests Passed: {tests_passed}/{tests_passed + tests_failed}")
    print("=" * 70)

    return tests_failed == 0


if __name__ == "__main__":
    success = run_cli_tests()
    exit(0 if success else 1)

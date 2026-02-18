#!/usr/bin/env python3
"""
MemCube - Event-Based Memory Unit
==================================

Core data structure for VERA's memory system.

Based on research:
- MemOS: Memory-Augmented Operating System architecture
- Event-based memory representation
- Compression with CommVQ 2-bit quantization

Key Features:
- Event-based memory unit (single semantic unit)
- Rich metadata (timestamp, importance, provenance)
- Compression support (basic now, full CommVQ in Week 3)
- Serialization for Memvid integration
- Importance scoring and decay

Architecture:
┌───────────────────────────────────┐
│           MemCube                 │
├───────────────────────────────────┤
│                                   │
│  ┌────────────────────────────┐  │
│  │  Content                   │  │
│  │  "User asked about..."     │  │
│  │  (string, dict, or bytes)  │  │
│  └────────────────────────────┘  │
│                                   │
│  ┌────────────────────────────┐  │
│  │  Metadata                  │  │
│  │  • timestamp               │  │
│  │  • importance (0.0-1.0)    │  │
│  │  • provenance (source)     │  │
│  │  • event_type              │  │
│  │  • tags []                 │  │
│  └────────────────────────────┘  │
│                                   │
│  ┌────────────────────────────┐  │
│  │  Compression               │  │
│  │  • compressed: bool        │  │
│  │  • compressed_bytes        │  │
│  │  • compression_ratio       │  │
│  └────────────────────────────┘  │
└───────────────────────────────────┘

Usage Example:
    # Create memory of user interaction
    cube = MemCube(
        content="User asked about Phase 2 timeline",
        event_type="user_query",
        importance=0.9,
        provenance={"source": "interactive_session", "user_id": "niz"}
    )

    # Compress
    cube.compress()

    # Serialize for storage
    data = cube.to_dict()

    # Restore
    restored = MemCube.from_dict(data)
"""

import json
import hashlib
import zlib
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum


class EventType(Enum):
    """Type of memory event"""
    USER_QUERY = "user_query"
    USER_COMMAND = "user_command"
    TOOL_EXECUTION = "tool_execution"
    AGENT_THOUGHT = "agent_thought"
    SYSTEM_EVENT = "system_event"
    EXTERNAL_DATA = "external_data"


@dataclass
class MemCubeMetadata:
    """Metadata for a MemCube"""
    timestamp: datetime
    importance: float  # 0.0 - 1.0
    event_type: EventType
    provenance: Dict[str, Any]  # Source information
    tags: List[str] = field(default_factory=list)
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    created_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "importance": self.importance,
            "event_type": self.event_type.value,
            "provenance": self.provenance,
            "tags": self.tags,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
            "created_by": self.created_by
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemCubeMetadata":
        """Create from dictionary"""
        return cls(
            timestamp=datetime.fromisoformat(data["timestamp"]),
            importance=data["importance"],
            event_type=EventType(data["event_type"]),
            provenance=data["provenance"],
            tags=data.get("tags", []),
            access_count=data.get("access_count", 0),
            last_accessed=datetime.fromisoformat(data["last_accessed"]) if data.get("last_accessed") else None,
            created_by=data.get("created_by")
        )


class MemCube:
    """
    Event-based memory unit

    Represents a single semantic memory (user query, tool result, thought, etc.)
    with rich metadata and compression support.

    Features:
    - Flexible content (string, dict, or pre-compressed bytes)
    - Importance scoring and decay
    - Compression (zlib now, CommVQ in Week 3)
    - Serialization for storage
    - Provenance tracking
    """

    def __init__(
        self,
        content: Any,
        event_type: EventType = EventType.SYSTEM_EVENT,
        importance: float = 0.5,
        provenance: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        created_by: Optional[str] = None
    ):
        """
        Create a MemCube

        Args:
            content: Memory content (string, dict, or bytes)
            event_type: Type of event
            importance: Initial importance (0.0 - 1.0)
            provenance: Source information
            tags: Optional tags for categorization
            created_by: Optional creator identifier
        """
        # Content
        self.content = content
        self._compressed = False
        self._compressed_bytes: Optional[bytes] = None
        self._compression_ratio: float = 1.0

        # Metadata
        self.metadata = MemCubeMetadata(
            timestamp=datetime.now(),
            importance=self._clamp_importance(importance),
            event_type=event_type,
            provenance=provenance or {},
            tags=tags or [],
            created_by=created_by
        )

        # Unique ID
        self.cube_id = self._generate_id()

    def _generate_id(self) -> str:
        """Generate unique ID based on content and timestamp"""
        content_str = str(self.content) + self.metadata.timestamp.isoformat()
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def _clamp_importance(self, importance: float) -> float:
        """Clamp importance to [0.0, 1.0]"""
        return max(0.0, min(1.0, importance))

    def compress(self, method: str = "zlib") -> bool:
        """
        Compress content

        Args:
            method: Compression method ("zlib" now, "commvq" in Week 3)

        Returns:
            True if compressed, False if already compressed
        """
        if self._compressed:
            return False

        # Convert content to bytes
        if isinstance(self.content, bytes):
            content_bytes = self.content
        elif isinstance(self.content, str):
            content_bytes = self.content.encode('utf-8')
        elif isinstance(self.content, dict):
            content_bytes = json.dumps(self.content).encode('utf-8')
        else:
            content_bytes = str(self.content).encode('utf-8')

        original_size = len(content_bytes)

        # Compress (basic zlib for now, will upgrade to CommVQ in Week 3)
        if method == "zlib":
            self._compressed_bytes = zlib.compress(content_bytes, level=9)
        else:
            # Future: CommVQ 2-bit quantization
            raise NotImplementedError(f"Compression method '{method}' not yet implemented")

        compressed_size = len(self._compressed_bytes)
        self._compression_ratio = compressed_size / original_size if original_size > 0 else 1.0

        self._compressed = True

        return True

    def decompress(self) -> Any:
        """
        Decompress and return content

        Returns:
            Decompressed content
        """
        if not self._compressed or self._compressed_bytes is None:
            return self.content

        # Decompress
        decompressed_bytes = zlib.decompress(self._compressed_bytes)

        # Try to restore original type
        try:
            # Try JSON first (for dicts)
            return json.loads(decompressed_bytes.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Fall back to string
            try:
                return decompressed_bytes.decode('utf-8')
            except UnicodeDecodeError:
                # Return raw bytes
                return decompressed_bytes

    def get_content(self) -> Any:
        """
        Get content (decompresses if needed)

        Returns:
            Content in original form
        """
        if self._compressed:
            return self.decompress()
        return self.content

    def access(self) -> None:
        """Mark cube as accessed (updates metadata)"""
        self.metadata.access_count += 1
        self.metadata.last_accessed = datetime.now()

    def decay_importance(self, decay_factor: float = 0.95) -> None:
        """
        Apply Ebbinghaus decay to importance

        Args:
            decay_factor: Decay multiplier (0.0 - 1.0)
        """
        self.metadata.importance *= decay_factor
        self.metadata.importance = max(0.0, self.metadata.importance)

    def boost_importance(self, boost: float = 0.1) -> None:
        """
        Boost importance (e.g., after being accessed/retrieved)

        Args:
            boost: Amount to add to importance
        """
        self.metadata.importance = self._clamp_importance(
            self.metadata.importance + boost
        )

    def add_tag(self, tag: str) -> None:
        """Add a tag"""
        if tag not in self.metadata.tags:
            self.metadata.tags.append(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag"""
        if tag in self.metadata.tags:
            self.metadata.tags.remove(tag)

    def has_tag(self, tag: str) -> bool:
        """Check if cube has a tag"""
        return tag in self.metadata.tags

    def age(self) -> timedelta:
        """Get age of memory"""
        return datetime.now() - self.metadata.timestamp

    def size_bytes(self) -> int:
        """Get size in bytes (compressed if available)"""
        if self._compressed and self._compressed_bytes:
            return len(self._compressed_bytes)

        # Estimate uncompressed size
        if isinstance(self.content, bytes):
            return len(self.content)
        elif isinstance(self.content, str):
            return len(self.content.encode('utf-8'))
        elif isinstance(self.content, dict):
            return len(json.dumps(self.content).encode('utf-8'))
        else:
            return len(str(self.content).encode('utf-8'))

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to dictionary

        Returns:
            Dictionary representation
        """
        data = {
            "cube_id": self.cube_id,
            "metadata": self.metadata.to_dict(),
            "compressed": self._compressed,
            "compression_ratio": self._compression_ratio
        }

        # Include content (compressed or raw)
        if self._compressed and self._compressed_bytes:
            # Store compressed bytes as base64
            import base64
            data["content_compressed"] = base64.b64encode(self._compressed_bytes).decode('ascii')
        else:
            data["content"] = self.content

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemCube":
        """
        Deserialize from dictionary

        Args:
            data: Dictionary representation

        Returns:
            MemCube instance
        """
        # Restore metadata
        metadata = MemCubeMetadata.from_dict(data["metadata"])

        # Create cube
        if data["compressed"]:
            # Restore compressed content
            import base64
            compressed_bytes = base64.b64decode(data["content_compressed"])

            cube = cls(
                content=None,  # Will be decompressed on access
                event_type=metadata.event_type,
                importance=metadata.importance,
                provenance=metadata.provenance,
                tags=metadata.tags,
                created_by=metadata.created_by
            )

            cube._compressed = True
            cube._compressed_bytes = compressed_bytes
            cube._compression_ratio = data["compression_ratio"]
        else:
            # Restore raw content
            cube = cls(
                content=data["content"],
                event_type=metadata.event_type,
                importance=metadata.importance,
                provenance=metadata.provenance,
                tags=metadata.tags,
                created_by=metadata.created_by
            )

        # Restore metadata timestamps
        cube.metadata.timestamp = metadata.timestamp
        cube.metadata.access_count = metadata.access_count
        cube.metadata.last_accessed = metadata.last_accessed

        # Restore ID
        cube.cube_id = data["cube_id"]

        return cube

    def __repr__(self) -> str:
        content_preview = str(self.get_content())[:50]
        if len(str(self.get_content())) > 50:
            content_preview += "..."

        return (
            f"MemCube(id={self.cube_id}, "
            f"type={self.metadata.event_type.value}, "
            f"importance={self.metadata.importance:.2f}, "
            f"content='{content_preview}')"
        )


# Example usage and testing
def run_example() -> None:
    """Demonstrate MemCube capabilities"""
    print("=== MemCube Example ===\n")

    # Example 1: Create memory
    print("Example 1: Create Memory")
    print("-" * 60)

    cube = MemCube(
        content="User asked: 'What is the status of Phase 2?'",
        event_type=EventType.USER_QUERY,
        importance=0.9,
        provenance={"source": "interactive_session", "session_id": "sess_123"},
        tags=["phase2", "status"],
        created_by="vera_agent"
    )

    print(f"Created: {cube}")
    print(f"ID: {cube.cube_id}")
    print(f"Size: {cube.size_bytes()} bytes")
    print(f"Age: {cube.age().total_seconds():.2f}s")

    # Example 2: Compression
    print("\n\nExample 2: Compression")
    print("-" * 60)

    # Create larger content
    large_content = {
        "query": "Explain Phase 2 implementation",
        "context": ["async tools", "output filtering", "memory system"] * 100,
        "metadata": {"session": "interactive", "timestamp": datetime.now().isoformat()}
    }

    large_cube = MemCube(
        content=large_content,
        event_type=EventType.USER_QUERY,
        importance=0.85
    )

    original_size = large_cube.size_bytes()
    print(f"Original size: {original_size} bytes")

    large_cube.compress()

    compressed_size = large_cube.size_bytes()
    print(f"Compressed size: {compressed_size} bytes")
    print(f"Compression ratio: {large_cube._compression_ratio:.1%}")
    print(f"Space saved: {original_size - compressed_size} bytes ({(1 - large_cube._compression_ratio):.1%})")

    # Verify content is preserved
    restored = large_cube.get_content()
    print(f"Content preserved: {restored == large_content}")

    # Example 3: Importance decay
    print("\n\nExample 3: Importance Decay (Ebbinghaus)")
    print("-" * 60)

    memory = MemCube(
        content="Temporary note",
        event_type=EventType.AGENT_THOUGHT,
        importance=0.8
    )

    print(f"Initial importance: {memory.metadata.importance:.2f}")

    for i in range(5):
        memory.decay_importance(decay_factor=0.9)
        print(f"After decay {i+1}: {memory.metadata.importance:.2f}")

    # Boost after access
    memory.access()
    memory.boost_importance(boost=0.2)
    print(f"After access boost: {memory.metadata.importance:.2f}")

    # Example 4: Serialization
    print("\n\nExample 4: Serialization")
    print("-" * 60)

    cube = MemCube(
        content={"key": "value", "data": [1, 2, 3]},
        event_type=EventType.TOOL_EXECUTION,
        importance=0.7,
        tags=["serialization", "test"]
    )

    cube.compress()

    # Serialize
    serialized = cube.to_dict()
    print(f"Serialized keys: {list(serialized.keys())}")

    # Deserialize
    restored_cube = MemCube.from_dict(serialized)
    print(f"Restored: {restored_cube}")
    print(f"Content match: {restored_cube.get_content() == cube.get_content()}")
    print(f"Metadata match: {restored_cube.metadata.importance == cube.metadata.importance}")

    # Example 5: Tags and filtering
    print("\n\nExample 5: Tags and Filtering")
    print("-" * 60)

    cubes = []
    for i in range(10):
        cube = MemCube(
            content=f"Memory {i}",
            event_type=EventType.SYSTEM_EVENT,
            importance=0.5 + (i / 20),  # Increasing importance
            tags=["test", f"priority_{i % 3}"]  # Different priority tags
        )
        cubes.append(cube)

    # Filter by tag
    high_priority = [c for c in cubes if c.has_tag("priority_2")]
    print(f"Total cubes: {len(cubes)}")
    print(f"High priority (tag='priority_2'): {len(high_priority)}")

    # Filter by importance
    important = [c for c in cubes if c.metadata.importance > 0.7]
    print(f"Important (>0.7): {len(important)}")

    print("\n✅ All examples complete")


if __name__ == "__main__":
    run_example()

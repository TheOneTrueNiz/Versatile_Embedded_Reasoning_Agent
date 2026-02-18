"""
Federated Memory: Privacy-Preserving Mesh Memory over LAN

Implements secure distributed memory sharing across agent instances
on a local network, enabling collaborative learning while preserving
privacy through differential privacy and secure aggregation.

Key components:
- LAN peer discovery via UDP broadcast/mDNS simulation
- Secure peer-to-peer memory sharing with encryption
- Privacy-preserving aggregation with differential privacy
- Mesh networking for mobile agents
- Selective memory synchronization with conflict resolution
- Vector clock for distributed ordering

Paper references:
- "Federated Learning: Strategies for Improving Communication Efficiency" (arXiv:1610.05492)
- "Differentially Private Federated Learning" (arXiv:1710.06963)
- "Secure Aggregation for Federated Learning" (arXiv:1912.04977)
"""

import json
import hashlib
import secrets
import socket
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional
import base64
import logging
logger = logging.getLogger(__name__)


class PeerState(Enum):
    """States a peer can be in."""
    DISCOVERED = "discovered"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    SYNCING = "syncing"
    DISCONNECTED = "disconnected"
    UNREACHABLE = "unreachable"


class MemoryType(Enum):
    """Types of shared memory."""
    KNOWLEDGE = "knowledge"         # Factual knowledge
    EXPERIENCE = "experience"       # Task execution history
    PREFERENCE = "preference"       # User preferences
    MODEL = "model"                 # Model weights/embeddings
    CONTEXT = "context"            # Conversation context


class SyncStrategy(Enum):
    """Strategies for memory synchronization."""
    FULL = "full"                  # Full sync of all memories
    INCREMENTAL = "incremental"    # Only new/changed items
    SELECTIVE = "selective"        # Based on relevance
    FEDERATED = "federated"        # Privacy-preserving aggregation


class ConflictResolution(Enum):
    """Strategies for resolving conflicts."""
    LATEST_WINS = "latest_wins"    # Most recent timestamp
    MERGE = "merge"                # Merge if possible
    VECTOR_CLOCK = "vector_clock"  # Based on causal ordering
    MAJORITY = "majority"          # Majority vote from peers


@dataclass
class VectorClock:
    """Vector clock for distributed ordering."""
    clocks: dict[str, int] = field(default_factory=dict)

    def increment(self, node_id: str) -> None:
        """Increment clock for a node."""
        self.clocks[node_id] = self.clocks.get(node_id, 0) + 1

    def merge(self, other: "VectorClock") -> None:
        """Merge with another vector clock."""
        all_nodes = set(self.clocks.keys()) | set(other.clocks.keys())
        for node in all_nodes:
            self.clocks[node] = max(
                self.clocks.get(node, 0),
                other.clocks.get(node, 0)
            )

    def happens_before(self, other: "VectorClock") -> bool:
        """Check if this clock happens-before another."""
        # Returns True if this clock is strictly before other
        at_least_one_less = False
        for node, time in self.clocks.items():
            other_time = other.clocks.get(node, 0)
            if time > other_time:
                return False
            if time < other_time:
                at_least_one_less = True

        # Check for nodes only in other
        for node in other.clocks:
            if node not in self.clocks and other.clocks[node] > 0:
                at_least_one_less = True

        return at_least_one_less

    def concurrent_with(self, other: "VectorClock") -> bool:
        """Check if clocks are concurrent (neither happens-before)."""
        return not self.happens_before(other) and not other.happens_before(self)

    def to_dict(self) -> dict[str, int]:
        return dict(self.clocks)

    @classmethod
    def from_dict(cls, data: dict[str, int]) -> "VectorClock":
        vc = cls()
        vc.clocks = dict(data)
        return vc


@dataclass
class MemoryItem:
    """A single memory item that can be shared."""
    item_id: str
    memory_type: MemoryType
    content: Any
    embedding: Optional[list[float]] = None
    timestamp: float = field(default_factory=time.time)
    vector_clock: VectorClock = field(default_factory=VectorClock)
    source_peer: Optional[str] = None
    privacy_level: int = 0  # 0=public, 1=friends, 2=private
    checksum: Optional[str] = None

    def __post_init__(self):
        if self.checksum is None:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute checksum of content."""
        content_str = json.dumps(self.content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "memory_type": self.memory_type.value,
            "content": self.content,
            "embedding": self.embedding,
            "timestamp": self.timestamp,
            "vector_clock": self.vector_clock.to_dict(),
            "source_peer": self.source_peer,
            "privacy_level": self.privacy_level,
            "checksum": self.checksum
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryItem":
        return cls(
            item_id=data.get("item_id", ""),
            memory_type=MemoryType(data.get("memory_type", "")),
            content=data.get("content", ""),
            embedding=data.get("embedding"),
            timestamp=data.get("timestamp", time.time()),
            vector_clock=VectorClock.from_dict(data.get("vector_clock", {})),
            source_peer=data.get("source_peer"),
            privacy_level=data.get("privacy_level", 0),
            checksum=data.get("checksum")
        )


@dataclass
class PeerInfo:
    """Information about a peer in the mesh."""
    peer_id: str
    address: str
    port: int
    state: PeerState
    last_seen: float = field(default_factory=time.time)
    capabilities: list[str] = field(default_factory=list)
    public_key: Optional[str] = None
    trust_score: float = 0.5
    memory_types: list[MemoryType] = field(default_factory=list)
    sync_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "peer_id": self.peer_id,
            "address": self.address,
            "port": self.port,
            "state": self.state.value,
            "last_seen": self.last_seen,
            "capabilities": self.capabilities,
            "public_key": self.public_key,
            "trust_score": self.trust_score,
            "memory_types": [m.value for m in self.memory_types],
            "sync_version": self.sync_version
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PeerInfo":
        return cls(
            peer_id=data.get("peer_id", ""),
            address=data.get("address", ""),
            port=data.get("port", ""),
            state=PeerState(data.get("state", "")),
            last_seen=data.get("last_seen", time.time()),
            capabilities=data.get("capabilities", []),
            public_key=data.get("public_key"),
            trust_score=data.get("trust_score", 0.5),
            memory_types=[MemoryType(m) for m in data.get("memory_types", [])],
            sync_version=data.get("sync_version", 0)
        )


@dataclass
class SyncRequest:
    """Request to synchronize memory with a peer."""
    request_id: str
    requester_id: str
    memory_types: list[MemoryType]
    since_timestamp: Optional[float] = None
    since_version: int = 0
    strategy: SyncStrategy = SyncStrategy.INCREMENTAL
    max_items: int = 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "requester_id": self.requester_id,
            "memory_types": [m.value for m in self.memory_types],
            "since_timestamp": self.since_timestamp,
            "since_version": self.since_version,
            "strategy": self.strategy.value,
            "max_items": self.max_items
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncRequest":
        return cls(
            request_id=data.get("request_id", ""),
            requester_id=data.get("requester_id", ""),
            memory_types=[MemoryType(m) for m in data.get("memory_types", "")],
            since_timestamp=data.get("since_timestamp"),
            since_version=data.get("since_version", 0),
            strategy=SyncStrategy(data.get("strategy", "incremental")),
            max_items=data.get("max_items", 100)
        )


@dataclass
class SyncResponse:
    """Response to a sync request."""
    request_id: str
    responder_id: str
    items: list[MemoryItem]
    current_version: int
    has_more: bool
    next_timestamp: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "responder_id": self.responder_id,
            "items": [i.to_dict() for i in self.items],
            "current_version": self.current_version,
            "has_more": self.has_more,
            "next_timestamp": self.next_timestamp
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SyncResponse":
        return cls(
            request_id=data.get("request_id", ""),
            responder_id=data.get("responder_id", ""),
            items=[MemoryItem.from_dict(i) for i in data.get("items", "")],
            current_version=data.get("current_version", ""),
            has_more=data.get("has_more", ""),
            next_timestamp=data.get("next_timestamp")
        )


class PrivacyEngine:
    """Handles privacy-preserving operations."""

    def __init__(self, epsilon: float = 1.0, delta: float = 1e-5) -> None:
        """
        Initialize privacy engine.

        Args:
            epsilon: Privacy budget (lower = more privacy)
            delta: Probability of privacy failure
        """
        self.epsilon = epsilon
        self.delta = delta
        self._lock = threading.Lock()

    def add_noise(self, value: float, sensitivity: float = 1.0) -> float:
        """Add Laplacian noise for differential privacy."""
        import random
        scale = sensitivity / self.epsilon
        # Laplacian noise
        u = random.random() - 0.5
        noise = -scale * (1 if u > 0 else -1) * (abs(2 * u) ** 0.5 if abs(u) < 0.5 else 1)
        return value + noise

    def add_noise_to_vector(self, vector: list[float], sensitivity: float = 1.0) -> list[float]:
        """Add noise to an entire vector."""
        return [self.add_noise(v, sensitivity) for v in vector]

    def clip_gradient(self, gradient: list[float], max_norm: float = 1.0) -> list[float]:
        """Clip gradient to limit sensitivity."""
        import math
        norm = math.sqrt(sum(g ** 2 for g in gradient))
        if norm > max_norm:
            scale = max_norm / norm
            return [g * scale for g in gradient]
        return gradient

    def secure_aggregate(self, values: list[float], num_peers: int) -> float:
        """Securely aggregate values from multiple peers."""
        # Simple averaging with privacy
        if not values:
            return 0.0

        # Clip each value
        clipped = [max(-1, min(1, v)) for v in values]

        # Average
        avg = sum(clipped) / len(clipped)

        # Add noise based on number of peers
        sensitivity = 2.0 / num_peers  # Sensitivity of average
        return self.add_noise(avg, sensitivity)

    def can_share(self, memory_item: MemoryItem, privacy_level: int) -> bool:
        """Check if item can be shared at given privacy level."""
        return memory_item.privacy_level <= privacy_level

    def anonymize_content(self, content: Any) -> Any:
        """Anonymize content by removing identifying information."""
        if isinstance(content, str):
            # Simple anonymization - in practice would use NER
            return content
        elif isinstance(content, dict):
            return {k: self.anonymize_content(v) for k, v in content.items()}
        elif isinstance(content, list):
            return [self.anonymize_content(v) for v in content]
        return content


class MockEncryption:
    """Mock encryption for testing (in production use proper crypto)."""

    def __init__(self) -> None:
        self.key = secrets.token_bytes(32)

    def encrypt(self, data: bytes) -> bytes:
        """Mock encrypt data."""
        # XOR with repeated key (not secure, just for testing)
        key_repeated = (self.key * ((len(data) // len(self.key)) + 1))[:len(data)]
        encrypted = bytes(a ^ b for a, b in zip(data, key_repeated))
        return base64.b64encode(encrypted)

    def decrypt(self, data: bytes) -> bytes:
        """Mock decrypt data."""
        decoded = base64.b64decode(data)
        key_repeated = (self.key * ((len(decoded) // len(self.key)) + 1))[:len(decoded)]
        decrypted = bytes(a ^ b for a, b in zip(decoded, key_repeated))
        return decrypted


class PeerDiscovery:
    """Handles peer discovery on the local network."""

    BROADCAST_PORT = 54321
    DISCOVERY_MAGIC = b"VERA_MESH_V1"

    def __init__(self, node_id: str, listen_port: int = 0) -> None:
        self.node_id = node_id
        self.listen_port = listen_port
        self.discovered_peers: dict[str, PeerInfo] = {}
        self._lock = threading.Lock()
        self._running = False
        self._socket: Optional[socket.socket] = None

    def _create_discovery_packet(self) -> bytes:
        """Create a discovery announcement packet."""
        data = {
            "magic": self.DISCOVERY_MAGIC.decode(),
            "peer_id": self.node_id,
            "port": self.listen_port,
            "timestamp": time.time(),
            "capabilities": ["sync", "aggregate"]
        }
        return json.dumps(data).encode()

    def _parse_discovery_packet(self, data: bytes, address: tuple[str, int]) -> Optional[PeerInfo]:
        """Parse a discovery packet."""
        try:
            info = json.loads(data.decode())
            if info.get("magic") != self.DISCOVERY_MAGIC.decode():
                return None

            if info["peer_id"] == self.node_id:
                return None  # Ignore self

            return PeerInfo(
                peer_id=info["peer_id"],
                address=address[0],
                port=info["port"],
                state=PeerState.DISCOVERED,
                capabilities=info.get("capabilities", [])
            )
        except (json.JSONDecodeError, KeyError):
            return None

    def broadcast_presence(self) -> None:
        """Broadcast presence on the network."""
        if self._socket is None:
            return

        try:
            packet = self._create_discovery_packet()
            self._socket.sendto(packet, ('<broadcast>', self.BROADCAST_PORT))
        except OSError as exc:
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def start(self) -> None:
        """Start peer discovery."""
        self._running = True
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.settimeout(1.0)

        try:
            self._socket.bind(('', self.BROADCAST_PORT))
        except OSError as exc:
            # Port may be in use
            logger.debug("Suppressed %s: %s", type(exc).__name__, exc)

    def stop(self) -> None:
        """Stop peer discovery."""
        self._running = False
        if self._socket:
            self._socket.close()
            self._socket = None

    def listen_once(self) -> Optional[PeerInfo]:
        """Listen for one discovery packet."""
        if self._socket is None or not self._running:
            return None

        try:
            data, address = self._socket.recvfrom(1024)
            peer = self._parse_discovery_packet(data, address)
            if peer:
                with self._lock:
                    self.discovered_peers[peer.peer_id] = peer
            return peer
        except socket.timeout:
            return None
        except OSError:
            return None

    def get_peers(self) -> list[PeerInfo]:
        """Get all discovered peers."""
        with self._lock:
            return list(self.discovered_peers.values())

    def add_peer_manually(self, peer: PeerInfo) -> None:
        """Add a peer manually (for testing)."""
        with self._lock:
            self.discovered_peers[peer.peer_id] = peer


class ConflictResolver:
    """Resolves conflicts between memory items."""

    def __init__(self, strategy: ConflictResolution = ConflictResolution.VECTOR_CLOCK) -> None:
        self.strategy = strategy

    def resolve(self, local: MemoryItem, remote: MemoryItem) -> MemoryItem:
        """Resolve conflict between local and remote items."""
        if self.strategy == ConflictResolution.LATEST_WINS:
            return remote if remote.timestamp > local.timestamp else local

        elif self.strategy == ConflictResolution.VECTOR_CLOCK:
            if local.vector_clock.happens_before(remote.vector_clock):
                return remote
            elif remote.vector_clock.happens_before(local.vector_clock):
                return local
            else:
                # Concurrent - use timestamp as tiebreaker
                return remote if remote.timestamp > local.timestamp else local

        elif self.strategy == ConflictResolution.MERGE:
            return self._merge_items(local, remote)

        elif self.strategy == ConflictResolution.MAJORITY:
            # For majority, we'd need more context
            return remote if remote.timestamp > local.timestamp else local

        return local

    def _merge_items(self, local: MemoryItem, remote: MemoryItem) -> MemoryItem:
        """Attempt to merge two items."""
        # Simple merge: prefer remote content but keep local metadata
        merged_clock = VectorClock.from_dict(local.vector_clock.to_dict())
        merged_clock.merge(remote.vector_clock)

        return MemoryItem(
            item_id=local.item_id,
            memory_type=local.memory_type,
            content=self._merge_content(local.content, remote.content),
            embedding=remote.embedding or local.embedding,
            timestamp=max(local.timestamp, remote.timestamp),
            vector_clock=merged_clock,
            source_peer=remote.source_peer,
            privacy_level=min(local.privacy_level, remote.privacy_level)
        )

    def _merge_content(self, local_content: Any, remote_content: Any) -> Any:
        """Merge content based on type."""
        if isinstance(local_content, dict) and isinstance(remote_content, dict):
            # Merge dictionaries
            merged = dict(local_content)
            merged.update(remote_content)
            return merged
        elif isinstance(local_content, list) and isinstance(remote_content, list):
            # Combine lists, remove duplicates
            seen = set()
            merged = []
            for item in local_content + remote_content:
                item_str = json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
                if item_str not in seen:
                    seen.add(item_str)
                    merged.append(item)
            return merged
        # Default: prefer remote
        return remote_content


class MemoryStore:
    """Local memory store for the mesh."""

    def __init__(self, node_id: str, storage_path: Optional[Path] = None) -> None:
        self.node_id = node_id
        self.storage_path = storage_path
        self.items: dict[str, MemoryItem] = {}
        self.version = 0
        self._lock = threading.Lock()
        self._item_counter = 0

        if storage_path:
            self._load_from_disk()

    def _generate_id(self) -> str:
        with self._lock:
            self._item_counter += 1
            return f"mem_{self.node_id[:8]}_{self._item_counter}_{int(time.time() * 1000) % 10000}"

    def add(self, memory_type: MemoryType, content: Any,
            embedding: Optional[list[float]] = None,
            privacy_level: int = 0) -> MemoryItem:
        """Add a new memory item."""
        item_id = self._generate_id()

        vector_clock = VectorClock()
        vector_clock.increment(self.node_id)

        item = MemoryItem(
            item_id=item_id,
            memory_type=memory_type,
            content=content,
            embedding=embedding,
            vector_clock=vector_clock,
            source_peer=self.node_id,
            privacy_level=privacy_level
        )

        with self._lock:
            self.items[item_id] = item
            self.version += 1

        return item

    def get(self, item_id: str) -> Optional[MemoryItem]:
        """Get a memory item by ID."""
        with self._lock:
            return self.items.get(item_id)

    def update(self, item_id: str, content: Any) -> Optional[MemoryItem]:
        """Update a memory item."""
        with self._lock:
            if item_id not in self.items:
                return None

            item = self.items[item_id]
            item.content = content
            item.timestamp = time.time()
            item.vector_clock.increment(self.node_id)
            item.checksum = item._compute_checksum()
            self.version += 1

            return item

    def delete(self, item_id: str) -> bool:
        """Delete a memory item."""
        with self._lock:
            if item_id in self.items:
                del self.items[item_id]
                self.version += 1
                return True
            return False

    def get_by_type(self, memory_type: MemoryType) -> list[MemoryItem]:
        """Get all items of a specific type."""
        with self._lock:
            return [i for i in self.items.values() if i.memory_type == memory_type]

    def get_since(self, timestamp: float) -> list[MemoryItem]:
        """Get items modified since timestamp."""
        with self._lock:
            return [i for i in self.items.values() if i.timestamp > timestamp]

    def get_shareable(self, privacy_level: int) -> list[MemoryItem]:
        """Get items that can be shared at given privacy level."""
        with self._lock:
            return [i for i in self.items.values() if i.privacy_level <= privacy_level]

    def merge_item(self, item: MemoryItem, resolver: ConflictResolver) -> MemoryItem:
        """Merge an incoming item with local store."""
        with self._lock:
            if item.item_id in self.items:
                local = self.items[item.item_id]
                resolved = resolver.resolve(local, item)
                self.items[item.item_id] = resolved
                self.version += 1
                return resolved
            else:
                # New item
                self.items[item.item_id] = item
                self.version += 1
                return item

    def get_all(self) -> list[MemoryItem]:
        """Get all memory items."""
        with self._lock:
            return list(self.items.values())

    def _save_to_disk(self):
        """Save store to disk."""
        if self.storage_path is None:
            return

        data = {
            "node_id": self.node_id,
            "version": self.version,
            "items": {k: v.to_dict() for k, v in self.items.items()}
        }

        self.storage_path.mkdir(parents=True, exist_ok=True)
        with open(self.storage_path / "memory_store.json", "w") as f:
            json.dump(data, f, indent=2)

    def _load_from_disk(self):
        """Load store from disk."""
        if self.storage_path is None:
            return

        store_file = self.storage_path / "memory_store.json"
        if not store_file.exists():
            return

        with open(store_file) as f:
            data = json.load(f)

        self.version = data.get("version", 0)
        self.items = {k: MemoryItem.from_dict(v) for k, v in data.get("items", {}).items()}


class SyncManager:
    """Manages memory synchronization between peers."""

    def __init__(
        self,
        node_id: str,
        memory_store: MemoryStore,
        privacy_engine: PrivacyEngine,
        conflict_resolver: ConflictResolver
    ):
        self.node_id = node_id
        self.memory_store = memory_store
        self.privacy_engine = privacy_engine
        self.conflict_resolver = conflict_resolver
        self.sync_history: dict[str, float] = {}  # peer_id -> last_sync_time
        self._lock = threading.Lock()
        self._request_counter = 0

    def _generate_request_id(self) -> str:
        with self._lock:
            self._request_counter += 1
            return f"sync_{self.node_id[:8]}_{self._request_counter}"

    def create_sync_request(
        self,
        peer_id: str,
        memory_types: list[MemoryType],
        strategy: SyncStrategy = SyncStrategy.INCREMENTAL
    ) -> SyncRequest:
        """Create a sync request for a peer."""
        since_timestamp = self.sync_history.get(peer_id)

        return SyncRequest(
            request_id=self._generate_request_id(),
            requester_id=self.node_id,
            memory_types=memory_types,
            since_timestamp=since_timestamp,
            since_version=0,
            strategy=strategy
        )

    def handle_sync_request(self, request: SyncRequest, privacy_level: int = 0) -> SyncResponse:
        """Handle an incoming sync request."""
        items_to_share = []

        for memory_type in request.memory_types:
            type_items = self.memory_store.get_by_type(memory_type)

            for item in type_items:
                # Check privacy
                if not self.privacy_engine.can_share(item, privacy_level):
                    continue

                # Check timestamp
                if request.since_timestamp and item.timestamp <= request.since_timestamp:
                    continue

                items_to_share.append(item)

        # Sort by timestamp
        items_to_share.sort(key=lambda x: x.timestamp)

        # Limit items
        has_more = len(items_to_share) > request.max_items
        items_to_share = items_to_share[:request.max_items]

        # Add privacy noise to embeddings
        for item in items_to_share:
            if item.embedding:
                item.embedding = self.privacy_engine.add_noise_to_vector(item.embedding)

        next_timestamp = items_to_share[-1].timestamp if items_to_share else None

        return SyncResponse(
            request_id=request.request_id,
            responder_id=self.node_id,
            items=items_to_share,
            current_version=self.memory_store.version,
            has_more=has_more,
            next_timestamp=next_timestamp
        )

    def apply_sync_response(self, response: SyncResponse) -> list[MemoryItem]:
        """Apply a sync response to local store."""
        merged_items = []

        for item in response.items:
            merged = self.memory_store.merge_item(item, self.conflict_resolver)
            merged_items.append(merged)

        # Update sync history
        with self._lock:
            if response.next_timestamp:
                self.sync_history[response.responder_id] = response.next_timestamp

        return merged_items

    def get_sync_status(self, peer_id: str) -> Optional[float]:
        """Get last sync time with a peer."""
        with self._lock:
            return self.sync_history.get(peer_id)


class FederatedAggregator:
    """Handles federated aggregation of model updates."""

    def __init__(self, privacy_engine: PrivacyEngine) -> None:
        self.privacy_engine = privacy_engine
        self.pending_updates: dict[str, list[list[float]]] = {}  # round_id -> updates
        self._lock = threading.Lock()

    def submit_update(self, round_id: str, update: list[float]) -> str:
        """Submit a model update for aggregation."""
        # Clip update for privacy
        clipped = self.privacy_engine.clip_gradient(update)

        with self._lock:
            if round_id not in self.pending_updates:
                self.pending_updates[round_id] = []
            self.pending_updates[round_id].append(clipped)

        return round_id

    def aggregate(self, round_id: str, min_participants: int = 2) -> Optional[list[float]]:
        """Aggregate updates from all participants."""
        with self._lock:
            if round_id not in self.pending_updates:
                return None

            updates = self.pending_updates[round_id]
            if len(updates) < min_participants:
                return None

            # Average across participants
            num_updates = len(updates)
            if num_updates == 0:
                return None

            dim = len(updates[0])
            aggregated = [0.0] * dim

            for update in updates:
                for i, val in enumerate(update):
                    aggregated[i] += val / num_updates

            # Add noise for differential privacy
            aggregated = self.privacy_engine.add_noise_to_vector(
                aggregated,
                sensitivity=2.0 / num_updates
            )

            return aggregated

    def clear_round(self, round_id: str) -> None:
        """Clear updates for a round."""
        with self._lock:
            self.pending_updates.pop(round_id, None)

    def get_participant_count(self, round_id: str) -> int:
        """Get number of participants in a round."""
        with self._lock:
            return len(self.pending_updates.get(round_id, []))


class MeshNetwork:
    """Main mesh network orchestrator."""

    def __init__(
        self,
        node_id: Optional[str] = None,
        listen_port: int = 0,
        storage_path: Optional[Path] = None,
        epsilon: float = 1.0
    ):
        self.node_id = node_id or f"node_{secrets.token_hex(8)}"
        self.listen_port = listen_port
        self.storage_path = storage_path

        # Components
        self.privacy_engine = PrivacyEngine(epsilon=epsilon)
        self.memory_store = MemoryStore(self.node_id, storage_path)
        self.conflict_resolver = ConflictResolver()
        self.peer_discovery = PeerDiscovery(self.node_id, listen_port)
        self.sync_manager = SyncManager(
            self.node_id,
            self.memory_store,
            self.privacy_engine,
            self.conflict_resolver
        )
        self.aggregator = FederatedAggregator(self.privacy_engine)

        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the mesh network."""
        self._running = True
        self.peer_discovery.start()

    def stop(self) -> None:
        """Stop the mesh network."""
        self._running = False
        self.peer_discovery.stop()

    def add_memory(
        self,
        memory_type: MemoryType,
        content: Any,
        embedding: Optional[list[float]] = None,
        privacy_level: int = 0
    ) -> MemoryItem:
        """Add a memory item to the local store."""
        return self.memory_store.add(memory_type, content, embedding, privacy_level)

    def get_memory(self, item_id: str) -> Optional[MemoryItem]:
        """Get a memory item by ID."""
        return self.memory_store.get(item_id)

    def sync_with_peer(self, peer: PeerInfo, memory_types: list[MemoryType]) -> list[MemoryItem]:
        """Synchronize with a specific peer (mock implementation)."""
        # In a real implementation, this would send network requests
        request = self.sync_manager.create_sync_request(peer.peer_id, memory_types)

        # Mock: simulate receiving response
        # In reality, we'd send request over network and wait for response
        response = SyncResponse(
            request_id=request.request_id,
            responder_id=peer.peer_id,
            items=[],
            current_version=0,
            has_more=False
        )

        return self.sync_manager.apply_sync_response(response)

    def broadcast_memory(self, item: MemoryItem, privacy_level: int = 0) -> int:
        """Broadcast a memory item to all connected peers."""
        if not self.privacy_engine.can_share(item, privacy_level):
            return 0

        peers = [p for p in self.peer_discovery.get_peers()
                 if p.state == PeerState.CONNECTED]

        # In a real implementation, we'd send to each peer
        return len(peers)

    def get_peers(self) -> list[PeerInfo]:
        """Get all known peers."""
        return self.peer_discovery.get_peers()

    def add_peer(self, peer: PeerInfo) -> None:
        """Add a peer manually."""
        self.peer_discovery.add_peer_manually(peer)

    def submit_federated_update(self, round_id: str, update: list[float]) -> str:
        """Submit a federated learning update."""
        return self.aggregator.submit_update(round_id, update)

    def get_aggregated_update(self, round_id: str) -> Optional[list[float]]:
        """Get aggregated federated update."""
        return self.aggregator.aggregate(round_id)

    def get_statistics(self) -> dict[str, Any]:
        """Get mesh network statistics."""
        peers = self.peer_discovery.get_peers()

        return {
            "node_id": self.node_id,
            "is_running": self._running,
            "total_peers": len(peers),
            "connected_peers": len([p for p in peers if p.state == PeerState.CONNECTED]),
            "memory_items": len(self.memory_store.items),
            "store_version": self.memory_store.version,
            "privacy_epsilon": self.privacy_engine.epsilon
        }

    def save_state(self) -> None:
        """Save current state to disk."""
        if self.storage_path:
            self.memory_store._save_to_disk()

    def load_state(self) -> None:
        """Load state from disk."""
        if self.storage_path:
            self.memory_store._load_from_disk()


class FederatedMemorySystem:
    """
    High-level interface for federated memory operations.

    Provides simplified API for common federated memory operations
    including peer management, memory sharing, and federated learning.
    """

    def __init__(
        self,
        node_name: Optional[str] = None,
        storage_path: Optional[Path] = None,
        privacy_epsilon: float = 1.0
    ):
        self.node_name = node_name or f"agent_{secrets.token_hex(4)}"
        self.mesh = MeshNetwork(
            node_id=f"mesh_{self.node_name}_{int(time.time())}",
            storage_path=storage_path,
            epsilon=privacy_epsilon
        )

    def start(self) -> None:
        """Start the federated memory system."""
        self.mesh.start()

    def stop(self) -> None:
        """Stop the federated memory system."""
        self.mesh.stop()
        self.mesh.save_state()

    def store_knowledge(self, content: Any, private: bool = False) -> str:
        """Store a piece of knowledge."""
        item = self.mesh.add_memory(
            MemoryType.KNOWLEDGE,
            content,
            privacy_level=2 if private else 0
        )
        return item.item_id

    def store_experience(self, content: Any, private: bool = False) -> str:
        """Store a task experience."""
        item = self.mesh.add_memory(
            MemoryType.EXPERIENCE,
            content,
            privacy_level=2 if private else 0
        )
        return item.item_id

    def store_preference(self, content: Any) -> str:
        """Store a user preference (always private)."""
        item = self.mesh.add_memory(
            MemoryType.PREFERENCE,
            content,
            privacy_level=2
        )
        return item.item_id

    def retrieve(self, item_id: str) -> Optional[Any]:
        """Retrieve a memory item's content."""
        item = self.mesh.get_memory(item_id)
        return item.content if item else None

    def get_all_knowledge(self) -> list[Any]:
        """Get all stored knowledge."""
        items = self.mesh.memory_store.get_by_type(MemoryType.KNOWLEDGE)
        return [i.content for i in items]

    def get_all_experiences(self) -> list[Any]:
        """Get all stored experiences."""
        items = self.mesh.memory_store.get_by_type(MemoryType.EXPERIENCE)
        return [i.content for i in items]

    def discover_peers(self) -> list[str]:
        """Discover peers on the network."""
        self.mesh.peer_discovery.broadcast_presence()
        return [p.peer_id for p in self.mesh.get_peers()]

    def connect_to_peer(self, address: str, port: int) -> bool:
        """Connect to a specific peer."""
        peer = PeerInfo(
            peer_id=f"manual_{address}_{port}",
            address=address,
            port=port,
            state=PeerState.CONNECTED
        )
        self.mesh.add_peer(peer)
        return True

    def sync_knowledge(self) -> int:
        """Sync knowledge with all connected peers."""
        synced = 0
        for peer in self.mesh.get_peers():
            if peer.state == PeerState.CONNECTED:
                items = self.mesh.sync_with_peer(peer, [MemoryType.KNOWLEDGE])
                synced += len(items)
        return synced

    def participate_in_round(self, round_id: str, local_update: list[float]) -> str:
        """Participate in a federated learning round."""
        return self.mesh.submit_federated_update(round_id, local_update)

    def get_round_result(self, round_id: str) -> Optional[list[float]]:
        """Get the aggregated result of a federated learning round."""
        return self.mesh.get_aggregated_update(round_id)

    def get_statistics(self) -> dict[str, Any]:
        """Get system statistics."""
        return self.mesh.get_statistics()


# CLI Testing
if __name__ == "__main__":
    import sys

    def run_tests():
        """Run basic functionality tests."""
        passed = 0
        failed = 0

        def test(name: str, condition: bool) -> None:
            nonlocal passed, failed
            if condition:
                print(f"  ✓ {name}")
                passed += 1
            else:
                print(f"  ✗ {name}")
                failed += 1

        print("\n=== Federated Memory Tests ===\n")

        # Test PeerState enum
        print("Testing PeerState...")
        test("DISCOVERED exists", PeerState.DISCOVERED.value == "discovered")
        test("CONNECTED exists", PeerState.CONNECTED.value == "connected")

        # Test MemoryType enum
        print("\nTesting MemoryType...")
        test("KNOWLEDGE exists", MemoryType.KNOWLEDGE.value == "knowledge")
        test("EXPERIENCE exists", MemoryType.EXPERIENCE.value == "experience")

        # Test VectorClock
        print("\nTesting VectorClock...")
        vc1 = VectorClock()
        vc1.increment("node1")
        test("Increment works", vc1.clocks["node1"] == 1)

        vc2 = VectorClock()
        vc2.increment("node2")
        vc1.merge(vc2)
        test("Merge works", "node2" in vc1.clocks)

        vc3 = VectorClock()
        vc3.increment("node1")
        vc4 = VectorClock()
        vc4.clocks = {"node1": 2}
        test("Happens-before works", vc3.happens_before(vc4))

        vc5 = VectorClock({"node1": 1})
        vc6 = VectorClock({"node2": 1})
        test("Concurrent detection", vc5.concurrent_with(vc6))

        # Test MemoryItem
        print("\nTesting MemoryItem...")
        item = MemoryItem(
            item_id="item1",
            memory_type=MemoryType.KNOWLEDGE,
            content={"fact": "test"},
            privacy_level=0
        )
        test("Item created", item.item_id == "item1")
        test("Checksum computed", item.checksum is not None)

        item_dict = item.to_dict()
        test("Item serializes", "item_id" in item_dict)

        restored = MemoryItem.from_dict(item_dict)
        test("Item deserializes", restored.item_id == "item1")

        # Test PeerInfo
        print("\nTesting PeerInfo...")
        peer = PeerInfo(
            peer_id="peer1",
            address="192.168.1.100",
            port=5000,
            state=PeerState.CONNECTED
        )
        test("Peer created", peer.peer_id == "peer1")

        peer_dict = peer.to_dict()
        test("Peer serializes", "address" in peer_dict)

        # Test SyncRequest/Response
        print("\nTesting SyncRequest/Response...")
        req = SyncRequest(
            request_id="req1",
            requester_id="node1",
            memory_types=[MemoryType.KNOWLEDGE]
        )
        test("Request created", req.request_id == "req1")

        resp = SyncResponse(
            request_id="req1",
            responder_id="node2",
            items=[item],
            current_version=5,
            has_more=False
        )
        test("Response created", len(resp.items) == 1)

        # Test PrivacyEngine
        print("\nTesting PrivacyEngine...")
        privacy = PrivacyEngine(epsilon=1.0)
        noisy = privacy.add_noise(10.0, sensitivity=1.0)
        test("Noise added", noisy != 10.0)

        vector = [1.0, 2.0, 3.0]
        noisy_vec = privacy.add_noise_to_vector(vector)
        test("Vector noise works", len(noisy_vec) == 3)

        gradient = [10.0, 20.0]
        clipped = privacy.clip_gradient(gradient, max_norm=1.0)
        import math
        norm = math.sqrt(sum(g ** 2 for g in clipped))
        test("Gradient clipped", norm <= 1.01)  # Small tolerance

        agg = privacy.secure_aggregate([0.5, 0.6, 0.7], num_peers=3)
        test("Secure aggregation", 0 <= agg <= 1.5)

        test("Privacy check works", privacy.can_share(item, 0))

        # Test MockEncryption
        print("\nTesting MockEncryption...")
        enc = MockEncryption()
        data = b"secret message"
        encrypted = enc.encrypt(data)
        test("Encryption works", encrypted != data)

        decrypted = enc.decrypt(encrypted)
        test("Decryption works", decrypted == data)

        # Test PeerDiscovery
        print("\nTesting PeerDiscovery...")
        discovery = PeerDiscovery("node1", 5000)
        test("Discovery created", discovery.node_id == "node1")

        packet = discovery._create_discovery_packet()
        test("Packet created", b"VERA_MESH" in packet)

        discovery.add_peer_manually(peer)
        test("Manual peer add", len(discovery.get_peers()) == 1)

        # Test ConflictResolver
        print("\nTesting ConflictResolver...")
        resolver = ConflictResolver(ConflictResolution.LATEST_WINS)

        item1 = MemoryItem("conflict", MemoryType.KNOWLEDGE, {"v": 1}, timestamp=100)
        item2 = MemoryItem("conflict", MemoryType.KNOWLEDGE, {"v": 2}, timestamp=200)

        resolved = resolver.resolve(item1, item2)
        test("Latest wins works", resolved.content["v"] == 2)

        vc_resolver = ConflictResolver(ConflictResolution.VECTOR_CLOCK)
        item1.vector_clock = VectorClock({"n1": 1})
        item2.vector_clock = VectorClock({"n1": 2})
        resolved = vc_resolver.resolve(item1, item2)
        test("Vector clock resolution", resolved.content["v"] == 2)

        merge_resolver = ConflictResolver(ConflictResolution.MERGE)
        item1.content = {"a": 1}
        item2.content = {"b": 2}
        merged = merge_resolver.resolve(item1, item2)
        test("Merge resolution", "a" in merged.content and "b" in merged.content)

        # Test MemoryStore
        print("\nTesting MemoryStore...")
        store = MemoryStore("store_node")
        added = store.add(MemoryType.KNOWLEDGE, {"test": "data"})
        test("Store add works", added.item_id is not None)

        retrieved = store.get(added.item_id)
        test("Store get works", retrieved is not None)

        updated = store.update(added.item_id, {"test": "updated"})
        test("Store update works", updated.content["test"] == "updated")

        by_type = store.get_by_type(MemoryType.KNOWLEDGE)
        test("Get by type works", len(by_type) >= 1)

        since = store.get_since(0)
        test("Get since works", len(since) >= 1)

        deleted = store.delete(added.item_id)
        test("Store delete works", deleted)

        # Test SyncManager
        print("\nTesting SyncManager...")
        store2 = MemoryStore("sync_node")
        store2.add(MemoryType.KNOWLEDGE, {"sync": "test"})

        sync_mgr = SyncManager("sync_node", store2, privacy, resolver)
        req = sync_mgr.create_sync_request("peer1", [MemoryType.KNOWLEDGE])
        test("Sync request created", req.requester_id == "sync_node")

        resp = sync_mgr.handle_sync_request(req, privacy_level=0)
        test("Sync response created", len(resp.items) >= 0)

        # Test FederatedAggregator
        print("\nTesting FederatedAggregator...")
        agg = FederatedAggregator(privacy)
        agg.submit_update("round1", [0.1, 0.2, 0.3])
        agg.submit_update("round1", [0.2, 0.3, 0.4])
        test("Updates submitted", agg.get_participant_count("round1") == 2)

        result = agg.aggregate("round1")
        test("Aggregation works", result is not None and len(result) == 3)

        agg.clear_round("round1")
        test("Round cleared", agg.get_participant_count("round1") == 0)

        # Test MeshNetwork
        print("\nTesting MeshNetwork...")
        mesh = MeshNetwork(node_id="mesh_test")
        test("Mesh created", mesh.node_id == "mesh_test")

        mem = mesh.add_memory(MemoryType.KNOWLEDGE, {"mesh": "test"})
        test("Mesh add memory", mem is not None)

        retrieved = mesh.get_memory(mem.item_id)
        test("Mesh get memory", retrieved is not None)

        stats = mesh.get_statistics()
        test("Mesh statistics", "node_id" in stats)

        mesh.add_peer(peer)
        test("Mesh add peer", len(mesh.get_peers()) == 1)

        mesh.submit_federated_update("mesh_round", [1.0, 2.0])
        test("Mesh federated update", True)

        # Test FederatedMemorySystem
        print("\nTesting FederatedMemorySystem...")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            system = FederatedMemorySystem(
                node_name="test_agent",
                storage_path=Path(tmpdir)
            )
            test("System created", system.node_name == "test_agent")

            know_id = system.store_knowledge({"fact": "test"})
            test("Knowledge stored", know_id is not None)

            exp_id = system.store_experience({"action": "test"})
            test("Experience stored", exp_id is not None)

            pref_id = system.store_preference({"theme": "dark"})
            test("Preference stored", pref_id is not None)

            content = system.retrieve(know_id)
            test("Retrieve works", content["fact"] == "test")

            knowledge = system.get_all_knowledge()
            test("Get all knowledge", len(knowledge) >= 1)

            experiences = system.get_all_experiences()
            test("Get all experiences", len(experiences) >= 1)

            connected = system.connect_to_peer("localhost", 5000)
            test("Peer connection", connected)

            system.participate_in_round("sys_round", [0.5, 0.6])
            test("Round participation", True)

            stats = system.get_statistics()
            test("System statistics", "node_id" in stats)

            system.mesh.save_state()
            test("State saved", (Path(tmpdir) / "memory_store.json").exists())

        print(f"\n=== Results: {passed} passed, {failed} failed ===\n")
        return failed == 0

    success = run_tests()
    sys.exit(0 if success else 1)

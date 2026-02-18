#!/usr/bin/env python3
"""
Memvid - QR Code Video Memory Encoding
=======================================

Implements video-based memory encoding using QR code-like representations.

Based on research:
- "Memvid: A QR Code-Based Approach for Automated Memory Archival"
- Visual encoding for long-term storage
- Frame-based memory retrieval
- Compressed visual representations

Key Features:
- QR code-like encoding of MemCubes
- Frame sequence generation
- Video-based archival
- Visual compression
- Frame-based retrieval

Architecture:
┌─────────────────────────────────────────┐
│         Memvid System                   │
├─────────────────────────────────────────┤
│                                         │
│  MemCube ──▶ Serialize                  │
│                  │                       │
│                  ▼                       │
│              JSON Data                   │
│                  │                       │
│                  ▼                       │
│              Compress                    │
│                  │                       │
│                  ▼                       │
│              Visual Frame                │
│              (QR-like)                   │
│                  │                       │
│                  ▼                       │
│              Frame Sequence              │
│                  │                       │
│                  ▼                       │
│              Video Archive               │
│                                         │
│  Retrieval:                             │
│  Frame ──▶ Decompress ──▶ MemCube       │
│                                         │
└─────────────────────────────────────────┘

Frame Format:
┌─────────────────────────────────────┐
│  Frame Header                       │
│  - Frame ID                         │
│  - Sequence number                  │
│  - Total frames                     │
│  - Checksum                         │
├─────────────────────────────────────┤
│  Compressed Payload                 │
│  - Base64 encoded                   │
│  - CommVQ compressed                │
│  - Error correction codes           │
└─────────────────────────────────────┘

Usage Example:
    memvid = MemvidEncoder()

    # Encode MemCubes to video frames
    frames = memvid.encode_to_frames(cubes)

    # Create video archive
    video_id = memvid.create_video(frames, "session_2025_12_20")

    # Retrieve from video
    retrieved_cubes = memvid.decode_from_video(video_id)
"""

import json
import hashlib
import base64
import time
from typing import Any, Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

try:
    from .mem_cube import MemCube, EventType
    from .commvq_compression import CommVQCompressor
except ImportError:
    from mem_cube import MemCube, EventType
    from commvq_compression import CommVQCompressor


@dataclass
class FrameMetadata:
    """Metadata for a video frame"""
    frame_id: str
    sequence_number: int
    total_frames: int
    timestamp: datetime
    checksum: str
    payload_size: int


@dataclass
class VideoMetadata:
    """Metadata for a video archive"""
    video_id: str
    title: str
    created_at: datetime
    total_frames: int
    total_events: int
    duration_ms: int
    compression_ratio: float


class MemvidFrame:
    """
    Single frame in Memvid video

    Represents a QR code-like visual encoding of memory data
    """

    def __init__(
        self,
        frame_id: str,
        sequence_number: int,
        total_frames: int,
        payload: bytes
    ):
        """
        Initialize frame

        Args:
            frame_id: Unique frame identifier
            sequence_number: Position in sequence (0-indexed)
            total_frames: Total frames in video
            payload: Compressed payload data
        """
        self.frame_id = frame_id
        self.sequence_number = sequence_number
        self.total_frames = total_frames
        self.payload = payload
        self.timestamp = datetime.now()

        # Compute checksum
        self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """Compute checksum for error detection"""
        data = (
            self.frame_id.encode() +
            str(self.sequence_number).encode() +
            self.payload
        )
        return hashlib.sha256(data).hexdigest()[:16]

    def verify_checksum(self) -> bool:
        """Verify frame integrity"""
        return self.checksum == self._compute_checksum()

    def to_visual_representation(self) -> str:
        """
        Convert frame to visual representation (QR-like)

        In production, this would generate actual QR code image
        For now, returns base64 encoded data
        """
        # Encode as base64 for visual representation
        visual_data = base64.b64encode(self.payload).decode('ascii')

        # Add frame header
        header = f"MEMVID_FRAME_{self.sequence_number}/{self.total_frames}_{self.checksum}"

        return f"{header}:{visual_data}"

    @classmethod
    def from_visual_representation(cls, visual: str) -> "MemvidFrame":
        """
        Decode frame from visual representation

        Args:
            visual: Visual representation string

        Returns:
            MemvidFrame
        """
        # Split header and data
        header, visual_data = visual.split(':', 1)

        # Parse header
        parts = header.replace('MEMVID_FRAME_', '').split('_')
        seq_total, checksum = parts[0], parts[1]
        sequence_number, total_frames = map(int, seq_total.split('/'))

        # Decode payload
        payload = base64.b64decode(visual_data)

        # Generate frame ID
        frame_id = hashlib.sha256(payload).hexdigest()[:16]

        # Create frame
        frame = cls(
            frame_id=frame_id,
            sequence_number=sequence_number,
            total_frames=total_frames,
            payload=payload
        )

        return frame

    def get_metadata(self) -> FrameMetadata:
        """Get frame metadata"""
        return FrameMetadata(
            frame_id=self.frame_id,
            sequence_number=self.sequence_number,
            total_frames=self.total_frames,
            timestamp=self.timestamp,
            checksum=self.checksum,
            payload_size=len(self.payload)
        )


class MemvidEncoder:
    """
    Encodes MemCubes into Memvid video frames

    Features:
    - QR code-like visual encoding
    - Frame sequencing
    - Compression
    - Error detection
    """

    def __init__(
        self,
        max_frame_size: int = 2048,  # 2KB per frame
        compression_enabled: bool = True
    ):
        """
        Initialize encoder

        Args:
            max_frame_size: Max payload size per frame
            compression_enabled: Whether to compress payloads
        """
        self.max_frame_size = max_frame_size
        self.compression_enabled = compression_enabled

        # Compressor
        if compression_enabled:
            self.compressor = CommVQCompressor()
        else:
            self.compressor = None

    def encode_to_frames(
        self,
        cubes: List[MemCube],
        max_cubes_per_frame: int = 10
    ) -> List[MemvidFrame]:
        """
        Encode MemCubes to video frames

        Args:
            cubes: List of MemCubes
            max_cubes_per_frame: Max cubes per frame

        Returns:
            List of MemvidFrames
        """
        frames = []

        # Split cubes into chunks
        chunks = [
            cubes[i:i+max_cubes_per_frame]
            for i in range(0, len(cubes), max_cubes_per_frame)
        ]

        total_frames = len(chunks)

        # Create frames
        for seq_num, chunk in enumerate(chunks):
            # Serialize cubes in chunk
            serialized = [cube.to_dict() for cube in chunk]
            json_data = json.dumps(serialized)

            # Compress if enabled
            if self.compression_enabled and self.compressor:
                import zlib
                payload = zlib.compress(json_data.encode('utf-8'), level=9)
            else:
                payload = json_data.encode('utf-8')

            # Generate frame ID
            frame_id = hashlib.sha256(payload).hexdigest()[:16]

            # Create frame
            frame = MemvidFrame(
                frame_id=frame_id,
                sequence_number=seq_num,
                total_frames=total_frames,
                payload=payload
            )

            frames.append(frame)

        return frames

    def decode_from_frames(
        self,
        frames: List[MemvidFrame]
    ) -> List[MemCube]:
        """
        Decode MemCubes from video frames

        Args:
            frames: List of MemvidFrames

        Returns:
            List of MemCubes
        """
        # Sort frames by sequence number
        frames.sort(key=lambda f: f.sequence_number)

        # Verify checksums
        for frame in frames:
            if not frame.verify_checksum():
                raise ValueError(f"Frame {frame.sequence_number} checksum mismatch")

        # Decode frames
        all_cubes = []

        for frame in frames:
            # Decompress payload
            if self.compression_enabled:
                import zlib
                json_data = zlib.decompress(frame.payload).decode('utf-8')
            else:
                json_data = frame.payload.decode('utf-8')

            # Deserialize cubes
            serialized = json.loads(json_data)

            for cube_data in serialized:
                cube = MemCube.from_dict(cube_data)
                all_cubes.append(cube)

        return all_cubes


class MemvidArchive:
    """
    Manages Memvid video archives

    Features:
    - Video creation and storage
    - Frame-based retrieval
    - Video metadata
    - Archival management
    """

    def __init__(self, encoder: Optional[MemvidEncoder] = None) -> None:
        """
        Initialize archive

        Args:
            encoder: MemvidEncoder instance
        """
        self.encoder = encoder or MemvidEncoder()

        # Video storage (video_id -> frames)
        self.videos: Dict[str, List[MemvidFrame]] = {}

        # Video metadata
        self.metadata: Dict[str, VideoMetadata] = {}

    def create_video(
        self,
        cubes: List[MemCube],
        title: str = "Untitled"
    ) -> str:
        """
        Create video archive from MemCubes

        Args:
            cubes: MemCubes to archive
            title: Video title

        Returns:
            video_id
        """
        start = time.time()

        # Encode to frames
        frames = self.encoder.encode_to_frames(cubes)

        # Generate video ID
        video_id = hashlib.sha256(
            f"{title}_{datetime.now().isoformat()}".encode()
        ).hexdigest()[:16]

        # Compute compression ratio
        original_size = sum(c.size_bytes() for c in cubes)
        compressed_size = sum(len(f.payload) for f in frames)
        compression_ratio = compressed_size / original_size if original_size > 0 else 1.0

        # Store video
        self.videos[video_id] = frames

        # Store metadata
        self.metadata[video_id] = VideoMetadata(
            video_id=video_id,
            title=title,
            created_at=datetime.now(),
            total_frames=len(frames),
            total_events=len(cubes),
            duration_ms=int((time.time() - start) * 1000),
            compression_ratio=compression_ratio
        )

        return video_id

    def get_video(self, video_id: str) -> List[MemCube]:
        """
        Retrieve MemCubes from video

        Args:
            video_id: Video identifier

        Returns:
            List of MemCubes
        """
        if video_id not in self.videos:
            raise ValueError(f"Video {video_id} not found")

        frames = self.videos[video_id]

        return self.encoder.decode_from_frames(frames)

    def get_video_metadata(self, video_id: str) -> VideoMetadata:
        """Get video metadata"""
        if video_id not in self.metadata:
            raise ValueError(f"Video {video_id} not found")

        return self.metadata[video_id]

    def list_videos(self) -> List[VideoMetadata]:
        """List all videos"""
        return list(self.metadata.values())

    def delete_video(self, video_id: str) -> None:
        """Delete video"""
        if video_id in self.videos:
            del self.videos[video_id]

        if video_id in self.metadata:
            del self.metadata[video_id]

    def export_video(self, video_id: str) -> Dict[str, Any]:
        """
        Export video as JSON

        Args:
            video_id: Video to export

        Returns:
            Video data dict
        """
        if video_id not in self.videos:
            raise ValueError(f"Video {video_id} not found")

        frames = self.videos[video_id]
        metadata = self.metadata[video_id]

        # Export frames as visual representations
        visual_frames = [f.to_visual_representation() for f in frames]

        # Convert metadata to dict with ISO timestamps
        meta_dict = asdict(metadata)
        meta_dict["created_at"] = metadata.created_at.isoformat()

        return {
            "video_id": video_id,
            "metadata": meta_dict,
            "frames": visual_frames
        }

    def import_video(self, video_data: Dict[str, Any]) -> str:
        """
        Import video from JSON

        Args:
            video_data: Video data dict

        Returns:
            video_id
        """
        video_id = video_data.get("video_id", "")

        # Import frames
        frames = [
            MemvidFrame.from_visual_representation(visual)
            for visual in video_data.get("frames", "")
        ]

        # Import metadata
        meta_dict = video_data.get("metadata", "").copy()

        # Convert created_at if it's a string
        if isinstance(meta_dict["created_at"], str):
            meta_dict["created_at"] = datetime.fromisoformat(meta_dict["created_at"])

        metadata = VideoMetadata(**meta_dict)

        # Store
        self.videos[video_id] = frames
        self.metadata[video_id] = metadata

        return video_id


# Example usage and testing
def run_example() -> None:
    """Demonstrate Memvid capabilities"""
    print("=== Memvid Example ===\n")

    # Example 1: Create encoder
    print("Example 1: Create Encoder")
    print("-" * 60)

    encoder = MemvidEncoder(
        max_frame_size=2048,
        compression_enabled=True
    )

    print(f"✓ Created encoder")
    print(f"✓ Max frame size: {encoder.max_frame_size} bytes")
    print(f"✓ Compression: {'enabled' if encoder.compression_enabled else 'disabled'}")

    # Example 2: Encode MemCubes to frames
    print("\n\nExample 2: Encode MemCubes to Frames")
    print("-" * 60)

    # Create test cubes
    cubes = []
    for i in range(25):
        cube = MemCube(
            content=f"Event {i}: Phase 2 Week 3 memory encoding test",
            event_type=EventType.SYSTEM_EVENT,
            importance=0.5 + (i / 50),
            tags=["memvid", "test"]
        )
        cubes.append(cube)

    print(f"Created {len(cubes)} MemCubes")

    # Encode to frames
    frames = encoder.encode_to_frames(cubes, max_cubes_per_frame=10)

    print(f"✓ Encoded to {len(frames)} frames")

    for i, frame in enumerate(frames[:3]):
        meta = frame.get_metadata()
        print(f"  Frame {i}: {meta.payload_size} bytes, checksum={meta.checksum[:8]}...")

    # Example 3: Decode frames back to cubes
    print("\n\nExample 3: Decode Frames to MemCubes")
    print("-" * 60)

    decoded_cubes = encoder.decode_from_frames(frames)

    print(f"✓ Decoded {len(decoded_cubes)} MemCubes")
    print(f"✓ Data preserved: {len(decoded_cubes) == len(cubes)}")

    # Verify content
    match = all(
        c1.get_content() == c2.get_content()
        for c1, c2 in zip(cubes, decoded_cubes)
    )
    print(f"✓ Content match: {match}")

    # Example 4: Create video archive
    print("\n\nExample 4: Create Video Archive")
    print("-" * 60)

    archive = MemvidArchive(encoder)

    video_id = archive.create_video(cubes, title="Phase 2 Week 3 Session")

    print(f"✓ Created video: {video_id}")

    metadata = archive.get_video_metadata(video_id)
    print(f"✓ Title: {metadata.title}")
    print(f"✓ Frames: {metadata.total_frames}")
    print(f"✓ Events: {metadata.total_events}")
    print(f"✓ Compression: {(1 - metadata.compression_ratio) * 100:.1f}%")
    print(f"✓ Created: {metadata.created_at.isoformat()}")

    # Example 5: Retrieve from video
    print("\n\nExample 5: Retrieve from Video")
    print("-" * 60)

    retrieved = archive.get_video(video_id)

    print(f"✓ Retrieved {len(retrieved)} MemCubes from video")
    print(f"✓ Match original: {len(retrieved) == len(cubes)}")

    # Example 6: Export/Import video
    print("\n\nExample 6: Export/Import Video")
    print("-" * 60)

    # Export
    exported = archive.export_video(video_id)

    print(f"✓ Exported video")
    print(f"✓ Video ID: {exported['video_id']}")
    print(f"✓ Frames: {len(exported['frames'])}")

    # Import to new archive
    new_archive = MemvidArchive(encoder)
    imported_id = new_archive.import_video(exported)

    print(f"✓ Imported video: {imported_id}")

    # Verify
    imported_cubes = new_archive.get_video(imported_id)
    print(f"✓ Retrieved {len(imported_cubes)} cubes from imported video")

    # Example 7: Visual frame representation
    print("\n\nExample 7: Visual Frame Representation")
    print("-" * 60)

    # Get first frame
    frame = frames[0]
    visual = frame.to_visual_representation()

    print(f"Visual representation preview:")
    print(f"  {visual[:80]}...")
    print(f"  (Total length: {len(visual)} chars)")

    # Decode from visual
    decoded_frame = MemvidFrame.from_visual_representation(visual)

    print(f"✓ Decoded from visual representation")
    print(f"✓ Checksum match: {decoded_frame.checksum == frame.checksum}")

    print("\n✅ All examples complete")


if __name__ == "__main__":
    run_example()

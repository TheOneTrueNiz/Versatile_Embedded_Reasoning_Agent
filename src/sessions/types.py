"""
Session Types
==============

Data types for the session management system.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class SessionScope(Enum):
    """How conversations are scoped."""
    PER_SENDER = "per_sender"     # Each user gets their own session
    PER_CHANNEL = "per_channel"   # Each channel gets one session
    GLOBAL = "global"             # One session for everything


@dataclass
class SessionEntry:
    """A conversation session with metadata.

    Tracks the state of a conversation between VERA and a user/channel,
    including message history path, timestamps, and routing context.
    """
    session_id: str
    session_key: str
    channel_id: str
    sender_id: str
    created_at: float = field(default_factory=time.time)
    last_active_at: float = field(default_factory=time.time)
    transcript_path: Optional[str] = None
    message_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    # Delivery routing context (last successful delivery)
    last_channel_id: Optional[str] = None
    last_target_id: Optional[str] = None
    last_thread_id: Optional[str] = None

    # Per-session overrides
    model_override: Optional[str] = None

    # Arbitrary metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded default TTL (1 hour)."""
        return (time.time() - self.last_active_at) > 3600

    def touch(self) -> None:
        """Update last_active timestamp."""
        self.last_active_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for persistence."""
        return {
            "session_id": self.session_id,
            "session_key": self.session_key,
            "channel_id": self.channel_id,
            "sender_id": self.sender_id,
            "created_at": self.created_at,
            "last_active_at": self.last_active_at,
            "transcript_path": self.transcript_path,
            "message_count": self.message_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "last_channel_id": self.last_channel_id,
            "last_target_id": self.last_target_id,
            "last_thread_id": self.last_thread_id,
            "model_override": self.model_override,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionEntry":
        """Deserialize from dict."""
        return cls(
            session_id=data.get("session_id", ""),
            session_key=data.get("session_key", ""),
            channel_id=data.get("channel_id", ""),
            sender_id=data.get("sender_id", ""),
            created_at=data.get("created_at", time.time()),
            last_active_at=data.get("last_active_at", time.time()),
            transcript_path=data.get("transcript_path"),
            message_count=data.get("message_count", 0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            last_channel_id=data.get("last_channel_id"),
            last_target_id=data.get("last_target_id"),
            last_thread_id=data.get("last_thread_id"),
            model_override=data.get("model_override"),
            metadata=data.get("metadata", {}),
        )

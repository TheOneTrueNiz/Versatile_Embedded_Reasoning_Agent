"""
Session Store
==============

In-memory session store with JSONL transcript persistence and TTL expiry.
Ported from Moltbot's session store pattern with file-based persistence.
"""

import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory.persistence.atomic_io import atomic_json_write, safe_json_read
from sessions.types import SessionEntry, SessionScope
from sessions.transcript import (
    append_to_transcript,
    build_transcript_entry,
    read_transcript,
    transcript_to_messages,
)

logger = logging.getLogger(__name__)


class SessionStore:
    """In-memory session store with JSONL transcript persistence.

    Manages conversation sessions keyed by session_key (channel:sender).
    Each session has an associated JSONL transcript file for persistence.

    Features:
    - TTL-based session expiry
    - Per-session conversation history
    - JSONL transcript persistence
    - Session metadata tracking
    """

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        ttl_seconds: int = 3600,
        max_history: int = 50,
        scope: SessionScope = SessionScope.PER_SENDER,
    ):
        self._storage_dir = storage_dir or Path("vera_memory/transcripts")
        self._ttl = ttl_seconds
        self._max_history = max_history
        self._scope = scope
        self._sessions: Dict[str, SessionEntry] = {}
        self._session_aliases: Dict[str, str] = {}
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._storage_dir / "session_index.json"
        self._load_index()

    def resolve_session_key(self, session_key: str) -> str:
        """Resolve a key through alias links to its canonical key."""
        key = str(session_key or "").strip()
        if not key:
            return ""

        visited: List[str] = []
        current = key
        while current in self._session_aliases:
            target = str(self._session_aliases.get(current) or "").strip()
            if not target:
                break
            if target == current or target in visited:
                logger.warning("Session alias cycle detected for key=%s", key)
                break
            visited.append(current)
            current = target

        # Path compression keeps alias lookups fast.
        for alias in visited:
            self._session_aliases[alias] = current
        return current

    def link_session_keys(self, canonical_key: str, *alias_keys: str) -> str:
        """Map one or more alias keys to a canonical key."""
        canonical_raw = str(canonical_key or "").strip()
        if not canonical_raw:
            return ""

        canonical = self.resolve_session_key(canonical_raw)
        if canonical not in self._sessions:
            for alias in alias_keys:
                alias_key = self.resolve_session_key(str(alias or "").strip())
                if alias_key and alias_key in self._sessions:
                    canonical = alias_key
                    break

        if canonical != canonical_raw:
            self._session_aliases[canonical_raw] = canonical

        for alias in alias_keys:
            alias_raw = str(alias or "").strip()
            if not alias_raw or alias_raw == canonical:
                continue
            resolved_alias = self.resolve_session_key(alias_raw)
            if resolved_alias == canonical:
                self._session_aliases[alias_raw] = canonical
                continue
            if resolved_alias and resolved_alias != alias_raw:
                self._session_aliases[resolved_alias] = canonical
            self._session_aliases[alias_raw] = canonical

        self._save_index()
        return canonical

    def aliases_for(self, session_key: str) -> List[str]:
        """Return aliases currently mapped to the canonical session key."""
        canonical = self.resolve_session_key(session_key)
        if not canonical:
            return []
        aliases = [
            alias
            for alias, target in self._session_aliases.items()
            if alias != canonical and self.resolve_session_key(target) == canonical
        ]
        return sorted(set(aliases))

    def get_or_create(
        self,
        session_key: str,
        channel_id: str = "",
        sender_id: str = "",
    ) -> SessionEntry:
        """Get an existing session or create a new one.

        If the session exists but is expired, creates a fresh one
        (the transcript file is preserved for history).
        """
        requested_key = str(session_key or "").strip()
        canonical_key = self.resolve_session_key(requested_key) or requested_key
        existing = self._sessions.get(canonical_key)

        if existing and not self._is_expired(existing):
            existing.touch()
            if requested_key and requested_key != canonical_key:
                if self._session_aliases.get(requested_key) != canonical_key:
                    self._session_aliases[requested_key] = canonical_key
                    self._save_index()
            return existing

        # Create new session
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        transcript_path = str(
            self._storage_dir / f"{self._sanitize_key(canonical_key)}.jsonl"
        )

        session = SessionEntry(
            session_id=session_id,
            session_key=canonical_key,
            channel_id=channel_id,
            sender_id=sender_id,
            transcript_path=transcript_path,
        )

        self._sessions[canonical_key] = session
        if requested_key and requested_key != canonical_key:
            self._session_aliases[requested_key] = canonical_key
        self._save_index()
        logger.debug(f"Session created: {canonical_key} -> {session_id}")
        return session

    def get(self, session_key: str) -> Optional[SessionEntry]:
        """Get a session by key, or None if not found/expired."""
        canonical_key = self.resolve_session_key(session_key)
        session = self._sessions.get(canonical_key)
        if session and not self._is_expired(session):
            return session
        return None

    def get_history(
        self,
        session_key: str,
        max_messages: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Get conversation history for a session as OpenAI-format messages.

        Reads from the JSONL transcript file and converts to message format.
        """
        canonical_key = self.resolve_session_key(session_key)
        session = self._sessions.get(canonical_key)
        if not session or not session.transcript_path:
            return []

        path = Path(session.transcript_path)
        limit = max_messages or self._max_history
        entries = read_transcript(path, limit=limit)
        return transcript_to_messages(entries, max_messages=limit)

    async def record_message(
        self,
        session_key: str,
        role: str,
        content: str,
        **kwargs: Any,
    ) -> None:
        """Record a message to the session transcript.

        Args:
            session_key: Session to record to
            role: Message role ("user", "assistant", "tool", "system")
            content: Message content
            **kwargs: Additional fields (tool_calls, provider_id, model, etc.)
        """
        canonical_key = self.resolve_session_key(session_key)
        session = self._sessions.get(canonical_key)
        if not session or not session.transcript_path:
            return

        session.message_count += 1
        session.touch()
        now = time.time()
        if role == "user":
            prev_user_at = session.metadata.get("last_user_at")
            if isinstance(prev_user_at, (int, float)):
                session.metadata["previous_user_at"] = prev_user_at
            session.metadata["last_user_at"] = now
        elif role == "assistant":
            session.metadata["last_assistant_at"] = now

        # Update token counts if provided
        usage = kwargs.get("usage")
        if usage:
            session.input_tokens += usage.get("prompt_tokens", 0)
            session.output_tokens += usage.get("completion_tokens", 0)

        entry = build_transcript_entry(role=role, content=content, **kwargs)
        path = Path(session.transcript_path)
        await append_to_transcript(path, entry)

    def update_delivery_context(
        self,
        session_key: str,
        channel_id: Optional[str] = None,
        target_id: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> None:
        """Update the last successful delivery routing context."""
        canonical_key = self.resolve_session_key(session_key)
        session = self._sessions.get(canonical_key)
        if not session:
            return

        if channel_id is not None:
            session.last_channel_id = channel_id
        if target_id is not None:
            session.last_target_id = target_id
        if thread_id is not None:
            session.last_thread_id = thread_id
        self._save_index()

    def set_model_override(
        self, session_key: str, model: Optional[str]
    ) -> None:
        """Set a per-session model override."""
        canonical_key = self.resolve_session_key(session_key)
        session = self._sessions.get(canonical_key)
        if session:
            session.model_override = model
            self._save_index()

    def prune_expired(self) -> int:
        """Remove expired sessions from memory. Returns count removed."""
        expired_keys = [
            key for key, session in self._sessions.items()
            if self._is_expired(session)
        ]
        for key in expired_keys:
            del self._sessions[key]
        if expired_keys:
            expired = set(expired_keys)
            self._session_aliases = {
                alias: target
                for alias, target in self._session_aliases.items()
                if alias not in expired and target not in expired
            }

        if expired_keys:
            logger.debug(f"Pruned {len(expired_keys)} expired sessions")
            self._save_index()
        return len(expired_keys)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all active sessions with summary info."""
        return [
            {
                "session_key": s.session_key,
                "session_id": s.session_id,
                "channel_id": s.channel_id,
                "sender_id": s.sender_id,
                "message_count": s.message_count,
                "last_active": s.last_active_at,
                "expired": self._is_expired(s),
                "aliases": self.aliases_for(s.session_key),
            }
            for s in self._sessions.values()
        ]

    @property
    def active_count(self) -> int:
        """Number of active (non-expired) sessions."""
        return sum(
            1 for s in self._sessions.values()
            if not self._is_expired(s)
        )

    def _is_expired(self, session: SessionEntry) -> bool:
        """Check if a session has expired based on TTL."""
        if self._ttl <= 0:
            return False
        return (time.time() - session.last_active_at) > self._ttl

    @staticmethod
    def _sanitize_key(key: str) -> str:
        """Sanitize a session key for use as a filename."""
        return key.replace(":", "_").replace("@", "_at_").replace("/", "_")

    def alias_map(self) -> Dict[str, str]:
        """Return a canonicalized alias->target mapping."""
        compact: Dict[str, str] = {}
        for alias, target in self._session_aliases.items():
            alias_key = str(alias or "").strip()
            if not alias_key:
                continue
            canonical = self.resolve_session_key(target)
            if canonical and alias_key != canonical:
                compact[alias_key] = canonical
        return compact

    def _load_index(self) -> None:
        """Load persisted session aliases and session metadata."""
        payload = safe_json_read(self._index_path, default={})
        if not isinstance(payload, dict):
            return

        raw_aliases = payload.get("aliases")
        if isinstance(raw_aliases, dict):
            for raw_alias, raw_target in raw_aliases.items():
                alias = str(raw_alias or "").strip()
                target = str(raw_target or "").strip()
                if not alias or not target or alias == target:
                    continue
                self._session_aliases[alias] = target

        raw_sessions = payload.get("sessions")
        if isinstance(raw_sessions, list):
            for item in raw_sessions:
                if not isinstance(item, dict):
                    continue
                try:
                    session = SessionEntry.from_dict(item)
                except Exception:
                    continue

                raw_key = str(session.session_key or "").strip()
                if not raw_key:
                    continue
                canonical_key = self.resolve_session_key(raw_key) or raw_key
                session.session_key = canonical_key
                if not session.transcript_path:
                    session.transcript_path = str(
                        self._storage_dir / f"{self._sanitize_key(canonical_key)}.jsonl"
                    )

                existing = self._sessions.get(canonical_key)
                if existing is None or session.last_active_at >= existing.last_active_at:
                    self._sessions[canonical_key] = session

    def _save_index(self) -> None:
        """Persist aliases and lightweight session metadata for restart continuity."""
        try:
            payload = {
                "version": 1,
                "saved_at": time.time(),
                "scope": self._scope.value,
                "ttl_seconds": self._ttl,
                "max_history": self._max_history,
                "aliases": self.alias_map(),
                "sessions": [session.to_dict() for session in self._sessions.values()],
            }
            atomic_json_write(self._index_path, payload, indent=2, sort_keys=True)
        except Exception as exc:
            logger.warning("Failed to persist session index %s: %s", self._index_path, exc)

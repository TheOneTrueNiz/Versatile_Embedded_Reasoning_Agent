"""
Speaker Memory — Persistent People Recognition with Natural Decay
=================================================================

VERA remembers who she's spoken with. Memories decay over time:
frequent interaction creates lasting memory, infrequent visitors fade.

Recognition tiers:
  KNOWN      (>0.7)  — "Hi Niz!"
  RECOGNIZED (0.4–0.7) — "Is that you, Niz?"
  VAGUE      (0.15–0.4) — "You seem familiar…"
  STRANGER   (<0.15) — "Who am I speaking to?"

Storage: vera_memory/speakers.json (atomic writes)
Journal: vera_memory/speaker_journal.ndjson (append-only interaction log)
"""

import json
import math
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Common words that should never be treated as names
_STOPWORDS = frozenset({
    "fine", "good", "great", "okay", "ok", "well", "here", "back",
    "sorry", "sure", "ready", "done", "tired", "busy", "happy",
    "sad", "excited", "confused", "lost", "home", "there", "not",
    "just", "also", "very", "really", "pretty", "quite", "still",
    "always", "never", "sometimes", "maybe", "probably", "definitely",
    "wondering", "thinking", "looking", "trying", "going", "coming",
    "leaving", "working", "having", "being", "doing", "saying",
    "asking", "telling", "writing", "reading", "using", "making",
    "getting", "taking", "giving", "finding", "feeling", "running",
    "calling", "sending", "starting", "stopping", "waiting", "helping",
    "interested", "curious", "new", "the", "your", "his", "her",
})

# Patterns that look like self-identification but aren't
_FALSE_POSITIVE_PREFIXES = (
    "i'm not", "i am not", "i'm no ", "i am no ",
    "i'm a ", "i am a ", "i'm an ", "i am an ",
    "i'm the ", "i am the ", "i'm so ", "i am so ",
    "i'm just", "i am just", "i'm very", "i am very",
    "i'm really", "i am really", "i'm pretty", "i am pretty",
    "i'm quite", "i am quite", "i'm still", "i am still",
)


class RecognitionTier(Enum):
    """How well VERA knows this speaker."""
    KNOWN = "known"
    RECOGNIZED = "recognized"
    VAGUE = "vague"
    STRANGER = "stranger"


@dataclass
class SpeakerEntry:
    """A person VERA remembers."""
    name: str
    aliases: List[str] = field(default_factory=list)
    first_seen: str = ""
    last_seen: str = ""
    interaction_count: int = 0
    conversation_count: int = 0
    peak_familiarity: float = 1.0
    notes: List[str] = field(default_factory=list)
    channel_ids: List[str] = field(default_factory=list)
    # Emotional memory — how the last conversation felt
    last_mood: str = ""
    last_emotion: str = ""
    last_sentiment_trend: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "aliases": self.aliases,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "interaction_count": self.interaction_count,
            "conversation_count": self.conversation_count,
            "peak_familiarity": self.peak_familiarity,
            "notes": self.notes[-10:],
            "channel_ids": list(set(self.channel_ids))[-10:],
            "last_mood": self.last_mood,
            "last_emotion": self.last_emotion,
            "last_sentiment_trend": self.last_sentiment_trend,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpeakerEntry":
        return cls(
            name=str(data.get("name") or ""),
            aliases=list(data.get("aliases") or []),
            first_seen=str(data.get("first_seen") or ""),
            last_seen=str(data.get("last_seen") or ""),
            interaction_count=int(data.get("interaction_count") or 0),
            conversation_count=int(data.get("conversation_count") or 0),
            peak_familiarity=float(data.get("peak_familiarity") or 1.0),
            notes=list(data.get("notes") or []),
            channel_ids=list(data.get("channel_ids") or []),
            last_mood=str(data.get("last_mood") or ""),
            last_emotion=str(data.get("last_emotion") or ""),
            last_sentiment_trend=str(data.get("last_sentiment_trend") or ""),
        )


class SpeakerMemory:
    """Persistent speaker recognition with natural memory decay."""

    def __init__(self, memory_dir: Path, half_life_hours: float = 168.0):
        self._storage_path = Path(memory_dir) / "speakers.json"
        self._journal_path = Path(memory_dir) / "speaker_journal.ndjson"
        self._speakers: Dict[str, SpeakerEntry] = {}
        self._half_life_hours = half_life_hours
        self._load()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def identify_speaker(
        self, name: str, sender_id: str, channel_id: str = "api"
    ) -> SpeakerEntry:
        """Register or refresh a speaker's identity."""
        key = self._normalize_key(sender_id)
        now_iso = datetime.now().isoformat()

        existing = self._speakers.get(key)
        if existing:
            existing.name = name
            existing.last_seen = now_iso
            existing.interaction_count += 1
            if channel_id and channel_id not in existing.channel_ids:
                existing.channel_ids.append(channel_id)
            fam = self.compute_familiarity(existing)
            if fam > existing.peak_familiarity:
                existing.peak_familiarity = fam
            self._save()
            self._journal({
                "event": "identify",
                "sender_id": sender_id,
                "name": name,
                "channel_id": channel_id,
            })
            return existing

        entry = SpeakerEntry(
            name=name,
            first_seen=now_iso,
            last_seen=now_iso,
            interaction_count=1,
            peak_familiarity=1.0,
            channel_ids=[channel_id] if channel_id else [],
        )
        self._speakers[key] = entry

        # Also index by name for cross-sender lookup
        name_key = self._normalize_key(name)
        if name_key != key and name_key not in self._speakers:
            self._speakers[name_key] = entry

        self._save()
        self._journal({
            "event": "first_identify",
            "sender_id": sender_id,
            "name": name,
            "channel_id": channel_id,
        })
        return entry

    def record_interaction(
        self, sender_id: str, channel_id: str = "api"
    ) -> None:
        """Record that a speaker interacted (even if unnamed)."""
        key = self._normalize_key(sender_id)
        entry = self._speakers.get(key)
        if not entry:
            return
        entry.last_seen = datetime.now().isoformat()
        entry.interaction_count += 1
        if channel_id and channel_id not in entry.channel_ids:
            entry.channel_ids.append(channel_id)
        fam = self.compute_familiarity(entry)
        if fam > entry.peak_familiarity:
            entry.peak_familiarity = fam
        self._save()

    def get_recognition(
        self, sender_id: str
    ) -> Tuple[RecognitionTier, Optional[SpeakerEntry], float]:
        """Determine how well VERA recognizes this speaker."""
        if not sender_id:
            return RecognitionTier.STRANGER, None, 0.0

        key = self._normalize_key(sender_id)
        entry = self._speakers.get(key)
        if not entry:
            return RecognitionTier.STRANGER, None, 0.0

        fam = self.compute_familiarity(entry)
        tier = self._tier_from_familiarity(fam)
        return tier, entry, fam

    def compute_familiarity(self, entry: SpeakerEntry) -> float:
        """Compute current familiarity (0–1) with exponential decay."""
        if not entry.last_seen:
            return 0.0
        try:
            last_seen_ts = datetime.fromisoformat(entry.last_seen).timestamp()
        except (ValueError, TypeError):
            return 0.0

        hours_elapsed = max(0.0, (time.time() - last_seen_ts) / 3600.0)
        decay_rate = math.log(2) / self._half_life_hours
        time_factor = math.exp(-decay_rate * hours_elapsed)

        # Interaction bonus: frequent contact creates lasting memory
        interaction_bonus = min(0.3, entry.interaction_count * 0.015)

        familiarity = (1.0 * time_factor) + interaction_bonus
        return round(min(1.0, max(0.0, familiarity)), 4)

    def start_conversation(self, sender_id: str) -> None:
        """Mark the start of a new conversation (for milestone tracking)."""
        key = self._normalize_key(sender_id)
        entry = self._speakers.get(key)
        if not entry:
            return
        entry.conversation_count += 1
        self._save()

    def update_emotional_context(
        self,
        sender_id: str,
        mood: str = "",
        emotion: str = "",
        sentiment_trend: str = "",
    ) -> None:
        """Store the emotional temperature of the current conversation."""
        key = self._normalize_key(sender_id)
        entry = self._speakers.get(key)
        if not entry:
            return
        if mood:
            entry.last_mood = mood
        if emotion:
            entry.last_emotion = emotion
        if sentiment_trend:
            entry.last_sentiment_trend = sentiment_trend
        self._save()

    def find_by_name(self, name: str) -> Optional[SpeakerEntry]:
        """Look up a speaker by name (case-insensitive)."""
        key = self._normalize_key(name)
        entry = self._speakers.get(key)
        if entry:
            return entry
        # Scan aliases
        for e in self._speakers.values():
            if e.name.lower() == name.lower():
                return e
            if name.lower() in [a.lower() for a in e.aliases]:
                return e
        return None

    # ------------------------------------------------------------------
    # Detection (static)
    # ------------------------------------------------------------------

    @staticmethod
    def detect_self_identification(text: str) -> Optional[str]:
        """Detect if the user is identifying themselves by name.

        Returns the detected name or None.
        Follows the scored-detection pattern from _detect_media_generation_intent.
        """
        if not text or len(text) > 500:
            return None

        # Normalize common apostrophe variants so contractions like "I'm"
        # are parsed consistently across keyboard/layout differences.
        normalized = (
            text.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u02bc", "'")
            .replace("\uff07", "'")
            .replace("\u2032", "'")
        )
        lowered = normalized.lower().strip()

        # Skip false positives: "I'm not...", "I'm a developer", etc.
        for prefix in _FALSE_POSITIVE_PREFIXES:
            if lowered.startswith(prefix):
                return None

        patterns = [
            r"\bi'm\s+([a-zA-Z]{2,20})\b",
            r"\bi am\s+([a-zA-Z]{2,20})\b",
            r"\bmy name(?:'s| is)\s+([a-zA-Z]{2,20})\b",
            r"\bthis is\s+([a-zA-Z]{2,20})\b",
            r"\bcall me\s+([a-zA-Z]{2,20})\b",
            r"\bi go by\s+([a-zA-Z]{2,20})\b",
            r"\bit's\s+([a-zA-Z]{2,20})\b(?:\s+here|\s*[.,!])",
        ]

        for pattern in patterns:
            match = re.search(pattern, normalized, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if name.lower() in _STOPWORDS:
                    continue
                if len(name) < 2 or len(name) > 20:
                    continue
                # Capitalize properly
                return name[0].upper() + name[1:]

        return None

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load speaker state from disk."""
        try:
            from memory.persistence.atomic_io import safe_json_read
            data = safe_json_read(self._storage_path, default={})
        except ImportError:
            data = self._fallback_read()

        raw_speakers = data.get("speakers", {})
        if isinstance(raw_speakers, dict):
            for key, val in raw_speakers.items():
                if isinstance(val, dict):
                    self._speakers[key] = SpeakerEntry.from_dict(val)
        logger.debug(
            "Speaker memory loaded: %d speakers from %s",
            len(self._speakers), self._storage_path,
        )

    def _save(self) -> None:
        """Persist speaker state atomically."""
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(),
            "half_life_hours": self._half_life_hours,
            "speakers": {
                key: entry.to_dict()
                for key, entry in self._speakers.items()
            },
        }
        try:
            from memory.persistence.atomic_io import atomic_json_write
            atomic_json_write(self._storage_path, payload, indent=2)
        except ImportError:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )

    def _journal(self, event: Dict[str, Any]) -> None:
        """Append interaction event to journal."""
        record = {"timestamp": datetime.now().isoformat(), **event}
        try:
            from memory.persistence.atomic_io import atomic_ndjson_append
            atomic_ndjson_append(self._journal_path, record)
        except ImportError:
            self._journal_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")

    def _fallback_read(self) -> Dict[str, Any]:
        """Read JSON without atomic_io (fallback)."""
        if not self._storage_path.exists():
            return {}
        try:
            return json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_key(value: str) -> str:
        """Normalize a sender_id or name to a consistent key."""
        return str(value or "").strip().lower()

    @staticmethod
    def _tier_from_familiarity(familiarity: float) -> RecognitionTier:
        """Map familiarity score to recognition tier."""
        if familiarity > 0.7:
            return RecognitionTier.KNOWN
        if familiarity > 0.4:
            return RecognitionTier.RECOGNIZED
        if familiarity > 0.15:
            return RecognitionTier.VAGUE
        return RecognitionTier.STRANGER

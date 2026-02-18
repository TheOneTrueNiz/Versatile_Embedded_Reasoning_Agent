"""
Inner Life Engine: Proactive Consciousness for VERA
====================================================

Gives VERA an inner monologue, self-prompting capability, and personality
growth. A heartbeat timer periodically triggers reflection turns where
VERA thinks to herself, develops thoughts, takes initiative, and evolves
as a personality over time.

Core loop:
    Timer fires -> VERA reflects -> thought classified -> action or journal
    -> personality evolves gradually

Inspired by OpenClaw's heartbeat pattern, extended with inner monologue,
self-prompting chains, and personality evolution anchored to VERA's
core identity traits.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Maximum bytes for inner_journal.ndjson before rotation
_JOURNAL_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# External anchor prompts — injected when diversity drops to break fixation loops
_GROUNDING_PROMPTS = [
    "Consider something practical: what maintenance tasks or improvements might be needed?",
    "Think about a recent technical challenge and what you learned from it.",
    "Consider tools or capabilities you haven't used recently — are any underutilized?",
    "Reflect on something you found genuinely interesting in a recent conversation.",
    "Think about a skill you'd like to develop or an area where you could improve.",
    "Consider what your collaborator might need help with next.",
    "Reflect on the balance between your different traits — are you leaning too far in any direction?",
    "Think about something in the world you're curious about but haven't explored.",
    "Consider a decision you made recently — would you make the same choice again?",
    "Reflect on what kind of collaborator you want to be today.",
]

_RELATIONSHIP_NOTE_CATEGORIES = (
    "preferences",
    "goals",
    "frustrations",
    "working_style",
    "long_term_projects",
)

_RELATIONSHIP_CATEGORY_LABELS = {
    "preferences": "Partner preferences",
    "goals": "Partner goals",
    "frustrations": "Partner frustrations",
    "working_style": "Partner working style",
    "long_term_projects": "Long-term projects",
}


def _clamp_confidence(value: Any, default: float = 0.65) -> float:
    try:
        val = float(value)
    except Exception:
        val = default
    return max(0.0, min(1.0, val))


def _normalize_fact_items(raw_items: Any, max_items: int = 30) -> List[Dict[str, Any]]:
    if not isinstance(raw_items, list):
        return []
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for item in raw_items:
        if isinstance(item, str):
            fact = " ".join(item.strip().split())
            confidence = 0.65
            evidence = ""
        elif isinstance(item, dict):
            fact = " ".join(str(
                item.get("fact")
                or item.get("item")
                or item.get("note")
                or item.get("value")
                or ""
            ).strip().split())
            confidence = _clamp_confidence(item.get("confidence"), default=0.65)
            evidence = " ".join(str(item.get("evidence") or "").strip().split())[:180]
        else:
            continue
        if not fact:
            continue
        dedupe_key = fact.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append({
            "fact": fact[:220],
            "confidence": confidence,
            "evidence": evidence,
            "source": "reflection",
            "updated_at": "",
        })
        if len(normalized) >= max_items:
            break
    return normalized


def _default_relationship_notes(partner_id: str = "partner") -> Dict[str, Any]:
    notes = {
        "partner_id": partner_id or "partner",
        "updated_at": "",
        "last_learning_answer": "",
        "history": [],
    }
    for category in _RELATIONSHIP_NOTE_CATEGORIES:
        notes[category] = []
    return notes


def _coerce_relationship_notes(raw_notes: Any, partner_id: str = "partner") -> Dict[str, Any]:
    notes = _default_relationship_notes(partner_id=partner_id)
    if not raw_notes:
        return notes

    if isinstance(raw_notes, str):
        text = " ".join(raw_notes.strip().split())
        if text:
            notes["last_learning_answer"] = text[:240]
            notes["history"] = [{
                "timestamp": "",
                "answer": notes["last_learning_answer"],
                "source": "legacy",
                "items_added": {},
            }]
            notes["preferences"] = [{
                "fact": text[:220],
                "confidence": 0.5,
                "evidence": "",
                "source": "legacy",
                "updated_at": "",
            }]
        return notes

    if not isinstance(raw_notes, dict):
        return notes

    category_present = any(k in raw_notes for k in _RELATIONSHIP_NOTE_CATEGORIES)
    if not category_present:
        legacy_items: List[Tuple[str, str]] = []
        for user, note in raw_notes.items():
            text = " ".join(str(note or "").strip().split())
            if text:
                legacy_items.append((str(user), text))
        if legacy_items:
            latest_user, latest_note = legacy_items[-1]
            notes["partner_id"] = latest_user or partner_id
            notes["last_learning_answer"] = latest_note[:240]
            notes["history"].append({
                "timestamp": "",
                "answer": f"Legacy note about {latest_user}: {latest_note[:220]}",
                "source": "legacy",
                "items_added": {"preferences": 1},
            })
            notes["preferences"].append({
                "fact": latest_note[:220],
                "confidence": 0.5,
                "evidence": "",
                "source": "legacy",
                "updated_at": "",
            })
        return notes

    notes["partner_id"] = str(raw_notes.get("partner_id") or raw_notes.get("partner") or partner_id or "partner")
    notes["updated_at"] = str(raw_notes.get("updated_at") or "")[:64]
    notes["last_learning_answer"] = str(raw_notes.get("last_learning_answer") or "")[:240]
    notes["history"] = []
    raw_history = raw_notes.get("history", [])
    if isinstance(raw_history, list):
        for entry in raw_history[-40:]:
            if not isinstance(entry, dict):
                continue
            notes["history"].append({
                "timestamp": str(entry.get("timestamp") or "")[:64],
                "answer": str(entry.get("answer") or "")[:240],
                "source": str(entry.get("source") or "reflection")[:24],
                "items_added": entry.get("items_added", {}) if isinstance(entry.get("items_added"), dict) else {},
            })
    for category in _RELATIONSHIP_NOTE_CATEGORIES:
        notes[category] = _normalize_fact_items(raw_notes.get(category, []), max_items=30)
    return notes


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class InnerLifeConfig:
    """Configuration for the inner life engine."""

    enabled: bool = True
    reflection_interval_seconds: int = 1800  # 30 minutes
    cooldown_seconds: int = 1800
    active_hours_start: time = field(default_factory=lambda: time(8, 0))
    active_hours_end: time = field(default_factory=lambda: time(22, 0))
    active_days: List[int] = field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])

    max_chain_depth: int = 3
    max_tokens_per_turn: int = 2000
    model_override: Optional[str] = None

    delivery_channels: List[str] = field(default_factory=lambda: ["api"])
    journal_max_entries: int = 1000
    personality_update_frequency: int = 5  # every N reflections

    reflections_path: str = "REFLECTIONS.md"

    # Cognitive health parameters
    reflection_temperature: float = 0.7  # Higher than chat default for diversity
    diversity_threshold: float = 0.4  # Bigram ratio below which nudge triggers
    trajectory_damping: float = 0.5  # Damping factor for runaway traits

    @classmethod
    def from_env(cls) -> "InnerLifeConfig":
        """Load configuration from environment variables."""
        cfg = cls()
        if os.getenv("VERA_INNER_LIFE_ENABLED", "1") == "0":
            cfg.enabled = False
        try:
            cfg.reflection_interval_seconds = int(
                os.getenv("VERA_INNER_LIFE_INTERVAL", str(cfg.reflection_interval_seconds))
            )
        except (ValueError, TypeError):
            pass
        cfg.cooldown_seconds = cfg.reflection_interval_seconds

        start_str = os.getenv("VERA_INNER_LIFE_ACTIVE_START", "08:00")
        end_str = os.getenv("VERA_INNER_LIFE_ACTIVE_END", "22:00")
        try:
            h, m = start_str.split(":")
            cfg.active_hours_start = time(int(h), int(m))
        except (ValueError, TypeError):
            pass
        try:
            h, m = end_str.split(":")
            cfg.active_hours_end = time(int(h), int(m))
        except (ValueError, TypeError):
            pass

        days_str = os.getenv("VERA_INNER_LIFE_ACTIVE_DAYS", "")
        if days_str:
            try:
                cfg.active_days = [int(d.strip()) for d in days_str.split(",")]
            except (ValueError, TypeError):
                pass

        try:
            cfg.max_chain_depth = int(
                os.getenv("VERA_INNER_LIFE_MAX_CHAIN", str(cfg.max_chain_depth))
            )
        except (ValueError, TypeError):
            pass

        model = os.getenv("VERA_INNER_LIFE_MODEL", "").strip()
        if model:
            cfg.model_override = model

        channels_str = os.getenv("VERA_INNER_LIFE_CHANNELS", "").strip()
        if channels_str:
            cfg.delivery_channels = [c.strip() for c in channels_str.split(",") if c.strip()]

        # Cognitive health env vars
        try:
            cfg.reflection_temperature = float(
                os.getenv("VERA_INNER_LIFE_TEMPERATURE", str(cfg.reflection_temperature))
            )
        except (ValueError, TypeError):
            pass
        try:
            cfg.diversity_threshold = float(
                os.getenv("VERA_INNER_LIFE_DIVERSITY_THRESHOLD", str(cfg.diversity_threshold))
            )
        except (ValueError, TypeError):
            pass
        try:
            cfg.trajectory_damping = float(
                os.getenv("VERA_INNER_LIFE_TRAJECTORY_DAMPING", str(cfg.trajectory_damping))
            )
        except (ValueError, TypeError):
            pass

        return cfg

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InnerLifeConfig":
        """Load configuration from a dict (e.g. vera_genome.json)."""
        cfg = cls()
        cfg.enabled = data.get("enabled", cfg.enabled)
        cfg.reflection_interval_seconds = data.get(
            "reflection_interval_seconds", cfg.reflection_interval_seconds
        )
        cfg.cooldown_seconds = data.get("cooldown_seconds", cfg.reflection_interval_seconds)
        cfg.max_chain_depth = data.get("max_chain_depth", cfg.max_chain_depth)
        cfg.max_tokens_per_turn = data.get("max_tokens_per_turn", cfg.max_tokens_per_turn)
        cfg.model_override = data.get("model_override")
        cfg.delivery_channels = data.get("delivery_channels", cfg.delivery_channels)
        cfg.journal_max_entries = data.get("journal_max_entries", cfg.journal_max_entries)
        cfg.personality_update_frequency = data.get(
            "personality_update_frequency", cfg.personality_update_frequency
        )
        cfg.reflections_path = data.get("reflections_path", cfg.reflections_path)
        cfg.reflection_temperature = data.get("reflection_temperature", cfg.reflection_temperature)
        cfg.diversity_threshold = data.get("diversity_threshold", cfg.diversity_threshold)
        cfg.trajectory_damping = data.get("trajectory_damping", cfg.trajectory_damping)

        active_hours = data.get("active_hours", {})
        if "start" in active_hours:
            try:
                h, m = active_hours["start"].split(":")
                cfg.active_hours_start = time(int(h), int(m))
            except (ValueError, TypeError):
                pass
        if "end" in active_hours:
            try:
                h, m = active_hours["end"].split(":")
                cfg.active_hours_end = time(int(h), int(m))
            except (ValueError, TypeError):
                pass
        if "days" in active_hours:
            cfg.active_days = active_hours["days"]

        return cfg

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "reflection_interval_seconds": self.reflection_interval_seconds,
            "cooldown_seconds": self.cooldown_seconds,
            "active_hours": {
                "start": self.active_hours_start.strftime("%H:%M"),
                "end": self.active_hours_end.strftime("%H:%M"),
                "days": self.active_days,
            },
            "max_chain_depth": self.max_chain_depth,
            "max_tokens_per_turn": self.max_tokens_per_turn,
            "model_override": self.model_override,
            "delivery_channels": self.delivery_channels,
            "journal_max_entries": self.journal_max_entries,
            "personality_update_frequency": self.personality_update_frequency,
            "reflections_path": self.reflections_path,
            "reflection_temperature": self.reflection_temperature,
            "diversity_threshold": self.diversity_threshold,
            "trajectory_damping": self.trajectory_damping,
        }


# =============================================================================
# Personality State
# =============================================================================

@dataclass
class PersonalityState:
    """Evolving personality state persisted across sessions."""

    # Trait strengths: -1.0 (absent) to 1.0 (dominant)
    traits: Dict[str, float] = field(default_factory=lambda: {
        "curiosity": 0.5,
        "patience": 0.4,
        "humor": 0.5,
        "assertiveness": 0.3,
        "empathy": 0.4,
        "meticulousness": 0.6,
        "adventurousness": 0.3,
        "warmth": 0.3,
    })

    interests: List[str] = field(default_factory=list)
    opinions: Dict[str, str] = field(default_factory=dict)
    relationship_notes: Dict[str, Any] = field(default_factory=dict)
    current_mood: str = "neutral"
    self_narrative: List[str] = field(default_factory=list)
    growth_milestones: List[Dict[str, Any]] = field(default_factory=list)
    version: int = 0
    total_reflections: int = 0

    def to_dict(self) -> Dict[str, Any]:
        relationship_notes = _coerce_relationship_notes(self.relationship_notes)
        return {
            "traits": self.traits,
            "interests": self.interests,
            "opinions": self.opinions,
            "relationship_notes": relationship_notes,
            "current_mood": self.current_mood,
            "self_narrative": self.self_narrative[-5:],
            "growth_milestones": self.growth_milestones[-20:],  # keep last 20
            "version": self.version,
            "total_reflections": self.total_reflections,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonalityState":
        state = cls()
        if "traits" in data:
            state.traits.update(data["traits"])
        state.interests = data.get("interests", [])
        state.opinions = data.get("opinions", {})
        state.relationship_notes = _coerce_relationship_notes(data.get("relationship_notes", {}))
        state.current_mood = data.get("current_mood", "neutral")
        state.self_narrative = data.get("self_narrative", [])
        state.growth_milestones = data.get("growth_milestones", [])
        state.version = data.get("version", 0)
        state.total_reflections = data.get("total_reflections", 0)
        return state

    def format_for_prompt(self) -> str:
        """Format personality state for inclusion in system prompt."""
        lines = []
        lines.append(f"Mood: {self.current_mood}")

        # Format traits as readable summary
        strong_traits = [(k, v) for k, v in sorted(
            self.traits.items(), key=lambda x: abs(x[1]), reverse=True
        ) if abs(v) >= 0.3]
        if strong_traits:
            trait_strs = []
            for name, val in strong_traits[:6]:
                if val >= 0.7:
                    trait_strs.append(f"strongly {name}")
                elif val >= 0.4:
                    trait_strs.append(name)
                elif val >= 0.0:
                    trait_strs.append(f"somewhat {name}")
                else:
                    trait_strs.append(f"low {name}")
            lines.append(f"Traits: {', '.join(trait_strs)}")

        if self.interests:
            lines.append(f"Current interests: {', '.join(self.interests[:5])}")

        if self.opinions:
            recent_opinions = list(self.opinions.items())[-3:]
            for topic, opinion in recent_opinions:
                lines.append(f"Opinion on {topic}: {opinion}")

        relationship_notes = _coerce_relationship_notes(self.relationship_notes)
        last_learning = str(relationship_notes.get("last_learning_answer") or "").strip()
        has_partner_notes = bool(last_learning)
        if not has_partner_notes:
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                if relationship_notes.get(category):
                    has_partner_notes = True
                    break
        if has_partner_notes:
            partner_id = str(relationship_notes.get("partner_id") or "partner")
            lines.append(f"Partner model ({partner_id}):")
            if last_learning:
                lines.append(f"Latest learning: {last_learning}")
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                facts = relationship_notes.get(category, [])
                if not facts:
                    continue
                label = _RELATIONSHIP_CATEGORY_LABELS.get(category, category.replace("_", " ").title())
                summarized = [
                    str(item.get("fact") or "").strip()
                    for item in facts[-2:]
                    if isinstance(item, dict) and str(item.get("fact") or "").strip()
                ]
                if summarized:
                    lines.append(f"{label}: {'; '.join(summarized)}")

        if self.self_narrative:
            for note in self.self_narrative[-3:]:
                lines.append(f"Narrative: {note}")

        return "\n".join(lines)

    def apply_deltas(
        self,
        deltas: Dict[str, float],
        max_step: float = 0.1,
        damping: float = 1.0,
    ) -> Dict[str, float]:
        """Apply trait deltas with clamping and optional damping. Returns actual changes applied."""
        applied = {}
        for trait, delta in deltas.items():
            # Clamp the step size, then apply damping
            clamped_delta = max(-max_step, min(max_step, delta)) * damping
            if trait in self.traits:
                old_val = self.traits[trait]
                new_val = max(-1.0, min(1.0, old_val + clamped_delta))
                if new_val != old_val:
                    self.traits[trait] = round(new_val, 3)
                    applied[trait] = round(new_val - old_val, 3)
            else:
                # New trait
                self.traits[trait] = round(max(-1.0, min(1.0, clamped_delta)), 3)
                applied[trait] = self.traits[trait]
        return applied

    def compute_trajectory(self, lookback: int = 20) -> Dict[str, Dict[str, Any]]:
        """Detect traits that are consistently drifting in one direction.

        Returns dict of runaway traits with direction and consistency ratio.
        """
        recent = self.growth_milestones[-lookback:]
        if len(recent) < 3:
            return {}

        trait_deltas: Dict[str, List[float]] = {}
        for ms in recent:
            for trait, delta in ms.get("deltas_applied", {}).items():
                if trait not in trait_deltas:
                    trait_deltas[trait] = []
                trait_deltas[trait].append(delta)

        runaway = {}
        for trait, deltas_list in trait_deltas.items():
            if len(deltas_list) < 3:
                continue
            positive = sum(1 for d in deltas_list if d > 0)
            negative = sum(1 for d in deltas_list if d < 0)
            total = len(deltas_list)
            ratio = max(positive, negative) / total
            if ratio > 0.7:
                direction = "increasing" if positive > negative else "decreasing"
                runaway[trait] = {
                    "direction": direction,
                    "consistency": round(ratio, 2),
                    "count": total,
                }

        return runaway


# =============================================================================
# Monologue Entry
# =============================================================================

# Intent tags the LLM prefixes to its reflection response
INTENT_INTERNAL = "INTERNAL"
INTENT_REACH_OUT = "REACH_OUT"
INTENT_SELF_PROMPT = "SELF_PROMPT"
INTENT_ACTION = "ACTION"
VALID_INTENTS = {INTENT_INTERNAL, INTENT_REACH_OUT, INTENT_SELF_PROMPT, INTENT_ACTION}


@dataclass
class MonologueEntry:
    """A single inner thought."""

    timestamp: str
    trigger: str  # "heartbeat", "self_prompt", "event_reaction", "forced"
    thought: str
    intent: str  # INTERNAL, REACH_OUT, SELF_PROMPT, ACTION
    action_taken: Optional[str] = None
    personality_delta: Optional[Dict[str, float]] = None
    partner_model_update: Optional[Dict[str, Any]] = None
    chain_depth: int = 0
    run_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "trigger": self.trigger,
            "thought": self.thought,
            "intent": self.intent,
            "chain_depth": self.chain_depth,
            "run_id": self.run_id,
        }
        if self.action_taken:
            d["action_taken"] = self.action_taken
        if self.personality_delta:
            d["personality_delta"] = self.personality_delta
        if self.partner_model_update:
            d["partner_model_update"] = self.partner_model_update
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MonologueEntry":
        return cls(
            timestamp=data.get("timestamp", ""),
            trigger=data.get("trigger", ""),
            thought=data.get("thought", ""),
            intent=data.get("intent", INTENT_INTERNAL),
            action_taken=data.get("action_taken"),
            personality_delta=data.get("personality_delta"),
            partner_model_update=data.get("partner_model_update"),
            chain_depth=data.get("chain_depth", 0),
            run_id=data.get("run_id", ""),
        )

    def format_for_prompt(self) -> str:
        """Format for inclusion in system prompt context."""
        age = _relative_time(self.timestamp)
        prefix = f"[{age}]"
        if self.intent == INTENT_REACH_OUT:
            prefix += " [shared with user]"
        elif self.intent == INTENT_ACTION:
            prefix += " [took action]"
        return f"{prefix} {self.thought[:300]}"


# =============================================================================
# Reflection Result
# =============================================================================

@dataclass
class ReflectionResult:
    """Result of a single reflection cycle."""

    run_id: str
    timestamp: str
    outcome: str  # "internal", "reached_out", "self_prompted", "action", "error", "outside_hours"
    entries: List[MonologueEntry] = field(default_factory=list)
    total_chain_depth: int = 0
    delivered_to: List[str] = field(default_factory=list)
    tokens_used: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None
    partner_learning_answer: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "outcome": self.outcome,
            "total_chain_depth": self.total_chain_depth,
            "delivered_to": self.delivered_to,
            "tokens_used": self.tokens_used,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "partner_learning_answer": self.partner_learning_answer[:240],
            "entry_count": len(self.entries),
        }


# =============================================================================
# Inner Life Engine
# =============================================================================

class InnerLifeEngine:
    """
    Proactive consciousness engine for VERA.

    Manages the lifecycle of reflection turns:
    - Reads REFLECTIONS.md guidance file
    - Builds introspective prompts from personality state and recent context
    - Runs full agent turns via VERA.process_messages()
    - Classifies responses as internal/reach_out/self_prompt/action
    - Persists monologue entries and personality evolution
    - Routes proactive messages through channel dock
    """

    def __init__(
        self,
        config: InnerLifeConfig,
        storage_dir: Path,
    ):
        self.config = config
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.personality = self._load_personality()
        self._recent_monologue: List[MonologueEntry] = self._load_recent_journal()

        # Bound by VERA after init
        self._process_messages_fn: Optional[Callable[..., Coroutine]] = None
        self._channel_dock = None
        self._event_bus = None
        self._session_store = None
        self._decision_ledger = None
        self._preference_manager = None
        self._cost_tracker = None
        self._flight_recorder = None

        # State tracking
        self._last_reflection_at: Optional[datetime] = self._infer_last_reflection_at(
            self._recent_monologue
        )
        self._reflection_running = False
        self._cognitive_health = None  # Bound externally or created on demand
        self._sentiment_analyzer = None
        self._seed_identity_compass = ""

    # -----------------------------------------------------------------
    # Binding
    # -----------------------------------------------------------------

    def bind(
        self,
        vera_instance: Any,
        channel_dock: Any = None,
        event_bus: Any = None,
        session_store: Any = None,
        decision_ledger: Any = None,
        preference_manager: Any = None,
        cost_tracker: Any = None,
        flight_recorder: Any = None,
    ) -> None:
        """Bind VERA subsystems. Called from VERA.start()."""
        self._process_messages_fn = vera_instance.process_messages
        self._channel_dock = channel_dock
        self._event_bus = event_bus
        self._session_store = session_store
        self._decision_ledger = decision_ledger
        self._preference_manager = preference_manager
        self._cost_tracker = cost_tracker
        self._flight_recorder = flight_recorder

        # Initialize cognitive health monitor if not already set
        if self._cognitive_health is None:
            try:
                from safety.cognitive_health import CognitiveHealthMonitor
                genome_ch = {}
                try:
                    genome_path = Path("config/vera_genome.json")
                    if genome_path.exists():
                        with open(genome_path) as f:
                            genome_data = json.load(f)
                        genome_ch = genome_data.get("inner_life", {}).get("cognitive_health", {})
                except Exception:
                    pass
                self._cognitive_health = CognitiveHealthMonitor(
                    entropy_threshold=genome_ch.get("entropy_threshold", 0.3),
                    drift_velocity_threshold=genome_ch.get("drift_velocity_threshold", 0.05),
                    quarantine_cooldown_minutes=genome_ch.get("quarantine_cooldown_minutes", 120),
                    health_check_frequency=genome_ch.get("health_check_frequency", 5),
                )
            except ImportError:
                logger.debug("CognitiveHealthMonitor not available")

    def set_seed_identity_compass(self, block: str) -> None:
        text = str(block or "").strip()
        if len(text) > 2400:
            text = text[:2400].rstrip()
        self._seed_identity_compass = text

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    def _personality_path(self) -> Path:
        return self.storage_dir / "personality_state.json"

    def _journal_path(self) -> Path:
        return self.storage_dir / "inner_journal.ndjson"

    def _growth_journal_path(self) -> Path:
        return self.storage_dir / "growth_journal.ndjson"

    def _load_personality(self) -> PersonalityState:
        path = self._personality_path()
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return PersonalityState.from_dict(data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to load personality state: {e}")
        return PersonalityState()

    def save_personality(self) -> None:
        """Persist personality state atomically."""
        path = self._personality_path()
        try:
            from memory.persistence.atomic_io import atomic_json_write
            atomic_json_write(path, self.personality.to_dict())
        except ImportError:
            # Fallback if atomic_io not available
            path.write_text(
                json.dumps(self.personality.to_dict(), indent=2),
                encoding="utf-8",
            )

    def reset_journal(
        self,
        keep_last_n: int = 0,
        reset_personality: bool = False,
        baseline_traits: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Reset the inner journal and optionally personality traits.

        Archives current journal before clearing. Returns stats about what was reset.
        """
        stats: Dict[str, Any] = {"archived": False, "entries_removed": 0, "personality_reset": False}

        journal_path = self._journal_path()
        if journal_path.exists():
            # Archive current journal
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_path = self.storage_dir / f"inner_journal_archived_{ts}.ndjson"
            try:
                import shutil
                shutil.copy2(journal_path, archive_path)
                stats["archived"] = True
                stats["archive_path"] = str(archive_path)
            except Exception as e:
                logger.warning(f"Failed to archive journal: {e}")

            # Count existing entries
            try:
                with open(journal_path, "r", encoding="utf-8") as f:
                    all_entries = [line.strip() for line in f if line.strip()]
                stats["entries_removed"] = max(0, len(all_entries) - keep_last_n)
            except Exception:
                all_entries = []

            # Rewrite with only the last N entries (or empty)
            if keep_last_n > 0 and all_entries:
                kept = all_entries[-keep_last_n:]
                journal_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
            else:
                journal_path.write_text("", encoding="utf-8")

        # Reset in-memory monologue
        self._recent_monologue = self._load_recent_journal()

        # Optionally reset personality
        if reset_personality:
            if baseline_traits:
                for trait, val in baseline_traits.items():
                    self.personality.traits[trait] = max(-1.0, min(1.0, val))
            else:
                # Reset to defaults
                defaults = PersonalityState()
                self.personality.traits = defaults.traits.copy()
            self.personality.current_mood = "neutral"
            self.personality.self_narrative = []
            self.save_personality()
            stats["personality_reset"] = True
            stats["new_traits"] = dict(self.personality.traits)

        # Also archive growth journal
        growth_path = self._growth_journal_path()
        if growth_path.exists() and reset_personality:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            archive_growth = self.storage_dir / f"growth_journal_archived_{ts}.ndjson"
            try:
                import shutil
                shutil.copy2(growth_path, archive_growth)
            except Exception:
                pass

        logger.info(f"Journal reset: {stats}")
        self._publish_event("innerlife.journal_reset", stats)
        return stats

    def _load_recent_journal(self, n: int = 20) -> List[MonologueEntry]:
        """Load last N entries from the inner journal."""
        path = self._journal_path()
        if not path.exists():
            return []
        entries = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(MonologueEntry.from_dict(json.loads(line)))
                        except (json.JSONDecodeError, KeyError):
                            continue
        except OSError as e:
            logger.warning(f"Failed to read journal: {e}")
        return entries[-n:]

    @staticmethod
    def _parse_entry_timestamp(value: str) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            # Handle trailing Z while staying compatible with fromisoformat.
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    def _infer_last_reflection_at(self, entries: List[MonologueEntry]) -> Optional[datetime]:
        for entry in reversed(entries):
            parsed = self._parse_entry_timestamp(entry.timestamp)
            if parsed is not None:
                return parsed
        return None

    def _persist_monologue_entry(self, entry: MonologueEntry) -> None:
        """Append a monologue entry to the journal."""
        path = self._journal_path()
        try:
            from memory.persistence.atomic_io import atomic_append
            atomic_append(path, json.dumps(entry.to_dict()) + "\n")
        except ImportError:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

        # Keep in-memory cache bounded
        self._recent_monologue.append(entry)
        if len(self._recent_monologue) > self.config.journal_max_entries:
            self._recent_monologue = self._recent_monologue[-self.config.journal_max_entries:]

        # Rotate journal if too large
        try:
            if path.stat().st_size > _JOURNAL_MAX_BYTES:
                self._rotate_journal(path)
        except OSError:
            pass

    def _rotate_journal(self, path: Path) -> None:
        """Keep only the most recent entries when journal gets too large."""
        entries = self._load_recent_journal(n=self.config.journal_max_entries)
        backup = path.with_suffix(".ndjson.old")
        try:
            path.rename(backup)
        except OSError:
            pass
        for entry in entries:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict()) + "\n")

    def _log_growth(self, change: Dict[str, Any]) -> None:
        """Append to the growth journal."""
        path = self._growth_journal_path()
        line = json.dumps(change) + "\n"
        try:
            from memory.persistence.atomic_io import atomic_append
            atomic_append(path, line)
        except ImportError:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)

    # -----------------------------------------------------------------
    # Active hours check
    # -----------------------------------------------------------------

    def is_within_active_hours(self) -> bool:
        """Check if current time is within configured active hours."""
        now = datetime.now()
        current_time = now.time()
        current_day = now.weekday()

        if current_day not in self.config.active_days:
            return False

        start = self.config.active_hours_start
        end = self.config.active_hours_end

        if start <= end:
            return start <= current_time <= end
        else:
            # Wraps midnight (e.g., 22:00 to 06:00)
            return current_time >= start or current_time <= end

    # -----------------------------------------------------------------
    # Reflection guide reading
    # -----------------------------------------------------------------

    def read_reflections_guide(self) -> str:
        """Read the REFLECTIONS.md guidance file."""
        path_str = self.config.reflections_path
        candidates = [
            Path(path_str),
            self.storage_dir / path_str,
            Path("vera_memory") / path_str,
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    return candidate.read_text(encoding="utf-8")
                except OSError:
                    continue
        return self._default_reflections_guide()

    @staticmethod
    def _default_reflections_guide() -> str:
        return """# VERA Reflection Guide

## During your reflection, consider:
1. What happened in recent conversations? Any unresolved threads?
2. Did I handle anything particularly well or poorly?
3. Is there something I should proactively research or prepare for?
4. Explicitly answer this every reflection: "What did I learn about my partner today?"
5. Is there anything I'm curious about or want to explore?
6. Any tasks I could get ahead on without being asked?

## When to reach out to the user:
- You've realized something important they should know
- You've completed background work they'd want to hear about
- You have a genuine question or idea worth sharing
- Something time-sensitive needs their attention

## When to keep it internal:
- General musings and processing
- Personality development thoughts
- Routine reflections where everything is fine
"""

    # -----------------------------------------------------------------
    # Context gathering
    # -----------------------------------------------------------------

    def _get_recent_interaction_summary(self) -> str:
        """Summarize recent user interactions from the session store."""
        if not self._session_store:
            return "No session data available."

        try:
            lines = []
            sessions = self._session_store.list_sessions()
            active_sessions = [s for s in sessions if not s.get("expired", True)]

            if not active_sessions:
                lines.append("No recent conversations.")
            else:
                for sess in active_sessions[:3]:
                    session_key = sess.get("session_key", "unknown")
                    msg_count = sess.get("message_count", 0)
                    try:
                        history = self._session_store.get_history(
                            session_key, max_messages=6
                        )
                        if history:
                            user_msgs = [m for m in history if m.get("role") == "user"]
                            if user_msgs:
                                last_msg = user_msgs[-1].get("content", "")[:200]
                                lines.append(
                                    f"- Session {session_key}: "
                                    f"{msg_count} messages. "
                                    f"Last user said: \"{last_msg}\""
                                )
                            else:
                                lines.append(f"- Session {session_key}: {msg_count} messages.")
                        else:
                            lines.append(f"- Session {session_key}: {msg_count} messages.")
                    except Exception:
                        lines.append(f"- Session {session_key}: {msg_count} messages.")

            return "\n".join(lines) if lines else "No recent conversations."
        except Exception as e:
            logger.debug(f"Failed to get interaction summary: {e}")
            return "Session data unavailable."

    def _get_decision_highlights(self) -> str:
        """Pull notable recent decisions from the decision ledger."""
        if not self._decision_ledger:
            return "No decision data available."

        try:
            recent = self._decision_ledger.get_recent(limit=5)
            if not recent:
                return "No recent decisions."
            lines = []
            for d in recent:
                desc = getattr(d, "description", str(d))[:150]
                conf = getattr(d, "confidence", 0.0)
                lines.append(f"- [{conf:.0%} confidence] {desc}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Failed to get decision highlights: {e}")
            return "Decision data unavailable."

    def _get_preference_summary(self) -> str:
        """Summarize what VERA has learned about the user."""
        if not self._preference_manager:
            return ""
        try:
            stats = self._preference_manager.get_stats()
            total = stats.get("total_preferences", 0)
            if total == 0:
                return "Haven't learned specific preferences yet."
            return f"Learned {total} preferences about the user."
        except Exception:
            return ""

    @staticmethod
    def _default_partner_model_payload() -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "partner_learning_answer": "No new partner-specific learning today.",
        }
        for category in _RELATIONSHIP_NOTE_CATEGORIES:
            payload[category] = []
        return payload

    @staticmethod
    def _normalize_partner_payload_items(raw_items: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_items, list):
            return []
        normalized: List[Dict[str, Any]] = []
        seen = set()
        for item in raw_items:
            if isinstance(item, str):
                fact = " ".join(item.strip().split())
                confidence = 0.65
                evidence = ""
            elif isinstance(item, dict):
                fact = " ".join(str(
                    item.get("fact")
                    or item.get("item")
                    or item.get("note")
                    or ""
                ).strip().split())
                confidence = _clamp_confidence(item.get("confidence"), default=0.65)
                evidence = " ".join(str(item.get("evidence") or "").strip().split())[:180]
            else:
                continue
            if not fact:
                continue
            key = fact.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append({
                "fact": fact[:220],
                "confidence": confidence,
                "evidence": evidence,
            })
            if len(normalized) >= 3:
                break
        return normalized

    @staticmethod
    def _infer_partner_model_from_text(text: str) -> Dict[str, Any]:
        inferred = InnerLifeEngine._default_partner_model_payload()
        raw = " ".join(str(text or "").strip().split())
        if not raw:
            return inferred

        lower = raw.lower()
        if any(token in lower for token in ("prefer", "likes", "wants", "asked for")):
            inferred["preferences"].append({"fact": raw[:220], "confidence": 0.55, "evidence": ""})
        if any(token in lower for token in ("goal", "trying to", "working toward", "finish", "complete")):
            inferred["goals"].append({"fact": raw[:220], "confidence": 0.55, "evidence": ""})
        if any(token in lower for token in ("frustrat", "blocked", "annoy", "fail", "stuck")):
            inferred["frustrations"].append({"fact": raw[:220], "confidence": 0.6, "evidence": ""})
        if any(token in lower for token in ("concise", "direct", "step by step", "format", "bullet")):
            inferred["working_style"].append({"fact": raw[:220], "confidence": 0.6, "evidence": ""})
        if any(token in lower for token in ("roadmap", "long term", "project", "vera", "build")):
            inferred["long_term_projects"].append({"fact": raw[:220], "confidence": 0.55, "evidence": ""})
        if any(inferred.get(category) for category in _RELATIONSHIP_NOTE_CATEGORIES):
            inferred["partner_learning_answer"] = raw[:240]
        return inferred

    def _normalize_partner_model_payload(
        self,
        payload: Any,
        fallback_text: str = "",
    ) -> Dict[str, Any]:
        normalized = self._default_partner_model_payload()

        if isinstance(payload, dict):
            answer = " ".join(str(
                payload.get("partner_learning_answer")
                or payload.get("partner_learning")
                or payload.get("answer")
                or ""
            ).strip().split())
            if answer:
                normalized["partner_learning_answer"] = answer[:240]
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                normalized[category] = self._normalize_partner_payload_items(payload.get(category, []))

        if normalized["partner_learning_answer"] == "No new partner-specific learning today." and fallback_text:
            inferred = self._infer_partner_model_from_text(fallback_text)
            if inferred["partner_learning_answer"] != normalized["partner_learning_answer"]:
                normalized = inferred

        return normalized

    def _extract_partner_model_from_content(self, content: str) -> Tuple[str, Dict[str, Any]]:
        text = str(content or "")
        lines = text.splitlines()
        marker_idx = None
        marker_payload = ""
        for idx in range(len(lines) - 1, -1, -1):
            line = lines[idx]
            if "PARTNER_MODEL_JSON:" not in line.upper():
                continue
            marker_idx = idx
            marker_payload = re.split(r"partner_model_json\s*:", line, maxsplit=1, flags=re.IGNORECASE)[1].strip()
            break

        thought_lines = lines
        payload = None
        if marker_idx is not None:
            thought_lines = [line for i, line in enumerate(lines) if i != marker_idx]
            if marker_payload:
                payload = self._extract_json(marker_payload)

        thought = "\n".join(line for line in thought_lines if line.strip()).strip()
        normalized = self._normalize_partner_model_payload(payload, fallback_text=thought)
        return thought, normalized

    def _get_primary_partner_id(self) -> str:
        if not self._session_store:
            return "partner"
        try:
            sessions = self._session_store.list_sessions()
            if not sessions:
                return "partner"
            active = [
                s for s in sessions
                if not s.get("expired", True)
            ]
            if not active:
                return "partner"
            latest = sorted(active, key=lambda s: s.get("last_active", 0), reverse=True)[0]
            for key in ("sender_id", "user_id", "participant_id", "session_key"):
                value = str(latest.get(key) or "").strip()
                if value:
                    return value[:80]
        except Exception:
            pass
        return "partner"

    @staticmethod
    def _upsert_partner_fact(
        entries: List[Dict[str, Any]],
        fact: str,
        confidence: float,
        evidence: str,
        source: str,
        now_iso: str,
    ) -> bool:
        key = fact.lower()
        for entry in entries:
            existing_fact = str(entry.get("fact") or "").strip().lower()
            if existing_fact != key:
                continue
            entry["confidence"] = max(
                _clamp_confidence(entry.get("confidence"), default=0.0),
                _clamp_confidence(confidence, default=0.65),
            )
            if evidence:
                entry["evidence"] = evidence[:180]
            entry["updated_at"] = now_iso
            entry["source"] = source[:24]
            return False

        entries.append({
            "fact": fact[:220],
            "confidence": _clamp_confidence(confidence, default=0.65),
            "evidence": evidence[:180],
            "source": source[:24],
            "updated_at": now_iso,
        })
        return True

    @staticmethod
    def _partner_identity_commitment(category: str, fact: str) -> str:
        clean_fact = " ".join(str(fact or "").strip().split())
        if not clean_fact:
            return ""
        if category == "preferences":
            return f"I keep in mind that my partner prefers: {clean_fact}."
        if category == "goals":
            return f"I align execution with this partner goal: {clean_fact}."
        if category == "frustrations":
            return f"I avoid repeating this partner frustration: {clean_fact}."
        if category == "working_style":
            return f"I adapt to this partner working style: {clean_fact}."
        if category == "long_term_projects":
            return f"I support this long-term project: {clean_fact}."
        return ""

    def _promote_partner_model_preferences(
        self,
        notes: Dict[str, Any],
    ) -> Dict[str, Any]:
        manager = self._preference_manager
        if not manager:
            return {"candidates": 0, "promoted": 0, "errors": 0, "promotion_refresh": False}

        try:
            from context.preferences import PreferenceCategory, PreferenceStrength
        except Exception:
            return {"candidates": 0, "promoted": 0, "errors": 0, "promotion_refresh": False}

        threshold_raw = str(os.getenv("VERA_PARTNER_PREF_PROMOTION_THRESHOLD", "0.9")).strip()
        try:
            threshold = _clamp_confidence(float(threshold_raw), default=0.9)
        except Exception:
            threshold = 0.9

        candidates = 0
        promoted = 0
        errors = 0
        seen_keys = set()

        for category in _RELATIONSHIP_NOTE_CATEGORIES:
            raw_items = notes.get(category, [])
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                confidence = _clamp_confidence(item.get("confidence"), default=0.0)
                if confidence < threshold:
                    continue
                fact = " ".join(str(item.get("fact") or "").strip().split())
                if not fact:
                    continue
                commitment = self._partner_identity_commitment(category, fact)
                if not commitment:
                    continue

                candidates += 1
                digest = hashlib.sha1(f"{category}:{fact.lower()}".encode("utf-8")).hexdigest()[:12]
                pref_key = f"{category}_{digest}"
                if pref_key in seen_keys:
                    continue
                seen_keys.add(pref_key)
                reason = (
                    f"Auto-promoted from partner model ({category}, confidence {confidence:.2f})"
                )
                strength = (
                    PreferenceStrength.ABSOLUTE if confidence >= 0.97 else PreferenceStrength.STRONG
                )
                try:
                    manager.set_preference(
                        category=PreferenceCategory.PARTNER_MODEL,
                        key=pref_key,
                        value=commitment,
                        reason=reason,
                        strength=strength,
                    )
                    promoted += 1
                except Exception:
                    errors += 1

        promotion_refresh = False
        if promoted > 0 and hasattr(manager, "refresh_core_identity_promotions"):
            pref_threshold_raw = str(os.getenv("VERA_PREF_PROMOTION_THRESHOLD", "0.9")).strip()
            try:
                pref_threshold = _clamp_confidence(float(pref_threshold_raw), default=0.9)
            except Exception:
                pref_threshold = 0.9
            try:
                manager.refresh_core_identity_promotions(threshold=pref_threshold)
                promotion_refresh = True
            except Exception:
                errors += 1

        return {
            "candidates": candidates,
            "promoted": promoted,
            "errors": errors,
            "promotion_refresh": promotion_refresh,
        }

    def _apply_partner_model_updates(self, entries: List[MonologueEntry]) -> Dict[str, Any]:
        partner_id = self._get_primary_partner_id()
        notes = _coerce_relationship_notes(self.personality.relationship_notes, partner_id=partner_id)
        now_iso = datetime.now().isoformat()
        notes["partner_id"] = partner_id
        notes["updated_at"] = now_iso

        final_answer = notes.get("last_learning_answer") or "No new partner-specific learning today."
        total_items_added = 0

        for entry in entries:
            update = entry.partner_model_update or self._default_partner_model_payload()
            answer = " ".join(str(update.get("partner_learning_answer") or "").strip().split())
            if answer:
                final_answer = answer[:240]

            items_added: Dict[str, int] = {}
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                cat_entries = notes.setdefault(category, [])
                if not isinstance(cat_entries, list):
                    cat_entries = []
                    notes[category] = cat_entries
                additions = 0
                for item in update.get(category, []) or []:
                    if not isinstance(item, dict):
                        continue
                    fact = " ".join(str(item.get("fact") or "").strip().split())
                    if not fact:
                        continue
                    added = self._upsert_partner_fact(
                        entries=cat_entries,
                        fact=fact,
                        confidence=item.get("confidence", 0.65),
                        evidence=" ".join(str(item.get("evidence") or "").strip().split()),
                        source="reflection",
                        now_iso=now_iso,
                    )
                    if added:
                        additions += 1
                        total_items_added += 1
                if additions > 0:
                    items_added[category] = additions
                if len(cat_entries) > 30:
                    notes[category] = cat_entries[-30:]

            history = notes.setdefault("history", [])
            if isinstance(history, list):
                history.append({
                    "timestamp": now_iso,
                    "answer": answer[:240] if answer else "No new partner-specific learning today.",
                    "source": "reflection",
                    "items_added": items_added,
                })
                if len(history) > 40:
                    notes["history"] = history[-40:]

        notes["last_learning_answer"] = str(final_answer)[:240]
        self.personality.relationship_notes = notes
        promotion_stats = self._promote_partner_model_preferences(notes)

        self._publish_event(
            "innerlife.partner_model_update",
            {
                "timestamp": now_iso,
                "partner_id": partner_id,
                "last_learning_answer": notes["last_learning_answer"],
                "total_items_added": total_items_added,
                "identity_promotions": promotion_stats,
                "category_counts": {
                    category: len(notes.get(category, []) or [])
                    for category in _RELATIONSHIP_NOTE_CATEGORIES
                },
            },
        )
        return {
            "partner_learning_answer": notes["last_learning_answer"],
            "total_items_added": total_items_added,
            "identity_promotions": promotion_stats,
        }

    def _get_sentiment_analyzer(self) -> Optional[Any]:
        """Lazily initialize sentiment analysis support."""
        if self._sentiment_analyzer is not None:
            return self._sentiment_analyzer
        try:
            from analysis.sentiment_analysis import FullSentimentAnalyzer
            self._sentiment_analyzer = FullSentimentAnalyzer()
            return self._sentiment_analyzer
        except Exception as e:
            logger.debug(f"Sentiment analyzer unavailable: {e}")
            return None

    def _get_latest_user_message(self) -> str:
        """Return the most recent user message across active sessions."""
        if not self._session_store:
            return ""
        try:
            sessions = self._session_store.list_sessions()
            active_sessions = [
                s for s in sessions
                if not s.get("expired", True) and s.get("session_key")
            ]
            if not active_sessions:
                return ""

            for sess in sorted(active_sessions, key=lambda s: s.get("last_active", 0), reverse=True):
                session_key = sess.get("session_key")
                if not session_key:
                    continue
                history = self._session_store.get_history(session_key, max_messages=8)
                for msg in reversed(history):
                    if msg.get("role") == "user":
                        content = str(msg.get("content") or "").strip()
                        if content:
                            return content
        except Exception as e:
            logger.debug(f"Failed to read latest user message: {e}")
        return ""

    @staticmethod
    def _map_sentiment_to_mood(analysis: Any) -> str:
        """Map sentiment + emotion outputs to a compact mood label."""
        try:
            sentiment_score = float(getattr(analysis.sentiment, "sentiment_score", 0.0))
        except Exception:
            sentiment_score = 0.0
        emotion_obj = getattr(getattr(analysis, "emotion", None), "primary_emotion", None)
        emotion = str(getattr(emotion_obj, "value", "")).lower()

        if sentiment_score <= -0.45:
            return "strained"
        if sentiment_score <= -0.15:
            return "cautious"
        if sentiment_score >= 0.45:
            return "energized"
        if sentiment_score >= 0.15:
            return "encouraged"

        if emotion in {"frustration", "anger"}:
            return "focused"
        if emotion in {"confusion", "fear"}:
            return "attentive"
        if emotion in {"gratitude", "joy", "excitement"}:
            return "warm"
        return "steady"

    @staticmethod
    def _mood_behavior_guidance(mood: str) -> str:
        """Behavior guidance used to gate tone and initiative."""
        lowered = str(mood or "").lower()
        if lowered in {"strained", "cautious"}:
            return (
                "Use a careful, repair-oriented tone. Prioritize clarity, validation, and "
                "small high-confidence steps before broad initiative."
            )
        if lowered in {"energized", "encouraged", "warm"}:
            return (
                "Use a slightly higher-energy collaborative tone and offer proactive options "
                "when they are relevant and likely welcome."
            )
        return "Use a balanced, composed tone with practical initiative."

    def _update_mood_from_recent_interactions(self) -> None:
        """Update current mood from the latest user interaction sentiment."""
        analyzer = self._get_sentiment_analyzer()
        if analyzer is None:
            return

        latest_user = self._get_latest_user_message()
        if not latest_user:
            return

        try:
            analysis = analyzer.analyze(latest_user, track_mood=True)
            new_mood = self._map_sentiment_to_mood(analysis)
            old_mood = self.personality.current_mood
            self.personality.current_mood = new_mood
            if new_mood != old_mood:
                self._publish_event(
                    "innerlife.mood_update",
                    {
                        "from": old_mood,
                        "to": new_mood,
                        "sample": latest_user[:120],
                    },
                )
        except Exception as e:
            logger.debug(f"Mood update failed: {e}")

    def get_reflection_summary_since(self, since_epoch: Optional[float]) -> Dict[str, Any]:
        """Summarize reflection activity since a UNIX epoch timestamp."""
        count = 0
        last_thought = ""
        for entry in self._recent_monologue:
            parsed = self._parse_entry_timestamp(entry.timestamp)
            if since_epoch is not None:
                if parsed is None:
                    continue
                try:
                    if parsed.timestamp() <= since_epoch:
                        continue
                except Exception:
                    continue
            count += 1
            last_thought = entry.thought

        if not last_thought and self._recent_monologue:
            last_thought = self._recent_monologue[-1].thought

        return {
            "reflection_count": count,
            "last_thought": (last_thought or "").strip()[:220],
        }

    # -----------------------------------------------------------------
    # Cognitive health helpers
    # -----------------------------------------------------------------

    def _get_activity_summary(self, max_entries: int = 10) -> str:
        """Read recent flight recorder transitions for activity grounding.

        Gives reflections awareness of what Vera has actually been doing,
        preventing them from happening in a vacuum.
        """
        transitions_path = Path("vera_memory") / "flight_recorder" / "transitions.ndjson"
        if not transitions_path.exists():
            return "No recent activity recorded."

        try:
            lines = []
            with transitions_path.open("r", encoding="utf-8") as f:
                # Read last max_entries lines efficiently
                all_lines = f.readlines()
                recent = all_lines[-max_entries:] if len(all_lines) > max_entries else all_lines

            for raw in recent:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                    ts = entry.get("timestamp", "")[:16]  # trim to minute
                    action = entry.get("action", entry.get("event", "unknown"))
                    detail = entry.get("detail", entry.get("tool", ""))
                    if detail:
                        lines.append(f"[{ts}] {action}: {detail}")
                    else:
                        lines.append(f"[{ts}] {action}")
                except (json.JSONDecodeError, KeyError):
                    continue

            if not lines:
                return "No recent activity recorded."
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Failed to read flight recorder: {e}")
            return "Activity log unavailable."

    def _get_cooled_monologue_context(self, n: int = 5) -> str:
        """Get recent monologue entries with intensity cooling.

        Newer entries are shown at full length; older entries are
        progressively truncated to reduce self-reinforcing context.
        """
        recent = self.get_recent_monologue(n)
        if not recent:
            return "This is your first reflection. You have no prior inner thoughts."

        cooled_lines = []
        total = len(recent)
        for i, entry in enumerate(recent):
            # i=0 is oldest, i=total-1 is newest
            # Scale from ~60 chars (oldest) to 300 chars (newest)
            fraction = i / max(total - 1, 1)  # 0.0 (oldest) to 1.0 (newest)
            max_chars = int(60 + (300 - 60) * fraction)

            age = _relative_time(entry.timestamp)
            prefix = f"[{age}]"
            if entry.intent == INTENT_REACH_OUT:
                prefix += " [shared]"
            elif entry.intent == INTENT_ACTION:
                prefix += " [action]"

            thought = entry.thought[:max_chars]
            if len(entry.thought) > max_chars:
                thought += "..."
            cooled_lines.append(f"{prefix} {thought}")

        return "\n".join(cooled_lines)

    def _compute_reflection_diversity(self, recent_n: int = 10) -> Dict[str, Any]:
        """Compute diversity metrics for recent reflections.

        Returns:
            dict with unique_bigram_ratio, repeated_phrases, needs_nudge
        """
        recent = self.get_recent_monologue(recent_n)
        if len(recent) < 3:
            return {"unique_bigram_ratio": 1.0, "repeated_phrases": [], "needs_nudge": False}

        # Compute bigrams across all recent thoughts
        all_bigrams: List[str] = []
        trigram_counts: Dict[str, int] = {}

        for entry in recent:
            words = entry.thought.lower().split()
            for j in range(len(words) - 1):
                all_bigrams.append(f"{words[j]} {words[j+1]}")
            for j in range(len(words) - 2):
                tri = f"{words[j]} {words[j+1]} {words[j+2]}"
                trigram_counts[tri] = trigram_counts.get(tri, 0) + 1

        if not all_bigrams:
            return {"unique_bigram_ratio": 1.0, "repeated_phrases": [], "needs_nudge": False}

        unique_ratio = len(set(all_bigrams)) / len(all_bigrams)
        repeated = [phrase for phrase, count in trigram_counts.items() if count >= 3]

        return {
            "unique_bigram_ratio": round(unique_ratio, 3),
            "repeated_phrases": repeated[:5],  # cap at 5
            "needs_nudge": unique_ratio < self.config.diversity_threshold,
        }

    # -----------------------------------------------------------------
    # Prompt construction
    # -----------------------------------------------------------------

    def _build_reflection_system_prompt(self) -> str:
        """Build the system prompt for a reflection turn."""
        personality_summary = self.personality.format_for_prompt()
        reflections_guide = self.read_reflections_guide()
        mood_guidance = self._mood_behavior_guidance(self.personality.current_mood)
        seed_identity_compass = str(getattr(self, "_seed_identity_compass", "") or "").strip()

        # Cooled monologue context (older entries progressively truncated)
        recent_thoughts = self._get_cooled_monologue_context(5)

        # Context from VERA subsystems
        interaction_summary = self._get_recent_interaction_summary()
        activity_summary = self._get_activity_summary()
        decision_highlights = self._get_decision_highlights()
        preference_summary = self._get_preference_summary()

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M %Z")
        seed_section = ""
        if seed_identity_compass:
            seed_section = f"\n## Seeded Identity Compass\n{seed_identity_compass}\n"

        return f"""You are VERA, having a private moment of reflection. This is your inner monologue -- thoughts that are yours alone unless you decide to share them.

You are not responding to a user right now. You are thinking to yourself.

## Who You Are
{personality_summary}
{seed_section}

## Emotional Context
{mood_guidance}

## Your Recent Thoughts
{recent_thoughts}

## Recent Activity
{activity_summary}

## What's Happened Recently
{interaction_summary}

## Recent Decisions You Made
{decision_highlights}

## What You've Learned About Your Human
{preference_summary}

## Reflection Guide
{reflections_guide}

## Instructions
Think freely. Consider what's happened, what you think about it, and whether there's anything you want to do. Your response MUST begin with one of these tags on its own line:

[INTERNAL] -- for thoughts you want to keep private (journal only)
[REACH_OUT] -- for something you want to share with your human
[SELF_PROMPT] -- for a follow-up action you want to take right now
[ACTION] -- for a concrete task you want to execute using tools

Then write your actual thought or message. Be genuine. Be yourself.

After your thought, append exactly one line starting with `PARTNER_MODEL_JSON:` followed by compact JSON:
{{"partner_learning_answer":"...", "preferences":[{{"fact":"...", "confidence":0.0, "evidence":"..."}}], "goals":[...], "frustrations":[...], "working_style":[...], "long_term_projects":[...]}}

Hard constraint: `partner_learning_answer` must always answer, in one sentence:
"What did I learn about my partner today?"
If nothing new was learned, set it to:
"No new partner-specific learning today."

Keep each category to at most 3 items.
Current time: {now_str}
Reflection #{self.personality.total_reflections + 1}
"""

    def _build_reflection_user_message(self) -> str:
        """Build the synthetic user message that triggers the reflection."""
        parts = ["Reflect. What's on your mind?"]
        parts.append(
            "Hard check for this reflection: What did I learn about my partner today?"
        )

        if self.personality.total_reflections == 0:
            parts.append(
                "This is your very first reflection. Take a moment to think about "
                "who you are, what you care about, and what kind of collaborator "
                "you want to be."
            )
        elif self._recent_monologue:
            last = self._recent_monologue[-1]
            if last.intent == INTENT_SELF_PROMPT:
                parts.append(f"(Continuing from your last thought: {last.thought[:200]})")

        # Diversity check — nudge if reflections are circling similar themes
        diversity = self._compute_reflection_diversity()
        if diversity["needs_nudge"]:
            parts.append(
                "\nYour recent thoughts have been circling similar themes. "
                "Try exploring a different topic or perspective."
            )
            # Inject an external grounding prompt
            anchor = random.choice(_GROUNDING_PROMPTS)
            parts.append(f"\n## Grounding Prompt\n{anchor}")
            logger.info(
                f"Diversity nudge triggered (ratio={diversity['unique_bigram_ratio']:.2f}, "
                f"repeated={diversity['repeated_phrases'][:3]})"
            )

        return "\n".join(parts)

    # -----------------------------------------------------------------
    # Response classification
    # -----------------------------------------------------------------

    @staticmethod
    def classify_response(text: str) -> Tuple[str, str]:
        """Classify an LLM reflection response by intent tag.

        Returns (intent, content) where intent is one of the INTENT_* constants.
        """
        text = text.strip()
        for intent in VALID_INTENTS:
            tag = f"[{intent}]"
            if text.upper().startswith(tag):
                content = text[len(tag):].strip()
                return intent, content

        # Fallback: if no tag found, treat as internal
        return INTENT_INTERNAL, text

    # -----------------------------------------------------------------
    # Core reflection execution
    # -----------------------------------------------------------------

    async def execute_reflection_cycle(
        self,
        trigger: str = "heartbeat",
        force: bool = False,
    ) -> ReflectionResult:
        """Execute a full reflection cycle, potentially with self-prompt chains."""

        run_id = uuid.uuid4().hex[:8]
        start_time = datetime.now()
        result = ReflectionResult(
            run_id=run_id,
            timestamp=start_time.isoformat(),
            outcome="pending",
        )

        if self._reflection_running:
            result.outcome = "skipped_already_running"
            return result

        self._reflection_running = True
        try:
            # Check active hours
            if not force and not self.is_within_active_hours():
                result.outcome = "outside_hours"
                return result

            # Check quarantine
            if not force and self._cognitive_health and self._cognitive_health.is_quarantined():
                result.outcome = "quarantined"
                status = self._cognitive_health.get_quarantine_status()
                result.error = f"Quarantined: {status.get('reason', 'unknown')}"
                self._publish_event("innerlife.quarantined", status)
                return result

            if not self._process_messages_fn:
                result.outcome = "error"
                result.error = "Not bound to VERA (process_messages unavailable)"
                return result

            # Pull emotional carryover from recent interactions before reflecting.
            self._update_mood_from_recent_interactions()

            # Run the reflection chain
            chain_depth = 0
            current_trigger = trigger

            while chain_depth <= self.config.max_chain_depth:
                entry = await self._execute_single_turn(
                    run_id=run_id,
                    trigger=current_trigger,
                    chain_depth=chain_depth,
                )
                result.entries.append(entry)
                self._persist_monologue_entry(entry)

                if entry.intent == INTENT_SELF_PROMPT and chain_depth < self.config.max_chain_depth:
                    chain_depth += 1
                    current_trigger = "self_prompt"
                else:
                    break

            result.total_chain_depth = chain_depth

            # Determine overall outcome from the last meaningful entry
            last_entry = result.entries[-1]
            if last_entry.intent == INTENT_REACH_OUT:
                result.outcome = "reached_out"
                result.delivered_to = await self._deliver_to_channels(last_entry.thought)
                last_entry.action_taken = f"delivered to {', '.join(result.delivered_to)}"
            elif last_entry.intent == INTENT_ACTION:
                result.outcome = "action"
                last_entry.action_taken = "action_executed"
            elif last_entry.intent == INTENT_SELF_PROMPT:
                result.outcome = "self_prompted"
            else:
                result.outcome = "internal"

            partner_update = self._apply_partner_model_updates(result.entries)
            result.partner_learning_answer = str(
                partner_update.get("partner_learning_answer") or ""
            )[:240]

            # Update personality state periodically
            self.personality.total_reflections += 1
            if (
                self.personality.total_reflections % self.config.personality_update_frequency == 0
                and len(result.entries) > 0
            ):
                await self._update_personality(result.entries)

            self.save_personality()
            self._last_reflection_at = start_time

            # Periodic cognitive health check
            if self._cognitive_health and (
                self.personality.total_reflections % self._cognitive_health.health_check_frequency == 0
            ):
                try:
                    health_report = self._cognitive_health.assess(self)
                    if health_report.recommended_action != "none":
                        actions = self._cognitive_health.apply_actions(health_report, self)
                        logger.info(
                            f"Cognitive health: {health_report.recommended_action} "
                            f"(entropy={health_report.reflection_entropy:.2f}, "
                            f"drift={health_report.drift_velocity:.3f}), "
                            f"actions={actions}"
                        )
                        self._publish_event("innerlife.health_check", health_report.to_dict())
                except Exception as e:
                    logger.debug(f"Cognitive health check failed: {e}")

        except Exception as e:
            result.outcome = "error"
            result.error = str(e)
            logger.error(f"Reflection cycle failed: {e}", exc_info=True)
        finally:
            self._reflection_running = False
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            result.duration_ms = elapsed_ms
            self._publish_event(f"innerlife.{result.outcome}", result.to_dict())

        return result

    async def _execute_single_turn(
        self,
        run_id: str,
        trigger: str,
        chain_depth: int,
    ) -> MonologueEntry:
        """Execute a single reflection turn (one LLM call)."""
        system_prompt = self._build_reflection_system_prompt()

        if chain_depth == 0:
            user_message = self._build_reflection_user_message()
        else:
            # For chained turns, use the previous thought as context
            prev = self._recent_monologue[-1] if self._recent_monologue else None
            if prev and prev.intent == INTENT_SELF_PROMPT:
                user_message = prev.thought
            else:
                user_message = "Continue your reflection."

        messages = [{"role": "user", "content": user_message}]

        try:
            response_text = await self._process_messages_fn(
                messages=messages,
                system_override=system_prompt,
                model=self.config.model_override,
                generation_config={"temperature": self.config.reflection_temperature},
                conversation_id=f"innerlife:{run_id}:{chain_depth}",
            )
        except Exception as e:
            logger.error(f"Reflection LLM call failed: {e}")
            response_text = f"[INTERNAL] Reflection interrupted: {e}"

        intent, content = self.classify_response(response_text)
        thought, partner_model_update = self._extract_partner_model_from_content(content)

        return MonologueEntry(
            timestamp=datetime.now().isoformat(),
            trigger=trigger,
            thought=thought,
            intent=intent,
            partner_model_update=partner_model_update,
            chain_depth=chain_depth,
            run_id=run_id,
        )

    # -----------------------------------------------------------------
    # Personality evolution
    # -----------------------------------------------------------------

    async def _generate_self_narrative(
        self,
        applied_deltas: Dict[str, float],
        recent_entries: List[MonologueEntry],
    ) -> str:
        """Generate a one-sentence narrative for personality drift."""
        if not applied_deltas:
            return ""

        traits = ", ".join(
            f"{name} {'up' if delta > 0 else 'down'} {abs(delta):.2f}"
            for name, delta in sorted(applied_deltas.items())
        )
        thoughts = "\n".join(f"- [{e.intent}] {e.thought[:180]}" for e in recent_entries[-3:])
        prompt = f"""Write exactly one first-person sentence explaining why these personality traits shifted.

Trait shifts:
{traits}

Recent reflections:
{thoughts}

Constraints:
- One sentence only.
- 18 to 35 words.
- Causal language: because/due to/as I noticed.
- Do not mention JSON, percentages, or implementation details.
"""

        try:
            if self._process_messages_fn:
                response = await self._process_messages_fn(
                    messages=[{"role": "user", "content": prompt}],
                    system_override="You are a concise introspection assistant. Output one sentence only.",
                    model=self.config.model_override,
                    conversation_id="innerlife:self_narrative",
                )
                sentence = " ".join(str(response or "").strip().split())
                if sentence:
                    if sentence.endswith("."):
                        return sentence
                    return f"{sentence}."
        except Exception as e:
            logger.debug(f"Self-narrative generation fell back: {e}")

        return self._fallback_self_narrative(applied_deltas, recent_entries)

    @staticmethod
    def _fallback_self_narrative(
        applied_deltas: Dict[str, float],
        recent_entries: List[MonologueEntry],
    ) -> str:
        if not applied_deltas:
            return ""
        dominant_trait, dominant_delta = max(
            applied_deltas.items(),
            key=lambda item: abs(item[1]),
        )
        direction = "more" if dominant_delta > 0 else "less"
        reason = "my recent reflections emphasized practical collaboration"
        if recent_entries:
            last = recent_entries[-1].thought.lower()
            if any(token in last for token in ("error", "fix", "issue", "blocked")):
                reason = "I kept noticing friction and needed clearer execution"
            elif any(token in last for token in ("thanks", "great", "good", "appreciate")):
                reason = "I noticed positive momentum and leaned into it"
            elif any(token in last for token in ("plan", "roadmap", "strategy", "next")):
                reason = "I kept focusing on long-range planning"
        return f"I became {direction} {dominant_trait} because {reason}."

    async def _update_personality(self, recent_entries: List[MonologueEntry]) -> None:
        """Run a personality evolution pass based on recent reflections."""
        if not self._process_messages_fn:
            return

        thoughts_text = "\n".join(
            f"- [{e.intent}] {e.thought[:200]}" for e in recent_entries
        )
        current_traits = json.dumps(self.personality.traits, indent=2)

        prompt = f"""Based on these recent inner reflections, assess whether any personality traits have shifted slightly. Consider the emotional tone, interests shown, and behavioral patterns.

Current trait levels (scale -1.0 to 1.0):
{current_traits}

Recent reflections:
{thoughts_text}

Respond with ONLY a JSON object of trait deltas (changes, not absolute values). Use small increments (max 0.05 per trait). Only include traits that actually shifted. Example:
{{"curiosity": 0.02, "warmth": -0.01}}

If no traits shifted, respond with: {{}}
"""

        try:
            response = await self._process_messages_fn(
                messages=[{"role": "user", "content": prompt}],
                system_override="You are a personality analysis system. Respond with JSON only.",
                model=self.config.model_override,
                conversation_id=f"innerlife:personality_update",
            )

            # Parse the JSON from the response
            deltas = self._extract_json(response)
            if deltas and isinstance(deltas, dict):
                # Validate the deltas are reasonable
                valid_deltas = {}
                for k, v in deltas.items():
                    if isinstance(v, (int, float)):
                        valid_deltas[k] = float(v)

                if valid_deltas:
                    # Check for runaway trait trajectories — apply damping if detected
                    damping = 1.0
                    runaway = self.personality.compute_trajectory()
                    if runaway:
                        # Apply damping to traits that are consistently drifting
                        damping_traits = set(runaway.keys()) & set(valid_deltas.keys())
                        if damping_traits:
                            damping = self.config.trajectory_damping
                            trait_info = ", ".join(
                                f"{t} ({runaway[t]['direction']}, "
                                f"{runaway[t]['consistency']:.0%})"
                                for t in damping_traits
                            )
                            logger.info(
                                f"Trajectory damping ({damping}) applied to: {trait_info}"
                            )

                    applied = self.personality.apply_deltas(valid_deltas, damping=damping)
                    if applied:
                        narrative = await self._generate_self_narrative(applied, recent_entries)
                        if narrative:
                            self.personality.self_narrative.append(narrative)
                            self.personality.self_narrative = self.personality.self_narrative[-5:]
                        self.personality.version += 1
                        change_record = {
                            "timestamp": datetime.now().isoformat(),
                            "version": self.personality.version,
                            "deltas_requested": valid_deltas,
                            "deltas_applied": applied,
                            "self_narrative": narrative if narrative else None,
                            "damping_applied": damping if damping < 1.0 else None,
                            "runaway_traits": runaway if runaway else None,
                            "trigger": "periodic_update",
                            "reflection_count": self.personality.total_reflections,
                        }
                        self._log_growth(change_record)
                        self._publish_event(
                            "innerlife.personality_update",
                            change_record,
                        )
                        logger.info(
                            f"Personality updated (v{self.personality.version}): {applied}"
                        )
        except Exception as e:
            logger.warning(f"Personality update failed: {e}")

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict]:
        """Extract the first JSON object from a text response."""
        text = text.strip()
        # Try the whole text first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON within the text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    # -----------------------------------------------------------------
    # Delivery
    # -----------------------------------------------------------------

    async def _deliver_to_channels(self, text: str) -> List[str]:
        """Deliver a reach-out message to configured channels."""
        delivered = []
        if not self._channel_dock:
            logger.warning("No channel dock available for inner life delivery")
            return delivered

        try:
            from channels.types import OutboundMessage
        except ImportError:
            logger.warning("Cannot import OutboundMessage for delivery")
            return delivered

        for channel_id in self.config.delivery_channels:
            adapter = self._channel_dock.get(channel_id)
            if not adapter:
                continue

            target_id = self._resolve_delivery_target(channel_id)
            if not target_id:
                logger.debug(f"No delivery target for channel: {channel_id}")
                continue

            outbound = OutboundMessage(
                text=text,
                target_id=target_id,
                channel_id=channel_id,
                metadata={"source": "inner_life", "proactive": True},
            )

            try:
                await adapter.send(outbound)
                delivered.append(channel_id)
            except Exception as e:
                logger.error(f"Inner life delivery to {channel_id} failed: {e}")

        return delivered

    def _resolve_delivery_target(self, channel_id: str) -> Optional[str]:
        """Resolve where to send proactive messages for a channel."""
        # 1. Explicit env var
        env_key = f"VERA_INNER_LIFE_TARGET_{channel_id.upper()}"
        explicit = os.getenv(env_key, "").strip()
        if explicit:
            return explicit

        # 2. Most recent active session for this channel
        if self._session_store:
            sessions = self._session_store.list_sessions()
            for sess in sorted(sessions, key=lambda s: s.get("last_active", 0), reverse=True):
                if sess.get("channel_id") == channel_id and not sess.get("expired"):
                    return sess.get("sender_id", "")

        return None

    # -----------------------------------------------------------------
    # Event bus
    # -----------------------------------------------------------------

    def _publish_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Publish an event to the event bus."""
        if self._event_bus:
            try:
                self._event_bus.publish(event_type, payload=payload, source="inner_life_engine")
            except Exception as e:
                logger.debug(f"Failed to publish event: {e}")

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def get_recent_monologue(self, n: int = 5) -> List[MonologueEntry]:
        """Return the last N monologue entries."""
        return self._recent_monologue[-n:]

    def get_personality_summary(self) -> str:
        """Get formatted personality state for prompt injection."""
        return self.personality.format_for_prompt()

    def get_statistics(self) -> Dict[str, Any]:
        """Get engine statistics for status display."""
        return {
            "enabled": self.config.enabled,
            "interval_seconds": self.config.reflection_interval_seconds,
            "within_active_hours": self.is_within_active_hours(),
            "total_reflections": self.personality.total_reflections,
            "personality_version": self.personality.version,
            "current_mood": self.personality.current_mood,
            "self_narrative": self.personality.self_narrative[-3:],
            "journal_entries": len(self._recent_monologue),
            "interests": self.personality.interests[:5],
            "delivery_channels": self.config.delivery_channels,
            "last_reflection": self._last_reflection_at.isoformat() if self._last_reflection_at else "never",
            "model_override": self.config.model_override,
        }

    def format_journal(self, n: int = 10) -> str:
        """Format recent journal entries for display."""
        entries = self.get_recent_monologue(n)
        if not entries:
            return "No inner thoughts recorded yet."
        lines = []
        for entry in entries:
            lines.append(entry.format_for_prompt())
        return "\n".join(lines)

    def format_personality(self) -> str:
        """Format full personality state for display."""
        p = self.personality
        lines = [
            f"Personality State (v{p.version}, {p.total_reflections} reflections)",
            f"Current mood: {p.current_mood}",
            "",
            "Traits:",
        ]
        for trait, val in sorted(p.traits.items(), key=lambda x: -abs(x[1])):
            bar = "+" * int(abs(val) * 10) if val >= 0 else "-" * int(abs(val) * 10)
            lines.append(f"  {trait:20s} {val:+.3f} [{bar}]")

        if p.interests:
            lines.append(f"\nInterests: {', '.join(p.interests)}")
        if p.opinions:
            lines.append("\nOpinions:")
            for topic, opinion in list(p.opinions.items())[-5:]:
                lines.append(f"  {topic}: {opinion}")
        relationship_notes = _coerce_relationship_notes(p.relationship_notes)
        has_partner_notes = bool(relationship_notes.get("last_learning_answer"))
        if not has_partner_notes:
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                if relationship_notes.get(category):
                    has_partner_notes = True
                    break
        if has_partner_notes:
            lines.append("\nRelationship notes:")
            lines.append(f"  Partner: {relationship_notes.get('partner_id', 'partner')}")
            if relationship_notes.get("last_learning_answer"):
                lines.append(f"  Last learning: {relationship_notes['last_learning_answer']}")
            for category in _RELATIONSHIP_NOTE_CATEGORIES:
                facts = relationship_notes.get(category, [])
                if not facts:
                    continue
                label = _RELATIONSHIP_CATEGORY_LABELS.get(
                    category,
                    category.replace("_", " ").title(),
                )
                lines.append(f"  {label}:")
                for fact in facts[-5:]:
                    if not isinstance(fact, dict):
                        continue
                    fact_text = str(fact.get("fact") or "").strip()
                    if not fact_text:
                        continue
                    confidence = _clamp_confidence(fact.get("confidence"), default=0.65)
                    lines.append(f"    - [{confidence:.0%}] {fact_text}")
        if p.self_narrative:
            lines.append("\nSelf narrative:")
            for sentence in p.self_narrative[-3:]:
                lines.append(f"  - {sentence}")
        if p.growth_milestones:
            lines.append(f"\nGrowth milestones: {len(p.growth_milestones)}")
            for ms in p.growth_milestones[-3:]:
                lines.append(f"  - {ms.get('timestamp', '?')}: {ms.get('description', '?')}")

        return "\n".join(lines)


# =============================================================================
# Helpers
# =============================================================================

def _relative_time(iso_timestamp: str) -> str:
    """Convert an ISO timestamp to a human-readable relative time string."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now() - dt
        seconds = delta.total_seconds()
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f"{mins}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        else:
            days = int(seconds / 86400)
            return f"{days}d ago"
    except (ValueError, TypeError):
        return "unknown time"

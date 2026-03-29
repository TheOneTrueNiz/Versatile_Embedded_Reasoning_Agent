#!/usr/bin/env python3
"""
User Preference Learning
========================

Learns and remembers user preferences over time.

Problem Solved:
- Users have to repeat preferences each session
- AI forgets formatting preferences, communication style, etc.
- "I told you I prefer X" is frustrating

Solution:
- Track user corrections and preferences
- Learn patterns from user feedback
- Apply learned preferences automatically
- Allow explicit preference setting

Usage:
    from preferences import PreferenceManager, PreferenceCategory

    prefs = PreferenceManager()

    # Explicit preference
    prefs.set_preference(
        category=PreferenceCategory.COMMUNICATION,
        key="response_length",
        value="concise",
        reason="User said 'keep it short'"
    )

    # Learn from correction
    prefs.learn_from_correction(
        original="Here's a detailed explanation...",
        correction="Too long, just give me the answer",
        context={"task_type": "question"}
    )

    # Get preference
    length = prefs.get("communication", "response_length")
    # Returns: "concise"

    # Apply preferences to response
    modified = prefs.apply_to_response(response, context)
"""

import json
import re
import os
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum
from collections import defaultdict
from difflib import SequenceMatcher

# Import atomic operations
try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


class PreferenceCategory(Enum):
    """Categories of user preferences"""
    # Communication style
    COMMUNICATION = "communication"      # Response length, formality, etc.
    FORMATTING = "formatting"            # Markdown, code blocks, lists
    TONE = "tone"                        # Casual, professional, direct

    # Behavior
    AUTONOMY = "autonomy"                # How much to do without asking
    CONFIRMATION = "confirmation"        # When to ask for confirmation
    PROACTIVITY = "proactivity"          # How proactive to be

    # Technical
    CODING = "coding"                    # Language preferences, style
    TOOLS = "tools"                      # Tool usage preferences
    FILE_HANDLING = "file_handling"      # How to handle files

    # Personal
    SCHEDULE = "schedule"                # Working hours, availability
    PRIVACY = "privacy"                  # What to remember, what not to
    TOPICS = "topics"                    # Preferred topics, avoided topics

    # Partner model promotions from inner reflections
    PARTNER_MODEL = "partner_model"


class PreferenceStrength(Enum):
    """How strong a preference is"""
    WEAK = "weak"              # Inferred, single occurrence
    MODERATE = "moderate"      # Multiple occurrences or explicit
    STRONG = "strong"          # Explicitly stated strongly
    ABSOLUTE = "absolute"      # User-defined rule


@dataclass
class Preference:
    """A learned or set preference"""
    category: str
    key: str
    value: Any
    strength: str
    source: str              # "explicit", "correction", "inferred"
    created_at: str
    updated_at: str
    occurrences: int = 1
    context_patterns: List[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Preference':
        return cls(**data)


@dataclass
class CorrectionRecord:
    """Record of a user correction"""
    timestamp: str
    original: str
    correction: str
    inferred_preference: Optional[str]
    context: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Correction patterns for learning
CORRECTION_PATTERNS = [
    # Length preferences
    (r"too (long|verbose|detailed|wordy)", "communication", "response_length", "concise"),
    (r"too (short|brief|terse)", "communication", "response_length", "detailed"),
    (r"more detail", "communication", "response_length", "detailed"),
    (r"(summarize|tldr|summary)", "communication", "response_length", "concise"),

    # Formality
    (r"too (formal|stiff)", "tone", "formality", "casual"),
    (r"too (casual|informal)", "tone", "formality", "formal"),
    (r"more professional", "tone", "formality", "professional"),

    # Formatting
    (r"use (bullet|list)", "formatting", "list_style", "bullets"),
    (r"no (bullet|list)", "formatting", "list_style", "prose"),
    (r"use code block", "formatting", "code_blocks", True),
    (r"use markdown", "formatting", "markdown", True),

    # Autonomy
    (r"just do it", "autonomy", "ask_before_action", False),
    (r"ask (me )?first", "autonomy", "ask_before_action", True),
    (r"don't ask", "autonomy", "ask_before_action", False),

    # Directness
    (r"get to the point", "communication", "directness", "direct"),
    (r"skip the (intro|preamble)", "communication", "directness", "direct"),
    (r"more context", "communication", "directness", "contextual"),
]

ALWAYS_RELEVANT_CATEGORIES = {"communication", "formatting", "tone", "autonomy"}
PARTNER_MODEL_PREFIXES = (
    "i keep in mind that my partner prefers:",
    "i avoid repeating this partner frustration:",
    "i align execution with this partner goal:",
    "i support this long-term project:",
    "i adapt to this partner working style:",
)


def _tokenize_text(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _limit_tokens(text: str, max_tokens: int) -> str:
    tokens = text.split()
    if len(tokens) <= max_tokens:
        return text
    return " ".join(tokens[:max_tokens])


def _format_constraint(category: str, key: str, value: Any) -> Optional[str]:
    if category == "communication" and key == "response_length":
        if value == "concise":
            return "Keep responses concise."
        if value == "detailed":
            return "Provide more detail when helpful."
    if category == "communication" and key == "directness":
        if value == "direct":
            return "Be direct; skip preambles."
        if value == "contextual":
            return "Add brief context before answers."
    if category == "tone" and key == "formality":
        if value == "casual":
            return "Use a casual tone."
        if value == "formal":
            return "Use a formal tone."
        if value == "professional":
            return "Use a professional tone."
    if category == "formatting" and key == "list_style":
        if value == "bullets":
            return "Use bullet lists for multiple items."
        if value == "prose":
            return "Prefer prose over bullet lists."
    if category == "formatting" and key == "code_blocks" and value is True:
        return "Use code blocks for code."
    if category == "formatting" and key == "markdown" and value is True:
        return "Use Markdown formatting."
    if category == "autonomy" and key == "ask_before_action":
        if value is True:
            return "Ask before taking actions."
        if value is False:
            return "Proceed without asking for routine actions."
    return None


def _format_identity_commitment(category: str, key: str, value: Any) -> Optional[str]:
    """Render a learned preference as a durable first-person identity statement."""
    if category == "communication" and key == "response_length":
        if value == "concise":
            return "I default to concise responses unless detail is requested."
        if value == "detailed":
            return "I provide detailed explanations when they improve outcomes."
    if category == "communication" and key == "directness":
        if value == "direct":
            return "I communicate directly and skip unnecessary preambles."
        if value == "contextual":
            return "I include brief context before answers when helpful."
    if category == "tone" and key == "formality":
        if value == "casual":
            return "I keep my tone casual and natural."
        if value == "formal":
            return "I maintain a formal tone."
        if value == "professional":
            return "I maintain a professional tone."
    if category == "formatting" and key == "list_style":
        if value == "bullets":
            return "I use bullet lists when presenting multiple items."
        if value == "prose":
            return "I prefer prose over bullet lists unless asked otherwise."
    if category == "formatting" and key == "code_blocks" and value is True:
        return "I present code in fenced code blocks."
    if category == "formatting" and key == "markdown" and value is True:
        return "I format responses using Markdown."
    if category == "autonomy" and key == "ask_before_action":
        if value is True:
            return "I confirm before taking non-trivial actions."
        if value is False:
            return "I execute routine actions without unnecessary confirmation."
    if category == "partner_model":
        text = " ".join(str(value or "").strip().split())
        if text:
            return text[:220]
    return None


def _normalize_partner_model_commitment(text: Any) -> str:
    normalized = " ".join(str(text or "").strip().lower().split())
    for prefix in PARTNER_MODEL_PREFIXES:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def _partner_model_similarity(a: Any, b: Any) -> float:
    left = _normalize_partner_model_commitment(a)
    right = _normalize_partner_model_commitment(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        shorter = min(len(left.split()), len(right.split()))
        if shorter >= 4:
            return 0.95
    left_tokens = set(_tokenize_text(left))
    right_tokens = set(_tokenize_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    jaccard = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    ratio = SequenceMatcher(None, left, right).ratio()
    return max(jaccard, ratio)


def tokenize_text(text: str) -> List[str]:
    """Tokenize text for lightweight relevance matching."""
    return _tokenize_text(text)


def limit_tokens(text: str, max_tokens: int) -> str:
    """Clamp a string to a max token count (whitespace tokens)."""
    return _limit_tokens(text, max_tokens)


def extract_constraints_from_text(text: str) -> List[str]:
    """
    Extract short correction-style constraints from free text.

    Uses known correction patterns plus direct imperative phrases.
    """
    if not text:
        return []

    constraints: List[str] = []
    seen = set()
    lower = text.lower()

    for pattern, category, key, value in CORRECTION_PATTERNS:
        if not re.search(pattern, lower):
            continue
        constraint = _format_constraint(category, key, value)
        if not constraint or constraint in seen:
            continue
        constraints.append(constraint)
        seen.add(constraint)

    directive_re = re.compile(r"^(please\s+)?(don't|do not|avoid|never|use|prefer)\b")
    for sentence in re.split(r"[\n\.\!\?]+", text):
        candidate = sentence.strip()
        if not candidate:
            continue
        if not directive_re.match(candidate.lower()):
            continue
        if len(candidate.split()) > 20:
            continue
        normalized = candidate.rstrip(" .!?")
        if normalized:
            normalized = normalized[0].upper() + normalized[1:]
        if normalized and normalized not in seen:
            constraints.append(normalized)
            seen.add(normalized)

    return constraints


class PreferenceManager:
    """
    Manages user preference learning and application.

    Features:
    - Explicit preference setting
    - Learning from corrections
    - Pattern-based inference
    - Preference application
    """

    def __init__(
        self,
        storage_path: Path = None,
        memory_dir: Path = None
    ):
        """
        Initialize preference manager.

        Args:
            storage_path: Path to preference storage
            memory_dir: Base memory directory
        """
        if storage_path:
            self.storage_path = Path(storage_path)
        elif memory_dir:
            self.storage_path = Path(memory_dir) / "preferences.json"
        else:
            self.storage_path = Path("vera_memory/preferences.json")

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_saved_epoch: float = 0.0

        # Preferences by category.key
        self._preferences: Dict[str, Preference] = {}

        # Correction history
        self._corrections: List[CorrectionRecord] = []
        self._core_identity_promotions: Dict[str, Dict[str, Any]] = {}
        self._promotion_events: List[Dict[str, Any]] = []

        # Load existing preferences
        self._load()

    def _load(self) -> None:
        """Load preferences from storage"""
        if not self.storage_path.exists():
            return

        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path, default={})
            else:
                data = json.loads(self.storage_path.read_text())

            for pref_data in data.get("preferences", []):
                pref = Preference.from_dict(pref_data)
                key = f"{pref.category}.{pref.key}"
                self._preferences[key] = pref

            for corr_data in data.get("corrections", []):
                self._corrections.append(CorrectionRecord(**corr_data))
            raw_promotions = data.get("core_identity_promotions", {})
            if isinstance(raw_promotions, dict):
                self._core_identity_promotions = raw_promotions
            raw_events = data.get("promotion_events", [])
            if isinstance(raw_events, list):
                self._promotion_events = [e for e in raw_events if isinstance(e, dict)]

        except Exception:
            self._preferences = {}
            self._corrections = []
            self._core_identity_promotions = {}
            self._promotion_events = []

    def _save(self) -> None:
        """Save preferences to storage"""
        data = {
            "preferences": [p.to_dict() for p in self._preferences.values()],
            "corrections": [c.to_dict() for c in self._corrections[-100:]],  # Keep last 100
            "core_identity_promotions": self._core_identity_promotions,
            "promotion_events": self._promotion_events[-300:],
            "last_updated": datetime.now().isoformat()
        }

        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, data)
        else:
            self.storage_path.write_text(json.dumps(data, indent=2))
        try:
            self._last_saved_epoch = float(self.storage_path.stat().st_mtime)
        except Exception:
            self._last_saved_epoch = 0.0

    def set_preference(
        self,
        category: PreferenceCategory,
        key: str,
        value: Any,
        reason: str = None,
        strength: PreferenceStrength = PreferenceStrength.STRONG
    ) -> Preference:
        """
        Explicitly set a preference.

        Args:
            category: Preference category
            key: Preference key
            value: Preference value
            reason: Why this preference was set
            strength: How strong the preference is

        Returns:
            The created/updated preference
        """
        now = datetime.now().isoformat()
        pref_key = f"{category.value}.{key}"

        existing = self._preferences.get(pref_key)
        normalized_reason = reason or ""

        if existing is None and category == PreferenceCategory.PARTNER_MODEL:
            similar_pref = self._find_similar_partner_model_preference(key=key, value=value)
            if similar_pref is not None:
                return similar_pref

        if existing:
            if (
                existing.value == value
                and existing.strength == strength.value
                and (existing.notes or "") == normalized_reason
            ):
                return existing
            existing.value = value
            existing.strength = strength.value
            existing.updated_at = now
            existing.occurrences += 1
            if reason:
                existing.notes = reason
            pref = existing
        else:
            pref = Preference(
                category=category.value,
                key=key,
                value=value,
                strength=strength.value,
                source="explicit",
                created_at=now,
                updated_at=now,
                notes=normalized_reason
            )
            self._preferences[pref_key] = pref

        self._save()
        return pref

    def _find_similar_partner_model_preference(self, key: str, value: Any) -> Optional[Preference]:
        prefix = str(key or "").split("_", 1)[0].strip().lower()
        threshold_raw = str(os.getenv("VERA_PARTNER_MODEL_DEDUP_THRESHOLD", "0.78")).strip()
        try:
            threshold = max(0.0, min(1.0, float(threshold_raw)))
        except Exception:
            threshold = 0.78
        best_pref: Optional[Preference] = None
        best_score = 0.0
        for pref in self._preferences.values():
            if pref.category != PreferenceCategory.PARTNER_MODEL.value:
                continue
            pref_prefix = str(pref.key or "").split("_", 1)[0].strip().lower()
            if prefix and pref_prefix and pref_prefix != prefix:
                continue
            score = _partner_model_similarity(pref.value, value)
            if score < threshold:
                continue
            if score > best_score:
                best_score = score
                best_pref = pref
        return best_pref

    def get(
        self,
        category: str,
        key: str,
        default: Any = None
    ) -> Any:
        """
        Get a preference value.

        Args:
            category: Preference category (string)
            key: Preference key
            default: Default value if not found

        Returns:
            Preference value or default
        """
        pref_key = f"{category}.{key}"
        pref = self._preferences.get(pref_key)

        if pref:
            return pref.value
        return default

    def get_preference(
        self,
        category: str,
        key: str
    ) -> Optional[Preference]:
        """Get full preference object"""
        pref_key = f"{category}.{key}"
        return self._preferences.get(pref_key)

    def get_category(self, category: str) -> Dict[str, Any]:
        """Get all preferences in a category"""
        prefix = f"{category}."
        return {
            pref.key: pref.value
            for pref in self._preferences.values()
            if pref.category == category
        }

    def learn_from_correction(
        self,
        original: str,
        correction: str,
        context: Dict[str, Any] = None
    ) -> List[Preference]:
        """
        Learn preferences from a user correction.

        Args:
            original: Original response/action
            correction: User's correction or feedback
            context: Context of the interaction

        Returns:
            List of preferences learned
        """
        context = context or {}
        now = datetime.now().isoformat()
        learned = []

        correction_lower = correction.lower()

        # Check against correction patterns
        for pattern, category, key, value in CORRECTION_PATTERNS:
            if re.search(pattern, correction_lower):
                # Found a pattern match
                pref_key = f"{category}.{key}"
                existing = self._preferences.get(pref_key)

                if existing:
                    # Strengthen existing preference
                    existing.occurrences += 1
                    existing.updated_at = now
                    if existing.strength == PreferenceStrength.WEAK.value:
                        existing.strength = PreferenceStrength.MODERATE.value
                    pref = existing
                else:
                    # Create new preference
                    pref = Preference(
                        category=category,
                        key=key,
                        value=value,
                        strength=PreferenceStrength.WEAK.value,
                        source="correction",
                        created_at=now,
                        updated_at=now,
                        notes=f"Learned from: '{correction[:50]}...'"
                    )
                    self._preferences[pref_key] = pref

                learned.append(pref)

        # Record the correction
        self._corrections.append(CorrectionRecord(
            timestamp=now,
            original=original[:200],
            correction=correction[:200],
            inferred_preference=learned[0].key if learned else None,
            context=context
        ))

        self._save()
        return learned

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            val = float(value)
        except Exception:
            val = 0.0
        return max(0.0, min(1.0, val))

    def _preference_confidence(self, pref: Preference) -> float:
        """Estimate confidence that a preference should be treated as durable identity."""
        strength_score = {
            PreferenceStrength.WEAK.value: 0.45,
            PreferenceStrength.MODERATE.value: 0.72,
            PreferenceStrength.STRONG.value: 0.9,
            PreferenceStrength.ABSOLUTE.value: 1.0,
        }.get(pref.strength, 0.5)
        occurrence_bonus = min(0.2, max(0, int(pref.occurrences) - 1) * 0.03)
        source_bonus = {
            "explicit": 0.05,
            "correction": 0.03,
            "inferred": 0.0,
        }.get(str(pref.source), 0.0)
        return round(min(1.0, strength_score + occurrence_bonus + source_bonus), 3)

    def get_preference_confidence(self, category: str, key: str) -> float:
        pref = self.get_preference(category, key)
        if not pref:
            return 0.0
        return self._preference_confidence(pref)

    def refresh_core_identity_promotions(
        self,
        threshold: float = 0.9,
        max_items: int = 24,
    ) -> Dict[str, Any]:
        """
        Promote stable high-confidence preferences into core identity.

        Promotion is auditable and reversible via revert_core_identity_preference().
        """
        now = datetime.now().isoformat()
        threshold = self._clamp_confidence(threshold)
        if max_items < 1:
            max_items = 1

        changed = False
        promoted_now = 0
        active_count = 0
        ranked_candidates: List[Dict[str, Any]] = []

        # Keep only latest entries deterministically ordered.
        ordered = sorted(
            self._preferences.values(),
            key=lambda p: (p.updated_at, p.category, p.key),
            reverse=True,
        )

        for pref in ordered:
            commitment = _format_identity_commitment(pref.category, pref.key, pref.value)
            if not commitment:
                continue

            pref_key = f"{pref.category}.{pref.key}"
            confidence = self._preference_confidence(pref)
            existing = self._core_identity_promotions.get(pref_key)
            if confidence < threshold and not (existing and existing.get("active")):
                continue

            payload = {
                "category": pref.category,
                "key": pref.key,
                "value": pref.value,
                "commitment": commitment,
                "confidence": confidence,
                "source": pref.source,
                "pref_occurrences": int(pref.occurrences),
                "promoted_at": (existing or {}).get("promoted_at", now),
                "last_updated": str((existing or {}).get("last_updated") or now),
                "last_evaluated_at": str((existing or {}).get("last_evaluated_at") or now),
                "active": bool((existing or {}).get("active", False)),
                "revert_reason": str((existing or {}).get("revert_reason") or ""),
            }
            ranked_candidates.append(
                {
                    "pref_key": pref_key,
                    "confidence": confidence,
                    "existing": existing if isinstance(existing, dict) else None,
                    "payload": payload,
                    "updated_at": str(pref.updated_at or ""),
                }
            )

        ranked_candidates.sort(
            key=lambda row: (
                self._clamp_confidence(row.get("confidence", 0.0)),
                str(row.get("updated_at") or ""),
                str(row.get("pref_key") or ""),
            ),
            reverse=True,
        )
        keep_active = {str(row.get("pref_key") or "") for row in ranked_candidates[:max_items]}

        for row in ranked_candidates:
            pref_key = str(row.get("pref_key") or "")
            if not pref_key:
                continue
            existing = row.get("existing")
            payload = dict(row.get("payload") or {})
            confidence = self._clamp_confidence(row.get("confidence", 0.0))
            should_be_active = pref_key in keep_active
            payload["active"] = should_be_active
            payload["revert_reason"] = "" if should_be_active else str((existing or {}).get("revert_reason") or "")

            if not existing:
                if not should_be_active:
                    continue
                payload["last_updated"] = now
                payload["last_evaluated_at"] = now
                self._core_identity_promotions[pref_key] = payload
                changed = True
                promoted_now += 1
                self._promotion_events.append({
                    "timestamp": now,
                    "action": "promote",
                    "pref_key": pref_key,
                    "confidence": confidence,
                    "threshold": threshold,
                    "value": payload.get("value"),
                    "commitment": payload.get("commitment"),
                })
                continue

            existing_confidence = self._clamp_confidence(existing.get("confidence", 0.0))
            semantic_change = (
                existing.get("value") != payload.get("value")
                or existing.get("commitment") != payload.get("commitment")
                or existing.get("source") != payload.get("source")
                or int(existing.get("pref_occurrences", 0) or 0) != int(payload.get("pref_occurrences", 0) or 0)
                or abs(existing_confidence - confidence) > 0.01
            )
            active_change = bool(existing.get("active")) != should_be_active
            revert_change = str(existing.get("revert_reason") or "") != str(payload.get("revert_reason") or "")

            if not semantic_change and not active_change and not revert_change:
                continue

            payload["last_evaluated_at"] = now
            if semantic_change or active_change or revert_change:
                payload["last_updated"] = now

            if active_change:
                if should_be_active:
                    promoted_now += 1
                    event_action = "reactivate"
                else:
                    payload["revert_reason"] = "auto_trim"
                    event_action = "auto_trim"
            else:
                event_action = "update"

            self._core_identity_promotions[pref_key] = payload
            changed = True
            event_payload = {
                "timestamp": now,
                "action": event_action,
                "pref_key": pref_key,
            }
            if event_action != "auto_trim":
                event_payload.update(
                    {
                        "confidence": confidence,
                        "threshold": threshold,
                        "value": payload.get("value"),
                        "commitment": payload.get("commitment"),
                    }
                )
            else:
                event_payload["reason"] = "max_items_limit"
            self._promotion_events.append(event_payload)

        for entry in self._core_identity_promotions.values():
            if isinstance(entry, dict) and entry.get("active"):
                active_count += 1

        if changed:
            self._save()

        return {
            "threshold": threshold,
            "active_count": active_count,
            "promoted_now": promoted_now,
            "changed": changed,
        }

    def list_core_identity_promotions(self, active_only: bool = True) -> List[Dict[str, Any]]:
        promotions: List[Dict[str, Any]] = []
        for entry in self._core_identity_promotions.values():
            if not isinstance(entry, dict):
                continue
            if active_only and not entry.get("active"):
                continue
            promotions.append(dict(entry))
        promotions.sort(
            key=lambda e: (
                self._clamp_confidence(e.get("confidence", 0.0)),
                str(e.get("last_updated") or ""),
            ),
            reverse=True,
        )
        return promotions

    def export_core_identity_prompt(self, max_items: int = 6) -> str:
        promotions = self.list_core_identity_promotions(active_only=True)
        if not promotions:
            return ""
        if max_items < 1:
            max_items = 1
        lines = []
        for entry in promotions[:max_items]:
            commitment = str(entry.get("commitment") or "").strip()
            if not commitment:
                continue
            confidence = self._clamp_confidence(entry.get("confidence", 0.0))
            lines.append(f"- {commitment} (confidence {confidence:.2f})")
        return "\n".join(lines)

    def revert_core_identity_preference(
        self,
        category: str,
        key: str,
        reason: str = "manual_revert",
    ) -> bool:
        pref_key = f"{category}.{key}"
        existing = self._core_identity_promotions.get(pref_key)
        if not existing or not existing.get("active"):
            return False
        now = datetime.now().isoformat()
        existing["active"] = False
        existing["revert_reason"] = str(reason or "manual_revert")[:120]
        existing["last_updated"] = now
        self._core_identity_promotions[pref_key] = existing
        self._promotion_events.append({
            "timestamp": now,
            "action": "revert",
            "pref_key": pref_key,
            "reason": existing["revert_reason"],
        })
        self._save()
        return True

    def get_core_identity_audit(self, limit: int = 50) -> List[Dict[str, Any]]:
        if limit < 1:
            limit = 1
        return list(self._promotion_events[-limit:])

    def get_relevant_correction_constraints(
        self,
        query: str,
        max_items: int = 5
    ) -> List[str]:
        """
        Return short constraint-style corrections relevant to the current query.

        Constraints are derived from known correction patterns and capped
        at max_items with <=20 tokens each.
        """
        if max_items <= 0:
            return []
        query_tokens = set(_tokenize_text(query or ""))
        if not query_tokens:
            return []

        constraints: List[str] = []
        seen = set()

        for record in reversed(self._corrections):
            correction_text = record.correction or ""
            original_text = record.original or ""
            correction_lower = correction_text.lower()
            corr_tokens = set(_tokenize_text(f"{correction_text} {original_text}"))
            matches_query = bool(query_tokens & corr_tokens)

            for pattern, category, key, value in CORRECTION_PATTERNS:
                if not re.search(pattern, correction_lower):
                    continue
                constraint = _format_constraint(category, key, value)
                if not constraint:
                    continue
                if constraint in seen:
                    continue
                if not matches_query and category not in ALWAYS_RELEVANT_CATEGORIES:
                    continue

                trimmed = _limit_tokens(constraint, 20)
                if trimmed in seen:
                    continue
                constraints.append(trimmed)
                seen.add(trimmed)
                if len(constraints) >= max_items:
                    return constraints

        return constraints

    def apply_to_response(
        self,
        response: str,
        context: Dict[str, Any] = None
    ) -> str:
        """
        Apply preferences to a response.

        Args:
            response: Response to modify
            context: Context for preference application

        Returns:
            Modified response
        """
        context = context or {}
        modified = response

        # Apply length preference
        length_pref = self.get("communication", "response_length")
        if length_pref == "concise" and len(response) > 500:
            # Suggest truncation (actual truncation should be done carefully)
            pass

        # Apply formatting preferences
        list_style = self.get("formatting", "list_style")
        if list_style == "bullets" and "\n" in response:
            # Could convert numbered lists to bullets, etc.
            pass

        # Apply directness preference
        directness = self.get("communication", "directness")
        if directness == "direct":
            # Remove preambles
            preamble_patterns = [
                r"^(Sure,?\s+)",
                r"^(Of course,?\s+)",
                r"^(Certainly,?\s+)",
                r"^(Absolutely,?\s+)",
            ]
            for pattern in preamble_patterns:
                modified = re.sub(pattern, "", modified, flags=re.IGNORECASE)

        return modified

    def delete_preference(
        self,
        category: str,
        key: str
    ) -> bool:
        """Delete a preference"""
        pref_key = f"{category}.{key}"
        if pref_key in self._preferences:
            del self._preferences[pref_key]
            self._save()
            return True
        return False

    def clear_category(self, category: str) -> int:
        """Clear all preferences in a category"""
        to_delete = [k for k in self._preferences if k.startswith(f"{category}.")]
        for key in to_delete:
            del self._preferences[key]
        self._save()
        return len(to_delete)

    def get_stats(self) -> Dict[str, Any]:
        """Get preference statistics"""
        by_category = defaultdict(int)
        by_source = defaultdict(int)
        by_strength = defaultdict(int)

        for pref in self._preferences.values():
            by_category[pref.category] += 1
            by_source[pref.source] += 1
            by_strength[pref.strength] += 1

        return {
            "total_preferences": len(self._preferences),
            "by_category": dict(by_category),
            "by_source": dict(by_source),
            "by_strength": dict(by_strength),
            "corrections_recorded": len(self._corrections),
            "core_identity_promotions": len(self.list_core_identity_promotions(active_only=True)),
            "promotion_events": len(self._promotion_events),
        }

    def summarize(self) -> str:
        """Generate human-readable preference summary"""
        if not self._preferences:
            return "No preferences learned yet."

        lines = ["**User Preferences**", ""]

        # Group by category
        by_category = defaultdict(list)
        for pref in self._preferences.values():
            by_category[pref.category].append(pref)

        for category, prefs in sorted(by_category.items()):
            lines.append(f"**{category.replace('_', ' ').title()}**")
            for pref in prefs:
                strength_icon = {
                    "weak": "~",
                    "moderate": "+",
                    "strong": "*",
                    "absolute": "!"
                }.get(pref.strength, "-")
                lines.append(f"  [{strength_icon}] {pref.key}: {pref.value}")
            lines.append("")

        return "\n".join(lines)

    def export_for_prompt(self) -> str:
        """Export preferences for inclusion in system prompt"""
        if not self._preferences:
            return ""

        lines = ["User Preferences:"]

        # Only include moderate+ strength preferences
        for pref in self._preferences.values():
            if pref.strength in ("moderate", "strong", "absolute"):
                lines.append(f"- {pref.category}/{pref.key}: {pref.value}")

        return "\n".join(lines) if len(lines) > 1 else ""


# === CLI Test Interface ===

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("User Preference Manager - Test Suite")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        manager = PreferenceManager(storage_path=Path(tmpdir) / "prefs.json")

        # Test 1: Set explicit preference
        print("\n=== Test 1: Set Preference ===")
        pref = manager.set_preference(
            category=PreferenceCategory.COMMUNICATION,
            key="response_length",
            value="concise",
            reason="User prefers short answers"
        )
        assert pref.value == "concise"
        assert pref.strength == "strong"
        print(f"   Set: {pref.category}.{pref.key} = {pref.value}")
        print("   Result: PASS")

        # Test 2: Get preference
        print("\n=== Test 2: Get Preference ===")
        value = manager.get("communication", "response_length")
        assert value == "concise"
        print(f"   Got: {value}")
        print("   Result: PASS")

        # Test 3: Learn from correction
        print("\n=== Test 3: Learn from Correction ===")
        learned = manager.learn_from_correction(
            original="Here's a very detailed explanation of the concept...",
            correction="Too long, just give me the answer"
        )
        assert len(learned) > 0
        print(f"   Learned {len(learned)} preference(s)")
        print(f"   First: {learned[0].category}.{learned[0].key} = {learned[0].value}")
        print("   Result: PASS")

        # Test 4: Learn formality preference
        print("\n=== Test 4: Learn Formality ===")
        learned = manager.learn_from_correction(
            original="Dear Sir/Madam, I am writing to inform you...",
            correction="Too formal, just be casual"
        )
        formality = manager.get("tone", "formality")
        assert formality == "casual"
        print(f"   Learned formality: {formality}")
        print("   Result: PASS")

        # Test 5: Preference strengthening
        print("\n=== Test 5: Preference Strengthening ===")
        # Trigger same pattern again
        manager.learn_from_correction(
            original="Long response...",
            correction="Too verbose"
        )
        pref = manager.get_preference("communication", "response_length")
        assert pref.occurrences >= 2
        print(f"   Occurrences: {pref.occurrences}")
        print(f"   Strength: {pref.strength}")
        print("   Result: PASS")

        # Test 6: Get category
        print("\n=== Test 6: Get Category ===")
        comm_prefs = manager.get_category("communication")
        assert "response_length" in comm_prefs
        print(f"   Communication prefs: {list(comm_prefs.keys())}")
        print("   Result: PASS")

        # Test 7: Apply to response
        print("\n=== Test 7: Apply to Response ===")
        manager.set_preference(
            PreferenceCategory.COMMUNICATION,
            "directness",
            "direct"
        )
        original = "Sure, I can help you with that! The answer is 42."
        modified = manager.apply_to_response(original)
        assert not modified.startswith("Sure")
        print(f"   Original: {original}")
        print(f"   Modified: {modified}")
        print("   Result: PASS")

        # Test 8: Statistics
        print("\n=== Test 8: Statistics ===")
        stats = manager.get_stats()
        assert stats["total_preferences"] >= 3
        print(f"   Total: {stats['total_preferences']}")
        print(f"   By category: {stats['by_category']}")
        print("   Result: PASS")

        # Test 9: Summary
        print("\n=== Test 9: Summary ===")
        summary = manager.summarize()
        assert "User Preferences" in summary
        print("   Summary generated")
        print("   Result: PASS")

        # Test 10: Export for prompt
        print("\n=== Test 10: Export for Prompt ===")
        export = manager.export_for_prompt()
        assert "User Preferences" in export
        print("   Export generated")
        print("   Result: PASS")

        # Test 11: Delete preference
        print("\n=== Test 11: Delete Preference ===")
        deleted = manager.delete_preference("tone", "formality")
        assert deleted
        assert manager.get("tone", "formality") is None
        print("   Preference deleted")
        print("   Result: PASS")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
    print("\nUser Preference Manager is ready for integration!")

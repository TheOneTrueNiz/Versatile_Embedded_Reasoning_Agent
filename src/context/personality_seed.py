#!/usr/bin/env python3
"""
Personality seed profile management for VERA.

This module loads a structured, layered seed profile and exports compact
identity blocks for runtime prompt injection. It also records seed metadata
for auditability and reinforcement tracking.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.atomic_io import atomic_json_write, safe_json_read

logger = logging.getLogger(__name__)

DEFAULT_PERSONALITY_SEED_PATH = Path(
    os.getenv("VERA_PERSONALITY_SEED_PATH", "config/persona/personality_seed.json")
)

_SECTION_ORDER = (
    "north_star",
    "behavior_policy",
    "core_identity",
    "guiding_principles",
    "role_models",
    "inspirations",
    "personal_tastes",
)

_DEFAULT_SECTION_MUTABILITY = {
    "north_star": False,
    "behavior_policy": False,
    "core_identity": False,
    "guiding_principles": False,
    "role_models": True,
    "inspirations": True,
    "personal_tastes": True,
}


def _utc_now_iso() -> str:
    return datetime.now().isoformat()


def _clean_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return text[:limit]


def _slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    base = re.sub(r"_+", "_", base).strip("_")
    return base or "item"


def _coerce_bool(value: Any, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "off", "no", ""}
    if isinstance(value, (int, float)):
        return value != 0
    return fallback


def _clamp_confidence(value: Any, fallback: float = 0.9) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = fallback
    return max(0.0, min(1.0, parsed))


def _normalize_seed_text(section: str, raw_item: Any) -> str:
    if isinstance(raw_item, str):
        return _clean_text(raw_item)
    if not isinstance(raw_item, dict):
        return ""

    if section == "role_models":
        name = _clean_text(raw_item.get("name"), limit=80)
        traits = _clean_text(raw_item.get("traits"), limit=220)
        if name and traits:
            return f"{name}: {traits}"
        if name:
            return name

    if section == "personal_tastes":
        key = _clean_text(raw_item.get("key"), limit=80)
        value = _clean_text(raw_item.get("value"), limit=180)
        if key and value:
            label = key.replace("_", " ").strip()
            if label:
                label = label[0].upper() + label[1:]
            return f"{label}: {value}"

    for key in ("text", "value", "quote", "statement"):
        text = _clean_text(raw_item.get(key))
        if text:
            return text
    return ""


class PersonalitySeedManager:
    """Loads and compacts a layered personality seed profile."""

    def __init__(
        self,
        memory_dir: Path,
        seed_path: Optional[Path] = None,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        if seed_path is not None:
            self.seed_path = Path(seed_path)
        else:
            env_path = os.getenv("VERA_PERSONALITY_SEED_PATH", "").strip()
            self.seed_path = Path(env_path) if env_path else DEFAULT_PERSONALITY_SEED_PATH

        self.state_path = self.memory_dir / "personality_seed_state.json"

        self.enabled = False
        self.seed_id = ""
        self.profile_name = ""
        self.seed_hash = ""
        self.compaction = {
            "max_role_models": 5,
            "max_principles": 4,
            "max_tastes": 5,
            "max_inspirations": 3,
        }
        self.sections: Dict[str, List[Dict[str, Any]]] = {section: [] for section in _SECTION_ORDER}

        self._state = safe_json_read(self.state_path, default={}) or {}
        if not isinstance(self._state, dict):
            self._state = {}

        self.reload()

    def reload(self) -> bool:
        self.sections = {section: [] for section in _SECTION_ORDER}
        self.enabled = False
        self.seed_id = ""
        self.profile_name = ""
        self.seed_hash = ""

        if not self.seed_path.exists():
            logger.info("Personality seed not found at %s", self.seed_path)
            return False

        try:
            payload = json.loads(self.seed_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to parse personality seed file %s: %s", self.seed_path, exc)
            return False

        if not isinstance(payload, dict):
            logger.warning("Personality seed payload must be an object: %s", self.seed_path)
            return False

        self.enabled = _coerce_bool(payload.get("enabled", True), True)
        self.seed_id = _clean_text(payload.get("seed_id"), limit=80) or "personality_seed"
        self.profile_name = _clean_text(payload.get("profile_name"), limit=120) or "Personality Seed"

        raw_compaction = payload.get("prompt_compaction", {})
        if isinstance(raw_compaction, dict):
            for key in self.compaction:
                try:
                    parsed = int(raw_compaction.get(key, self.compaction[key]))
                except Exception:
                    parsed = self.compaction[key]
                self.compaction[key] = max(1, parsed)

        for section in _SECTION_ORDER:
            self.sections[section] = self._normalize_section(section, payload.get(section, []))

        canonical = {
            "seed_id": self.seed_id,
            "sections": self.sections,
        }
        digest = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        self.seed_hash = digest[:16]

        self._refresh_state()
        return self.enabled

    def _normalize_section(self, section: str, raw_items: Any) -> List[Dict[str, Any]]:
        items = raw_items if isinstance(raw_items, list) else []
        normalized: List[Dict[str, Any]] = []
        seen = set()
        default_mutable = _DEFAULT_SECTION_MUTABILITY.get(section, True)

        for idx, raw_item in enumerate(items):
            text = _normalize_seed_text(section, raw_item)
            if not text:
                continue
            dedupe_key = text.lower()
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            if isinstance(raw_item, dict):
                raw_id = _clean_text(raw_item.get("id"), limit=80)
                confidence = _clamp_confidence(raw_item.get("confidence"), fallback=0.9)
                mutable = _coerce_bool(raw_item.get("mutable"), default_mutable)
                source = _clean_text(raw_item.get("source"), limit=32) or "seed"
            else:
                raw_id = ""
                confidence = 0.9
                mutable = default_mutable
                source = "seed"

            item_id = raw_id or f"{section}_{idx + 1}_{_slugify(text)[:40]}"
            normalized.append(
                {
                    "id": item_id,
                    "section": section,
                    "text": text,
                    "source": source,
                    "confidence": confidence,
                    "mutable": mutable,
                    "last_reinforced_at": "",
                }
            )
            if len(normalized) >= 30:
                break
        return normalized

    def _refresh_state(self) -> None:
        now_iso = _utc_now_iso()
        previous_hash = str(self._state.get("seed_hash") or "")
        previous_items = self._state.get("items", {})
        if not isinstance(previous_items, dict):
            previous_items = {}

        applied_at = str(self._state.get("applied_at") or "")
        if not applied_at or previous_hash != self.seed_hash:
            applied_at = now_iso

        indexed_items: Dict[str, Dict[str, Any]] = {}
        for section in _SECTION_ORDER:
            for item in self.sections.get(section, []):
                existing = previous_items.get(item["id"], {}) if isinstance(previous_items, dict) else {}
                item_state = {
                    "id": item["id"],
                    "section": item["section"],
                    "text": item["text"],
                    "source": item["source"],
                    "confidence": item["confidence"],
                    "mutable": item["mutable"],
                    "first_applied_at": str(existing.get("first_applied_at") or applied_at or now_iso),
                    "last_reinforced_at": now_iso,
                }
                indexed_items[item["id"]] = item_state
                item["last_reinforced_at"] = now_iso

        self._state = {
            "enabled": self.enabled,
            "seed_path": str(self.seed_path),
            "seed_id": self.seed_id,
            "profile_name": self.profile_name,
            "seed_hash": self.seed_hash,
            "applied_at": applied_at,
            "last_reinforced_at": now_iso,
            "item_count": len(indexed_items),
            "items": indexed_items,
        }
        atomic_json_write(self.state_path, self._state)

    def active_item_count(self) -> int:
        if not self.enabled:
            return 0
        return sum(len(items) for items in self.sections.values())

    def get_state(self) -> Dict[str, Any]:
        return dict(self._state)

    def _section_texts(self, section: str, max_items: int) -> List[str]:
        if not self.enabled or max_items <= 0:
            return []
        items = self.sections.get(section, [])
        lines: List[str] = []
        for item in items[:max_items]:
            text = _clean_text(item.get("text"), limit=240)
            if text:
                lines.append(text)
        return lines

    def export_identity_prompt(self) -> str:
        """
        Build compact identity injection for the main system prompt.
        """
        if not self.enabled:
            return ""

        lines: List[str] = [f"- Seed profile: {self.profile_name} ({self.seed_id})"]

        north_star = self._section_texts("north_star", 1)
        if north_star:
            lines.append(f"- North star: {north_star[0]}")

        behavior = self._section_texts("behavior_policy", 2)
        if behavior:
            lines.append(f"- Behavior guardrails: {'; '.join(behavior)}")

        core_identity = self._section_texts("core_identity", 2)
        if core_identity:
            lines.append(f"- Core identity: {'; '.join(core_identity)}")

        principles = self._section_texts("guiding_principles", self.compaction["max_principles"])
        if principles:
            lines.append(f"- Guiding principles: {'; '.join(principles)}")

        role_models_raw = self._section_texts("role_models", self.compaction["max_role_models"])
        if role_models_raw:
            role_models = [entry.split(":", 1)[0].strip() for entry in role_models_raw]
            lines.append(f"- Role-model lens: {', '.join(role_models)}")

        tastes = self._section_texts("personal_tastes", self.compaction["max_tastes"])
        if tastes:
            lines.append(f"- Personal touches: {'; '.join(tastes)}")

        inspirations = self._section_texts("inspirations", self.compaction["max_inspirations"])
        if inspirations:
            lines.append(f"- Inspiration anchors: {'; '.join(inspirations)}")

        return "\n".join(lines)

    def export_reflection_compass(self) -> str:
        """
        Build compact identity compass for private reflection prompts.
        """
        if not self.enabled:
            return ""

        lines: List[str] = []
        north_star = self._section_texts("north_star", 1)
        if north_star:
            lines.append(f"North star: {north_star[0]}")

        behavior = self._section_texts("behavior_policy", 2)
        if behavior:
            lines.append(f"Behavior guardrails: {'; '.join(behavior)}")

        core_identity = self._section_texts("core_identity", 2)
        if core_identity:
            lines.append(f"Core identity commitments: {'; '.join(core_identity)}")

        principles = self._section_texts("guiding_principles", min(3, self.compaction["max_principles"]))
        if principles:
            lines.append(f"Decision lens: {'; '.join(principles)}")

        role_models_raw = self._section_texts("role_models", min(4, self.compaction["max_role_models"]))
        if role_models_raw:
            role_models = [entry.split(":", 1)[0].strip() for entry in role_models_raw]
            lines.append(f"Role models to emulate: {', '.join(role_models)}")

        tastes = self._section_texts("personal_tastes", min(3, self.compaction["max_tastes"]))
        if tastes:
            lines.append(f"Warm personal touches: {'; '.join(tastes)}")

        return "\n".join(lines)

#!/usr/bin/env python3
"""
Flight Recorder - Unified Transition Log for Self-Improvement
=============================================================

Records (state, action, reward) transitions for LLM + tool calls
with lightweight AIR (Automatic Intermediate Reward) scoring.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import copy

try:
    from learning.reward_model import DEFAULT_MODEL_PATH, RewardModel, load_reward_model
    HAS_REWARD_MODEL = True
except Exception:
    HAS_REWARD_MODEL = False
    RewardModel = None
    DEFAULT_MODEL_PATH = Path("vera_memory/flight_recorder/reward_model.json")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}...[truncated]"


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=True, default=str)
    except Exception:
        return str(value)


@dataclass
class AIRResult:
    score: float
    reason: str


class FlightRecorder:
    """
    Lightweight transition logger with AIR scoring.

    Writes NDJSON entries under vera_memory/flight_recorder by default.
    """

    def __init__(
        self,
        base_dir: Path,
        enabled: bool = True,
        max_snapshot_chars: int = 2000,
        max_action_chars: int = 1200,
        max_result_chars: int = 2000,
    ):
        self.base_dir = Path(base_dir)
        self.enabled = enabled
        self.max_snapshot_chars = max_snapshot_chars
        self.max_action_chars = max_action_chars
        self.max_result_chars = max_result_chars

        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.transitions_path = self.base_dir / "transitions.ndjson"
        self._lock = threading.Lock()
        self._last_tool_hash: Dict[str, str] = {}
        self._reward_model_enabled = os.getenv("VERA_REWARD_MODEL_ENABLED", "0") == "1"
        self._reward_model_path = Path(os.getenv("VERA_REWARD_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
        self._reward_model: Optional[RewardModel] = None
        if self._reward_model_enabled and HAS_REWARD_MODEL and self._reward_model_path.exists():
            try:
                self._reward_model = load_reward_model(self._reward_model_path)
            except Exception:
                self._reward_model = None

    def _append(self, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        line = _json_dumps(payload)
        with self._lock:
            with self.transitions_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def _air_score_tool(
        self,
        tool_name: str,
        success: bool,
        output_text: str,
        error: Optional[str] = None,
        conversation_id: str = "default",
    ) -> AIRResult:
        if not success:
            return AIRResult(score=-1.0, reason="tool_error")
        if error:
            return AIRResult(score=-1.0, reason="tool_error")

        if not output_text.strip():
            return AIRResult(score=-0.5, reason="empty_output")

        key = f"{conversation_id}:{tool_name}"
        output_hash = _hash_text(output_text)
        if self._last_tool_hash.get(key) == output_hash:
            return AIRResult(score=-0.5, reason="stalled_repeat_output")

        self._last_tool_hash[key] = output_hash
        return AIRResult(score=0.5, reason="tool_success")

    def _air_score_llm(self, success: bool, output_text: str) -> AIRResult:
        if not success:
            return AIRResult(score=-1.0, reason="llm_error")
        if not output_text.strip():
            return AIRResult(score=-0.2, reason="empty_llm_output")
        return AIRResult(score=0.0, reason="llm_neutral")

    def log_transition(
        self,
        state_snapshot: str,
        action: Dict[str, Any],
        result: Dict[str, Any],
        air: AIRResult,
        meta: Optional[Dict[str, Any]] = None,
        provenance: Optional[Dict[str, Any]] = None,
    ) -> None:
        snapshot = _truncate(state_snapshot, self.max_snapshot_chars)
        action_text = _truncate(_json_dumps(action), self.max_action_chars)
        result_text = _truncate(_json_dumps(result), self.max_result_chars)

        payload = {
            "type": "transition",
            "uuid": str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "context_hash": _hash_text(snapshot) if snapshot else "",
            "context_snapshot": snapshot,
            "action": action,
            "action_preview": action_text,
            "result": result,
            "result_preview": result_text,
            "air_score": air.score,
            "air_reason": air.reason,
            "is_failure": air.score < 0,
            "meta": meta or {},
            "provenance": provenance or {},
        }
        self._append(payload)

    def record_tool_call(
        self,
        *,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
        success: bool,
        latency_ms: float,
        conversation_id: str,
        source_type: str = "tool",
        error: Optional[str] = None,
    ) -> None:
        result_text = _json_dumps(result)
        air = self._air_score_tool(
            tool_name=tool_name,
            success=success,
            output_text=result_text,
            error=error,
            conversation_id=conversation_id or "default",
        )

        state_snapshot = _json_dumps({
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "params": params,
        })
        action = {
            "type": "tool_call",
            "tool_name": tool_name,
            "params": params,
        }
        result_payload = {
            "success": success,
            "output": result,
            "error": error,
        }
        meta = {
            "latency_ms": round(latency_ms, 2),
            "success": success,
        }
        base_air = air
        air, reward_score = self._apply_reward_model(action, result_payload, meta, air)
        if reward_score is not None:
            meta["reward_score"] = reward_score
            meta["air_base_score"] = base_air.score
            meta["reward_model_path"] = str(self._reward_model_path)
        provenance = {
            "source_type": source_type,
            "tool": tool_name,
        }
        self.log_transition(state_snapshot, action, result_payload, air, meta, provenance)

    def record_llm_call(
        self,
        *,
        model: str,
        messages: Any,
        response: Any,
        latency_ms: float,
        success: bool,
        tool_choice: Optional[Any] = None,
    ) -> None:
        state_snapshot = _truncate(_json_dumps(messages), self.max_snapshot_chars)
        response_text = _json_dumps(response)
        air = self._air_score_llm(success=success, output_text=response_text)

        action = {
            "type": "llm_call",
            "model": model,
            "tool_choice": tool_choice,
        }
        result_payload = {
            "success": success,
            "response": response,
        }
        meta = {
            "latency_ms": round(latency_ms, 2),
            "success": success,
        }
        base_air = air
        air, reward_score = self._apply_reward_model(action, result_payload, meta, air)
        if reward_score is not None:
            meta["reward_score"] = reward_score
            meta["air_base_score"] = base_air.score
            meta["reward_model_path"] = str(self._reward_model_path)
        provenance = {
            "source_type": "llm",
            "model": model,
        }
        self.log_transition(state_snapshot, action, result_payload, air, meta, provenance)

    def get_stats(self) -> Dict[str, Any]:
        if not self.transitions_path.exists():
            return {"path": str(self.transitions_path), "entries": 0}
        try:
            with self.transitions_path.open("r", encoding="utf-8") as handle:
                count = sum(1 for _ in handle)
        except Exception:
            count = 0
        return {
            "path": str(self.transitions_path),
            "entries": count,
            "enabled": self.enabled,
        }

    def record_task_feedback(
        self,
        *,
        conversation_id: str,
        user_message: str,
        score: float,
        reason: str,
    ) -> None:
        air = AIRResult(score=score, reason=reason)
        state_snapshot = _json_dumps({
            "conversation_id": conversation_id,
            "user_message": user_message,
        })
        action = {
            "type": "user_feedback",
            "conversation_id": conversation_id,
        }
        result_payload = {
            "message": user_message,
            "score": score,
            "reason": reason,
        }
        meta = {
            "feedback": True,
        }
        provenance = {
            "source_type": "user",
        }
        self.log_transition(state_snapshot, action, result_payload, air, meta, provenance)

    def record_routing_decision(
        self,
        *,
        conversation_id: str,
        query_preview: str,
        selected_categories: list,
        selected_servers: list,
        tool_confidence: dict,
        pass1_confidence: float,
        used_llm_router: bool,
        model_selected: str,
        model_reason: str,
    ) -> None:
        """Record a tool/model routing decision as a learning signal."""
        air = AIRResult(score=0.0, reason="routing_decision")
        state_snapshot = _json_dumps({
            "conversation_id": conversation_id,
            "query_preview": _truncate(query_preview, 200),
        })
        action = {
            "type": "routing_decision",
            "selected_categories": selected_categories,
            "selected_servers": selected_servers,
            "model_selected": model_selected,
            "model_reason": model_reason,
            "pass1_confidence": round(pass1_confidence, 3),
            "used_llm_router": used_llm_router,
        }
        top_tools = dict(sorted(tool_confidence.items(), key=lambda x: -x[1])[:10]) if tool_confidence else {}
        result_payload = {
            "tool_count": len(tool_confidence),
            "top_tools": top_tools,
        }
        meta = {"routing": True}
        provenance = {"source_type": "smart_router"}
        self.log_transition(state_snapshot, action, result_payload, air, meta, provenance)

    def record_model_selection(
        self,
        *,
        conversation_id: str,
        model_selected: str,
        reason: str,
        alternatives: list,
    ) -> None:
        """Record model variant selection as a learning signal."""
        air = AIRResult(score=0.0, reason="model_selection")
        state_snapshot = _json_dumps({"conversation_id": conversation_id})
        action = {
            "type": "model_selection",
            "model": model_selected,
            "reason": reason,
            "alternatives": alternatives,
        }
        result_payload = {"model": model_selected}
        meta = {"routing": True}
        provenance = {"source_type": "model_router"}
        self.log_transition(state_snapshot, action, result_payload, air, meta, provenance)

    def _apply_reward_model(
        self,
        action: Dict[str, Any],
        result_payload: Dict[str, Any],
        meta: Dict[str, Any],
        air: AIRResult,
    ) -> tuple[AIRResult, Optional[float]]:
        if not self._reward_model:
            return air, None
        entry = {
            "action": action,
            "result": result_payload,
            "meta": meta,
            "action_preview": _json_dumps(action),
            "air_score": air.score,
        }
        try:
            reward_score = float(self._reward_model.score_entry(entry))
        except Exception:
            return air, None
        combined = max(-1.0, min(1.0, 0.7 * air.score + 0.3 * reward_score))
        return AIRResult(score=combined, reason=air.reason), reward_score

    def export_memvid(
        self,
        output_path: Path,
        title: str = "vera_flight_recorder",
        limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Export transitions to a Memvid JSON archive.
        """
        try:
            from memory.storage.memvid import MemvidArchive
            from memory.storage.mem_cube import MemCube, EventType
        except Exception as exc:
            raise RuntimeError(f"Memvid unavailable: {exc}") from exc

        if not self.transitions_path.exists():
            raise FileNotFoundError(f"Transitions not found: {self.transitions_path}")

        transitions: list[dict[str, Any]] = []
        with self.transitions_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    transitions.append(json.loads(line))
                except Exception:
                    continue

        if limit:
            transitions = transitions[-limit:]

        cubes = []
        for entry in transitions:
            air_score = float(entry.get("air_score", 0.0))
            importance = max(0.0, min(1.0, 0.5 + 0.5 * air_score))
            content = copy.deepcopy(entry)
            cube = MemCube(
                content=content,
                event_type=EventType.EXTERNAL_DATA,
                importance=importance,
                tags=["flight_recorder", "transition"],
                provenance={
                    "source_type": "flight_recorder",
                    "air_score": air_score,
                },
            )
            cubes.append(cube)

        archive = MemvidArchive()
        video_id = archive.create_video(cubes, title=title)
        payload = archive.export_video(video_id)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        return payload

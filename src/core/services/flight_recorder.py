#!/usr/bin/env python3
"""
Flight Recorder - Unified Transition Log for Self-Improvement
=============================================================

Records (state, action, reward) transitions for LLM + tool calls
with lightweight AIR (Automatic Intermediate Reward) scoring.
"""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import threading
import uuid
import gzip
import shutil
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List
import copy

logger = logging.getLogger(__name__)

try:
    from memory.persistence.atomic_io import atomic_ndjson_append
    HAS_ATOMIC_APPEND = True
except Exception:
    HAS_ATOMIC_APPEND = False

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


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    )


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _compute_ledger_hash_self(record: Dict[str, Any]) -> str:
    payload = {k: v for k, v in record.items() if k != "hash_self"}
    return _sha256_hex(_canonical_json(payload))


def _read_last_nonempty_json_line(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            return None
    return None


def _read_last_nonempty_json_line_from_lines(lines: List[str]) -> Optional[Dict[str, Any]]:
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            return None
    return None


def verify_flight_ledger(
    ledger_path: Path,
    *,
    cross_check_source: bool = False,
    max_errors: int = 10,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    records = 0
    prev_hash: Optional[str] = None

    if not ledger_path.exists():
        return {
            "ok": False,
            "records": 0,
            "errors": [f"ledger_missing:{ledger_path}"],
            "warnings": [],
            "exit_code": 30,
        }

    def _find_source_event(source_path: Path, event_uuid: str) -> Optional[Dict[str, Any]]:
        if not source_path.exists() or not event_uuid:
            return None
        try:
            with source_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if str(obj.get("uuid") or "") == event_uuid:
                        return obj
        except Exception:
            return None
        return None

    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_num, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            records += 1
            try:
                record = json.loads(line)
            except Exception:
                errors.append(f"line_{line_num}:invalid_json")
                if len(errors) >= max_errors:
                    break
                continue

            record_type = str(record.get("record_type") or "")
            hash_prev = str(record.get("hash_prev") or "")
            hash_self = str(record.get("hash_self") or "")

            if records == 1:
                if record_type != "GENESIS":
                    errors.append(f"line_{line_num}:missing_genesis")
                if hash_prev != ("0" * 64):
                    errors.append(f"line_{line_num}:genesis_prev_hash_invalid")
            elif prev_hash and hash_prev != prev_hash:
                errors.append(f"line_{line_num}:hash_prev_mismatch")

            expected_hash = _compute_ledger_hash_self(record)
            if hash_self != expected_hash:
                errors.append(f"line_{line_num}:hash_self_mismatch")

            if cross_check_source and record_type != "GENESIS":
                source_file = Path(str(record.get("source_file") or ""))
                event_uuid = str(record.get("event_uuid") or "")
                source_obj = _find_source_event(source_file, event_uuid)
                if source_obj is None:
                    warnings.append(f"line_{line_num}:source_event_missing")
                else:
                    payload_sha256 = str(record.get("payload_sha256") or "")
                    source_sha256 = _sha256_hex(_canonical_json(source_obj))
                    if payload_sha256 != source_sha256:
                        errors.append(f"line_{line_num}:payload_sha256_mismatch")

            prev_hash = hash_self
            if len(errors) >= max_errors:
                break

    exit_code = 30 if errors else (20 if warnings else 0)
    return {
        "ok": not errors,
        "records": records,
        "errors": errors,
        "warnings": warnings,
        "exit_code": exit_code,
    }


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
        self.ledger_path = self.base_dir / "ledger.jsonl"
        self._max_mb = self._safe_env_float("VERA_FLIGHT_RECORDER_MAX_MB", 50.0, minimum=1.0)
        self._max_backups = self._safe_env_int("VERA_FLIGHT_RECORDER_MAX_BACKUPS", 2, minimum=1)
        self._compress_backups = os.getenv("VERA_FLIGHT_RECORDER_COMPRESS_BACKUPS", "1").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._compression_level = self._safe_env_int("VERA_FLIGHT_RECORDER_GZIP_LEVEL", 6, minimum=1, maximum=9)
        self._ledger_enabled = os.getenv("VERA_FLIGHT_LEDGER_ENABLED", "1").lower() not in {"0", "false", "off"}
        self._lock = threading.Lock()
        self._last_tool_hash: Dict[str, str] = {}
        self._ledger_last_hash: Optional[str] = None
        self._reward_model_enabled = os.getenv("VERA_REWARD_MODEL_ENABLED", "0") == "1"
        self._reward_model_path = Path(os.getenv("VERA_REWARD_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
        self._reward_model: Optional[RewardModel] = None
        if self._reward_model_enabled and HAS_REWARD_MODEL and self._reward_model_path.exists():
            try:
                self._reward_model = load_reward_model(self._reward_model_path)
            except Exception:
                self._reward_model = None

    @staticmethod
    def _safe_env_int(name: str, fallback: int, minimum: int = 0, maximum: Optional[int] = None) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return fallback
        try:
            value = int(raw)
        except Exception:
            return fallback
        if maximum is not None:
            value = min(value, maximum)
        return max(minimum, value)

    @staticmethod
    def _safe_env_float(name: str, fallback: float, minimum: float = 0.0) -> float:
        raw = os.getenv(name, "").strip()
        if not raw:
            return fallback
        try:
            value = float(raw)
        except Exception:
            return fallback
        return max(minimum, value)

    def _backup_path(self, index: int, compressed: bool = False) -> Path:
        base = self.transitions_path.with_suffix(f".ndjson.{max(1, int(index))}")
        if compressed:
            return Path(str(base) + ".gz")
        return base

    def _remove_backup_slot(self, index: int) -> None:
        plain = self._backup_path(index, compressed=False)
        compressed = self._backup_path(index, compressed=True)
        for path in (plain, compressed):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _compress_file(self, src: Path, dst: Path) -> bool:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                dst.unlink()
            with src.open("rb") as src_handle:
                with gzip.open(dst, "wb", compresslevel=self._compression_level) as dst_handle:
                    shutil.copyfileobj(src_handle, dst_handle)
            src.unlink()
            return True
        except Exception:
            try:
                if dst.exists():
                    dst.unlink()
            except Exception:
                pass
            return False

    def _rotate_backup_slots(self) -> None:
        # Remove the oldest slot first.
        self._remove_backup_slot(self._max_backups)

        # Shift existing backups upward.
        for index in range(self._max_backups - 1, 0, -1):
            src_plain = self._backup_path(index, compressed=False)
            src_gz = self._backup_path(index, compressed=True)
            dst_plain = self._backup_path(index + 1, compressed=False)
            dst_gz = self._backup_path(index + 1, compressed=True)
            self._remove_backup_slot(index + 1)

            if src_gz.exists():
                src_gz.rename(dst_gz)
                continue

            if not src_plain.exists():
                continue

            if self._compress_backups:
                if self._compress_file(src_plain, dst_gz):
                    continue
            src_plain.rename(dst_plain)

    def _rotate_if_needed(self) -> None:
        """Rotate transitions.ndjson when it exceeds the size limit."""
        try:
            if not self.transitions_path.exists():
                return
            size_mb = self.transitions_path.stat().st_size / (1024 * 1024)
            if size_mb < self._max_mb:
                return
            self._rotate_backup_slots()
            backup_1_plain = self._backup_path(1, compressed=False)
            backup_1_gz = self._backup_path(1, compressed=True)
            self._remove_backup_slot(1)
            if self._compress_backups:
                if not self._compress_file(self.transitions_path, backup_1_gz):
                    self.transitions_path.rename(backup_1_plain)
            else:
                self.transitions_path.rename(backup_1_plain)
        except Exception:
            pass  # Don't let rotation errors break logging

    def _append(self, payload: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        line = _json_dumps(payload)
        with self._lock:
            self._rotate_if_needed()
            with self.transitions_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            if self._ledger_enabled:
                try:
                    self._append_ledger_record_locked(payload)
                except Exception as exc:
                    logger.warning("flight ledger append failed: %s", exc)

    def _append_ledger_line_locked(self, handle: Any, record: Dict[str, Any]) -> None:
        line = _canonical_json(record)
        handle.write(line + "\n")

    def _ledger_summary(self, payload: Dict[str, Any]) -> str:
        record_type = str(payload.get("type") or "transition")
        action = payload.get("action") or {}
        result = payload.get("result") or {}
        if isinstance(action, dict):
            if record_type == "transition":
                action_type = str(action.get("type") or "")
                tool_name = str(action.get("tool_name") or "")
                model = str(action.get("model") or "")
                if tool_name:
                    return _truncate(f"{record_type}:{action_type}:{tool_name}", 160)
                if model:
                    return _truncate(f"{record_type}:{action_type}:{model}", 160)
                if action_type:
                    return _truncate(f"{record_type}:{action_type}", 160)
        success = ""
        if isinstance(result, dict) and "success" in result:
            success = f":success={bool(result.get('success'))}"
        return _truncate(f"{record_type}{success}", 160)

    def _ledger_meta(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        action = payload.get("action") or {}
        meta = payload.get("meta") or {}
        compact = {
            "action_type": str((action or {}).get("type") or ""),
            "tool_name": str((action or {}).get("tool_name") or ""),
            "model": str((action or {}).get("model") or ""),
            "success": bool((meta or {}).get("success")) if "success" in (meta or {}) else None,
            "air_score": payload.get("air_score"),
            "air_reason": str(payload.get("air_reason") or ""),
            "latency_ms": (meta or {}).get("latency_ms"),
        }
        return {k: v for k, v in compact.items() if v not in ("", None)}

    def _append_ledger_record_locked(self, payload: Dict[str, Any]) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                lines = handle.readlines()
                last_record = _read_last_nonempty_json_line_from_lines(lines)
                last_hash = str((last_record or {}).get("hash_self") or "")
                if not last_hash:
                    genesis = {
                        "ledger_version": 1,
                        "timestamp_utc": _utc_now_iso(),
                        "record_type": "GENESIS",
                        "event_uuid": "",
                        "source_file": "",
                        "source_kind": "flight_recorder",
                        "hash_prev": "0" * 64,
                        "hash_self": "",
                        "payload_sha256": "",
                        "summary": "flight ledger genesis",
                        "meta": {},
                    }
                    genesis["hash_self"] = _compute_ledger_hash_self(genesis)
                    handle.seek(0, os.SEEK_END)
                    self._append_ledger_line_locked(handle, genesis)
                    last_hash = genesis["hash_self"]
                source_sha256 = _sha256_hex(_canonical_json(payload))
                record = {
                    "ledger_version": 1,
                    "timestamp_utc": _utc_now_iso(),
                    "record_type": str(payload.get("type") or "transition"),
                    "event_uuid": str(payload.get("uuid") or str(uuid.uuid4())),
                    "source_file": str(self.transitions_path),
                    "source_kind": "flight_recorder",
                    "hash_prev": last_hash or ("0" * 64),
                    "hash_self": "",
                    "payload_sha256": source_sha256,
                    "summary": self._ledger_summary(payload),
                    "meta": self._ledger_meta(payload),
                }
                record["hash_self"] = _compute_ledger_hash_self(record)
                handle.seek(0, os.SEEK_END)
                self._append_ledger_line_locked(handle, record)
                handle.flush()
                os.fsync(handle.fileno())
                self._ledger_last_hash = record["hash_self"]
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

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
            return {
                "path": str(self.transitions_path),
                "entries": 0,
                "max_mb": self._max_mb,
                "max_backups": self._max_backups,
                "compress_backups": self._compress_backups,
            }
        try:
            with self.transitions_path.open("r", encoding="utf-8") as handle:
                count = sum(1 for _ in handle)
        except Exception:
            count = 0
        backup_sizes = []
        for index in range(1, self._max_backups + 1):
            plain = self._backup_path(index, compressed=False)
            compressed = self._backup_path(index, compressed=True)
            if plain.exists():
                backup_sizes.append({"slot": index, "path": str(plain), "bytes": plain.stat().st_size})
            if compressed.exists():
                backup_sizes.append({"slot": index, "path": str(compressed), "bytes": compressed.stat().st_size})
        return {
            "path": str(self.transitions_path),
            "entries": count,
            "enabled": self.enabled,
            "max_mb": self._max_mb,
            "max_backups": self._max_backups,
            "compress_backups": self._compress_backups,
            "current_size_bytes": self.transitions_path.stat().st_size,
            "backup_files": backup_sizes,
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

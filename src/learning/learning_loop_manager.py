#!/usr/bin/env python3
"""
Learning Loop Manager
=====================

Runtime wiring for:
- Daily trace extraction from DecisionLedger
- Flight recorder -> distillation pipeline ingestion
- Workflow memory capture/reuse for multi-tool chains
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import time
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from observability.decision_ledger import DecisionLedger
from learning.trace_extraction import TraceExtractionEngine
from learning.trajectory_distillation import (
    AdapterRegistry,
    DistillationConfig,
    DistillationPipeline,
    ExampleStore,
    LoRAConfig,
    MockLoRATrainer,
    QualityLevel,
    TrajectoryCapture,
    TrajectoryStep,
)

logger = logging.getLogger(__name__)

try:
    from learning.reward_model import load_reward_model, train_reward_model
    _REWARD_MODEL_AVAILABLE = True
except Exception:
    load_reward_model = None  # type: ignore
    train_reward_model = None  # type: ignore
    _REWARD_MODEL_AVAILABLE = False


def _safe_read_json(path: Path, default: Any) -> Any:
    try:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _safe_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")


class LearningLoopManager:
    """Coordinates learning infrastructure currently dormant in production."""

    def __init__(
        self,
        memory_dir: Path,
        ledger: DecisionLedger,
        event_bus: Optional[Any] = None,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = ledger
        self.event_bus = event_bus

        self.state_path = self.memory_dir / "learning_loop_state.json"
        self.workflow_path = self.memory_dir / "workflow_templates.json"
        trigger_path_raw = str(os.getenv("VERA_WORKFLOW_TRIGGER_PATH", "")).strip()
        if trigger_path_raw:
            trigger_path = Path(trigger_path_raw).expanduser()
            if not trigger_path.is_absolute():
                trigger_path = self.memory_dir / trigger_path
            self.workflow_trigger_path = trigger_path
        else:
            self.workflow_trigger_path = self.memory_dir / "workflow_memory_triggers.json"
        self._workflow_trigger_mtime = 0.0
        self._workflow_triggers: Dict[str, Any] = {"triggers": []}
        self.flight_path = self.memory_dir / "flight_recorder" / "transitions.ndjson"
        self.lora_eval_history_path = self.memory_dir / "learning_reports" / "lora_eval_history.ndjson"

        self.capture = TrajectoryCapture(storage_path=self.memory_dir / "trajectories" / "trajectories.json")
        self.example_store = ExampleStore(storage_path=self.memory_dir / "training_examples" / "examples.json")
        self.adapter_registry = AdapterRegistry(storage_dir=self.memory_dir / "adapters")
        self.trace_engine = TraceExtractionEngine(self.ledger, self.capture, min_confidence=0.85)

        self._state = _safe_read_json(
            self.state_path,
            {
                "last_trace_date": "",
                "last_trace_at": "",
                "flight_offset": 0,
                "flight_processed_total": 0,
                "daily_runs": 0,
                "reward_last_trained_at": "",
                "reward_last_train_processed_total": 0,
                "reward_last_samples": 0,
                "reward_last_status": "",
                "reward_last_error": "",
                "reward_last_attempt_at": "",
                "reward_last_status_updated_at": "",
                "lora_last_trained_at": "",
                "lora_last_train_example_count": 0,
                "lora_last_adapter_id": "",
                "lora_last_status": "",
                "lora_last_error": "",
                "lora_last_attempt_at": "",
                "lora_last_metrics": {},
                "lora_last_activation_reason": "",
                "lora_last_eval_report": {},
            },
        )
        self._workflows = _safe_read_json(self.workflow_path, {"templates": {}})
        if not isinstance(self._state, dict):
            self._state = {}
        self._state.setdefault("reward_last_status_updated_at", "")

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._cycle_running = False
        self._diag: Dict[str, Any] = {
            "start_attempts": 0,
            "start_successes": 0,
            "start_failures": 0,
            "last_start_at": "",
            "last_start_error": "",
            "last_start_due_now": False,
            "last_start_due_reason": "",
            "last_start_last_trace_date": "",
            "last_start_scheduled_today": "",
            "last_start_next_due_at": "",
            "last_stop_at": "",
            "ticks_total": 0,
            "last_tick_at": "",
            "last_tick_due_now": False,
            "last_tick_due_reason": "",
            "last_tick_next_due_at": "",
            "manual_cycle_requests": 0,
            "manual_cycles_started": 0,
            "manual_cycles_completed": 0,
            "last_manual_cycle_started_at": "",
            "last_manual_cycle_completed_at": "",
            "last_manual_cycle_error": "",
            "last_manual_cycle_result": {},
            "cycles_started": 0,
            "cycles_completed": 0,
            "last_cycle_started_at": "",
            "last_cycle_completed_at": "",
            "last_cycle_error": "",
            "last_cycle_result": {},
            "workflow_outcome_calls": 0,
            "workflow_outcome_saved": 0,
            "workflow_outcome_skip_short_chain": 0,
            "workflow_outcome_last": {},
            "workflow_replay_calls": 0,
            "workflow_replay_saved": 0,
            "workflow_replay_skip_short_chain": 0,
            "workflow_replay_last": {},
        }

        self.daily_hour = self._read_int_env("VERA_TRACE_EXTRACTION_HOUR", 2, min_value=0, max_value=23)
        self.poll_seconds = self._read_int_env("VERA_TRACE_EXTRACTION_POLL_SECONDS", 300, min_value=30)
        self.startup_delay_seconds = self._read_int_env(
            "VERA_LEARNING_LOOP_STARTUP_DELAY_SECONDS",
            self.poll_seconds,
            min_value=0,
        )
        self.flight_batch_max = self._read_int_env("VERA_FLIGHT_DISTILL_BATCH_MAX", 250, min_value=10)
        self.debug_trace_enabled = self._read_bool_env("VERA_LEARNING_LOOP_DEBUG", False)
        self.workflow_trace_enabled = self._read_bool_env("VERA_WORKFLOW_TRACE_DEBUG", self.debug_trace_enabled)
        self.reward_trace_enabled = self._read_bool_env("VERA_REWARD_TRACE_DEBUG", self.debug_trace_enabled)
        self._load_workflow_triggers()
        self.workflow_min_success = self._read_int_env("VERA_WORKFLOW_MIN_SUCCESS", 2, min_value=1)
        self.workflow_min_reliability = self._read_float_env(
            "VERA_WORKFLOW_MIN_RELIABILITY",
            0.6,
            min_value=0.0,
            max_value=1.0,
        )
        self.workflow_fuzzy_min_score = self._read_float_env(
            "VERA_WORKFLOW_FUZZY_MIN_SCORE",
            0.35,
            min_value=0.0,
            max_value=1.0,
        )
        self.workflow_disable_minutes = self._read_int_env(
            "VERA_WORKFLOW_TEMPLATE_DISABLE_MINUTES",
            180,
            min_value=15,
            max_value=1440,
        )
        self.workflow_disable_failures = self._read_int_env(
            "VERA_WORKFLOW_DISABLE_CONSECUTIVE_FAILURES",
            3,
            min_value=2,
            max_value=10,
        )
        self.workflow_replay_disable_failures = self._read_int_env(
            "VERA_WORKFLOW_REPLAY_DISABLE_CONSECUTIVE_FAILURES",
            2,
            min_value=1,
            max_value=10,
        )
        self.workflow_quarantine_minutes = self._read_int_env(
            "VERA_WORKFLOW_QUARANTINE_MINUTES",
            self.workflow_disable_minutes,
            min_value=15,
            max_value=10080,
        )
        quarantine_tags_raw = str(
            os.getenv(
                "VERA_WORKFLOW_QUARANTINE_TAGS",
                (
                    "tool_call_limit_reached,tool_timeout,llm_timeout,"
                    "confirmation_required,cached_chain_not_completed,chain_mismatch,"
                    "tool_execution_error"
                ),
            )
            or ""
        ).strip()
        quarantine_tags = [
            str(tag).strip().lower()
            for tag in quarantine_tags_raw.split(",")
            if str(tag).strip()
        ]
        if not quarantine_tags:
            quarantine_tags = [
                "tool_call_limit_reached",
                "tool_timeout",
                "llm_timeout",
                "confirmation_required",
                "cached_chain_not_completed",
                "chain_mismatch",
                "tool_execution_error",
            ]
        self.workflow_quarantine_tags = sorted(set(quarantine_tags))
        self.reward_auto_train_enabled = self._read_bool_env("VERA_REWARD_AUTO_TRAIN", True)
        self.reward_train_min_new_transitions = self._read_int_env(
            "VERA_REWARD_TRAIN_MIN_NEW_TRANSITIONS",
            100,
            min_value=1,
        )
        self.reward_train_max_interval_days = self._read_int_env(
            "VERA_REWARD_TRAIN_MAX_INTERVAL_DAYS",
            7,
            min_value=1,
        )
        self.reward_train_min_examples = self._read_int_env(
            "VERA_REWARD_TRAIN_MIN_EXAMPLES",
            20,
            min_value=1,
        )
        self.reward_train_epochs = self._read_int_env(
            "VERA_REWARD_TRAIN_EPOCHS",
            60,
            min_value=1,
            max_value=500,
        )
        self.reward_train_lr = self._read_float_env(
            "VERA_REWARD_TRAIN_LR",
            0.08,
            min_value=0.0001,
            max_value=1.0,
        )
        self.reward_train_l2 = self._read_float_env(
            "VERA_REWARD_TRAIN_L2",
            0.01,
            min_value=0.0,
            max_value=1.0,
        )
        self.workflow_reward_weight = self._read_float_env(
            "VERA_WORKFLOW_REWARD_WEIGHT",
            0.15,
            min_value=0.0,
            max_value=0.4,
        )

        # Periodic LoRA retraining cadence (VERA 3.0 runway)
        self.lora_auto_train_enabled = self._read_bool_env("VERA_LORA_AUTO_TRAIN", True)
        self.lora_train_min_examples = self._read_int_env(
            "VERA_LORA_TRAIN_MIN_EXAMPLES",
            500,
            min_value=1,
        )
        self.lora_train_max_interval_days = self._read_int_env(
            "VERA_LORA_TRAIN_MAX_INTERVAL_DAYS",
            30,
            min_value=1,
        )
        self.lora_train_base_model = str(os.getenv("VERA_LORA_BASE_MODEL", "vera-base-model")).strip() or "vera-base-model"
        self.lora_train_name_prefix = str(os.getenv("VERA_LORA_NAME_PREFIX", "vera_monthly")).strip() or "vera_monthly"
        self.lora_trainer_backend_preference = str(os.getenv("VERA_LORA_TRAINER_BACKEND", "auto")).strip().lower() or "auto"
        self.lora_train_min_quality = self._read_float_env(
            "VERA_LORA_TRAIN_MIN_QUALITY",
            0.7,
            min_value=0.0,
            max_value=1.0,
        )
        self.lora_hf_max_train_examples = self._read_int_env(
            "VERA_LORA_HF_MAX_TRAIN_EXAMPLES",
            1200,
            min_value=50,
            max_value=20000,
        )
        self.lora_hf_max_eval_examples = self._read_int_env(
            "VERA_LORA_HF_MAX_EVAL_EXAMPLES",
            256,
            min_value=16,
            max_value=10000,
        )
        self.lora_hf_use_fp16 = self._read_bool_env("VERA_LORA_HF_USE_FP16", True)
        self.lora_auto_evaluate_enabled = self._read_bool_env("VERA_LORA_AUTO_EVALUATE", True)
        self.lora_eval_compare_active = self._read_bool_env("VERA_LORA_EVAL_COMPARE_ACTIVE", True)
        self.lora_auto_activate_enabled = self._read_bool_env("VERA_LORA_AUTO_ACTIVATE", True)
        self.lora_auto_replace_active = self._read_bool_env("VERA_LORA_AUTO_REPLACE_ACTIVE", False)
        self.lora_replace_min_val_loss_delta = self._read_float_env(
            "VERA_LORA_REPLACE_MIN_VAL_LOSS_DELTA",
            0.02,
            min_value=0.0,
            max_value=5.0,
        )
        self.lora_replace_min_accuracy_delta = self._read_float_env(
            "VERA_LORA_REPLACE_MIN_ACCURACY_DELTA",
            0.01,
            min_value=0.0,
            max_value=1.0,
        )
        self.lora_activation_min_accuracy = self._read_float_env(
            "VERA_LORA_ACTIVATION_MIN_ACCURACY",
            0.8,
            min_value=0.0,
            max_value=1.0,
        )

        self.lora_rank = self._read_int_env("VERA_LORA_RANK", 16, min_value=1, max_value=256)
        self.lora_alpha = self._read_int_env("VERA_LORA_ALPHA", 32, min_value=1, max_value=512)
        self.lora_dropout = self._read_float_env("VERA_LORA_DROPOUT", 0.05, min_value=0.0, max_value=0.5)
        self.lora_learning_rate = self._read_float_env("VERA_LORA_LEARNING_RATE", 2e-4, min_value=1e-7, max_value=1.0)
        self.lora_batch_size = self._read_int_env("VERA_LORA_BATCH_SIZE", 4, min_value=1, max_value=128)
        self.lora_gradient_accumulation_steps = self._read_int_env(
            "VERA_LORA_GRAD_ACCUM_STEPS",
            4,
            min_value=1,
            max_value=128,
        )
        self.lora_num_epochs = self._read_int_env("VERA_LORA_EPOCHS", 3, min_value=1, max_value=100)
        self.lora_warmup_ratio = self._read_float_env("VERA_LORA_WARMUP_RATIO", 0.1, min_value=0.0, max_value=1.0)
        self.lora_weight_decay = self._read_float_env("VERA_LORA_WEIGHT_DECAY", 0.01, min_value=0.0, max_value=1.0)
        self.lora_max_seq_length = self._read_int_env("VERA_LORA_MAX_SEQ_LENGTH", 2048, min_value=64, max_value=16384)

        self.lora_trainer_backend = "mock"
        self.lora_trainer_backend_reason = ""
        self.lora_trainer = self._build_lora_trainer()
        self.pipeline = DistillationPipeline(
            capture=self.capture,
            example_store=self.example_store,
            adapter_registry=self.adapter_registry,
            trainer=self.lora_trainer,
            config=DistillationConfig(
                min_trajectory_score=0.55,
                min_quality_level=QualityLevel.MEDIUM,
                min_examples_for_training=100,
                auto_train_threshold=500,
            ),
        )

        self.reward_model_path = self.memory_dir / "flight_recorder" / "reward_model.json"
        self.reward_model: Optional[Any] = None
        self._load_reward_model_if_available()

    @staticmethod
    def _read_int_env(
        name: str,
        default: int,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> int:
        raw = str(os.getenv(name, "")).strip()
        try:
            value = int(raw) if raw else default
        except Exception:
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    @staticmethod
    def _read_float_env(
        name: str,
        default: float,
        min_value: Optional[float] = None,
        max_value: Optional[float] = None,
    ) -> float:
        raw = str(os.getenv(name, "")).strip()
        try:
            value = float(raw) if raw else default
        except Exception:
            value = default
        if min_value is not None:
            value = max(min_value, value)
        if max_value is not None:
            value = min(max_value, value)
        return value

    @staticmethod
    def _read_bool_env(name: str, default: bool) -> bool:
        raw = str(os.getenv(name, "")).strip().lower()
        if not raw:
            return default
        if raw in {"1", "true", "yes", "on"}:
            return True
        if raw in {"0", "false", "no", "off"}:
            return False
        return default

    def _trace_learning(self, message: str, *args: Any) -> None:
        if not self.debug_trace_enabled:
            return
        logger.info("[learning-loop-debug] " + message, *args)

    def _trace_workflow(self, message: str, *args: Any) -> None:
        if not self.workflow_trace_enabled:
            return
        logger.info("[workflow-debug] " + message, *args)

    def _trace_reward(self, message: str, *args: Any) -> None:
        if not self.reward_trace_enabled:
            return
        logger.info("[reward-debug] " + message, *args)

    @staticmethod
    def _short_text(value: Any, limit: int = 240) -> str:
        return str(value or "")[:max(1, int(limit))]

    @staticmethod
    def _short_task(value: Any, limit: int = 180) -> str:
        return str(value or "").strip().replace("\n", " ")[:max(1, int(limit))]

    def _set_reward_status_state(
        self,
        *,
        status: str,
        error: str = "",
        attempted_at: Optional[datetime] = None,
        save: bool = True,
    ) -> None:
        now_text = datetime.now().isoformat()
        if attempted_at is not None:
            self._state["reward_last_attempt_at"] = attempted_at.isoformat()
        self._state["reward_last_status"] = self._short_text(status, 180)
        self._state["reward_last_error"] = self._short_text(error, 220)
        self._state["reward_last_status_updated_at"] = now_text
        if save:
            self._save_state()

    def _build_lora_trainer(self) -> Any:
        preference = str(self.lora_trainer_backend_preference or "auto").strip().lower()
        if preference not in {"auto", "mock", "hf_peft", "hf"}:
            preference = "auto"

        if preference in {"auto", "hf_peft", "hf"}:
            try:
                from learning.hf_lora_trainer import HFPEFTLoRATrainer, hf_lora_dependencies_status

                dep_status = hf_lora_dependencies_status()
                if bool(dep_status.get("available", False)):
                    self.lora_trainer_backend = "hf_peft"
                    self.lora_trainer_backend_reason = "hf_peft_available"
                    return HFPEFTLoRATrainer(
                        base_model_name=self.lora_train_base_model,
                        max_train_examples=self.lora_hf_max_train_examples,
                        max_eval_examples=self.lora_hf_max_eval_examples,
                        use_fp16=self.lora_hf_use_fp16,
                    )

                missing = ", ".join(str(name) for name in (dep_status.get("missing") or []))
                self.lora_trainer_backend_reason = (
                    f"hf_peft_missing_dependencies:{missing}" if missing else "hf_peft_unavailable"
                )
                if preference in {"hf_peft", "hf"}:
                    logger.warning(
                        "LoRA trainer backend '%s' unavailable; falling back to mock (%s)",
                        preference,
                        self.lora_trainer_backend_reason,
                    )
            except Exception as exc:
                self.lora_trainer_backend_reason = f"hf_peft_init_error:{exc}"
                if preference in {"hf_peft", "hf"}:
                    logger.warning(
                        "LoRA trainer backend '%s' failed to initialize; falling back to mock (%s)",
                        preference,
                        exc,
                    )

        self.lora_trainer_backend = "mock"
        if not self.lora_trainer_backend_reason:
            self.lora_trainer_backend_reason = "forced_mock" if preference == "mock" else "auto_fallback_to_mock"
        return MockLoRATrainer()

    @staticmethod
    def _probe_write_access(path: Path) -> Dict[str, Any]:
        path = Path(path)
        probe_path = path / ".write_probe.tmp"
        payload = {
            "path": str(path),
            "ok": False,
            "error": "",
        }
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe_path.write_text("ok\n", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
            payload["ok"] = True
            return payload
        except Exception as exc:
            payload["error"] = str(exc)
            try:
                if probe_path.exists():
                    probe_path.unlink(missing_ok=True)
            except Exception:
                pass
            return payload

    def get_lora_backend_readiness(self) -> Dict[str, Any]:
        hf_status: Dict[str, Any] = {
            "available": False,
            "required": ["torch", "transformers", "peft", "datasets"],
            "missing": [],
        }
        try:
            from learning.hf_lora_trainer import hf_lora_dependencies_status

            probe = hf_lora_dependencies_status()
            if isinstance(probe, dict):
                hf_status.update(probe)
        except Exception as exc:
            hf_status["error"] = str(exc)

        torch_info: Dict[str, Any] = {
            "installed": False,
            "cuda_available": False,
            "cuda_device_count": 0,
            "version": "",
        }
        if importlib.util.find_spec("torch") is not None:
            torch_info["installed"] = True
            try:
                import torch

                torch_info["version"] = str(getattr(torch, "__version__", "") or "")
                cuda_available = bool(torch.cuda.is_available())
                torch_info["cuda_available"] = cuda_available
                torch_info["cuda_device_count"] = int(torch.cuda.device_count()) if cuda_available else 0
                if cuda_available:
                    names = []
                    for idx in range(int(torch.cuda.device_count())):
                        try:
                            names.append(str(torch.cuda.get_device_name(idx)))
                        except Exception:
                            names.append("unknown")
                    torch_info["cuda_devices"] = names
            except Exception as exc:
                torch_info["error"] = str(exc)

        adapters_probe = self._probe_write_access(self.memory_dir / "adapters")
        reports_probe = self._probe_write_access(self.memory_dir / "learning_reports")

        return {
            "timestamp": datetime.now().isoformat(),
            "trainer_backend_preference": self.lora_trainer_backend_preference,
            "trainer_backend_selected": self.lora_trainer_backend,
            "trainer_backend_reason": self.lora_trainer_backend_reason,
            "base_model": self.lora_train_base_model,
            "hf_dependencies_available": bool(hf_status.get("available", False)),
            "hf_dependencies": hf_status,
            "torch": torch_info,
            "checks": {
                "adapters_dir_writable": bool(adapters_probe.get("ok", False)),
                "learning_reports_dir_writable": bool(reports_probe.get("ok", False)),
            },
            "paths": {
                "adapters_dir": str(self.memory_dir / "adapters"),
                "learning_reports_dir": str(self.memory_dir / "learning_reports"),
                "lora_eval_history_path": str(self.lora_eval_history_path),
            },
        }

    def _save_state(self) -> None:
        _safe_write_json(self.state_path, self._state)
        self._trace_learning(
            (
                "state_saved path=%s last_trace_date=%s flight_processed_total=%s "
                "reward_last_train_processed_total=%s reward_last_status=%s"
            ),
            self.state_path,
            str(self._state.get("last_trace_date", "")),
            int(self._state.get("flight_processed_total", 0) or 0),
            int(self._state.get("reward_last_train_processed_total", 0) or 0),
            str(self._state.get("reward_last_status", "")),
        )

    def _save_workflows(self) -> None:
        _safe_write_json(self.workflow_path, self._workflows)
        self._trace_workflow(
            "workflows_saved path=%s template_count=%s",
            self.workflow_path,
            len((self._workflows or {}).get("templates", {})),
        )

    def _load_reward_model_if_available(self) -> bool:
        if not _REWARD_MODEL_AVAILABLE or not load_reward_model:
            self.reward_model = None
            return False
        if not self.reward_model_path.exists():
            self.reward_model = None
            return False
        try:
            self.reward_model = load_reward_model(self.reward_model_path)
            return True
        except Exception:
            self.reward_model = None
            return False

    def _emit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        if not self.event_bus:
            return
        try:
            self.event_bus.publish(event_type, payload=payload, source="learning_loop")
        except Exception:
            logger.debug("Suppressed Exception in learning_loop_manager")

    def start(self) -> None:
        if self._running:
            self._trace_learning("start_skipped reason=already_running")
            return
        self._diag["start_attempts"] = int(self._diag.get("start_attempts", 0) or 0) + 1
        self._diag["last_start_at"] = datetime.now().isoformat()
        self._diag["last_start_error"] = ""
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            due_details = self._daily_due_details(now=datetime.now())
            self._task = loop.create_task(self._daily_loop())
            self._task.add_done_callback(self._on_daily_loop_done)
            self._diag["start_successes"] = int(self._diag.get("start_successes", 0) or 0) + 1
            self._diag["last_start_error"] = ""
            self._diag["last_start_due_now"] = bool(due_details.get("due_now", False))
            self._diag["last_start_due_reason"] = str(due_details.get("reason", ""))
            self._diag["last_start_last_trace_date"] = str(due_details.get("last_trace_date", ""))
            self._diag["last_start_scheduled_today"] = str(due_details.get("scheduled_today", ""))
            self._diag["last_start_next_due_at"] = str(due_details.get("next_due_at", ""))
            self._trace_learning(
                (
                    "start_ok poll_seconds=%s startup_delay_seconds=%s daily_hour=%s due_now=%s due_reason=%s "
                    "last_trace_date=%s next_due_at=%s"
                ),
                self.poll_seconds,
                self.startup_delay_seconds,
                self.daily_hour,
                bool(due_details.get("due_now", False)),
                str(due_details.get("reason", "")),
                str(due_details.get("last_trace_date", "")),
                str(due_details.get("next_due_at", "")),
            )
        except RuntimeError:
            self._running = False
            self._task = None
            self._diag["start_failures"] = int(self._diag.get("start_failures", 0) or 0) + 1
            self._diag["last_start_error"] = "no_running_asyncio_loop"
            logger.warning(
                "Learning loop start skipped: no running asyncio loop (poll_seconds=%s daily_hour=%s)",
                self.poll_seconds,
                self.daily_hour,
            )

    def _on_daily_loop_done(self, task: asyncio.Task) -> None:
        """Restart the loop if it exits unexpectedly while manager is still running."""
        if task is not self._task:
            return
        self._cycle_running = False
        if not self._running:
            return

        if task.cancelled():
            reason = "daily_loop_cancelled_unexpectedly"
            logger.warning("Learning loop task was cancelled unexpectedly; restarting.")
        else:
            exc = task.exception()
            if exc is not None:
                reason = self._short_text(exc, 240)
                logger.warning("Learning loop task crashed; restarting: %s", exc)
            else:
                reason = "daily_loop_exited_unexpectedly"
                logger.warning("Learning loop task exited unexpectedly; restarting.")
        self._diag["last_start_error"] = reason

        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._daily_loop())
            self._task.add_done_callback(self._on_daily_loop_done)
            self._diag["start_successes"] = int(self._diag.get("start_successes", 0) or 0) + 1
            self._diag["last_start_at"] = datetime.now().isoformat()
            self._trace_learning("daily_loop_restarted")
        except RuntimeError:
            self._running = False
            self._task = None
            self._diag["start_failures"] = int(self._diag.get("start_failures", 0) or 0) + 1
            self._diag["last_start_error"] = "daily_loop_restart_missing_event_loop"
            logger.warning("Learning loop restart failed: no running asyncio loop.")

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self._diag["last_stop_at"] = datetime.now().isoformat()
        self._trace_learning("stop_completed")

    async def shutdown(self, timeout_seconds: float = 120.0) -> None:
        """
        Gracefully stop the background loop and wait for in-flight work to finish.

        This avoids abandoning long-running to_thread() jobs, which can leave
        executor workers alive past event-loop shutdown.
        """
        self._running = False
        self._diag["last_stop_at"] = datetime.now().isoformat()
        task = self._task
        if task is None:
            self._trace_learning("shutdown_skip reason=no_task")
            return
        if task.done():
            self._task = None
            self._trace_learning("shutdown_skip reason=already_done")
            return

        # If the loop is idle (typically sleeping between polls), cancel
        # immediately so shutdown does not block for poll_seconds.
        if not self._cycle_running:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in learning_loop_manager")
            self._task = None
            self._trace_learning("shutdown_done mode=cancel_idle")
            return

        timeout = max(0.1, float(timeout_seconds))
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            self._trace_learning("shutdown_done mode=graceful")
        except asyncio.TimeoutError:
            self._trace_learning("shutdown_timeout canceling_task timeout_seconds=%s", timeout)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("Suppressed Exception in learning_loop_manager")
        finally:
            self._task = None

    async def _daily_loop(self) -> None:
        first_tick = True
        while self._running:
            if first_tick and self.startup_delay_seconds > 0:
                first_tick = False
                try:
                    await asyncio.sleep(self.startup_delay_seconds)
                except asyncio.CancelledError:
                    self._cycle_running = False
                    break
                if not self._running:
                    break
            else:
                first_tick = False
            try:
                now = datetime.now()
                due_details = self._daily_due_details(now=now)
                self._diag["ticks_total"] = int(self._diag.get("ticks_total", 0) or 0) + 1
                self._diag["last_tick_at"] = now.isoformat()
                self._diag["last_tick_due_now"] = bool(due_details.get("due_now", False))
                self._diag["last_tick_due_reason"] = str(due_details.get("reason", ""))
                self._diag["last_tick_next_due_at"] = str(due_details.get("next_due_at", ""))
                self._trace_learning(
                    (
                        "tick due_now=%s reason=%s now=%s last_trace_date=%s "
                        "scheduled_today=%s next_due_at=%s"
                    ),
                    bool(due_details.get("due_now", False)),
                    str(due_details.get("reason", "")),
                    str(due_details.get("now", "")),
                    str(due_details.get("last_trace_date", "")),
                    str(due_details.get("scheduled_today", "")),
                    str(due_details.get("next_due_at", "")),
                )
                if bool(due_details.get("due_now", False)):
                    self._trace_learning("tick_run_cycle_start")
                    self._diag["cycles_started"] = int(self._diag.get("cycles_started", 0) or 0) + 1
                    self._diag["last_cycle_started_at"] = now.isoformat()
                    self._diag["last_cycle_error"] = ""
                    self._cycle_running = True
                    try:
                        result = await self.run_daily_learning_cycle()
                    finally:
                        self._cycle_running = False
                    self._diag["cycles_completed"] = int(self._diag.get("cycles_completed", 0) or 0) + 1
                    self._diag["last_cycle_completed_at"] = datetime.now().isoformat()
                    self._diag["last_cycle_result"] = {
                        "trajectories_extracted": int(result.get("trajectories_extracted", 0) or 0),
                        "examples_from_trajectories": int(result.get("examples_from_trajectories", 0) or 0),
                        "flight_examples_created": int(((result.get("flight_ingest") or {}).get("examples_created", 0) or 0)),
                        "reward_trained": bool(((result.get("reward_training") or {}).get("trained", False))),
                        "lora_trained": bool(((result.get("lora_training") or {}).get("trained", False))),
                        "total_examples": int(result.get("total_examples", 0) or 0),
                    }
                    self._trace_learning(
                        (
                            "tick_run_cycle_done traces=%s examples=%s flight_examples=%s "
                            "reward_trained=%s lora_trained=%s total_examples=%s"
                        ),
                        int(result.get("trajectories_extracted", 0) or 0),
                        int(result.get("examples_from_trajectories", 0) or 0),
                        int(((result.get("flight_ingest") or {}).get("examples_created", 0) or 0)),
                        bool(((result.get("reward_training") or {}).get("trained", False))),
                        bool(((result.get("lora_training") or {}).get("trained", False))),
                        int(result.get("total_examples", 0) or 0),
                    )
            except asyncio.CancelledError:
                self._cycle_running = False
                break
            except Exception as exc:
                self._cycle_running = False
                self._diag["last_cycle_error"] = self._short_text(exc, 240)
                logger.warning("Learning loop tick failed: %s", exc)
            await asyncio.sleep(self.poll_seconds)

    @staticmethod
    def _parse_date(value: str) -> Optional[date]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except Exception:
            return None

    def _scheduled_run_time_for_date(self, target_date: date) -> datetime:
        hour = max(0, min(23, int(self.daily_hour)))
        return datetime.combine(target_date, dt_time(hour=hour))

    def _is_daily_cycle_due(self, now: Optional[datetime] = None) -> bool:
        now_dt = now or datetime.now()
        last_date = self._parse_date(str(self._state.get("last_trace_date", "")))
        today = now_dt.date()
        if last_date == today:
            return False

        # If we are at/after today's scheduled time and haven't run today, cycle is due.
        if now_dt >= self._scheduled_run_time_for_date(today):
            return True

        # Before today's schedule, run a catch-up cycle if stale by > 1 full day.
        if last_date is None:
            return True
        return last_date <= (today - timedelta(days=2))

    def _daily_due_details(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        now_dt = now or datetime.now()
        today = now_dt.date()
        scheduled_today = self._scheduled_run_time_for_date(today)
        last_date = self._parse_date(str(self._state.get("last_trace_date", "")))
        due_now = self._is_daily_cycle_due(now=now_dt)

        reason = "not_due"
        if last_date == today:
            reason = "already_ran_today"
        elif now_dt >= scheduled_today:
            reason = "scheduled_time_reached"
        elif last_date is None:
            reason = "never_ran"
        elif last_date <= (today - timedelta(days=2)):
            reason = "stale_catchup"
        else:
            reason = "waiting_for_schedule"

        return {
            "due_now": bool(due_now),
            "reason": reason,
            "now": now_dt.isoformat(),
            "last_trace_date": str(self._state.get("last_trace_date", "")),
            "scheduled_today": scheduled_today.isoformat(),
            "next_due_at": self._next_due_datetime(now=now_dt).isoformat(),
        }

    def _next_due_datetime(self, now: Optional[datetime] = None) -> datetime:
        now_dt = now or datetime.now()
        today = now_dt.date()
        scheduled_today = self._scheduled_run_time_for_date(today)
        if self._parse_date(str(self._state.get("last_trace_date", ""))) != today and now_dt <= scheduled_today:
            return scheduled_today
        return self._scheduled_run_time_for_date(today + timedelta(days=1))

    async def run_daily_learning_cycle_if_due(self, force: bool = False) -> Dict[str, Any]:
        now = datetime.now()
        self._diag["manual_cycle_requests"] = int(self._diag.get("manual_cycle_requests", 0) or 0) + 1
        due_details = self._daily_due_details(now=now)
        due = bool(due_details.get("due_now", False))
        self._trace_learning(
            (
                "run_if_due force=%s due_now=%s reason=%s last_trace_date=%s "
                "next_due_at=%s"
            ),
            bool(force),
            due,
            str(due_details.get("reason", "")),
            str(due_details.get("last_trace_date", "")),
            str(due_details.get("next_due_at", "")),
        )
        if not force and not due:
            return {
                "ran": False,
                "reason": "not_due",
                "due_now": False,
                "next_due_at": self._next_due_datetime(now=now).isoformat(),
                "last_trace_date": str(self._state.get("last_trace_date", "")),
                "due_details": due_details,
            }
        if self._cycle_running:
            return {
                "ran": False,
                "reason": "already_running",
                "due_now": due,
                "next_due_at": self._next_due_datetime(now=now).isoformat(),
                "last_trace_date": str(self._state.get("last_trace_date", "")),
                "due_details": due_details,
            }
        self._diag["manual_cycles_started"] = int(self._diag.get("manual_cycles_started", 0) or 0) + 1
        self._diag["last_manual_cycle_started_at"] = datetime.now().isoformat()
        self._diag["last_manual_cycle_error"] = ""
        self._cycle_running = True
        try:
            result = await self.run_daily_learning_cycle()
        except Exception as exc:
            self._diag["last_manual_cycle_error"] = self._short_text(exc, 240)
            raise
        finally:
            self._cycle_running = False
        self._diag["manual_cycles_completed"] = int(self._diag.get("manual_cycles_completed", 0) or 0) + 1
        self._diag["last_manual_cycle_completed_at"] = datetime.now().isoformat()
        self._diag["last_manual_cycle_result"] = {
            "trajectories_extracted": int(result.get("trajectories_extracted", 0) or 0),
            "examples_from_trajectories": int(result.get("examples_from_trajectories", 0) or 0),
            "flight_examples_created": int(((result.get("flight_ingest") or {}).get("examples_created", 0) or 0)),
            "reward_trained": bool(((result.get("reward_training") or {}).get("trained", False))),
            "lora_trained": bool(((result.get("lora_training") or {}).get("trained", False))),
            "total_examples": int(result.get("total_examples", 0) or 0),
        }
        return {
            "ran": True,
            "reason": "forced" if force and not due else "due",
            "due_now": due,
            "next_due_at": self._next_due_datetime(now=datetime.now()).isoformat(),
            "due_details": due_details,
            "result": result,
        }

    async def run_daily_learning_cycle(self) -> Dict[str, Any]:
        """Run trace extraction + distillation + flight ingest."""
        now = datetime.now()
        self._trace_learning(
            "run_cycle_start at=%s flight_offset=%s flight_processed_total=%s",
            now.isoformat(),
            int(self._state.get("flight_offset", 0) or 0),
            int(self._state.get("flight_processed_total", 0) or 0),
        )
        extracted_ids = await asyncio.to_thread(self.trace_engine.extract_recent_successes, 24)
        distilled_examples = await asyncio.to_thread(self.pipeline.extract_from_all_successful)
        flight_stats = await asyncio.to_thread(self.ingest_flight_recorder_transitions, self.flight_batch_max)
        reward_training = await asyncio.to_thread(self.maybe_train_reward_model)
        lora_training = await asyncio.to_thread(self.maybe_train_lora_adapter)

        self._state["last_trace_date"] = now.date().isoformat()
        self._state["last_trace_at"] = now.isoformat()
        self._state["daily_runs"] = int(self._state.get("daily_runs", 0)) + 1
        self._save_state()

        result = {
            "run_at": now.isoformat(),
            "trajectories_extracted": len(extracted_ids),
            "examples_from_trajectories": len(distilled_examples),
            "flight_ingest": flight_stats,
            "reward_training": reward_training,
            "lora_training": lora_training,
            "total_examples": self.example_store.count(),
        }
        logger.info(
            (
                "Learning cycle complete: traces=%s examples=%s flight_examples=%s "
                "reward_trained=%s lora_trained=%s total_examples=%s"
            ),
            len(extracted_ids),
            len(distilled_examples),
            flight_stats.get("examples_created", 0),
            bool(reward_training.get("trained", False)),
            bool(lora_training.get("trained", False)),
            self.example_store.count(),
        )
        self._emit_event("learning.daily_cycle", result)
        self._trace_learning("run_cycle_emit_event ok run_at=%s", result.get("run_at"))
        return result

    def _reward_train_due(self, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
        now_dt = now or datetime.now()
        processed_total = int(self._state.get("flight_processed_total", 0) or 0)
        last_processed = int(self._state.get("reward_last_train_processed_total", 0) or 0)
        new_since = max(0, processed_total - last_processed)
        last_trained_at = self._parse_datetime(str(self._state.get("reward_last_trained_at", "") or ""))
        days_since = None
        if last_trained_at is not None:
            days_since = (now_dt - last_trained_at).days

        due_by_volume = new_since >= self.reward_train_min_new_transitions
        due_by_interval = bool(days_since is not None and days_since >= self.reward_train_max_interval_days and new_since > 0)
        due = bool(force or due_by_volume or due_by_interval)
        reason = "forced" if force else "not_due"
        if not force:
            if due_by_volume:
                reason = "new_transitions_threshold"
            elif due_by_interval:
                reason = "max_interval_elapsed"
        return {
            "due": due,
            "reason": reason,
            "new_transitions_since_last_train": new_since,
            "processed_total": processed_total,
            "last_processed_total": last_processed,
            "days_since_last_train": days_since,
        }

    def maybe_train_reward_model(self, force: bool = False) -> Dict[str, Any]:
        now = datetime.now()
        due_info = self._reward_train_due(now=now, force=force)
        self._trace_reward(
            (
                "reward_train_check force=%s enabled=%s available=%s due=%s reason=%s "
                "new_since=%s min_new=%s processed_total=%s last_processed=%s"
            ),
            bool(force),
            bool(self.reward_auto_train_enabled),
            bool(_REWARD_MODEL_AVAILABLE),
            bool(due_info.get("due", False)),
            str(due_info.get("reason", "")),
            int(due_info.get("new_transitions_since_last_train", 0) or 0),
            self.reward_train_min_new_transitions,
            int(due_info.get("processed_total", 0) or 0),
            int(due_info.get("last_processed_total", 0) or 0),
        )
        result: Dict[str, Any] = {
            "enabled": bool(self.reward_auto_train_enabled),
            "available": bool(_REWARD_MODEL_AVAILABLE),
            "trained": False,
            "ran": False,
            "reason": due_info["reason"],
            "new_transitions_since_last_train": due_info["new_transitions_since_last_train"],
            "min_new_transitions_required": self.reward_train_min_new_transitions,
            "max_interval_days": self.reward_train_max_interval_days,
            "model_path": str(self.reward_model_path),
            "samples": 0,
        }
        if not self.reward_auto_train_enabled:
            result["reason"] = "disabled"
            self._set_reward_status_state(status=result["reason"], error="")
            self._trace_reward("reward_train_skip reason=disabled")
            return result
        if not _REWARD_MODEL_AVAILABLE or not train_reward_model:
            result["reason"] = "reward_model_unavailable"
            self._set_reward_status_state(status=result["reason"], error="")
            self._trace_reward("reward_train_skip reason=reward_model_unavailable")
            return result
        if not self.flight_path.exists():
            result["reason"] = "no_flight_recorder"
            self._set_reward_status_state(status=result["reason"], error="")
            self._trace_reward("reward_train_skip reason=no_flight_recorder path=%s", self.flight_path)
            return result
        if not bool(due_info["due"]):
            self._set_reward_status_state(status="not_due", error="")
            self._trace_reward("reward_train_skip reason=not_due")
            return result

        self._state["reward_last_attempt_at"] = now.isoformat()
        self._trace_reward(
            (
                "reward_train_start transitions_path=%s output_path=%s epochs=%s lr=%s l2=%s min_examples=%s"
            ),
            self.flight_path,
            self.reward_model_path,
            self.reward_train_epochs,
            self.reward_train_lr,
            self.reward_train_l2,
            self.reward_train_min_examples,
        )
        try:
            training = train_reward_model(
                transitions_path=self.flight_path,
                output_path=self.reward_model_path,
                epochs=self.reward_train_epochs,
                lr=self.reward_train_lr,
                l2=self.reward_train_l2,
                min_examples=self.reward_train_min_examples,
            )
        except Exception as exc:
            training = {
                "trained": False,
                "reason": "train_error",
                "samples": 0,
                "error": str(exc),
            }
            self._trace_reward("reward_train_error error=%s", exc)

        result["ran"] = True
        result["trained"] = bool(training.get("trained", False))
        result["reason"] = str(training.get("reason") or result["reason"])
        result["samples"] = int(training.get("samples", 0) or 0)
        if training.get("output_path"):
            result["model_path"] = str(training.get("output_path"))
        if training.get("error"):
            result["error"] = str(training.get("error"))

        if result["trained"]:
            self._state["reward_last_trained_at"] = now.isoformat()
            self._state["reward_last_train_processed_total"] = int(
                self._state.get("flight_processed_total", 0) or 0
            )
            self._state["reward_last_samples"] = result["samples"]
            self._set_reward_status_state(status="trained", error="", attempted_at=now, save=False)
            self._load_reward_model_if_available()
        else:
            self._set_reward_status_state(
                status=str(result.get("reason") or "not_trained"),
                error=str(result.get("error") or ""),
                attempted_at=now,
                save=False,
            )

        self._trace_reward(
            (
                "reward_train_done trained=%s reason=%s samples=%s new_last_processed=%s "
                "state_status=%s state_error=%s"
            ),
            bool(result.get("trained", False)),
            str(result.get("reason", "")),
            int(result.get("samples", 0) or 0),
            int(self._state.get("reward_last_train_processed_total", 0) or 0),
            str(self._state.get("reward_last_status", "")),
            str(self._state.get("reward_last_error", "")),
        )
        self._save_state()
        self._emit_event("learning.reward_training", result)
        return result

    def _build_lora_config(self) -> LoRAConfig:
        return LoRAConfig(
            rank=self.lora_rank,
            alpha=self.lora_alpha,
            dropout=self.lora_dropout,
            learning_rate=self.lora_learning_rate,
            batch_size=self.lora_batch_size,
            gradient_accumulation_steps=self.lora_gradient_accumulation_steps,
            num_epochs=self.lora_num_epochs,
            warmup_ratio=self.lora_warmup_ratio,
            weight_decay=self.lora_weight_decay,
            max_seq_length=self.lora_max_seq_length,
        )

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        try:
            return float(value)
        except Exception:
            return None

    @classmethod
    def _sanitize_metrics(cls, metrics: Any) -> Dict[str, float]:
        if not isinstance(metrics, dict):
            return {}
        sanitized: Dict[str, float] = {}
        for key, value in metrics.items():
            parsed = cls._float_or_none(value)
            if parsed is None:
                continue
            sanitized[str(key)] = float(parsed)
        return sanitized

    @staticmethod
    def _metric_delta(candidate: Optional[float], baseline: Optional[float]) -> Optional[float]:
        if candidate is None or baseline is None:
            return None
        return round(candidate - baseline, 6)

    def _persist_lora_eval_report(self, report: Dict[str, Any]) -> None:
        try:
            _append_jsonl(self.lora_eval_history_path, report)
        except Exception as exc:
            logger.warning("Unable to persist LoRA evaluation report: %s", exc)

    def _build_lora_eval_report(
        self,
        *,
        timestamp: datetime,
        result: Dict[str, Any],
        candidate_metrics: Dict[str, float],
        active_adapter_id: str = "",
        active_metrics: Optional[Dict[str, float]] = None,
        activation_decision: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        active_payload = self._sanitize_metrics(active_metrics or {})
        candidate_loss = self._float_or_none(candidate_metrics.get("loss"))
        active_loss = self._float_or_none(active_payload.get("loss"))
        candidate_acc = self._float_or_none(candidate_metrics.get("accuracy"))
        active_acc = self._float_or_none(active_payload.get("accuracy"))
        candidate_ppl = self._float_or_none(candidate_metrics.get("perplexity"))
        active_ppl = self._float_or_none(active_payload.get("perplexity"))

        report = {
            "timestamp": timestamp.isoformat(),
            "trainer_backend": self.lora_trainer_backend,
            "candidate_adapter_id": str(result.get("adapter_id") or ""),
            "candidate_adapter_name": str(result.get("adapter_name") or ""),
            "active_adapter_id": str(active_adapter_id or ""),
            "candidate_metrics": self._sanitize_metrics(candidate_metrics),
            "active_metrics": active_payload,
            "deltas": {
                "loss_delta": self._metric_delta(candidate_loss, active_loss),
                "accuracy_delta": self._metric_delta(candidate_acc, active_acc),
                "perplexity_delta": self._metric_delta(candidate_ppl, active_ppl),
            },
            "improvement_flags": {
                "loss_improved": bool(candidate_loss is not None and active_loss is not None and candidate_loss < active_loss),
                "accuracy_improved": bool(candidate_acc is not None and active_acc is not None and candidate_acc > active_acc),
                "perplexity_improved": bool(candidate_ppl is not None and active_ppl is not None and candidate_ppl < active_ppl),
            },
            "activation_decision": {
                "reason": str((activation_decision or {}).get("reason") or ""),
                "activate": bool((activation_decision or {}).get("activate", False)),
            },
            "activated": bool(result.get("activated", False)),
        }
        return report

    def _lora_train_due(self, now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
        now_dt = now or datetime.now()
        total_examples = int(self.example_store.count())
        last_examples = int(self._state.get("lora_last_train_example_count", 0) or 0)
        new_since = max(0, total_examples - last_examples)
        last_trained_at = self._parse_datetime(str(self._state.get("lora_last_trained_at", "") or ""))
        days_since = None
        if last_trained_at is not None:
            days_since = (now_dt - last_trained_at).days

        due = False
        reason = "not_due"
        if force:
            due = True
            reason = "forced"
        elif total_examples < self.lora_train_min_examples:
            reason = "below_min_examples"
        elif last_trained_at is None:
            due = True
            reason = "first_train_ready"
        elif days_since is not None and days_since >= self.lora_train_max_interval_days and new_since > 0:
            due = True
            reason = "monthly_interval_elapsed"

        return {
            "due": due,
            "reason": reason,
            "total_examples": total_examples,
            "last_train_example_count": last_examples,
            "new_examples_since_last_train": new_since,
            "days_since_last_train": days_since,
        }

    def _should_activate_lora_adapter(
        self,
        adapter: Any,
        metrics: Dict[str, float],
        active_adapter: Optional[Any] = None,
        active_eval_metrics: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        if not self.lora_auto_activate_enabled:
            return {"activate": False, "reason": "auto_activate_disabled"}

        active_adapter = active_adapter or self.adapter_registry.get_active_adapter()
        if active_adapter is None:
            return {"activate": True, "reason": "no_active_adapter"}

        if not self.lora_auto_replace_active:
            return {
                "activate": False,
                "reason": "active_adapter_present",
                "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
            }

        candidate_val_loss = self._float_or_none(getattr(adapter, "validation_loss", None))
        if candidate_val_loss is None:
            candidate_val_loss = self._float_or_none(metrics.get("loss"))

        active_val_loss = self._float_or_none(getattr(active_adapter, "validation_loss", None))
        if active_val_loss is None:
            active_val_loss = self._float_or_none((active_eval_metrics or {}).get("loss"))
        if (
            candidate_val_loss is not None
            and active_val_loss is not None
            and candidate_val_loss <= (active_val_loss - self.lora_replace_min_val_loss_delta)
        ):
            return {
                "activate": True,
                "reason": "validation_loss_improved",
                "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
            }

        candidate_acc = self._float_or_none(metrics.get("accuracy"))
        active_metrics = self._sanitize_metrics(active_eval_metrics or getattr(active_adapter, "metrics", {}) or {})
        active_acc = self._float_or_none(active_metrics.get("accuracy"))
        if (
            candidate_acc is not None
            and active_acc is not None
            and candidate_acc >= (active_acc + self.lora_replace_min_accuracy_delta)
        ):
            return {
                "activate": True,
                "reason": "accuracy_improved",
                "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
            }
        if candidate_acc is not None and active_acc is None and candidate_acc >= self.lora_activation_min_accuracy:
            return {
                "activate": True,
                "reason": "accuracy_floor_pass",
                "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
            }

        return {
            "activate": False,
            "reason": "no_metric_improvement",
            "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
        }

    def maybe_train_lora_adapter(self, force: bool = False) -> Dict[str, Any]:
        now = datetime.now()
        due_info = self._lora_train_due(now=now, force=force)
        result: Dict[str, Any] = {
            "enabled": bool(self.lora_auto_train_enabled),
            "trained": False,
            "ran": False,
            "reason": due_info["reason"],
            "trainer_backend": self.lora_trainer_backend,
            "trainer_backend_preference": self.lora_trainer_backend_preference,
            "trainer_backend_reason": self.lora_trainer_backend_reason,
            "eval_compare_active_enabled": bool(self.lora_eval_compare_active),
            "total_examples": due_info["total_examples"],
            "min_examples_required": self.lora_train_min_examples,
            "new_examples_since_last_train": due_info["new_examples_since_last_train"],
            "days_since_last_train": due_info["days_since_last_train"],
            "max_interval_days": self.lora_train_max_interval_days,
            "base_model": self.lora_train_base_model,
            "adapter_name_prefix": self.lora_train_name_prefix,
            "adapter_id": "",
            "adapter_name": "",
            "activated": False,
            "activation_reason": "",
            "metrics": {},
            "active_metrics": {},
        }
        if not self.lora_auto_train_enabled:
            result["reason"] = "disabled"
            return result
        if not bool(due_info["due"]):
            return result

        self._state["lora_last_attempt_at"] = now.isoformat()
        config = self._build_lora_config()
        adapter_name = f"{self.lora_train_name_prefix}_{now.strftime('%Y%m%d')}"
        tags = ["auto", "cadence", "monthly"]

        try:
            adapter = self.pipeline.train_adapter(
                name=adapter_name,
                base_model=self.lora_train_base_model,
                config=config,
                min_quality=self.lora_train_min_quality,
                tags=tags,
            )
        except Exception as exc:
            adapter = None
            result["error"] = str(exc)
            result["reason"] = "train_error"

        result["ran"] = True
        if adapter is None:
            if "error" not in result:
                result["reason"] = "train_failed_or_insufficient_examples"
            self._state["lora_last_status"] = str(result.get("reason") or "not_trained")
            self._state["lora_last_error"] = str(result.get("error") or "")[:220]
            self._save_state()
            self._emit_event("learning.lora_training", result)
            return result

        result["trained"] = True
        result["adapter_id"] = str(getattr(adapter, "adapter_id", "") or "")
        result["adapter_name"] = str(getattr(adapter, "name", "") or "")
        result["training_examples_count"] = int(getattr(adapter, "training_examples_count", 0) or 0)
        result["training_loss"] = self._float_or_none(getattr(adapter, "training_loss", None))
        result["validation_loss"] = self._float_or_none(getattr(adapter, "validation_loss", None))

        metrics: Dict[str, float] = {}
        if self.lora_auto_evaluate_enabled and result["adapter_id"]:
            try:
                metrics = self._sanitize_metrics(self.pipeline.evaluate_adapter(result["adapter_id"]))
            except Exception as exc:
                result["evaluation_error"] = str(exc)
        result["metrics"] = metrics

        active_adapter = self.adapter_registry.get_active_adapter()
        active_adapter_id = str(getattr(active_adapter, "adapter_id", "") or "")
        result["active_adapter_id"] = active_adapter_id

        active_metrics: Dict[str, float] = {}
        if (
            self.lora_auto_evaluate_enabled
            and self.lora_eval_compare_active
            and active_adapter_id
            and active_adapter_id != result["adapter_id"]
        ):
            try:
                active_metrics = self._sanitize_metrics(self.pipeline.evaluate_adapter(active_adapter_id))
            except Exception as exc:
                result["active_evaluation_error"] = str(exc)
        result["active_metrics"] = active_metrics

        activation_decision = self._should_activate_lora_adapter(
            adapter,
            metrics,
            active_adapter=active_adapter,
            active_eval_metrics=active_metrics,
        )
        result["activation_reason"] = str(activation_decision.get("reason") or "")
        if bool(activation_decision.get("activate")) and result["adapter_id"]:
            try:
                self.adapter_registry.activate_adapter(result["adapter_id"])
                result["activated"] = True
            except Exception as exc:
                result["activated"] = False
                result["activation_reason"] = "activate_failed"
                result["activation_error"] = str(exc)

        eval_report = self._build_lora_eval_report(
            timestamp=now,
            result=result,
            candidate_metrics=metrics,
            active_adapter_id=active_adapter_id,
            active_metrics=active_metrics,
            activation_decision=activation_decision,
        )
        result["evaluation_report"] = eval_report
        self._persist_lora_eval_report(eval_report)

        self._state["lora_last_trained_at"] = now.isoformat()
        self._state["lora_last_train_example_count"] = int(due_info["total_examples"])
        self._state["lora_last_adapter_id"] = str(result.get("adapter_id") or "")
        self._state["lora_last_status"] = "trained"
        self._state["lora_last_error"] = str(
            result.get("activation_error")
            or result.get("active_evaluation_error")
            or result.get("evaluation_error")
            or ""
        )[:220]
        self._state["lora_last_metrics"] = metrics
        self._state["lora_last_activation_reason"] = str(result.get("activation_reason") or "")
        self._state["lora_last_eval_report"] = eval_report

        self._save_state()
        self._emit_event("learning.lora_training", result)
        return result

    @staticmethod
    def _clamp_reward_score(value: Any) -> float:
        try:
            score = float(value)
        except Exception:
            score = 0.0
        return max(-1.0, min(1.0, score))

    def _score_workflow_transition(
        self,
        task_text: str,
        chain: List[str],
        success: bool,
        error: str = "",
    ) -> float:
        if not self.reward_model:
            return 0.0
        try:
            synthetic_transition = {
                "action": {
                    "type": "tool_call",
                    "tool_name": chain[0] if chain else "workflow",
                },
                "result": {
                    "success": bool(success),
                    "error": str(error or "")[:180],
                },
                "action_preview": str(task_text or "")[:400],
                "meta": {
                    "latency_ms": 0.0,
                },
            }
            return self._clamp_reward_score(self.reward_model.score_entry(synthetic_transition))
        except Exception:
            return 0.0

    def _apply_workflow_reward_score(self, entry: Dict[str, Any], score: float, now_iso: str) -> None:
        score = self._clamp_reward_score(score)
        samples = int(entry.get("reward_samples", 0) or 0)
        prior = self._clamp_reward_score(entry.get("reward_score_ema", 0.0))
        alpha = 0.3
        ema = score if samples <= 0 else ((1.0 - alpha) * prior + alpha * score)
        entry["reward_last_score"] = round(score, 4)
        entry["reward_score_ema"] = round(self._clamp_reward_score(ema), 4)
        entry["reward_samples"] = samples + 1
        entry["reward_last_scored_at"] = now_iso

    @staticmethod
    def _sanitize_tool_chain(tools_used: List[str]) -> List[str]:
        chain: List[str] = []
        last = None
        for name in tools_used:
            if not isinstance(name, str) or not name:
                continue
            if name == last:
                continue
            chain.append(name)
            last = name
        return chain

    @staticmethod
    def _tokenize_task(text: str) -> List[str]:
        lowered = re.sub(r"[^a-z0-9\s]", " ", str(text or "").lower())
        tokens = [tok for tok in lowered.split() if len(tok) >= 3]
        stop = {
            "the", "and", "for", "that", "this", "with", "from", "into", "then",
            "please", "could", "would", "about", "your", "have", "has", "was",
            "what", "when", "where", "which", "while", "after", "before",
        }
        return [tok for tok in tokens if tok not in stop][:20]

    def _task_signature(self, text: str) -> str:
        tokens = sorted(set(self._tokenize_task(text)))
        if not tokens:
            return "generic"
        canonical = " ".join(tokens[:10])
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
        return f"{tokens[0]}:{digest}"

    @staticmethod
    def _workflow_entry_defaults(signature: str, tokens: List[str], chain: List[str]) -> Dict[str, Any]:
        return {
            "signature": signature,
            "tokens": list(tokens or []),
            "tool_chain": list(chain or []),
            "success_count": 0,
            "failure_count": 0,
            "replay_success_count": 0,
            "replay_failure_count": 0,
            "consecutive_failures": 0,
            "last_used_at": "",
            "sample_task": "",
            "last_conversation_id": "",
            "last_error": "",
            "last_failure_tag": "",
            "last_failure_at": "",
            "last_replay_at": "",
            "last_replay_outcome": "",
            "last_replay_error": "",
            "last_suggested_at": "",
            "last_suggested_score": 0.0,
            "reward_score_ema": 0.0,
            "reward_last_score": 0.0,
            "reward_samples": 0,
            "reward_last_scored_at": "",
            "disabled_until": "",
            "disabled_reason": "",
            "quarantine_count": 0,
            "quarantine_until": "",
            "quarantine_reason": "",
            "quarantine_last_at": "",
            "quarantine_last_failure_tag": "",
            "quarantine_requires_fresh_success": False,
            "quarantine_success_baseline": 0,
            "quarantine_propagated_count": 0,
            # --- Skill identity & trust ---
            "source": "self_crafted",
            "trust_tier": "provisional",
            "human_name": "",
            "description": "",
            "created_at": "",
        }

    @staticmethod
    def _compute_trust_tier(entry: Dict[str, Any]) -> str:
        """Derive trust tier from success history and source."""
        success = int(entry.get("success_count", 0) or 0)
        replay_success = int(entry.get("replay_success_count", 0) or 0)
        failure = int(entry.get("failure_count", 0) or 0)
        total = success + failure
        reliability = success / max(total, 1)
        source = entry.get("source", "self_crafted")

        if source == "external":
            return "untrusted"
        if entry.get("disabled_until") or entry.get("quarantine_until"):
            return "quarantined"
        if total < 2:
            return "provisional"
        if reliability >= 0.8 and replay_success >= 3:
            return "proven"
        if reliability >= 0.6 and success >= 2:
            return "trusted"
        return "provisional"

    def _normalize_workflow_entry(
        self,
        entry: Dict[str, Any],
        signature: str,
        task_text: str,
        chain: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        base_chain = self._sanitize_tool_chain(chain or entry.get("tool_chain", []))
        if not base_chain:
            base_chain = self._sanitize_tool_chain(entry.get("tool_chain", []))
        defaults = self._workflow_entry_defaults(
            signature=signature,
            tokens=self._tokenize_task(task_text),
            chain=base_chain,
        )
        normalized = dict(defaults)
        normalized.update(entry or {})
        normalized["signature"] = signature
        normalized["tokens"] = list(normalized.get("tokens") or self._tokenize_task(task_text))
        normalized["tool_chain"] = self._sanitize_tool_chain(normalized.get("tool_chain", []))
        if not normalized["tool_chain"]:
            normalized["tool_chain"] = list(base_chain)
        for key in (
            "success_count",
            "failure_count",
            "replay_success_count",
            "replay_failure_count",
            "consecutive_failures",
            "reward_samples",
            "quarantine_count",
            "quarantine_success_baseline",
            "quarantine_propagated_count",
        ):
            try:
                normalized[key] = int(normalized.get(key, 0) or 0)
            except Exception:
                normalized[key] = 0
        normalized["quarantine_requires_fresh_success"] = bool(
            normalized.get("quarantine_requires_fresh_success", False)
        )
        try:
            normalized["last_suggested_score"] = float(normalized.get("last_suggested_score", 0.0) or 0.0)
        except Exception:
            normalized["last_suggested_score"] = 0.0
        normalized["reward_score_ema"] = self._clamp_reward_score(normalized.get("reward_score_ema", 0.0))
        normalized["reward_last_score"] = self._clamp_reward_score(normalized.get("reward_last_score", 0.0))
        normalized["last_failure_tag"] = str(normalized.get("last_failure_tag", "") or "")[:120]
        normalized["last_failure_at"] = str(normalized.get("last_failure_at", "") or "")[:64]
        return normalized

    @staticmethod
    def _parse_datetime(value: str) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _load_workflow_triggers(self) -> None:
        payload = _safe_read_json(self.workflow_trigger_path, {"triggers": []})
        if not isinstance(payload, dict):
            payload = {"triggers": []}
        self._workflow_triggers = payload
        try:
            self._workflow_trigger_mtime = float(self.workflow_trigger_path.stat().st_mtime)
        except Exception:
            self._workflow_trigger_mtime = 0.0
        self._trace_workflow(
            "workflow_triggers_loaded path=%s trigger_count=%s",
            self.workflow_trigger_path,
            len(list(payload.get("triggers", []) or [])),
        )

    def _refresh_workflow_triggers_if_needed(self) -> None:
        if not self.workflow_trigger_path.exists():
            if self._workflow_trigger_mtime != 0.0:
                self._workflow_trigger_mtime = 0.0
                self._workflow_triggers = {"triggers": []}
                self._trace_workflow("workflow_triggers_cleared path=%s", self.workflow_trigger_path)
            return
        try:
            current_mtime = float(self.workflow_trigger_path.stat().st_mtime)
        except Exception:
            return
        if current_mtime > self._workflow_trigger_mtime:
            self._load_workflow_triggers()

    def _match_workflow_trigger(self, task_text: str) -> Optional[Dict[str, Any]]:
        self._refresh_workflow_triggers_if_needed()
        lowered = str(task_text or "").strip().lower()
        if not lowered:
            return None

        payload = self._workflow_triggers if isinstance(self._workflow_triggers, dict) else {}
        best_match: Optional[Dict[str, Any]] = None
        best_score = -1
        for raw_trigger in list(payload.get("triggers", []) or []):
            if not isinstance(raw_trigger, dict):
                continue
            if not bool(raw_trigger.get("enabled", True)):
                continue

            phrases = raw_trigger.get("contains", raw_trigger.get("phrases", []))
            phrase_list = [str(item).strip().lower() for item in list(phrases or []) if str(item).strip()]
            if not phrase_list:
                continue
            if not any(phrase in lowered for phrase in phrase_list):
                continue

            chain = self._sanitize_tool_chain(raw_trigger.get("tool_chain", []))
            if len(chain) < 2:
                continue

            trigger_name = str(raw_trigger.get("name") or "custom_trigger").strip() or "custom_trigger"
            confidence = 0.92
            try:
                confidence = float(raw_trigger.get("confidence", 0.92) or 0.92)
            except Exception:
                confidence = 0.92
            confidence = max(0.0, min(0.99, confidence))

            hit_score = max(len(phrase) for phrase in phrase_list)
            if hit_score > best_score:
                signature_seed = f"{trigger_name}:{'|'.join(chain)}"
                best_match = {
                    "signature": f"trigger:{hashlib.sha256(signature_seed.encode('utf-8')).hexdigest()[:12]}",
                    "tool_chain": chain,
                    "source": "trigger",
                    "confidence": round(confidence, 4),
                    "reliability": 1.0,
                    "reward_score_ema": 0.0,
                    "success_count": int(raw_trigger.get("success_count_seed", 2) or 2),
                    "failure_count": 0,
                    "trigger_name": trigger_name,
                    "matched_phrases": phrase_list,
                }
                best_score = hit_score

        if best_match:
            self._trace_workflow(
                "plan_lookup_hit source=trigger trigger_name=%s chain=%s",
                str(best_match.get("trigger_name", "")),
                list(best_match.get("tool_chain", [])),
            )
        return best_match

    def _is_workflow_disabled(self, entry: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        now_dt = now or datetime.now()
        disabled_until = self._parse_datetime(str(entry.get("disabled_until") or ""))
        if disabled_until is None:
            return False
        if disabled_until <= now_dt:
            entry["disabled_until"] = ""
            entry["disabled_reason"] = ""
            return False
        return True

    @staticmethod
    def _classify_workflow_failure_tag(error: str) -> str:
        lowered = str(error or "").strip().lower()
        if not lowered:
            return ""
        if (
            "tool call limit reached" in lowered
            or "tool_call_limit_reached" in lowered
            or "no_progress_tool_loop" in lowered
        ):
            return "tool_call_limit_reached"
        if "tool_timeout" in lowered or "tool execution timeout" in lowered:
            return "tool_timeout"
        if "tool execution error" in lowered or "tool_execution_error" in lowered:
            return "tool_execution_error"
        if "llm_timeout" in lowered or "llm request timed out" in lowered:
            return "llm_timeout"
        if (
            "confirmation_required" in lowered
            or "confirmation required" in lowered
            or "awaiting confirmation" in lowered
            or "reply 'yes' to proceed" in lowered
            or "reply \"yes\" to proceed" in lowered
        ):
            return "confirmation_required"
        if "cached_chain_not_completed" in lowered or "cached chain not completed" in lowered:
            return "cached_chain_not_completed"
        if (
            "chain_mismatch" in lowered
            or "chain mismatch" in lowered
            or ("expected_" in lowered and "_got_" in lowered)
            or ("expected " in lowered and " got " in lowered)
        ):
            return "chain_mismatch"
        return ""

    @staticmethod
    def _clear_workflow_quarantine(entry: Dict[str, Any], reason: str = "") -> None:
        entry["quarantine_until"] = ""
        entry["quarantine_reason"] = ""
        entry["quarantine_last_at"] = ""
        entry["quarantine_requires_fresh_success"] = False
        entry["quarantine_success_baseline"] = 0
        entry["quarantine_last_cleared_reason"] = str(reason or "")
        entry["quarantine_last_failure_tag"] = ""

    @staticmethod
    def _workflow_chain_key(chain: List[str]) -> str:
        return "|".join(
            str(name).strip()
            for name in list(chain or [])
            if isinstance(name, str) and str(name).strip()
        )

    def _apply_replay_quarantine(
        self,
        entry: Dict[str, Any],
        *,
        now: datetime,
        failure_tag: str,
        reason_prefix: str = "replay_failure",
    ) -> bool:
        if not failure_tag:
            return False

        reason_value = f"{reason_prefix}:{failure_tag}"
        baseline = int(entry.get("success_count", 0) or 0)
        quarantine_until_dt = now + timedelta(minutes=self.workflow_quarantine_minutes)
        existing_until = self._parse_datetime(str(entry.get("quarantine_until") or ""))

        entry["quarantine_count"] = int(entry.get("quarantine_count", 0) or 0) + 1
        if existing_until is None or existing_until < quarantine_until_dt:
            entry["quarantine_until"] = quarantine_until_dt.isoformat()
        entry["quarantine_reason"] = reason_value
        entry["quarantine_last_at"] = now.isoformat()
        entry["quarantine_last_failure_tag"] = failure_tag
        entry["quarantine_requires_fresh_success"] = True
        entry["quarantine_success_baseline"] = baseline
        return True

    def _propagate_chain_quarantine(
        self,
        templates: Dict[str, Any],
        *,
        source_signature: str,
        chain: List[str],
        now: datetime,
        failure_tag: str,
    ) -> int:
        source_key = self._workflow_chain_key(chain)
        if not source_key:
            return 0

        propagated = 0
        for candidate_signature, raw_candidate in list(templates.items()):
            if candidate_signature == source_signature or not isinstance(raw_candidate, dict):
                continue
            candidate_entry = self._normalize_workflow_entry(
                raw_candidate,
                signature=candidate_signature,
                task_text=str(raw_candidate.get("sample_task") or ""),
            )
            candidate_chain = self._sanitize_tool_chain(candidate_entry.get("tool_chain", []))
            if self._workflow_chain_key(candidate_chain) != source_key:
                continue

            if self._apply_replay_quarantine(
                candidate_entry,
                now=now,
                failure_tag=failure_tag,
                reason_prefix="propagated_replay_failure",
            ):
                templates[candidate_signature] = candidate_entry
                propagated += 1

        if propagated > 0:
            self._trace_workflow(
                "record_replay_quarantine_propagated source_signature=%s failure_tag=%s propagated=%s chain=%s",
                source_signature,
                failure_tag,
                propagated,
                chain,
            )
        return propagated

    def _workflow_quarantine_state(
        self,
        entry: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> Tuple[bool, bool, str]:
        now_dt = now or datetime.now()
        changed = False

        try:
            success_count = int(entry.get("success_count", 0) or 0)
        except Exception:
            success_count = 0
        try:
            baseline = int(entry.get("quarantine_success_baseline", 0) or 0)
        except Exception:
            baseline = 0
        requires_fresh_success = bool(entry.get("quarantine_requires_fresh_success", False))
        quarantine_until = self._parse_datetime(str(entry.get("quarantine_until") or ""))

        if requires_fresh_success and success_count > baseline:
            self._clear_workflow_quarantine(entry, reason="fresh_success")
            changed = True
            return False, changed, "fresh_success"

        if quarantine_until is not None and quarantine_until > now_dt:
            return True, changed, "active"

        if requires_fresh_success and success_count <= baseline:
            return True, changed, "awaiting_fresh_success"

        if quarantine_until is not None and quarantine_until <= now_dt:
            self._clear_workflow_quarantine(entry, reason="expired")
            changed = True
            return False, changed, "expired"

        return False, changed, ""

    @staticmethod
    def _workflow_reliability(entry: Dict[str, Any]) -> float:
        success = int(entry.get("success_count", 0)) + int(entry.get("replay_success_count", 0))
        failure = int(entry.get("failure_count", 0)) + int(entry.get("replay_failure_count", 0))
        total = success + failure
        if total <= 0:
            return 0.0
        return success / total

    @staticmethod
    def _workflow_total_failures(entry: Dict[str, Any]) -> int:
        return int(entry.get("failure_count", 0) or 0) + int(entry.get("replay_failure_count", 0) or 0)

    def _workflow_failure_tag_from_entry(self, entry: Dict[str, Any]) -> str:
        explicit = str(entry.get("last_failure_tag", "") or "").strip().lower()
        if explicit:
            return explicit
        quarantine_tag = str(entry.get("quarantine_last_failure_tag", "") or "").strip().lower()
        if quarantine_tag:
            return quarantine_tag
        for field in ("last_replay_error", "last_error", "quarantine_reason"):
            tag = self._classify_workflow_failure_tag(str(entry.get(field, "") or ""))
            if tag:
                return tag
        return ""

    def _workflow_reward_component(self, entry: Dict[str, Any]) -> float:
        score = self._clamp_reward_score(entry.get("reward_score_ema", 0.0))
        samples = int(entry.get("reward_samples", 0) or 0)
        confidence_scale = min(1.0, samples / 3.0)
        return ((score + 1.0) / 2.0) * confidence_scale

    def _resolve_workflow_signature(
        self,
        task_text: str,
        chain: List[str],
        explicit_signature: str = "",
    ) -> str:
        templates = self._workflows.setdefault("templates", {})
        if explicit_signature and explicit_signature in templates:
            return explicit_signature

        task_signature = self._task_signature(task_text)
        task_entry = templates.get(task_signature)
        if task_entry and self._sanitize_tool_chain(task_entry.get("tool_chain", [])) == chain:
            return task_signature

        best_signature = ""
        best_overlap = -1
        query_tokens = set(self._tokenize_task(task_text))
        for signature, entry in templates.items():
            if self._sanitize_tool_chain(entry.get("tool_chain", [])) != chain:
                continue
            tokens = set(entry.get("tokens", []))
            overlap = len(query_tokens & tokens) if query_tokens else 0
            if overlap > best_overlap:
                best_overlap = overlap
                best_signature = signature
        return best_signature or task_signature

    def record_workflow_outcome(
        self,
        task_text: str,
        tools_used: List[str],
        success: bool,
        conversation_id: str = "default",
        error: str = "",
    ) -> None:
        self._diag["workflow_outcome_calls"] = int(self._diag.get("workflow_outcome_calls", 0) or 0) + 1
        self._diag["workflow_outcome_last"] = {
            "at": datetime.now().isoformat(),
            "conversation_id": str(conversation_id or "default"),
            "success": bool(success),
            "chain": self._sanitize_tool_chain(tools_used),
            "error": self._short_text(error, 180),
            "task": self._short_task(task_text, 180),
        }
        chain = self._sanitize_tool_chain(tools_used)
        if len(chain) < 2:
            self._diag["workflow_outcome_skip_short_chain"] = int(
                self._diag.get("workflow_outcome_skip_short_chain", 0) or 0
            ) + 1
            self._trace_workflow(
                "record_outcome_skip reason=chain_too_short chain=%s conversation_id=%s",
                chain,
                str(conversation_id or "default"),
            )
            return

        signature = self._task_signature(task_text)
        templates = self._workflows.setdefault("templates", {})
        now = datetime.now()
        entry = self._normalize_workflow_entry(
            templates.get(signature, {}),
            signature=signature,
            task_text=task_text,
            chain=chain,
        )

        entry["tool_chain"] = chain
        entry["last_used_at"] = now.isoformat()
        entry["sample_task"] = str(task_text or "")[:180]
        entry["last_conversation_id"] = conversation_id
        if not entry.get("created_at"):
            entry["created_at"] = now.isoformat()
        if not entry.get("source"):
            entry["source"] = "self_crafted"
        if success:
            entry["success_count"] = int(entry.get("success_count", 0)) + 1
            entry["consecutive_failures"] = 0
            entry["last_error"] = ""
            entry["last_failure_tag"] = ""
            entry["last_failure_at"] = ""
            entry["disabled_until"] = ""
            entry["disabled_reason"] = ""
            if bool(entry.get("quarantine_requires_fresh_success", False)):
                self._clear_workflow_quarantine(entry, reason="runtime_success")
        else:
            entry["failure_count"] = int(entry.get("failure_count", 0)) + 1
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["last_error"] = str(error or "")[:180]
            failure_tag = self._classify_workflow_failure_tag(error)
            entry["last_failure_tag"] = str(failure_tag or "")[:120]
            entry["last_failure_at"] = now.isoformat()
            if int(entry.get("consecutive_failures", 0)) >= self.workflow_disable_failures:
                disabled_until = now + timedelta(minutes=self.workflow_disable_minutes)
                entry["disabled_until"] = disabled_until.isoformat()
                entry["disabled_reason"] = "consecutive_runtime_failures"
        reward_score = self._score_workflow_transition(
            task_text=task_text,
            chain=chain,
            success=success,
            error=error,
        )
        self._apply_workflow_reward_score(entry, reward_score, now.isoformat())
        entry["trust_tier"] = self._compute_trust_tier(entry)
        templates[signature] = entry
        self._diag["workflow_outcome_saved"] = int(self._diag.get("workflow_outcome_saved", 0) or 0) + 1
        self._save_workflows()
        self._trace_workflow(
            (
                "record_outcome_saved signature=%s success=%s chain=%s success_count=%s "
                "failure_count=%s consecutive_failures=%s disabled_until=%s"
            ),
            signature,
            bool(success),
            chain,
            int(entry.get("success_count", 0) or 0),
            int(entry.get("failure_count", 0) or 0),
            int(entry.get("consecutive_failures", 0) or 0),
            str(entry.get("disabled_until", "")),
        )

    def list_skills(
        self,
        sort_by: str = "trust_tier",
        trust_filter: str = "",
    ) -> List[Dict[str, Any]]:
        """Return learned workflow skills with trust tiers for API consumption."""
        templates = self._workflows.get("templates", {})
        tier_order = {"proven": 0, "trusted": 1, "provisional": 2, "quarantined": 3, "untrusted": 4}
        skills: List[Dict[str, Any]] = []
        for sig, entry in templates.items():
            tier = self._compute_trust_tier(entry)
            if trust_filter and tier != trust_filter:
                continue
            total = int(entry.get("success_count", 0) or 0) + int(entry.get("failure_count", 0) or 0)
            reliability = int(entry.get("success_count", 0) or 0) / max(total, 1)
            skills.append({
                "signature": sig,
                "human_name": entry.get("human_name") or "",
                "description": entry.get("description") or "",
                "tool_chain": entry.get("tool_chain", []),
                "source": entry.get("source", "self_crafted"),
                "trust_tier": tier,
                "success_count": int(entry.get("success_count", 0) or 0),
                "failure_count": int(entry.get("failure_count", 0) or 0),
                "replay_success_count": int(entry.get("replay_success_count", 0) or 0),
                "replay_failure_count": int(entry.get("replay_failure_count", 0) or 0),
                "reliability": round(reliability, 3),
                "reward_score_ema": round(float(entry.get("reward_score_ema", 0) or 0), 3),
                "sample_task": entry.get("sample_task", ""),
                "created_at": entry.get("created_at", ""),
                "last_used_at": entry.get("last_used_at", ""),
            })
        if sort_by == "trust_tier":
            skills.sort(key=lambda s: (tier_order.get(s["trust_tier"], 9), -s["reliability"]))
        elif sort_by == "reliability":
            skills.sort(key=lambda s: -s["reliability"])
        elif sort_by == "recent":
            skills.sort(key=lambda s: s.get("last_used_at", ""), reverse=True)
        return skills

    def get_workflow_plan(self, task_text: str) -> Dict[str, Any]:
        trigger_plan = self._match_workflow_trigger(task_text)
        if trigger_plan:
            return trigger_plan

        templates = self._workflows.get("templates", {})
        if not templates:
            self._trace_workflow("plan_lookup_skip reason=no_templates")
            return {}

        now = datetime.now()
        changed = False
        signature = self._task_signature(task_text)
        direct_raw = templates.get(signature)
        direct: Optional[Dict[str, Any]] = None
        if isinstance(direct_raw, dict):
            direct = self._normalize_workflow_entry(direct_raw, signature, task_text)
            templates[signature] = direct
            if self._is_workflow_disabled(direct, now=now):
                direct = None
            else:
                quarantined, quarantine_changed, quarantine_reason = self._workflow_quarantine_state(direct, now=now)
                if quarantine_changed:
                    changed = True
                if quarantined:
                    self._trace_workflow(
                        "plan_lookup_skip reason=quarantine signature=%s quarantine_reason=%s",
                        signature,
                        quarantine_reason,
                    )
                    direct = None
                else:
                    runtime_success = int(direct.get("success_count", 0))
                    reliability = self._workflow_reliability(direct)
                    if runtime_success >= self.workflow_min_success and reliability >= self.workflow_min_reliability:
                        reward_component = self._workflow_reward_component(direct)
                        confidence = min(0.99, 0.5 + reliability * 0.4 + reward_component * self.workflow_reward_weight)
                        direct["last_suggested_at"] = now.isoformat()
                        direct["last_suggested_score"] = round(confidence, 4)
                        changed = True
                        if changed:
                            self._save_workflows()
                        self._trace_workflow(
                            (
                                "plan_lookup_hit source=direct signature=%s confidence=%.4f "
                                "reliability=%.4f chain=%s"
                            ),
                            signature,
                            float(confidence),
                            float(reliability),
                            list(direct.get("tool_chain", [])),
                        )
                        return {
                            "signature": signature,
                            "tool_chain": list(direct.get("tool_chain", [])),
                            "source": "direct",
                            "confidence": round(confidence, 4),
                            "reliability": round(reliability, 4),
                            "reward_score_ema": round(self._clamp_reward_score(direct.get("reward_score_ema", 0.0)), 4),
                            "success_count": runtime_success,
                            "failure_count": int(direct.get("failure_count", 0)),
                        }

        query_tokens = set(self._tokenize_task(task_text))
        if not query_tokens:
            if changed:
                self._save_workflows()
            self._trace_workflow("plan_lookup_skip reason=no_query_tokens")
            return {}

        best_signature = ""
        best_entry: Optional[Dict[str, Any]] = None
        best_score = 0.0

        for raw_signature, raw_entry in templates.items():
            if not isinstance(raw_entry, dict):
                continue
            entry = self._normalize_workflow_entry(raw_entry, raw_signature, task_text)
            templates[raw_signature] = entry
            if self._is_workflow_disabled(entry, now=now):
                continue
            quarantined, quarantine_changed, quarantine_reason = self._workflow_quarantine_state(entry, now=now)
            if quarantine_changed:
                changed = True
            if quarantined:
                self._trace_workflow(
                    "plan_lookup_skip reason=quarantine signature=%s quarantine_reason=%s",
                    raw_signature,
                    quarantine_reason,
                )
                continue
            candidate_tokens = set(entry.get("tokens", []))
            if not candidate_tokens:
                continue
            overlap = len(query_tokens & candidate_tokens)
            if overlap <= 0:
                continue
            score = overlap / max(len(query_tokens), 1)
            runtime_success = int(entry.get("success_count", 0))
            reliability = self._workflow_reliability(entry)
            reward_component = self._workflow_reward_component(entry)
            lexical_weight = max(0.4, 0.7 - self.workflow_reward_weight)
            reliability_weight = 0.3 - (self.workflow_reward_weight / 3.0)
            weighted = score * lexical_weight + reliability * reliability_weight + reward_component * self.workflow_reward_weight
            if (
                weighted > best_score
                and runtime_success >= self.workflow_min_success
                and reliability >= self.workflow_min_reliability
            ):
                best_score = weighted
                best_signature = raw_signature
                best_entry = entry

        if best_entry and best_score >= self.workflow_fuzzy_min_score:
            best_entry["last_suggested_at"] = now.isoformat()
            best_entry["last_suggested_score"] = round(best_score, 4)
            templates[best_signature] = best_entry
            self._save_workflows()
            self._trace_workflow(
                (
                    "plan_lookup_hit source=fuzzy signature=%s confidence=%.4f "
                    "reliability=%.4f chain=%s"
                ),
                best_signature,
                float(best_score),
                float(self._workflow_reliability(best_entry)),
                list(best_entry.get("tool_chain", [])),
            )
            return {
                "signature": best_signature,
                "tool_chain": list(best_entry.get("tool_chain", [])),
                "source": "fuzzy",
                "confidence": round(best_score, 4),
                "reliability": round(self._workflow_reliability(best_entry), 4),
                "reward_score_ema": round(self._clamp_reward_score(best_entry.get("reward_score_ema", 0.0)), 4),
                "success_count": int(best_entry.get("success_count", 0)),
                "failure_count": int(best_entry.get("failure_count", 0)),
            }

        if changed:
            self._save_workflows()
        self._trace_workflow(
            "plan_lookup_miss reason=no_candidate_above_threshold tokens=%s templates=%s",
            sorted(query_tokens),
            len(templates),
        )
        return {}

    def suggest_workflow_chain(self, task_text: str) -> List[str]:
        plan = self.get_workflow_plan(task_text)
        if not plan:
            return []
        chain = plan.get("tool_chain", [])
        return list(chain) if isinstance(chain, list) else []

    def get_failure_recovery_plan(self, task_text: str) -> Dict[str, Any]:
        """
        Return a compact hint distilled from prior workflow failures.

        The hint contains:
        - failing chain/tools to avoid for similar tasks
        - an alternative high-reliability chain when available
        """
        templates = self._workflows.get("templates", {})
        if not isinstance(templates, dict) or not templates:
            return {}

        query_tokens = set(self._tokenize_task(task_text))
        if not query_tokens:
            return {}

        now = datetime.now()
        changed = False
        best_fail_signature = ""
        best_fail_entry: Optional[Dict[str, Any]] = None
        best_fail_score = 0.0

        for raw_signature, raw_entry in templates.items():
            if not isinstance(raw_entry, dict):
                continue
            entry = self._normalize_workflow_entry(raw_entry, raw_signature, task_text)
            templates[raw_signature] = entry
            candidate_tokens = set(entry.get("tokens", []))
            if not candidate_tokens:
                continue
            overlap = len(query_tokens & candidate_tokens)
            if overlap <= 0:
                continue
            total_failures = self._workflow_total_failures(entry)
            if total_failures <= 0:
                continue

            lexical = overlap / max(len(query_tokens), 1)
            reliability_penalty = 1.0 - self._workflow_reliability(entry)
            failure_weight = min(0.4, total_failures / 10.0)
            failure_tag = self._workflow_failure_tag_from_entry(entry)
            quarantine_bonus = 0.12 if failure_tag in set(self.workflow_quarantine_tags) else 0.0
            recency_bonus = 0.0
            last_failure_dt = self._parse_datetime(str(entry.get("last_failure_at") or ""))
            if last_failure_dt is not None:
                age_hours = max(0.0, (now - last_failure_dt).total_seconds() / 3600.0)
                recency_bonus = max(0.0, 0.25 - min(0.25, age_hours / 96.0))

            score = lexical * 0.55 + reliability_penalty * 0.25 + failure_weight + quarantine_bonus + recency_bonus
            if score > best_fail_score:
                best_fail_score = score
                best_fail_signature = str(raw_signature)
                best_fail_entry = entry

        if best_fail_entry is None:
            if changed:
                self._save_workflows()
            return {}

        avoid_chain = self._sanitize_tool_chain(best_fail_entry.get("tool_chain", []))
        if len(avoid_chain) < 2:
            if changed:
                self._save_workflows()
            return {}

        best_recovery_signature = ""
        best_recovery_chain: List[str] = []
        best_recovery_score = 0.0
        avoid_key = self._workflow_chain_key(avoid_chain)

        for raw_signature, raw_entry in templates.items():
            if raw_signature == best_fail_signature or not isinstance(raw_entry, dict):
                continue
            entry = self._normalize_workflow_entry(raw_entry, raw_signature, task_text)
            templates[raw_signature] = entry

            chain = self._sanitize_tool_chain(entry.get("tool_chain", []))
            if len(chain) < 2:
                continue
            if self._workflow_chain_key(chain) == avoid_key:
                continue

            success_total = int(entry.get("success_count", 0) or 0) + int(entry.get("replay_success_count", 0) or 0)
            reliability = self._workflow_reliability(entry)
            if success_total < self.workflow_min_success or reliability < self.workflow_min_reliability:
                continue

            candidate_tokens = set(entry.get("tokens", []))
            overlap = len(query_tokens & candidate_tokens) if candidate_tokens else 0
            if overlap <= 0:
                continue
            lexical = overlap / max(len(query_tokens), 1)
            reward_component = self._workflow_reward_component(entry)
            score = lexical * 0.55 + reliability * 0.25 + reward_component * self.workflow_reward_weight
            if score > best_recovery_score:
                best_recovery_score = score
                best_recovery_signature = str(raw_signature)
                best_recovery_chain = chain

        if changed:
            self._save_workflows()

        failure_tag = self._workflow_failure_tag_from_entry(best_fail_entry)
        result: Dict[str, Any] = {
            "source_signature": best_fail_signature,
            "source_failure_tag": failure_tag,
            "source_failure_count": self._workflow_total_failures(best_fail_entry),
            "source_reliability": round(self._workflow_reliability(best_fail_entry), 4),
            "source_last_error": self._short_text(
                best_fail_entry.get("last_replay_error") or best_fail_entry.get("last_error") or "",
                200,
            ),
            "avoid_chain": list(avoid_chain),
            "avoid_tools": list(dict.fromkeys(avoid_chain)),
            "confidence": round(min(0.99, max(0.0, best_fail_score)), 4),
        }
        if best_recovery_chain:
            result["suggested_recovery_chain"] = list(best_recovery_chain)
            result["recovery_signature"] = best_recovery_signature
            result["recovery_confidence"] = round(min(0.99, max(0.0, best_recovery_score)), 4)

        self._trace_workflow(
            (
                "failure_recovery_plan source_signature=%s failure_tag=%s avoid=%s "
                "recovery_signature=%s recovery_chain=%s"
            ),
            best_fail_signature,
            failure_tag,
            list(avoid_chain),
            best_recovery_signature,
            list(best_recovery_chain),
        )
        return result

    def record_workflow_replay_result(
        self,
        task_text: str,
        tool_chain: List[str],
        success: bool,
        conversation_id: str = "default",
        error: str = "",
        signature: str = "",
    ) -> None:
        self._diag["workflow_replay_calls"] = int(self._diag.get("workflow_replay_calls", 0) or 0) + 1
        self._diag["workflow_replay_last"] = {
            "at": datetime.now().isoformat(),
            "conversation_id": str(conversation_id or "default"),
            "success": bool(success),
            "chain": self._sanitize_tool_chain(tool_chain),
            "signature": self._short_text(signature, 120),
            "error": self._short_text(error, 180),
            "task": self._short_task(task_text, 180),
        }
        chain = self._sanitize_tool_chain(tool_chain)
        if len(chain) < 2:
            self._diag["workflow_replay_skip_short_chain"] = int(
                self._diag.get("workflow_replay_skip_short_chain", 0) or 0
            ) + 1
            self._trace_workflow(
                "record_replay_skip reason=chain_too_short chain=%s conversation_id=%s",
                chain,
                str(conversation_id or "default"),
            )
            return

        templates = self._workflows.setdefault("templates", {})
        now = datetime.now()
        resolved_signature = self._resolve_workflow_signature(
            task_text=task_text,
            chain=chain,
            explicit_signature=signature,
        )
        entry = self._normalize_workflow_entry(
            templates.get(resolved_signature, {}),
            signature=resolved_signature,
            task_text=task_text,
            chain=chain,
        )
        entry["tool_chain"] = chain
        entry["last_replay_at"] = now.isoformat()
        entry["last_conversation_id"] = str(conversation_id or "default")
        if success:
            entry["replay_success_count"] = int(entry.get("replay_success_count", 0)) + 1
            entry["consecutive_failures"] = 0
            entry["last_replay_outcome"] = "success"
            entry["last_replay_error"] = ""
            entry["last_failure_tag"] = ""
            entry["last_failure_at"] = ""
            entry["disabled_until"] = ""
            entry["disabled_reason"] = ""
            if bool(entry.get("quarantine_requires_fresh_success", False)):
                self._clear_workflow_quarantine(entry, reason="replay_success")
        else:
            entry["replay_failure_count"] = int(entry.get("replay_failure_count", 0)) + 1
            entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
            entry["last_replay_outcome"] = "failure"
            entry["last_replay_error"] = str(error or "")[:220]
            entry["last_failure_at"] = now.isoformat()
            if int(entry.get("consecutive_failures", 0)) >= self.workflow_replay_disable_failures:
                disabled_until = now + timedelta(minutes=self.workflow_disable_minutes)
                entry["disabled_until"] = disabled_until.isoformat()
                entry["disabled_reason"] = "replay_failures"
            failure_tag = self._classify_workflow_failure_tag(error)
            entry["last_failure_tag"] = str(failure_tag or "")[:120]
            propagated = 0
            if failure_tag and failure_tag in set(self.workflow_quarantine_tags):
                self._apply_replay_quarantine(
                    entry,
                    now=now,
                    failure_tag=failure_tag,
                    reason_prefix="replay_failure",
                )
                propagated = self._propagate_chain_quarantine(
                    templates,
                    source_signature=resolved_signature,
                    chain=chain,
                    now=now,
                    failure_tag=failure_tag,
                )
                if propagated > 0:
                    entry["quarantine_propagated_count"] = int(
                        entry.get("quarantine_propagated_count", 0) or 0
                    ) + propagated
                self._trace_workflow(
                    (
                        "record_replay_quarantine signature=%s failure_tag=%s "
                        "quarantine_until=%s success_baseline=%s propagated=%s"
                    ),
                    resolved_signature,
                    failure_tag,
                    entry.get("quarantine_until", ""),
                    int(entry.get("quarantine_success_baseline", 0) or 0),
                    int(propagated),
                )
        reward_score = self._score_workflow_transition(
            task_text=task_text,
            chain=chain,
            success=success,
            error=error,
        )
        self._apply_workflow_reward_score(entry, reward_score, now.isoformat())
        templates[resolved_signature] = entry
        self._diag["workflow_replay_saved"] = int(self._diag.get("workflow_replay_saved", 0) or 0) + 1
        self._save_workflows()
        self._trace_workflow(
            (
                "record_replay_saved signature=%s success=%s chain=%s replay_success=%s "
                "replay_failure=%s consecutive_failures=%s disabled_until=%s "
                "quarantine_until=%s quarantine_reason=%s"
            ),
            resolved_signature,
            bool(success),
            chain,
            int(entry.get("replay_success_count", 0) or 0),
            int(entry.get("replay_failure_count", 0) or 0),
            int(entry.get("consecutive_failures", 0) or 0),
            str(entry.get("disabled_until", "")),
            str(entry.get("quarantine_until", "")),
            str(entry.get("quarantine_reason", "")),
        )

    @staticmethod
    def _parse_context_snapshot(snapshot: str) -> str:
        text = str(snapshot or "").strip()
        if not text:
            return ""
        try:
            payload = json.loads(text)
        except Exception:
            return text[:600]

        if isinstance(payload, list):
            for msg in reversed(payload):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = str(msg.get("content") or "").strip()
                    if content:
                        return content[:600]
            return str(payload[-1]).strip()[:600] if payload else ""
        if isinstance(payload, dict):
            for key in ("user_message", "query_preview", "task", "content"):
                value = str(payload.get(key) or "").strip()
                if value:
                    return value[:600]
        return text[:600]

    @staticmethod
    def _extract_output_text(entry: Dict[str, Any]) -> str:
        action = entry.get("action", {}) or {}
        result = entry.get("result", {}) or {}
        action_type = str(action.get("type") or "")
        if action_type == "llm_call":
            response = result.get("response", {}) or {}
            choices = response.get("choices", []) or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message", {}) or {}
                return str(message.get("content") or "").strip()[:1200]
        if action_type == "tool_call":
            output = result.get("output")
            if isinstance(output, (dict, list)):
                return json.dumps(output, ensure_ascii=True, default=str)[:1200]
            return str(output or "").strip()[:1200]
        preview = str(entry.get("result_preview") or "").strip()
        return preview[:1200]

    @staticmethod
    def _extract_conversation_id(entry: Dict[str, Any]) -> str:
        action = entry.get("action", {}) or {}
        params = action.get("params", {}) or {}
        convo = str(params.get("conversation_id") or "").strip()
        if convo:
            return convo
        snapshot = str(entry.get("context_snapshot") or "")
        if '"conversation_id"' in snapshot:
            try:
                payload = json.loads(snapshot)
                if isinstance(payload, dict):
                    convo = str(payload.get("conversation_id") or "").strip()
                    if convo:
                        return convo
            except Exception:
                pass
        return "default"

    @staticmethod
    def _quality_from_air(air_score: float) -> QualityLevel:
        if air_score >= 0.7:
            return QualityLevel.EXPERT
        if air_score >= 0.4:
            return QualityLevel.HIGH
        if air_score >= 0.1:
            return QualityLevel.MEDIUM
        return QualityLevel.LOW

    def ingest_flight_recorder_transitions(self, max_transitions: Optional[int] = None) -> Dict[str, Any]:
        """Convert flight recorder transitions into distillation trajectories/examples."""
        if not self.flight_path.exists():
            self._trace_reward("flight_ingest_skip reason=no_flight_recorder path=%s", self.flight_path)
            return {"transitions_processed": 0, "examples_created": 0, "reason": "no_flight_recorder"}

        max_items = int(max_transitions or self.flight_batch_max)
        offset = int(self._state.get("flight_offset", 0) or 0)
        start_offset = offset
        processed = 0
        examples_created = 0
        malformed = 0
        self._trace_reward(
            "flight_ingest_start path=%s offset=%s max_items=%s",
            self.flight_path,
            start_offset,
            max_items,
        )

        with self.flight_path.open("r", encoding="utf-8") as handle:
            try:
                handle.seek(offset)
            except Exception:
                handle.seek(0)
                offset = 0

            while processed < max_items:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                line_end = handle.tell()
                stripped = line.strip()
                if not stripped:
                    offset = line_end
                    continue
                try:
                    entry = json.loads(stripped)
                except Exception:
                    malformed += 1
                    offset = line_end
                    continue

                if entry.get("type") != "transition":
                    offset = line_end
                    continue

                action = entry.get("action", {}) or {}
                action_type = str(action.get("type") or "transition")
                air_score = float(entry.get("air_score", 0.0) or 0.0)
                instruction = self._parse_context_snapshot(str(entry.get("context_snapshot") or ""))
                output_text = self._extract_output_text(entry)
                if not instruction or not output_text:
                    offset = line_end
                    continue

                conversation_id = self._extract_conversation_id(entry)
                trajectory_id = self.capture.start_trajectory(
                    task_description=f"flight:{action_type}:{conversation_id}",
                    tags=["flight_recorder", action_type],
                )
                step = TrajectoryStep(
                    step_id=f"flight_step_{processed + 1}",
                    timestamp=datetime.fromisoformat(str(entry.get("timestamp") or datetime.now().isoformat())),
                    input_text=instruction,
                    output_text=output_text,
                    tool_calls=[action] if action_type == "tool_call" else [],
                    tool_results=[entry.get("result", {})] if action_type == "tool_call" else [],
                    reasoning=f"Flight recorder AIR={air_score:.3f}",
                    metadata={
                        "source": "flight_recorder",
                        "transition_uuid": entry.get("uuid", ""),
                        "air_reason": entry.get("air_reason", ""),
                        "is_failure": bool(entry.get("is_failure", False)),
                    },
                )
                self.capture.add_step(trajectory_id, step)
                success_score = max(0.0, min(1.0, (air_score + 1.0) / 2.0))
                self.capture.complete_trajectory(
                    trajectory_id=trajectory_id,
                    success_score=success_score,
                    quality_level=self._quality_from_air(air_score),
                )
                examples = self.pipeline.extract_from_trajectory(trajectory_id)
                examples_created += len(examples)
                processed += 1
                offset = line_end

                # Guard against parser edge cases where tell() can become stale.
                if line_start == line_end:
                    break

        self._state["flight_offset"] = offset
        self._state["flight_processed_total"] = int(self._state.get("flight_processed_total", 0)) + processed
        self._save_state()

        self._trace_reward(
            (
                "flight_ingest_done processed=%s examples=%s malformed=%s offset_before=%s "
                "offset_after=%s flight_processed_total=%s"
            ),
            processed,
            examples_created,
            malformed,
            start_offset,
            offset,
            int(self._state.get("flight_processed_total", 0) or 0),
        )

        return {
            "transitions_processed": processed,
            "examples_created": examples_created,
            "malformed_lines": malformed,
            "offset": offset,
        }

    def get_lora_eval_history(self, limit: int = 20, adapter_id: str = "") -> List[Dict[str, Any]]:
        max_items = max(1, min(int(limit or 20), 500))
        adapter_filter = str(adapter_id or "").strip()
        if not self.lora_eval_history_path.exists():
            return []

        rows: List[Dict[str, Any]] = []
        try:
            with self.lora_eval_history_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    text = str(line or "").strip()
                    if not text:
                        continue
                    try:
                        row = json.loads(text)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if adapter_filter:
                        candidate = str(row.get("candidate_adapter_id") or "")
                        active = str(row.get("active_adapter_id") or "")
                        if adapter_filter not in {candidate, active}:
                            continue
                    rows.append(row)
        except Exception:
            return []

        if len(rows) <= max_items:
            return rows
        return rows[-max_items:]

    def get_stats(self) -> Dict[str, Any]:
        templates = self._workflows.get("templates", {})
        triggers_payload = self._workflow_triggers if isinstance(self._workflow_triggers, dict) else {}
        now = datetime.now()
        due_details = self._daily_due_details(now=now)
        active_adapter = self.adapter_registry.get_active_adapter()
        quarantine_active = 0
        quarantine_pending_fresh_success = 0
        for raw_entry in templates.values():
            if not isinstance(raw_entry, dict):
                continue
            entry = self._normalize_workflow_entry(raw_entry, str(raw_entry.get("signature") or ""), "")
            quarantine_until = self._parse_datetime(str(entry.get("quarantine_until") or ""))
            if quarantine_until is not None and quarantine_until > now:
                quarantine_active += 1
            if bool(entry.get("quarantine_requires_fresh_success", False)):
                try:
                    success_count = int(entry.get("success_count", 0) or 0)
                    baseline = int(entry.get("quarantine_success_baseline", 0) or 0)
                except Exception:
                    success_count = 0
                    baseline = 0
                if success_count <= baseline:
                    quarantine_pending_fresh_success += 1
        return {
            "daily_hour": self.daily_hour,
            "poll_seconds": self.poll_seconds,
            "startup_delay_seconds": self.startup_delay_seconds,
            "debug_trace_enabled": bool(self.debug_trace_enabled),
            "workflow_trace_enabled": bool(self.workflow_trace_enabled),
            "reward_trace_enabled": bool(self.reward_trace_enabled),
            "running": bool(self._running),
            "task_active": bool(self._task is not None and not self._task.done()),
            "cycle_running": bool(self._cycle_running),
            "state": dict(self._state),
            "diagnostics": dict(self._diag),
            "workflow_templates": len(templates),
            "workflow_trigger_path": str(self.workflow_trigger_path),
            "workflow_triggers": len(list(triggers_payload.get("triggers", []) or [])),
            "workflow_quarantine_minutes": int(self.workflow_quarantine_minutes),
            "workflow_quarantine_tags": list(self.workflow_quarantine_tags),
            "workflow_quarantine_active": quarantine_active,
            "workflow_quarantine_pending_fresh_success": quarantine_pending_fresh_success,
            "reward_model_loaded": self.reward_model is not None,
            "reward_auto_train_enabled": bool(self.reward_auto_train_enabled),
            "workflow_reward_weight": self.workflow_reward_weight,
            "lora_auto_train_enabled": bool(self.lora_auto_train_enabled),
            "lora_min_examples": self.lora_train_min_examples,
            "lora_max_interval_days": self.lora_train_max_interval_days,
            "lora_base_model": self.lora_train_base_model,
            "lora_trainer_backend": self.lora_trainer_backend,
            "lora_trainer_backend_preference": self.lora_trainer_backend_preference,
            "lora_trainer_backend_reason": self.lora_trainer_backend_reason,
            "lora_eval_compare_active": bool(self.lora_eval_compare_active),
            "lora_eval_history_path": str(self.lora_eval_history_path),
            "lora_last_eval_report": dict(self._state.get("lora_last_eval_report") or {}),
            "lora_auto_activate_enabled": bool(self.lora_auto_activate_enabled),
            "active_adapter_id": str(getattr(active_adapter, "adapter_id", "") or ""),
            "example_count": self.example_store.count(),
            "trajectory_stats": self.capture.get_statistics(),
            "daily_due_now": bool(due_details.get("due_now", False)),
            "daily_next_due_at": str(due_details.get("next_due_at", "")),
            "daily_due_reason": str(due_details.get("reason", "")),
            "daily_due_details": due_details,
        }

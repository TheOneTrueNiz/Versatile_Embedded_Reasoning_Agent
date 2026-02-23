#!/usr/bin/env python3
"""
Self-Improvement Runner
=======================

Runs red-team, architect, regression, and memvid export tasks with
basic logging and status tracking for UI diagnostics.
"""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from core.atomic_io import atomic_json_write, safe_json_read
from core.services.red_team_harness import run_red_team
from core.services.specialist_exporter import export_specialist_bundle


@dataclass
class RunStatus:
    running: bool = False
    action: str = ""
    started_at: str = ""
    finished_at: str = ""
    last_error: str = ""
    last_result: Optional[Dict[str, Any]] = None


class SelfImprovementRunner:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.base_dir / "self_improvement_state.json"
        self.log_path = self.base_dir / "self_improvement.log"
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._status = self._load_state()

    def _load_state(self) -> RunStatus:
        data = safe_json_read(self.state_path, default={}) or {}
        return RunStatus(
            running=bool(data.get("running", False)),
            action=str(data.get("action", "")),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            last_error=str(data.get("last_error", "")),
            last_result=data.get("last_result"),
        )

    def _save_state(self) -> None:
        payload = {
            "running": self._status.running,
            "action": self._status.action,
            "started_at": self._status.started_at,
            "finished_at": self._status.finished_at,
            "last_error": self._status.last_error,
            "last_result": self._status.last_result,
        }
        atomic_json_write(self.state_path, payload)

    def _log(self, message: str) -> None:
        timestamp = datetime.now().isoformat()
        line = f"[{timestamp}] {message}\n"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            self._status = self._load_state()
            return {
                "running": self._status.running,
                "action": self._status.action,
                "started_at": self._status.started_at,
                "finished_at": self._status.finished_at,
                "last_error": self._status.last_error,
                "last_result": self._status.last_result,
                "log_path": str(self.log_path),
            }

    def tail_log(self, lines: int = 200) -> str:
        if not self.log_path.exists():
            return ""
        try:
            content = self.log_path.read_text(encoding="utf-8")
        except Exception:
            return ""
        rows = content.splitlines()
        if lines <= 0:
            return content
        return "\n".join(rows[-lines:])

    def start(self, action: str, params: Optional[Dict[str, Any]] = None, vera: Any = None) -> Dict[str, Any]:
        params = params or {}
        with self._lock:
            if self._status.running:
                return {"ok": False, "error": "Self-improvement task already running."}
            self._status = RunStatus(
                running=True,
                action=action,
                started_at=datetime.now().isoformat(),
                finished_at="",
                last_error="",
                last_result=None,
            )
            self._save_state()
            self._log(f"Started action: {action}")

            self._thread = threading.Thread(
                target=self._run_action,
                args=(action, params, vera),
                daemon=True,
            )
            self._thread.start()

        return {"ok": True, "status": self.get_status()}

    def _run_action(self, action: str, params: Dict[str, Any], vera: Any) -> None:
        result: Dict[str, Any] = {}
        error = ""
        try:
            if action == "red_team":
                result = run_red_team(
                    failure_limit=int(params.get("failure_limit", 10)),
                    hard_count=int(params.get("hard_count", 10)),
                    regression_count=int(params.get("regression_count", 20)),
                    use_llm=bool(params.get("use_llm", True)),
                )
                self._log(f"Red-team result: {result}")
            elif action == "architect":
                result = self._run_script(
                    [self._python_bin(), "scripts/vera_architect.py"],
                    env=params.get("env"),
                )
            elif action == "regression":
                cmd = [self._python_bin(), "scripts/vera_regression_runner.py"]
                limit = int(params.get("limit", 0))
                if limit > 0:
                    cmd.extend(["--limit", str(limit)])
                base_url = params.get("base_url")
                if base_url:
                    # Only allow localhost URLs for regression testing
                    from urllib.parse import urlparse as _urlparse
                    parsed = _urlparse(str(base_url))
                    if (parsed.hostname or "").lower() not in ("localhost", "127.0.0.1", "::1"):
                        raise ValueError(f"base_url must be localhost, got: {parsed.hostname}")
                    cmd.extend(["--base-url", str(base_url)])
                result = self._run_script(cmd, env=params.get("env"))
            elif action == "train_reward_model":
                result = self._run_script(
                    [self._python_bin(), "scripts/train_reward_model.py"],
                    env=params.get("env"),
                )
            elif action == "memvid_export":
                result = self._export_memvid(params, vera)
            elif action == "export_specialist":
                result = self._export_specialist(params, vera)
            else:
                raise ValueError(f"Unknown action: {action}")
        except Exception as exc:
            error = str(exc)
            self._log(f"Action failed: {error}")

        with self._lock:
            self._status.running = False
            self._status.finished_at = datetime.now().isoformat()
            self._status.last_error = error
            self._status.last_result = result
            self._save_state()

    def _export_memvid(self, params: Dict[str, Any], vera: Any) -> Dict[str, Any]:
        if not vera or not getattr(vera, "flight_recorder", None):
            raise RuntimeError("Flight recorder unavailable.")
        output_path = Path(params.get("output_path") or "vera_memory/flight_recorder/vera_blackbox.mv2.json")
        limit = params.get("limit")
        limit_val = int(limit) if limit is not None else None
        payload = vera.flight_recorder.export_memvid(output_path=output_path, limit=limit_val)
        self._log(f"Memvid export saved to {output_path}")
        return {"output_path": str(output_path), "entries": len(payload.get("entries", []))}

    def _export_specialist(self, params: Dict[str, Any], vera: Any) -> Dict[str, Any]:
        output_dir = Path(params.get("output_dir") or "vera_memory/flight_recorder/exports")
        genome_path = Path(params.get("genome_path") or "config/vera_genome.json")
        limit = params.get("memvid_limit")
        memvid_limit = int(limit) if limit is not None else None
        result = export_specialist_bundle(
            vera=vera,
            output_dir=output_dir,
            genome_path=genome_path,
            memvid_limit=memvid_limit,
        )
        self._log(f"Specialist bundle exported to {result.get('zip_path')}")
        return result

    def _python_bin(self) -> str:
        return os.getenv("VERA_PYTHON_BIN", "python")

    # Env keys that must never be overridden by API callers
    _ENV_BLOCKLIST = frozenset({
        "PATH", "HOME", "USER", "SHELL", "LOGNAME",
        "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
        "PYTHONPATH", "PYTHONSTARTUP", "PYTHONHOME",
        "VERA_API_KEY", "VERA_LLM_BASE_URL", "VERA_LLM_API_KEY",
        "XAI_API_KEY", "API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "GOOGLE_API_KEY", "GEMINI_API_KEY", "BRAVE_API_KEY",
        "VERA_TRUSTED_PROXIES", "VERA_CORS_ORIGIN",
    })

    def _run_script(self, command: list[str], env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        self._log(f"Running command: {' '.join(command)}")
        merged_env = os.environ.copy()
        if env:
            for k, v in env.items():
                key = str(k).strip()
                if key.upper() in self._ENV_BLOCKLIST:
                    self._log(f"Blocked env override for protected key: {key}")
                    continue
                merged_env[key] = str(v)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=merged_env,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if stdout:
            self._log(stdout)
        if stderr:
            self._log(stderr)
        return {
            "return_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

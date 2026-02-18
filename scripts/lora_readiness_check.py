#!/usr/bin/env python3
"""
LoRA backend readiness dry-run check.

This script is CPU-safe and does not execute LoRA training.
It validates dependency visibility, writable paths, and backend selection state.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _resolve_memory_dir(repo_root: Path, raw: str) -> Path:
    candidate = Path(str(raw or "vera_memory")).expanduser()
    if candidate.is_absolute():
        return candidate
    return (repo_root / candidate).resolve()


def _evaluate_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    reasons: List[str] = []
    checks = payload.get("checks") or {}

    if not bool(checks.get("adapters_dir_writable", False)):
        reasons.append("adapters_dir_not_writable")
    if not bool(checks.get("learning_reports_dir_writable", False)):
        reasons.append("learning_reports_dir_not_writable")

    preference = str(payload.get("trainer_backend_preference") or "").strip().lower()
    hf_available = bool(payload.get("hf_dependencies_available", False))
    if preference in {"hf", "hf_peft"} and not hf_available:
        reasons.append("hf_backend_forced_but_dependencies_missing")

    return {
        "ok": len(reasons) == 0,
        "failure_reasons": reasons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="CPU-safe LoRA backend readiness dry-run")
    parser.add_argument("--memory-dir", default="vera_memory", help="Memory directory path")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / "src"))

    from observability.decision_ledger import DecisionLedger
    from learning.learning_loop_manager import LearningLoopManager

    memory_dir = _resolve_memory_dir(repo_root, args.memory_dir)
    ledger = DecisionLedger(memory_dir=memory_dir)
    manager = LearningLoopManager(memory_dir=memory_dir, ledger=ledger)
    payload = manager.get_lora_backend_readiness()
    payload["memory_dir"] = str(memory_dir)

    status = _evaluate_status(payload)
    payload["ok"] = bool(status["ok"])
    payload["failure_reasons"] = list(status["failure_reasons"])

    if args.compact:
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(json.dumps(payload, indent=2, ensure_ascii=True))

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

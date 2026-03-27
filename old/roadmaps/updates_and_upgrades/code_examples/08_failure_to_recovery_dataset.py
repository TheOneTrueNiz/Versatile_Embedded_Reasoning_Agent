"""Example: build failure->recovery training examples from runtime logs.

Integration targets:
- src/core/services/flight_recorder.py
- src/learning/learning_loop_manager.py
- src/core/runtime/tool_orchestrator.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List


@dataclass
class RecoveryExample:
    task_signature: str
    failed_tool: str
    failure_reason: str
    recovery_tool: str
    recovery_outcome: str
    confidence: float

    def to_json(self) -> Dict[str, Any]:
        return {
            "type": "failure_recovery_example",
            "task_signature": self.task_signature,
            "failed_tool": self.failed_tool,
            "failure_reason": self.failure_reason,
            "recovery_tool": self.recovery_tool,
            "recovery_outcome": self.recovery_outcome,
            "confidence": self.confidence,
        }


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(payload, dict):
                yield payload


def _task_signature(row: Dict[str, Any]) -> str:
    task = str(row.get("task") or row.get("input") or "").strip().lower()
    return task[:200]


def extract_examples(events_path: Path, action_events_path: Path) -> List[RecoveryExample]:
    failures: Dict[str, Dict[str, Any]] = {}
    examples: List[RecoveryExample] = []

    for row in _iter_jsonl(events_path):
        if row.get("type") != "tool_call":
            continue
        if bool(row.get("success", False)):
            continue
        key = _task_signature(row)
        failures[key] = {
            "failed_tool": str(row.get("tool_name") or ""),
            "failure_reason": str(row.get("result") or ""),
        }

    for row in _iter_jsonl(action_events_path):
        key = _task_signature(row)
        prior = failures.get(key)
        if not prior:
            continue
        outcome = str(row.get("status") or "")
        if outcome not in {"completed", "running"}:
            continue
        recovery_tool = str(row.get("workflow_id") or row.get("tool_name") or "")
        confidence = 0.9 if outcome == "completed" else 0.6
        examples.append(
            RecoveryExample(
                task_signature=key,
                failed_tool=prior["failed_tool"],
                failure_reason=prior["failure_reason"][:500],
                recovery_tool=recovery_tool,
                recovery_outcome=outcome,
                confidence=confidence,
            )
        )
    return examples


def write_examples(examples: List[RecoveryExample], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with out_path.open("a", encoding="utf-8") as handle:
        for row in examples:
            handle.write(json.dumps(row.to_json(), ensure_ascii=True) + "\n")
            written += 1
    return written


if __name__ == "__main__":
    events = Path("tmp/followthrough_events.jsonl")
    action_events = Path("tmp/followthrough_action_events.jsonl")
    out = Path("vera_memory/training_examples/failure_recovery_examples.jsonl")

    examples = extract_examples(events, action_events)
    count = write_examples(examples, out)
    print(f"Wrote {count} failure-recovery examples to {out}")

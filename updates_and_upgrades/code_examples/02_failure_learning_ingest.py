"""Example: derive failure-learning examples from flight recorder transitions.

Integration targets:
- src/core/services/flight_recorder.py
- src/learning/learning_loop_manager.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class FailureExample:
    task: str
    failed_tool: str
    failure_class: str
    fallback_tool: str
    final_outcome: str
    transcript: str

    def to_json(self) -> Dict[str, Any]:
        return {
            "type": "failure_learning",
            "task": self.task,
            "failed_tool": self.failed_tool,
            "failure_class": self.failure_class,
            "fallback_tool": self.fallback_tool,
            "final_outcome": self.final_outcome,
            "transcript": self.transcript,
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
                row = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(row, dict):
                yield row


def _classify_failure(tool_result: str) -> str:
    lowered = tool_result.lower()
    if "timed out" in lowered:
        return "tool_timeout"
    if "auth" in lowered or "unauthorized" in lowered:
        return "tool_auth_required"
    if "rate limit" in lowered:
        return "tool_rate_limited"
    return "tool_execution_error"


def extract_failure_examples(transitions_path: Path) -> List[FailureExample]:
    examples: List[FailureExample] = []
    for row in _iter_jsonl(transitions_path):
        if row.get("type") != "tool_call":
            continue
        success = bool(row.get("success", False))
        if success:
            continue

        failed_tool = str(row.get("tool_name") or "")
        result_text = str(row.get("result") or "")
        failure_class = _classify_failure(result_text)
        fallback_tool = str(row.get("fallback_tool") or "")
        final_outcome = str(row.get("final_outcome") or "failed")
        task = str(row.get("task") or row.get("input") or "")
        transcript = str(row.get("trace") or result_text)[:1200]

        examples.append(
            FailureExample(
                task=task,
                failed_tool=failed_tool,
                failure_class=failure_class,
                fallback_tool=fallback_tool,
                final_outcome=final_outcome,
                transcript=transcript,
            )
        )
    return examples


def write_failure_examples(examples: List[FailureExample], out_path: Path) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("a", encoding="utf-8") as handle:
        for ex in examples:
            handle.write(json.dumps(ex.to_json(), ensure_ascii=True) + "\n")
            count += 1
    return count


if __name__ == "__main__":
    source = Path("vera_memory/flight_recorder/transitions.jsonl")
    target = Path("vera_memory/training_examples/failure_examples.jsonl")
    rows = extract_failure_examples(source)
    written = write_failure_examples(rows, target)
    print(f"Extracted {written} failure examples")

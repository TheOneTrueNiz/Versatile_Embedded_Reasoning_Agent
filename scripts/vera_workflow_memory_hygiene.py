#!/usr/bin/env python3
"""Conservative workflow-template hygiene pass.

Quarantines clearly problematic workflow templates in `vera_memory/workflow_templates.json`
without deleting anything.

Default behavior is dry-run. Use `--apply` to persist changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

ACKNOWLEDGEMENT_TASKS = {
    "yes",
    "yes please",
    "y",
    "ok",
    "okay",
    "sure",
    "yep",
    "yup",
    "no",
    "n",
    "no thanks",
    "cancel",
    "thanks",
    "thank you",
    "great",
    "perfect",
    "sounds good",
    "looks good",
    "cool",
    "done",
}


@dataclass
class Candidate:
    signature: str
    reason: str
    details: str


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _default_max_forced_steps() -> int:
    raw_forced = str(os.getenv("VERA_WORKFLOW_MAX_FORCED_STEPS", "")).strip()
    if raw_forced:
        try:
            return max(1, int(raw_forced))
        except Exception:
            pass

    raw_rounds = str(os.getenv("VERA_MAX_TOOL_ROUNDS", "")).strip()
    if raw_rounds:
        try:
            return max(1, int(raw_rounds) - 1)
        except Exception:
            pass

    # LLMBridge default: max_tool_rounds=5 -> budget 4.
    return 4


def _detect_media_intent(sample_task: str) -> str:
    text = _normalize_text(sample_task)
    if not text:
        return ""

    if (
        "video generation" in text
        or bool(re.search(r"\b(generate|create|make|render|produce)\s+(?:an?\s+|another\s+)?video\b", text))
    ):
        return "video"

    if (
        "image generation" in text
        or bool(re.search(r"\b(generate|create|make|render|design)\s+(?:an?\s+|another\s+)?image\b", text))
    ):
        return "image"

    return ""


def _has_failure_evidence(entry: Dict[str, Any]) -> bool:
    failure_count = _safe_int(entry.get("failure_count"), 0)
    replay_failure_count = _safe_int(entry.get("replay_failure_count"), 0)
    consecutive_failures = _safe_int(entry.get("consecutive_failures"), 0)
    if (failure_count + replay_failure_count + consecutive_failures) > 0:
        return True

    error_blob = " ".join(
        [
            str(entry.get("last_error") or ""),
            str(entry.get("last_replay_error") or ""),
            str(entry.get("quarantine_reason") or ""),
        ]
    ).lower()
    return any(
        token in error_blob
        for token in (
            "tool call limit reached",
            "cached_chain_not_completed",
            "confirmation_required",
            "chain_mismatch",
            "workflow_failed",
        )
    )


def _evaluate_entry(
    signature: str,
    entry: Dict[str, Any],
    max_forced_steps: int,
) -> Candidate | None:
    chain = [str(name).strip() for name in (entry.get("tool_chain") or []) if str(name).strip()]
    if len(chain) < 2:
        return None

    sample_task = str(entry.get("sample_task") or "")
    sample_norm = _normalize_text(sample_task)
    failure_evidence = _has_failure_evidence(entry)

    if len(chain) > max_forced_steps:
        return Candidate(
            signature=signature,
            reason=f"chain_exceeds_budget:{len(chain)}>{max_forced_steps}",
            details=f"chain={chain}",
        )

    if sample_norm in ACKNOWLEDGEMENT_TASKS and failure_evidence:
        return Candidate(
            signature=signature,
            reason="acknowledgement_chain",
            details=f"sample_task={sample_task!r}; chain={chain}",
        )

    media_intent = _detect_media_intent(sample_task)
    has_native_media_tool = "generate_video" in chain or "generate_image" in chain
    if media_intent and not has_native_media_tool and failure_evidence:
        return Candidate(
            signature=signature,
            reason=f"media_{media_intent}_missing_native_tool",
            details=f"sample_task={sample_task!r}; chain={chain}",
        )

    return None


def _load_templates(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workflow templates file is not a JSON object")
    if not isinstance(payload.get("templates"), dict):
        raise ValueError("workflow templates file missing templates object")
    return payload


def _apply_quarantine(entry: Dict[str, Any], reason: str, quarantine_minutes: int, now: datetime) -> bool:
    reason_value = f"manual_hygiene:{reason}"
    existing_reason = str(entry.get("quarantine_reason") or "")
    existing_requires_fresh = bool(entry.get("quarantine_requires_fresh_success", False))
    if existing_reason == reason_value and existing_requires_fresh:
        return False

    until = now + timedelta(minutes=max(15, int(quarantine_minutes)))
    entry["quarantine_count"] = _safe_int(entry.get("quarantine_count"), 0) + 1
    entry["quarantine_until"] = until.isoformat()
    entry["quarantine_reason"] = reason_value
    entry["quarantine_last_at"] = now.isoformat()
    entry["quarantine_last_failure_tag"] = "manual_hygiene"
    entry["quarantine_requires_fresh_success"] = True
    entry["quarantine_success_baseline"] = _safe_int(entry.get("success_count"), 0)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Conservative workflow memory hygiene pass")
    parser.add_argument(
        "--workflow-path",
        default="vera_memory/workflow_templates.json",
        help="Path to workflow templates JSON",
    )
    parser.add_argument(
        "--max-forced-steps",
        type=int,
        default=_default_max_forced_steps(),
        help="Maximum forced steps workflow replay can support (default derived from env/runtime)",
    )
    parser.add_argument(
        "--quarantine-minutes",
        type=int,
        default=max(15, _safe_int(os.getenv("VERA_WORKFLOW_QUARANTINE_MINUTES"), 180)),
        help="Quarantine window minutes to stamp for manual hygiene actions",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes (default is dry-run)",
    )
    args = parser.parse_args()

    workflow_path = Path(args.workflow_path)
    if not workflow_path.exists():
        print(f"ERROR: workflow file not found: {workflow_path}")
        return 2

    payload = _load_templates(workflow_path)
    templates: Dict[str, Dict[str, Any]] = payload["templates"]

    candidates: List[Tuple[Candidate, Dict[str, Any]]] = []
    for signature, raw_entry in templates.items():
        if not isinstance(raw_entry, dict):
            continue
        candidate = _evaluate_entry(signature, raw_entry, max_forced_steps=max(1, int(args.max_forced_steps)))
        if candidate is not None:
            candidates.append((candidate, raw_entry))

    print(f"Workflow hygiene scan: templates={len(templates)} candidates={len(candidates)}")
    print(f"  max_forced_steps={max(1, int(args.max_forced_steps))}")
    print(f"  mode={'APPLY' if args.apply else 'DRY_RUN'}")

    if not candidates:
        print("No candidates found.")
        return 0

    for idx, (candidate, _entry) in enumerate(candidates, start=1):
        print(f"{idx}. {candidate.signature} -> {candidate.reason}")
        print(f"   {candidate.details}")

    if not args.apply:
        print("Dry-run complete. Re-run with --apply to persist quarantines.")
        return 0

    now = datetime.now()
    changed = 0
    for candidate, entry in candidates:
        did_change = _apply_quarantine(
            entry,
            reason=candidate.reason,
            quarantine_minutes=max(15, int(args.quarantine_minutes)),
            now=now,
        )
        if did_change:
            changed += 1

    if changed <= 0:
        print("No entries changed (already quarantined with matching manual_hygiene reason).")
        return 0

    backup_path = workflow_path.with_suffix(workflow_path.suffix + f".bak.{now.strftime('%Y%m%dT%H%M%S')}")
    shutil.copy2(workflow_path, backup_path)

    workflow_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Applied quarantines: {changed}")
    print(f"Backup written: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

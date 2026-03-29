#!/usr/bin/env python3
"""
Architect pipeline: propose genome patches from failures and stage candidates.
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

project_root = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(project_root / "src"))

from observability.self_improvement_budget import (
    SelfImprovementBudget,
    estimate_cost,
    estimate_tokens,
)
from core.runtime.genome_config import (
    DEFAULT_GENOME_PATH,
    apply_genome_patch,
    load_genome_config,
)


def _read_ndjson(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def _summarize_failure(entry: Dict[str, Any]) -> str:
    action = entry.get("action", {})
    result = entry.get("result", {})
    reason = entry.get("air_reason", "")
    summary = {
        "action": action,
        "result": result,
        "air_reason": reason,
        "timestamp": entry.get("timestamp", ""),
    }
    return json.dumps(summary, ensure_ascii=True)


def _build_architect_prompts(config_json: str, failure_summary: str) -> Tuple[str, str]:
    system_prompt = (
        "You are the Architect for VERA. "
        "Given a genome config JSON and a failure summary, "
        "output a JSON PATCH array (RFC6902) to fix the issue. "
        "Return ONLY the JSON array; no markdown."
    )
    user_prompt = (
        "### CURRENT GENOME CONFIG\n"
        f"{config_json}\n\n"
        "### FAILURE SUMMARY\n"
        f"{failure_summary}\n\n"
        "### INSTRUCTION\n"
        "Propose a minimal JSON Patch that addresses the failure without deleting required keys."
    )
    return system_prompt, user_prompt


def _call_architect(
    api_key: str,
    base_url: str,
    model: str,
    config_json: str,
    failure_summary: str,
    max_tokens: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    system_prompt, user_prompt = _build_architect_prompts(config_json, failure_summary)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    with httpx.Client(base_url=base_url, timeout=90.0) as client:
        response = client.post("/chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    patch_ops = json.loads(content)
    if not isinstance(patch_ops, list):
        raise ValueError("Architect output is not a JSON array")
    return patch_ops, data.get("usage", {})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transitions", type=Path, default=Path("vera_memory/flight_recorder/transitions.ndjson"))
    parser.add_argument("--genome", type=Path, default=DEFAULT_GENOME_PATH)
    parser.add_argument("--failure-limit", type=int, default=3)
    parser.add_argument("--base-url", type=str, default=os.getenv("XAI_API_BASE", "https://api.x.ai/v1"))
    parser.add_argument("--model", type=str, default=os.getenv("XAI_MODEL", "grok-4.20-experimental-beta-0304-reasoning"))
    parser.add_argument("--out-dir", type=Path, default=Path("vera_memory/flight_recorder/patch_candidates"))
    parser.add_argument("--candidate-dir", type=Path, default=Path("config/candidates"))
    args = parser.parse_args()

    max_tokens = int(os.getenv("VERA_ARCHITECT_MAX_TOKENS", "800"))
    budget = SelfImprovementBudget()

    api_key = os.getenv("XAI_API_KEY") or os.getenv("API_KEY") or ""
    if not api_key:
        print("XAI_API_KEY is required to run the architect.")
        return 1

    transitions = _read_ndjson(args.transitions)
    failures = [t for t in transitions if t.get("air_score", 0) < 0]
    failures.sort(key=lambda t: t.get("timestamp", ""), reverse=True)
    failures = failures[: args.failure_limit]
    if not failures:
        print("No failures found.")
        return 0

    config, validation = load_genome_config(args.genome)
    if not validation.valid:
        print("Genome config invalid:")
        for err in validation.errors:
            print(f"- {err}")
        return 1

    config_json = json.dumps(config, ensure_ascii=True, indent=2)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.candidate_dir.mkdir(parents=True, exist_ok=True)

    for idx, failure in enumerate(failures, start=1):
        failure_summary = _summarize_failure(failure)
        system_prompt, user_prompt = _build_architect_prompts(config_json, failure_summary)
        estimated_prompt_tokens = estimate_tokens(system_prompt + "\n" + user_prompt)
        estimated_total = estimated_prompt_tokens + max_tokens
        allowed, reason = budget.check(
            category="architect",
            estimated_tokens=estimated_total,
            estimated_cost=estimate_cost(estimated_prompt_tokens, max_tokens),
            calls=1,
        )
        if not allowed:
            print(f"Architect budget blocked: {reason}")
            break
        try:
            patch_ops, usage = _call_architect(
                api_key=api_key,
                base_url=args.base_url,
                model=args.model,
                config_json=config_json,
                failure_summary=failure_summary,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            print(f"Architect failed for failure #{idx}: {exc}")
            continue

        tokens_in = int(usage.get("prompt_tokens", estimated_prompt_tokens) or 0)
        tokens_out = int(usage.get("completion_tokens", max_tokens) or 0)
        budget.record_usage(
            category="architect",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=estimate_cost(tokens_in, tokens_out),
            calls=1,
        )

        patch_path = args.out_dir / f"patch_{now}_{idx}.json"
        patch_path.write_text(json.dumps(patch_ops, ensure_ascii=True, indent=2), encoding="utf-8")

        patched, patch_validation = apply_genome_patch(config, patch_ops)
        if not patch_validation.valid:
            print(f"Patch invalid for failure #{idx}:")
            for err in patch_validation.errors:
                print(f"- {err}")
            continue

        candidate_path = args.candidate_dir / f"genome_{now}_{idx}.json"
        candidate_path.write_text(json.dumps(patched, ensure_ascii=True, indent=2), encoding="utf-8")
        print(f"Staged candidate: {candidate_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

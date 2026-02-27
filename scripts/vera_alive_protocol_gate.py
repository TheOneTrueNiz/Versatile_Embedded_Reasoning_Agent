#!/usr/bin/env python3
"""Generate a red/yellow/green status report for the VERA Alive Protocol."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx


@dataclass
class GateItem:
    key: str
    status: str
    summary: str
    evidence: Dict[str, Any]
    next_action: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _has(path: Path, pattern: str) -> bool:
    text = _read_text(path)
    if not text:
        return False
    return re.search(pattern, text, flags=re.MULTILINE) is not None


def _safe_get(client: httpx.Client, base_url: str, endpoint: str) -> Tuple[int, Any]:
    url = f"{base_url}{endpoint}"
    try:
        r = client.get(url)
        if "application/json" in (r.headers.get("content-type") or ""):
            return int(r.status_code), r.json()
        try:
            return int(r.status_code), r.json()
        except Exception:
            return int(r.status_code), r.text
    except Exception as exc:
        return 0, {"error": str(exc)}


def _status_rank(status: str) -> int:
    return {"green": 0, "yellow": 1, "red": 2}.get(status, 3)


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _alive24_reachout_count(proactive_summary: Dict[str, Any]) -> int:
    outcomes = proactive_summary.get("log_run_outcomes") or []
    reached_out_in_outcomes = 0
    if isinstance(outcomes, list):
        reached_out_in_outcomes = sum(
            1
            for row in outcomes
            if isinstance(row, dict) and str(row.get("outcome") or "").strip().lower() == "reached_out"
        )
    recent_thought_runs = proactive_summary.get("reachout_runs_from_recent_thoughts") or []
    log_reached_out_runs = proactive_summary.get("log_reached_out_runs") or []
    reached_out_with_fcm = _to_int(proactive_summary.get("reached_out_with_fcm_count"), 0)
    return max(
        reached_out_in_outcomes,
        len(recent_thought_runs) if isinstance(recent_thought_runs, list) else 0,
        len(log_reached_out_runs) if isinstance(log_reached_out_runs, list) else 0,
        reached_out_with_fcm,
    )


def _latest_alive24_evidence(root: Path) -> Dict[str, Any]:
    soak_dir = root / "tmp" / "soak"
    if not soak_dir.exists():
        return {"found": False, "reason": "tmp/soak missing"}

    checks_files = list(soak_dir.glob("alive24_*_checks_summary.json"))
    if not checks_files:
        return {"found": False, "reason": "no alive24 checks summary found"}

    latest_checks = max(checks_files, key=lambda p: p.stat().st_mtime)
    run_prefix = latest_checks.name.replace("_checks_summary.json", "")
    proactive_path = soak_dir / f"{run_prefix}_proactive_summary.json"

    checks_summary = _safe_read_json(latest_checks)
    proactive_summary = _safe_read_json(proactive_path) if proactive_path.exists() else {}

    duration_hours = _to_float(checks_summary.get("duration_hours"), 0.0)
    cycles = _to_int(checks_summary.get("cycles"), 0)
    failures = _to_int(checks_summary.get("failures"), 0)
    passes = _to_int(checks_summary.get("passes"), 0)
    proactive_ok = bool(proactive_summary.get("ok")) if proactive_summary else False
    reachout_events = _alive24_reachout_count(proactive_summary) if proactive_summary else 0

    min_duration = _to_float(os.getenv("VERA_ALIVE24_MIN_DURATION_HOURS", "23.5"), 23.5)
    min_reachouts = _to_int(os.getenv("VERA_ALIVE24_MIN_REACHOUT_EVENTS", "1"), 1)

    meets_duration = duration_hours >= min_duration
    meets_reachout = reachout_events >= min_reachouts
    meets_gate = bool(checks_summary) and proactive_ok and meets_duration and meets_reachout

    return {
        "found": True,
        "run_prefix": run_prefix,
        "checks_summary_path": str(latest_checks),
        "proactive_summary_path": str(proactive_path) if proactive_path.exists() else "",
        "checks_summary": checks_summary,
        "proactive_summary": proactive_summary,
        "started_at_utc": checks_summary.get("started_at_utc") or proactive_summary.get("started_at_utc"),
        "finished_at_utc": checks_summary.get("finished_at_utc") or proactive_summary.get("ended_at_utc"),
        "duration_hours": duration_hours,
        "cycles": cycles,
        "passes": passes,
        "failures": failures,
        "proactive_ok": proactive_ok,
        "reachout_events": reachout_events,
        "min_duration_hours": min_duration,
        "min_reachout_events": min_reachouts,
        "meets_duration": meets_duration,
        "meets_reachout": meets_reachout,
        "meets_gate": meets_gate,
    }


def build_report(base_url: str, root: Path) -> Dict[str, Any]:
    src = root / "src"
    vera_py = src / "core" / "runtime" / "vera.py"
    prompts_py = src / "core" / "runtime" / "prompts.py"
    innerlife_py = src / "planning" / "inner_life_engine.py"
    llm_bridge_py = src / "orchestration" / "llm_bridge.py"
    learning_py = src / "learning" / "learning_loop_manager.py"
    proactive_py = src / "core" / "runtime" / "proactive_manager.py"
    server_py = src / "api" / "server.py"
    run_full_sh = root / "scripts" / "run_vera_full.sh"

    with httpx.Client(timeout=20.0) as client:
        health_code, health = _safe_get(client, base_url, "/api/health")
        inner_code, inner = _safe_get(client, base_url, "/api/innerlife/status")
        learning_code, learning = _safe_get(client, base_url, "/api/learning/status")
        lora_code, lora = _safe_get(client, base_url, "/api/learning/lora-readiness")
        links_code, links = _safe_get(client, base_url, "/api/session/links")
        link_map_code, link_map = _safe_get(client, base_url, "/api/session/link-map")
        partner_code, partner = _safe_get(client, base_url, "/api/preferences/partner-model")
        core_id_code, core_id = _safe_get(client, base_url, "/api/preferences/core-identity")
        memory_code, memory = _safe_get(client, base_url, "/api/memory/stats")
        channels_code, channels = _safe_get(client, base_url, "/api/channels/status")

    items: List[GateItem] = []

    # 1) Temporal continuity
    temporal_ok = (
        _has(vera_py, r"def _build_temporal_context")
        and _has(vera_py, r"I last heard from my partner")
        and _has(prompts_py, r"My last thought was")
    )
    items.append(
        GateItem(
            key="temporal_continuity",
            status="green" if temporal_ok else "red",
            summary="Time-gap and reflection carryover are injected into prompt context."
            if temporal_ok
            else "Temporal continuity wiring missing.",
            evidence={
                "code_checks": {
                    "build_temporal_context": _has(vera_py, r"def _build_temporal_context"),
                    "continuity_line": _has(vera_py, r"I last heard from my partner"),
                    "last_thought_prompt": _has(prompts_py, r"My last thought was"),
                },
            },
            next_action="None." if temporal_ok else "Wire temporal context into prompt/session metadata.",
        )
    )

    # 2) Emotional carryover
    emotional_ok = (
        _has(vera_py, r"def _refresh_emotional_state")
        and _has(vera_py, r"Emotional carryover")
        and _has(innerlife_py, r"def _mood_behavior_guidance")
    )
    items.append(
        GateItem(
            key="emotional_carryover",
            status="green" if emotional_ok else "red",
            summary="Mood/sentiment are carried into behavior guidance."
            if emotional_ok
            else "Mood carryover wiring missing.",
            evidence={
                "code_checks": {
                    "refresh_emotional_state": _has(vera_py, r"def _refresh_emotional_state"),
                    "prompt_emotional_carryover": _has(vera_py, r"Emotional carryover"),
                    "innerlife_mood_guidance": _has(innerlife_py, r"def _mood_behavior_guidance"),
                },
                "runtime_mood": (inner.get("stats") or {}).get("current_mood") if isinstance(inner, dict) else None,
            },
            next_action="None." if emotional_ok else "Wire sentiment->mood->behavior guidance in runtime and reflections.",
        )
    )

    # 3) Self-narrative reasoning
    narrative_ok = (
        _has(innerlife_py, r"def _generate_self_narrative")
        and _has(innerlife_py, r"explaining why these personality traits shifted")
    )
    self_narrative_entries = 0
    if isinstance(inner, dict):
        stats = inner.get("stats") or {}
        if isinstance(stats, dict):
            self_narrative_entries = len(stats.get("self_narrative") or [])
    items.append(
        GateItem(
            key="self_narrative_reasoning",
            status="green" if (narrative_ok and self_narrative_entries >= 1) else "yellow",
            summary="Trait updates include explicit narrative reasoning."
            if narrative_ok
            else "Self-narrative generator missing.",
            evidence={
                "code_checks": {
                    "generate_self_narrative": _has(innerlife_py, r"def _generate_self_narrative"),
                    "why_prompt": _has(innerlife_py, r"explaining why these personality traits shifted"),
                },
                "runtime_self_narrative_entries": self_narrative_entries,
            },
            next_action="No action." if (narrative_ok and self_narrative_entries >= 1) else "Run more reflection cycles and verify narrative entries append.",
        )
    )

    # 4) Daily trace extraction
    learning_running = False
    learning_stats = {}
    if isinstance(learning, dict):
        learning_stats = learning.get("stats") or {}
        if isinstance(learning_stats, dict):
            learning_running = bool(learning_stats.get("running"))
    trace_ok = (
        _has(learning_py, r"VERA_TRACE_EXTRACTION_HOUR")
        and _has(learning_py, r"extract_recent_successes")
        and learning_running
    )
    items.append(
        GateItem(
            key="daily_trace_extraction",
            status="green" if trace_ok else "yellow",
            summary="Daily trace extraction scheduler is present and running."
            if trace_ok
            else "Trace extraction exists but runtime loop is not confirmed running.",
            evidence={
                "code_checks": {
                    "trace_hour_env": _has(learning_py, r"VERA_TRACE_EXTRACTION_HOUR"),
                    "extract_recent_successes_call": _has(learning_py, r"extract_recent_successes"),
                },
                "runtime_running": learning_running,
                "daily_hour": learning_stats.get("daily_hour") if isinstance(learning_stats, dict) else None,
                "last_trace_date": (learning_stats.get("state") or {}).get("last_trace_date") if isinstance(learning_stats, dict) else None,
            },
            next_action="Ensure loop starts at boot and verify daily logs." if not trace_ok else "No action.",
        )
    )

    # 5) Workflow memory
    workflow_ok = _has(learning_py, r"def get_workflow_plan") and _has(learning_py, r"def record_workflow_replay_result")
    workflow_diag = {}
    if isinstance(learning_stats, dict):
        workflow_diag = learning_stats.get("diagnostics") or {}
    items.append(
        GateItem(
            key="workflow_memory",
            status="green" if workflow_ok else "red",
            summary="Workflow replay, quarantine, and plan lookup are wired."
            if workflow_ok
            else "Workflow memory wiring is missing.",
            evidence={
                "code_checks": {
                    "get_workflow_plan": _has(learning_py, r"def get_workflow_plan"),
                    "record_workflow_replay_result": _has(learning_py, r"def record_workflow_replay_result"),
                    "llm_bridge_workflow_plan": _has(llm_bridge_py, r"_resolve_workflow_runtime_plan"),
                },
                "runtime_diag": {
                    "workflow_outcome_calls": workflow_diag.get("workflow_outcome_calls"),
                    "workflow_outcome_saved": workflow_diag.get("workflow_outcome_saved"),
                    "workflow_replay_calls": workflow_diag.get("workflow_replay_calls"),
                    "workflow_replay_saved": workflow_diag.get("workflow_replay_saved"),
                },
            },
            next_action="No action." if workflow_ok else "Wire workflow plan lookup + replay result recording.",
        )
    )

    # 6) Flight recorder -> distillation
    distill_ok = _has(learning_py, r"def ingest_flight_recorder_transitions") and _has(learning_py, r"flight_ingest")
    items.append(
        GateItem(
            key="flight_recorder_distillation",
            status="green" if distill_ok else "red",
            summary="Flight recorder transitions ingest into distillation pipeline."
            if distill_ok
            else "Flight recorder ingestion wiring is missing.",
            evidence={
                "code_checks": {
                    "ingest_flight_recorder_transitions": _has(learning_py, r"def ingest_flight_recorder_transitions"),
                    "run_cycle_flight_ingest": _has(learning_py, r"flight_ingest"),
                }
            },
            next_action="No action." if distill_ok else "Wire flight recorder ingestion into run cycle.",
        )
    )

    # 7) Context summarization @50+
    summarize_ok = (
        _has(vera_py, r"def _maybe_summarize_conversation_history")
        and _has(vera_py, r"VERA_CONTEXT_SUMMARY_TRIGGER_MESSAGES\", \"50")
        and _has(vera_py, r"recursive\.summarize")
    )
    items.append(
        GateItem(
            key="context_summarization_50_plus",
            status="green" if summarize_ok else "yellow",
            summary="Conversation history compaction and recursive summarization trigger at 50+ messages."
            if summarize_ok
            else "History summarization trigger is not clearly wired to 50+ threshold.",
            evidence={
                "code_checks": {
                    "summary_function": _has(vera_py, r"def _maybe_summarize_conversation_history"),
                    "trigger_default_50": _has(vera_py, r"VERA_CONTEXT_SUMMARY_TRIGGER_MESSAGES\", \"50"),
                    "recursive_summarize_call": _has(vera_py, r"recursive\.summarize"),
                }
            },
            next_action="No action." if summarize_ok else "Ensure 50+ trigger and recursive summarizer path are active.",
        )
    )

    # 8) Partner model extraction
    partner_ok = (
        _has(innerlife_py, r"Hard constraint: `partner_learning_answer`")
        and _has(innerlife_py, r"def _apply_partner_model_updates")
        and isinstance(partner, dict)
        and int(partner.get("high_confidence_fact_count", 0) or 0) > 0
    )
    items.append(
        GateItem(
            key="partner_model_extraction",
            status="green" if partner_ok else "yellow",
            summary="Partner-specific learning is extracted and persisted."
            if partner_ok
            else "Partner model extraction exists but runtime evidence is weak.",
            evidence={
                "code_checks": {
                    "hard_constraint_prompt": _has(innerlife_py, r"Hard constraint: `partner_learning_answer`"),
                    "apply_partner_updates": _has(innerlife_py, r"def _apply_partner_model_updates"),
                },
                "runtime_partner": partner if isinstance(partner, dict) else {"status": partner_code},
            },
            next_action="Run reflection cycles and inspect partner-model endpoint for fact growth." if not partner_ok else "No action.",
        )
    )

    # 9) Preference promotion -> identity
    identity_ok = (
        _has(innerlife_py, r"def _promote_partner_model_preferences")
        and _has(root / "src" / "context" / "preferences.py", r"def refresh_core_identity_promotions")
        and isinstance(core_id, dict)
        and int(core_id.get("active_count", 0) or 0) > 0
    )
    items.append(
        GateItem(
            key="preference_promotion_identity",
            status="green" if identity_ok else "yellow",
            summary="High-confidence preferences are promoted into core identity prompt."
            if identity_ok
            else "Preference promotion path exists but active promotions are not confirmed.",
            evidence={
                "code_checks": {
                    "promote_partner_model_preferences": _has(innerlife_py, r"def _promote_partner_model_preferences"),
                    "refresh_core_identity_promotions": _has(root / "src" / "context" / "preferences.py", r"def refresh_core_identity_promotions"),
                },
                "runtime_core_identity": core_id if isinstance(core_id, dict) else {"status": core_id_code},
            },
            next_action="No action." if identity_ok else "Run promotion refresh and verify active commitments.",
        )
    )

    # 10) Cross-channel continuity
    active_channels = []
    if isinstance(channels, dict):
        active_channels = [row.get("id") for row in (channels.get("active") or []) if isinstance(row, dict)]
    links_count = 0
    if isinstance(links, dict):
        links_count = int(links.get("count", 0) or 0)
    link_default_seed = _has(run_full_sh, r"VERA_DEFAULT_SESSION_LINK_ID")
    if len(active_channels) <= 1:
        link_status = "yellow"
        link_summary = "Session linking is wired, but only one active channel is currently online."
        link_next = "Enable another channel (e.g., Discord) and verify handoff continuity."
    elif links_count > 0:
        link_status = "green"
        link_summary = "Cross-channel session link aliases are active."
        link_next = "No action."
    else:
        link_status = "yellow"
        link_summary = "Cross-channel infrastructure exists but no active link aliases are recorded."
        link_next = "Create/verify link aliases via /api/session/link."
    items.append(
        GateItem(
            key="cross_channel_continuity",
            status=link_status,
            summary=link_summary,
            evidence={
                "code_checks": {
                    "session_link_extract": _has(vera_py, r"def _extract_inbound_session_link_id"),
                    "session_link_routes": _has(server_py, r"/api/session/links"),
                    "launcher_default_session_link_seed": link_default_seed,
                },
                "runtime": {
                    "active_channels": active_channels,
                    "session_links_count": links_count,
                    "link_map": link_map if isinstance(link_map, dict) else {"status": link_map_code},
                },
            },
            next_action=link_next,
        )
    )

    # 11) Proactive initiative
    proactive_payload = {}
    if isinstance(inner, dict):
        proactive_payload = inner.get("proactive") or {}
    proactive_defaults_ok = (
        _has(proactive_py, r'VERA_PROACTIVE_EXECUTION\", \"1')
        and _has(proactive_py, r'VERA_CALENDAR_PROACTIVE\", \"1')
        and bool(proactive_payload.get("proactive_execution_enabled", False))
    )
    items.append(
        GateItem(
            key="initiative_proactive",
            status="green" if proactive_defaults_ok else "yellow",
            summary="Autonomy cadence and proactive execution are enabled by default with operator opt-out."
            if proactive_defaults_ok
            else "Initiative logic exists but default-enabled runtime state is not fully confirmed.",
            evidence={
                "code_checks": {
                    "calendar_default_on": _has(proactive_py, r'VERA_CALENDAR_PROACTIVE\", \"1'),
                    "sentinel_default_on": _has(proactive_py, r'VERA_PROACTIVE_EXECUTION\", \"1'),
                },
                "runtime_proactive": proactive_payload,
            },
            next_action="Run short soak (2-4h) and inspect initiative quality/noise." if not proactive_defaults_ok else "No action.",
        )
    )

    # 12) Periodic LoRA retraining cadence
    lora_backend = ""
    if isinstance(lora, dict):
        lora_backend = str(lora.get("trainer_backend_selected") or "")
    lora_code_ok = _has(learning_py, r"VERA_LORA_AUTO_TRAIN") and _has(learning_py, r"def _lora_train_due")
    if lora_code_ok and lora_backend not in {"", "mock"}:
        lora_status = "green"
        lora_summary = "LoRA cadence is wired and a non-mock trainer backend is available."
        lora_next = "No action."
    elif lora_code_ok:
        lora_status = "yellow"
        lora_summary = "LoRA cadence is wired, but current machine is using mock backend."
        lora_next = "Install HF deps + CUDA-capable host for production LoRA training."
    else:
        lora_status = "red"
        lora_summary = "LoRA cadence wiring is missing."
        lora_next = "Wire env-driven LoRA cadence checks and adapter training call."
    items.append(
        GateItem(
            key="lora_cadence",
            status=lora_status,
            summary=lora_summary,
            evidence={
                "code_checks": {
                    "lora_auto_train_env": _has(learning_py, r"VERA_LORA_AUTO_TRAIN"),
                    "lora_due_fn": _has(learning_py, r"def _lora_train_due"),
                },
                "runtime_lora": lora if isinstance(lora, dict) else {"status": lora_code},
            },
            next_action=lora_next,
        )
    )

    # 13) 24h alive-when-idle validation gate
    alive24 = _latest_alive24_evidence(root)
    if not alive24.get("found"):
        alive24_status = "red"
        alive24_summary = "No completed 24-hour alive-when-idle evidence found."
        alive24_next = "Run full 24h validation and persist checks/proactive summaries under tmp/soak."
    elif alive24.get("meets_gate"):
        alive24_status = "green"
        alive24_summary = (
            "24-hour unattended validation completed with successful reach-out behavior."
        )
        alive24_next = "No action."
    elif alive24.get("meets_duration"):
        alive24_status = "yellow"
        alive24_summary = (
            "24-hour runtime evidence exists, but reach-out threshold was not met."
        )
        alive24_next = "Tune initiative thresholds and re-run 24h validation."
    else:
        alive24_status = "yellow"
        alive24_summary = (
            "Alive-when-idle run evidence exists, but duration/quality threshold is not yet met."
        )
        alive24_next = "Re-run 24h validation with stable runtime and verify summary artifacts."

    items.append(
        GateItem(
            key="alive_when_idle_24h_validation",
            status=alive24_status,
            summary=alive24_summary,
            evidence=alive24,
            next_action=alive24_next,
        )
    )

    counts = {"green": 0, "yellow": 0, "red": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    overall = "green" if counts["red"] == 0 and counts["yellow"] == 0 else ("yellow" if counts["red"] == 0 else "red")

    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "overall": overall,
        "counts": counts,
        "items": [asdict(item) for item in items],
        "health_status_code": health_code,
        "health": health,
        "memory_status_code": memory_code,
        "memory": memory if isinstance(memory, dict) else {"body": str(memory)[:400]},
        "channels_status_code": channels_code,
        "links_status_code": links_code,
        "link_map_status_code": link_map_code,
        "partner_status_code": partner_code,
        "core_identity_status_code": core_id_code,
        "learning_status_code": learning_code,
        "lora_status_code": lora_code,
        "innerlife_status_code": inner_code,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    lines = []
    lines.append("# VERA Alive Protocol Gate")
    lines.append("")
    lines.append(f"- Generated: `{report.get('timestamp_utc', '')}`")
    lines.append(f"- Base URL: `{report.get('base_url', '')}`")
    lines.append(f"- Overall: `{report.get('overall', '').upper()}`")
    counts = report.get("counts") or {}
    lines.append(
        f"- Counts: green={counts.get('green', 0)}, yellow={counts.get('yellow', 0)}, red={counts.get('red', 0)}"
    )
    lines.append("")
    lines.append("| Item | Status | Summary |")
    lines.append("|---|---|---|")
    for item in report.get("items", []):
        key = str(item.get("key", ""))
        status = str(item.get("status", "")).upper()
        summary = str(item.get("summary", "")).replace("|", "\\|")
        lines.append(f"| `{key}` | `{status}` | {summary} |")

    lines.append("")
    lines.append("## Non-Green Actions")
    for item in sorted(report.get("items", []), key=lambda x: _status_rank(str(x.get("status", "")))):
        status = str(item.get("status", ""))
        if status == "green":
            continue
        lines.append(f"- `{item.get('key')}` [{status.upper()}]: {item.get('next_action')}")

    lines.append("")
    lines.append("## Evidence")
    for item in report.get("items", []):
        lines.append(f"- `{item.get('key')}`: `{json.dumps(item.get('evidence', {}), ensure_ascii=True)[:900]}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate VERA Alive Protocol R/Y/G status.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--output-json", default="")
    parser.add_argument("--output-md", default="")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    report = build_report(args.base_url, root=root)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_json = Path(args.output_json) if args.output_json else root / "tmp" / "audits" / ts / "alive_protocol_gate.json"
    output_md = Path(args.output_md) if args.output_md else root / "tmp" / "audits" / ts / "alive_protocol_gate.md"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")

    print(f"Report JSON: {output_json}")
    print(f"Report MD: {output_md}")
    print(f"Overall: {str(report.get('overall', '')).upper()}")
    print(f"Counts: {report.get('counts')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

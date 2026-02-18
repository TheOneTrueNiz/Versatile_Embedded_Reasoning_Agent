#!/usr/bin/env python3
"""
VERA production readiness checklist.

Small deployment gate script for validating API/tool health and critical paths.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx


@dataclass
class CheckResult:
    name: str
    ok: bool
    critical: bool
    detail: str


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> Tuple[bool, Any, str]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"

    if response.status_code >= 400:
        detail = response.text.strip()
        if detail:
            return False, response.text, f"HTTP {response.status_code}: {detail}"
        return False, response.text, f"HTTP {response.status_code}"

    try:
        return True, response.json(), ""
    except Exception:
        return True, response.text, ""


def _print_check(result: CheckResult) -> None:
    status = "OK" if result.ok else ("FAIL" if result.critical else "WARN")
    critical_tag = "critical" if result.critical else "non-critical"
    print(f"[{status}] {result.name} ({critical_tag}) - {result.detail}", flush=True)


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except Exception:
                    continue
                if isinstance(item, dict):
                    rows.append(item)
    except Exception:
        return []
    return rows


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _jsonl_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except Exception:
        return 0
    return count


def _find_creds_dir() -> Path:
    env_value = os.getenv("CREDS_DIR", "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / "Documents" / "creds"


def _run_optional_script(label: str, cmd: List[str], timeout: float) -> CheckResult:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(1.0, timeout),
            check=False,
        )
    except Exception as exc:
        return CheckResult(label, False, True, f"failed to execute: {exc}")

    output = (proc.stdout or "").strip()
    if not output:
        output = (proc.stderr or "").strip()
    preview = output.replace("\n", " ")[:220]
    if proc.returncode == 0:
        return CheckResult(label, True, True, preview or "ok")
    return CheckResult(label, False, True, f"rc={proc.returncode}; {preview}")


def _run_prompt_tool_sweep(
    root_dir: Path,
    host: str,
    port: int,
    timeout: float,
    skip_call_me: bool,
    case_filters: List[str],
) -> CheckResult:
    script = root_dir / "scripts" / "vera_prompt_tool_sweep.py"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    default_cases = [
        "time",
        "filesystem",
        "memory",
        "sequential",
        "calculator",
        "wikipedia",
        "searxng",
        "brave",
        "github",
        "google_workspace",
        "memvid",
        "call_me_native_push",
        "call_me_mobile_push",
    ]
    filtered_cases = [str(case_id).strip() for case_id in case_filters if str(case_id).strip()]
    cases = filtered_cases or default_cases
    if skip_call_me:
        cases = [case_id for case_id in cases if not case_id.startswith("call_me_")]
    if not cases:
        return CheckResult("prompt_tool_sweep", True, True, "no cases selected")

    per_case_timeout = max(120.0, max(1.0, float(timeout)) / max(1, len(cases)))
    failed_cases: List[str] = []
    warning_cases: List[str] = []
    timeout_cases: List[str] = []
    report_paths: List[str] = []

    for case_id in cases:
        output_path = root_dir / "tmp" / f"prompt_tool_sweep_gate_{ts}_{case_id}.json"
        report_paths.append(str(output_path))
        cmd = [
            sys.executable,
            str(script),
            "--host",
            host,
            "--port",
            str(port),
            "--case",
            case_id,
            "--output",
            str(output_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=per_case_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failed_cases.append(case_id)
            timeout_cases.append(case_id)
            continue
        except Exception:
            failed_cases.append(case_id)
            continue

        report_obj: Dict[str, Any] = {}
        if output_path.exists():
            try:
                report_obj = json.loads(output_path.read_text(encoding="utf-8"))
            except Exception:
                report_obj = {}

        failures_int = 0
        try:
            failures_int = int(report_obj.get("failures") or 0)
        except Exception:
            failures_int = 1

        case_failed = proc.returncode != 0 or failures_int != 0
        case_warning = False
        results = report_obj.get("results")
        if isinstance(results, list) and results:
            row = results[0] if isinstance(results[0], dict) else {}
            row_passed = bool(row.get("passed") is True)
            row_critical = bool(row.get("critical", True))
            if not row_passed:
                if row_critical:
                    case_failed = True
                else:
                    case_warning = True
        if case_failed:
            failed_cases.append(case_id)
        elif case_warning:
            warning_cases.append(case_id)

    if not failed_cases:
        return CheckResult(
            "prompt_tool_sweep",
            True,
            True,
            (
                f"cases={len(cases)} passed; "
                f"warnings={warning_cases or 'none'}; "
                f"per_case_timeout={int(per_case_timeout)}s; "
                f"reports={report_paths[0]}..{report_paths[-1]}"
            ),
        )

    return CheckResult(
        "prompt_tool_sweep",
        False,
        True,
        (
            f"failed_cases={failed_cases}; timeout_cases={timeout_cases or 'none'}; "
            f"warning_cases={warning_cases or 'none'}; "
            f"per_case_timeout={int(per_case_timeout)}s; reports={report_paths[0]}..{report_paths[-1]}"
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _callme_sms_mode() -> str:
    raw = os.getenv("CALLME_SMS_MODE", "").strip().lower()
    if raw:
        if raw in {"off", "disabled", "disable", "none", "0", "false", "no"}:
            return "off"
        if raw in {"send-only", "send_only", "sendonly", "send", "outbound", "one-way", "one_way"}:
            return "send-only"
        if raw in {"two-way", "two_way", "twoway", "reply", "autoreply", "auto-reply", "bidirectional"}:
            return "two-way"
    sms_enabled = _env_bool("CALLME_SMS_ENABLED", False)
    if not sms_enabled:
        return "off"
    sms_autoreply = _env_bool("CALLME_SMS_AUTOREPLY", False)
    return "two-way" if sms_autoreply else "send-only"


def main() -> int:
    parser = argparse.ArgumentParser(description="Production checklist for Vera_2.0 deployment")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--timeout", type=float, default=25.0, help="HTTP timeout seconds")
    parser.add_argument("--min-running-mcp", type=int, default=8, help="Minimum running MCP servers")
    parser.add_argument("--skip-chat", action="store_true", help="Skip /v1/chat/completions check")
    parser.add_argument("--chat-model", default="", help="Optional model id for chat probe")
    parser.add_argument("--chat-message", default="Return exactly: VERA_CHECK_OK", help="Chat probe message")
    parser.add_argument("--with-live-call-me", action="store_true", help="Run scripts/call_me_live_smoke.py")
    parser.add_argument(
        "--live-call-me-skip-sms",
        action="store_true",
        help="When running --with-live-call-me, skip SMS and validate call path only",
    )
    parser.add_argument("--with-memvid-load", action="store_true", help="Run scripts/memvid_retrieval_hardening.py")
    parser.add_argument(
        "--with-native-push-hardening",
        action="store_true",
        help="Run scripts/native_push_hardening.py filter/tag validation",
    )
    parser.add_argument(
        "--native-push-hardening-no-live-send",
        action="store_true",
        help="When running --with-native-push-hardening, skip live push send",
    )
    parser.add_argument(
        "--with-prompt-tool-sweep",
        action="store_true",
        help="Run scripts/vera_prompt_tool_sweep.py and require zero critical failures",
    )
    parser.add_argument(
        "--with-mcp-golden-gate",
        action="store_true",
        help="Run scripts/vera_mcp_golden_gate.py deployment gate",
    )
    parser.add_argument(
        "--prompt-tool-sweep-skip-call-me",
        action="store_true",
        help="When running --with-prompt-tool-sweep, skip call-me push cases",
    )
    parser.add_argument(
        "--prompt-tool-sweep-case",
        action="append",
        default=[],
        help="Optional case_id filter(s) to pass through to vera_prompt_tool_sweep.py",
    )
    parser.add_argument(
        "--prompt-tool-sweep-timeout",
        type=float,
        default=840.0,
        help="Timeout seconds for prompt tool sweep subprocess",
    )
    parser.add_argument(
        "--mcp-golden-gate-timeout",
        type=float,
        default=1500.0,
        help="Timeout seconds for MCP golden gate subprocess",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Write JSON report to this path (default: tmp/production_checklist_<ts>.json)",
    )
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (root_dir / "tmp" / f"production_checklist_{ts}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    base_url = f"http://{args.host}:{args.port}"
    results: List[CheckResult] = []
    models: List[str] = []
    tools_list_map: Dict[str, List[str]] = {}
    tools_status_servers: Dict[str, Dict[str, Any]] = {}
    critical_failures = 0

    with httpx.Client(timeout=args.timeout) as client:
        ok, data, err = _request_json(client, "GET", f"{base_url}/api/health")
        health_ok = ok and isinstance(data, dict) and data.get("ok") is True
        results.append(CheckResult("api_health", health_ok, True, "ok" if health_ok else (err or "unexpected response")))

        ok, data, err = _request_json(client, "GET", f"{base_url}/v1/models")
        if ok and isinstance(data, dict):
            model_rows = data.get("data", [])
            if isinstance(model_rows, list):
                for row in model_rows:
                    if isinstance(row, dict):
                        model_id = str(row.get("id") or "").strip()
                        if model_id:
                            models.append(model_id)
        models_ok = len(models) > 0
        results.append(CheckResult("models", models_ok, True, f"count={len(models)}"))

        if not args.skip_chat:
            chosen_model = args.chat_model.strip() or (models[0] if models else "")
            if not chosen_model:
                results.append(CheckResult("chat_completion", False, True, "no model available"))
            else:
                payload = {
                    "model": chosen_model,
                    "messages": [{"role": "user", "content": args.chat_message}],
                }
                ok, data, err = _request_json(client, "POST", f"{base_url}/v1/chat/completions", json=payload)
                preview = ""
                if ok and isinstance(data, dict):
                    choices = data.get("choices", [])
                    if isinstance(choices, list) and choices:
                        first = choices[0] if isinstance(choices[0], dict) else {}
                        preview = str(first.get("message", {}).get("content", "")).strip().replace("\n", " ")
                chat_ok = ok and bool(preview)
                detail = preview[:160] if chat_ok else (err or "invalid chat response")
                results.append(CheckResult("chat_completion", chat_ok, True, detail))

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools")
        if ok and isinstance(data, dict):
            mcp = data.get("mcp", {})
            if isinstance(mcp, dict):
                servers = mcp.get("servers", {})
                if isinstance(servers, dict):
                    tools_status_servers = {
                        str(name): info
                        for name, info in servers.items()
                        if isinstance(info, dict)
                    }
        running_servers = sum(1 for info in tools_status_servers.values() if info.get("running") is True)
        running_ok = running_servers >= max(0, args.min_running_mcp)
        results.append(
            CheckResult(
                "mcp_running_count",
                running_ok,
                True,
                f"running={running_servers}, required>={args.min_running_mcp}",
            )
        )

        critical_servers = ["filesystem", "memory", "time", "sequential-thinking", "memvid", "call-me"]
        for server_name in critical_servers:
            info = tools_status_servers.get(server_name)
            if not info:
                results.append(CheckResult(f"mcp_server:{server_name}", False, True, "missing from /api/tools status"))
                continue
            running = info.get("running") is True
            missing_env = info.get("missing_env") or []
            if isinstance(missing_env, list):
                missing_env = [str(item) for item in missing_env]
            else:
                missing_env = [str(missing_env)]
            ok_server = running and len(missing_env) == 0
            detail = f"running={running}, missing_env={','.join(missing_env) if missing_env else 'none'}"
            results.append(CheckResult(f"mcp_server:{server_name}", ok_server, True, detail))

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/tools/list")
        if ok and isinstance(data, dict):
            tools = data.get("tools", {})
            if isinstance(tools, dict):
                for server, names in tools.items():
                    if isinstance(names, list):
                        tools_list_map[str(server)] = [str(name) for name in names]
        tools_list_ok = bool(tools_list_map)
        results.append(CheckResult("tools_list", tools_list_ok, True, f"servers={len(tools_list_map)}"))

        callme_tools = set(tools_list_map.get("call-me", []))
        sms_mode = _callme_sms_mode()
        callme_required = {"initiate_call", "send_mobile_push", "send_native_push"}
        if sms_mode != "off":
            callme_required.update({"send_sms", "send_mms"})
        callme_ok = callme_required.issubset(callme_tools)
        results.append(
            CheckResult(
                "call_me_tools",
                callme_ok,
                True,
                f"sms_mode={sms_mode}, required={sorted(callme_required)}, found={sorted(callme_tools)}",
            )
        )

        memvid_tools = set(tools_list_map.get("memvid", []))
        memvid_ok = "memvid_search" in memvid_tools
        results.append(
            CheckResult(
                "memvid_tools",
                memvid_ok,
                True,
                f"found={sorted(memvid_tools)}",
            )
        )

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/memory/stats")
        memvid_enabled = False
        if ok and isinstance(data, dict):
            stats = data.get("stats", {})
            if isinstance(stats, dict):
                memvid_block = stats.get("memvid_sdk", {})
                if isinstance(memvid_block, dict):
                    memvid_enabled = bool(memvid_block.get("enabled"))
        results.append(CheckResult("memory_stats", ok, True, "ok" if ok else (err or "failed")))
        results.append(CheckResult("memory_memvid_enabled", memvid_enabled, True, f"enabled={memvid_enabled}"))

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/push/native/status")
        native_push_detail = err or "unavailable"
        native_push_ok = False
        if ok and isinstance(data, dict):
            enabled = bool(data.get("enabled"))
            configured = bool(data.get("configured"))
            device_count = int(data.get("device_count") or 0)
            native_push_detail = f"enabled={enabled}, configured={configured}, devices={device_count}"
            native_push_ok = enabled and configured and device_count > 0
        results.append(CheckResult("native_push_status", native_push_ok, False, native_push_detail))

        ok, data, err = _request_json(client, "POST", f"{base_url}/api/push/native/targets", json={})
        native_targets_ok = False
        native_targets_detail = err or "unavailable"
        if ok and isinstance(data, dict):
            matched = int(data.get("matched") or 0)
            total_devices = int(data.get("total_devices") or 0)
            native_targets_ok = matched >= 0
            native_targets_detail = f"matched={matched}, total_devices={total_devices}"
        results.append(CheckResult("native_push_targets_preview", native_targets_ok, False, native_targets_detail))

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/innerlife/status")
        innerlife_ok = ok and isinstance(data, dict)
        results.append(CheckResult("innerlife_status", innerlife_ok, True, "ok" if innerlife_ok else (err or "failed")))
        autonomy: Dict[str, Any] = {}
        if innerlife_ok and isinstance(data, dict):
            raw_autonomy = data.get("autonomy")
            if isinstance(raw_autonomy, dict):
                autonomy = raw_autonomy
        autonomy_cfg = autonomy.get("config") if isinstance(autonomy.get("config"), dict) else {}
        autonomy_enabled = bool(autonomy_cfg.get("enabled")) if isinstance(autonomy_cfg, dict) else False
        autonomy_followthrough = bool(autonomy_cfg.get("followthrough_enabled")) if isinstance(autonomy_cfg, dict) else False
        phase = str(autonomy.get("phase") or "").strip().lower()
        phase_ok = phase in {"active", "idle"}
        last_cycle = str(autonomy.get("last_cycle_utc") or "").strip()
        results.append(CheckResult("autonomy_enabled", autonomy_enabled, True, f"enabled={autonomy_enabled}"))
        results.append(CheckResult("autonomy_followthrough_enabled", autonomy_followthrough, True, f"enabled={autonomy_followthrough}"))
        results.append(CheckResult("autonomy_phase", phase_ok, True, f"phase={phase or 'unknown'}"))
        results.append(CheckResult("autonomy_last_cycle", bool(last_cycle), False, f"last_cycle_utc={last_cycle or 'missing'}"))

    creds_dir = _find_creds_dir()
    required_cred_files = [
        creds_dir / "telnyx" / "telnyx_api_key",
        creds_dir / "telnyx" / "connection_id",
        creds_dir / "telnyx" / "phone_number",
        creds_dir / "telnyx" / "user_phone_number",
        creds_dir / "ngrok" / "ngrok_auth_token",
    ]
    missing_creds = [str(path) for path in required_cred_files if not path.exists()]
    creds_ok = not missing_creds
    results.append(
        CheckResult(
            "callme_credentials_files",
            creds_ok,
            True,
            "all present" if creds_ok else f"missing={missing_creds}",
        )
    )

    regression_path = root_dir / "vera_memory" / "flight_recorder" / "regression_results.jsonl"
    rows = _load_jsonl(regression_path)
    if rows:
        last_20 = rows[-20:]
        failed = sum(1 for row in last_20 if row.get("ok") is False)
        detail = f"recent={len(last_20)}, failed={failed}"
        results.append(CheckResult("regression_recent", failed == 0, False, detail))
    else:
        results.append(CheckResult("regression_recent", False, False, "no regression_results.jsonl rows found"))

    autonomy_events_path = root_dir / "vera_memory" / "autonomy_cadence_events.jsonl"
    autonomy_events_count = _jsonl_line_count(autonomy_events_path)
    results.append(
        CheckResult(
            "autonomy_events_log",
            autonomy_events_count > 0,
            False,
            f"path={autonomy_events_path}, rows={autonomy_events_count}",
        )
    )

    followthrough_state_path = root_dir / "tmp" / "followthrough_state.json"
    followthrough_actions_path = root_dir / "tmp" / "followthrough_actions.json"
    followthrough_action_events_path = root_dir / "tmp" / "followthrough_action_events.jsonl"
    followthrough_state = _load_json(followthrough_state_path)
    followthrough_actions = _load_json(followthrough_actions_path)

    commitments = followthrough_state.get("commitments")
    commitments_map = commitments if isinstance(commitments, dict) else {}
    failed_commitments = sum(
        1 for row in commitments_map.values() if isinstance(row, dict) and str(row.get("status") or "").lower() == "failed"
    )
    missed_commitments = sum(
        1 for row in commitments_map.values() if isinstance(row, dict) and str(row.get("status") or "").lower() == "missed"
    )
    results.append(
        CheckResult(
            "followthrough_state",
            followthrough_state_path.exists(),
            True,
            f"path={followthrough_state_path}, commitments={len(commitments_map)}",
        )
    )
    results.append(
        CheckResult(
            "followthrough_failed_commitments",
            failed_commitments == 0,
            True,
            f"failed={failed_commitments}, missed={missed_commitments}",
        )
    )

    action_rows = followthrough_actions.get("actions")
    actions_map = action_rows if isinstance(action_rows, dict) else {}
    failed_actions = sum(
        1 for row in actions_map.values() if isinstance(row, dict) and str(row.get("status") or "").lower() == "failed"
    )
    missed_actions = sum(
        1 for row in actions_map.values() if isinstance(row, dict) and str(row.get("status") or "").lower() == "missed"
    )
    results.append(
        CheckResult(
            "followthrough_actions",
            followthrough_actions_path.exists(),
            True,
            f"path={followthrough_actions_path}, actions={len(actions_map)}",
        )
    )
    results.append(
        CheckResult(
            "followthrough_failed_actions",
            failed_actions == 0,
            True,
            f"failed={failed_actions}, missed={missed_actions}",
        )
    )

    followthrough_action_events_count = _jsonl_line_count(followthrough_action_events_path)
    results.append(
        CheckResult(
            "followthrough_action_events_log",
            followthrough_action_events_count > 0,
            False,
            f"path={followthrough_action_events_path}, rows={followthrough_action_events_count}",
        )
    )

    if args.with_live_call_me:
        script = root_dir / "scripts" / "call_me_live_smoke.py"
        cmd = [sys.executable, str(script), "--host", args.host, "--port", str(args.port), "--wait", "45"]
        if args.live_call_me_skip_sms:
            cmd.append("--skip-sms")
        results.append(_run_optional_script("live_call_me_smoke", cmd, timeout=420))

    if args.with_memvid_load:
        script = root_dir / "scripts" / "memvid_retrieval_hardening.py"
        cmd = [
            sys.executable,
            str(script),
            "--events",
            "180",
            "--queries",
            "90",
            "--concurrency",
            "8",
        ]
        results.append(_run_optional_script("memvid_load_hardening", cmd, timeout=480))

    if args.with_native_push_hardening:
        script = root_dir / "scripts" / "native_push_hardening.py"
        cmd = [
            sys.executable,
            str(script),
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.native_push_hardening_no_live_send:
            cmd.append("--no-live-send")
        results.append(_run_optional_script("native_push_hardening", cmd, timeout=240))

    if args.with_prompt_tool_sweep:
        results.append(
            _run_prompt_tool_sweep(
                root_dir=root_dir,
                host=args.host,
                port=args.port,
                timeout=args.prompt_tool_sweep_timeout,
                skip_call_me=args.prompt_tool_sweep_skip_call_me,
                case_filters=list(args.prompt_tool_sweep_case or []),
            )
        )

    if args.with_mcp_golden_gate:
        script = root_dir / "scripts" / "vera_mcp_golden_gate.py"
        cmd = [
            sys.executable,
            str(script),
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--skip-routing",
            "--require-trainer-zero-rc",
            "--trainer-timeout",
            str(args.mcp_golden_gate_timeout),
        ]
        results.append(
            _run_optional_script(
                "mcp_golden_gate",
                cmd,
                timeout=max(180.0, args.mcp_golden_gate_timeout + 60.0),
            )
        )

    for result in results:
        _print_check(result)
        if result.critical and not result.ok:
            critical_failures += 1

    overall_ok = critical_failures == 0
    warnings = sum(1 for result in results if (not result.critical) and (not result.ok))
    print(
        f"Summary: overall_ok={overall_ok}, critical_failures={critical_failures}, warnings={warnings}",
        flush=True,
    )

    report = {
        "ok": overall_ok,
        "timestamp_utc": ts,
        "base_url": base_url,
        "critical_failures": critical_failures,
        "warnings": warnings,
        "results": [
            {
                "name": result.name,
                "ok": result.ok,
                "critical": result.critical,
                "detail": result.detail,
            }
            for result in results
        ],
        "models": models,
        "tools_servers_count": len(tools_status_servers),
        "tools_list_servers_count": len(tools_list_map),
    }
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Report written to {output_path}", flush=True)
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Controlled preflight checks for scenarios that were previously manual/skip-only.

Checks covered:
1) Memory persistence across restart (API transcript/session continuity)
2) Discord roundtrip readiness (and live status gate)
3) Voice backend + command/playback API path
4) Forced provider fallback (grok failure -> claude success) via local mock
5) Deterministic budget soft/hard threshold behavior (CostTracker)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

# Ensure local src/ packages are importable for deterministic module checks.
ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@dataclass
class CheckResult:
    name: str
    status: str  # ok | fail | skip
    detail: str
    critical: bool = True


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> Tuple[bool, Any, str, int]:
    try:
        response = client.request(method, url, timeout=timeout, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}", 0
    status = int(response.status_code)
    if status >= 400:
        body = response.text.strip()
        return False, body, f"HTTP {status}: {body}" if body else f"HTTP {status}", status
    try:
        return True, response.json(), "", status
    except Exception:
        return True, response.text, "", status


def _extract_chat_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    msg = first.get("message")
    if isinstance(msg, dict):
        return str(msg.get("content") or "")
    return ""


def _chat_once(
    client: httpx.Client,
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    conversation_id: Optional[str] = None,
    timeout: float = 90.0,
) -> Tuple[bool, str]:
    payload: Dict[str, Any] = {"model": model, "messages": messages}
    if conversation_id:
        payload["conversation_id"] = conversation_id
    ok, data, err, _ = _request_json(
        client,
        "POST",
        f"{base_url}/v1/chat/completions",
        json=payload,
        timeout=timeout,
    )
    if not ok:
        return False, err or "chat failed"
    text = _extract_chat_text(data).strip()
    return bool(text), text


def _load_xai_key(creds_dir: Path) -> str:
    key_path = creds_dir / "xai" / "xai_api"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    return ""


def _base_temp_env(root: Path, critical_servers: str = "time") -> Dict[str, str]:
    env = dict(os.environ)
    creds_dir = Path(env.get("CREDS_DIR", str(Path.home() / "Documents" / "creds"))).expanduser()
    env["CREDS_DIR"] = str(creds_dir)
    xai_key = env.get("XAI_API_KEY", "").strip() or _load_xai_key(creds_dir)
    if xai_key:
        env["XAI_API_KEY"] = xai_key
        env["API_KEY"] = xai_key
    env.setdefault("VERA_OPEN_BROWSER", "0")
    env.setdefault("VERA_CONFIG_WATCH_ENABLED", "0")
    env.setdefault("VERA_MCP_AUTOSTART", "1")
    env["VERA_STARTUP_CRITICAL_SERVERS"] = critical_servers
    env.setdefault("VERA_VOICE", "1")
    env.setdefault("VERA_MEMVID_ENABLED", "1")
    env.setdefault("GOOGLE_MCP_CREDENTIALS_DIR", str(creds_dir / "google" / "credentials"))

    # Best-effort Google OAuth resolution from generated client secret.
    generated_secret = creds_dir / "google" / "client_secret_generated.json"
    if generated_secret.exists():
        try:
            obj = json.loads(generated_secret.read_text(encoding="utf-8"))
            cfg = obj.get("installed") or obj.get("web") or {}
            client_id = str(cfg.get("client_id") or "").strip()
            client_secret = str(cfg.get("client_secret") or "").strip()
            redirect_uris = cfg.get("redirect_uris") if isinstance(cfg.get("redirect_uris"), list) else []
            redirect = str(redirect_uris[0]).strip() if redirect_uris else ""
            if client_id:
                env.setdefault("GOOGLE_OAUTH_CLIENT_ID", client_id)
            if client_secret:
                env.setdefault("GOOGLE_OAUTH_CLIENT_SECRET", client_secret)
            if redirect:
                env.setdefault("GOOGLE_OAUTH_REDIRECT_URI", redirect)
                env.setdefault("GOOGLE_REDIRECT_URI", redirect)
                env.setdefault("REDIRECT_URL", redirect)
            env.setdefault("GOOGLE_CLIENT_SECRET_PATH", str(generated_secret))
        except Exception:
            pass

    return env


class TempAPIServer:
    def __init__(
        self,
        *,
        root: Path,
        port: int,
        name: str,
        env_overrides: Optional[Dict[str, str]] = None,
        critical_servers: str = "time",
    ) -> None:
        self.root = root
        self.port = int(port)
        self.name = name
        self.env_overrides = dict(env_overrides or {})
        self.critical_servers = critical_servers
        self.process: Optional[subprocess.Popen[str]] = None
        self.log_path = root / "tmp" / f"controlled_{name}_{_utc_ts()}.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self, timeout: float = 150.0) -> Tuple[bool, str]:
        if self.process and self.process.poll() is None:
            return True, "already running"
        env = _base_temp_env(self.root, critical_servers=self.critical_servers)
        env.update(self.env_overrides)
        cmd = [
            str(self.root / ".venv" / "bin" / "python"),
            str(self.root / "run_vera_api.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--logging",
        ]
        log_handle = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )

        deadline = time.time() + max(20.0, timeout)
        with httpx.Client(timeout=5.0) as client:
            while time.time() < deadline:
                if self.process.poll() is not None:
                    return False, f"exited rc={self.process.returncode}; log={self.log_path}"
                ok, data, err, _ = _request_json(client, "GET", f"{self.base_url}/api/readiness")
                if ok and isinstance(data, dict):
                    if bool(data.get("ready")):
                        return True, f"ready phase={data.get('phase')}"
                time.sleep(1.0)
        return False, f"startup timeout; log={self.log_path}"

    def stop(self, timeout: float = 35.0) -> None:
        if not self.process:
            return
        if self.process.poll() is not None:
            self.process = None
            return
        try:
            with httpx.Client(timeout=5.0) as client:
                _request_json(client, "POST", f"{self.base_url}/api/exit", json={}, timeout=5.0)
        except Exception:
            pass
        deadline = time.time() + max(5.0, timeout)
        while time.time() < deadline:
            if self.process.poll() is not None:
                self.process = None
                return
            time.sleep(0.5)
        try:
            self.process.terminate()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5.0)
        except Exception:
            try:
                self.process.kill()
            except Exception:
                pass
        self.process = None


class _MockFallbackHandler(BaseHTTPRequestHandler):
    mock_state: Dict[str, int] = {"grok_calls": 0, "claude_calls": 0}

    def _write_json(self, code: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/chat/completions":
            _MockFallbackHandler.mock_state["grok_calls"] += 1
            self._write_json(503, {"error": {"message": "mock grok outage"}})
            return
        if self.path == "/v1/messages":
            _MockFallbackHandler.mock_state["claude_calls"] += 1
            self._write_json(
                200,
                {
                    "id": "msg_mock",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-20250514",
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": "CLAUDE_FALLBACK_OK"}],
                    "usage": {"input_tokens": 10, "output_tokens": 4},
                },
            )
            return
        self._write_json(404, {"error": {"message": f"unknown path {self.path}"}})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return


class MockFallbackServer:
    def __init__(self, port: int) -> None:
        self.port = int(port)
        self.httpd: Optional[ThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        _MockFallbackHandler.mock_state = {"grok_calls": 0, "claude_calls": 0}
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _MockFallbackHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        self.httpd = None
        self.thread = None

    @property
    def calls(self) -> Dict[str, int]:
        return dict(_MockFallbackHandler.mock_state)


def _check_restart_persistence(root: Path, model: str, port: int) -> CheckResult:
    runner = TempAPIServer(root=root, port=port, name="restart_check", critical_servers="time")
    token = f"VERA_RESTART_{_utc_ts()[-6:]}"
    convo = f"controlled-restart-{_utc_ts()}"
    try:
        ok, detail = runner.start()
        if not ok:
            return CheckResult("restart_persistence", "fail", detail)
        with httpx.Client(timeout=90.0) as client:
            ok1, text1 = _chat_once(
                client,
                runner.base_url,
                model,
                [{"role": "user", "content": f"Remember this token exactly for this conversation: {token}. Reply with ACK only."}],
                conversation_id=convo,
                timeout=90.0,
            )
            if not ok1:
                return CheckResult("restart_persistence", "fail", f"step1 failed: {text1}")
        runner.stop()
        ok, detail = runner.start()
        if not ok:
            return CheckResult("restart_persistence", "fail", f"restart failed: {detail}")
        with httpx.Client(timeout=90.0) as client:
            ok2, text2 = _chat_once(
                client,
                runner.base_url,
                model,
                [{"role": "user", "content": "What token did I ask you to remember? Reply with only the token."}],
                conversation_id=convo,
                timeout=90.0,
            )
            passed = ok2 and (token in text2)
            return CheckResult(
                "restart_persistence",
                "ok" if passed else "fail",
                f"expected={token}, got={text2[:220]}",
            )
    finally:
        runner.stop()


def _check_discord_roundtrip(base_url: str, timeout: float) -> CheckResult:
    with httpx.Client(timeout=timeout) as client:
        ok, data, err, _ = _request_json(client, "GET", f"{base_url}/api/channels/status")
    if not ok or not isinstance(data, dict):
        return CheckResult("discord_roundtrip", "fail", err or "channels status unavailable")
    active = data.get("active") if isinstance(data.get("active"), list) else []
    active_ids: List[str] = []
    for row in active:
        if isinstance(row, dict):
            cid = str(row.get("id") or "").strip()
            if cid:
                active_ids.append(cid)
    if "discord" not in active_ids:
        configured = data.get("configured") if isinstance(data.get("configured"), dict) else {}
        return CheckResult(
            "discord_roundtrip",
            "skip",
            f"discord channel not active/configured; active={active_ids or ['none']}, configured={configured}",
            critical=False,
        )
    return CheckResult(
        "discord_roundtrip",
        "skip",
        "discord adapter active but no API endpoint exists for deterministic external send/receive loopback",
        critical=False,
    )


def _check_voice_path(base_url: str, model: str, timeout: float) -> CheckResult:
    with httpx.Client(timeout=max(30.0, timeout)) as client:
        ok_status, status_obj, status_err, _ = _request_json(client, "GET", f"{base_url}/api/voice/status")
        if not ok_status or not isinstance(status_obj, dict):
            return CheckResult("voice_backend_command_playback", "fail", status_err or "voice status unavailable")
        if not bool(status_obj.get("enabled")):
            return CheckResult("voice_backend_command_playback", "fail", "voice disabled")

        ok_test, test_obj, test_err, _ = _request_json(
            client,
            "POST",
            f"{base_url}/api/voice/test",
            json={"voice": "eve", "include_audio": True},
            timeout=max(60.0, timeout),
        )
        if not ok_test or not isinstance(test_obj, dict):
            return CheckResult("voice_backend_command_playback", "fail", test_err or "voice test failed")
        audio_ok = bool(test_obj.get("ok")) and bool(str(test_obj.get("audio_b64") or "").strip())
        if not audio_ok:
            return CheckResult("voice_backend_command_playback", "fail", f"voice test payload={test_obj}")

        ok_chat, chat_obj, chat_err, _ = _request_json(
            client,
            "POST",
            f"{base_url}/v1/chat/voice",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with exactly: VERA_VOICE_CHAT_OK"}],
            },
            timeout=max(60.0, timeout),
        )
        if not ok_chat:
            return CheckResult("voice_backend_command_playback", "fail", chat_err or "voice chat failed")
        text = _extract_chat_text(chat_obj)
        marker_ok = "VERA_VOICE_CHAT_OK" in text
        detail = (
            f"backend={status_obj.get('backend')}, backend_ready={status_obj.get('backend_ready')}, "
            f"audio_b64={bool(test_obj.get('audio_b64'))}, voice_chat={text[:120]}"
        )
        return CheckResult("voice_backend_command_playback", "ok" if marker_ok else "fail", detail)


def _check_forced_fallback(root: Path, model: str, api_port: int, mock_port: int) -> CheckResult:
    mock = MockFallbackServer(mock_port)
    mock.start()
    runner = TempAPIServer(
        root=root,
        port=api_port,
        name="fallback_check",
        env_overrides={
            "XAI_API_KEY": "mock-invalid-grok-key",
            "API_KEY": "mock-invalid-grok-key",
            "ANTHROPIC_API_KEY": "mock-claude-key",
            "VERA_LLM_BASE_URL": f"http://127.0.0.1:{mock_port}",
        },
        critical_servers="time",
    )
    try:
        ok, detail = runner.start()
        if not ok:
            return CheckResult("forced_fallback_grok_to_claude", "fail", detail)
        with httpx.Client(timeout=90.0) as client:
            ok_chat, text = _chat_once(
                client,
                runner.base_url,
                model,
                [{"role": "user", "content": "Reply with exactly: CLAUDE_FALLBACK_OK"}],
                conversation_id=f"controlled-fallback-{_utc_ts()}",
                timeout=90.0,
            )
        calls = mock.calls
        passed = ok_chat and ("CLAUDE_FALLBACK_OK" in text) and calls.get("grok_calls", 0) > 0 and calls.get("claude_calls", 0) > 0
        return CheckResult(
            "forced_fallback_grok_to_claude",
            "ok" if passed else "fail",
            f"text={text[:140]}, grok_calls={calls.get('grok_calls', 0)}, claude_calls={calls.get('claude_calls', 0)}",
        )
    finally:
        runner.stop()
        mock.stop()


def _check_budget_deterministic() -> CheckResult:
    # Deterministic threshold behavior at module level.
    from observability.cost_tracker import BudgetStatus, CostTracker

    tracker = CostTracker(
        session_budget=1.0,
        soft_limit_ratio=0.5,
        hard_limit_ratio=0.8,
    )
    s0 = tracker.check_budget("web_search")
    tracker.record_usage("web_search", cost=0.55)
    s1 = tracker.check_budget("web_search")
    tracker.record_usage("web_search", cost=0.30)
    s2 = tracker.check_budget("web_search")
    passed = (
        s0 == BudgetStatus.OK
        and s1 == BudgetStatus.SOFT_LIMIT_WARNING
        and s2 == BudgetStatus.HARD_LIMIT_EXCEEDED
    )
    return CheckResult(
        "budget_soft_hard_limit_behavior",
        "ok" if passed else "fail",
        f"statuses={[s0.value, s1.value, s2.value]} expected=['ok','warning','exceeded']",
    )


def run(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    root = Path(__file__).resolve().parents[1]
    ts = _utc_ts()
    output = Path(args.output) if args.output else (root / "tmp" / f"controlled_checks_{ts}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    base_url = f"http://{args.host}:{args.port}"

    results: List[CheckResult] = []

    # 1) Restart persistence across restart.
    results.append(_check_restart_persistence(root, args.model, args.restart_port))

    # 2) Discord roundtrip readiness/live status.
    results.append(_check_discord_roundtrip(base_url, args.timeout))

    # 3) Voice backend + command/playback API path.
    results.append(_check_voice_path(base_url, args.model, args.timeout))

    # 4) Forced fallback grok -> claude via local provider mock.
    results.append(_check_forced_fallback(root, args.model, args.fallback_port, args.mock_port))

    # 5) Deterministic budget behavior.
    results.append(_check_budget_deterministic())

    critical_failures = sum(1 for r in results if r.critical and r.status == "fail")
    fails = sum(1 for r in results if r.status == "fail")
    skips = sum(1 for r in results if r.status == "skip")
    oks = sum(1 for r in results if r.status == "ok")
    overall_ok = critical_failures == 0

    report = {
        "ok": overall_ok,
        "timestamp_utc": ts,
        "base_url": base_url,
        "summary": {
            "ok": oks,
            "failed": fails,
            "skipped": skips,
            "critical_failures": critical_failures,
        },
        "results": [asdict(r) for r in results],
    }
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    for item in results:
        label = "OK" if item.status == "ok" else ("SKIP" if item.status == "skip" else "FAIL")
        print(f"[{label}] {item.name} - {item.detail}", flush=True)
    print(
        f"Summary: ok={oks}, failed={fails}, skipped={skips}, "
        f"critical_failures={critical_failures}, overall_ok={overall_ok}",
        flush=True,
    )
    print(f"Report written to {output}", flush=True)
    return (0 if overall_ok else 1), report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run controlled preflight checks")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--model", default="grok-4.20-experimental-beta-0304-reasoning")
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--restart-port", type=int, default=8791)
    parser.add_argument("--fallback-port", type=int, default=8792)
    parser.add_argument("--mock-port", type=int, default=18080)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    rc, _ = run(args)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

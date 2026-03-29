from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from api.server import (
    _ack_runplane_if_available,
    _evaluate_tools_readiness,
    autonomy_action_run,
    autonomy_dead_letter,
    autonomy_dead_letter_replay,
    autonomy_jobs,
    autonomy_runs_mark,
    autonomy_runs,
    autonomy_slo,
    create_app,
    improvement_archive_suggest,
    innerlife_autonomy_cycle,
    push_native_ack,
    session_activity,
    tools_preview,
    tools_start,
)
from core.services.event_bus import EventBus
from core.runtime.autonomy_runplane import AutonomyRunplane


class _RunplaneStub:
    def __init__(self) -> None:
        self.ack_calls = []
        self.replay_calls = []
        self.begin_calls = []
        self.complete_calls = []
        self.mark_calls = []
        self._counter = 0

    def begin_run(
        self,
        *,
        job_id: str,
        lane_key: str,
        trigger: str,
        kind: str = "generic",
        metadata: Dict[str, Any] | None = None,
        max_attempts: int = 3,
    ):
        self._counter += 1
        run_id = f"run_stub_{self._counter}"
        self.begin_calls.append((job_id, lane_key, trigger, kind, metadata or {}, max_attempts, run_id))
        return {"ok": True, "run_id": run_id}

    def complete_run(
        self,
        *,
        job_id: str,
        run_id: str,
        ok: bool,
        result: Dict[str, Any] | None = None,
        failure_class: str = "",
        retryable: bool = False,
        status: str = "",
    ):
        self.complete_calls.append((job_id, run_id, ok, result or {}, failure_class, retryable, status))
        return {"ok": True, "job_id": job_id, "run_id": run_id, "run_status": status or ("delivered" if ok else "failed")}

    def ack_run(self, run_id: str, *, ack_type: str = "opened", source: str = "unknown") -> Dict[str, Any]:
        self.ack_calls.append((run_id, ack_type, source))
        return {"ok": True, "run_id": run_id, "job_id": "reachout.push", "job_state": "acked"}

    def list_jobs(self, *, limit: int = 200, state_filter: str = ""):
        return [
            {
                "job_id": "executor.followthrough",
                "state": state_filter or "running",
                "updated_at_utc": "2026-03-05T00:00:00Z",
            }
        ][:limit]

    def list_runs(self, *, limit: int = 200, job_id: str = "", status_filter: str = ""):
        return [
            {
                "run_id": "run_test",
                "job_id": job_id or "executor.followthrough",
                "status": status_filter or "running",
                "started_at_utc": "2026-03-05T00:00:00Z",
            }
        ][:limit]

    def list_dead_letters(self, *, limit: int = 200):
        return [{"job_id": "executor.week1", "run_id": "run_dead"}][:limit]

    def status_snapshot(self) -> Dict[str, Any]:
        return {"job_count": 1, "run_count": 2, "dead_letter_count": 1}

    def slo_snapshot(self) -> Dict[str, Any]:
        return {"total_runs": 2, "delivery_success_rate_pct": 50.0}

    def operator_baseline_snapshot(self) -> Dict[str, Any]:
        return {"total_runs": 1, "delivery_success_rate_pct": 100.0, "scope": "operator_baseline"}

    def slo_windows_snapshot(self) -> Dict[str, Any]:
        return {"last_24h": {"total_runs": 1, "delivery_success_rate_pct": 100.0}}

    def replay_dead_letter(self, *, run_id: str = "", job_id: str = "", trigger: str = "operator_replay"):
        self.replay_calls.append((run_id, job_id, trigger))
        if not run_id and not job_id:
            return {"ok": False, "reason": "missing_run_or_job_id"}
        return {"ok": True, "job_id": job_id or "executor.week1", "job_state": "due"}

    def mark_run_status(self, *, run_id: str, status: str, source: str = "operator", note: str = ""):
        self.mark_calls.append((run_id, status, source, note))
        if status not in {"delivered", "acked", "escalated", "closed", "failed", "dead_letter"}:
            return {"ok": False, "reason": "invalid_status"}
        return {"ok": True, "run_id": run_id, "run_status": status, "job_state": status, "job_id": "delivery.reachout"}


class _PushServiceStub:
    def __init__(self, *, enabled: bool = True, subscriptions=None) -> None:
        self.enabled = enabled
        self._subscriptions = list(subscriptions or [])

    def list_subscriptions(self):
        return list(self._subscriptions)


class _NativePushServiceStub:
    def __init__(self, *, enabled: bool = True, configured: bool = True, devices=None) -> None:
        self.enabled = enabled
        self.configured = configured
        self._devices = list(devices or [])

    def list_devices(self):
        return list(self._devices)


class _FakeRequest:
    def __init__(self, *, app: Dict[str, Any], query: Dict[str, str] | None = None, payload: Dict[str, Any] | None = None):
        self.app = app
        self.query = query or {}
        self._payload = payload or {}
        self.can_read_body = True

    async def json(self) -> Dict[str, Any]:
        return self._payload


class _MCPStartStub:
    def __init__(self) -> None:
        self.calls = []

    def _start_server_with_timeout(self, name: str, timeout: float) -> bool:
        self.calls.append((name, timeout))
        return name != "call-me"

    def start_all(self) -> None:
        self.calls.append(("all", None))


class _ProactiveCycleStub:
    def __init__(self, future: Any) -> None:
        self._autonomy_cycle_future = future
        self.calls = []

    def action_autonomy_cycle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(dict(payload))
        return {"scheduled": True, "trigger": payload.get("trigger"), "force": payload.get("force")}

    def get_autonomy_status(self) -> Dict[str, Any]:
        return {"running": True}


class _ProactiveActionStub:
    def __init__(self) -> None:
        self.calls = []

    def action_check_tasks(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(("check_tasks", dict(payload)))
        return {"overdue_count": 1, "tasks": [{"id": "TASK-004", "title": "probe"}]}


class _ToolPreviewBridgeStub:
    def __init__(self) -> None:
        self.calls = []
        self.last_tool_payload = {"tool_names": ["get_events", "list_calendars"]}

    async def _build_tool_schemas(self, *, context: str):
        self.calls.append(context)
        return (
            [
                {"type": "function", "function": {"name": "get_events"}},
                {"type": "function", "function": {"name": "list_calendars"}},
            ],
            None,
            [],
        )

    def get_last_tool_payload(self) -> Dict[str, Any]:
        return dict(self.last_tool_payload)


def _route_paths(app) -> set[str]:
    paths: set[str] = set()
    for resource in app.router.resources():
        info = resource.get_info()
        path = info.get("path") or info.get("formatter")
        if path:
            paths.add(path)
    return paths


def test_create_app_registers_autonomy_routes() -> None:
    vera = SimpleNamespace(event_bus=EventBus())
    app = create_app(vera, ui_dist=None)
    paths = _route_paths(app)
    assert "/api/autonomy/jobs" in paths
    assert "/api/autonomy/actions/run" in paths
    assert "/api/autonomy/runs" in paths
    assert "/api/autonomy/runs/mark" in paths
    assert "/api/autonomy/dead-letter" in paths
    assert "/api/autonomy/dead-letter/replay" in paths
    assert "/api/autonomy/slo" in paths
    assert "/api/improvement-archive/suggest" in paths
    assert "/api/tools/status" in paths
    assert "/api/tools/preview" in paths


@pytest.mark.asyncio
async def test_tools_preview_builds_payload_without_chat_completion() -> None:
    bridge = _ToolPreviewBridgeStub()
    vera = SimpleNamespace(_llm_bridge=bridge)
    request = _FakeRequest(
        app={"vera": vera},
        payload={"context": "Check my calendar for upcoming events and reminders."},
    )

    response = await tools_preview(request)
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["tool_count"] == 2
    assert payload["payload"]["tool_names"] == ["get_events", "list_calendars"]
    assert bridge.calls == ["Check my calendar for upcoming events and reminders."]


@pytest.mark.asyncio
async def test_tools_start_uses_bounded_server_timeout_for_named_servers(monkeypatch) -> None:
    monkeypatch.setenv("VERA_MCP_MANUAL_START_TIMEOUT_SECONDS", "12")
    mcp = _MCPStartStub()
    vera = SimpleNamespace(mcp=mcp)
    request = _FakeRequest(app={"vera": vera}, payload={"servers": ["call-me", "time"]})

    response = await tools_start(request)
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["started"] == {"call-me": False, "time": True}
    assert mcp.calls == [("call-me", 12.0), ("time", 12.0)]


@pytest.mark.asyncio
async def test_improvement_archive_suggest_returns_matches(tmp_path) -> None:
    archive_path = tmp_path / "improvement_archive.json"
    archive_path.write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at_utc": "2026-03-26T21:00:00Z",
                "entries": [
                    {
                        "archive_id": "ia_exact",
                        "created_at_utc": "2026-03-26T21:00:00Z",
                        "title": "Exact",
                        "failure_class": "tool_routing_noise",
                        "problem_signature": "preview:web_research:browser_noise",
                        "intervention_type": "routing_rule",
                        "source_work_item_id": "awj_x",
                        "source_task_id": "TASK-X",
                        "proof_artifact": "tmp/audits/x.json",
                        "files_changed": ["src/orchestration/llm_bridge.py"],
                        "success_evidence": {"artifact_exists": True},
                        "proof_check": {"artifact_exists": True, "reason": "ok"},
                        "reuse_rule": "Suggest exact reuse.",
                        "rollout_guard": "suggest_only",
                        "status": "active",
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    response = await improvement_archive_suggest(
        _FakeRequest(
            app={"vera": SimpleNamespace()},
            payload={
                "archive_path": str(archive_path),
                "problem_signature": "preview:web_research:browser_noise",
                "failure_class": "tool_routing_noise",
                "limit": 2,
            },
        )
    )
    payload = json.loads(response.body.decode("utf-8"))

    assert response.status == 200
    assert payload["ok"] is True
    assert payload["result"]["match_count"] == 1
    assert payload["result"]["matches"][0]["archive_id"] == "ia_exact"


def test_evaluate_tools_readiness_includes_runtime_warnings() -> None:
    mcp = SimpleNamespace(
        get_status=lambda: {
            "total_configured": 1,
            "total_running": 1,
            "servers": {
                "call-me": {
                    "running": True,
                    "health": "healthy",
                    "uptime_seconds": 42.0,
                    "warning": "call-me running in degraded tunnel mode via localtunnel (ngrok_contention_cooldown)",
                    "runtime_status": {
                        "phase": "ready",
                        "tunnel_kind": "localtunnel",
                        "degraded": True,
                    },
                }
            },
        }
    )
    vera = SimpleNamespace(mcp=mcp)
    payload = _evaluate_tools_readiness({"vera": vera, "started_at": 0.0})

    assert payload["ready"] is True
    assert payload["warnings"][0]["server"] == "call-me"
    assert payload["warnings"][0]["runtime_status"]["tunnel_kind"] == "localtunnel"


def test_reachout_event_records_runplane_delivery_once() -> None:
    event_bus = EventBus()
    runplane = _RunplaneStub()
    vera = SimpleNamespace(event_bus=event_bus, proactive_manager=SimpleNamespace(runplane=runplane))
    app = create_app(vera, ui_dist=None)

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_abc", "delivered_to": ["fcm"]},
        source="test",
        sync=True,
    )
    # Duplicate publish should be ignored by the de-dupe map.
    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_abc", "delivered_to": ["fcm"]},
        source="test",
        sync=True,
    )

    assert app["last_reachout_event"]["run_id"] == "inner_abc"
    assert len(runplane.begin_calls) == 1
    assert len(runplane.complete_calls) == 1
    completed = runplane.complete_calls[0]
    assert completed[2] is True
    assert completed[3].get("innerlife_run_id") == "inner_abc"
    assert completed[3].get("delivered_to") == ["fcm"]
    assert completed[3].get("delivery_source_channels") == ["fcm"]
    assert completed[3].get("ack_expected") is True
    assert completed[3].get("ack_channels") == ["fcm"]


def test_reachout_api_only_delivery_is_not_marked_ack_expected() -> None:
    event_bus = EventBus()
    runplane = _RunplaneStub()
    vera = SimpleNamespace(event_bus=event_bus, proactive_manager=SimpleNamespace(runplane=runplane))
    app = create_app(vera, ui_dist=None)
    app["push_service"] = _PushServiceStub(enabled=False, subscriptions=[])
    app["native_push_service"] = _NativePushServiceStub(enabled=False, configured=False, devices=[])

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_api_only", "delivered_to": ["api"]},
        source="test",
        sync=True,
    )

    assert len(runplane.complete_calls) == 1
    completed = runplane.complete_calls[0]
    assert completed[2] is True
    assert completed[3].get("delivered_to") == ["api"]
    assert completed[3].get("delivery_source_channels") == ["api"]
    assert completed[3].get("ack_expected") is False
    assert completed[3].get("ack_channels") in (None, [])


def test_reachout_api_delivery_marks_ack_expected_when_push_targets_exist() -> None:
    event_bus = EventBus()
    runplane = _RunplaneStub()
    vera = SimpleNamespace(event_bus=event_bus, proactive_manager=SimpleNamespace(runplane=runplane))
    app = create_app(vera, ui_dist=None)
    app["push_service"] = _PushServiceStub(enabled=True, subscriptions=[{"endpoint": "https://example.test/push"}])
    app["native_push_service"] = _NativePushServiceStub(
        enabled=True,
        configured=True,
        devices=[{"token": "tok_12345678901234567890", "provider": "fcm"}],
    )

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_api_push", "delivered_to": ["api"]},
        source="test",
        sync=True,
    )

    assert len(runplane.complete_calls) == 1
    completed = runplane.complete_calls[0]
    assert completed[2] is True
    assert completed[3].get("delivered_to") == ["web_push", "fcm"]
    assert completed[3].get("delivery_source_channels") == ["api"]
    assert completed[3].get("ack_expected") is True
    assert completed[3].get("ack_channels") == ["web_push", "fcm"]


def test_ack_runplane_helper_marks_ack() -> None:
    runplane = _RunplaneStub()
    vera = SimpleNamespace(proactive_manager=SimpleNamespace(runplane=runplane))
    request = _FakeRequest(app={"vera": vera})
    result = _ack_runplane_if_available(
        request,
        run_id="run_123",
        ack_type="opened",
        source="native_ack",
    )
    assert result.get("ok") is True
    assert runplane.ack_calls == [("run_123", "opened", "native_ack")]


def test_push_native_ack_writes_log_and_updates_runplane(monkeypatch, tmp_path) -> None:
    ack_log = tmp_path / "push_ack.jsonl"
    monkeypatch.setenv("VERA_PUSH_ACK_LOG_PATH", str(ack_log))

    runplane = _RunplaneStub()
    vera = SimpleNamespace(proactive_manager=SimpleNamespace(runplane=runplane))
    request = _FakeRequest(
        app={"vera": vera},
        payload={
            "run_id": "run_abc",
            "ack_type": "opened",
            "channel": "fcm",
            "source": "native_ack_test",
        },
    )

    response = asyncio.run(push_native_ack(request))
    body = json.loads(response.text)

    assert response.status == 200
    assert body.get("ok") is True
    assert body.get("runplane_ack", {}).get("ok") is True
    assert runplane.ack_calls[-1] == ("run_abc", "opened", "native_ack_test")
    assert ack_log.exists()


def test_session_activity_proxies_ack_for_recent_reachout(monkeypatch, tmp_path) -> None:
    ack_log = tmp_path / "push_ack.jsonl"
    monkeypatch.setenv("VERA_PUSH_ACK_LOG_PATH", str(ack_log))
    monkeypatch.setenv("VERA_SESSION_ACTIVITY_ACK_WINDOW_SECONDS", "900")

    event_bus = EventBus()
    runplane = _RunplaneStub()
    vera = SimpleNamespace(event_bus=event_bus, proactive_manager=SimpleNamespace(runplane=runplane))
    app = create_app(vera, ui_dist=None)

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_session_ack", "delivered_to": ["api"]},
        source="test",
        sync=True,
    )

    response = asyncio.run(
        session_activity(
            _FakeRequest(
                app=app,
                payload={
                    "conversation_id": "conv1",
                    "channel_id": "ui",
                    "trigger": "page_focus",
                },
            )
        )
    )
    body = json.loads(response.text)

    assert response.status == 200
    assert body.get("ack_run_id") == "inner_session_ack"
    assert runplane.ack_calls[-1] == ("inner_session_ack", "opened", "session_activity_proxy")
    assert ack_log.exists()


def test_new_reachout_closes_prior_delivered_ackable_reachouts(tmp_path) -> None:
    event_bus = EventBus()
    runplane = AutonomyRunplane(tmp_path / "runplane")
    vera = SimpleNamespace(event_bus=event_bus, proactive_manager=SimpleNamespace(runplane=runplane))
    create_app(vera, ui_dist=None)

    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_old", "delivered_to": ["fcm"]},
        source="test",
        sync=True,
    )
    event_bus.publish(
        "innerlife.reached_out",
        {"run_id": "inner_new", "delivered_to": ["fcm"]},
        source="test",
        sync=True,
    )

    runs = runplane.list_runs(limit=10)
    by_job = {str(row.get("job_id")): row for row in runs}
    old_row = by_job["delivery.reachout.inner_old"]
    new_row = by_job["delivery.reachout.inner_new"]

    assert old_row.get("status") == "closed"
    assert old_row.get("status_source") == "reachout_superseded"
    assert "superseded_by:" in str(old_row.get("status_note") or "")
    assert new_row.get("status") == "delivered"


def test_autonomy_endpoints_return_runplane_payloads() -> None:
    runplane = _RunplaneStub()
    vera = SimpleNamespace(proactive_manager=SimpleNamespace(runplane=runplane))
    app = {"vera": vera}

    jobs_resp = asyncio.run(autonomy_jobs(_FakeRequest(app=app, query={"limit": "5", "state": "due"})))
    jobs_body = json.loads(jobs_resp.text)
    assert jobs_resp.status == 200
    assert jobs_body.get("count") == 1
    assert jobs_body.get("jobs", [])[0].get("state") == "due"

    runs_resp = asyncio.run(
        autonomy_runs(_FakeRequest(app=app, query={"limit": "5", "job_id": "executor.followthrough", "status": "running"}))
    )
    runs_body = json.loads(runs_resp.text)
    assert runs_resp.status == 200
    assert runs_body.get("count") == 1
    assert runs_body.get("runs", [])[0].get("job_id") == "executor.followthrough"

    mark_resp = asyncio.run(
        autonomy_runs_mark(
            _FakeRequest(
                app=app,
                payload={
                    "run_id": "run_test",
                    "status": "escalated",
                    "source": "unit_test",
                    "note": "awaiting ack",
                },
            )
        )
    )
    mark_body = json.loads(mark_resp.text)
    assert mark_resp.status == 200
    assert mark_body.get("ok") is True
    assert runplane.mark_calls[-1] == ("run_test", "escalated", "unit_test", "awaiting ack")

    dead_resp = asyncio.run(autonomy_dead_letter(_FakeRequest(app=app, query={"limit": "5"})))
    dead_body = json.loads(dead_resp.text)
    assert dead_resp.status == 200
    assert dead_body.get("count") == 1

    replay_resp = asyncio.run(
        autonomy_dead_letter_replay(
            _FakeRequest(app=app, payload={"job_id": "executor.week1", "trigger": "unit_test"})
        )
    )
    replay_body = json.loads(replay_resp.text)
    assert replay_resp.status == 200
    assert replay_body.get("ok") is True
    assert runplane.replay_calls[-1] == ("", "executor.week1", "unit_test")

    slo_resp = asyncio.run(autonomy_slo(_FakeRequest(app=app)))
    slo_body = json.loads(slo_resp.text)
    assert slo_resp.status == 200
    assert "slo" in slo_body
    assert "operator_baseline" in slo_body
    assert "status" in slo_body
    assert "windows" in slo_body
    assert "last_24h" in slo_body["windows"]


def test_innerlife_autonomy_cycle_wait_defaults_to_non_trivial_timeout() -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        future = loop.create_future()
        future.set_result({"ok": True, "reason": "completed"})
        proactive = _ProactiveCycleStub(future)
        vera = SimpleNamespace(proactive_manager=proactive)
        request = _FakeRequest(
            app={"vera": vera},
            payload={"trigger": "test_wait", "force": False, "wait": True},
        )

        response = loop.run_until_complete(innerlife_autonomy_cycle(request))
        body = json.loads(response.text)

        assert response.status == 200
        assert body.get("completed") is True
        assert body.get("cycle_result", {}).get("reason") == "completed"
        assert proactive.calls == [{"trigger": "test_wait", "force": False}]
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_innerlife_autonomy_cycle_timeout_returns_accepted_not_gateway_error() -> None:
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    try:
        asyncio.set_event_loop(loop)
        proactive = _ProactiveCycleStub(future)
        vera = SimpleNamespace(proactive_manager=proactive)
        request = _FakeRequest(
            app={"vera": vera},
            payload={"trigger": "test_wait_timeout", "force": False, "wait": True, "timeout_seconds": 1},
        )

        response = loop.run_until_complete(innerlife_autonomy_cycle(request))
        body = json.loads(response.text)

        assert response.status == 202
        assert body.get("scheduled") is True
        assert body.get("completed") is False
        assert body.get("in_progress") is True
        assert body.get("timeout_seconds") == 1.0
    finally:
        future.cancel()
        asyncio.set_event_loop(None)
        loop.close()


def test_autonomy_action_run_dispatches_allowed_action() -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        proactive = _ProactiveActionStub()
        request = _FakeRequest(
            app={"vera": SimpleNamespace(proactive_manager=proactive)},
            payload={"action_type": "check_tasks", "payload": {"source": "test"}},
        )

        response = loop.run_until_complete(autonomy_action_run(request))
        body = json.loads(response.text)

        assert response.status == 200
        assert body.get("ok") is True
        assert body.get("action_type") == "check_tasks"
        assert body.get("result", {}).get("overdue_count") == 1
        assert proactive.calls == [("check_tasks", {"source": "test"})]
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_autonomy_action_run_rejects_unknown_action() -> None:
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        request = _FakeRequest(
            app={"vera": SimpleNamespace(proactive_manager=_ProactiveActionStub())},
            payload={"action_type": "drop_database"},
        )

        response = loop.run_until_complete(autonomy_action_run(request))
        body = json.loads(response.text)

        assert response.status == 400
        assert body.get("error") == "Unsupported autonomy action."
    finally:
        asyncio.set_event_loop(None)
        loop.close()

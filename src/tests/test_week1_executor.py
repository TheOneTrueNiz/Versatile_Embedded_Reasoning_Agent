import json
from pathlib import Path
from types import SimpleNamespace

from scripts import vera_week1_executor as week1


def _make_args(tmp_path: Path, **overrides):
    parser = week1.build_arg_parser()
    args = parser.parse_args([])
    args.vera_root = tmp_path
    args.base_url = "http://127.0.0.1:8788"
    args.timezone = "America/Chicago"
    args.user_email = "jeffnyzio@gmail.com"
    args.state_path = tmp_path / "week1_state.json"
    args.event_log_path = tmp_path / "week1_events.jsonl"
    args.seed_csv = tmp_path / "seed.csv"
    args.docx = ""
    args.now_override = ""
    args.only_event_id = ""
    args.skip_import = False
    args.probe_due = False
    args.dry_run = False
    args.max_actions_per_run = 3
    args.max_retries_per_event = 3
    args.email_mode = "send"
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_probe_due_can_target_single_event_with_fixed_clock(tmp_path: Path, capsys) -> None:
    args = _make_args(
        tmp_path,
        probe_due=True,
        only_event_id="low_dopamine_start",
        now_override="2026-03-07T12:06:00-06:00",
    )

    rc = week1.run(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["probe_due"] is True
    assert payload["due_count"] == 1
    assert payload["due_events"] == [
        {
            "event_id": "low_dopamine_start",
            "kind": "push",
            "due_local": "2026-03-07T12:05:00-06:00",
            "minutes_late": 1,
            "attempts": 0,
        }
    ]


def test_ensure_week1_import_uses_seed_csv_when_docx_is_missing(tmp_path: Path, monkeypatch) -> None:
    args = _make_args(tmp_path)
    args.vera_root = tmp_path
    args.docx = ""
    args.seed_csv.write_text(
        "\n".join(
            [
                "category,task,priority,start_step,default_status_prompt,notes",
                "Home logistics,Order Hungryroot and set recurring drinks/snacks,P1,Open Hungryroot,DONE|STARTED|SNOOZE 10|RESCHEDULE,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    script_path = tmp_path / "scripts" / "import_week1_operating_tasks.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text("# stub\n", encoding="utf-8")
    seen = {}

    def _fake_run(cmd, cwd, capture_output, text, timeout, check):
        seen["cmd"] = cmd
        seen["cwd"] = cwd
        output_report = tmp_path / "tmp" / "audits" / "week1_task_import_report.json"
        output_report.parent.mkdir(parents=True, exist_ok=True)
        output_report.write_text(
            json.dumps(
                {
                    "parsed_items": 1,
                    "created_parent_tasks": 0,
                    "created_start_step_subtasks": 0,
                    "skipped_existing_parent_tasks": 1,
                    "skipped_existing_start_step_subtasks": 1,
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(week1.subprocess, "run", _fake_run)
    monkeypatch.setattr(week1, "_resolve_docx_path", lambda *_a, **_k: None)
    state = {"last_import_local_date": ""}

    result = week1._ensure_week1_import(args, "2026-03-27", state)

    assert result["ok"] is True
    assert state["last_import_local_date"] == "2026-03-27"
    assert "--seed-csv" in seen["cmd"]
    assert str(args.seed_csv) in seen["cmd"]
    assert "--docx" not in seen["cmd"]
    assert "--schedule-output" in seen["cmd"]
    assert str(tmp_path / "vera_memory" / "week1_task_schedule.json") in seen["cmd"]


def test_fetch_top_week1_tasks_prefers_structured_schedule_over_raw_list_order(tmp_path: Path, monkeypatch) -> None:
    schedule_path = tmp_path / "week1_task_schedule.json"
    schedule_path.write_text(
        json.dumps(
            {
                "timezone": "America/Chicago",
                "items": [
                    {
                        "parent_title": "[P1] Vacuum whole house",
                        "scheduled_local": "2026-03-27T17:30:00-05:00",
                        "priority": "P1",
                    },
                    {
                        "parent_title": "[P0] Make colonoscopy appointment",
                        "scheduled_local": "2026-03-27T13:30:00-05:00",
                        "priority": "P0",
                    },
                    {
                        "parent_title": "[P1] Order Hungryroot and set recurring drinks/snacks",
                        "scheduled_local": "2026-03-28T09:30:00-05:00",
                        "priority": "P1",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(week1, "_find_week1_task_list_id", lambda *a, **k: "task-list-1")
    monkeypatch.setattr(
        week1,
        "_call_tool",
        lambda *a, **k: (
            True,
            {
                "result": {
                    "content": [
                        {
                            "text": "\n".join(
                                [
                                    "- [P1] Vacuum whole house (ID: a1)",
                                    "- [P1] Order Hungryroot and set recurring drinks/snacks (ID: a2)",
                                    "- [P0] Make colonoscopy appointment (ID: a3)",
                                ]
                            )
                        }
                    ]
                }
            },
            "",
        ),
    )

    top = week1._fetch_top_week1_tasks(
        "http://127.0.0.1:8788",
        "jeffnyzio@gmail.com",
        "VERA Week1 Operating System v10",
        limit=3,
        schedule_path=schedule_path,
        timezone_name="America/Chicago",
        local_now=week1.dt.datetime.fromisoformat("2026-03-27T12:00:00-05:00"),
    )

    assert top == [
        "[P0] Make colonoscopy appointment",
        "[P1] Vacuum whole house",
        "[P1] Order Hungryroot and set recurring drinks/snacks",
    ]


def test_probe_due_includes_overlay_schedule_event(tmp_path: Path, capsys) -> None:
    probe_path = tmp_path / "week1_probe_schedule.json"
    probe_path.write_text(
        json.dumps(
            [
                {
                    "event_id": "probe_wake_call_20260314T1000",
                    "hhmm": "10:00",
                    "catchup_minutes": 120,
                    "kind": "call",
                    "enabled": True,
                }
            ]
        ),
        encoding="utf-8",
    )
    args = _make_args(
        tmp_path,
        probe_due=True,
        only_event_id="probe_wake_call_20260314T1000",
        now_override="2026-03-14T10:01:00-05:00",
        probe_schedule_path=probe_path,
    )

    rc = week1.run(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert rc == 0
    assert payload["due_count"] == 1
    assert payload["due_events"][0]["event_id"] == "probe_wake_call_20260314T1000"
    assert payload["due_events"][0]["kind"] == "call"


def test_skip_import_allows_deterministic_event_execution(tmp_path: Path, monkeypatch, capsys) -> None:
    args = _make_args(
        tmp_path,
        skip_import=True,
        only_event_id="low_dopamine_start",
        now_override="2026-03-07T12:06:00-06:00",
    )

    monkeypatch.setattr(week1, "_fetch_top_week1_tasks", lambda *a, **k: ["[P0] Ship the timing fix"])
    monkeypatch.setattr(
        week1,
        "_execute_event",
        lambda *a, **k: week1.DeliveryOutcome(
            ok=True,
            status="ok",
            detail="native_push_sent",
            delivery_channel="native_push",
            primary_channel="native_push",
        ),
    )

    rc = week1.run(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    state = json.loads(args.state_path.read_text(encoding="utf-8"))
    event_rows = args.event_log_path.read_text(encoding="utf-8").strip().splitlines()

    assert rc == 0
    assert payload["import_result"]["reason"] == "skip_import"
    assert payload["actions_attempted"] == 1
    assert payload["events_report"][0]["event_id"] == "low_dopamine_start"
    assert payload["events_report"][0]["status"] == "ok"
    assert payload["events_report"][0]["delivery_channel"] == "native_push"
    assert state["completed_events"]["2026-03-07:low_dopamine_start"]["status"] == "ok"
    assert len(event_rows) == 1


def test_send_push_retries_transient_native_failure(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def _fake_call(base_url, server, name, arguments, timeout_seconds=30.0):
        calls.append((server, name, arguments))
        if len(calls) == 1:
            return False, {}, 'HTTP 500: {"error":"Internal server error."}'
        return True, {"result": {"content": [{"text": "Native push sent."}]}}, ""

    monkeypatch.setattr(week1, "_call_tool", _fake_call)
    monkeypatch.setattr(week1.time, "sleep", lambda *_args, **_kwargs: None)

    outcome = week1._send_push("http://127.0.0.1:8788", "VERA", "Test")

    assert outcome.ok is True
    assert outcome.status == "ok"
    assert outcome.delivery_channel == "native_push"
    assert outcome.detail == "Native push sent."
    assert calls == [
        ("call-me", "send_native_push", {"title": "VERA", "message": "Test"}),
        ("call-me", "send_native_push", {"title": "VERA", "message": "Test"}),
    ]


def test_send_push_does_not_retry_non_retryable_error(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def _fake_call(base_url, server, name, arguments, timeout_seconds=30.0):
        calls.append((server, name, arguments))
        if name == "send_native_push":
            return False, {}, 'HTTP 400: {"error":"bad request"}'
        return True, {"result": {"content": [{"text": "Mobile push sent."}]}}, ""

    monkeypatch.setattr(week1, "_call_tool", _fake_call)
    monkeypatch.setattr(week1.time, "sleep", lambda *_args, **_kwargs: None)

    outcome = week1._send_push("http://127.0.0.1:8788", "VERA", "Test")

    assert outcome.ok is True
    assert outcome.status == "ok"
    assert outcome.delivery_channel == "mobile_push"
    assert outcome.primary_error == 'HTTP 400: {"error":"bad request"}'
    assert outcome.detail == "Mobile push sent."
    assert calls == [
        ("call-me", "send_native_push", {"title": "VERA", "message": "Test"}),
        ("call-me", "send_mobile_push", {"title": "VERA", "message": "Test"}),
    ]


def test_not_ready_call_me_does_not_consume_week1_retry(tmp_path: Path, monkeypatch, capsys) -> None:
    args = _make_args(
        tmp_path,
        skip_import=True,
        only_event_id="closeout",
        now_override="2026-03-07T20:31:00-06:00",
    )

    monkeypatch.setattr(week1, "_fetch_top_week1_tasks", lambda *a, **k: [])
    monkeypatch.setattr(
        week1,
        "_execute_event",
        lambda *a, **k: week1.DeliveryOutcome(
            ok=False,
            status="failed",
            detail='native_push_failed=HTTP 500: {"error":"MCP server call-me not running"}',
            primary_channel="native_push",
            fallback_channel="mobile_push",
            primary_error='HTTP 500: {"error":"MCP server call-me not running"}',
        ),
    )

    rc = week1.run(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    state = json.loads(args.state_path.read_text(encoding="utf-8"))
    event_rows = [json.loads(line) for line in args.event_log_path.read_text(encoding="utf-8").strip().splitlines()]

    assert rc == 0
    assert payload["events_report"][0]["status"] == "deferred_not_ready"
    assert state["attempts"] == {}
    assert state["completed_events"] == {}
    assert "2026-03-07:closeout" in state["deferred_not_ready"]
    assert event_rows[0]["status"] == "deferred_not_ready"
    assert event_rows[0]["holdoff_seconds"] == 900


def test_not_ready_holdoff_suppresses_repeat_event_logging(tmp_path: Path, monkeypatch, capsys) -> None:
    args = _make_args(
        tmp_path,
        skip_import=True,
        only_event_id="closeout",
        now_override="2026-03-07T20:31:00-06:00",
    )

    monkeypatch.setattr(week1, "_fetch_top_week1_tasks", lambda *a, **k: [])
    monkeypatch.setattr(
        week1,
        "_execute_event",
        lambda *a, **k: week1.DeliveryOutcome(
            ok=False,
            status="failed",
            detail='native_push_failed=HTTP 500: {"error":"MCP server call-me not running"}',
            primary_channel="native_push",
            fallback_channel="mobile_push",
            primary_error='HTTP 500: {"error":"MCP server call-me not running"}',
        ),
    )

    rc1 = week1.run(args)
    first_payload = json.loads(capsys.readouterr().out)
    state_after_first = json.loads(args.state_path.read_text(encoding="utf-8"))
    first_log_lines = args.event_log_path.read_text(encoding="utf-8").strip().splitlines()

    args.now_override = "2026-03-07T20:35:00-06:00"
    rc2 = week1.run(args)
    second_payload = json.loads(capsys.readouterr().out)
    state_after_second = json.loads(args.state_path.read_text(encoding="utf-8"))
    second_log_lines = args.event_log_path.read_text(encoding="utf-8").strip().splitlines()

    assert rc1 == 0
    assert rc2 == 0
    assert first_payload["events_report"][0]["status"] == "deferred_not_ready"
    assert second_payload["events_report"] == []
    assert state_after_first["deferred_not_ready"] == state_after_second["deferred_not_ready"]
    assert len(first_log_lines) == 1
    assert second_log_lines == first_log_lines


def test_probe_due_skips_event_during_not_ready_holdoff(tmp_path: Path, monkeypatch, capsys) -> None:
    args = _make_args(
        tmp_path,
        probe_due=True,
        only_event_id="closeout",
        now_override="2026-03-07T20:35:00-06:00",
    )
    args.state_path.write_text(
        json.dumps(
            {
                "version": 1,
                "last_run_utc": "",
                "last_import_local_date": "",
                "completed_events": {},
                "attempts": {},
                "deferred_not_ready": {
                    "2026-03-07:closeout": {
                        "until_utc": "2026-03-08T03:00:00Z",
                        "detail": "call-me not running",
                        "updated_at_utc": "2026-03-08T02:31:00Z",
                    }
                },
                "updated_at_utc": "2026-03-08T02:31:00Z",
            }
        ),
        encoding="utf-8",
    )

    rc = week1.run(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["due_count"] == 0
    assert payload["due_events"] == []


def test_send_call_with_fallback_reports_partial_success(monkeypatch) -> None:
    calls = []

    def _fake_call(base_url, server, name, arguments, timeout_seconds=30.0, max_attempts=2, retry_sleep_seconds=0.35):
        calls.append((server, name, arguments, timeout_seconds, max_attempts, retry_sleep_seconds))
        if name == "initiate_call":
            return False, {}, 'HTTP 500: {"error":"call backend failed"}'
        if name == "send_native_push":
            return True, {"result": {"content": [{"text": "Native push sent."}]}}, ""
        raise AssertionError(name)

    monkeypatch.setattr(week1, "_call_tool_with_retry", _fake_call)
    monkeypatch.setenv("VERA_WEEK1_WAKE_CALL_ATTEMPTS", "2")
    monkeypatch.setenv("VERA_WEEK1_WAKE_CALL_RETRY_SLEEP_SECONDS", "5.0")

    outcome = week1._send_call_with_fallback(
        "http://127.0.0.1:8788",
        "Wake up",
        "VERA Wake Check",
        "Wake fallback",
    )

    assert outcome.ok is True
    assert outcome.status == "partial_ok_fallback_push"
    assert outcome.delivery_channel == "native_push"
    assert outcome.primary_channel == "call"
    assert outcome.fallback_channel == "native_push"
    assert outcome.primary_error == 'HTTP 500: {"error":"call backend failed"}'
    assert outcome.detail == "Native push sent."
    assert calls == [
        ("call-me", "initiate_call", {"message": "Wake up"}, 75.0, 2, 5.0),
        ("call-me", "send_native_push", {"title": "VERA Wake Check", "message": "Wake fallback"}, 30.0, 2, 0.35),
    ]


def test_send_call_with_fallback_recovers_on_second_call_attempt(monkeypatch) -> None:
    calls = []
    attempts = {"count": 0}

    def _fake_call(base_url, server, name, arguments, timeout_seconds=30.0):
        calls.append((server, name, arguments, timeout_seconds))
        if name == "initiate_call":
            attempts["count"] += 1
            if attempts["count"] == 1:
                return False, {}, "timed out"
            return True, {"result": {"content": [{"text": "Call initiated successfully."}]}}, ""
        raise AssertionError(name)

    monkeypatch.setattr(week1, "_call_tool", _fake_call)
    monkeypatch.setattr(week1.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setenv("VERA_WEEK1_WAKE_CALL_ATTEMPTS", "2")
    monkeypatch.setenv("VERA_WEEK1_WAKE_CALL_RETRY_SLEEP_SECONDS", "5.0")

    outcome = week1._send_call_with_fallback(
        "http://127.0.0.1:8788",
        "Wake up",
        "VERA Wake Check",
        "Wake fallback",
    )

    assert outcome.ok is True
    assert outcome.status == "ok"
    assert outcome.delivery_channel == "call"
    assert attempts["count"] == 2
    assert calls == [
        ("call-me", "initiate_call", {"message": "Wake up"}, 75.0),
        ("call-me", "initiate_call", {"message": "Wake up"}, 75.0),
    ]


def test_run_records_partial_wake_call_fallback_status(tmp_path: Path, monkeypatch, capsys) -> None:
    args = _make_args(
        tmp_path,
        skip_import=True,
        only_event_id="wake_call",
        now_override="2026-03-07T08:01:00-06:00",
    )

    monkeypatch.setattr(week1, "_fetch_top_week1_tasks", lambda *a, **k: [])
    monkeypatch.setattr(
        week1,
        "_execute_event",
        lambda *a, **k: week1.DeliveryOutcome(
            ok=True,
            status="partial_ok_fallback_push",
            detail="Native push sent.",
            delivery_channel="native_push",
            primary_channel="call",
            fallback_channel="native_push",
            primary_error='HTTP 500: {"error":"call backend failed"}',
        ),
    )

    rc = week1.run(args)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    state = json.loads(args.state_path.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["events_report"][0]["status"] == "partial_ok_fallback_push"
    assert payload["events_report"][0]["delivery_channel"] == "native_push"
    assert payload["events_report"][0]["primary_channel"] == "call"
    assert "call backend failed" in payload["events_report"][0]["primary_error"]
    assert state["completed_events"]["2026-03-07:wake_call"]["status"] == "partial_ok_fallback_push"

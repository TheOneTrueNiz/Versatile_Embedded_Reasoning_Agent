import json
from pathlib import Path

from scripts import import_week1_operating_tasks as importer


def _make_args(tmp_path: Path, **overrides):
    parser = importer.argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--user-email", default="jeffnyzio@gmail.com")
    parser.add_argument("--docx", default="")
    parser.add_argument("--seed-csv", default="")
    parser.add_argument("--task-list-title", default="VERA Week1 Operating System v10")
    parser.add_argument("--timezone", default="America/Chicago")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", default=str(tmp_path / "report.json"))
    parser.add_argument("--schedule-output", default=str(tmp_path / "week1_schedule.json"))
    args = parser.parse_args([])
    args.base_url = "http://127.0.0.1:8788"
    args.user_email = "jeffnyzio@gmail.com"
    args.docx = ""
    args.seed_csv = str(tmp_path / "seed.csv")
    args.task_list_title = "VERA Week1 Operating System v10"
    args.timezone = "America/Chicago"
    args.dry_run = True
    args.output = str(tmp_path / "report.json")
    args.schedule_output = str(tmp_path / "week1_schedule.json")
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def test_build_backlog_from_seed_rows_supports_public_csv_only_seed() -> None:
    seeds = {
        "task-one": importer.SeedRow(
            category="Home logistics",
            task="Task One",
            priority="P1",
            start_step="Open the page",
            status_prompt="DONE|STARTED",
            notes="first",
        ),
        "task-two": importer.SeedRow(
            category="Appointments",
            task="Task Two",
            priority="P0",
            start_step="Call the clinic",
            status_prompt="DONE|STARTED",
            notes="second",
        ),
    }

    items = importer._build_backlog_from_seed_rows(seeds)

    assert [item.task for item in items] == ["Task One", "Task Two"]
    assert items[0].category_key == "home_logistics"
    assert items[1].category_key == "appointments"
    assert items[1].priority == "P0"


def test_run_supports_csv_only_import_when_docx_is_absent(tmp_path: Path, monkeypatch, capsys) -> None:
    seed_path = tmp_path / "seed.csv"
    seed_path.write_text(
        "\n".join(
            [
                "category,task,priority,start_step,default_status_prompt,notes",
                "Home logistics,Order Hungryroot and set recurring drinks/snacks,P1,Open Hungryroot and check last order items,DONE|STARTED|SNOOZE 10|RESCHEDULE,reduce household friction",
                "Appointments,Make colonoscopy appointment,P0,Identify preferred clinic and call window,DONE|STARTED|SNOOZE 10|RESCHEDULE,",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args = _make_args(tmp_path, seed_csv=str(seed_path))

    monkeypatch.setattr(importer, "_ensure_task_list", lambda *a, **k: "task-list-123")
    monkeypatch.setattr(importer, "_fetch_existing_titles", lambda *a, **k: ({}, {}))

    rc = importer.run(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["source_mode"] == "seed_csv"
    assert payload["docx"] is None
    assert payload["seed_csv"] == str(seed_path.resolve())
    assert payload["parsed_items"] == 2
    assert payload["created_parent_tasks"] == 0
    assert payload["created_start_step_subtasks"] == 0
    assert payload["dry_run"] is True
    assert payload["items"][0]["task"] == "Make colonoscopy appointment"
    assert payload["items"][0]["priority"] == "P0"
    assert Path(args.output).exists()
    schedule_payload = json.loads(Path(args.schedule_output).read_text())
    assert schedule_payload["timezone"] == "America/Chicago"
    assert len(schedule_payload["items"]) == 2
    assert schedule_payload["items"][0]["parent_title"].startswith("[P0] ")
    assert schedule_payload["items"][0]["focus_slot"] in {"09:30", "13:30", "17:30"}

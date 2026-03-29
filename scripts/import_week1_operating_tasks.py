#!/usr/bin/env python3
"""
Import Week 1 Operating System task backlog into Google Tasks via Vera API.

Scope:
- Parse section 13.3 task items from a Week1 .docx file.
- Create/lookup a dedicated Google task list.
- Create one parent task + one START STEP subtask per imported item.
- Attach followthrough metadata in notes.
- Avoid duplicate task creation by title.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo


SECTION_START = "13.3 Task List (to be ingested and scheduled)"
SECTION_END = "14. Family Schedule Constraints"
STATUS_PROMPT_DEFAULT = "DONE|STARTED|SNOOZE 10|RESCHEDULE"

CATEGORY_HEADERS = {
    "Home logistics / admin": "home_logistics",
    "Home logistics": "home_logistics",
    "Appointments (health/pets)": "appointments",
    "Appointments": "appointments",
    "House cleaning - baseline": "cleaning_baseline",
    "Cleaning baseline": "cleaning_baseline",
    "Declutter projects (chunk into sprints)": "declutter",
    "Declutter": "declutter",
    "Exterior / yard": "exterior",
    "Home improvement": "home_improvement",
}

HEAVY_CATEGORIES = {"cleaning_baseline", "declutter", "exterior", "home_improvement"}


@dataclass
class SeedRow:
    category: str
    task: str
    priority: str
    start_step: str
    status_prompt: str
    notes: str


@dataclass
class BacklogItem:
    category_key: str
    category_label: str
    task: str
    priority: str
    start_step: str
    status_prompt: str
    notes: str


@dataclass
class ScheduledItem:
    item: BacklogItem
    due_local: dt.datetime


def _norm(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = cleaned.replace("’", "'").replace("`", "'")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def _read_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        data = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    data = re.sub(r"<w:p[^>]*>", "\n", data)
    data = re.sub(r"<[^>]+>", "", data)
    data = (
        data.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("\xa0", " ")
    )
    lines = [line.strip() for line in data.splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_section_lines(text: str) -> List[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    out: List[str] = []
    active = False
    for line in lines:
        if not active and line.startswith(SECTION_START):
            active = True
            continue
        if active and line.startswith(SECTION_END):
            break
        if active:
            out.append(line)
    return out


def _load_seed_rows(path: Optional[Path]) -> Dict[str, SeedRow]:
    if not path or not path.exists():
        return {}
    rows: Dict[str, SeedRow] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            task = (row.get("task") or "").strip()
            if not task:
                continue
            seed = SeedRow(
                category=(row.get("category") or "").strip(),
                task=task,
                priority=(row.get("priority") or "").strip() or "P1",
                start_step=(row.get("start_step") or "").strip(),
                status_prompt=(row.get("default_status_prompt") or "").strip() or STATUS_PROMPT_DEFAULT,
                notes=(row.get("notes") or "").strip(),
            )
            rows[_norm(task)] = seed
    return rows


def _category_key_for_label(label: str) -> Tuple[str, str]:
    cleaned = (label or "").strip()
    key = CATEGORY_HEADERS.get(cleaned)
    if key:
        return key, cleaned
    normalized = _norm(cleaned)
    for candidate, candidate_key in CATEGORY_HEADERS.items():
        if _norm(candidate) == normalized:
            return candidate_key, candidate
    raise KeyError(f"Unknown Week1 category label: {cleaned}")


def _parse_backlog(section_lines: Iterable[str], seed_rows: Dict[str, SeedRow]) -> List[BacklogItem]:
    items: List[BacklogItem] = []
    current_label = ""
    current_key = ""

    for raw in section_lines:
        line = raw.strip()
        if line in CATEGORY_HEADERS:
            current_label = line
            current_key = CATEGORY_HEADERS[line]
            continue
        if not current_key:
            continue
        # Keep only actual task lines under each category.
        if line.endswith(":"):
            continue

        task = line.rstrip(".").strip()
        if not task:
            continue

        seed = seed_rows.get(_norm(task))
        priority = _priority_for(task, current_key, seed.priority if seed else None)
        start_step = (seed.start_step if seed and seed.start_step else _fallback_start_step(task, current_key)).strip()
        status_prompt = (seed.status_prompt if seed and seed.status_prompt else STATUS_PROMPT_DEFAULT).strip()
        notes = (seed.notes if seed else "").strip()

        items.append(
            BacklogItem(
                category_key=current_key,
                category_label=current_label,
                task=task,
                priority=priority,
                start_step=start_step,
                status_prompt=status_prompt,
                notes=notes,
            )
        )

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: List[BacklogItem] = []
    for item in items:
        key = _norm(item.task)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _build_backlog_from_seed_rows(seed_rows: Dict[str, SeedRow]) -> List[BacklogItem]:
    items: List[BacklogItem] = []
    seen: set[str] = set()
    for seed in seed_rows.values():
        task_key = _norm(seed.task)
        if not task_key or task_key in seen:
            continue
        category_key, category_label = _category_key_for_label(seed.category)
        items.append(
            BacklogItem(
                category_key=category_key,
                category_label=category_label,
                task=seed.task.strip(),
                priority=_priority_for(seed.task, category_key, seed.priority),
                start_step=(seed.start_step or _fallback_start_step(seed.task, category_key)).strip(),
                status_prompt=(seed.status_prompt or STATUS_PROMPT_DEFAULT).strip(),
                notes=(seed.notes or "").strip(),
            )
        )
        seen.add(task_key)
    return items


def _priority_for(task: str, category_key: str, seeded: Optional[str]) -> str:
    if seeded in {"P0", "P1", "P2", "P3"}:
        return seeded
    text = _norm(task)
    if category_key == "appointments":
        if any(token in text for token in ("colonoscopy", "adhd", "autism", "assessment")):
            return "P0"
        return "P1"
    if category_key == "home_logistics" and "insurance" in text:
        return "P0"
    if category_key in {"home_improvement", "exterior"}:
        return "P2"
    if "lowest priority" in text:
        return "P2"
    return "P1"


def _fallback_start_step(task: str, category_key: str) -> str:
    text = task.strip()
    lower = _norm(text)

    if "appointment" in lower or lower.startswith("make "):
        return "Find contact details and choose a 10-minute call window"
    if category_key == "declutter":
        return "Pick one small area and sort keep/toss for 2 minutes"
    if category_key == "cleaning_baseline":
        return "Set a 10-minute timer and start with one small area"
    if category_key == "home_logistics":
        return "Open the relevant app/site and define the first 2-minute action"
    if category_key == "exterior":
        return "Walk the target area and list the first visible quick win"
    if category_key == "home_improvement":
        return "List current fixture/part and one next step for quote or replacement"

    # Generic fallback.
    words = text.split()
    snippet = " ".join(words[:8])
    return f"Start the first 2-minute action for: {snippet}".strip()


def _priority_rank(priority: str) -> int:
    return {"P0": 0, "P1": 1, "P2": 2, "P3": 3}.get(priority, 1)


def _schedule_items(items: List[BacklogItem], tz_name: str, start_date: dt.date) -> List[ScheduledItem]:
    tz = ZoneInfo(tz_name)
    slots = [dt.time(9, 30), dt.time(13, 30), dt.time(17, 30)]

    by_day_total: Dict[dt.date, int] = {}
    by_day_heavy: Dict[dt.date, int] = {}
    by_day_declutter: Dict[dt.date, int] = {}

    sorted_items = sorted(items, key=lambda x: (_priority_rank(x.priority), x.category_key, x.task.lower()))
    scheduled: List[ScheduledItem] = []

    for item in sorted_items:
        day_offset = 0
        while True:
            target_day = start_date + dt.timedelta(days=day_offset)
            total = by_day_total.get(target_day, 0)
            heavy = by_day_heavy.get(target_day, 0)
            declutter = by_day_declutter.get(target_day, 0)

            is_heavy = item.category_key in HEAVY_CATEGORIES
            is_declutter = item.category_key == "declutter"

            if total >= len(slots):
                day_offset += 1
                continue
            if is_heavy and heavy >= 2:
                day_offset += 1
                continue
            if is_declutter and declutter >= 1:
                day_offset += 1
                continue

            slot_idx = total
            due_local = dt.datetime.combine(target_day, slots[slot_idx], tz)
            by_day_total[target_day] = total + 1
            if is_heavy:
                by_day_heavy[target_day] = heavy + 1
            if is_declutter:
                by_day_declutter[target_day] = declutter + 1

            scheduled.append(ScheduledItem(item=item, due_local=due_local))
            break

    return scheduled


def _call_tool(base_url: str, server: str, name: str, arguments: Dict[str, object], timeout: float = 30.0) -> Dict[str, object]:
    payload = {
        "server": server,
        "name": name,
        "arguments": arguments,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/tools/call",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _extract_result_text(tool_response: Dict[str, object]) -> str:
    result = tool_response.get("result")
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            text = structured.get("result")
            if isinstance(text, str) and text.strip():
                return text
        content = result.get("content")
        if isinstance(content, list):
            for entry in content:
                if isinstance(entry, dict):
                    text = entry.get("text")
                    if isinstance(text, str) and text.strip():
                        return text
    return ""


def _parse_task_list_ids(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    pattern = re.compile(r"^-\s+(.+?)\s+\(ID:\s*([A-Za-z0-9_\-]+)\)", re.MULTILINE)
    for match in pattern.finditer(text):
        title = match.group(1).strip()
        list_id = match.group(2).strip()
        out[title] = list_id
    return out


def _parse_task_structure(text: str) -> Tuple[Dict[str, str], Dict[str, bool]]:
    all_titles: Dict[str, str] = {}
    parent_has_start_step: Dict[str, bool] = {}

    top_pattern = re.compile(r"^-\s+(.+?)\s+\(ID:\s*([A-Za-z0-9_\-]+)\)$")
    sub_pattern = re.compile(r"^\s+\*\s+(.+?)\s+\(ID:\s*([A-Za-z0-9_\-]+)\)$")
    current_parent_key: Optional[str] = None

    for raw in text.splitlines():
        line = raw.rstrip()
        top_match = top_pattern.match(line)
        if top_match:
            parent_title = top_match.group(1).strip()
            parent_id = top_match.group(2).strip()
            current_parent_key = _norm(parent_title)
            all_titles[current_parent_key] = parent_id
            parent_has_start_step.setdefault(current_parent_key, False)
            continue

        sub_match = sub_pattern.match(line)
        if sub_match:
            sub_title = sub_match.group(1).strip()
            sub_id = sub_match.group(2).strip()
            all_titles[_norm(sub_title)] = sub_id
            if current_parent_key and _norm(sub_title).startswith(_norm("START STEP (2m):")):
                parent_has_start_step[current_parent_key] = True

    return all_titles, parent_has_start_step


def _parse_created_task_id(text: str) -> Optional[str]:
    match = re.search(r"\bID:\s*([A-Za-z0-9_\-]+)", text)
    if match:
        return match.group(1).strip()
    return None


def _ensure_task_list(base_url: str, user_email: str, title: str) -> str:
    data = _call_tool(
        base_url,
        "google-workspace",
        "list_task_lists",
        {"user_google_email": user_email},
    )
    listing = _extract_result_text(data)
    lists = _parse_task_list_ids(listing)
    if title in lists:
        return lists[title]

    created = _call_tool(
        base_url,
        "google-workspace",
        "create_task_list",
        {"user_google_email": user_email, "title": title},
    )
    created_text = _extract_result_text(created)
    new_id = _parse_created_task_id(created_text)
    if new_id:
        return new_id

    # Fallback re-list for eventual consistency.
    data = _call_tool(
        base_url,
        "google-workspace",
        "list_task_lists",
        {"user_google_email": user_email},
    )
    listing = _extract_result_text(data)
    lists = _parse_task_list_ids(listing)
    if title in lists:
        return lists[title]

    raise RuntimeError(f"Unable to create/find task list '{title}'")


def _fetch_existing_titles(base_url: str, user_email: str, task_list_id: str) -> Tuple[Dict[str, str], Dict[str, bool]]:
    data = _call_tool(
        base_url,
        "google-workspace",
        "list_tasks",
        {
            "user_google_email": user_email,
            "task_list_id": task_list_id,
            "show_completed": True,
            "show_deleted": False,
            "max_results": 200,
        },
    )
    text = _extract_result_text(data)
    return _parse_task_structure(text)


def _build_parent_title(item: BacklogItem) -> str:
    return f"[{item.priority}] {item.task}"


def _build_start_title(item: BacklogItem) -> str:
    task_title = item.task.strip()
    return f"START STEP (2m): {task_title}"


def _build_parent_notes(item: BacklogItem, due_local: dt.datetime, source_ref: str) -> str:
    slot_label = due_local.strftime("%H:%M")
    lines = [
        f"Category: {item.category_label}",
        f"Priority: {item.priority}",
        f"Start Step: {item.start_step}",
        f"Status Prompt: {item.status_prompt}",
        "Definition of Done: explicit DONE or COMPLETE confirmation.",
        "Escalation: soft -> firm -> hard (budget-aware).",
        "Quiet Hours: 23:00-07:00 local unless hard constraint.",
        "Week1 Scheduling Mode: structured_backlog",
        f"Week1 Focus Slot: {slot_label}",
        f"Scheduled Window (local): {due_local.strftime('%Y-%m-%d %H:%M %Z')}",
        f"Source: {source_ref}",
    ]
    if item.notes:
        lines.append(f"Notes: {item.notes}")
    return "\n".join(lines)


def _create_task(
    base_url: str,
    user_email: str,
    task_list_id: str,
    title: str,
    notes: str,
    due_utc_iso: str,
    parent: Optional[str] = None,
) -> str:
    args: Dict[str, object] = {
        "user_google_email": user_email,
        "task_list_id": task_list_id,
        "title": title,
        "notes": notes,
        "due": due_utc_iso,
    }
    if parent:
        args["parent"] = parent

    created = _call_tool(base_url, "google-workspace", "create_task", args)
    text = _extract_result_text(created)
    task_id = _parse_created_task_id(text)
    if not task_id:
        raise RuntimeError(f"Unable to parse created task id for '{title}'")
    return task_id


def run(args: argparse.Namespace) -> int:
    seed_path = Path(args.seed_csv).expanduser().resolve() if args.seed_csv else None
    seeds = _load_seed_rows(seed_path)
    docx_path: Optional[Path] = None
    source_mode = "seed_csv"
    source_ref = str(seed_path) if seed_path else "seed_csv"

    if args.docx:
        candidate = Path(args.docx).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(f"Doc not found: {candidate}")
        docx_path = candidate
        doc_text = _read_docx_text(docx_path)
        section_lines = _extract_section_lines(doc_text)
        if not section_lines:
            raise RuntimeError("Could not find section 13.3 in the provided document")
        items = _parse_backlog(section_lines, seeds)
        source_mode = "docx"
        source_ref = str(docx_path)
    else:
        if not seeds:
            raise RuntimeError("No Week1 source material available; provide --docx or a populated --seed-csv")
        items = _build_backlog_from_seed_rows(seeds)

    if not items:
        raise RuntimeError("No Week1 backlog items could be materialized from the provided sources")

    tz = ZoneInfo(args.timezone)
    local_now = dt.datetime.now(tz)
    start_date = (local_now + dt.timedelta(days=1)).date()
    scheduled = _schedule_items(items, args.timezone, start_date)

    task_list_id = _ensure_task_list(args.base_url, args.user_email, args.task_list_title)
    existing_titles, parent_has_start_step = _fetch_existing_titles(args.base_url, args.user_email, task_list_id)

    created_parent = 0
    created_start = 0
    skipped_parent = 0
    skipped_start = 0
    created_items: List[Dict[str, str]] = []

    for sched in scheduled:
        item = sched.item
        parent_title = _build_parent_title(item)
        parent_key = _norm(parent_title)
        parent_id = existing_titles.get(parent_key)

        if parent_id:
            skipped_parent += 1
        elif args.dry_run:
            skipped_parent += 1
            parent_id = "dry-run-parent"
        else:
            due_utc = sched.due_local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            parent_notes = _build_parent_notes(item, sched.due_local, source_ref)
            parent_id = _create_task(
                args.base_url,
                args.user_email,
                task_list_id,
                parent_title,
                parent_notes,
                due_utc,
            )
            existing_titles[parent_key] = parent_id
            created_parent += 1

        start_title = _build_start_title(item)
        start_key = _norm(start_title)

        if parent_has_start_step.get(parent_key):
            skipped_start += 1
        elif args.dry_run:
            skipped_start += 1
        else:
            start_due_local = sched.due_local - dt.timedelta(minutes=15)
            start_due_utc = start_due_local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
            start_notes = (
                f"Parent Task: {parent_title}\n"
                f"Status Prompt: {item.status_prompt}\n"
                "Reply options: DONE / STARTED / SNOOZE 10 / RESCHEDULE"
            )
            start_id = _create_task(
                args.base_url,
                args.user_email,
                task_list_id,
                start_title,
                start_notes,
                start_due_utc,
                parent=parent_id,
            )
            existing_titles[start_key] = start_id
            parent_has_start_step[parent_key] = True
            created_start += 1

        created_items.append(
            {
                "task": item.task,
                "priority": item.priority,
                "category": item.category_label,
                "scheduled_local": sched.due_local.isoformat(),
                "start_step": item.start_step,
            }
        )

    report = {
        "ok": True,
        "source_mode": source_mode,
        "docx": str(docx_path) if docx_path else None,
        "seed_csv": str(seed_path) if seed_path else None,
        "task_list_title": args.task_list_title,
        "task_list_id": task_list_id,
        "parsed_items": len(items),
        "created_parent_tasks": created_parent,
        "created_start_step_subtasks": created_start,
        "skipped_existing_parent_tasks": skipped_parent,
        "skipped_existing_start_step_subtasks": skipped_start,
        "dry_run": bool(args.dry_run),
        "items": created_items,
    }

    if args.schedule_output:
        schedule_items = []
        for sched in scheduled:
            item = sched.item
            schedule_items.append(
                {
                    "parent_title": _build_parent_title(item),
                    "task": item.task,
                    "priority": item.priority,
                    "category": item.category_label,
                    "category_key": item.category_key,
                    "scheduled_local": sched.due_local.isoformat(),
                    "focus_slot": sched.due_local.strftime("%H:%M"),
                    "start_step": item.start_step,
                    "status_prompt": item.status_prompt,
                    "notes": item.notes,
                }
            )
        schedule_payload = {
            "source_mode": source_mode,
            "source_ref": source_ref,
            "timezone": args.timezone,
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
            "items": schedule_items,
        }
        schedule_path = Path(args.schedule_output).expanduser().resolve()
        schedule_path.parent.mkdir(parents=True, exist_ok=True)
        schedule_path.write_text(json.dumps(schedule_payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Week1 section 13.3 tasks into Google Tasks")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788", help="Vera API base URL")
    parser.add_argument("--user-email", default="jeffnyzio@gmail.com", help="Google Workspace user email")
    parser.add_argument("--docx", default="", help="Optional path to Vera Week1 .docx")
    parser.add_argument("--seed-csv", default="ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv", help="Optional seed CSV")
    parser.add_argument("--task-list-title", default="VERA Week1 Operating System v10", help="Target Google Task list title")
    parser.add_argument("--timezone", default="America/Chicago", help="Local timezone for scheduling")
    parser.add_argument("--dry-run", action="store_true", help="Parse and schedule only; do not create tasks")
    parser.add_argument("--output", default="tmp/audits/week1_task_import_report.json", help="Write JSON report to this path")
    parser.add_argument(
        "--schedule-output",
        default="vera_memory/week1_task_schedule.json",
        help="Write structured Week1 schedule JSON to this path",
    )

    args = parser.parse_args()
    try:
        return run(args)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP error: {exc.code} {exc.reason}\n{body}")
        return 2
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

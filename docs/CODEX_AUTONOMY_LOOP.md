# Codex Autonomy Loop

This is a machine-side control plane for ongoing Codex work between chat turns.

It is not "the model thinking in the background." It is a local runner that:

- persists a queue in `vera_memory/codex_autonomy_queue.json`
- executes due tasks on a timer
- writes audit artifacts to `tmp/audits/`
- writes execution events to `tmp/audits/codex_autonomy_loop_events.jsonl`

## Why this exists

Chat turns are not a daemon. If we want durable autonomous continuity, it has to be encoded into local processes and state.

This loop is the first version of that plumbing.

## Current default tasks

The runner seeds these tasks automatically if the queue file does not exist:

1. `watch_active_autonomy_cycle`
- captures the next new active `autonomy_cycle`
- snapshots current cadence state
- includes Week1 progress state
- includes `TASK-016` excerpt

2. `verify_week1_procurement_consistency`
- checks that `TASK-016` remains `blocked`
- checks that `procurement_packet` remains unfinished until a real completion happens

3. `ensure_week1_procurement_prerequisite`
- if `TASK-016` is still blocked and `procurement_packet` is still unfinished
- creates the missing prerequisite task once
- reuses that prerequisite on later passes instead of creating duplicates

4. `snapshot_autonomy_slo_24h`
- snapshots `/api/autonomy/slo`
- stores the `windows.last_24h` view

## Files

- Runner:
  - `scripts/codex_autonomy_runner.py`
- Installer:
  - `scripts/install_codex_autonomy_loop_timer.sh`
- Queue:
  - `vera_memory/codex_autonomy_queue.json`
- Lock:
  - `vera_memory/locks/codex_autonomy_runner.lock`
- Event log:
  - `tmp/audits/codex_autonomy_loop_events.jsonl`

## Install

```bash
./scripts/install_codex_autonomy_loop_timer.sh
```

Optional arguments:

```bash
./scripts/install_codex_autonomy_loop_timer.sh <interval_seconds> <max_tasks_per_pass>
```

Example:

```bash
./scripts/install_codex_autonomy_loop_timer.sh 60 8
```

## Manual run

```bash
.venv/bin/python scripts/codex_autonomy_runner.py --max-tasks 8
```

Initialize queue only:

```bash
.venv/bin/python scripts/codex_autonomy_runner.py --init-only
```

## Operational notes

- The runner uses a non-blocking file lock, so overlapping timer ticks do not stack.
- Task types are intentionally narrow and local-first.
- This loop is for durable probes, checks, and stateful follow-up work. It is not a shell free-for-all.

## Next expansion targets

1. add explicit repair tasks for known state drifts
2. add queue task types for bounded repo checks and report generation
3. add a small "plan file" that lets Codex seed the next machine-side actions directly

## Morning Active-Window Capture

A separate daily user timer captures the first real morning active-window autonomy cycles.

Files:
- Script:
  - `scripts/codex_morning_active_window_capture.py`
- Installer:
  - `scripts/install_codex_morning_capture_timer.sh`
- Timer:
  - `codex-morning-active-window-capture.timer`

Default schedule:
- `07:55:00` local time, daily

Purpose:
- snapshot preflight readiness/health/SLO before the morning window
- wait for the first real active `autonomy_cycle` rows
- capture the first two active cycles
- run `scripts/vera_active_window_audit.py`
- leave a single audit artifact under `tmp/audits/`

Install:
```bash
./scripts/install_codex_morning_capture_timer.sh
```

Override schedule:
```bash
./scripts/install_codex_morning_capture_timer.sh '*-*-* 07:55:00'
```

## One-Shot State-Sync Proof

Use this script when a bounded live proof has already run but you want a durable JSON artifact without relying on inline `systemd-run` shell quoting.

- Script:
  - `scripts/codex_state_sync_surface_note_proof.py`

Example:
```bash
python3 scripts/codex_state_sync_surface_note_proof.py \
  --task-id TASK-030 \
  --work-item-id awj_state_sync_surface_note_01
```

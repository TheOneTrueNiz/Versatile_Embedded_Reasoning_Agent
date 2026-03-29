# Rollout Service Runbook

## Purpose

The rollout service is Vera's bounded replay lane for explicit work items.
It is not part of the live active-window dispatcher.
It exists to:
- build a normalized rollout envelope
- execute one bounded replay lane outside live runtime control
- emit a replay trajectory artifact
- append an auditable flight-recorder ledger entry
- compare replay modes on the same explicit work item

## Phase 1 Scope

Current phase-1 runner supports:
- explicit work-jar items
- archived or pending items
- artifact-based replay scoring
- isolated executor-backed replay for `tool_choice = none`
- bounded local-action deliverable writes under `vera_memory/rollouts/<rollout_id>/`
- isolated autonomy-queue repair on a copied work jar
- isolated autonomy-queue surface snapshot capture
- isolated state-sync task/memory surface snapshot capture
- isolated Week1 ops surface snapshot capture
- isolated operator/runtime snapshot capture from the live local HTTP surfaces
- isolated copied-Week1 validation snapshot generation
- isolated copied-flight-recorder verification for the flight-ledger work item
- isolated local runtime action for improvement-archive materialization
- isolated local runtime action for improvement-archive suggestion queries
- isolated local runtime action for improvement-archive operator diagnostics
- side-by-side replay comparison across multiple modes for the same work item
- policy-variant comparison across the same replay envelope for the major local subsystems

It does not yet do:
- live MCP/tool execution inside the replay lane
- automatic promotion into live runtime state

## Entrypoint

```bash
python3 scripts/vera_rollout_run.py --item-id <work_item_id> [--include-archived] [--artifact /path/to/file] [--mode auto|artifact|executor]
```

Comparison:

```bash
python3 scripts/vera_rollout_compare.py --item-id <work_item_id> [--include-archived] --mode artifact --mode auto [--policy verified_only --policy verified_or_completed]
```

Mode semantics:
- `auto`: use isolated executor replay for `tool_choice=none`, otherwise fall back to artifact replay
- `artifact`: score the best available evidence artifact only
- `executor`: force the isolated toolless executor path

Policy semantics:
- policies are optional and executor-specific
- current queue-repair executor supports:
  - `verified_only`
  - `verified_or_completed`
- current Week1 ops-surface executor supports:
  - `strict_hold_aware`
  - `raw_schedule`
- current archive-suggestion executor supports:
  - `strict_signature`
  - `relaxed_failure_class`
- current operator/runtime snapshot executor supports:
  - `strict_operator_health`
  - `baseline_favoring_health`
- current state-sync surface executor supports:
  - `strict_note_required`
  - `verifier_state_only`
- current Week1 validation executor supports:
  - `strict_ack_required`
  - `delivery_signal_only`
- current archive operator-surface executor supports:
  - `strict_active_only`
  - `include_inactive`
- current flight-ledger verifier executor supports:
  - `rebuild_only_if_invalid`
  - `always_rebuild_copy`
- policy comparison runs the same replay envelope multiple times with different policy knobs and records a preferred policy when results tie on mechanical checks

## Outputs

Trajectory artifacts:
- `vera_memory/rollouts/<rollout_id>.json`

Executor-backed replay outputs:
- `vera_memory/rollouts/<rollout_id>/MASTER_TODO.md`
- `vera_memory/rollouts/<rollout_id>/deliverable.md`
- `vera_memory/rollouts/<rollout_id>/execution_summary.md`
- `vera_memory/rollouts/<rollout_id>/autonomy_work_jar_repaired.json` for the copied autonomy-queue repair executor
- `vera_memory/rollouts/<rollout_id>/autonomy_queue_surface_snapshot.json` for the autonomy-queue executor
- `vera_memory/rollouts/<rollout_id>/state_sync_surface_snapshot.json` for the state-sync task/memory executor
- `vera_memory/rollouts/<rollout_id>/week1_ops_surface_snapshot.json` for the Week1 ops-surface executor
- `vera_memory/rollouts/<rollout_id>/operator_runtime_snapshot.json` for the operator/runtime snapshot executor
- `vera_memory/rollouts/<rollout_id>/week1_validation_snapshot.md` for the Week1 validation executor
- `vera_memory/rollouts/<rollout_id>/ledger_verify.json` for the flight-ledger verifier executor
- `vera_memory/rollouts/<rollout_id>/ledger_rebuild.json` when the flight-ledger executor rebuilds the copied ledger
- `vera_memory/rollouts/<rollout_id>/improvement_archive.json` for the archive-materialization executor
- `vera_memory/rollouts/<rollout_id>/archive_suggestions.json` for the archive-suggestion executor
- `vera_memory/rollouts/<rollout_id>/operator_diagnostics.json` for the operator-surface executor

Flight recorder / ledger:
- `vera_memory/flight_recorder/transitions.ndjson`
- `vera_memory/flight_recorder/ledger.jsonl`

## Examples

Artifact-only replay:

```bash
python3 scripts/vera_rollout_run.py --item-id awj_flight_ledger_impl_phase1_01 --include-archived --mode artifact
```

Executor-backed replay for a toolless work item:

```bash
python3 scripts/vera_rollout_run.py --item-id awj_flight_ledger_impl_phase1_01 --include-archived --mode auto
```

Executor-backed replay for isolated improvement-archive materialization:

```bash
python3 scripts/vera_rollout_run.py --item-id awj_improvement_archive_impl_phase1_01 --include-archived --mode auto
```

Executor-backed replay for isolated copied-ledger verification:

```bash
python3 scripts/vera_rollout_run.py --item-id awj_flight_ledger_impl_phase1_01 --include-archived --mode auto
```

Executor-backed replay for an isolated Week1 validation snapshot:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `signal summary`
  - `likely weak spots`
  - `top 3 week2 tuning recommendations`
- use an older Week1 validation snapshot as `metadata.artifact` if you want an artifact-vs-auto comparison
- compare `strict_ack_required` vs `delivery_signal_only` when you want to test whether ACK evidence is treated as a hard signal requirement

Executor-backed replay for an isolated operator/runtime snapshot:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `health`
  - `readiness`
  - `operator baseline`
  - `tool diagnostics`
- set `metadata.base_url` when you want to point at a non-default local API base URL

Executor-backed replay for an isolated state-sync task/memory surface snapshot:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `verification hook`
  - `repair write`
  - `follow-up replay`
- set `metadata.task_id` when you want to target a specific state-sync task marker in `vera_memory/MASTER_TODO.md`
- compare `strict_note_required` vs `verifier_state_only` when you want to test whether a verifier event can stand in for the missing task-surface note

Executor-backed replay for an isolated Week1 ops surface snapshot:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `focus lane`
  - `human followthrough holds`
  - `next focus slots`
- this executor prefers the canonical runtime Week1 files over the temporary probe jar so it snapshots the real Week1 ops surface

Executor-backed replay for an isolated autonomy queue surface snapshot:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `pending items`
  - `archived items`
  - `queue health`
- this executor prefers the canonical runtime work jar and verifier state over the temporary probe jar so it snapshots the real queue surface

Executor-backed replay for an isolated copied autonomy queue repair:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `verified complete`
  - `archived items`
  - `queue repair`
- this executor repairs a copied work jar only
- by default it mutates a copied canonical runtime queue using canonical verifier state
- for a stronger proof, seed an isolated copied queue with one verified completed item and compare `artifact` vs `auto`

Executor-backed replay for an isolated archive operator surface:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `operator diagnostics`
  - `archive suggestions`
  - `suggest_only`
- compare `strict_active_only` vs `include_inactive` when you want to test whether inactive archive rows should remain visible to the operator

Executor-backed replay for an isolated copied flight-ledger verifier:
- use a temporary work-jar payload with `tool_choice=none`
- required markers:
  - `lazy genesis`
  - `verifier script`
  - `focused tests`
- compare `rebuild_only_if_invalid` vs `always_rebuild_copy` when you want to test conservative repair on the same copied recorder state

## What To Inspect

In the rollout artifact:
- `envelope`
- `trajectory.kind`
- `trajectory.steps`
- `score.passed_checks`
- `score.failed_checks`
- `score.artifact_path`
- `executor_result` if executor-backed mode was used

In the rollout directory:
- `MASTER_TODO.md`
- `deliverable.md`
- `execution_summary.md`
- `autonomy_work_jar_repaired.json` when the copied autonomy-queue repair executor is selected
- `autonomy_queue_surface_snapshot.json` when the autonomy-queue executor is selected
- `state_sync_surface_snapshot.json` when the state-sync task/memory executor is selected
- `week1_ops_surface_snapshot.json` when the Week1 ops-surface executor is selected
- `operator_runtime_snapshot.json` when the operator/runtime snapshot executor is selected
- `week1_validation_snapshot.md` when the Week1 validation executor is selected
- `ledger_verify.json` when the flight-ledger verifier executor is selected
- `ledger_rebuild.json` when the flight-ledger verifier executor rebuilds the copied ledger
- `improvement_archive.json` when the archive-materialization executor is selected
- `archive_suggestions.json` when the archive-suggestion executor is selected
- `operator_diagnostics.json` when the operator-surface executor is selected

In the flight recorder:
- action type `rollout_replay`
- resulting ledger continuity via `scripts/vera_flight_ledger_verify.py`

In the comparison artifact:
- `preferred_mode`
- `preferred_policy`
- `comparisons[*].mode`
- `comparisons[*].policy`
- `comparisons[*].trajectory_kind`
- `comparisons[*].executor_kind`
- `comparisons[*].artifact_path`

## Current Guardrails

- opt-in only
- bounded to one explicit work item
- isolated task file for executor-backed mode
- deliverable writes stay under the rollout directory
- no automatic live-state promotion
- no autonomous code mutation

## Operational Note

The flight ledger now refreshes the live tail under a file lock before each append.
That avoids stale `hash_prev` mismatches when multiple recorder instances or processes append to the ledger.

## Recommended Next Step

This local-subsystem comparison phase is now broad enough to stop expanding sideways.
The next step should be one of:
- cross-subsystem scoring/promotion logic over the existing replay artifacts
- or one tightly bounded live-tool replay lane outside the active-window dispatcher

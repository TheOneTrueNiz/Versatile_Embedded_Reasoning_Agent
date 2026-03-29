# VERA Operator Runbook

This is the current operator flow for this repo.

## 1) Online Setup (Optional)

Build/refresh a local wheelhouse (and seed archive) when internet is available:

```bash
./scripts/build_wheelhouse.sh
```

Configure dev secrets in OS keychain (recommended):

```bash
./scripts/vera_secret_store.sh set XAI_API_KEY "<your_key>"
```

Or migrate file-based credentials:

```bash
./scripts/vera_secret_store.sh migrate-creds "${HOME}/Documents/creds"
```

## 2) Offline Bootstrap

Point to a prepared wheelhouse/seed location and run dependency bootstrap without starting VERA:

```bash
export VERA_WHEELHOUSE_DIR=/mnt/storage/vera_wheelhouse && VERA_NO_RUN=1 ./scripts/run_vera.sh
```

## 3) Normal Runtime Entry

```bash
./scripts/run_vera.sh
```

Dry-check equivalent (bootstrap only):

```bash
VERA_NO_RUN=1 ./scripts/run_vera.sh
```

## 4) API / Monolithic Entrypoints

API check:

```bash
.venv/bin/python run_vera_api.py --help
```

Monolithic check:

```bash
python3 run_vera_monolithic.py --help
```

Local release gate (writes manifest/logs under `tmp/release_gate/<timestamp>/`):

```bash
./scripts/vera_release_gate_local.py
```

Alive protocol gate (writes JSON/MD under `tmp/audits/<timestamp>/`):

```bash
.venv/bin/python scripts/vera_alive_protocol_gate.py
```

## 5) API + UI + MCP Stack

Primary stack launcher:

```bash
./scripts/run_vera_full.sh --diag-only
```

Notes:
- `scripts/run_vera_full.sh` is the full-stack orchestrator (API + UI + MCP + optional SearxNG).
- For live launch, run without `--diag-only`.

## 5.1) Doctor/Professor Guided Learning

Run the Vera-side guided curriculum session:

```bash
.venv/bin/python scripts/vera_guided_learning_curriculum.py --base-url http://127.0.0.1:8788
```

Run CI gate with guided curriculum included:

```bash
.venv/bin/python scripts/vera_doctor_professor_ci_gate.py --base-url http://127.0.0.1:8788 --run-guided-learning
```

Curriculum assets:
- `config/doctor_professor/vera_guided_learning_curriculum.json`
- `config/doctor_professor/vera_professor_protocol.md`

## 6) Manual Halt Sentinel

- Path: `vera_memory/manual_halt`
- Behavior: launchers exit intentionally while this file exists (including `./scripts/run_vera_full.sh`).
- Action to resume:

```bash
rm -f vera_memory/manual_halt
```

- This is safe/intentional ops control.

## 7) Bootstrap / Restore Behavior

`scripts/run_vera.sh` core behavior:
- Uses `requirements.txt` hash stamping (`.venv/.deps_core_sha256`) to detect drift.
- Uses wheelhouse only if at least one `*.whl` is present.
- Falls back to `venv_seed.tar.gz` restore when needed.
- Seed restore is rollback-safe:
  - existing `.venv` is renamed to `.venv__pre_seed_<timestamp>`
  - failed restore rolls the original `.venv` back

Retention controls:
- `VERA_PRESEED_BACKUPS_TO_KEEP` (default `1`)
- `VERA_KEEP_ALL_PRESEED_BACKUPS=1` (disable pruning)

## 8) Non-Git Runtime/Archive Areas

- `dev/` (archival only; not current guidance)
- `.venv/`
- `wheelhouse/`

## 9) Secrets Runtime Behavior

- `scripts/run_vera.sh` and `scripts/run_vera_full.sh` auto-load secrets from OS keychain by default.
- Disable keychain autoload with `VERA_KEYCHAIN_LOAD=0`.
- Legacy file-based credential fallback remains available for migration scenarios.
- Preferred production pattern is environment/secret-manager injection.

## 10) Memory Footprint Budget

- Default persistent memory budget is **1024 MB** via `VERA_MEMORY_MAX_FOOTPRINT_MB=1024` when unset.
- Override via env:

```bash
export VERA_MEMORY_MAX_FOOTPRINT_MB=1536
```

- Override via CLI:
  - `./scripts/run_vera.sh --memory-footprint-mb 1536`
  - `.venv/bin/python run_vera_api.py --memory-footprint-mb 1536`
  - `python3 run_vera_monolithic.py --memory-footprint-mb 1536`
  - `./scripts/run_vera_full.sh --memory-footprint-mb 1536`

- Disable budget checks with `VERA_MEMORY_MAX_FOOTPRINT_MB=0`.
- Runtime telemetry is exposed at `/api/memory/stats` under `disk_usage`.

## 11) Proactive + Continuity Defaults

- Proactive execution defaults to enabled unless explicitly disabled:
  - `VERA_PROACTIVE_EXECUTION=1` (default)
  - `VERA_CALENDAR_PROACTIVE=1` (default)
- `scripts/run_vera_full.sh` auto-seeds `VERA_DEFAULT_SESSION_LINK_ID` from onboarded workspace email when unset (single-owner continuity default).

Override examples:

```bash
export VERA_PROACTIVE_EXECUTION=0
export VERA_CALENDAR_PROACTIVE=0
export VERA_DEFAULT_SESSION_LINK_ID="my-link-id"
```

Cross-channel continuity default:
- `config/channels.json` enables two channels out of the box:
  - `api`
  - `local-loopback` (deterministic local channel used for continuity validation)
- Loopback endpoints:
  - `POST /api/channels/local/inbound`
  - `GET /api/channels/local/outbox`
  - `POST /api/channels/local/outbox/clear`
- Note: tray-managed runtime must be cycled once after updates for channel config/code changes to take effect.

## 12) Preferences API Endpoints

Primary:
- `GET /api/preferences/core-identity`
- `POST /api/preferences/core-identity/refresh`
- `POST /api/preferences/core-identity/revert`
- `GET /api/preferences/partner-model`

Compatibility aliases:
- `GET /api/preferences/identity`
- `GET /api/preferences/promote`
- `POST /api/preferences/promote`

## 13) Push Reach-Out Acknowledgement (Tier-3)

- Ack ingest endpoint: `POST /api/push/native/ack`
- Required payload field: `run_id`
- Optional fields: `ack_type`, `channel`, `source`, `event_type`, `device_id`, `metadata`
- Default ack log path: `vera_memory/push_user_ack.jsonl`
  - Override with `VERA_PUSH_ACK_LOG_PATH=/path/to/file.jsonl`
- Native register proxy ack:
  - When a device re-registers shortly after a reach-out, server can infer a proxy ack.
  - Window env: `VERA_PUSH_REGISTER_ACK_WINDOW_SECONDS` (default `180`)
  - Sources written: `native_register_explicit` (if run_id passed), `native_register_proxy` (time-window inference)

Strict proactive soak (tier-3 required) reads the ack log by default:

```bash
.venv/bin/python scripts/vera_proactive_soak_runner.py \
  --base-url http://127.0.0.1:8788 \
  --duration-minutes 120 \
  --require-user-ack
```

For browser push, the service worker posts click/open acknowledgements automatically when push payload includes `run_id`.

## 14) Week1 Continuous Cadence Executor

- Runtime owner: `src/core/runtime/proactive_manager.py`
- Executor script: `scripts/vera_week1_executor.py`
- Cadence model: timer-driven tick under autonomy cadence (not startup-only)
- State and evidence:
  - `vera_memory/week1_executor_state.json`
  - `vera_memory/week1_executor_events.jsonl`

Default behavior:
- Daily Week1 task import/reconciliation through `scripts/import_week1_operating_tasks.py`
- Public-clone fallback:
  - if no private Week1 `.docx` resolves, the importer now uses the shipped seed backlog at `ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv`
  - `scripts/run_vera.sh` and `scripts/run_vera_full.sh` print the detected Week1 source at startup
- Due-time anchors:
  - 07:30 Isaac Learning Boost (email)
  - 08:00 wake call (+ push fallback)
  - 08:05 daily sweep (push)
  - 08:10 morning merge (push)
  - 12:00 midday check (push)
  - 12:05 low-dopamine start step (push)
  - 15:00 follow-up factory (push)
  - 20:30 closeout (push)
  - 20:45 tomorrow brief (email)

Autonomy toggles:
- `VERA_AUTONOMY_WEEK1_EXECUTOR_ENABLED=1` (default)
- `VERA_AUTONOMY_WEEK1_EXECUTOR_COOLDOWN_SECONDS=900` (default)
- `VERA_AUTONOMY_WEEK1_EXECUTOR_TIMEOUT_SECONDS=600` (default)
- `VERA_WEEK1_EMAIL_MODE=send|draft` (default `send`)

Manual tick:

```bash
.venv/bin/python scripts/vera_week1_executor.py --vera-root . --base-url http://127.0.0.1:8788
```

Manual dry-run tick (no side effects, no state writes):

```bash
.venv/bin/python scripts/vera_week1_executor.py --vera-root . --base-url http://127.0.0.1:8788 --dry-run --email-mode draft
```

CSV-only import dry-run:

```bash
PYTHONPATH=src .venv/bin/python scripts/import_week1_operating_tasks.py --seed-csv ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv --dry-run
```

## 15) Autonomy Runplane Ops Surface

State/metrics APIs:
- `GET /api/autonomy/jobs`
- `GET /api/autonomy/runs`
- `GET /api/autonomy/dead-letter`
- `GET /api/autonomy/slo`

Operator controls:
- `POST /api/autonomy/dead-letter/replay` (requires `run_id` or `job_id`)
- `POST /api/autonomy/runs/mark` (requires `run_id` + `status`)
  - common statuses: `escalated`, `closed`

Reach-out delivery and ACK:
- `innerlife.reached_out` now records a delivery run in runplane.
- Push ACK (`/api/push/native/ack`) can resolve by external inner-life run ID alias, not only internal runplane ID.

Channel routing mode:
- `VERA_INNER_LIFE_DELIVERY_MODE=fallback` (default): stop after first successful channel.
- `VERA_INNER_LIFE_DELIVERY_MODE=broadcast`: attempt all configured channels.

Lane queue tuning:
- `VERA_PROACTIVE_LANE_QUEUE_MAX` (default `8`): max queued proactive actions per lane (`action_type:session_scope`).

Auto dead-letter replay:
- `VERA_AUTONOMY_DEAD_LETTER_AUTO_REPLAY=1` (default on)
- `VERA_AUTONOMY_DEAD_LETTER_REPLAY_MAX_PER_CYCLE=2`
- `VERA_AUTONOMY_DEAD_LETTER_REPLAY_COOLDOWN_SECONDS=1800`
- `VERA_AUTONOMY_DEAD_LETTER_MAX_REPLAYS_PER_JOB=3`
- `VERA_AUTONOMY_DEAD_LETTER_REPLAY_FAIL_ESCALATION_THRESHOLD=2`
- `VERA_AUTONOMY_DEAD_LETTER_REPLAY_ALLOW=<csv failure classes>`
  - default includes: `delivery_unroutable,stale_lane,transport_error,rate_limited,transient_timeout,executor_failure,executor_nonzero_exit`

Dead-letter replay SLO audit hooks:
- `VERA_AUTONOMY_DEAD_LETTER_SLO_MIN_SUCCESS_RATE=0.50`
- `VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_BACKLOG=20`
- `VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_CYCLE_FAILURES=3`
- `VERA_AUTONOMY_DEAD_LETTER_SLO_MAX_ESCALATED_PER_CYCLE=2`
- Audit events are appended to `vera_memory/autonomy_cadence_events.jsonl` (`type=dead_letter_replay_slo_audit`).

ACK-SLA stale delivery escalation:
- `VERA_AUTONOMY_ACK_SLA_ESCALATION_ENABLED=1`
- `VERA_AUTONOMY_ACK_SLA_SECONDS=900`
- `VERA_AUTONOMY_ACK_SLA_MAX_ESCALATIONS_PER_CYCLE=3`
- `VERA_AUTONOMY_ACK_SLA_SCAN_LIMIT=400`
- `VERA_AUTONOMY_ACK_SLA_KIND_PREFIXES=delivery`
- Cycle emits `delivery_ack_sla_scan` into `vera_memory/autonomy_cadence_events.jsonl`.

Failure-learning event log:
- `vera_memory/failure_learning_events.jsonl`

Learning-loop failure ingestion (new):
- `VERA_FAILURE_LEARNING_INGEST_ENABLED=1` (default on)
- `VERA_FAILURE_LEARNING_BATCH_MAX=250`
- Ingested by `LearningLoopManager.run_daily_learning_cycle()` as `failure_learning_ingest`.
- Progress counters in `learning_loop_state.json`:
  - `failure_learning_offset`
  - `failure_learning_processed_total`
  - `failure_learning_examples_total`
  - `failure_learning_malformed_total`

Workflow failure-risk scoring (selection hardening):
- `VERA_WORKFLOW_FAILURE_PENALTY_WEIGHT=0.25`
- `VERA_WORKFLOW_RECENT_FAILURE_WINDOW_HOURS=48`
- `VERA_WORKFLOW_FAILURE_HARD_BLOCK_THRESHOLD=0.92`
- `VERA_WORKFLOW_MAX_FAILURE_PENALTY=0.70` (LLM bridge chain acceptance gate)
- `VERA_WORKFLOW_RECOVERY_OVERRIDE_MIN_PENALTY=0.60` (when to auto-switch to recovery chain)
- These values bias workflow suggestion away from recently failing/repeatedly failing chains.
- Runtime telemetry is exposed in `workflow_recording.failure_recovery_override` via last tool payload:
  - `applied`, `replayed`, `successes`, `failures`, `success_rate_pct`, `replay_rate_pct`
- Inspect with:
  - `GET /api/tools/last_payload` → `payload.workflow_recording.failure_recovery_override`

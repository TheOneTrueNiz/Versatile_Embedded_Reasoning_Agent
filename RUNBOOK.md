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

Or migrate a legacy file-based credentials directory:

```bash
./scripts/vera_secret_store.sh migrate-creds "/path/to/legacy-creds"
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

## 5.1) Guided Learning

Run the Vera-side guided curriculum session:

```bash
.venv/bin/python scripts/vera_guided_learning_curriculum.py --base-url http://127.0.0.1:8788
```

Curriculum assets:
- `config/guided_learning/vera_guided_learning_curriculum.json`
- `config/guided_learning/vera_guided_learning_protocol.md`

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
- The legacy `CREDS_DIR` location remains as a compatibility fallback.
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

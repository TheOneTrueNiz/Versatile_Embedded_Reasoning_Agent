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

## 5) API + UI + MCP Stack

Primary stack launcher:

```bash
./scripts/run_vera_full.sh --diag-only
```

Notes:
- `scripts/run_vera_full.sh` is the full-stack orchestrator (API + UI + MCP + optional SearxNG).
- For live launch, run without `--diag-only`.

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
- `~/Documents/creds` remains as compatibility fallback.
- Preferred production pattern is environment/secret-manager injection.

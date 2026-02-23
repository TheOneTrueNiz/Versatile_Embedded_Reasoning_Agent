# VERA 2.0

VERA is a local-first agent runtime with:
- CLI runtime (`run_vera.py`)
- OpenAI-compatible API server (`run_vera_api.py`)
- Optional UI (`ui/minimal-chat/dist`)
- MCP tool orchestration (`mcp_server_and_tools/`, `scripts/run_*_mcp.sh`)

## Operator Entry Points

- Online setup (optional): `./scripts/build_wheelhouse.sh`
- One-time dev secret migration (optional): `./scripts/vera_secret_store.sh migrate-creds "${HOME}/Documents/creds"`
- Offline bootstrap: `export VERA_WHEELHOUSE_DIR=/mnt/storage/vera_wheelhouse && VERA_NO_RUN=1 ./scripts/run_vera.sh`
- Normal run: `./scripts/run_vera.sh`
- Local release gate: `./scripts/vera_release_gate_local.py`
- Monolithic check: `python3 run_vera_monolithic.py --help`
- Guided learning drill: `.venv/bin/python scripts/vera_guided_learning_curriculum.py --base-url http://127.0.0.1:8788`

## Quickstart

1. Configure secrets (recommended: OS keychain):

```bash
./scripts/vera_secret_store.sh set XAI_API_KEY "<your_key>"
```

Or migrate existing file-based secrets:

```bash
./scripts/vera_secret_store.sh migrate-creds "${HOME}/Documents/creds"
```

2. Smoke-check bootstrap without launching runtime:

```bash
VERA_NO_RUN=1 ./scripts/run_vera.sh
```

3. Start CLI runtime:

```bash
./scripts/run_vera.sh
```

4. API dry-check:

```bash
.venv/bin/python run_vera_api.py --help
```

## Secret Management (Dev + Prod)

- Dev default: use OS keychain via `scripts/vera_secret_store.sh` (`secret-tool` on Linux, `security` on macOS).
- Launchers auto-load keychain secrets when available (`VERA_KEYCHAIN_LOAD=1`, default).
- File-based `~/Documents/creds` is still supported as fallback for compatibility.
- Disable keychain loading if needed: `VERA_KEYCHAIN_LOAD=0`.
- Production: inject secrets through environment/secret manager; do not store runtime secrets in repo files.

## API + UI + MCP

- Full-stack launcher lives at `scripts/run_vera_full.sh` (API + UI + MCP + optional SearxNG).
- Safe preflight command:

```bash
./scripts/run_vera_full.sh --diag-only
```

- API + UI launcher: `scripts/run_vera_gui.sh`
- MCP hub wrapper: `scripts/run_mcp_hub.sh` (requires `MCP_HUB_COMMAND` to be set)

## Guided Learning Harness

- Vera-side guided curriculum runner:

```bash
.venv/bin/python scripts/vera_guided_learning_curriculum.py --base-url http://127.0.0.1:8788
```

- Doctor/Professor CI gate with guided curriculum enabled:

```bash
.venv/bin/python scripts/vera_doctor_professor_ci_gate.py --base-url http://127.0.0.1:8788 --run-guided-learning
```

- Curriculum and protocol files:
  - `config/doctor_professor/vera_guided_learning_curriculum.json`
  - `config/doctor_professor/vera_professor_protocol.md`

## Manual Halt Sentinel

- Path: `vera_memory/manual_halt`
- Behavior: launchers exit intentionally while this file exists (including `./scripts/run_vera_full.sh`).
- Action: remove the file to resume normal starts:

```bash
rm -f vera_memory/manual_halt
```

- Purpose: safe/intentional operator control to pause startup.

## Environment Variables (Common)

- `XAI_API_KEY`: LLM key for runtime/API calls
- `VERA_NO_RUN=1`: bootstrap dependencies, then exit
- `VERA_FORCE_INSTALL=1`: force dependency install path
- `VERA_WHEELHOUSE_DIR`: external wheelhouse location
- `VERA_MEMVID_ENABLED=1`: opt-in memvid experimental path
- `VERA_PRESEED_BACKUPS_TO_KEEP` (default `1`): pre-seed backup retention
- `VERA_KEEP_ALL_PRESEED_BACKUPS=1`: disable pre-seed backup pruning

## Repository Scope

Included in git (production-required):
- Runtime and orchestration code in `src/` and entrypoints (`run_vera.py`, `run_vera_api.py`, `run_vera_monolithic.py`)
- Launch and ops scripts in `scripts/`
- Runtime configuration in `config/` and `mcp_servers.json`
- UI source in `ui/minimal-chat/` (build artifacts generated locally)
- MCP integration/tooling in `mcp_server_and_tools/` used by launchers

Excluded / expected external:
- `.venv/`, `wheelhouse/`, and `dev/` (gitignored)
- Secrets in OS keychain (recommended) and/or credentials in `~/Documents/creds` (fallback)
- Runtime/generated state (`logs/`, `tmp/`, `vera_memory/`, `vera_checkpoints/`, `rollback_storage/`)
- Archived/non-production artifacts (kept under `dev/production_prune_*` if retained)

## Docs

- `RUNBOOK.md` for operator commands and runtime flow
- `OFFLINE_BOOTSTRAP.md` for offline/bootstrap behavior details
- `SECRETS.md` for keychain and credential migration workflows

## Contributors

- Niz Nyzio
- Claude
- Codex (OpenAI)

## Ops Changes (2026-02-18)

- Non-production repo content was archived into `dev/production_prune_*`.
- Offline bootstrap added (`wheelhouse/` + `.venv` seed fallback).
- `run_vera.sh` hardened with:
  - `requirements.txt` hash stamp checks (`.venv/.deps_core_sha256`)
  - safe seed restore with rollback on failure
  - configurable pre-seed backup retention

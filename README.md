# VERA 2.0

VERA is a local-first agent runtime with:
- CLI runtime (`run_vera.py`)
- OpenAI-compatible API server (`run_vera_api.py`)
- Optional UI (`ui/minimal-chat/dist`)
- MCP tool orchestration (`mcp_server_and_tools/`, `scripts/run_*_mcp.sh`)

## Operator Entry Points

- Online setup (optional): `./scripts/build_wheelhouse.sh`
- Offline bootstrap: `export VERA_WHEELHOUSE_DIR=/mnt/storage/vera_wheelhouse && VERA_NO_RUN=1 ./scripts/run_vera.sh`
- Normal run: `./scripts/run_vera.sh`
- Monolithic check: `python3 run_vera_monolithic.py --help`

## Quickstart

1. Set credentials (expected outside repo): `~/Documents/creds`
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

## API + UI + MCP

- Full-stack launcher lives at `scripts/run_vera_full.sh` (API + UI + MCP + optional SearxNG).
- Safe preflight command:

```bash
./scripts/run_vera_full.sh --diag-only
```

- API + UI launcher: `scripts/run_vera_gui.sh`
- MCP hub wrapper: `scripts/run_mcp_hub.sh` (requires `MCP_HUB_COMMAND` to be set)

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
- Credentials in `~/Documents/creds`
- Runtime/generated state (`logs/`, `tmp/`, `vera_memory/`, `vera_checkpoints/`, `rollback_storage/`)
- Archived/non-production artifacts (kept under `dev/production_prune_*` if retained)

## Docs

- `RUNBOOK.md` for operator commands and runtime flow
- `OFFLINE_BOOTSTRAP.md` for offline/bootstrap behavior details

## Ops Changes (2026-02-18)

- Non-production repo content was archived into `dev/production_prune_*`.
- Offline bootstrap added (`wheelhouse/` + `.venv` seed fallback).
- `run_vera.sh` hardened with:
  - `requirements.txt` hash stamp checks (`.venv/.deps_core_sha256`)
  - safe seed restore with rollback on failure
  - configurable pre-seed backup retention

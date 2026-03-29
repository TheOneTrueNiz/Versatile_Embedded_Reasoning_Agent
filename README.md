# VERA 2.0

VERA is a local-first agent runtime with:
- an OpenAI-compatible HTTP API
- MCP tool orchestration
- proactive/autonomy runtime control
- operator diagnostics and runtime observability
- optional UI and supporting local services

## Repo Layout
- `src/`: runtime, orchestration, API, planning, observability, tests
- `scripts/`: launchers, diagnostics, audits, operator helpers
- `config/`: runtime configuration and prompt/persona assets
- `services/`: local supporting services
- `mcp_server_and_tools/`: MCP tools and local MCP integrations
- `ui/`: optional frontend
- `docs/`: active reference docs
- `ops/`: operator procedures and seeded operational material
- `old/`: archived legacy/project-context material not needed in the root harness surface

## Primary Entrypoints
- `./scripts/run_vera_full.sh --logging`
- `./scripts/restart_vera.sh --no-searxng`
- `./.venv/bin/python run_vera_api.py --host 127.0.0.1 --port 8788 --logging`

## Public Week1 Bootstrap
- The public repo ships a deterministic Week1 seed backlog at:
  - `ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv`
- A private Week1 `.docx` is optional, not required.
- Startup launchers now report which Week1 source will be used:
  - private `.docx`, if found
  - otherwise the shipped seed CSV fallback
- CSV-only dry-run import:

```bash
PYTHONPATH=src .venv/bin/python scripts/import_week1_operating_tasks.py \
  --seed-csv ops/week1/WEEK1_SEEDED_TASK_BACKLOG.csv \
  --dry-run
```

- Full Week1 executor dry-run:

```bash
PYTHONPATH=src .venv/bin/python scripts/vera_week1_executor.py \
  --vera-root . \
  --base-url http://127.0.0.1:8788 \
  --dry-run
```

## Operator Docs
- `RUNBOOK.md`
- `OFFLINE_BOOTSTRAP.md`
- `docs/SECRETS.md`
- `docs/PUBLIC_EVAL_SPEC.md`

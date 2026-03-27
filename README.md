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

## Operator Docs
- `RUNBOOK.md`
- `OFFLINE_BOOTSTRAP.md`
- `docs/SECRETS.md`
- `docs/PUBLIC_EVAL_SPEC.md`

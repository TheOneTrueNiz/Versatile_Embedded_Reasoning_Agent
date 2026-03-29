<img width="1200" height="400" alt="Vera" src="https://github.com/user-attachments/assets/80e1ed77-f727-4305-9670-71a04a9bd0f0" />

# Versatile Embedded Reasoning Agent (VERA)

VERA is a local-first agent harness for running a persistent, tool-using reasoning system on your own hardware.

This is not a thin chat wrapper. It is the full integrated runtime: model-facing API, autonomy loop, operator surfaces, UI, bundled MCP tooling, local state, audits, and recovery rails needed to run an embedded agent stack end to end.

## Why This Repo Exists

Most "agent" projects stop at one of these layers:
- a prompt
- a chat UI
- a stateless API wrapper
- a tool-calling demo

VERA is trying to solve the harder systems problem: how to run an agent continuously on real hardware without losing track of state, flooding the user with noise, or letting finished work silently drift out of sync with the rest of the system.

That means VERA focuses on runtime engineering, not just prompting:
- persistent local runtime instead of one-shot request handling
- bounded autonomy with active/idle cadence and workflow caps
- tool routing that constrains and shortlists MCP surfaces instead of exposing everything blindly
- verifier and state-sync rails so task state, surfaced state, and archive state stay aligned
- operator-visible diagnostics so current health is separated from stale historical baggage
- local auditability, restart hygiene, and recovery tooling

## What Is Working Today

VERA is already a serious local harness, not a concept stub.

Working on the current baseline:
- OpenAI-compatible HTTP API for model-facing integration
- integrated MCP orchestration across bundled servers and local tool wrappers
- bounded autonomy runtime with active/idle windows, workflow caps, and direct-workflow rails for explicit queued work
- operator surfaces for readiness, health, tool payload inspection, autonomy SLO, and operator baseline
- state-sync verifier that catches and repairs post-completion drift
- hash-chained flight ledger for append-only runtime auditability
- deterministic restart/cleanup path for bringing the stack back to a known-good state
- standalone publication of selected first-party MCP tools while keeping this monorepo as the integrated system of record

## Current Development State

Current status: **controlled live-testing baseline**.

That means:
- the runtime is stable enough for real local testing on your own hardware
- recent rolling windows are being used as the primary operator health view
- autonomy is no longer blocked on the major reliability issues that previously caused repeated false failures or surface churn

Recent completed runtime work includes:
- truthful autonomy SLO and operator-baseline surfaces
- elimination of stale workflow debris from the actionable surface
- direct execution path for explicit queued autonomy work without reflection dependence
- TaskStateSyncMonitor for recurring post-completion drift
- Week1 CSV-only public bootstrap path instead of private-docx dependency
- Week1 validation monitor rail driven by recent executor evidence and ACK data
- MCP shortlist control improvements for calendar, local-memory, and web-research routing

## What Still Needs Work

VERA is not being presented as finished or production-hardened for every environment.

Still in active development:
- broader deterministic actionable surfaces beyond Week1 and manually queued work
- more live proofs for newly added monitor rails as they roll into the runtime
- continued tool-routing quality improvements across broader query families
- stronger first-clone onboarding and platform-specific bootstrap hardening
- ongoing curation of bundled MCP servers and standalone MCP repo boundaries

High-risk or credential-heavy components remain intentionally conservative:
- Google Workspace MCPs stay integrated here, not published as separate standalone repos
- local secrets, memory, ledgers, audits, and runtime state are kept out of the public push surface

## What Makes VERA Different

If you want a full local agent harness rather than a demo shell, these are the parts that matter.

VERA includes:
- autonomy rails with bounded execution and cooldown logic
- workflow-cap and reserve logic so the runtime does not burn itself down in one window
- improvement archive and work-jar primitives for iterative, research-backed runtime growth
- state-sync verification and monitor rails for recurring mismatch detection
- operator telemetry that distinguishes clean current behavior from polluted lifetime history
- bundled tool surface plus standalone MCP repos for users who want individual tools without the full harness

## System Components

- `src/`
  - core runtime, orchestration, API server, planning, observability, tests
- `scripts/`
  - launchers, restart helpers, audits, diagnostics, operator utilities
- `config/`
  - runtime configuration, prompt assets, guided-learning and persona/config surfaces
- `services/`
  - supporting local services used by the harness
- `mcp_server_and_tools/`
  - bundled MCP servers, wrappers, and local tool integrations used by VERA
- `ui/`
  - optional frontend surfaces
- `docs/`
  - active documentation, design notes, operator-facing references
- `old/`
  - archived legacy/project-context material intentionally kept out of the root working surface

## Bundled MCP / Tooling Surface

This monorepo intentionally keeps the integrated tool surface with the harness so a single checkout can stand up the system.

Included here are:
- bundled MCP servers used directly by VERA
- local wrappers around selected tools and services
- upstream-derived forks that remain part of the integrated harness

Selected MCP tools are also published as standalone repos for users who want the tool without the full VERA harness:
- [`mcp-time-tool`](https://github.com/TheOneTrueNiz/mcp-time-tool)
- [`mcp-calculator-tool`](https://github.com/TheOneTrueNiz/mcp-calculator-tool)
- [`mcp-grokipedia-tool`](https://github.com/TheOneTrueNiz/mcp-grokipedia-tool)
- [`mcp-brave_search_tool`](https://github.com/TheOneTrueNiz/mcp-brave_search_tool)
- [`mcp_pdf_reader`](https://github.com/TheOneTrueNiz/mcp_pdf_reader)
- [`wikipedia-mcp`](https://github.com/TheOneTrueNiz/wikipedia-mcp)
- [`memvid`](https://github.com/TheOneTrueNiz/memvid)

The main VERA repo remains the integrated system of record.

## Quick Start

### 1. Create the Python environment

```bash
./scripts/setup_environment.sh venv
```

### 2. Configure secrets

Recommended: store model/provider secrets in the OS keychain.

```bash
./scripts/vera_secret_store.sh set XAI_API_KEY "<your_key>"
```

Legacy migration path:

```bash
./scripts/vera_secret_store.sh migrate-creds "/path/to/legacy-creds"
```

### 3. Bootstrap without launching

```bash
VERA_NO_RUN=1 ./scripts/run_vera.sh
```

### 4. Launch the full stack

```bash
./scripts/run_vera_full.sh --logging
```

### 5. Verify the runtime

```bash
curl -s http://127.0.0.1:8788/api/health
curl -s http://127.0.0.1:8788/api/readiness
```

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

## Primary Entrypoints

- full launcher:
  - `./scripts/run_vera_full.sh --logging`
- deterministic restart path:
  - `./scripts/restart_vera.sh --no-searxng`
- direct API process:
  - `./.venv/bin/python run_vera_api.py --host 127.0.0.1 --port 8788 --logging`

## Operator Surfaces

- readiness:
  - `/api/readiness`
- health:
  - `/api/health`
- autonomy SLO and operator baseline:
  - `/api/autonomy/slo`
- tool diagnostics:
  - `/api/tools/last_payload`
  - `/api/tools/status`

## Research Lineage

VERA is informed by ongoing applied agent-systems research and implementation notes.

Research repo:
- [Not Your Average Automaton Research Repo](https://github.com/TheOneTrueNiz/Not_Your_Average_Automaton_Research_Repo)

That research stream informs work on:
- autonomy architecture
- bounded self-improvement and improvement archives
- tool-routing and shortlist control
- latency and budget control
- runtime verification and auditability
- long-horizon agent operation on local hardware

## Docs To Start With

- quick operator flow:
  - `RUNBOOK.md`
- offline/bootstrap path:
  - `OFFLINE_BOOTSTRAP.md`
- secrets/runtime notes:
  - `docs/SECRETS.md`
- public evaluation scope:
  - `docs/PUBLIC_EVAL_SPEC.md`
- MCP publication strategy:
  - `docs/MCP_REPO_SPLIT_PLAN.md`

## Attribution

Primary builder:
- [TheOneTrueNiz](https://github.com/TheOneTrueNiz)

Engineering collaboration and implementation support:
- OpenAI Codex

GitHub's contributor graph reflects git authorship. This section is the explicit project-level attribution for collaborative engineering work on the harness.

## Screenshots

<img width="1272" height="1042" alt="Screenshot_20260327_000932" src="https://github.com/user-attachments/assets/b6a979fc-75d0-4b65-acbf-c6166e90ac59" />

<img width="1272" height="1042" alt="Screenshot_20260327_000948" src="https://github.com/user-attachments/assets/afc06a35-08b4-432d-adea-cc1f5fb6a303" />

<img width="1272" height="1042" alt="Screenshot_20260327_001017" src="https://github.com/user-attachments/assets/89dc59e1-8fd4-44b5-bc7b-b7b17e44877d" />

<img width="1272" height="1042" alt="Screenshot_20260327_001101" src="https://github.com/user-attachments/assets/847178a6-1f93-438b-8adf-17fb61166a17" />

<img width="1459" height="1042" alt="Screenshot_20260327_001158" src="https://github.com/user-attachments/assets/9791b958-95bf-4a44-91c9-0149040dfd03" />

<img width="1459" height="1042" alt="Screenshot_20260327_001206" src="https://github.com/user-attachments/assets/c80b0ddf-2b66-4203-a04d-f0dc40b888a1" />

<img width="1459" height="1042" alt="Screenshot_20260327_001214" src="https://github.com/user-attachments/assets/784591a1-6ae3-4693-b0bf-05d9743318f3" />

<img width="1459" height="1042" alt="Screenshot_20260327_001234" src="https://github.com/user-attachments/assets/ead67074-6dba-4009-932a-596c6d8d4f81" />

<img width="1459" height="1042" alt="Screenshot_20260327_001246" src="https://github.com/user-attachments/assets/8f2c711d-e0b1-412d-ad3d-1c4e205e17dc" />

<img width="1459" height="1042" alt="Screenshot_20260327_001254" src="https://github.com/user-attachments/assets/ac358f42-028f-4307-881d-8674295572a9" />

<img width="1459" height="1042" alt="Screenshot_20260327_001310" src="https://github.com/user-attachments/assets/8c0a5c3a-3bd2-460a-bedc-12c58a55fa6a" />

<img width="1459" height="1042" alt="Screenshot_20260327_001317" src="https://github.com/user-attachments/assets/7611798c-1347-40a5-b6cc-e1c53f3ce075" />

<img width="384" height="28" alt="Screenshot_20260327_001356" src="https://github.com/user-attachments/assets/6b164b15-4753-49b1-be35-d4be4a1f77fe" />


<img width="1200" height="400" alt="Vera" src="https://github.com/user-attachments/assets/80e1ed77-f727-4305-9670-71a04a9bd0f0" />


# Versatile Embedded Reasoning Agent (VERA)

VERA is a local-first agent harness for building and operating a persistent, tool-using reasoning system on your own hardware.

This repository is not just an API wrapper or a prompt pack. It is the integrated agent runtime: orchestration, autonomy loop, operator surfaces, UI, local services, and bundled MCP tool servers needed to run a full embedded agent stack.

## What VERA Provides

- OpenAI-compatible HTTP API for model-facing integration
- MCP orchestration layer for multi-tool routing and tool exposure control
- proactive autonomy runtime with active/idle cadence, bounded workflow execution, and operator-visible control flow
- local-first runtime design with on-device state, audits, and recovery tooling
- operator diagnostics, SLO surfaces, runplane telemetry, and readiness/health reporting
- optional UI and service components for interactive operation
- bundled MCP servers and local tool integrations so one repo can bring up the full harness

## What Makes This Different

VERA is designed as an embedded agent system, not a stateless chat shell.

The system includes:
- a persistent runtime rather than one-shot request handling
- autonomy rails with bounded execution and recovery behavior
- tool routing that constrains and shortlists MCP surfaces instead of exposing everything blindly
- verifier and state-sync mechanisms so finished work and surfaced state do not silently drift apart
- observability that distinguishes current operator health from polluted lifetime history

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

Some first-party MCP tools are also published as standalone repositories for users who want the tool without the full VERA harness:
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
- autonomy SLO / operator baseline:
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
- latency/budget control
- runtime verification and auditability
- long-horizon agent operation on local hardware

## Docs To Start With

- quick operator flow:
  - `RUNBOOK.md`
- offline/bootstrap path:
  - `OFFLINE_BOOTSTRAP.md`
- `docs/SECRETS.md`
- `docs/PUBLIC_EVAL_SPEC.md`
- `docs/MCP_REPO_SPLIT_PLAN.md`

## Current Positioning

VERA is meant for builders and operators who want a full local-first agent harness they can run, inspect, modify, and extend.

If you want a single repo that includes the harness, UI, orchestration, observability surfaces, and bundled MCP integrations, this is that repo.

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



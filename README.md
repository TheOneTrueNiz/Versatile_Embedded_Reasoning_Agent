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

- `RUNBOOK.md`
- `OFFLINE_BOOTSTRAP.md`
- `docs/SECRETS.md`
- `docs/PUBLIC_EVAL_SPEC.md`
- `docs/MCP_REPO_SPLIT_PLAN.md`

## Current Positioning

VERA is meant for builders and operators who want a full local-first agent harness they can run, inspect, modify, and extend.

If you want a single repo that includes the harness, UI, orchestration, observability surfaces, and bundled MCP integrations, this is that repo.

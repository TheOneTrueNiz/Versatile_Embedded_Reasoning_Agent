![Up<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 400" width="100%" height="100%">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0d1117" />
      <stop offset="100%" stop-color="#161b22" />
    </linearGradient>
    
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#58a6ff" />
      <stop offset="100%" stop-color="#1f6feb" />
    </linearGradient>
    
    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
      <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#30363d" stroke-width="0.5" opacity="0.4"/>
    </pattern>
    
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feGaussianBlur stdDeviation="4" result="blur" />
      <feComposite in="SourceGraphic" in2="blur" operator="over" />
    </filter>
  </defs>

  <rect width="100%" height="100%" fill="url(#bg)" />
  <rect width="100%" height="100%" fill="url(#grid)" />

  <rect x="0" y="0" width="1200" height="4" fill="url(#accent)" />

  <g transform="translate(180, 200)">
    <circle cx="0" cy="0" r="90" fill="none" stroke="#30363d" stroke-width="2" />
    <circle cx="0" cy="0" r="110" fill="none" stroke="#21262d" stroke-width="1" stroke-dasharray="4 4" />
    
    <circle cx="-45" cy="-45" r="5" fill="#8b949e" />
    <circle cx="45" cy="-45" r="5" fill="#8b949e" />
    <circle cx="-45" cy="45" r="5" fill="#8b949e" />
    <circle cx="45" cy="45" r="5" fill="#8b949e" />
    
    <circle cx="0" cy="0" r="14" fill="#58a6ff" filter="url(#glow)" />

    <path d="M -45 -45 L 0 0 L 45 -45 M -45 45 L 0 0 L 45 45" fill="none" stroke="#484f58" stroke-width="2" />
    <path d="M -45 -45 L 45 -45 L 45 45 L -45 45 Z" fill="none" stroke="#30363d" stroke-width="1" stroke-dasharray="2 2" />
  </g>

  <text x="360" y="160" font-family="system-ui, -apple-system, sans-serif" font-size="76" font-weight="800" fill="#c9d1d9" letter-spacing="4">VERA</text>
  <text x="365" y="210" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="600" fill="#8b949e" letter-spacing="2">VERSATILE EMBEDDED REASONING AGENT</text>
  
  <text x="365" y="260" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="400" fill="#8b949e">A local-first agent harness for building and operating a persistent,</text>
  <text x="365" y="285" font-family="system-ui, -apple-system, sans-serif" font-size="16" font-weight="400" fill="#8b949e">tool-using reasoning system on your own hardware.</text>

  <g transform="translate(365, 320)">
    <rect x="0" y="0" width="150" height="28" rx="14" fill="#21262d" stroke="#30363d" stroke-width="1" />
    <text x="75" y="19" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="600" fill="#58a6ff" text-anchor="middle">MCP Orchestration</text>
    
    <rect x="165" y="0" width="130" height="28" rx="14" fill="#21262d" stroke="#30363d" stroke-width="1" />
    <text x="230" y="19" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="600" fill="#3fb950" text-anchor="middle">Autonomy Loop</text>
    
    <rect x="310" y="0" width="110" height="28" rx="14" fill="#21262d" stroke="#30363d" stroke-width="1" />
    <text x="365" y="19" font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="600" fill="#d2a8ff" text-anchor="middle">Local-First</text>
  </g>
</svg>
loading gemini-svg.svg…]()


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

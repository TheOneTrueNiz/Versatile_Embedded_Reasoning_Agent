# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VERA 2.0 (Versatile Embedded Reasoning Agent) is a local-first AI agent runtime with an OpenAI-compatible HTTP API, MCP tool orchestration, multi-provider LLM fallback chains, Discord integration, and an optional Vue.js GUI. It uses xAI Grok as the primary LLM with Claude, Gemini, and OpenAI/GPT as fallback providers. Features advanced memory, safety, planning, channel abstraction, hook/event, and session management systems.

## Common Commands

### Starting VERA

```bash
# Full one-click launcher (API + UI + MCP + SearxNG)
./scripts/run_vera_full.sh --logging

# Quiet mode (fewer startup messages)
./scripts/run_vera_full.sh --logging --quiet

# Diagnostics only (verify tools and exit)
./scripts/run_vera_full.sh --diag-only

# API server only (no launcher features)
./.venv/bin/python run_vera_api.py --host 127.0.0.1 --port 8788 --logging

# Minimal API (text only, no native tools)
VERA_VOICE=0 VERA_BROWSER=0 VERA_DESKTOP=0 VERA_PDF=0 VERA_MCP_AUTOSTART=0 \
  ./.venv/bin/python run_vera_api.py --host 127.0.0.1 --port 8788 --logging
```

### Running Tests

```bash
# Python tests (pytest)
./.venv/bin/python -m pytest src/tests/ -v

# Run a single test file
./.venv/bin/python -m pytest src/tests/test_specific.py -v

# Integration smoke tests (requires running Vera)
VERA_TEST_BASE_URL=http://127.0.0.1:8788 ./.venv/bin/python -m pytest src/tests/test_integration_smoke.py -v

# Frontend unit tests
cd ui/minimal-chat && npm run test:unit

# Frontend E2E tests
cd ui/minimal-chat && npm run test:e2e
```

### Frontend Build

```bash
cd ui/minimal-chat
npm install
npm run build      # Production build -> dist/
npm run dev        # Dev server
npm run lint       # ESLint + fix
npm run format     # Prettier
```

### Diagnostics & Verification

```bash
# Health checks and tool list
./.venv/bin/python scripts/vera_diagnostics.py --tools --tools-list-names

# Full MCP tool verification
./.venv/bin/python scripts/vera_tool_verification.py --host 127.0.0.1 --port 8788

# Cleanup stale processes/ports
./scripts/cleanup_vera.sh
```

## Architecture Overview

### Request Flow

1. Client sends POST `/v1/chat/completions` (OpenAI-compatible)
2. API server (`src/api/server.py`) receives and normalizes the request
3. Bootloader (`src/core/foundation/bootloader.py`) checks for crash loops
4. VERA runtime (`src/core/runtime/vera.py`) builds the system prompt from genome config and routes to LLM
5. LLM Bridge (`src/orchestration/llm_bridge.py`) calls xAI Grok API
6. Tool router dispatches to native tools or MCP servers via `src/orchestration/mcp_orchestrator.py`
7. Results stream back through the response

### Key Directory Structure

- **`src/core/runtime/`** - Main VERA class, config, genome-based prompts
- **`src/core/foundation/`** - Bootloader, panic button, crash recovery
- **`src/api/`** - HTTP/WebSocket server, OpenAI-compatible endpoints
- **`src/orchestration/`** - LLM bridge, MCP orchestrator, tool execution
- **`src/planning/`** - Sentinel engine (DND mode), approval workflows, speculative execution
- **`src/safety/`** - Validators, internal critic, challenger agent
- **`src/quorum/`** - Mixture-of-Agents (MOA) framework for multi-agent consensus
- **`src/memory/`** & **`src/memory_system/`** - Persistence, retrieval, memvid (QR video memory)
- **`mcp_server_and_tools/`** - 34 MCP servers (brave_search, stealth-browser, x-twitter, sandbox, VoxCPM, nofx-trading, etc.)
- **`ui/minimal-chat/`** - Vue.js frontend (builds to `dist/`)
- **`config/`** - `vera_genome.json` (modular prompts), `vera_router.json`
- **`vera_memory/`** - Runtime state, MCP config (created at runtime)

### Critical Files

- `run_vera_api.py` - API entry point
- `src/core/runtime/vera.py` - Main VERA class (~185KB / 5K+ lines, the heart of the system)
- `src/core/foundation/bootloader.py` - Crash loop detection and recovery
- `src/api/server.py` - HTTP API endpoints
- `src/orchestration/mcp_orchestrator.py` - MCP server lifecycle
- `mcp_servers.json` - MCP tool configuration (root level, expanded to vera_memory/)
- `config/vera_genome.json` - Modular system prompt definition

### Safety & Observability

- **Internal critic** reviews all tool calls before execution
- **Challenger agent** provides adversarial critique
- **Two-source rule** for high-impact actions
- **Sentinel engine** manages DND mode and execution controls
- **Flight recorder** logs all operations in-memory
- **Decision ledger** tracks high-impact decisions

## Environment Variables

```bash
# Core
VERA_API_HOST=127.0.0.1
VERA_API_PORT=8788
CREDS_DIR=~/Documents/creds  # Credentials directory

# Auth & rate limiting
VERA_API_KEY=             # Bearer token for API auth (unset = auth disabled). Keyring → creds file → env var.
VERA_CORS_ORIGIN=*        # Allowed CORS origin
VERA_RATE_LIMIT=1         # Enable rate limiting (0 to disable)
VERA_RATE_LIMIT_MAX=60    # Max requests per window per IP
VERA_RATE_LIMIT_WINDOW=60.0  # Window in seconds
VERA_TRUSTED_PROXIES=        # Comma-separated IPs of trusted reverse proxies (for X-Forwarded-For)
VERA_TERMINAL_ENABLED=1      # Enable terminal WebSocket (0 to disable entirely)
VERA_SESSION_PRUNE_INTERVAL=300  # Seconds between expired session cleanup sweeps

# Feature flags
VERA_VOICE=1      # Voice I/O
VERA_BROWSER=1    # Browser automation
VERA_DESKTOP=1    # Desktop control
VERA_PDF=1        # PDF processing

# MCP/Tool control
VERA_MCP_AUTOSTART=1           # Auto-start MCP servers
VERA_TOOL_MODE=auto            # auto|all|core|none
VERA_TOOL_MAX=30               # Max tools per request

# Quorum/Swarm
VERA_QUORUM_ENABLED=0             # Enable quorum tool
VERA_SWARM_ENABLED=0              # Enable swarm tool
VERA_QUORUM_AUTO_TRIGGER=0        # Auto-consult quorum on severity >= 4

# Workflow learning
VERA_WORKFLOW_MIN_SUCCESS=2        # Min successes before suggesting workflow
VERA_WORKFLOW_MIN_RELIABILITY=0.6  # Min success rate threshold

# Self-improvement
VERA_SELF_IMPROVEMENT_AUTO=0              # Auto-trigger red-team in autonomy cadence
VERA_SELF_IMPROVEMENT_INTERVAL_HOURS=12   # Min hours between auto-triggered runs

# Debug
VERA_DEBUG=1
VERA_LOGGING=1
```

## Credentials Layout

Credentials are stored in `~/Documents/creds/` (override with `CREDS_DIR`). First-run wizard auto-launches when sentinel is missing:

```
~/Documents/creds/
  xai/xai_api                 # xAI API key (required)
  brave/brave_api             # Brave Search API key
  git/git_token               # GitHub PAT
  searxng/searxng_url         # SearxNG base URL
  google/*.json               # OAuth credentials
  google/user_email           # Primary Google email
  .vera_bootstrap_complete    # Sentinel file
```

## Development Notes

- Python 3.13 required; virtual environment at `.venv/`
- Node.js 18+ for frontend; built output served by API at root
- pytest configured with `pythonpath = . src` in `pytest.ini`
- The bootloader is critical for crash recovery - modify with caution
- MCP servers are isolated in their own directories with separate dependencies
- Logs written to `logs/` and `logs/mcp/`

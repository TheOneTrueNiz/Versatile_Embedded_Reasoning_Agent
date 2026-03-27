# MCP Repo Split Plan

This repo should only retain the Vera harness and the glue needed to run it.
First-party MCP tools that are independently reusable should be split into standalone repositories.

## Immediate Standalone Repo Candidates

These are the cleanest candidates because Vera invokes them from local code paths rather than third-party package names.

1. `mcp_server_and_tools/call-me`
2. `mcp_server_and_tools/brave_search`
3. `mcp_server_and_tools/grokipedia-mcp`
4. `mcp_server_and_tools/mcp_pdf_reader`
5. `mcp_server_and_tools/mcp_time`
6. `mcp_server_and_tools/mcp_calculator`
7. `mcp_server_and_tools/searxng`

## Split Later, After Additional Scrub

These are locally wired, but they carry more operational or credential complexity and should not be split until their repo boundaries are cleaned.

1. `mcp_server_and_tools/google_workspace_mcp`
2. `mcp_server_and_tools/call-me` companion launcher glue in `scripts/run_call_me_mcp.sh`
3. `mcp_server_and_tools/stealth-browser-mcp`
4. `mcp_server_and_tools/memvid`
5. `mcp_server_and_tools/MARM-Systems/marm-mcp-server`
6. `mcp_server_and_tools/VoxCPM`

## Do Not Treat As First-Party Standalone Repos

These are vendor integrations, external packages, or large third-party projects that Vera happens to launch.

1. `@modelcontextprotocol/server-filesystem`
2. `@modelcontextprotocol/server-github`
3. `@modelcontextprotocol/server-sequential-thinking`
4. `@browserbasehq/mcp-server-browserbase`
5. `scrapeless-mcp-server`
6. `mcp_server_and_tools/docker-android`
7. `mcp_server_and_tools/os-ai-computer-use`
8. `mcp_server_and_tools/MultiBot`
9. `mcp_server_and_tools/mcpcan`
10. `mcp_server_and_tools/nofx`
11. `mcp_server_and_tools/wikipedia-mcp`
12. `mcp_server_and_tools/mcp-server-youtube-transcript`

## Split Sequence

1. Push the cleaned Vera harness baseline first.
2. Extract the immediate standalone candidates one at a time.
3. For each extracted tool:
   - add its own `README.md`
   - add a minimal `.gitignore`
   - remove Vera-specific wrapper assumptions
   - move secrets and machine-local config to examples/templates only
   - verify it can run outside this monorepo
4. After extraction, replace monorepo-local paths with:
   - git submodules, or
   - external install instructions, or
   - separate deployment checkouts

## Push Gate For The Vera Repo

Before pushing the Vera harness repo:

1. keep `old/local/` ignored
2. keep runtime state and ledgers ignored
3. keep doctor/professor harness material out of the tracked push surface
4. keep MCP split work as later commits, not mixed into the hygiene baseline

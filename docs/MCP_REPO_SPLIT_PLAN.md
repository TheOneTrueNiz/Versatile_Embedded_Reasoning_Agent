# MCP Repo Split Plan

The integrated `Versatile_Embedded_Reasoning_Agent` repo remains the full system of record.
It should keep the harness, UI, orchestration, observability surfaces, and bundled MCP/tooling surface so one checkout can stand up the full agent stack.

Standalone MCP repos are optional distribution repos for users who want individual tools without the full VERA harness.

## Current Repo Model

1. `Versatile_Embedded_Reasoning_Agent`
   - full integrated VERA system
   - harness, UI, scripts, runtime, bundled MCP integrations
2. standalone MCP repos
   - individually reusable MCP tools
   - published separately when their boundaries are clean and their public surface is scrubbed

## Already Published Standalone / Forked Repos

Standalone first-party MCP repos:

1. `mcp-time-tool`
2. `mcp-calculator-tool`
3. `mcp-grokipedia-tool`
4. `mcp-brave_search_tool`

Upstream-derived forks refreshed and kept public as their own repos:

1. `mcp_pdf_reader`
2. `wikipedia-mcp`
3. `memvid`

## Keep In The Main VERA Repo Only

These remain bundled in the integrated harness and should not be published as standalone repos without additional scrub or architectural separation.

1. `mcp_server_and_tools/google_workspace_mcp`
2. `mcp_server_and_tools/google-workspace-mcp`
3. `mcp_server_and_tools/call-me` companion launcher/runtime glue
4. `mcp_server_and_tools/stealth-browser-mcp`
5. `mcp_server_and_tools/MARM-Systems/marm-mcp-server`
6. `mcp_server_and_tools/VoxCPM`

## Do Not Treat As First-Party Standalone Repos

These are vendor integrations, external packages, or large third-party projects that VERA happens to launch or bundle.

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
11. `mcp_server_and_tools/mcp-server-youtube-transcript`

## Publication Rule

For any MCP repo, do not publish blindly.

Before public release:

1. scan for secrets, tokens, credentials, and machine-local paths
2. remove tracked runtime artifacts, caches, and packaged build junk
3. move examples to placeholders/templates only
4. verify the repo can run outside the VERA monorepo
5. preserve upstream lineage when the tool is a fork rather than first-party code

## Push Gate For The Main VERA Repo

Before pushing the integrated VERA repo:

1. keep `old/local/` ignored
2. keep runtime state and ledgers ignored
3. keep `my_diary/` out of the tracked push surface
4. keep doctor/professor harness material out of the tracked push surface
5. remove packaged local artifacts from bundled MCP subtrees when they are not needed publicly

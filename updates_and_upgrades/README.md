# Vera Updates and Upgrades

This directory is the execution package built from:
- Current Vera 2.0 codebase (`src/`, `scripts/`)
- Research corpus in `/home/nizbot-macmini/Desktop/Research_Repo`
- Primary research index: `/home/nizbot-macmini/Desktop/Research_Repo/INDEX.md`

## What This Contains
- `VERA_2_0_BOLSTER_PLAN.md`
  - Immediate reliability and autonomy hardening for the current runtime.
- `VERA_3_0_PLUS_ROADMAP.md`
  - Architecture plan for Vera 3.0 and beyond.
- `RESEARCH_TO_CODE_CROSSWALK.md`
  - Mapping from research themes to exact Vera modules and upgrade hooks.
- `MILESTONES_AND_RELEASE_GATES.md`
  - Milestone sequence, objective gates, and pass/fail criteria.
- `V2_PATCH_QUEUE_WITH_FILE_HOOKS.md`
  - Ordered patch queue with exact function/file integration hooks.
- `REMOTE_TWO_WAY_MESSAGING_AND_VOICE_PLAN.md`
  - Vera-centric plan for remote two-way mobile messaging and voice without cognitive bypass.
- `code_examples/`
  - Implementation-ready example modules for high-value upgrades.

## Current Context Snapshot
- 24h alive-when-idle run id: read from `tmp/soak/.active_run_id`
- Runtime stability checks: `scripts/vera_soak_runner.py`
- Proactive/autonomy telemetry: `scripts/vera_proactive_soak_runner.py`

## How To Use This Package
1. Execute V2 hardening items first (`VERA_2_0_BOLSTER_PLAN.md`).
2. Keep 24h soak telemetry as baseline while patching.
3. After V2 gate pass, stage V3 modules from `VERA_3_0_PLUS_ROADMAP.md`.
4. Track every completed item against `MILESTONES_AND_RELEASE_GATES.md`.

## Ground Rules
- No speculative architecture without module-level integration targets.
- Every proposed upgrade has:
  - Exact target file(s)
  - Acceptance criteria
  - Test/validation command(s)
- Prioritize runtime behavior over paper compliance.

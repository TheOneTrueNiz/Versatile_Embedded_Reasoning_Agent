# Pickle Rick Adaptation Plan

## Purpose

This document maps the useful patterns from `pickle-rick-extension` onto Vera and the local Codex autonomy loop.

Repository reviewed:
- `https://github.com/TheOneTrueNiz/pickle-rick-extension`
- local clone: `/tmp/pickle-rick-extension`

Primary references:
- `/tmp/pickle-rick-extension/README.md`
- `/tmp/pickle-rick-extension/cli/docs/ARCHITECTURE.md`
- `/tmp/pickle-rick-extension/cli/docs/USAGE.md`

## Bottom Line

Do not integrate Pickle Rick directly into Vera.

Reasons:
- it is tightly coupled to Gemini CLI hooks and extension contracts
- it mixes useful orchestration ideas with persona and CLI/TUI concerns
- Vera already has a stronger deterministic runtime foundation than this repo

What is worth borrowing:
- explicit completion criteria
- persistent session artifacts
- resumable loop state
- deferred work queue / jar
- phase-oriented long-run execution traces

## Where It Fits

### For Codex

Useful now:
- yes

Why:
- Codex does not run persistently by itself between chat turns
- the local queue + runner + `systemd --user` timer we already installed is the correct substrate
- Pickle Rick provides product ideas for making that loop more durable and legible

### For Vera

Useful now:
- partially

Why:
- Vera needs deterministic runtime orchestration
- Pickle Rick is useful as a pattern library, not a runtime dependency
- the right move is to adapt selected behaviors natively into Vera's current control plane

## Adopt / Ignore Matrix

### Adopt Now

1. Completion promises
- Add an explicit completion contract for bounded autonomous workflows
- Vera equivalent:
  - `completion_contract`
  - `success_markers`
  - `blocking_markers`
  - `required_artifacts`

2. Durable session/work artifacts
- Persist a per-run working bundle:
  - prompt/goal
  - current stage
  - artifacts produced
  - completion decision
  - next retry or next stage

3. Resume semantics
- Allow a stalled or partially-complete autonomy workflow to resume from the last known good stage instead of regenerating work from scratch

4. Deferred work jar
- Add a first-class deferred autonomous work bucket
- This is more structured than the current ad hoc loop queue

### Adopt Later

1. Phase machine for long jobs
- PRD -> breakdown -> research -> plan -> implement -> refactor is too software-specific for Vera globally
- but a generalized phase machine is useful for long autonomous chains:
  - gather
  - normalize
  - decide
  - execute
  - verify
  - close

2. Session dashboard
- useful later for observability
- not on the critical path for runtime correctness

3. Worktree isolation
- useful for Codex/code-modifying loops
- not directly relevant to Vera’s general autonomy runtime

### Ignore / Reject

1. Persona layer
- not useful
- adds noise and risk

2. Gemini hook dependence
- wrong substrate for Vera

3. Blind self-reprompt looping
- Vera should keep deterministic budgets and runtime guards
- no recursive loop without explicit stop conditions

## Concrete Adaptation Plan

### Phase 1: Completion Contracts

Goal:
- make autonomous workflows stop for the right reason and resume for the right reason

Add:
- `completion_contract` field on autonomy workflow tasks
- examples:
  - required artifact exists
  - required task status reached
  - missing-info blocker remains unresolved

Likely files:
- `src/core/runtime/proactive_manager.py`
- `src/core/runtime/autonomy_runplane.py`
- `vera_memory/` task/workflow artifacts

Success criteria:
- workflows can report:
  - `completed`
  - `blocked`
  - `deferred`
  - `needs_retry`
  with explicit contract evaluation

### Phase 2: Deferred Work Jar

Goal:
- separate “do later” autonomous work from the immediate active-window pulse

Add:
- `vera_memory/autonomy_work_jar.json`
- each entry should include:
  - id
  - source trigger
  - objective
  - completion contract
  - next eligible run
  - retry count
  - priority
  - required dependencies

Use cases:
- work discovered during active windows but not suitable right now
- blocked work waiting on external dependencies
- non-urgent artifact completion

Success criteria:
- Vera can enqueue, revisit, and retire deferred work deterministically

### Phase 3: Durable Workflow Session Artifacts

Goal:
- every long-running autonomous effort has a single durable record

Add:
- `vera_memory/autonomy_sessions/<id>.json`

Session contents:
- objective
- stage
- source task ids
- artifacts produced
- completion contract
- last attempt outcome
- next recommended step

Success criteria:
- no more “lost middle” on multi-step autonomy work
- restart-safe resume is possible without guessing from prose

### Phase 4: Phase Machine for Long Autonomous Chains

Goal:
- stop treating multi-step work as one-shot fallback generation

Use generalized phases:
1. gather
2. normalize
3. decide
4. execute
5. verify
6. close

Success criteria:
- Vera can move a work item through explicit stages and stop/retry at the correct boundary

## Immediate Mapping To Vera

### Codex Loop

The Codex loop already provides:
- timer
- queue
- audit artifacts
- resumable task execution

Enhance it with:
- explicit completion contracts for each loop task
- a small deferred-work jar separate from the loop queue
- better “why this task stopped” reporting

### Vera Runtime

The best first insertion point is not the reflection layer.

It is:
- bounded fallback workflows
- long-running Week1/autonomy tasks
- dependency-driven blocked work

Current best target:
- Week1 procurement chain

Why:
- it already exposed:
  - prerequisites
  - blocked states
  - artifact progression
  - stale context/retry issues
- that makes it the cleanest place to pilot completion contracts and deferred work semantics

## Proposed Implementation Order

1. Add completion contracts to autonomy fallback workflows
2. Add `autonomy_work_jar.json`
3. Move blocked/deferred Week1 work into the jar instead of re-discovering it every window
4. Add durable session files for long chains
5. Extend beyond Week1 to other proactive work families

## Recommendation

Use Pickle Rick as an orchestration pattern reference, not a dependency.

For Codex:
- adopt its loop-product ideas into the existing local runner

For Vera:
- adopt completion contracts, deferred work jar semantics, and durable session artifacts

That is the part that materially strengthens Class 5 behavior.

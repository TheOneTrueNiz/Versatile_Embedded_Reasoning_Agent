# ProRL Rollout Service Adaptation For Vera

## Source

Primary reference:
- Hao Zhang et al., "ProRL Agent: Rollout-as-a-Service for RL Training of Multi-Turn LLM Agents," arXiv:2603.18815, submitted March 19, 2026.
- Abstract/source: https://arxiv.org/abs/2603.18815

The useful takeaway for Vera is not RL training itself. It is the separation of rollout orchestration from the live training or control loop, plus standardized task envelopes and replayable trajectories.

## Why This Matters For Vera

Vera already has many of the right primitives:
- bounded autonomy cadence
- structured actionable surfaces
- `autonomy_work_jar`
- state-sync verifier
- flight recorder and hash-chained ledger
- improvement archive
- operator-visible SLO and runplane state

What Vera does not yet have is a clean replay lane where a task can be executed in a standardized envelope, recorded as a trajectory, scored offline, and compared against later variants without touching the live operator runtime.

That is the part worth borrowing from ProRL Agent.

## Problem Statement

Today Vera can:
- execute live bounded autonomy work
- record audits and traces
- preserve successful interventions in an improvement archive

But Vera still lacks a first-class boundary between:
- live runtime control
- offline replay / evaluation / improvement experiments

Without that boundary, improvement work risks mixing:
- production state
- operator control flow
- evaluation traces
- experimental policy changes

That is the wrong coupling.

## Design Goal

Add a Vera rollout service boundary that can:
- accept a standardized task envelope
- execute that envelope in a bounded replay context
- emit a replayable trajectory artifact
- score the result with explicit checks
- keep live operator runtime state separate from experiment state

This is not a self-modifying engine.
It is a controlled replay and evaluation lane.

## Non-Goals

Do not do these in phase 1:
- no RL trainer integration
- no policy-gradient or reward-model training loop
- no automatic code mutation
- no direct replay against live operator state
- no unrestricted sandbox execution

## Proposed Architecture

### 1. Rollout Envelope

Create a normalized rollout request structure, for example:

```json
{
  "rollout_id": "rollout_...",
  "source": "work_jar|operator_probe|improvement_archive|manual_eval",
  "problem_signature": "week1_ops:landscaper_prep",
  "objective": "Produce a prep artifact for contacting 3-5 landscapers.",
  "context_refs": [
    "ops/week1/WEEK1_VALIDATION_METRICS.md",
    "vera_memory/week1_task_schedule.json"
  ],
  "tool_policy": {
    "tool_choice": "auto",
    "allowed_servers": ["filesystem", "google-workspace", "time"],
    "max_tool_calls": 8
  },
  "budget": {
    "max_runtime_seconds": 90,
    "max_steps": 12
  },
  "success_checks": [
    "artifact_exists",
    "required_markers_present"
  ]
}
```

This gives Vera a stable, replayable execution contract.

### 2. Rollout Runner

Add a dedicated replay runner that executes envelopes outside the normal active-window autonomy dispatcher.

Responsibilities:
- load the envelope
- create an isolated run record
- execute bounded workflow/tool logic
- record step-by-step trajectory
- emit terminal status

Phase 1 should reuse existing workflow execution logic where possible rather than inventing a second planner.

### 3. Trajectory Artifact

Persist each rollout as a structured artifact, for example under:
- `vera_memory/rollouts/<rollout_id>.json`
- optional summary mirror in `tmp/audits/`

Trajectory should include:
- normalized input envelope
- selected tools / shortlist
- tool calls and results
- reflection reason if present
- produced artifact paths
- pass/fail scoring
- runtime budget consumption

This is the replay object that later improvement logic can compare.

### 4. Scoring Layer

Scoring should be explicit and mechanical.

Phase 1 score inputs:
- required markers present
- artifact existence
- expected file writes present
- no verifier mismatch introduced
- no dead-letter / runplane failure generated

Do not use vague free-text self-grading as the primary pass/fail gate.

### 5. Separation From Live Runtime

The replay lane must not directly mutate live operational state by default.

Default rule:
- replay outputs go to experiment artifacts only
- promotion into live state requires a separate explicit step

That keeps experiments from polluting:
- active tasks
- runplane history semantics
- operator-visible current state

## Vera Mapping

### Existing pieces to reuse

- `src/core/runtime/proactive_manager.py`
  - bounded workflow execution and actionable surface logic
- `src/core/runtime/autonomy_runplane.py`
  - terminal run accounting and failure classes
- `src/core/services/flight_recorder.py`
  - trajectory-friendly append logging and ledger mirror
- `src/observability/improvement_archive.py`
  - recurring intervention suggestions
- `scripts/vera_autonomy_work_jar.py`
  - source of explicit bounded tasks

### New pieces to add

Phase 1 suggested additions:
- `src/observability/rollout_service.py`
- `scripts/vera_rollout_run.py`
- `vera_memory/rollouts/`
- `docs/ROLLOUT_SERVICE_RUNBOOK.md`

## Suggested Phase Plan

### Phase 1: Replayable Rollout Lane

Add:
- rollout envelope schema
- rollout runner CLI
- structured trajectory artifact
- mechanical scoring

Success condition:
- one bounded task can be replayed outside the live active-window loop and produce a scored artifact.

### Phase 2: Improvement Archive Integration

Add:
- archive suggestions into rollout envelopes
- compare current run vs prior successful interventions
- expose operator-visible replay summaries

Success condition:
- Vera can say which prior intervention patterns were reused and whether replay improved outcome quality.

### Phase 3: Policy Evaluation Harness

Add:
- side-by-side comparison of two routing or policy variants
- same envelope, same budget, separate trajectories
- operator-visible diff summary

Success condition:
- Vera can compare policy variants without touching live runtime behavior.

## Safety Guardrails

Required from day one:
- replay lane is opt-in, not automatic
- strict runtime budgets
- explicit allowed-tool policy per rollout
- no direct live-state promotion by default
- all replay results logged through the flight ledger
- scoring is deterministic where possible

## Why This Fits Vera

This complements work already completed:
- improvement archive gives Vera memory of successful repairs
- flight ledger gives tamper-evident rollout history
- work-jar gives explicit bounded objectives
- operator baseline and SLO surfaces keep live state honest

The missing piece is a proper replay lane. ProRL Agent is a good reference because it separates rollout orchestration from the rest of the system. That separation is the architectural lesson Vera should adopt.

## Recommended Next Step

Implement only Phase 1.

Concrete next implementation target:
- build a rollout envelope for one existing explicit work-jar task type
- run it through a standalone replay CLI
- write a trajectory artifact and ledger entry
- score it mechanically

That is enough to validate the architecture without dragging Vera into RL infrastructure or broad self-modification.

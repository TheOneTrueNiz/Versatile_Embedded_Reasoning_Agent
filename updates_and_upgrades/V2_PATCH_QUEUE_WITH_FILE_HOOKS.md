# V2 Patch Queue with File Hooks

This is a patch-order queue intended for fast, low-regression implementation.

## P1 - Checklist Chat Probe Retry Classification

### Files
- `scripts/vera_production_checklist.py`

### Hooks
- Chat probe call path in `main()` where `/v1/chat/completions` is invoked.

### Change
- Add retry wrapper for chat probe only:
  - max 2 retries
  - short jitter
  - classify `transient_timeout` separately

### Done When
- Single transient timeout does not fail entire cycle without retry evidence.

## P2 - Budget Guard Explainability Payload

### Files
- `src/observability/self_improvement_budget.py`
- `src/core/runtime/proactive_manager.py`
- `src/api/server.py`

### Hooks
- `SelfImprovementBudget.check()`
- `ProactiveManager._can_spend()`
- innerlife/autonomy status serialization

### Change
- Return reason with counters and limits, e.g. `daily_call_budget_exceeded(24/24)`.
- Surface snapshot in API status for audit.

### Done When
- Every budget guard reason is directly auditable from status API.

## P3 - Failure Trajectory Dataset Path

### Files
- `src/core/services/flight_recorder.py`
- `src/learning/learning_loop_manager.py`

### Hooks
- `FlightRecorder.record_tool_call()` output schema
- Learning loop extraction stage before distillation

### Change
- Emit failure examples with:
  - failed tool
  - error class
  - fallback used
  - final result
- Persist in `vera_memory/training_examples/failure_examples.jsonl`

### Done When
- Failure examples are consumed by learning loop metrics.

## P4 - Workflow Quarantine Expansion

### Files
- `src/learning/learning_loop_manager.py`
- `src/orchestration/llm_bridge.py`

### Hooks
- workflow replay/disable logic
- workflow plan acceptance checks

### Change
- Store failure class counters per workflow template.
- Disable by class and cooldown, not only aggregate failures.

### Done When
- Repeated failing workflow classes stop replaying automatically.

## P5 - Memory Lifecycle Policy Triggering

### Files
- `src/core/services/memory_service.py`

### Hooks
- `_compute_disk_usage_snapshot()`
- retrieval/write paths where pressure can trigger lifecycle actions

### Change
- Add threshold actions for summarize/compress/archive/forget.
- Emit lifecycle events to an append-only log.

### Done When
- Memory pressure drives visible, deterministic lifecycle behavior.

## P6 - Cross-Channel Continuity Test Script

### Files
- `scripts/` (new script)
- `src/core/runtime/vera.py` (if link metadata needed)

### Hooks
- channel scope resolution and session linking code paths

### Change
- Add deterministic A->B continuity check with a marker handshake.

### Done When
- Continuity test passes in CI/local gate runs.

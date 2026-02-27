# Vera 2.0 Bolster Plan (Production Hardening)

Objective: make the current runtime robust, autonomous, and non-wedging under sustained operation.

## Priority Order
1. Runtime check stability under latency spikes
2. Autonomy budget/cooldown correctness
3. Failure-learning ingestion
4. Tool-chain reliability and safe fallback
5. Memory lifecycle pressure behavior
6. Cross-channel continuity validation

## 1) Runtime Check Stability

### Problem
`chat_completion` in `scripts/vera_production_checklist.py` intermittently times out during long soak despite healthy API readiness.

### Current Mitigation (already applied)
- Increased checklist HTTP timeout default from 25s to 45s.
- Added `max_tokens=32` for chat probe.

### Next Hardening
- Add short retry with jitter only for `chat_completion` probe.
- Keep non-chat checks single-shot to avoid hiding system faults.

### Target Files
- `scripts/vera_production_checklist.py`

### Acceptance Criteria
- During 24h soak, no critical-fail streak from single transient timeout.
- Failures classify as `transient_timeout` vs `hard_failure` in output JSON.

### Validation
- `.venv/bin/python scripts/vera_production_checklist.py --host 127.0.0.1 --port 8788 --min-running-mcp 8`
- Review `tmp/soak/checklist_*.json`

## 2) Autonomy Budget/Cooldown Correctness

### Problem
Autonomy samples can report `budget_guard:*` reasons that may not align with persisted budget state during long-running processes.

### Hardening Actions
- Force budget config/state reload boundaries in autonomy cycle (runtime-safe read path).
- Add explicit telemetry fields in autonomy status:
  - `budget_snapshot.calls`
  - `budget_snapshot.tokens_used`
  - `budget_limit.calls`
  - `budget_limit.tokens`
- Tag reason with observed values, e.g.:
  - `budget_guard:daily_call_budget_exceeded(24/24)`

### Target Files
- `src/observability/self_improvement_budget.py`
- `src/core/runtime/proactive_manager.py`
- `src/api/server.py` (status payload exposure)

### Acceptance Criteria
- Budget-guard reasons are numerically explainable from status payload.
- No false-positive guard events after config updates.

### Validation
- `curl -sS http://127.0.0.1:8788/api/self_improvement/budget`
- `curl -sS http://127.0.0.1:8788/api/innerlife/status`

## 3) Failure-Learning Ingestion (Edison Loop)

### Problem
Learning loop is success-biased; it should also learn from failed attempts and recovery outcomes.

### Hardening Actions
- Add failure trajectory extraction path:
  - capture tool failure class
  - capture chosen fallback
  - capture final outcome
- Store to a dedicated training shard:
  - `vera_memory/training_examples/failure_examples.jsonl`
- Add failure-weighted reward shaping in reward model inputs.

### Target Files
- `src/learning/learning_loop_manager.py`
- `src/core/services/flight_recorder.py`

### Acceptance Criteria
- Failure examples accumulate automatically.
- Workflow disable/quarantine decisions improve over repeated similar failures.

### Validation
- Run tool exam subset with known failing tools and verify stored failure examples.

## 4) Tool-Chain Reliability and Safe Fallback

### Problem
Learned workflows can still drift into low-value loops unless disabled quickly and replaced predictably.

### Hardening Actions
- Tighten no-progress detection and hard cap chain depth by task class.
- Expand chain quarantine metadata:
  - failure_count
  - last_failure_class
  - disable_until
- Introduce fallback policy tiers:
  - retry same tool (idempotent only)
  - switch alternative tool
  - degrade to user-visible partial result

### Target Files
- `src/orchestration/llm_bridge.py`
- `src/core/runtime/tool_orchestrator.py`
- `src/learning/learning_loop_manager.py`

### Acceptance Criteria
- No repeated reuse of quarantined failing chains.
- Reduced `tool_call_limit_reached` incidence in soak/exam runs.

### Validation
- `scripts/vera_tool_exam_campaign.py`
- `scripts/vera_tool_exam_observer.py`

## 5) Memory Lifecycle Pressure Behavior

### Problem
Budget exists, but lifecycle actions (compress/abstract/forget) should be explicit and policy-driven as memory grows.

### Hardening Actions
- Implement policy thresholds:
  - green < 70%
  - yellow 70-85% (summarize/compress)
  - red > 85% (archive + selective forgetting)
- Persist lifecycle events for auditability.

### Target Files
- `src/core/services/memory_service.py`
- `src/planning/inner_life_engine.py` (memory-aware reflection prompts)

### Acceptance Criteria
- Memory pressure telemetry corresponds to automatic lifecycle actions.
- Retrieval quality remains stable under pressure.

### Validation
- `curl -sS http://127.0.0.1:8788/api/memory/stats`
- Check lifecycle event logs in `vera_memory/`

## 6) Cross-Channel Continuity Validation

### Problem
Architecture supports channel docking, but active operational proof across channels must be repeatable.

### Hardening Actions
- Add a deterministic cross-channel continuity test script:
  - create context in channel A
  - continue in channel B
  - verify carryover keys
- Publish a continuity score in release gate.

### Target Files
- `src/core/runtime/vera.py`
- `src/channels/*`
- `scripts/vera_alive_protocol_gate.py`

### Acceptance Criteria
- Channel switches preserve active thread context without re-explaining.

### Validation
- Scripted two-channel test + gate output.

## V2 Exit Gate
- Soak stability: no repeated critical streaks.
- Reachout: confirmed and high-signal events in 24h window.
- Budget/cooldown diagnostics: fully explainable in status APIs.
- Tool exam: no systemic wedges, failures are recovered or quarantined.

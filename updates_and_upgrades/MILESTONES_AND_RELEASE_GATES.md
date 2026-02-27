# Milestones and Release Gates

## M0 - Baseline Lock (Current 2.0)

### Goals
- Keep 24h alive-when-idle soak running and capture baseline metrics.
- Freeze known-good behavior and failure profile.

### Required Artifacts
- Active run id in `tmp/soak/.active_run_id`
- Soak streams:
  - `tmp/soak/<run>_checks.jsonl`
  - `tmp/soak/<run>_proactive_samples.jsonl`

### Gate
- Runtime up and responsive (`/api/readiness` ready=true).

## M1 - Reliability Hardening (2.0+)

### Scope
- Checklist timeout resilience
- Budget/cooldown diagnostics
- Tool-chain anti-loop hardening

### Gate Criteria
- No critical fail streak >= 2 in 24h soak.
- `tool_call_limit_reached` rate reduced in campaign logs.
- Budget guard reasons include numeric evidence.

### Validation Commands
- `.venv/bin/python scripts/vera_production_checklist.py --host 127.0.0.1 --port 8788 --min-running-mcp 8`
- `.venv/bin/python scripts/vera_alive_protocol_gate.py --base-url http://127.0.0.1:8788`

## M2 - Failure-Learning Integration

### Scope
- Failure trajectory extraction and training dataset path
- Recovery signal feeding reward updates

### Gate Criteria
- Failure examples generated from live operations.
- Recovery recommendations improve on repeated failure class.

### Validation Commands
- Tool exam subset with known failing paths
- Inspect `vera_memory/training_examples/` for failure shards

## M3 - Memory Lifecycle Controller

### Scope
- Automatic compress/abstract/forget behavior under pressure
- Pressure telemetry + lifecycle event log

### Gate Criteria
- Memory stays below budget without retrieval collapse.
- Lifecycle actions are observable and reversible.

### Validation Commands
- `curl -sS http://127.0.0.1:8788/api/memory/stats`
- Verify lifecycle event logs in `vera_memory/`

## M4 - Cross-Channel Continuity Gate

### Scope
- Multi-channel short-term continuity and session-link reliability

### Gate Criteria
- Channel switch test passes with no context re-explanation.
- Shared thread keys preserved across adapters.

### Validation Commands
- Scripted A->B continuity scenario (to be added in `scripts/`)

## M5 - Vera 3.0 Cutover Readiness

### Scope
- Supervisor/Cognition/Memory split planning complete
- Hardware migration pack complete for dual-4090 host

### Gate Criteria
- LoRA cadence and training backend verified on target host.
- Repeatable deployment and rollback documented.

### Validation Commands
- `scripts/lora_readiness_check.py`
- `scripts/lora_cutover_check.py`

## Post-M5 Ongoing Cadence
- Weekly:
  - production checklist + alive protocol gate
- Monthly:
  - adapter retrain eval cycle
- Continuous:
  - proactive quality metrics and failure-learning updates

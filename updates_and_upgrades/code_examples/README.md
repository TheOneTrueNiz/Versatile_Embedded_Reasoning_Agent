# Code Examples

These are integration-oriented examples for planned upgrades. They are not auto-wired into runtime yet.

## Files
- `01_chat_probe_resilience.py`
  - Retry/jitter wrapper for checklist chat probe classification.
- `02_failure_learning_ingest.py`
  - Build training examples from failed tool trajectories + recovery.
- `03_autonomy_budget_signal.py`
  - Explainable budget guard reason with current counters.
- `04_memory_lifecycle_controller.py`
  - Pressure-driven ingest/assimilate/compress/forget policy.
- `05_foreagent_simulator_stub.py`
  - Predictive scoring of candidate tool chains before execution.
- `06_cross_channel_continuity_check.py`
  - Deterministic continuity probe across channel adapters.
- `07_autonomy_kernel_orchestrator.py`
  - Recovery-first autonomy decision and fallback orchestration skeleton.
- `08_failure_to_recovery_dataset.py`
  - Build fail->recover training examples from followthrough and action logs.

## Recommended Landing Paths
- Checklist probe logic:
  - `scripts/vera_production_checklist.py`
- Learning ingestion:
  - `src/learning/learning_loop_manager.py`
  - `src/core/services/flight_recorder.py`
- Autonomy/budget diagnostics:
  - `src/core/runtime/proactive_manager.py`
  - `src/observability/self_improvement_budget.py`
- Memory lifecycle:
  - `src/core/services/memory_service.py`
- Predictive tool simulation:
  - `src/orchestration/llm_bridge.py`
  - `src/core/runtime/tool_orchestrator.py`
- Autonomy kernel orchestration:
  - `src/core/runtime/proactive_manager.py`
  - `src/planning/sentinel_engine.py`

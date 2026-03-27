# Vera 3.0+ Architecture Roadmap

This roadmap translates research themes into practical architecture upgrades.

## Vera 3.0 Design Thesis
- Vera 2.0 proves integrated autonomy.
- Vera 3.0 should move from a strong monolith to a supervised multi-process cognition stack.
- Vera 4.0+ should optimize local-first intelligence on high-end consumer hardware with optional hybrid routing.

## Target Runtime Topology (3.0)

### P0 Supervisor
- Responsibilities:
  - Health diagnostics
  - Intervention and strategy reset
  - Blind audit lane for policy drift
- Initial placement:
  - `src/planning/sentinel_engine.py`
  - `src/core/runtime/proactive_manager.py`

### P3 Cognition
- Responsibilities:
  - Tool reasoning
  - Workflow execution
  - Reflection and followthrough
- Initial placement:
  - `src/orchestration/llm_bridge.py`
  - `src/core/runtime/tool_orchestrator.py`
  - `src/planning/inner_life_engine.py`

### P5 Memory
- Responsibilities:
  - Episodic/semantic consolidation
  - Graph-based retrieval
  - Lifecycle management under pressure
- Initial placement:
  - `src/core/services/memory_service.py`
  - `src/core/services/memvid_adapter.py`

## Vera 3.0 Feature Clusters

### Cluster A: Predictive Tooling (ForeAgent-style)
- Simulate likely tool outcomes before costly execution.
- Rank candidate tool chains by predicted success.
- Integrate as pre-execution phase in LLM bridge.

### Cluster B: Failure-First Learning
- Train not only on wins but on "failed attempt -> corrected strategy" traces.
- Use this for workflow memory suppression and recovery strategy selection.

### Cluster C: Hierarchical Memory
- Distinguish:
  - immediate working context
  - durable episodic memory
  - semantic graph memory
- Add explicit consolidation and forgetting schedule.

### Cluster D: Supervisory Audits
- Separate audit agent watches cognition outputs and trajectories.
- Detect hidden instability, repeated low-signal loops, and policy drift.

## Vera 4.0 Direction (Dual-4090 Host)
- Local model serving stack with quantized adapters.
- Multi-model router for cost/latency/quality tradeoffs.
- Adapter registry by skill domain (coding, planning, multimodal, retrieval).

## Vera 5.0 Direction (Family-Scale Collaborative Runtime)
- Multi-user workspace isolation and shared memory with ACL.
- Policy layers per collaborator profile.
- Local-first optional federated sharing of non-sensitive improvements.

## Research Anchors Used
- Agentic frameworks: ADP-MA, MoA, LatentMAS
- Memory: Titans, Engram, A-Mem, GraphRAG/KARMA
- Tool reliability: failure-analysis and trajectory recovery papers
- Continual learning: DPO, LoRA/QLoRA, self-instruct style distillation
- Reliability control: state-machine and intervention architectures

## Non-Negotiables for 3.0
1. No silent autonomy wedge states.
2. No unrecoverable repeated tool loops.
3. Memory growth must be policy-controlled and observable.
4. Every self-modification path must be auditable and reversible.

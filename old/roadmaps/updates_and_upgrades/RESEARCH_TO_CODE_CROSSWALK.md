# Research to Code Crosswalk

Source anchor: `/path/to/Research_Repo/INDEX.md`

## Core Mapping

| Research Theme | INDEX Highlights | Vera Modules Today | V2.0 Bolster Action | V3+ Upgrade Direction |
|---|---|---|---|---|
| Memory systems | Titans, Engram, A-Mem, GraphRAG, KARMA | `src/core/services/memory_service.py`, `src/core/services/memvid_adapter.py` | Add explicit memory lifecycle controller (ingest/assimilate/compress/forget) and pressure actions tied to `VERA_MEMORY_MAX_FOOTPRINT_MB` | Hybrid memory graph with background KG enrichment (KARMA-like ingestion + GraphRAG retrieval) |
| Agentic frameworks | ADP-MA, LatentMAS, MoA, proactive inner-thought agents | `src/core/runtime/vera.py`, `src/core/runtime/proactive_manager.py`, `src/orchestration/llm_bridge.py` | Harden autonomy loop transitions and fallback routing with explicit no-progress limits | Introduce Supervisor/Cognition split with ADP-MA-style strategy reset loop |
| Reflection and reasoning | Policy of Thoughts, verified reasoning | `src/planning/inner_life_engine.py`, `src/core/runtime/proactive_manager.py` | Persist reflection reason/outcome diagnostics and enforce anti-repeat checks in reflection prompts | Add verifier lane for high-stakes reasoning traces before execution |
| Tool use and error analysis | Tool failure studies, hierarchical error checklists, trajectory recovery | `src/core/runtime/tool_orchestrator.py`, `src/orchestration/llm_bridge.py`, `scripts/vera_tool_exam_battery.py` | Failure taxonomy + retry/fallback policy with quarantine tags and cooldown discipline | Predictive execution (ForeAgent-like) to prune failing tool plans before live calls |
| State machines and reliable control flow | XGrammar, StepShield, logic-grounded flow | `src/planning/sentinel_engine.py`, `src/core/runtime/proactive_manager.py` | Tighten trigger condition/cooldown semantics and invariant checks | Formal policy graph/statechart for autonomous execution and interventions |
| Continual learning and RL | DPO, self-evolving agent survey | `src/learning/learning_loop_manager.py`, `src/core/services/flight_recorder.py` | Add failure-learning ingestion path (not only success trajectories) | Preference optimization loop combining trajectory quality + partner feedback |
| Distillation and small models | LoRA, QLoRA, distillation | `src/learning/learning_loop_manager.py`, `scripts/install_lora_cadence_timer.sh` | Ensure reliable cadence and runtime wiring on target machine | Multi-adapter policy bank and selective adapter activation by task domain |
| Prompt optimization | DSPy-style prompt compilation | `config/vera_genome.json`, `src/orchestration/llm_bridge.py` | Add prompt/version regression checks and contract tests | Compile prompt programs with metric-driven optimization and A/B promotion |
| Evaluation and benchmarks | RAG eval, agent benchmarks | `scripts/vera_production_checklist.py`, `scripts/vera_alive_protocol_gate.py`, `scripts/vera_tool_exam_campaign.py` | Separate transient latency from hard failures with retry budget in checklist probes | Continuous evaluation harness with weekly score deltas and regression alarms |
| Security and ops | Agent cgroup isolation, deceptive alignment monitoring | `src/safety/safety_validator.py`, `src/planning/sentinel_engine.py`, `src/core/runtime/tool_orchestrator.py` | Add stronger anomaly triggers from tool trajectories and memory poisoning risk | Supervisory blind-audit stream (P0 monitor) with attribution summaries |
| Long-horizon planning | ReAcTree, recursive language models | `src/planning/sentinel_engine.py`, `src/core/runtime/proactive_manager.py` | Improve commitment/followthrough state consistency and replay recovery | Hierarchical planner with decomposition, speculative execution, and rollback |
| Hardware and deployment | Hybrid routing, inference engines survey | `run_vera_api.py`, `scripts/run_vera.sh`, `src/orchestration/llm_bridge.py` | Keep stable routing with clear fallback behavior on iGPU host | Dual-4090 local-first runtime with optional cloud overflow routing |

## Existing Vera Strengths Confirmed
- Persistent inner life and personality state across sessions.
- Proactive cadence with active/idle phase transitions and followthrough logic.
- Workflow memory, reward/LoRA cadence scaffolding, and flight recorder pipeline.
- Tool-level guardrails in orchestrator/bridge (timeouts, fallback, blocklist, description sanitation).

## High-Value Gaps Identified
1. Checklist probe still sees intermittent `chat_completion` timeout spikes under soak load.
2. Budget guard reasons can become misleading across long runs unless runtime state and config are continuously synchronized after deploy.
3. Failure learning is weaker than success learning; failed trajectories are not yet first-class training examples.
4. Predictive tool simulation is not yet present, so failing chains are discovered late.
5. Cross-channel continuity exists architecturally but needs stronger operational validation under active multi-channel load.

# Vera 3.0 Post-Migration Blueprint

Purpose: make Vera 3.0 build-out deterministic on the dual-4090 host while Vera 2.0 continues live validation on the current machine.

This file is execution-oriented and pairs with:
- `updates_and_upgrades/VERA_3_0_PLUS_ROADMAP.md`
- `updates_and_upgrades/RESEARCH_PAPER_PLAYBOOK.md`
- `updates_and_upgrades/code_examples/`

## 0) Scope and Principles

1. Keep Vera 2.0 stable and observable while building 3.0.
2. No speculative refactors without testable wiring targets.
3. Every new subsystem must have:
   - runtime owner module
   - failure mode policy
   - gate command and pass criteria

## 1) Build Tracks (Parallelizable)

## Track A: Autonomy Kernel (initiative + recovery)

Goal: proactive behavior that does not wedge, spam, or stall under tool failures.

Primary module targets:
- `src/core/runtime/proactive_manager.py`
- `src/core/runtime/vera.py`
- `src/planning/sentinel_engine.py`
- `src/orchestration/llm_bridge.py`

Research anchors:
- `/home/nizbot-macmini/Desktop/Research_Repo/02_Agentic_Frameworks/2602.00307_ADP_MA.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/02_Agentic_Frameworks/2511.02424_ReAcTree.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/09_Tool_Usage_and_Error_Analysis/2601.05930_ForeAgent.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/21_State_Machines_and_Reliable_Control_Flow/2411.15100_XGrammar_Structured_Generation.pdf`

Implementation sequence:
1. Add an autonomy decision kernel that consumes budget, cooldown, and recent failure state.
2. Add strict no-progress fallback transition: retry -> alternate workflow -> defer with explicit reason.
3. Add "dead-end" detector to prevent repeated failed workflow reuse.
4. Bind all autonomy actions to followthrough state updates.

Acceptance gates:
- `python3 scripts/vera_alive_protocol_gate.py --base-url http://127.0.0.1:8788`
- `python3 scripts/vera_proactive_soak_runner.py --base-url http://127.0.0.1:8788 --hours 4`

## Track B: Failure-First Learning Loop

Goal: failed attempts become training assets, not just logs.

Primary module targets:
- `src/learning/learning_loop_manager.py`
- `src/core/services/flight_recorder.py`
- `src/core/runtime/tool_orchestrator.py`

Research anchors:
- `/home/nizbot-macmini/Desktop/Research_Repo/02_Agentic_Frameworks/2509.18847_failure_makes_agent_stronger_tool_reflection.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/09_Tool_Usage_and_Error_Analysis/2601.12658_Trajectory_Error_Recovery.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/11_Continual_Learning_and_RL/2305.18290_DPO_Direct_Preference_Optimization.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/17_Data_Engineering_and_Datasets/2212.10560_Self_Instruct_Aligning_LM.pdf`

Implementation sequence:
1. Build fail->recover example extraction from followthrough + flight recorder logs.
2. Add failure taxonomy labels and recovery quality scoring.
3. Add ingestion lane into distillation dataset with lower trust weight than confirmed successes.
4. Add suppression list for repeated bad chains until new evidence appears.

Acceptance gates:
- `python3 scripts/vera_tool_exam_campaign.py --base-url http://127.0.0.1:8788 --tier1-scope all --tier2-mode inferred`
- `python3 scripts/vera_production_checklist.py --base-url http://127.0.0.1:8788`

## Track C: Memory Architecture V2 (capacity + quality)

Goal: scale persistent memory quality under larger autonomy windows.

Primary module targets:
- `src/core/services/memory_service.py`
- `src/core/services/memvid_adapter.py`
- `src/planning/inner_life_engine.py`

Research anchors:
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2501.00663_TITANS_Neural_Memory.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2601.07372_Engram_Conditional_Memory.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2601.12658_AMem_Zettelkasten.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2404.16130_GraphRAG_Local_to_Global.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2502.06472_KARMA_MultiAgent_KG_Enrichment.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/01_Memory_Systems/2510.22590_ATOM_Dynamic_Temporal_KG.pdf`

Implementation sequence:
1. Keep 1GB default budget (`VERA_MEMORY_MAX_FOOTPRINT_MB`) with pressure telemetry.
2. Implement explicit lifecycle stages: ingest -> assimilate -> abstract -> compress -> forget.
3. Add memory quality checks: duplicate suppression, stale memory decay, retrieval precision metrics.
4. Add graph enrichment background job with bounded duty cycle.

Acceptance gates:
- `python3 scripts/vera_production_checklist.py --base-url http://127.0.0.1:8788`
- `python3 scripts/vera_alive_protocol_gate.py --base-url http://127.0.0.1:8788`

## Track D: Tool Intelligence at 379+ Scale

Goal: stable tool selection under large tool inventories.

Primary module targets:
- `src/orchestration/llm_bridge.py`
- `src/core/runtime/tool_orchestrator.py`
- `src/core/runtime/vera.py`

Research anchors:
- `/home/nizbot-macmini/Desktop/Research_Repo/09_Tool_Usage_and_Error_Analysis/2505.03275_RAG_MCP_Tool_Prompt_Bloat.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/09_Tool_Usage_and_Error_Analysis/2602.20426_Rewrite_Tool_Descriptions.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/24_Prompt_Engineering_and_Optimization/2310.03714_DSPy_Declarative_LM_Pipelines.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/12_Evaluation_and_Benchmarks/2509.24002_MCPMark.pdf`

Implementation sequence:
1. Tool retrieval pre-filter (top-k candidates) before full prompt assembly.
2. Description rewrite pipeline based on real call success/failure traces.
3. Add route confidence and abstain/defer behavior for ambiguous tool intent.
4. Keep regression guard for `tool_call_limit_reached`.

Acceptance gates:
- `python3 scripts/vera_tool_exam_campaign.py --base-url http://127.0.0.1:8788 --tier1-scope all --tier2-mode inferred`
- `python3 scripts/vera_mcp_golden_gate.py --base-url http://127.0.0.1:8788`

## Track E: Training + Adapter Ops (3.0 host only)

Goal: reproducible LoRA/DPO pipeline on dual-4090 machine.

Primary module targets:
- `src/learning/learning_loop_manager.py`
- `src/learning/hf_lora_trainer.py`
- `src/learning/adaptive_lora.py`
- `scripts/install_lora_cadence_timer.sh`

Research anchors:
- `/home/nizbot-macmini/Desktop/Research_Repo/15_Optimization_and_Training_Dynamics/2106.09685_LoRA_Low_Rank_Adaptation.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/07_Efficiency_and_Quantization/2305.14314_QLoRA_Efficient_Finetuning.pdf`
- `/home/nizbot-macmini/Desktop/Research_Repo/11_Continual_Learning_and_RL/2305.18290_DPO_Direct_Preference_Optimization.pdf`

Implementation sequence:
1. Verify CUDA stack + PEFT/datasets and trainer dry-run.
2. Promote failure/success mixed dataset generation.
3. Install cadence timer and retention policy.
4. Add post-train eval gate against reliability/autonomy scores.

Acceptance gates:
- `python3 -m pytest -q`
- LoRA dry-run and eval report generation on target host.

## 2) Hardware Split

Current host (iGPU) keeps:
- continuous V2 runtime soak
- tool exam battery
- autonomy behavior validation
- cross-channel continuity validation

Dual-4090 host receives:
- LoRA/QLoRA/DPO training and adapter eval
- heavier memory graph ingestion jobs
- long-run distillation and retraining cadence

## 3) Release Criteria to Start Vera 3.0 Cutover

Required before declaring 3.0 readiness:
1. Tier1+Tier2 exam pass rates meet target and no critical side-effect gaps.
2. 24h alive-when-idle green with verified external reachout delivery.
3. No unresolved wedge/stall pattern in soak logs.
4. LoRA cadence operational on target host with reproducible eval output.
5. Cross-channel continuity validated under active multi-channel load.

## 4) Immediate Next Steps (Post-Migration Day 0/1)

1. Mirror this repo + `Research_Repo` on dual-4090 host.
2. Run environment bootstrap and GPU verification.
3. Start Track E setup while keeping Track A/B hardening active on this host.
4. Keep `my_diary` entries per major patch/gate event to preserve project grounding.

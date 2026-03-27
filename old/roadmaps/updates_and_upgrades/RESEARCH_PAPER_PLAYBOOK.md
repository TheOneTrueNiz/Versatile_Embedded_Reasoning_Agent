# Research Paper Playbook for Vera 3.0+

Source root:
- `/path/to/research-corpus`
- Canonical index: `/path/to/research-corpus/INDEX.md`

This playbook converts paper references into concrete execution hooks.

## Priority Read Order (Execution-First)

1. `/path/to/research-corpus/02_Agentic_Frameworks/2602.00307_ADP_MA.pdf`
2. `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2601.05930_ForeAgent.pdf`
3. `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2505.03275_RAG_MCP_Tool_Prompt_Bloat.pdf`
4. `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2602.20426_Rewrite_Tool_Descriptions.pdf`
5. `/path/to/research-corpus/01_Memory_Systems/2601.07372_Engram_Conditional_Memory.pdf`
6. `/path/to/research-corpus/01_Memory_Systems/2601.12658_AMem_Zettelkasten.pdf`
7. `/path/to/research-corpus/01_Memory_Systems/2404.16130_GraphRAG_Local_to_Global.pdf`
8. `/path/to/research-corpus/01_Memory_Systems/2502.06472_KARMA_MultiAgent_KG_Enrichment.pdf`
9. `/path/to/research-corpus/11_Continual_Learning_and_RL/2305.18290_DPO_Direct_Preference_Optimization.pdf`
10. `/path/to/research-corpus/07_Efficiency_and_Quantization/2305.14314_QLoRA_Efficient_Finetuning.pdf`

## Paper -> Vera Wiring Map

| Focus | Paper | Local File | Vera Wiring Target |
|---|---|---|---|
| Autonomy supervisor | ADP-MA | `/path/to/research-corpus/02_Agentic_Frameworks/2602.00307_ADP_MA.pdf` | `src/core/runtime/proactive_manager.py`, `src/planning/sentinel_engine.py` |
| Long-horizon decomposition | ReAcTree | `/path/to/research-corpus/02_Agentic_Frameworks/2511.02424_ReAcTree.pdf` | `src/planning/sentinel_engine.py`, followthrough planners |
| Multi-agent latent comms | LatentMAS | `/path/to/research-corpus/02_Agentic_Frameworks/2511.20639_LatentMAS.pdf` | future 3.0 supervisor/cognition lanes |
| Predictive tool execution | ForeAgent | `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2601.05930_ForeAgent.pdf` | `src/orchestration/llm_bridge.py`, `src/core/runtime/tool_orchestrator.py` |
| Tool prompt bloat mitigation | RAG-MCP | `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2505.03275_RAG_MCP_Tool_Prompt_Bloat.pdf` | tool candidate pre-filter layer in bridge/orchestrator |
| Tool description optimization | Rewrite Tool Descriptions | `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2602.20426_Rewrite_Tool_Descriptions.pdf` | MCP metadata rewrite pass + telemetry loop |
| Failure-to-recovery learning | Trajectory Error Recovery | `/path/to/research-corpus/09_Tool_Usage_and_Error_Analysis/2601.12658_Trajectory_Error_Recovery.pdf` | `src/learning/learning_loop_manager.py`, flight recorder ingestion |
| Reliability stress eval | ReliabilityBench | `/path/to/research-corpus/12_Evaluation_and_Benchmarks/2601.06112_ReliabilityBench_Production_Stress.pdf` | `scripts/vera_production_checklist.py` gate expansion |
| Structured tool contracts | XGrammar | `/path/to/research-corpus/21_State_Machines_and_Reliable_Control_Flow/2411.15100_XGrammar_Structured_Generation.pdf` | strict JSON/contract validation around tool outputs |
| Decision robustness | Self-Consistency | `/path/to/research-corpus/04_Reflection_and_Reasoning/2203.11171_Self_Consistency_CoT.pdf` | high-stakes decision fan-out in planner |
| Memory scaling | Titans | `/path/to/research-corpus/01_Memory_Systems/2501.00663_TITANS_Neural_Memory.pdf` | memory hierarchy tuning and retrieval budget policies |
| Conditional memory retrieval | Engram | `/path/to/research-corpus/01_Memory_Systems/2601.07372_Engram_Conditional_Memory.pdf` | `src/core/services/memory_service.py` selective retrieval |
| Episodic-semantic linking | A-Mem | `/path/to/research-corpus/01_Memory_Systems/2601.12658_AMem_Zettelkasten.pdf` | relationship notes -> durable graph links |
| Graph retrieval foundations | GraphRAG | `/path/to/research-corpus/01_Memory_Systems/2404.16130_GraphRAG_Local_to_Global.pdf` | graph retrieval quality and traversal strategy |
| KG enrichment pipeline | KARMA | `/path/to/research-corpus/01_Memory_Systems/2502.06472_KARMA_MultiAgent_KG_Enrichment.pdf` | background ingestion pipeline for memory graph |
| Temporal KG durability | ATOM | `/path/to/research-corpus/01_Memory_Systems/2510.22590_ATOM_Dynamic_Temporal_KG.pdf` | temporal fact storage and decay policy |
| Multi-user memory isolation | Collaborative Memory | `/path/to/research-corpus/01_Memory_Systems/2505.18279_Collaborative_Memory_MultiUser.pdf` | Vera 3.0+ private/shared memory lanes |
| Agent resource isolation | AgentCgroup | `/path/to/research-corpus/18_Agentic_OpsSec_and_Security/2602.09345_AgentCgroup_OS_Resource_Isolation.pdf` | tool runtime resource guardrails |
| Adapter training core | LoRA | `/path/to/research-corpus/15_Optimization_and_Training_Dynamics/2106.09685_LoRA_Low_Rank_Adaptation.pdf` | `src/learning/adaptive_lora.py` |
| Efficient adapter training | QLoRA | `/path/to/research-corpus/07_Efficiency_and_Quantization/2305.14314_QLoRA_Efficient_Finetuning.pdf` | `src/learning/hf_lora_trainer.py` |
| Preference learning | DPO | `/path/to/research-corpus/11_Continual_Learning_and_RL/2305.18290_DPO_Direct_Preference_Optimization.pdf` | reward/distillation loop ranking |
| Data generation loop | Self-Instruct | `/path/to/research-corpus/17_Data_Engineering_and_Datasets/2212.10560_Self_Instruct_Aligning_LM.pdf` | trajectory -> dataset synthesis |
| RAG architecture | A-RAG | `/path/to/research-corpus/23_Retrieval_and_RAG/2602.03442_A_RAG_Agentic_Hierarchical_Retrieval.pdf` | hierarchical retrieval in memory layer |
| RAG evaluation methods | RAG Eval Survey | `/path/to/research-corpus/23_Retrieval_and_RAG/2504.14891_RAG_Evaluation_Survey_LLM_Era.pdf` | memory quality scorecard definitions |
| Hallucination-resistant retrieval | Faithful RAG | `/path/to/research-corpus/23_Retrieval_and_RAG/2512.08892_Faithful_RAG_Sparse_Autoencoders.pdf` | verify/cross-check retrieval outputs |
| Prompt/program optimization | DSPy | `/path/to/research-corpus/24_Prompt_Engineering_and_Optimization/2310.03714_DSPy_Declarative_LM_Pipelines.pdf` | `config/vera_genome.json` evolution pipeline |

## Suggested Weekly Research-to-Code Cadence

1. Pick 2 papers max per week.
2. For each paper, define one concrete code hook and one measurable metric.
3. Ship a narrow implementation patch.
4. Run gate scripts and record deltas in `my_diary`.
5. Promote only when metrics improve and regressions remain zero.

## Anti-Drift Rule

If a paper insight cannot be mapped to a file/function/test in Vera, do not implement it yet. Add it to backlog with missing prerequisites explicitly listed.

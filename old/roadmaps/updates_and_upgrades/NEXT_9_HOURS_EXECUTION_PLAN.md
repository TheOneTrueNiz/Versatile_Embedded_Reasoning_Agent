# Next 9 Hours Execution Plan (While 24h Soak Runs)

## Goal
Use soak time for high-leverage prep so post-soak implementation is fast and low-risk.

## Block A (Now): Spec and Patch Prep
- Finalize V2 patch queue with diff-ready implementation notes:
  - checklist transient timeout handling
  - budget guard explainability
  - failure-learning ingestion path
  - memory lifecycle policy events

## Block B: Test Harness Preparation
- Prepare deterministic tests for each patch:
  - timeout simulation test for checklist
  - budget reason correctness test
  - failure-example extraction test
  - memory pressure policy threshold test

## Block C: 3.0 Scaffolding Draft
- Draft P0/P3/P5 module boundaries and message contracts.
- Define event schema for blind-audit telemetry.
- Define workflow-simulation (ForeAgent-style) interface contract.

## Block D: Migration Readiness (Dual-4090)
- Confirm environment checklist:
  - LoRA trainer deps
  - CUDA visibility
  - adapter storage and eval paths
- Prepare first-run smoke scripts.

## Block E: Post-Soak Immediate Actions
1. Read final summaries (`checks_summary`, `proactive_summary`).
2. If green, freeze baseline and branch for V2 hardening sprint.
3. Apply patch queue with one patchset per milestone.
4. Re-run short soak + tool exam deltas before merging.

## Definition of Productive Use of Soak Time
- Every planned change has:
  - target file/function
  - test command
  - rollback plan

# HyperAgents Stepping-Stone Archive

## Goal
Add a bounded improvement archive that stores successful Vera runtime interventions as reusable stepping stones. The archive should help Vera recognize recurring failure classes and propose previously successful repairs without introducing open-ended self-modification.

## Why this is the correct adaptation
The useful part of `HyperAgents` is not full recursive self-editing. It is the combination of:
- persistent archive of successful interventions
- explicit reuse criteria
- separation between normal task execution and improvement-policy execution

Vera already has the raw ingredients:
- archived completed work-jar items in `vera_memory/autonomy_work_jar.json`
- verifier state in `vera_memory/autonomy_state_sync_verifier.json`
- proof artifacts in `tmp/audits/`
- diary checkpoints in `my_diary/`

The archive should unify those into a reusable improvement-policy memory.

## Scope boundary
Do not build a self-editing agent.

Phase 1 is only:
- archive successful interventions
- classify them by failure class
- define reuse rules
- expose a way to suggest one previously successful intervention when the same class recurs

No automatic code patch replay in phase 1.

## Archive location
- `vera_memory/improvement_archive.json`

## Archive entry schema
Each entry stores:
- `archive_id`
- `created_at_utc`
- `title`
- `failure_class`
- `problem_signature`
- `intervention_type`
- `source_work_item_id`
- `source_task_id`
- `proof_artifact`
- `files_changed`
- `success_evidence`
- `reuse_rule`
- `rollout_guard`
- `status`

### Meaning
- `failure_class`
  - stable category such as:
    - `tool_routing_noise`
    - `reflection_timeout`
    - `work_surface_starvation`
    - `delivery_not_ready`
    - `state_sync_mismatch`
    - `flight_recorder_integrity`
- `problem_signature`
  - compact normalized signature for matching recurrence
  - examples:
    - `preview:web_research:browser_noise`
    - `preview:web_research:ranking_local_video_noise`
    - `flight_recorder:integrity:no_hash_chain`
- `intervention_type`
  - one of:
    - `routing_rule`
    - `ranking_rule`
    - `payload_budget`
    - `state_sync_repair`
    - `ledger_integrity`
- `proof_artifact`
  - primary file proving success
- `files_changed`
  - bounded list of code files or docs touched
- `success_evidence`
  - compact structured summary:
    - passing tests
    - live proof fields
    - before/after symptoms
- `reuse_rule`
  - human-readable and machine-usable condition for when to suggest this intervention again
- `rollout_guard`
  - the constraint that keeps reuse bounded
  - examples:
    - `suggest_only`
    - `same_failure_class_only`
    - `requires_live_proof`
- `status`
  - `active`, `superseded`, or `retired`

## Materialization rule
Phase 1 should harvest entries only from interventions that meet all of these:
1. work-jar item is archived as completed
2. completion has a proof artifact
3. the proof artifact shows a concrete live or test success condition
4. the intervention can be classified into one stable failure class

This avoids filling the archive with vague notes or incomplete work.

## First seed candidates from current Vera history
These are the obvious phase-1 seeds:

1. `awj_web_research_shortlist_cleanup_01`
- failure class:
  - `tool_routing_noise`
- problem signature:
  - `preview:web_research:browser_noise`
- intervention type:
  - `routing_rule`
- proof artifact:
  - `tmp/audits/web_research_shortlist_cleanup_live_20260326T204724Z.json`

2. `awj_preview_payload_budget_01`
- failure class:
  - `tool_routing_observability_latency`
- problem signature:
  - `preview:payload:unbounded_debug_rows`
- intervention type:
  - `payload_budget`
- proof artifact:
  - `tmp/audits/preview_payload_budget_live_20260326T205135Z.json`

3. `awj_web_research_ranking_cleanup_01`
- failure class:
  - `tool_routing_noise`
- problem signature:
  - `preview:web_research:ranking_local_video_noise`
- intervention type:
  - `ranking_rule`
- proof artifact:
  - `tmp/audits/web_research_ranking_cleanup_live_20260326T205715Z.json`

4. `awj_flight_ledger_impl_phase1_01`
- failure class:
  - `flight_recorder_integrity`
- problem signature:
  - `flight_recorder:no_hash_chain_verification`
- intervention type:
  - `ledger_integrity`
- proof artifact:
  - `tmp/audits/flight_ledger_live_verify_20260326T210649Z.json`

## Reuse rule design
Phase 1 reuse is suggestion-only.

Rule:
- when a new bounded task or audit is created
- and its normalized signature matches an active archive entry's `problem_signature` or `failure_class`
- surface the archive entry as a suggested prior successful intervention

Output should include:
- title
- failure class
- proof artifact
- files changed
- reuse rule

This is enough to accelerate future fixes without letting the system silently rewrite itself.

## Rollout plan
### Phase 1
- create archive schema and materializer script
- harvest the first 3-5 entries from already archived successful work-jar items
- suggestion-only usage

### Phase 2
- integrate archive lookup into queued improvement-task creation
- when a recurring failure appears, seed the next work item with matching archive context automatically

### Phase 3
- allow guarded semi-automatic replay for narrow classes only
- examples:
  - payload budget settings
  - routing clamps
- never for broad codebase edits without explicit proof and review

## Why this fits Vera better than full HyperAgents
- keeps all improvements operator-auditable
- ties reuse to explicit proof artifacts
- separates task work from improvement-policy memory
- gives cross-domain transfer without uncontrolled recursion

## Next implementation task
Phase 1 implementation:
- add `vera_memory/improvement_archive.json`
- add a materializer that converts qualifying archived work-jar items into archive entries
- seed the first entries from the current archived interventions

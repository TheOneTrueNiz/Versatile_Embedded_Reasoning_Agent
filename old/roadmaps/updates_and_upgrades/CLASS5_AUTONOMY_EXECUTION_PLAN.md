# Vera Class-5 Autonomy Execution Plan

## Objective
Deliver Vera as a deterministic, restart-safe, self-recovering autonomous collaborator where cognition and operations are both production-grade.

## Current State (2026-03-05)
- Cognition stack is strong (memory, reflections, learning loop, partner model surfaces).
- Reliability plumbing is partially complete.
- New in this pass:
  - Durable runplane module (`JobStore + RunStore + lane serialization + dead-letter + SLO snapshots`).
  - Proactive executors wired to runplane.
  - ACK ingestion wired to runplane from native push flows.
  - New APIs: `/api/autonomy/jobs`, `/api/autonomy/runs`, `/api/autonomy/runs/mark`, `/api/autonomy/dead-letter`, `/api/autonomy/dead-letter/replay`, `/api/autonomy/slo`.
  - Reachout delivery events now record delivery runs in runplane with external run-id aliasing.
  - Proactive side effects now use lane guards, per-lane queues, and exception-safe lane release.
  - Inner-life delivery routing now supports deterministic `fallback` mode (first successful channel) and `broadcast` mode.
  - Dead-letter auto-replay policy is now wired into autonomy cadence with cooldown + allowlist controls.
  - Failure-learning events are persisted (`vera_memory/failure_learning_events.jsonl`) for post-hoc analysis and distillation input.
  - Replay governance now includes per-job replay caps, auto-escalation thresholds, and cycle-level SLO audits.
  - ACK-SLA stale delivery escalation is now automated with per-cycle caps and event-log evidence.

## Tiered Execution Program

### Tier 1: Deterministic Runplane (Complete)
Goal: no ambiguity in what ran, what failed, and what needs replay.
- Durable job/run state persisted atomically.
- One-active-run-per-lane serialization.
- Retry/backoff/dead-letter transitions.
- ACK state transition support.
- API visibility for jobs/runs/dead-letter/SLO.

Ship gates:
- Lane collision produces `lane_busy` instead of race conditions.
- Failed non-retryable runs reach dead-letter deterministically.
- Push ACK updates run/job status to `acked`.

### Tier 2: Delivery State Machine + Channel Determinism (In Progress)
Goal: commitment delivery is deterministic and measurable.
- Standardize state transitions:
  - `planned -> due -> running -> delivered -> acked -> escalated -> closed`
- Pin routing policy in host config (not model-selected destination).
- Add fallback chain policies per commitment type:
  - `push -> email -> call` (with quiet-hours rules)
- Correlate every delivery with run_id and channel receipt artifacts.

Ship gates:
- No silent misses for P0 commitments.
- Delivery and ACK rates visible via API.

### Tier 3: Failure Taxonomy + Recovery Kernel (In Progress)
Goal: failures degrade gracefully; no wedges.
- Classify failures: transient/auth/rate-limit/transport/validation/permanent.
- Bounded exponential backoff + jitter for transient classes.
- Circuit breaker + dead-letter replay path.
- Recovery contract: if primary tool fails, attempt alternate action before escalation.

Ship gates:
- Stuck-run rate <= 0.1% in soak windows.
- Auto-recovery median <= 2 minutes for transient failures.

### Tier 4: Queue Lanes + Side-Effect Control (Planned)
Goal: keep session behavior coherent under load.
- Session-lane serialization for side-effecting actions.
- Global concurrency caps.
- Queue modes (`collect`, `followup`, `steer`) and overload policy.

Ship gates:
- Zero session collision races.
- Stable latency with bounded queue depth.

### Tier 5: Autonomy Governance + Initiative Quality (Planned)
Goal: proactive behavior that is useful, not noisy.
- Initiative budgets, cooldown policy, interruption policy.
- Confidence gates for side effects.
- Escalation ladder for unresolved commitments.
- Failure-learning ingestion (successes and failures) into workflow memory.

Ship gates:
- High-signal outreach rate target met.
- No spam loops under prolonged idle windows.

### Tier 6: Validation Battery + Release Gates (Planned)
Goal: prove runtime behavior end-to-end.
- Tier A: subsystem unit/integration.
- Tier B: scenario tests (wakeup/reminders/ack miss/API outage/auth expiry).
- Tier C: chaos (channel down/rate limits/tool failures).
- Tier D: autonomy soaks (2h -> 8h -> 24h).

Ship gates:
- Scheduled wake/reminder execution >= 99%.
- Delivery success with fallback >= 99%.
- ACK capture when user engages >= 95%.
- Zero silent P0 failures.

## Immediate Next Build Order
1. Harden delivery state machine and fallback chain execution paths.
2. Add per-session side-effect lanes for proactive outputs.
3. Expand test battery for repeated bad-workflow quarantine and recovery.
4. Re-run 2-4h soak with SLO capture, then 24h validation when gate criteria are green.

## Migration Note
LoRA cadence validation remains blocked on non-GPU host limitations; keep as post-migration gate on i9/dual-4090 machine. Do not block Tier 1-6 runtime reliability hardening on that dependency.

# VERA Public Evaluation Spec

## Purpose
Define a reproducible, operator-facing evaluation battery that proves VERA reliability, autonomy quality, and end-to-end tool execution.

## Evaluation Tiers
1. Tier 1: Direct Tool Execution
- Prompt each tool explicitly and verify execution outcomes, not just model text.
2. Tier 2: Inferred Tool Use and Tool Chaining
- Validate selection quality, sequencing, fallback behavior, and completion quality.
3. Autonomy Soak
- Measure reflection cycles, initiative triggers, outreach quality, and non-spam behavior.

## Required Commands
1. Full exam campaign
```bash
.venv/bin/python scripts/vera_tool_exam_campaign.py \
  --base-url http://127.0.0.1:8788 \
  --tier1-scope server \
  --retries 0 \
  --wait-ready-seconds 60 \
  --ready-streak 3 \
  --run-native-push-hardening \
  --output tmp/tool_exam_campaign/<timestamp>_manifest.json
```
2. Battery only
```bash
.venv/bin/python scripts/vera_tool_exam_battery.py --help
```
3. Proactive soak
```bash
.venv/bin/python scripts/vera_proactive_soak_runner.py \
  --base-url http://127.0.0.1:8788 \
  --duration-minutes 120 \
  --interval-seconds 60 \
  --output tmp/soak/<timestamp>_summary.json \
  --samples-output tmp/soak/<timestamp>_samples.jsonl
```
4. Local release gate
```bash
.venv/bin/python scripts/vera_release_gate_local.py --help
```

## Minimum Public Pass Gates
1. Tier 1 pass rate: 95% or higher.
2. Tier 2 pass rate: 90% or higher.
3. Zero fatal wedge/stall events during campaign.
4. No unrecovered tool-call-limit loop.
5. Autonomy soak:
- At least one high-signal proactive action in test window.
- No spam bursts.
- Recovery from transient external tool/API failures.
6. Release gate script completes with no blocking failures.

## Evidence Requirements
1. Campaign manifest JSON.
2. Tier-level result files and failure buckets.
3. Soak summary JSON and sampled timeline JSONL.
4. Relevant log excerpts with timestamps and run IDs.
5. Environment profile:
- CPU/GPU class, RAM, Python version, OS version.
6. Commit hash and configuration fingerprint for reproducibility.

## Failure Classification
1. Product bug
- Wrong output or missing side effect despite valid request.
2. Runtime wiring bug
- Handler not reached, scheduler not firing, state write not applied.
3. External dependency failure
- Upstream API outage/rate limit/network interruption.
4. Evaluation harness issue
- False positive/negative due to test instrumentation.

## Remediation Loop
1. Patch only the root cause.
2. Re-run failed subset.
3. Re-run full tier once subset is clean.
4. Update reliability counters and regression tests.
5. Publish delta report with before/after counts.

## Anti-Hype Rule
Do not claim AGI. Claim measured capability and publish reproducible evidence.

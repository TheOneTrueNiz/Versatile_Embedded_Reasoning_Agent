# Flight Ledger Design

## Goal
Add a Python-native append-only hash-chained ledger beside Vera's existing flight recorder so high-value runtime events gain cheap tamper-evident verification without disrupting current `transitions.ndjson` ingestion or reward-model training.

## Existing integration point
Current append path:
- `src/core/services/flight_recorder.py`
  - `FlightRecorder._append()` writes NDJSON to `vera_memory/flight_recorder/transitions.ndjson`

Current atomic append primitive:
- `src/memory/persistence/atomic_io.py`
  - `atomic_ndjson_append()`

Reference patterns:
- `/tmp/echo-root-ve-1774557432/ve_ledger_append.ps1`
- `/tmp/echo-root-ve-1774557432/ve_quickcheck.py`

## Design choice
Do not replace `transitions.ndjson`.

Instead, add a second file:
- `vera_memory/flight_recorder/ledger.jsonl`

This ledger mirrors only a compact canonical subset of each high-value event. That keeps:
- existing learning pipelines unchanged
- append cost low
- verification cheap
- rollout reversible

## Ledger record schema
Each ledger line is canonical JSON with sorted keys and these fields:
- `ledger_version`
- `timestamp_utc`
- `record_type`
- `event_uuid`
- `source_file`
- `source_kind`
- `hash_prev`
- `hash_self`
- `payload_sha256`
- `summary`
- `meta`

### Field meaning
- `ledger_version`
  - schema version for future migrations
- `timestamp_utc`
  - UTC ISO-8601 with `Z`
- `record_type`
  - one of:
    - `GENESIS`
    - `transition`
    - `tool_call`
    - `llm_call`
    - `routing_decision`
    - `task_feedback`
- `event_uuid`
  - the existing event UUID when available
  - otherwise generated once at append time
- `source_file`
  - usually `vera_memory/flight_recorder/transitions.ndjson`
- `source_kind`
  - `flight_recorder`
- `hash_prev`
  - previous ledger record `hash_self`, or zero64 for genesis
- `hash_self`
  - SHA-256 over canonical JSON of the record excluding `hash_self`
- `payload_sha256`
  - SHA-256 over the source event payload written to `transitions.ndjson`
- `summary`
  - compact human-readable summary, bounded length
- `meta`
  - compact bounded metadata such as:
    - `action_type`
    - `tool_name`
    - `model`
    - `success`
    - `air_score`
    - `air_reason`

## Canonicalization rule
Use deterministic canonical JSON before hashing:
- UTF-8
- sorted keys
- compact separators
- no pretty printing

This matches the useful part of the PowerShell reference while staying Python-native.

## Append rule
Phase 1 appends one ledger record immediately after a successful write to `transitions.ndjson`.

Ordering:
1. build the normal transition payload
2. append transition to `transitions.ndjson`
3. build compact ledger mirror from the same in-memory payload
4. append ledger record to `ledger.jsonl`

If the ledger append fails:
- do not fail the main runtime action
- emit a warning/log event
- keep runtime behavior unchanged

Reason:
- the ledger is integrity instrumentation, not the source of truth

## High-value runtime events for Phase 1
Mirror only these existing flight-recorder writes:
- `transition`
- `tool_call`
- `llm_call`
- `routing_decision`
- `task_feedback`

Do not mirror unrelated logs yet.

Reason:
- these are already centralized in `FlightRecorder`
- they cover the most useful runtime traces
- they are enough to verify append continuity and source integrity

## Verifier design
Add:
- `scripts/vera_flight_ledger_verify.py`

Verifier checks:
1. every line parses as JSON
2. first record is valid `GENESIS`
3. each `hash_prev` matches prior `hash_self`
4. each `hash_self` recomputes correctly
5. optional source integrity mode:
  - recompute `payload_sha256` against matching source event when available

Verifier exit classes:
- `0`
  - ledger valid
- `20`
  - warnings only, such as missing source event for optional cross-check
- `30`
  - hard integrity failure

## Rollout plan
### Phase 1
- implement append-only ledger mirror in `FlightRecorder`
- write `GENESIS` lazily on first append
- add verifier script
- add tests for:
  - genesis creation
  - hash chain continuity
  - tamper detection
  - non-fatal ledger write failure handling

### Phase 2
- expose simple operator status:
  - ledger path
  - entry count
  - last verified timestamp
  - last verify result

### Phase 3
- selectively extend the mirror to autonomy/verifier/runplane events only if they need the same integrity property
- do not merge everything into one universal ledger without measured need

## Why this design fits Vera
- keeps current `transitions.ndjson` and reward-model ingestion unchanged
- uses existing atomic append primitive
- gives cheap tamper evidence for the most important runtime trail
- avoids porting the PowerShell repo's regex-shell guard model, which is the wrong layer for Vera

## Next implementation task
Phase 1 implementation:
- add `ledger.jsonl` mirror append to `FlightRecorder`
- add `scripts/vera_flight_ledger_verify.py`
- add focused tests under `src/tests/`

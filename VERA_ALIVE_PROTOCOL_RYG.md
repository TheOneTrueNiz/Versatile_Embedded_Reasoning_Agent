# VERA Alive Protocol — R/Y/G Gate

Generated from `scripts/vera_alive_protocol_gate.py`.

## Latest Gate Results

1. Live tray runtime (`http://127.0.0.1:8788`)  
Source: `tmp/audits/20260224T164025Z/alive_protocol_gate.md`
- Green: 9
- Yellow: 3
- Red: 1
- Notes: live runtime is still pre-restart for latest reflection-timeout hardening and proactive-default changes.

2. Updated-code temp runtime (`http://127.0.0.1:8796`)  
Source: `tmp/audits/20260224T171122Z_temp8796_alive/alive_protocol_gate_temp8796.md`
- Green: 10
- Yellow: 2
- Red: 1

3. Reflection hardening validation (`http://127.0.0.1:8796`)  
Source: `tmp/audits/20260224T164906Z_temp8796/system_audit_temp8796_postfix.json`
- `innerlife_reflect_trigger`: PASS (`completed=False` + `deferred=True` accepted)
- `innerlife_reflect_persistence`: PASS (`journal_entries_before=22`, `after=23`, `reflections_incremented=True`)

## Current Status Board (Updated Code)

| Item | Status | Notes |
|---|---|---|
| Temporal continuity | GREEN | Time-since-last + reflections + last thought injected into prompt context. |
| Emotional carryover | GREEN | Sentiment/mood mapped and behavior guidance injected. |
| Self-narrative reasoning | GREEN | Personality deltas include one-sentence causal self-narrative. |
| Daily trace extraction | GREEN | Scheduler running with daily cadence and trace engine calls. |
| Workflow memory | GREEN | Plan lookup + replay result/quarantine wiring active. |
| Flight recorder -> distillation | GREEN | Ingestion path wired into learning cycle. |
| Context summarization at 50+ | GREEN | Trigger defaults to 50; recursive summarizer path active. |
| Partner model extraction | GREEN | Reflection hard constraint + structured relationship notes active. |
| Preference promotion -> identity | GREEN | High-confidence preferences promoted into core identity prompt. |
| Cross-channel continuity | YELLOW | Linking infra is wired; only API channel active in current runtime. |
| Proactive initiative | GREEN | Default-on proactive/calendar gates verified in updated code runtime. |
| LoRA cadence | YELLOW | Cadence wired, but this host runs mock backend (no CUDA/HF deps). |
| 24h alive-when-idle validation | RED | Deferred by operator directive until final stage. |

## Remaining Non-Green Path

1. Cross-channel continuity (YELLOW)
- Enable at least one additional active channel and verify same-thread handoff with shared link identity.
- Session-link primitives are now regression-tested in `src/tests/test_session_link_aliases.py`.

2. LoRA cadence (YELLOW)
- Run on CUDA host with `peft` + `datasets` available to move from mock to HF backend.

3. 24h alive-when-idle (RED, deferred)
- Run once final preconditions are complete.

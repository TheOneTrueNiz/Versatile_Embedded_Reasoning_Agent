# Remote Two-Way Messaging + Voice Plan (Vera-Centric)

## Objective

Enable reliable remote collaboration with Vera from mobile push context:
- Vera can proactively notify partner.
- Partner can respond remotely (text first, voice second).
- Vera remains the only cognitive authority (memory/planning/tooling).

## Non-Negotiable Architecture Rule

Grok Voice Agent (or any voice stack) is I/O only:
- Allowed: ASR (speech->text), TTS (text->speech), call/session transport.
- Not allowed: direct planning, direct tool execution, memory writes outside Vera runtime.
- All user input must route through Vera message processing before action.

## Current State

- Outbound native push exists and is working (`/api/push/native/test`, inner-life reach-out events).
- Ack ingest exists (`POST /api/push/native/ack`) with strict soak support.
- Web push click ack exists via service worker.
- Native token app flow currently re-registers token but may not auto-post ack.
- Backend fallback hardening now supports proxy ack on recent re-register windows.

## Target End State

Remote app supports:
1. Notification receipt from Vera.
2. Reply with text from notification/app.
3. Optional voice input/output while preserving Vera cognition path.
4. Shared conversation continuity with desktop/web channel.

## Phase 1 (MVP): Two-Way Text (No Voice Yet)

### API additions (server)

Add in `src/api/server.py`:
- `POST /api/push/native/message`
  - Authenticated device submits remote user text.
  - Payload: `device_id/token`, `session_link_id` (optional), `text`, `client_msg_id`, `timestamp`.
  - Server resolves/creates conversation context and routes to Vera runtime.
- `GET /api/push/native/thread`
  - Optional fetch of recent remote-visible thread items for app sync.

### Auth model

- Bind each registered native device to server-issued auth secret/token.
- Require signed/expiring request metadata for inbound message endpoint.
- Add nonce/replay protection and per-device rate limiting.

### Runtime routing

- Inbound remote text must call Vera processing path (same as standard chat pipeline).
- Response should be:
  - returned synchronously when fast, and/or
  - delivered asynchronously back to same device via native push.

### Persistence & telemetry

Add JSONL logs under `vera_memory/`:
- `mobile_inbound.jsonl`
- `mobile_outbound.jsonl`
- Include `session_link_id`, `conversation_id`, `run_id`, `device_id`, `source`.

## Phase 2: Voice Layer (Grok Voice Adapter)

### Voice adapter contract

Create a bridge module/service (new file, suggested):
- `src/core/services/remote_voice_bridge.py`

Responsibilities:
- Receive audio from mobile app.
- ASR -> transcript.
- Send transcript to Vera remote text endpoint.
- Receive Vera text reply.
- TTS reply -> audio payload/url to app.

### Hard guardrails

- Adapter cannot call Vera tools directly.
- Adapter cannot write memory directly.
- Adapter cannot bypass session link resolution.
- Adapter writes transport logs only; Vera writes cognition logs.

## Phase 3: Notification UX + Active Dialog

- Push notification actions:
  - Quick reply text
  - Open full app thread
  - Optional push-to-talk
- Correlate every interaction with `run_id`/`conversation_id`.
- Auto-ack on notification open/click from native app (explicit tier-3 evidence).

## Security Controls

- Per-device allowlist and revocation path.
- Signed requests with short TTL.
- Replay protection (nonce store + expiry).
- Per-device/per-IP rate limit buckets.
- Optional DND/priority controls for proactive reach-outs.

## Suggested File Hooks

- `src/api/server.py`
  - new endpoints, auth checks, rate-limit buckets, session mapping.
- `src/core/services/native_push_notifications.py`
  - targeted delivery helpers for remote conversation replies.
- `src/core/runtime/vera.py`
  - ensure remote source metadata is preserved through processing.
- `scripts/vera_proactive_soak_runner.py`
  - add optional remote message round-trip checks in future tier tests.

## Validation Plan

### MVP (text)

1. Remote inbound smoke:
   - POST remote text -> receives Vera response.
2. Continuity:
   - Desktop and remote app share same active session context.
3. Safety:
   - Invalid signature rejected.
   - Replay nonce rejected.
4. Delivery:
   - Vera outbound reply reaches originating device.

### Voice

1. ASR transcript enters Vera path (auditable).
2. Vera reply text returned and voiced by adapter.
3. No tool execution occurs outside Vera runtime logs.

## Release Gate (for this feature)

Ship when all are true:
- Remote text round-trip stable for >= 2h soak.
- No cognition bypass observed in logs.
- Session continuity confirmed across desktop + remote.
- Ack evidence captured for proactive notifications.
- Rate-limit/auth tests pass.

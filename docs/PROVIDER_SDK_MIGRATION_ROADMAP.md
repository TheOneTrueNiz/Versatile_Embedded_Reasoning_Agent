# Provider SDK Migration Roadmap

Status: planned after current runtime stabilization work

## Purpose

Move Vera from primarily OpenAI-compatible HTTP integrations to provider-native SDKs by default, while preserving the current compatibility path as fallback.

This is a transport-layer maturity upgrade, not a cognition rewrite.

## Current State

- xAI/Grok: direct `httpx` calls against `https://api.x.ai/v1`
- Anthropic: compatibility/native HTTP path, not first-party SDK-default
- Gemini: compatibility/native HTTP path, not first-party SDK-default
- OpenAI: compatibility/native HTTP path, not first-party SDK-default

## Target State

- xAI: `xai-sdk` is the default path for Grok
- Anthropic: official Anthropic SDK is the default path
- Gemini: official `google-genai` SDK is the default path
- OpenAI: official `openai` SDK is the default path
- Existing HTTP/OpenAI-compatible providers remain available as fallback rails

## Non-Goals

- Do not remove provider abstraction
- Do not hard-fork Vera into provider-specific application logic
- Do not block fallback behavior on SDK availability
- Do not mix this migration with unrelated autonomy/runtime hardening

## Why

Provider-native SDKs generally provide:

- better support for provider-specific capabilities
- faster compatibility with beta/preview features
- fewer edge-case mismatches versus compatibility APIs
- cleaner upgrade path for new transport primitives

## Risks

- SDK lock-in if abstraction is weakened
- drift in tool-calling semantics across providers
- streaming/event model differences
- more dependency surface area
- preview model instability, especially on xAI beta slugs

## Architecture

Keep the current provider abstraction and split each provider into two implementations where applicable:

- native SDK provider
- compatibility HTTP provider

Selection policy:

1. prefer native SDK provider when enabled and available
2. fall back to compatibility HTTP provider on import failure, unsupported feature, or provider-side error class
3. preserve provider fallback chain at the registry/router layer

## Proposed xAI Layout

- `GrokProviderXaiSdk`
- `GrokProviderCompat` or keep current `GrokProvider` as compat path
- registry chooses SDK path by default
- env gates:
  - `VERA_XAI_PROVIDER_MODE=sdk|compat|auto`
  - default: `sdk`

## Migration Phases

### Phase 1: xAI

- add `xai-sdk` dependency
- implement `GrokProviderXaiSdk`
- keep current `httpx` Grok provider as compatibility fallback
- validate:
  - chat completion
  - tool calls
  - streaming
  - model selection
  - graceful fallback to compat path

Ship gate:

- no regression in `run_vera_api.py`
- no regression in tool-calling path
- live fallback verified

### Phase 2: Anthropic

- add/activate official Anthropic SDK path
- preserve current compat/native HTTP fallback
- validate message/tool paths and streaming semantics

### Phase 3: Gemini

- add/activate official `google-genai` SDK path
- preserve current fallback path
- validate tool and multimodal behavior

### Phase 4: OpenAI

- switch OpenAI provider default to official SDK
- preserve compatibility path only where required

## Implementation Checklist

- [ ] add provider-mode config/env knobs
- [ ] add SDK availability detection
- [ ] add SDK provider classes
- [ ] add provider-level fallback policy
- [ ] add transport capability matrix
- [ ] add regression tests per provider
- [ ] add live smoke checks per provider
- [ ] update docs/runbook

## Validation Matrix

For each provider:

- simple text completion
- multi-turn conversation
- tool-calling
- stream path
- timeout behavior
- provider error mapping
- fallback on import failure
- fallback on transport failure

## Sequencing Decision

Do this after current runtime work is stable:

1. finish current Vera 2.0 runtime validation and hardening
2. confirm model selection is stable
3. migrate xAI first
4. defer Anthropic/Gemini/OpenAI SDK migration until xAI transport is proven

## Immediate Decision Rule

Until xAI reachability is verified:

- do not roll back the 4.20 model based on assumption
- only revert to `grok-4-1-fast-reasoning` if live xAI probe shows the 4.20 slug is unavailable or failing materially

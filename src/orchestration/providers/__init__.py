"""
VERA 2.0 - Multi-Provider LLM System
=====================================

Provider-agnostic LLM abstraction with fallback chains.
Supports Grok (primary), Claude, Gemini, and OpenAI/GPT.
"""

from orchestration.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCredential,
    ProviderHealth,
    ProviderStatus,
)
from orchestration.providers.registry import (
    FallbackChainConfig,
    ProviderRegistry,
)
from orchestration.providers.auth import (
    AuthProfileStore,
    resolve_credential,
)

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "ProviderCredential",
    "ProviderHealth",
    "ProviderStatus",
    "FallbackChainConfig",
    "ProviderRegistry",
    "AuthProfileStore",
    "resolve_credential",
]

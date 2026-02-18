"""
LLM Router
==========

Builds the provider registry and creates LLM bridges for VERA.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LLMRouter:
    """Encapsulates provider registry creation and LLM bridge wiring."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner
        self._registry = None

    def build_registry(self):
        """Build the multi-provider LLM registry with fallback chain."""
        try:
            from orchestration.providers.registry import ProviderRegistry, FallbackChainConfig
            from orchestration.providers.auth import resolve_credential
            from orchestration.providers.grok import GrokProvider
            from orchestration.providers.claude import ClaudeProvider
            from orchestration.providers.gemini import GeminiProvider
            from orchestration.providers.openai_provider import OpenAIProvider
        except ImportError as exc:
            logger.debug("Provider system not available: %s", exc)
            self._registry = None
            return None

        # Read fallback chain from env (default: grok,claude,gemini,openai)
        chain_str = os.getenv("VERA_LLM_PROVIDERS", "grok,claude,gemini,openai")
        chain = [p.strip().lower() for p in chain_str.split(",") if p.strip()]

        config = FallbackChainConfig(providers=chain)
        registry = ProviderRegistry(config)

        provider_classes = {
            "grok": GrokProvider,
            "claude": ClaudeProvider,
            "gemini": GeminiProvider,
            "openai": OpenAIProvider,
        }

        registered = []
        for provider_id in chain:
            cls = provider_classes.get(provider_id)
            if not cls:
                logger.debug("Unknown provider in chain: %s", provider_id)
                continue

            cred = resolve_credential(provider_id)
            if not cred:
                logger.debug("No credentials for provider: %s", provider_id)
                continue

            try:
                provider = cls(credential=cred)
                registry.register(provider)
                registered.append(provider_id)
            except Exception as exc:
                logger.warning("Failed to initialize provider %s: %s", provider_id, exc)

        if not registered:
            logger.info("No providers registered; using legacy single-provider mode")
            self._registry = None
            return None

        logger.info("Provider registry initialized: %s", " -> ".join(registered))
        self._registry = registry
        return registry

    @property
    def registry(self):
        return self._registry

    def create_bridge(self) -> Any:
        from orchestration.llm_bridge import LLMBridge
        return LLMBridge(self._owner, registry=self._registry)

"""
Provider Registry with Fallback Chains
========================================

Manages LLM providers and implements automatic failover.
Ported from Moltbot's model-fallback pattern.

Fallback chain: Grok -> Claude -> Gemini -> OpenAI/GPT
Any single provider can fully drive VERA's tool-calling harness.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from orchestration.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderHealth,
    ProviderStatus,
)

logger = logging.getLogger(__name__)


@dataclass
class FallbackChainConfig:
    """Configuration for the provider fallback chain."""
    # Ordered provider list: first is primary, rest are fallbacks
    providers: List[str] = field(
        default_factory=lambda: ["grok", "claude", "gemini", "openai"]
    )
    max_retries_per_provider: int = 2
    cooldown_seconds: float = 60.0
    max_consecutive_failures: int = 5
    backoff_multiplier: float = 2.0


class ProviderNotAvailableError(Exception):
    """Raised when no providers are available in the fallback chain."""

    def __init__(self, attempts: List[Dict[str, Any]]) -> None:
        self.attempts = attempts
        providers = [a["provider_id"] for a in attempts]
        errors = [f"{a['provider_id']}: {a['error']}" for a in attempts]
        super().__init__(
            f"All providers exhausted. Tried: {providers}. "
            f"Errors:\n" + "\n".join(f"  - {e}" for e in errors)
        )


class ProviderRegistry:
    """Manages LLM providers with automatic fallback.

    Tracks provider health, routes requests to the primary provider,
    and automatically falls back through the chain on failure.
    """

    def __init__(self, config: Optional[FallbackChainConfig] = None) -> None:
        self._config = config or FallbackChainConfig()
        self._providers: Dict[str, LLMProvider] = {}
        self._health: Dict[str, ProviderHealth] = {}
        self._active_provider_id: Optional[str] = None

    def register(self, provider: LLMProvider) -> None:
        """Register a provider. First registered becomes primary if in chain."""
        pid = provider.provider_id
        self._providers[pid] = provider
        self._health[pid] = ProviderHealth()
        logger.info(f"Registered LLM provider: {pid}")

        # Set active provider to first in the configured chain
        if self._active_provider_id is None:
            for chain_pid in self._config.providers:
                if chain_pid in self._providers:
                    self._active_provider_id = chain_pid
                    logger.info(f"Active provider set to: {chain_pid}")
                    break

    def get_provider(self, provider_id: str) -> Optional[LLMProvider]:
        """Get a specific provider by ID."""
        return self._providers.get(provider_id)

    def get_active_provider(self) -> Optional[LLMProvider]:
        """Get the current active (primary) provider."""
        if self._active_provider_id:
            return self._providers.get(self._active_provider_id)
        return None

    @property
    def active_provider_id(self) -> Optional[str]:
        return self._active_provider_id

    def get_health(self, provider_id: str) -> Optional[ProviderHealth]:
        """Get health status for a provider."""
        return self._health.get(provider_id)

    def get_all_health(self) -> Dict[str, ProviderHealth]:
        """Get health status for all registered providers."""
        return dict(self._health)

    def list_available(self) -> List[str]:
        """List provider IDs that are currently available."""
        available = []
        for pid in self._config.providers:
            if pid in self._providers:
                health = self._health.get(pid)
                if health and health.is_available:
                    available.append(pid)
        return available

    def list_registered(self) -> List[str]:
        """List all registered provider IDs."""
        return list(self._providers.keys())

    def mark_success(self, provider_id: str) -> None:
        """Record a successful request for a provider."""
        health = self._health.get(provider_id)
        if health:
            health.record_success()

    def mark_failure(self, provider_id: str, error: str) -> None:
        """Record a failed request for a provider."""
        health = self._health.get(provider_id)
        if health:
            health.record_failure(
                error,
                cooldown_seconds=self._config.cooldown_seconds,
                max_consecutive=self._config.max_consecutive_failures,
            )

    def _get_fallback_order(self) -> List[str]:
        """Get providers in fallback order, skipping unavailable ones."""
        order = []
        for pid in self._config.providers:
            if pid not in self._providers:
                continue
            health = self._health.get(pid)
            if health and health.is_available:
                order.append(pid)
            elif health and health.cooldown_until and time.time() >= health.cooldown_until:
                # Cooldown expired, give it another chance
                health.reset()
                order.append(pid)
        return order

    async def chat_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
        on_provider_switch: Optional[Any] = None,
    ) -> LLMResponse:
        """Execute a chat completion with automatic fallback on failure.

        Tries each provider in the fallback chain. If the primary fails,
        falls back to the next available provider. Tracks all attempts
        for error reporting.

        Args:
            messages: Conversation messages in OpenAI format
            tools: Tool schemas in OpenAI format (normalized per provider)
            tool_choice: Tool selection mode
            generation_config: LLM generation parameters
            model: Model override (provider-specific)
            on_provider_switch: Optional callback(old_id, new_id) when switching

        Returns:
            LLMResponse from the first successful provider

        Raises:
            ProviderNotAvailableError: If all providers fail
        """
        fallback_order = self._get_fallback_order()
        if not fallback_order:
            raise ProviderNotAvailableError([{
                "provider_id": "none",
                "error": "No providers registered or available",
            }])

        attempts: List[Dict[str, Any]] = []
        previous_provider = self._active_provider_id

        for pid in fallback_order:
            provider = self._providers[pid]

            # Notify about provider switch
            if previous_provider and pid != previous_provider and on_provider_switch:
                try:
                    await on_provider_switch(previous_provider, pid)
                except Exception:
                    logger.debug("Suppressed Exception in registry")
                    pass  # Don't let callback failures block the request

            for retry in range(self._config.max_retries_per_provider):
                try:
                    # Normalize tools and messages for this provider
                    provider_tools = None
                    if tools:
                        provider_tools = provider.normalize_tool_schemas(tools)
                    provider_messages = provider.normalize_messages(messages)

                    response = await provider.chat_completion(
                        messages=provider_messages,
                        tools=provider_tools,
                        tool_choice=tool_choice,
                        generation_config=generation_config,
                        model=model,
                    )

                    # Success
                    self.mark_success(pid)
                    self._active_provider_id = pid
                    if pid != previous_provider and previous_provider:
                        logger.info(
                            f"Provider fallback: {previous_provider} -> {pid}"
                        )
                    return response

                except Exception as e:
                    error_msg = f"{type(e).__name__}: {e}"
                    self.mark_failure(pid, error_msg)
                    attempts.append({
                        "provider_id": pid,
                        "retry": retry,
                        "error": error_msg,
                        "timestamp": time.time(),
                    })
                    logger.warning(
                        f"Provider {pid} failed (attempt {retry + 1}/"
                        f"{self._config.max_retries_per_provider}): {error_msg}"
                    )

                    # Check if we should retry or move to next provider
                    health = self._health.get(pid)
                    if health and not health.is_available:
                        break  # Provider went into cooldown/failed

            previous_provider = pid

        raise ProviderNotAvailableError(attempts)

    async def stream_with_fallback(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream a chat completion with fallback.

        Falls back to non-streaming if streaming fails, then to
        the next provider in the chain.
        """
        fallback_order = self._get_fallback_order()
        if not fallback_order:
            raise ProviderNotAvailableError([{
                "provider_id": "none",
                "error": "No providers registered or available",
            }])

        attempts: List[Dict[str, Any]] = []

        for pid in fallback_order:
            provider = self._providers[pid]
            if not provider.supports_streaming():
                continue

            try:
                provider_tools = None
                if tools:
                    provider_tools = provider.normalize_tool_schemas(tools)
                provider_messages = provider.normalize_messages(messages)

                async for chunk in provider.stream_completion(
                    messages=provider_messages,
                    tools=provider_tools,
                    generation_config=generation_config,
                    model=model,
                ):
                    yield chunk

                self.mark_success(pid)
                self._active_provider_id = pid
                return

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                self.mark_failure(pid, error_msg)
                attempts.append({
                    "provider_id": pid,
                    "error": error_msg,
                })
                logger.warning(f"Stream failed for {pid}: {error_msg}")

        raise ProviderNotAvailableError(attempts)

    async def close_all(self) -> None:
        """Close all registered providers."""
        for pid, provider in self._providers.items():
            try:
                await provider.close()
                logger.debug(f"Closed provider: {pid}")
            except Exception as e:
                logger.warning(f"Error closing provider {pid}: {e}")

    def status_summary(self) -> Dict[str, Any]:
        """Get a summary of all providers and their health."""
        return {
            "active_provider": self._active_provider_id,
            "fallback_chain": self._config.providers,
            "registered": list(self._providers.keys()),
            "available": self.list_available(),
            "health": {
                pid: {
                    "status": h.status.value,
                    "error_count": h.error_count,
                    "consecutive_failures": h.consecutive_failures,
                    "last_error": h.last_error,
                    "total_requests": h.total_requests,
                }
                for pid, h in self._health.items()
            },
        }

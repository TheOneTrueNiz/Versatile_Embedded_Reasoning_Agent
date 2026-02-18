"""
LLM Provider Base Abstractions
===============================

Abstract interface and shared data types for all LLM providers.
Each provider (Grok, Claude, Gemini, OpenAI) implements LLMProvider
to normalize tool calling, streaming, and response formats.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProviderStatus(Enum):
    """Health status of an LLM provider."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    COOLDOWN = "cooldown"


@dataclass
class ProviderCredential:
    """Credential for authenticating with an LLM provider."""
    provider_id: str
    credential_type: str  # "api_key", "token", "oauth"
    key: str
    base_url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        masked = self.key[:4] + "..." + self.key[-4:] if len(self.key) > 8 else "***"
        return (
            f"ProviderCredential(provider_id={self.provider_id!r}, "
            f"type={self.credential_type!r}, key={masked!r})"
        )


@dataclass
class ProviderHealth:
    """Health and error tracking for a provider."""
    status: ProviderStatus = ProviderStatus.HEALTHY
    error_count: int = 0
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    last_error_at: Optional[float] = None
    cooldown_until: Optional[float] = None
    last_success_at: Optional[float] = None
    total_requests: int = 0
    total_failures: int = 0

    @property
    def is_available(self) -> bool:
        """Check if provider is available (not in cooldown or permanently failed)."""
        if self.status == ProviderStatus.FAILED:
            return False
        if self.cooldown_until and time.time() < self.cooldown_until:
            return False
        return True

    def record_success(self) -> None:
        """Record a successful request."""
        self.consecutive_failures = 0
        self.last_success_at = time.time()
        self.total_requests += 1
        self.status = ProviderStatus.HEALTHY
        # Clear cooldown on success
        self.cooldown_until = None

    def record_failure(self, error: str, cooldown_seconds: float = 60.0,
                       max_consecutive: int = 5) -> None:
        """Record a failed request. Enter cooldown after max_consecutive failures."""
        self.error_count += 1
        self.consecutive_failures += 1
        self.total_failures += 1
        self.total_requests += 1
        self.last_error = error
        self.last_error_at = time.time()

        if self.consecutive_failures >= max_consecutive:
            self.status = ProviderStatus.FAILED
            logger.warning(
                f"Provider marked FAILED after {self.consecutive_failures} "
                f"consecutive failures: {error}"
            )
        elif self.consecutive_failures >= 2:
            self.status = ProviderStatus.COOLDOWN
            self.cooldown_until = time.time() + cooldown_seconds
            logger.info(
                f"Provider entering cooldown for {cooldown_seconds}s "
                f"after {self.consecutive_failures} failures"
            )
        else:
            self.status = ProviderStatus.DEGRADED

    def reset(self) -> None:
        """Reset health to healthy state."""
        self.status = ProviderStatus.HEALTHY
        self.consecutive_failures = 0
        self.cooldown_until = None


@dataclass
class LLMResponse:
    """Normalized response from any LLM provider.

    All providers convert their native response format into this
    canonical structure so the rest of VERA doesn't need to know
    which provider generated it.
    """
    content: str
    tool_calls: List[Dict[str, Any]]
    raw_message: Dict[str, Any]
    model: str
    provider_id: str
    usage: Optional[Dict[str, int]] = None
    finish_reason: Optional[str] = None
    reasoning_content: Optional[str] = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def input_tokens(self) -> int:
        if self.usage:
            return self.usage.get("prompt_tokens", 0)
        return 0

    @property
    def output_tokens(self) -> int:
        if self.usage:
            return self.usage.get("completion_tokens", 0)
        return 0

    def to_openai_message(self) -> Dict[str, Any]:
        """Convert to OpenAI-format assistant message for history."""
        msg: Dict[str, Any] = {
            "role": "assistant",
            "content": self.content,
        }
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


class LLMProvider(ABC):
    """Abstract interface for an LLM provider.

    Each provider (Grok, Claude, Gemini, OpenAI) implements this interface
    to normalize API communication. The ProviderRegistry uses these to
    implement fallback chains.

    Tool schemas are provided in OpenAI format (the canonical format).
    Providers that use a different format override normalize_tool_schemas()
    to convert.
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique identifier: 'grok', 'claude', 'gemini', 'openai'."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model for this provider."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: Conversation history in OpenAI format
                      [{"role": "system"|"user"|"assistant"|"tool", "content": ...}]
            tools: Tool definitions in OpenAI format (will be normalized per provider)
            tool_choice: Tool selection mode ("auto", "none", or specific tool)
            generation_config: Temperature, top_p, max_tokens, etc.
            model: Override the default model for this request

        Returns:
            Normalized LLMResponse
        """
        ...

    @abstractmethod
    async def stream_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Stream a chat completion. Yields normalized delta chunks.

        Each chunk is a dict with:
            {"type": "text_delta", "content": "..."}
            {"type": "tool_call_delta", "tool_call": {...}}
            {"type": "done", "usage": {...}}
        """
        ...

    def normalize_tool_schemas(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-format tool schemas to this provider's format.

        Default implementation returns tools unchanged (works for
        OpenAI-compatible providers like Grok and GPT).
        Override for providers with different formats (Claude, Gemini).
        """
        return tools

    def normalize_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI-format messages to this provider's format.

        Default implementation returns messages unchanged.
        Override for providers with different message formats.
        """
        return messages

    @abstractmethod
    def normalize_response(
        self, raw_response: Dict[str, Any]
    ) -> LLMResponse:
        """Convert provider-specific response to normalized LLMResponse."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Shut down HTTP client and release resources."""
        ...

    def supports_tool_calling(self) -> bool:
        """Whether this provider supports function/tool calling."""
        return True

    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming responses."""
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider_id={self.provider_id!r})"

"""
OpenAI/GPT Provider
====================

LLM provider for OpenAI's GPT models. Last in the fallback chain.
Uses the same OpenAI-compatible format as Grok, but with
OpenAI's base URL and auth.
"""

import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from orchestration.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCredential,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.2"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAIProvider(LLMProvider):
    """OpenAI GPT provider. Last resort in the fallback chain.

    Uses OpenAI-compatible format (same as Grok), so tool schemas
    and messages pass through without conversion.
    """

    def __init__(
        self,
        credential: ProviderCredential,
        model: Optional[str] = None,
        timeout: float = 60.0,
    ):
        self._credential = credential
        self._model = model or DEFAULT_MODEL
        base_url = credential.base_url or DEFAULT_BASE_URL
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            base_url=self._base_url,
        )

    @property
    def provider_id(self) -> str:
        return "openai"

    @property
    def default_model(self) -> str:
        return self._model

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._credential.key}",
        }

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        start_time = time.time()
        payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        if generation_config:
            for key in ("temperature", "top_p", "max_tokens",
                        "frequency_penalty", "presence_penalty"):
                if key in generation_config and generation_config[key] is not None:
                    payload[key] = generation_config[key]

        headers = self._build_headers()
        response = await self._client.post(
            "/chat/completions", headers=headers, json=payload
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            error_msg = f"OpenAI API error {response.status_code}: {detail[:500]}"
            raise RuntimeError(error_msg) from exc

        data = response.json()
        latency_ms = (time.time() - start_time) * 1000
        logger.debug(f"OpenAI response in {latency_ms:.0f}ms")

        return self.normalize_response(data)

    async def stream_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        if generation_config:
            for key in ("temperature", "top_p", "max_tokens"):
                if key in generation_config and generation_config[key] is not None:
                    payload[key] = generation_config[key]

        headers = self._build_headers()
        async with self._client.stream(
            "POST", "/chat/completions", headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    yield {"type": "done"}
                    break

                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                if delta.get("content"):
                    yield {"type": "text_delta", "content": delta["content"]}
                if delta.get("tool_calls"):
                    yield {"type": "tool_call_delta", "tool_calls": delta["tool_calls"]}

                if chunk.get("usage"):
                    yield {"type": "usage", "usage": chunk["usage"]}

    def normalize_response(self, raw_response: Dict[str, Any]) -> LLMResponse:
        choices = raw_response.get("choices", [])
        if not choices:
            return LLMResponse(
                content="",
                tool_calls=[],
                raw_message={},
                model=raw_response.get("model", self._model),
                provider_id=self.provider_id,
                usage=raw_response.get("usage"),
                finish_reason="error",
            )

        message = choices[0].get("message", {})
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls") or []

        normalized_tools = []
        for tc in tool_calls:
            normalized_tools.append({
                "id": tc.get("id", ""),
                "type": "function",
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                },
            })

        return LLMResponse(
            content=content,
            tool_calls=normalized_tools,
            raw_message=message,
            model=raw_response.get("model", self._model),
            provider_id=self.provider_id,
            usage=raw_response.get("usage"),
            finish_reason=choices[0].get("finish_reason"),
        )

    async def close(self) -> None:
        await self._client.aclose()

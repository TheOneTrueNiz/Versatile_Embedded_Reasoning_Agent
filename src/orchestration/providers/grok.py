"""
Grok/xAI Provider
==================

LLM provider for xAI's Grok models via their OpenAI-compatible API.
This is VERA's primary (default) provider.

Extracted from the original GrokReasoningBridge._call_chat() method.
"""

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

DEFAULT_MODEL = "grok-4-1-fast-reasoning"
DEFAULT_BASE_URL = "https://api.x.ai/v1"


class GrokProvider(LLMProvider):
    """xAI Grok provider using OpenAI-compatible API format.

    This is VERA's primary provider. Since xAI uses OpenAI-compatible
    format, tool schemas and messages pass through without conversion.
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
        return "grok"

    @property
    def default_model(self) -> str:
        return self._model

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._credential.key:
            headers["Authorization"] = f"Bearer {self._credential.key}"
        return headers

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

        if tool_choice and tool_choice != "auto":
            logger.info("Grok API payload tool_choice=%s tools_count=%s", tool_choice, len(tools) if tools else 0)

        headers = self._build_headers()
        response = await self._client.post(
            "/chat/completions", headers=headers, json=payload
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            # Fallback: retry without tools on 400
            if response.status_code == 400 and tools:
                logger.warning(
                    f"Grok 400 with tools, retrying without: {detail[:200]}"
                )
                fallback = dict(payload)
                fallback.pop("tools", None)
                fallback.pop("tool_choice", None)
                retry = await self._client.post(
                    "/chat/completions", headers=headers, json=fallback
                )
                retry.raise_for_status()
                data = retry.json()
                return self.normalize_response(data)

            error_msg = f"Grok API error {response.status_code}: {detail[:500]}"
            raise RuntimeError(error_msg) from exc

        data = response.json()
        latency_ms = (time.time() - start_time) * 1000
        finish = data.get("choices", [{}])[0].get("finish_reason", "?")
        has_tool_calls = bool(data.get("choices", [{}])[0].get("message", {}).get("tool_calls"))
        logger.debug(f"Grok response in {latency_ms:.0f}ms finish_reason={finish} has_tool_calls={has_tool_calls}")

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

                import json
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

        # Normalize tool_calls to canonical format
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

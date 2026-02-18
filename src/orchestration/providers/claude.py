"""
Claude/Anthropic Provider
==========================

LLM provider for Anthropic's Claude models. Second in the fallback chain.

Handles the Anthropic Messages API format, which differs from OpenAI:
- System prompt is a separate parameter, not a message
- Tool calling uses tool_use/tool_result content blocks
- Response structure uses content blocks instead of flat content
"""

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from orchestration.providers.base import (
    LLMProvider,
    LLMResponse,
    ProviderCredential,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"


class ClaudeProvider(LLMProvider):
    """Anthropic Claude provider. Second in the fallback chain.

    Normalizes between OpenAI and Anthropic message formats:
    - System messages are extracted to a separate parameter
    - Tool schemas are converted to Anthropic's input_schema format
    - tool_use/tool_result content blocks map to OpenAI's tool_calls format
    """

    def __init__(
        self,
        credential: ProviderCredential,
        model: Optional[str] = None,
        timeout: float = 120.0,
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
        return "claude"

    @property
    def default_model(self) -> str:
        return self._model

    def _build_headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self._credential.key,
            "anthropic-version": API_VERSION,
        }

    def normalize_tool_schemas(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Anthropic tool format.

        OpenAI:  {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Anthropic: {"name": ..., "description": ..., "input_schema": ...}
        """
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return anthropic_tools

    def normalize_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI messages to Anthropic format.

        - Strips system messages (handled separately)
        - Converts tool role messages to tool_result content blocks
        - Ensures alternating user/assistant pattern
        """
        anthropic_messages = []

        for msg in messages:
            role = msg.get("role", "")

            # Skip system messages (extracted separately in chat_completion)
            if role == "system":
                continue

            if role == "tool":
                # OpenAI tool results become user messages with tool_result content
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif role == "assistant":
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                if tool_calls:
                    # Build content blocks: text + tool_use blocks
                    blocks: List[Dict[str, Any]] = []
                    if content:
                        blocks.append({"type": "text", "text": content})
                    for tc in tool_calls:
                        func = tc.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}
                        blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", str(uuid.uuid4())),
                            "name": func.get("name", ""),
                            "input": args,
                        })
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": blocks,
                    })
                else:
                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content,
                    })
            elif role == "user":
                anthropic_messages.append({
                    "role": "user",
                    "content": msg.get("content", ""),
                })

        # Anthropic requires messages start with user role
        # and alternate user/assistant. Merge adjacent same-role messages.
        merged = []
        for msg in anthropic_messages:
            if merged and merged[-1]["role"] == msg["role"]:
                # Merge content
                prev_content = merged[-1]["content"]
                new_content = msg["content"]
                if isinstance(prev_content, str) and isinstance(new_content, str):
                    merged[-1]["content"] = prev_content + "\n" + new_content
                elif isinstance(prev_content, list) and isinstance(new_content, list):
                    merged[-1]["content"] = prev_content + new_content
                elif isinstance(prev_content, str) and isinstance(new_content, list):
                    merged[-1]["content"] = [{"type": "text", "text": prev_content}] + new_content
                elif isinstance(prev_content, list) and isinstance(new_content, str):
                    merged[-1]["content"] = prev_content + [{"type": "text", "text": new_content}]
            else:
                merged.append(msg)

        return merged

    def _extract_system(self, messages: List[Dict[str, Any]]) -> str:
        """Extract and join all system messages from the original OpenAI messages."""
        system_parts = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if content:
                    system_parts.append(content)
        return "\n\n".join(system_parts)

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        start_time = time.time()

        # Messages passed here are already normalized by normalize_messages(),
        # but we need the original messages for system extraction.
        # The registry calls normalize_messages() before passing to us,
        # so system messages are already stripped. We need to handle this
        # by accepting that system is passed via generation_config or
        # was already extracted.

        payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "max_tokens": 8192,
        }

        # System prompt from generation_config (set by the bridge)
        if generation_config:
            if "system" in generation_config:
                payload["system"] = generation_config.pop("system")
            if "temperature" in generation_config:
                payload["temperature"] = generation_config["temperature"]
            if "top_p" in generation_config:
                payload["top_p"] = generation_config["top_p"]
            if "max_tokens" in generation_config:
                payload["max_tokens"] = generation_config["max_tokens"]

        if tools:
            payload["tools"] = tools
            if tool_choice:
                if isinstance(tool_choice, str) and tool_choice == "auto":
                    payload["tool_choice"] = {"type": "auto"}
                elif isinstance(tool_choice, str) and tool_choice == "none":
                    payload["tool_choice"] = {"type": "none"}
                elif isinstance(tool_choice, dict):
                    # Specific tool: {"type": "function", "function": {"name": "..."}}
                    func_name = tool_choice.get("function", {}).get("name", "")
                    if func_name:
                        payload["tool_choice"] = {"type": "tool", "name": func_name}

        headers = self._build_headers()
        response = await self._client.post(
            "/v1/messages", headers=headers, json=payload
        )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            error_msg = f"Claude API error {response.status_code}: {detail[:500]}"
            raise RuntimeError(error_msg) from exc

        data = response.json()
        latency_ms = (time.time() - start_time) * 1000
        logger.debug(f"Claude response in {latency_ms:.0f}ms")

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
            "max_tokens": 8192,
            "stream": True,
        }

        if generation_config:
            if "system" in generation_config:
                payload["system"] = generation_config.pop("system")
            if "temperature" in generation_config:
                payload["temperature"] = generation_config["temperature"]
            if "max_tokens" in generation_config:
                payload["max_tokens"] = generation_config["max_tokens"]

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = {"type": "auto"}

        headers = self._build_headers()
        async with self._client.stream(
            "POST", "/v1/messages", headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]

                try:
                    event = json.loads(data_str)
                except Exception:
                    continue

                event_type = event.get("type", "")

                if event_type == "content_block_delta":
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta":
                        yield {"type": "text_delta", "content": delta.get("text", "")}
                    elif delta.get("type") == "input_json_delta":
                        yield {"type": "tool_call_delta", "partial_json": delta.get("partial_json", "")}
                elif event_type == "message_delta":
                    usage = event.get("usage", {})
                    if usage:
                        yield {"type": "usage", "usage": {
                            "prompt_tokens": 0,
                            "completion_tokens": usage.get("output_tokens", 0),
                        }}
                elif event_type == "message_stop":
                    yield {"type": "done"}

    def normalize_response(self, raw_response: Dict[str, Any]) -> LLMResponse:
        """Convert Anthropic response to normalized LLMResponse.

        Anthropic returns content as an array of blocks:
        [{"type": "text", "text": "..."}, {"type": "tool_use", "id": "...", ...}]
        """
        content_blocks = raw_response.get("content", [])
        text_parts = []
        tool_calls = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                # Convert to OpenAI tool_call format
                tool_calls.append({
                    "id": block.get("id", str(uuid.uuid4())),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        content = "\n".join(text_parts)

        # Build usage in OpenAI format
        usage_data = raw_response.get("usage", {})
        usage = None
        if usage_data:
            usage = {
                "prompt_tokens": usage_data.get("input_tokens", 0),
                "completion_tokens": usage_data.get("output_tokens", 0),
                "total_tokens": (
                    usage_data.get("input_tokens", 0)
                    + usage_data.get("output_tokens", 0)
                ),
            }

        # Map Anthropic stop_reason to OpenAI finish_reason
        stop_reason = raw_response.get("stop_reason", "")
        finish_reason_map = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
        }
        finish_reason = finish_reason_map.get(stop_reason, stop_reason)

        # Build a synthetic OpenAI-format message for raw_message
        raw_message: Dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls:
            raw_message["tool_calls"] = tool_calls

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            raw_message=raw_message,
            model=raw_response.get("model", self._model),
            provider_id=self.provider_id,
            usage=usage,
            finish_reason=finish_reason,
        )

    async def close(self) -> None:
        await self._client.aclose()

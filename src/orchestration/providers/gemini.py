"""
Gemini/Google Provider
=======================

LLM provider for Google's Gemini models. Third in the fallback chain.

Handles the Google Generative Language API format, which differs from OpenAI:
- Uses generateContent endpoint
- functionDeclarations instead of tools
- functionCall/functionResponse parts instead of tool_calls
- Content uses parts[] array with text/functionCall/functionResponse
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

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiProvider(LLMProvider):
    """Google Gemini provider. Third in the fallback chain.

    Normalizes between OpenAI and Google Generative Language API formats.
    The API key is passed as a query parameter, not a header.
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
        self._client = httpx.AsyncClient(timeout=timeout)

    @property
    def provider_id(self) -> str:
        return "gemini"

    @property
    def default_model(self) -> str:
        return self._model

    def _build_url(self, model: str, action: str = "generateContent") -> str:
        return (
            f"{self._base_url}/v1beta/models/{model}:{action}"
            f"?key={self._credential.key}"
        )

    def normalize_tool_schemas(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI tool format to Gemini functionDeclarations format.

        OpenAI:  {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        Gemini:  {"functionDeclarations": [{"name": ..., "description": ..., "parameters": ...}]}
        """
        declarations = []
        for tool in tools:
            func = tool.get("function", {})
            params = func.get("parameters", {})

            # Gemini doesn't support all JSON Schema features.
            # Clean up the parameters schema.
            cleaned_params = self._clean_schema(params)

            declarations.append({
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": cleaned_params,
            })

        return [{"functionDeclarations": declarations}] if declarations else []

    def _clean_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Clean JSON Schema for Gemini compatibility.

        Gemini has limited JSON Schema support - remove unsupported fields.
        """
        cleaned = {}
        for key, val in schema.items():
            # Gemini doesn't support these
            if key in ("additionalProperties", "$schema", "default", "examples"):
                continue
            if key == "properties" and isinstance(val, dict):
                cleaned[key] = {
                    k: self._clean_schema(v) if isinstance(v, dict) else v
                    for k, v in val.items()
                }
            elif key == "items" and isinstance(val, dict):
                cleaned[key] = self._clean_schema(val)
            else:
                cleaned[key] = val
        return cleaned

    def normalize_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert OpenAI messages to Gemini contents format.

        Gemini uses:
        - "user" and "model" roles (not "assistant")
        - parts[] array instead of content string
        - system instructions are separate
        """
        gemini_contents = []

        for msg in messages:
            role = msg.get("role", "")

            # System messages handled separately
            if role == "system":
                continue

            gemini_role = "model" if role == "assistant" else "user"

            if role == "tool":
                # Tool results become user messages with functionResponse part
                gemini_contents.append({
                    "role": "user",
                    "parts": [{
                        "functionResponse": {
                            "name": msg.get("name", msg.get("tool_call_id", "unknown")),
                            "response": {"result": msg.get("content", "")},
                        }
                    }],
                })
            elif role == "assistant":
                parts: List[Dict[str, Any]] = []
                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                if content:
                    parts.append({"text": content})

                for tc in tool_calls:
                    func = tc.get("function", {})
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        args = {}
                    parts.append({
                        "functionCall": {
                            "name": func.get("name", ""),
                            "args": args,
                        }
                    })

                if parts:
                    gemini_contents.append({"role": "model", "parts": parts})
            else:
                content = msg.get("content", "")
                gemini_contents.append({
                    "role": "user",
                    "parts": [{"text": content}],
                })

        # Merge adjacent same-role messages
        merged = []
        for msg in gemini_contents:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["parts"].extend(msg["parts"])
            else:
                merged.append(msg)

        return merged

    def _extract_system(self, messages: List[Dict[str, Any]]) -> Optional[str]:
        """Extract system instructions from original OpenAI messages."""
        parts = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if content:
                    parts.append(content)
        return "\n\n".join(parts) if parts else None

    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> LLMResponse:
        start_time = time.time()
        use_model = model or self._model

        payload: Dict[str, Any] = {
            "contents": messages,  # Already normalized by registry
        }

        # System instruction from generation_config
        if generation_config and "system" in generation_config:
            payload["systemInstruction"] = {
                "parts": [{"text": generation_config.pop("system")}]
            }

        # Generation config
        gen_config = {}
        if generation_config:
            if "temperature" in generation_config:
                gen_config["temperature"] = generation_config["temperature"]
            if "top_p" in generation_config:
                gen_config["topP"] = generation_config["top_p"]
            if "max_tokens" in generation_config:
                gen_config["maxOutputTokens"] = generation_config["max_tokens"]
        if gen_config:
            payload["generationConfig"] = gen_config

        if tools:
            payload["tools"] = tools

        url = self._build_url(use_model)
        headers = {"Content-Type": "application/json"}
        response = await self._client.post(url, headers=headers, json=payload)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text.strip()
            error_msg = f"Gemini API error {response.status_code}: {detail[:500]}"
            raise RuntimeError(error_msg) from exc

        data = response.json()
        latency_ms = (time.time() - start_time) * 1000
        logger.debug(f"Gemini response in {latency_ms:.0f}ms")

        return self.normalize_response(data)

    async def stream_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        generation_config: Optional[Dict[str, Any]] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        use_model = model or self._model

        payload: Dict[str, Any] = {
            "contents": messages,
        }

        if generation_config and "system" in generation_config:
            payload["systemInstruction"] = {
                "parts": [{"text": generation_config.pop("system")}]
            }

        gen_config = {}
        if generation_config:
            if "temperature" in generation_config:
                gen_config["temperature"] = generation_config["temperature"]
            if "max_tokens" in generation_config:
                gen_config["maxOutputTokens"] = generation_config["max_tokens"]
        if gen_config:
            payload["generationConfig"] = gen_config

        if tools:
            payload["tools"] = tools

        url = self._build_url(use_model, "streamGenerateContent")
        url += "&alt=sse"
        headers = {"Content-Type": "application/json"}

        async with self._client.stream(
            "POST", url, headers=headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]

                try:
                    chunk = json.loads(data_str)
                except Exception:
                    continue

                candidates = chunk.get("candidates", [])
                if not candidates:
                    continue

                content = candidates[0].get("content", {})
                parts = content.get("parts", [])

                for part in parts:
                    if "text" in part:
                        yield {"type": "text_delta", "content": part["text"]}
                    elif "functionCall" in part:
                        fc = part["functionCall"]
                        yield {
                            "type": "tool_call_delta",
                            "tool_calls": [{
                                "function": {
                                    "name": fc.get("name", ""),
                                    "arguments": json.dumps(fc.get("args", {})),
                                }
                            }],
                        }

                if candidates[0].get("finishReason"):
                    usage = chunk.get("usageMetadata", {})
                    if usage:
                        yield {
                            "type": "usage",
                            "usage": {
                                "prompt_tokens": usage.get("promptTokenCount", 0),
                                "completion_tokens": usage.get("candidatesTokenCount", 0),
                            },
                        }
                    yield {"type": "done"}

    def normalize_response(self, raw_response: Dict[str, Any]) -> LLMResponse:
        """Convert Gemini response to normalized LLMResponse.

        Gemini returns candidates[0].content.parts[] with text and functionCall parts.
        """
        candidates = raw_response.get("candidates", [])
        if not candidates:
            return LLMResponse(
                content="",
                tool_calls=[],
                raw_message={},
                model=self._model,
                provider_id=self.provider_id,
                finish_reason="error",
            )

        content_obj = candidates[0].get("content", {})
        parts = content_obj.get("parts", [])

        text_parts = []
        tool_calls = []

        for part in parts:
            if "text" in part:
                text_parts.append(part["text"])
            elif "functionCall" in part:
                fc = part["functionCall"]
                tool_calls.append({
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {
                        "name": fc.get("name", ""),
                        "arguments": json.dumps(fc.get("args", {})),
                    },
                })

        content = "\n".join(text_parts)

        # Build usage in OpenAI format
        usage_meta = raw_response.get("usageMetadata", {})
        usage = None
        if usage_meta:
            prompt_tokens = usage_meta.get("promptTokenCount", 0)
            completion_tokens = usage_meta.get("candidatesTokenCount", 0)
            usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }

        # Map Gemini finish reason to OpenAI format
        finish_reason_raw = candidates[0].get("finishReason", "")
        finish_reason_map = {
            "STOP": "stop",
            "MAX_TOKENS": "length",
            "SAFETY": "content_filter",
            "RECITATION": "content_filter",
            "OTHER": "stop",
        }
        finish_reason = finish_reason_map.get(finish_reason_raw, "stop")
        if tool_calls:
            finish_reason = "tool_calls"

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
            model=self._model,
            provider_id=self.provider_id,
            usage=usage,
            finish_reason=finish_reason,
        )

    async def close(self) -> None:
        await self._client.aclose()

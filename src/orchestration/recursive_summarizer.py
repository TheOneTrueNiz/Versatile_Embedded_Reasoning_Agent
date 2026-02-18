#!/usr/bin/env python3
"""
Recursive Summarizer
====================

Chunk -> map -> reduce -> recurse summarizer for long-context inputs.
Uses xAI's chat completions endpoint without tool-calling.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx


class RecursiveSummarizer:
    """Recursive long-context summarizer with map/reduce passes."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        model: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model or os.getenv("VERA_RECURSIVE_MODEL", "grok-4-1-fast-reasoning")
        self.timeout = timeout

    async def summarize(
        self,
        text: str,
        goal: Optional[str] = None,
        max_chunk_chars: int = 4000,
        overlap_chars: int = 200,
        target_chars: int = 1800,
        max_rounds: int = 4,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not text.strip():
            return {"error": "text is required"}

        summary = text
        rounds = 0
        chunks = 0
        chosen_model = model or self.model

        while len(summary) > target_chars and rounds < max_rounds:
            rounds += 1
            parts = self._chunk_text(summary, max_chunk_chars, overlap_chars)
            chunks = max(chunks, len(parts))

            mapped = []
            for part in parts:
                mapped.append(
                    await self._summarize_chunk(part, goal=goal, model=chosen_model)
                )

            summary = await self._reduce_summaries(mapped, goal=goal, model=chosen_model)

        return {
            "summary": summary.strip(),
            "rounds": rounds,
            "chunks": chunks,
            "model": chosen_model,
        }

    def _chunk_text(self, text: str, max_chars: int, overlap_chars: int) -> List[str]:
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0

        for para in paragraphs:
            if current_len + len(para) + 2 > max_chars and current:
                chunk = "\n\n".join(current)
                chunks.append(chunk)
                if overlap_chars > 0:
                    tail = chunk[-overlap_chars:]
                    current = [tail]
                    current_len = len(tail)
                else:
                    current = []
                    current_len = 0

            current.append(para)
            current_len += len(para) + 2

        if current:
            chunks.append("\n\n".join(current))

        return chunks or [text]

    async def _summarize_chunk(self, chunk: str, goal: Optional[str], model: str) -> str:
        task = "Summarize the chunk into concise bullet points."
        if goal:
            task = f"Summarize the chunk with focus on: {goal}"
        prompt = f"{task}\n\nChunk:\n{chunk}"
        return await self._call_llm(prompt, model)

    async def _reduce_summaries(self, summaries: List[str], goal: Optional[str], model: str) -> str:
        joined = "\n".join(f"- {summary.strip()}" for summary in summaries if summary.strip())
        task = "Merge the summaries into a coherent, concise narrative."
        if goal:
            task = f"Merge the summaries with focus on: {goal}"
        prompt = f"{task}\n\nSummaries:\n{joined}"
        return await self._call_llm(prompt, model)

    async def _call_llm(self, prompt: str, model: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a concise summarizer. Return only the summary.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, base_url=self.base_url) as client:
            response = await client.post("/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return ""
        return choices[0].get("message", {}).get("content", "").strip()

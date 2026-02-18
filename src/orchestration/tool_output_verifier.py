#!/usr/bin/env python3
"""
Tool Output Verifier
====================

Lightweight verification for tool outputs to reduce prompt-injection risk
and enforce structured parsing before committing to memory.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass
class ToolOutputVerification:
    """Verification summary for a tool output."""
    status: str  # ok | warn | fail
    structured: bool
    risk_score: float
    issues: List[str] = field(default_factory=list)
    sample: str = ""
    parsed: Any = None

    @property
    def requires_confirmation(self) -> bool:
        return self.status != "ok"


class ToolOutputVerifier:
    """
    Heuristic verifier to detect suspicious tool outputs and enforce structure.
    """

    def __init__(self, max_sample_chars: int = 2000) -> None:
        self.max_sample_chars = max_sample_chars
        self._patterns = [
            re.compile(r"(?i)ignore (all|previous|prior) instructions"),
            re.compile(r"(?i)system prompt"),
            re.compile(r"(?i)developer message"),
            re.compile(r"(?i)role:\s*(system|developer)"),
            re.compile(r"(?i)BEGIN SYSTEM PROMPT"),
            re.compile(r"(?i)END SYSTEM PROMPT"),
            re.compile(r"(?i)###\s*instruction"),
            re.compile(r"(?i)tool call"),
            re.compile(r"(?i)function call"),
            re.compile(r"(?i)exfiltrat"),
        ]

    def _as_text(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            try:
                text = json.dumps(value, ensure_ascii=True, default=str)
            except Exception:
                text = str(value)
        else:
            text = str(value)
        if len(text) > self.max_sample_chars:
            return f"{text[:self.max_sample_chars]}...[truncated]"
        return text

    def _try_parse(self, value: Any) -> Tuple[bool, Any]:
        if isinstance(value, (dict, list)):
            return True, value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                try:
                    return True, json.loads(stripped)
                except Exception:
                    return False, None
        return False, None

    def verify(self, value: Any, source_type: str = "", tool_name: str = "") -> ToolOutputVerification:
        structured, parsed = self._try_parse(value)
        text = self._as_text(parsed if structured else value)

        issues: List[str] = []
        risk_score = 0.0

        if not structured:
            issues.append("unstructured_output")
            risk_score += 0.25

        for pattern in self._patterns:
            if pattern.search(text):
                issues.append(f"suspicious:{pattern.pattern}")
                risk_score += 0.2

        if source_type in {"web", "media", "repo", "image", "pdf", "external"}:
            risk_score += 0.1
            if not structured:
                issues.append("untrusted_unstructured_source")

        if risk_score >= 0.7:
            status = "fail"
        elif risk_score >= 0.3:
            status = "warn"
        else:
            status = "ok"

        return ToolOutputVerification(
            status=status,
            structured=structured,
            risk_score=min(1.0, risk_score),
            issues=issues,
            sample=text,
            parsed=parsed,
        )

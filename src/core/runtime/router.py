#!/usr/bin/env python3
"""
Simple hypergraph router for genome selection.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any


DEFAULT_ROUTER_PATH = Path(os.getenv("VERA_ROUTER_CONFIG_PATH", "config/vera_router.json"))


def _load_router(path: Path = DEFAULT_ROUTER_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _score(prompt: str, signature: str, description: str = "") -> float:
    prompt_words = set(prompt.lower().split())
    signature_words = set(signature.lower().split())
    score = len(prompt_words & signature_words)
    if description and description.lower() in prompt.lower():
        score += 2.0
    return float(score)


def select_genome_path(prompt: str, path: Path = DEFAULT_ROUTER_PATH) -> Path | None:
    if not prompt:
        return None
    router = _load_router(path)
    nodes = router.get("nodes", {}) if isinstance(router, dict) else {}
    if not nodes:
        return None

    best_node = None
    best_score = -1.0
    for name, node in nodes.items():
        signature = str(node.get("embedding_signature", "")).strip()
        desc = str(node.get("description", "")).strip()
        score = _score(prompt, signature, desc)
        if score > best_score:
            best_score = score
            best_node = node

    if not best_node:
        return None

    config_path = best_node.get("config_path")
    if not config_path:
        return None
    return Path(config_path)

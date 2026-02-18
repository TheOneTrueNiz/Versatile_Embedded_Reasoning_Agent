#!/usr/bin/env python3
"""
Reward Model (Lightweight AIR Enhancer)
=======================================

Trains a small linear model on flight recorder transitions and
scores new transitions to refine AIR.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np


DEFAULT_MODEL_PATH = Path("vera_memory/flight_recorder/reward_model.json")
DEFAULT_TRANSITIONS = Path("vera_memory/flight_recorder/transitions.ndjson")


@dataclass
class RewardModelConfig:
    num_buckets: int = 16
    latency_scale: float = 5000.0
    output_scale: float = 2000.0
    input_scale: float = 1200.0


def _hash_bucket(value: str, num_buckets: int) -> int:
    return abs(hash(value)) % num_buckets if num_buckets > 0 else 0


def _safe_len(value: Any) -> int:
    try:
        return len(value)
    except Exception:
        return 0


def _extract_label(entry: Dict[str, Any]) -> Optional[int]:
    action = entry.get("action", {})
    result = entry.get("result", {})
    if action.get("type") == "user_feedback":
        score = result.get("score")
        if score is None:
            return None
        return 1 if float(score) > 0 else 0
    air_score = entry.get("air_score")
    if air_score is None:
        return None
    if float(air_score) == 0:
        return None
    return 1 if float(air_score) > 0 else 0


def extract_features(entry: Dict[str, Any], config: RewardModelConfig) -> np.ndarray:
    action = entry.get("action", {}) or {}
    result = entry.get("result", {}) or {}
    meta = entry.get("meta", {}) or {}

    action_type = str(action.get("type", ""))
    is_tool = 1.0 if action_type == "tool_call" else 0.0
    is_llm = 1.0 if action_type == "llm_call" else 0.0
    is_feedback = 1.0 if action_type == "user_feedback" else 0.0

    success = result.get("success")
    success_flag = 1.0 if success is True else 0.0

    latency_ms = float(meta.get("latency_ms", 0.0) or 0.0)
    latency_norm = min(latency_ms / config.latency_scale, 1.0) if config.latency_scale > 0 else 0.0

    output_len = _safe_len(json.dumps(result, ensure_ascii=True))
    output_norm = min(output_len / config.output_scale, 1.0) if config.output_scale > 0 else 0.0

    action_preview = entry.get("action_preview") or ""
    input_norm = min(_safe_len(action_preview) / config.input_scale, 1.0) if config.input_scale > 0 else 0.0

    bucket = np.zeros(config.num_buckets, dtype=float)
    key = action.get("tool_name") or action.get("model") or action_type
    if key:
        bucket[_hash_bucket(str(key), config.num_buckets)] = 1.0

    base = np.array([is_tool, is_llm, is_feedback, success_flag, latency_norm, output_norm, input_norm], dtype=float)
    return np.concatenate([base, bucket])


@dataclass
class RewardModel:
    weights: np.ndarray
    bias: float
    config: RewardModelConfig

    def predict_proba(self, features: np.ndarray) -> float:
        score = float(np.dot(self.weights, features) + self.bias)
        return 1.0 / (1.0 + math.exp(-score))

    def score_entry(self, entry: Dict[str, Any]) -> float:
        features = extract_features(entry, self.config)
        prob = self.predict_proba(features)
        return max(-1.0, min(1.0, 2.0 * (prob - 0.5)))


def save_reward_model(model: RewardModel, path: Path = DEFAULT_MODEL_PATH) -> None:
    payload = {
        "weights": model.weights.tolist(),
        "bias": model.bias,
        "config": {
            "num_buckets": model.config.num_buckets,
            "latency_scale": model.config.latency_scale,
            "output_scale": model.config.output_scale,
            "input_scale": model.config.input_scale,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def load_reward_model(path: Path = DEFAULT_MODEL_PATH) -> RewardModel:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cfg = payload.get("config") or {}
    config = RewardModelConfig(
        num_buckets=int(cfg.get("num_buckets", 16)),
        latency_scale=float(cfg.get("latency_scale", 5000.0)),
        output_scale=float(cfg.get("output_scale", 2000.0)),
        input_scale=float(cfg.get("input_scale", 1200.0)),
    )
    weights = np.array(payload.get("weights", []), dtype=float)
    bias = float(payload.get("bias", 0.0))
    return RewardModel(weights=weights, bias=bias, config=config)


def _read_ndjson(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return items


def train_reward_model(
    transitions_path: Path = DEFAULT_TRANSITIONS,
    output_path: Path = DEFAULT_MODEL_PATH,
    epochs: int = 60,
    lr: float = 0.08,
    l2: float = 0.01,
    min_examples: int = 20,
    config: Optional[RewardModelConfig] = None,
) -> Dict[str, Any]:
    config = config or RewardModelConfig()
    transitions = _read_ndjson(transitions_path)

    features: List[np.ndarray] = []
    labels: List[int] = []
    for entry in transitions:
        label = _extract_label(entry)
        if label is None:
            continue
        features.append(extract_features(entry, config))
        labels.append(label)

    if len(features) < min_examples:
        return {
            "trained": False,
            "reason": "insufficient_samples",
            "samples": len(features),
        }

    X = np.vstack(features)
    y = np.array(labels, dtype=float)

    weights = np.zeros(X.shape[1], dtype=float)
    bias = 0.0
    sample_count = float(len(y))

    for _ in range(epochs):
        logits = X.dot(weights) + bias
        preds = 1.0 / (1.0 + np.exp(-logits))
        error = preds - y
        grad_w = (X.T.dot(error) / sample_count) + (l2 * weights)
        grad_b = float(error.sum() / sample_count)
        weights -= lr * grad_w
        bias -= lr * grad_b

    model = RewardModel(weights=weights, bias=bias, config=config)
    save_reward_model(model, output_path)
    return {
        "trained": True,
        "samples": len(features),
        "output_path": str(output_path),
    }

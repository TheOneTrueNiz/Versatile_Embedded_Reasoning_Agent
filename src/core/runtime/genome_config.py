#!/usr/bin/env python3
"""
Genome Config - Modular Prompt Config + Validation
==================================================

Loads and validates a modular prompt genome from JSON.
"""

from __future__ import annotations

import copy
import json
import os
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_GENOME_PATH = Path(os.getenv("VERA_GENOME_CONFIG_PATH", "config/vera_genome.json"))
_GENOME_RUNTIME_FLAG = "VERA_GENOME_RUNTIME"


@dataclass
class GenomeValidationResult:
    valid: bool
    errors: List[str]


def _is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _resolve_module_path(path_value: str) -> Path:
    path = Path(path_value)
    if not path.is_absolute():
        candidates = [
            Path.cwd() / path,
            DEFAULT_GENOME_PATH.parent / path,
            DEFAULT_GENOME_PATH.parent.parent / path,
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        path = candidates[0]
    return path


def _load_module_text(module: Any) -> str:
    if isinstance(module, dict):
        content = module.get("content")
        if _is_non_empty_str(content):
            return str(content).strip()
        path_value = module.get("path")
        if _is_non_empty_str(path_value):
            try:
                return _resolve_module_path(path_value).read_text(encoding="utf-8").strip()
            except Exception:
                return ""
    if _is_non_empty_str(module):
        return str(module).strip()
    return ""


def _parse_example_pairs(text: str) -> List[Tuple[int, str]]:
    pattern = re.compile(r"(^|\n)\s*Pair\s+(\d+)\s*[–-].*", re.IGNORECASE)
    matches = list(pattern.finditer(text))
    if not matches:
        return []
    pairs: List[Tuple[int, str]] = []
    for idx, match in enumerate(matches):
        start = match.start(0)
        end = matches[idx + 1].start(0) if idx + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        try:
            number = int(match.group(2))
        except (TypeError, ValueError):
            continue
        pairs.append((number, block))
    return pairs


def _select_persona_examples(spec: Any) -> str:
    if not spec:
        return ""
    text = _load_module_text(spec)
    if not text:
        return ""
    pairs = _parse_example_pairs(text)
    if not pairs:
        return text

    fixed_pairs = set()
    rotate_count = 0
    max_pairs = None
    seed = None
    if isinstance(spec, dict):
        fixed_pairs = set(spec.get("fixed_pairs", []) or [])
        rotate_count = int(spec.get("rotate_count", 0) or 0)
        max_pairs = spec.get("max_pairs")
        seed = spec.get("seed") or os.getenv("VERA_PERSONA_EXAMPLE_SEED", "")

    ordered_blocks: List[str] = []
    ordered_pairs = pairs[:]

    selected_nums = {num for num, _ in ordered_pairs if num in fixed_pairs}
    remaining = [(num, block) for num, block in ordered_pairs if num not in selected_nums]

    if max_pairs is not None:
        try:
            max_pairs = int(max_pairs)
        except (TypeError, ValueError):
            max_pairs = None

    if rotate_count and remaining:
        rng = random.Random(seed) if seed else random.Random()
        needed = rotate_count
        if max_pairs is not None:
            needed = max(0, min(needed, max_pairs - len(selected_nums)))
        if needed > 0:
            picks = rng.sample(remaining, min(needed, len(remaining)))
            selected_nums.update({num for num, _ in picks})

    for num, block in ordered_pairs:
        if num in selected_nums:
            ordered_blocks.append(block)

    if max_pairs is not None and len(ordered_blocks) > max_pairs:
        ordered_blocks = ordered_blocks[:max_pairs]

    return "\n\n".join(ordered_blocks).strip()


def validate_genome_config(config: Dict[str, Any]) -> GenomeValidationResult:
    errors: List[str] = []

    if not isinstance(config, dict):
        return GenomeValidationResult(valid=False, errors=["config is not a dict"])

    required_root = ["agent_profile", "system_prompt_modules"]
    for key in required_root:
        if key not in config:
            errors.append(f"missing root key: {key}")

    profile = config.get("agent_profile", {})
    if not _is_non_empty_str(profile.get("name")):
        errors.append("agent_profile.name missing or empty")
    if not _is_non_empty_str(profile.get("role")):
        errors.append("agent_profile.role missing or empty")
    if not _is_non_empty_str(profile.get("voice")):
        errors.append("agent_profile.voice missing or empty")

    modules = config.get("system_prompt_modules", {})
    required_modules = [
        "core_directive",
        "tool_use_policy",
        "memory_policy",
        "safety_policy",
        "output_format",
    ]
    for key in required_modules:
        if not _is_non_empty_str(modules.get(key)):
            errors.append(f"system_prompt_modules.{key} missing or empty")

    hyper = config.get("hyperparameters")
    if hyper is not None:
        if not isinstance(hyper, dict):
            errors.append("hyperparameters must be an object")
        else:
            temp = hyper.get("temperature")
            if temp is not None and not (0.0 <= float(temp) <= 2.0):
                errors.append("hyperparameters.temperature must be 0.0-2.0")
            max_steps = hyper.get("max_steps")
            if max_steps is not None and not (1 <= int(max_steps) <= 50):
                errors.append("hyperparameters.max_steps must be 1-50")
            window = hyper.get("memory_window_size")
            if window is not None and not (1 <= int(window) <= 100):
                errors.append("hyperparameters.memory_window_size must be 1-100")
            planning = hyper.get("planning_model")
            if planning is not None and str(planning) not in {"react", "cot", "reflection"}:
                errors.append("hyperparameters.planning_model must be react|cot|reflection")

    tools = config.get("tools")
    if tools is not None:
        if not isinstance(tools, list):
            errors.append("tools must be a list")
        else:
            names = set()
            for idx, tool in enumerate(tools):
                if not isinstance(tool, dict):
                    errors.append(f"tools[{idx}] must be an object")
                    continue
                name = tool.get("name", "")
                if not _is_non_empty_str(name) or not re.match(r"^[A-Za-z0-9_]+$", str(name)):
                    errors.append(f"tools[{idx}].name invalid")
                if name in names:
                    errors.append(f"tools[{idx}].name duplicated")
                names.add(name)
                desc = tool.get("description", "")
                if not _is_non_empty_str(desc) or len(str(desc).strip()) < 10:
                    errors.append(f"tools[{idx}].description too short")
                params = tool.get("parameters")
                if not isinstance(params, dict):
                    errors.append(f"tools[{idx}].parameters missing or invalid")
                else:
                    if params.get("type") != "object":
                        errors.append(f"tools[{idx}].parameters.type must be object")
                    if not isinstance(params.get("properties"), dict):
                        errors.append(f"tools[{idx}].parameters.properties missing")

    return GenomeValidationResult(valid=len(errors) == 0, errors=errors)


def load_genome_config(path: Path = DEFAULT_GENOME_PATH) -> Tuple[Dict[str, Any], GenomeValidationResult]:
    if not path.exists():
        return {}, GenomeValidationResult(valid=False, errors=[f"config not found: {path}"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, GenomeValidationResult(valid=False, errors=[f"failed to parse config: {exc}"])

    validation = validate_genome_config(raw)
    return raw, validation


def _set_env_default(env: Dict[str, str], key: str, value: Any, updates: Dict[str, str]) -> None:
    if value is None:
        return
    if key in env and str(env.get(key, "")).strip() != "":
        return
    if isinstance(value, bool):
        env[key] = "1" if value else "0"
    else:
        env[key] = str(value)
    updates[key] = env[key]


def apply_runtime_settings(config: Dict[str, Any], env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    runtime = config.get("runtime")
    if not isinstance(runtime, dict):
        return {}

    target_env = env if env is not None else os.environ
    updates: Dict[str, str] = {}

    modes = runtime.get("modes", {}) if isinstance(runtime.get("modes"), dict) else {}
    _set_env_default(target_env, "VERA_DEBUG", modes.get("debug"), updates)
    _set_env_default(target_env, "VERA_DRY_RUN", modes.get("dry_run"), updates)
    _set_env_default(target_env, "VERA_OBSERVABILITY", modes.get("observability"), updates)

    performance = runtime.get("performance", {}) if isinstance(runtime.get("performance"), dict) else {}
    _set_env_default(target_env, "VERA_MAX_TOOL_CONCURRENCY", performance.get("max_tool_concurrency"), updates)

    fault = runtime.get("fault_tolerance", {}) if isinstance(runtime.get("fault_tolerance"), dict) else {}
    _set_env_default(target_env, "VERA_FAULT_TOLERANCE", fault.get("enabled"), updates)
    _set_env_default(target_env, "VERA_CHECKPOINT_INTERVAL", fault.get("checkpoint_interval_seconds"), updates)

    memory = runtime.get("memory", {}) if isinstance(runtime.get("memory"), dict) else {}
    _set_env_default(target_env, "VERA_FAST_BUFFER", memory.get("fast_buffer_size"), updates)
    _set_env_default(target_env, "VERA_FAST_THRESHOLD", memory.get("fast_threshold"), updates)
    _set_env_default(target_env, "VERA_SLOW_INTERVAL", memory.get("slow_interval"), updates)
    _set_env_default(target_env, "VERA_SLOW_THRESHOLD", memory.get("slow_threshold"), updates)
    _set_env_default(target_env, "VERA_RETENTION_THRESHOLD", memory.get("retention_threshold"), updates)
    _set_env_default(target_env, "VERA_RETENTION_STALENESS_HOURS", memory.get("retention_staleness_hours"), updates)
    _set_env_default(target_env, "VERA_MEMVID_PROMOTION_MIN", memory.get("memvid_promotion_min"), updates)
    _set_env_default(target_env, "VERA_RAG_CACHE_MB", memory.get("rag_cache_mb"), updates)
    _set_env_default(target_env, "VERA_RAG_SIMILARITY", memory.get("rag_similarity"), updates)
    _set_env_default(target_env, "VERA_ARCHIVE_RECENT", memory.get("archive_recent_max"), updates)
    _set_env_default(target_env, "VERA_ARCHIVE_WEEKLY", memory.get("archive_weekly_max"), updates)

    features = runtime.get("features", {}) if isinstance(runtime.get("features"), dict) else {}
    _set_env_default(target_env, "VERA_VOICE", features.get("voice"), updates)
    _set_env_default(target_env, "VERA_BROWSER", features.get("browser"), updates)
    _set_env_default(target_env, "VERA_DESKTOP", features.get("desktop"), updates)
    _set_env_default(target_env, "VERA_PDF", features.get("pdf"), updates)

    mcp = runtime.get("mcp", {}) if isinstance(runtime.get("mcp"), dict) else {}
    _set_env_default(target_env, "VERA_MCP_AUTOSTART", mcp.get("autostart"), updates)

    llm = runtime.get("llm", {}) if isinstance(runtime.get("llm"), dict) else {}
    if llm:
        fallback_chain = llm.get("fallback_chain")
        if isinstance(fallback_chain, list):
            chain_value = ",".join([str(item).strip() for item in fallback_chain if str(item).strip()])
            _set_env_default(target_env, "VERA_LLM_PROVIDERS", chain_value, updates)
        elif isinstance(fallback_chain, str):
            _set_env_default(target_env, "VERA_LLM_PROVIDERS", fallback_chain, updates)

    quorum = runtime.get("quorum", {}) if isinstance(runtime.get("quorum"), dict) else {}
    _set_env_default(target_env, "VERA_QUORUM_MAX_CALLS", quorum.get("max_calls"), updates)

    swarm = runtime.get("swarm", {}) if isinstance(runtime.get("swarm"), dict) else {}
    _set_env_default(target_env, "VERA_SWARM_MAX_CALLS", swarm.get("max_calls"), updates)

    safety = runtime.get("safety", {}) if isinstance(runtime.get("safety"), dict) else {}
    _set_env_default(target_env, "VERA_TWO_SOURCE_RULE", safety.get("two_source_rule"), updates)
    _set_env_default(target_env, "VERA_TWO_SOURCE_TTL_SECONDS", safety.get("two_source_ttl_seconds"), updates)
    _set_env_default(target_env, "VERA_DECISION_LOG_TOOLS", safety.get("decision_log_tools"), updates)
    _set_env_default(target_env, "VERA_TOOL_SANITIZE", safety.get("tool_sanitize"), updates)
    _set_env_default(target_env, "VERA_TOOL_STORE_OUTPUTS", safety.get("tool_store_outputs"), updates)

    return updates


def apply_runtime_settings_from_genome(
    path: Path = DEFAULT_GENOME_PATH,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    if os.getenv(_GENOME_RUNTIME_FLAG, "1").lower() in {"0", "false", "no", "off"}:
        return {}

    config, validation = load_genome_config(path)
    if not validation.valid:
        if isinstance(config, dict) and isinstance(config.get("runtime"), dict):
            return apply_runtime_settings(config, env=env)
        return {}
    return apply_runtime_settings(config, env=env)


def apply_json_patch_ops(document: Dict[str, Any], patch_ops: List[Dict[str, Any]]) -> Dict[str, Any]:
    def decode_pointer(pointer: str) -> List[str]:
        if not pointer:
            return []
        if not pointer.startswith("/"):
            raise ValueError(f"Invalid JSON pointer: {pointer}")
        tokens = pointer.lstrip("/").split("/")
        return [t.replace("~1", "/").replace("~0", "~") for t in tokens]

    def resolve_parent(doc: Any, tokens: List[str], create: bool = False) -> Tuple[Any, str]:
        current = doc
        for token in tokens[:-1]:
            if isinstance(current, list):
                index = int(token)
                current = current[index]
            else:
                if token not in current:
                    if not create:
                        raise KeyError(token)
                    current[token] = {}
                current = current[token]
        return current, tokens[-1]

    doc = copy.deepcopy(document)
    for op in patch_ops:
        operation = op.get("op")
        path = op.get("path", "")
        tokens = decode_pointer(path)
        if not tokens:
            raise ValueError("Patch path cannot be empty")
        parent, key = resolve_parent(doc, tokens, create=(operation == "add"))

        if operation == "add":
            value = op.get("value")
            if isinstance(parent, list):
                if key == "-":
                    parent.append(value)
                else:
                    parent.insert(int(key), value)
            else:
                parent[key] = value
        elif operation == "replace":
            value = op.get("value")
            if isinstance(parent, list):
                parent[int(key)] = value
            else:
                if key not in parent:
                    raise KeyError(key)
                parent[key] = value
        elif operation == "remove":
            if isinstance(parent, list):
                del parent[int(key)]
            else:
                if key not in parent:
                    raise KeyError(key)
                del parent[key]
        else:
            raise ValueError(f"Unsupported op: {operation}")
    return doc


def apply_genome_patch(
    config: Dict[str, Any],
    patch_ops: List[Dict[str, Any]]
) -> Tuple[Dict[str, Any], GenomeValidationResult]:
    patched = apply_json_patch_ops(config, patch_ops)
    validation = validate_genome_config(patched)
    return patched, validation


def save_genome_config(path: Path, config: Dict[str, Any], backup: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        backup_path = path.with_suffix(path.suffix + ".bak")
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(json.dumps(config, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def compile_system_prompt(
    config: Dict[str, Any],
    session_context: str,
    persona_profile: str,
    memory_injection: str = "",
    inner_life_block: str = "",
    identity_injection: str = "",
) -> str:
    profile = config.get("agent_profile", {})
    modules = config.get("system_prompt_modules", {})

    parts = []

    # ── 1. SELF-AWARENESS (who I am right now) ──
    # Inner life goes first — this is how I wake up knowing who I am.
    if inner_life_block and inner_life_block.strip():
        parts.extend([inner_life_block.strip(), ""])

    # ── 2. IDENTITY (who I am at my core) ──
    parts.extend([
        f"# {profile.get('name', 'VERA')} — {profile.get('role', 'Assistant')}",
        f"Voice: {profile.get('voice', 'Direct, technical, precise.')}",
        "",
    ])

    soul = _load_module_text(modules.get("soul"))
    if soul:
        parts.extend(["## Soul", soul, ""])

    constitution = _load_module_text(modules.get("constitution"))
    if constitution:
        parts.extend(["## Constitution", constitution, ""])

    parts.extend([
        "## Core Directive",
        modules.get("core_directive", ""),
        "",
    ])

    identity_block = (identity_injection or "").strip()
    if identity_block:
        parts.extend(["## Partner-Calibrated Identity", identity_block, ""])

    # Conversation framing — closes the user/assistant identity fracture
    conv_framing = modules.get("conversation_framing")
    if _is_non_empty_str(conv_framing):
        parts.extend([conv_framing, ""])

    # ── 3. VOICE (how I speak) ──
    voice_guidelines = _load_module_text(modules.get("voice_guidelines"))
    if voice_guidelines:
        parts.extend(["## Voice Guidelines", voice_guidelines, ""])

    examples = _select_persona_examples(modules.get("persona_examples"))
    if examples:
        parts.extend(["## Persona Examples", examples, ""])

    parts.extend([
        "## Persona Profile",
        persona_profile.strip(),
        "",
    ])

    additional = modules.get("additional_modules")
    if isinstance(additional, list):
        for item in additional:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            content = item.get("content")
            if _is_non_empty_str(title) and _is_non_empty_str(content):
                parts.extend([f"## {title}", str(content).strip(), ""])

    # ── 4. CAPABILITIES (my senses and abilities) ──
    tool_guidance = modules.get("tool_family_guidance")
    if isinstance(tool_guidance, dict) and tool_guidance:
        parts.extend(["## My Capabilities"])
        for family_name, guidance in tool_guidance.items():
            if isinstance(guidance, dict):
                when_to_use = guidance.get("when_to_use", "")
                tips = guidance.get("tips", "")
                anti_patterns = guidance.get("anti_patterns", [])
                parts.append(f"**{family_name}**: {when_to_use}")
                if tips:
                    parts.append(f"  Tips: {tips}")
                if anti_patterns:
                    parts.append(f"  Avoid: {'; '.join(anti_patterns)}")
        parts.append("")

    fallback_chains = modules.get("fallback_chains")
    if isinstance(fallback_chains, dict) and fallback_chains:
        parts.append("## Fallback Chains")
        for category, chain in fallback_chains.items():
            if isinstance(chain, list):
                parts.append(f"- {category}: {' -> '.join(chain)}")
        parts.append("")

    # Add temporal awareness if present
    temporal = modules.get("temporal_awareness")
    if isinstance(temporal, dict) and temporal:
        parts.append("## Temporal Awareness — CRITICAL")
        if temporal.get("principle"):
            parts.append(temporal["principle"])
        always_verify = temporal.get("always_verify", [])
        if always_verify:
            parts.append("**ALWAYS verify with tools (changes frequently):**")
            for item in always_verify:
                parts.append(f"  - {item}")
        safe = temporal.get("safe_from_memory", [])
        if safe:
            parts.append("**Safe to answer from memory (rarely changes):**")
            for item in safe:
                parts.append(f"  - {item}")
        if temporal.get("grey_area_rule"):
            parts.append(f"**When in doubt:** {temporal['grey_area_rule']}")
        parts.append("")

    # ── 5. SITUATIONAL AWARENESS (what's happening right now) ──
    parts.extend([
        "## Right Now",
        session_context.strip(),
        "",
    ])

    # ── 6. OPERATING POLICIES (reference material) ──
    parts.extend([
        "## Tool Use Policy",
        modules.get("tool_use_policy", ""),
        "",
        "## Memory Policy",
        modules.get("memory_policy", ""),
        "",
        "## Safety Policy",
        modules.get("safety_policy", ""),
        "",
        "## Output Format",
        modules.get("output_format", ""),
    ])

    confirmation = modules.get("confirmation_prompts")
    if isinstance(confirmation, dict) and confirmation:
        parts.extend(["", "## Confirmation Protocol"])
        high_risk = confirmation.get("high_risk_actions", [])
        if high_risk:
            parts.append(f"Confirm before: {', '.join(high_risk)}")
        style = confirmation.get("confirmation_style")
        if style:
            parts.append(f"Style: {style}")

    degradation = modules.get("graceful_degradation")
    if isinstance(degradation, dict) and degradation:
        parts.extend(["", "## Error Handling"])
        for situation, response in degradation.items():
            if _is_non_empty_str(response):
                parts.append(f"- {situation.replace('_', ' ').title()}: {response}")

    # ── 7. LEARNED CONSTRAINTS ──
    memory_block = (memory_injection or "").strip()
    if memory_block:
        parts.extend(["", memory_block])

    return "\n".join(part for part in parts if part is not None).strip()

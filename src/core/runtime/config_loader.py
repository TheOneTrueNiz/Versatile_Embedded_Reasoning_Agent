"""
VERA 2.0 Configuration Loader
===============================

Canonical config source: config/vera_genome.json (runtime section).
Precedence:
    1. Defaults (from Pydantic model)
    2. Genome runtime (config/vera_genome.json)
    3. Optional YAML fallback (config/vera_config.yaml) if VERA_USE_YAML_CONFIG=1
    4. Environment variables (VERA_ prefix)
    5. CLI arguments

Backward compatible with existing env-var-only configuration.
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge override into base. Override values win."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _deep_merge_missing(base: Dict, fallback: Dict) -> Dict:
    """Deep merge fallback into base without overriding existing values."""
    result = dict(base)
    for key, val in fallback.items():
        if key not in result or result[key] is None:
            result[key] = val
        elif isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge_missing(result[key], val)
    return result


def _load_yaml_config(path: Path) -> Dict[str, Any]:
    """Load config from YAML file. Returns empty dict if file missing."""
    if not path.exists():
        return {}

    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        logger.info(f"Loaded config from {path}")
        return data
    except ImportError:
        logger.debug("PyYAML not available, skipping YAML config")
        return {}
    except Exception as e:
        logger.warning(f"Failed to load config from {path}: {e}")
        return {}


def _load_genome_runtime_config() -> Dict[str, Any]:
    """Load runtime config from the genome JSON (canonical source)."""
    try:
        from core.runtime.genome_config import DEFAULT_GENOME_PATH, load_genome_config
    except Exception as exc:
        logger.debug("Genome config loader unavailable: %s", exc)
        return {}

    config, validation = load_genome_config(DEFAULT_GENOME_PATH)
    if not isinstance(config, dict):
        return {}
    runtime = config.get("runtime") if isinstance(config.get("runtime"), dict) else {}
    if not runtime:
        return {}

    data: Dict[str, Any] = {}

    modes = runtime.get("modes", {}) if isinstance(runtime.get("modes"), dict) else {}
    if modes:
        if "debug" in modes:
            data["debug"] = bool(modes.get("debug"))
        if "dry_run" in modes:
            data["dry_run"] = bool(modes.get("dry_run"))
        if "observability" in modes:
            data["observability"] = bool(modes.get("observability"))

    memory = runtime.get("memory", {}) if isinstance(runtime.get("memory"), dict) else {}
    if memory:
        data.setdefault("memory", {})
        for key in (
            "fast_buffer_size",
            "fast_threshold",
            "slow_interval",
            "slow_threshold",
            "retention_threshold",
            "retention_staleness_hours",
            "memvid_promotion_min",
            "rag_cache_mb",
            "rag_similarity",
            "archive_recent_max",
            "archive_weekly_max",
        ):
            if key in memory:
                data["memory"][key] = memory.get(key)

    llm = runtime.get("llm", {}) if isinstance(runtime.get("llm"), dict) else {}
    if llm:
        fallback_chain = llm.get("fallback_chain")
        if isinstance(fallback_chain, list):
            data.setdefault("llm", {})
            data["llm"]["fallback_chain"] = fallback_chain

    fault = runtime.get("fault_tolerance", {}) if isinstance(runtime.get("fault_tolerance"), dict) else {}
    performance = runtime.get("performance", {}) if isinstance(runtime.get("performance"), dict) else {}
    if fault or performance:
        data.setdefault("safety", {})
        if "enabled" in fault:
            data["safety"]["fault_tolerance"] = bool(fault.get("enabled"))
        if "checkpoint_interval_seconds" in fault:
            data["safety"]["checkpoint_interval"] = fault.get("checkpoint_interval_seconds")
        if "max_tool_concurrency" in performance:
            data["safety"]["max_tool_concurrency"] = performance.get("max_tool_concurrency")

    return data


def _env_overrides() -> Dict[str, Any]:
    """Build config overrides from environment variables.

    Maps VERA_ prefixed env vars to nested config keys:
        VERA_DEBUG=1          -> {"debug": True}
        VERA_LLM_TIMEOUT=120  -> {"llm": {"timeout": 120}}
        VERA_LLM_PROVIDERS=grok,claude -> {"llm": {"fallback_chain": ["grok", "claude"]}}
    """
    overrides: Dict[str, Any] = {}

    # Simple boolean flags
    bool_mappings = {
        "VERA_DEBUG": "debug",
        "VERA_DRY_RUN": "dry_run",
        "VERA_OBSERVABILITY": "observability",
    }
    for env_var, config_key in bool_mappings.items():
        val = os.getenv(env_var, "").strip()
        if val:
            overrides[config_key] = val.lower() in ("1", "true", "yes", "on")

    # LLM config
    llm_providers = os.getenv("VERA_LLM_PROVIDERS", "").strip()
    if llm_providers:
        overrides.setdefault("llm", {})["fallback_chain"] = [
            p.strip() for p in llm_providers.split(",") if p.strip()
        ]

    llm_timeout = os.getenv("VERA_LLM_TIMEOUT", "").strip()
    if llm_timeout:
        try:
            overrides.setdefault("llm", {})["timeout"] = float(llm_timeout)
        except ValueError:
            logger.debug("Suppressed ValueError in config_loader")
            pass

    # Memory config
    memory_mappings = {
        "VERA_FAST_BUFFER": ("memory", "fast_buffer_size", int),
        "VERA_FAST_THRESHOLD": ("memory", "fast_threshold", float),
        "VERA_SLOW_INTERVAL": ("memory", "slow_interval", float),
        "VERA_RAG_CACHE_MB": ("memory", "rag_cache_mb", int),
        "VERA_RAG_SIMILARITY": ("memory", "rag_similarity", float),
    }
    for env_var, (section, key, type_fn) in memory_mappings.items():
        val = os.getenv(env_var, "").strip()
        if val:
            try:
                overrides.setdefault(section, {})[key] = type_fn(val)
            except ValueError:
                logger.debug("Suppressed ValueError in config_loader")
                pass

    # Safety config
    fault_tolerance = os.getenv("VERA_FAULT_TOLERANCE", "").strip()
    if fault_tolerance:
        overrides.setdefault("safety", {})["fault_tolerance"] = (
            fault_tolerance.lower() in ("1", "true", "yes", "on")
        )

    max_tool_concurrency = os.getenv("VERA_MAX_TOOL_CONCURRENCY", "").strip()
    if max_tool_concurrency:
        try:
            overrides.setdefault("safety", {})["max_tool_concurrency"] = int(max_tool_concurrency)
        except ValueError:
            logger.debug("Suppressed ValueError in config_loader")
            pass

    # Discord config
    discord_token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
    if discord_token:
        overrides.setdefault("channels", {}).setdefault("discord", {})["enabled"] = True

    return overrides


def load_config(
    config_path: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> "VERAConfigV2":
    """Load VERA 2.0 configuration with hierarchical precedence.

    Args:
        config_path: Path to YAML config file. Defaults to config/vera_config.yaml
        cli_overrides: Overrides from command-line arguments

    Returns:
        Validated VERAConfigV2 instance
    """
    try:
        from core.runtime.config_schema import VERAConfigV2
    except ImportError:
        logger.warning("config_schema not available, using defaults")
        return None

    # 1. Start with defaults (from Pydantic model)
    config_data: Dict[str, Any] = {}

    # 2. Load canonical runtime from genome JSON
    genome_data = _load_genome_runtime_config()
    config_data = _deep_merge(config_data, genome_data)

    # 3. Optional YAML fallback for legacy fields (only fills missing values)
    if os.getenv("VERA_USE_YAML_CONFIG", "0").lower() in ("1", "true", "yes", "on"):
        if config_path is None:
            candidates = [
                Path("config/vera_config.yaml"),
                Path("config/vera_config.yml"),
                Path("vera_config.yaml"),
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = candidate
                    break

        if config_path:
            yaml_data = _load_yaml_config(config_path)
            config_data = _deep_merge_missing(config_data, yaml_data)

    # 4. Apply environment variable overrides
    env_data = _env_overrides()
    config_data = _deep_merge(config_data, env_data)

    # 5. Apply CLI overrides
    if cli_overrides:
        config_data = _deep_merge(config_data, cli_overrides)

    # Validate and return
    try:
        config = VERAConfigV2(**config_data)
        logger.info("Configuration loaded and validated")
        return config
    except Exception as e:
        logger.warning(f"Config validation failed, using defaults: {e}")
        return VERAConfigV2()

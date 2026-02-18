"""
Channel Adapter Loader
======================

Loads channel adapters from a JSON config file or env vars.
Allows users to plug in messaging adapters of their choice.
"""

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from channels.api_adapter import ApiChannelAdapter

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config") / "channels.json"


def _load_config(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read channel config %s: %s", path, exc)
        return []
    if isinstance(payload, dict):
        channels = payload.get("channels")
        return channels if isinstance(channels, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _parse_env_channels() -> List[Dict[str, Any]]:
    raw = os.getenv("VERA_CHANNELS", "").strip()
    if not raw:
        return []
    specs: List[Dict[str, Any]] = []
    for item in raw.split(","):
        channel_type = item.strip().lower()
        if not channel_type:
            continue
        specs.append({"type": channel_type, "enabled": True})
    return specs


def _import_adapter(target: str, settings: Optional[Dict[str, Any]] = None):
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise ValueError("Adapter module must be in form 'module:ClassName'")
    module = importlib.import_module(module_name)
    adapter_cls = getattr(module, attr)
    if settings:
        return adapter_cls(**settings)
    return adapter_cls()


def _build_adapter(spec: Dict[str, Any]):
    if not isinstance(spec, dict):
        return None
    if spec.get("enabled", True) is False:
        return None

    adapter_type = (spec.get("type") or "").strip().lower()
    settings = spec.get("settings") if isinstance(spec.get("settings"), dict) else {}
    module_override = spec.get("module") or spec.get("factory")

    if module_override:
        try:
            return _import_adapter(module_override, settings)
        except Exception as exc:
            logger.warning("Failed to load adapter %s: %s", module_override, exc)
            return None

    if adapter_type == "api":
        return ApiChannelAdapter()

    if adapter_type == "discord":
        try:
            from channels.discord.adapter import DiscordAdapter
        except Exception as exc:
            logger.warning("Discord adapter unavailable: %s", exc)
            return None
        token = settings.get("token") or os.getenv(settings.get("token_env", "DISCORD_BOT_TOKEN"), "")
        if not token:
            logger.warning("Discord adapter skipped (missing token).")
            return None
        return DiscordAdapter(
            token=token,
            allowed_guilds=settings.get("allowed_guilds") or settings.get("guilds"),
            allowed_users=settings.get("allowed_users") or settings.get("users"),
            command_prefix=settings.get("command_prefix", "!"),
        )

    if adapter_type == "telegram":
        try:
            from channels.telegram.adapter import TelegramAdapter
        except Exception as exc:
            logger.warning("Telegram adapter unavailable: %s", exc)
            return None
        token = settings.get("token") or os.getenv(settings.get("token_env", "TELEGRAM_BOT_TOKEN"), "")
        if not token:
            logger.warning("Telegram adapter skipped (missing token).")
            return None
        return TelegramAdapter(
            token=token,
            allowed_chats=settings.get("allowed_chats") or settings.get("chats"),
            allowed_users=settings.get("allowed_users") or settings.get("users"),
            command_prefix=settings.get("command_prefix", "/"),
        )

    if adapter_type == "whatsapp":
        try:
            from channels.whatsapp.adapter import WhatsAppAdapter
        except Exception as exc:
            logger.warning("WhatsApp adapter unavailable: %s", exc)
            return None

        token = settings.get("access_token") or os.getenv(settings.get("token_env", "WHATSAPP_ACCESS_TOKEN"), "")
        phone_number_id = settings.get("phone_number_id") or os.getenv(
            settings.get("phone_number_id_env", "WHATSAPP_PHONE_NUMBER_ID"),
            "",
        )
        if not token or not phone_number_id:
            logger.warning("WhatsApp adapter skipped (missing token or phone_number_id).")
            return None

        verify_token = settings.get("verify_token") or os.getenv(
            settings.get("verify_token_env", "WHATSAPP_VERIFY_TOKEN"),
            "",
        )
        app_secret = settings.get("app_secret") or os.getenv(
            settings.get("app_secret_env", "WHATSAPP_APP_SECRET"),
            "",
        )

        return WhatsAppAdapter(
            access_token=token,
            phone_number_id=phone_number_id,
            verify_token=verify_token,
            app_secret=app_secret,
            base_url=settings.get("base_url") or os.getenv("WHATSAPP_BASE_URL", ""),
            graph_version=settings.get("graph_version") or os.getenv("WHATSAPP_GRAPH_VERSION", ""),
            allowed_numbers=settings.get("allowed_numbers") or settings.get("numbers"),
        )

    logger.warning("Unknown channel adapter type: %s", adapter_type or "<missing>")
    return None


def _redact_sensitive(settings: Dict[str, Any]) -> Dict[str, Any]:
    if not settings:
        return {}
    redacted: Dict[str, Any] = {}
    for key, value in settings.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("token", "secret", "key", "password", "credential", "auth")):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


def _sanitize_spec(spec: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(spec, dict):
        return None
    safe = {
        "type": spec.get("type"),
        "enabled": spec.get("enabled", True),
    }
    module_override = spec.get("module") or spec.get("factory")
    if module_override:
        safe["module"] = module_override
    settings = spec.get("settings")
    if isinstance(settings, dict) and settings:
        safe["settings"] = _redact_sensitive(settings)
    return safe


def get_channel_config_snapshot(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Return a redacted snapshot of the channel config source."""
    path = Path(os.getenv("VERA_CHANNEL_CONFIG", "")).expanduser() if os.getenv("VERA_CHANNEL_CONFIG") else None
    if not path:
        path = config_path or DEFAULT_CONFIG_PATH

    config_exists = path.exists()
    specs = _load_config(path) if config_exists else []
    source = "file" if specs else ""

    if not specs:
        env_specs = _parse_env_channels()
        if env_specs:
            specs = env_specs
            source = "env"
        else:
            specs = [{"type": "api", "enabled": True}]
            source = "default"

    sanitized = []
    for spec in specs:
        clean = _sanitize_spec(spec)
        if clean:
            sanitized.append(clean)

    rel_path = ""
    try:
        rel_path = str(path.resolve().relative_to(Path.cwd().resolve()))
    except Exception:
        rel_path = ""

    return {
        "source": source or "default",
        "config_path": str(path),
        "config_path_relative": rel_path,
        "config_exists": config_exists,
        "specs": sanitized,
    }


def load_channel_adapters(config_path: Optional[Path] = None) -> List[Any]:
    path = Path(os.getenv("VERA_CHANNEL_CONFIG", "")).expanduser() if os.getenv("VERA_CHANNEL_CONFIG") else None
    if not path:
        path = config_path or DEFAULT_CONFIG_PATH

    specs = _load_config(path)
    if not specs:
        specs = _parse_env_channels()
    if not specs:
        specs = [{"type": "api", "enabled": True}]

    adapters = []
    for spec in specs:
        adapter = _build_adapter(spec)
        if adapter:
            adapters.append(adapter)
    return adapters

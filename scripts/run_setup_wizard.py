#!/usr/bin/env python3
"""
Minimal preflight web wizard for first-run credential setup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

from aiohttp import web


def _creds_dir() -> Path:
    root = os.getenv("CREDS_DIR")
    if root:
        return Path(root).expanduser()
    return Path.home() / "Documents" / "creds"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _normalize_url(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if not text.startswith(("http://", "https://")):
        text = f"http://{text}"
    if not text.rstrip("/").endswith("/v1"):
        text = f"{text.rstrip('/')}/v1"
    return text


def _write_value(subdir: str, filename: str, value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    creds_dir = _creds_dir()
    target = creds_dir / subdir / filename
    _atomic_write(target, f"{value}\n")
    return str(target)


def _update_env_file(values: Dict[str, str]) -> Optional[str]:
    env_path = Path(__file__).resolve().parents[1] / "scripts" / "vera_env.local"
    existing: Dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            if raw.startswith("export "):
                raw = raw[len("export "):]
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            existing[key.strip()] = value.strip().strip('"')

    for key, value in values.items():
        if value is None:
            continue
        existing[key] = str(value)

    if not existing:
        return None

    lines = [f'export {key}="{existing[key].replace("\"", "\\\"")}"' for key in sorted(existing.keys())]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(env_path)


def _read_env_file() -> Dict[str, str]:
    env_path = Path(__file__).resolve().parents[1] / "scripts" / "vera_env.local"
    existing: Dict[str, str] = {}
    if not env_path.exists():
        return existing
    for line in env_path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("export "):
            raw = raw[len("export "):]
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        existing[key.strip()] = value.strip().strip('"')
    return existing


def _read_secret(subdir: str, filename: str) -> str:
    path = _creds_dir() / subdir / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _parse_list(value: str) -> Optional[list]:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _persist_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    creds_dir = _creds_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)
    (creds_dir / ".vera_creds_pointer").write_text(
        f"VERA credentials live at: {creds_dir}\n",
        encoding="utf-8",
    )

    persisted = []
    xai_key = payload.get("XAI_API_KEY") or payload.get("API_KEY")
    local_base = _normalize_url(payload.get("VERA_LLM_BASE_URL", ""))
    local_key = payload.get("VERA_LLM_API_KEY", "")
    local_model = payload.get("VERA_MODEL", "")

    if xai_key:
        result = _write_value("xai", "xai_api", xai_key)
        if result:
            persisted.append(result)

    if local_base:
        result = _write_value("local", "llm_base_url", local_base)
        if result:
            persisted.append(result)
        if local_key:
            result = _write_value("local", "llm_api_key", local_key)
            if result:
                persisted.append(result)
        if local_model:
            result = _write_value("local", "model_id", local_model)
            if result:
                persisted.append(result)

    brave_key = payload.get("BRAVE_API_KEY", "")
    github_token = payload.get("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    searxng_url = payload.get("SEARXNG_BASE_URL", "")
    obsidian_path = payload.get("OBSIDIAN_VAULT_PATH", "")
    hub_command = payload.get("MCP_HUB_COMMAND", "")
    hub_args = payload.get("MCP_HUB_ARGS", "")
    composio_key = payload.get("COMPOSIO_API_KEY", "")
    vera_browser = payload.get("VERA_BROWSER", "")
    user_email = payload.get("GOOGLE_WORKSPACE_USER_EMAIL", "")
    google_client_id = payload.get("GOOGLE_OAUTH_CLIENT_ID", "")
    google_client_secret = payload.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    google_redirect_uri = payload.get("GOOGLE_OAUTH_REDIRECT_URI", "")

    for subdir in (
        "brave",
        "git",
        "searxng",
        "google",
        "local",
        "xai",
        "obsidian",
        "hub",
        "telegram",
        "whatsapp",
        "discord",
    ):
        (creds_dir / subdir).mkdir(parents=True, exist_ok=True)

    if brave_key:
        result = _write_value("brave", "brave_api", brave_key)
        if result:
            persisted.append(result)
    if github_token:
        result = _write_value("git", "git_token", github_token)
        if result:
            persisted.append(result)
    if searxng_url:
        result = _write_value("searxng", "searxng_url", searxng_url)
        if result:
            persisted.append(result)
    if obsidian_path:
        result = _write_value("obsidian", "vault_path", obsidian_path)
        if result:
            persisted.append(result)
    if hub_command:
        result = _write_value("hub", "command", hub_command)
        if result:
            persisted.append(result)
    if hub_args:
        result = _write_value("hub", "args", hub_args)
        if result:
            persisted.append(result)
    if composio_key:
        result = _write_value("hub", "composio_api_key", composio_key)
        if result:
            persisted.append(result)
    if user_email:
        result = _write_value("google", "user_email", user_email)
        if result:
            persisted.append(result)

    if google_client_id and google_client_secret:
        oauth_path = creds_dir / "google" / "client_secret_generated.json"
        oauth_payload = {
            "installed": {
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            }
        }
        if google_redirect_uri:
            oauth_payload["installed"]["redirect_uris"] = [google_redirect_uri]
        _atomic_write(oauth_path, json.dumps(oauth_payload, indent=2, ensure_ascii=True))
        persisted.append(str(oauth_path))

    telegram_token = payload.get("TELEGRAM_BOT_TOKEN", "")
    telegram_allowed_chats = payload.get("TELEGRAM_ALLOWED_CHATS", "")
    telegram_allowed_users = payload.get("TELEGRAM_ALLOWED_USERS", "")
    telegram_command_prefix = payload.get("TELEGRAM_COMMAND_PREFIX", "/") or "/"

    if telegram_token:
        result = _write_value("telegram", "bot_token", telegram_token)
        if result:
            persisted.append(result)

    whatsapp_access_token = payload.get("WHATSAPP_ACCESS_TOKEN", "")
    whatsapp_phone_id = payload.get("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_verify_token = payload.get("WHATSAPP_VERIFY_TOKEN", "")
    whatsapp_app_secret = payload.get("WHATSAPP_APP_SECRET", "")
    whatsapp_allowed_numbers = payload.get("WHATSAPP_ALLOWED_NUMBERS", "")
    whatsapp_graph_version = payload.get("WHATSAPP_GRAPH_VERSION", "v20.0") or "v20.0"

    if whatsapp_access_token:
        result = _write_value("whatsapp", "access_token", whatsapp_access_token)
        if result:
            persisted.append(result)
    if whatsapp_phone_id:
        result = _write_value("whatsapp", "phone_number_id", whatsapp_phone_id)
        if result:
            persisted.append(result)
    if whatsapp_verify_token:
        result = _write_value("whatsapp", "verify_token", whatsapp_verify_token)
        if result:
            persisted.append(result)
    if whatsapp_app_secret:
        result = _write_value("whatsapp", "app_secret", whatsapp_app_secret)
        if result:
            persisted.append(result)

    discord_token = payload.get("DISCORD_BOT_TOKEN", "")
    discord_allowed_guilds = payload.get("DISCORD_ALLOWED_GUILDS", "")
    discord_allowed_users = payload.get("DISCORD_ALLOWED_USERS", "")
    discord_command_prefix = payload.get("DISCORD_COMMAND_PREFIX", "!") or "!"

    if discord_token:
        result = _write_value("discord", "bot_token", discord_token)
        if result:
            persisted.append(result)

    env_updates = {}
    if obsidian_path:
        env_updates["OBSIDIAN_VAULT_PATH"] = obsidian_path
    if hub_command:
        env_updates["MCP_HUB_COMMAND"] = hub_command
    if hub_args:
        env_updates["MCP_HUB_ARGS"] = hub_args
    if vera_browser:
        env_updates["VERA_BROWSER"] = vera_browser
    if telegram_token:
        env_updates["TELEGRAM_BOT_TOKEN"] = telegram_token
    if whatsapp_access_token:
        env_updates["WHATSAPP_ACCESS_TOKEN"] = whatsapp_access_token
    if whatsapp_phone_id:
        env_updates["WHATSAPP_PHONE_NUMBER_ID"] = whatsapp_phone_id
    if whatsapp_verify_token:
        env_updates["WHATSAPP_VERIFY_TOKEN"] = whatsapp_verify_token
    if whatsapp_app_secret:
        env_updates["WHATSAPP_APP_SECRET"] = whatsapp_app_secret
    if whatsapp_graph_version:
        env_updates["WHATSAPP_GRAPH_VERSION"] = whatsapp_graph_version
    if discord_token:
        env_updates["DISCORD_BOT_TOKEN"] = discord_token
    env_path = _update_env_file(env_updates) if env_updates else None

    enable_telegram = _parse_bool(payload.get("ENABLE_TELEGRAM"))
    enable_whatsapp = _parse_bool(payload.get("ENABLE_WHATSAPP"))
    enable_discord = _parse_bool(payload.get("ENABLE_DISCORD"))

    channels_config_path = None
    if enable_telegram or enable_whatsapp or enable_discord:
        channels = [{"type": "api", "enabled": True}]
        if enable_discord:
            settings: Dict[str, Any] = {
                "token_env": "DISCORD_BOT_TOKEN",
                "command_prefix": discord_command_prefix,
            }
            guilds = _parse_list(discord_allowed_guilds)
            users = _parse_list(discord_allowed_users)
            if guilds:
                settings["allowed_guilds"] = guilds
            if users:
                settings["allowed_users"] = users
            channels.append({"type": "discord", "enabled": True, "settings": settings})
        if enable_telegram:
            settings = {
                "token_env": "TELEGRAM_BOT_TOKEN",
                "command_prefix": telegram_command_prefix,
            }
            chats = _parse_list(telegram_allowed_chats)
            users = _parse_list(telegram_allowed_users)
            if chats:
                settings["allowed_chats"] = chats
            if users:
                settings["allowed_users"] = users
            channels.append({"type": "telegram", "enabled": True, "settings": settings})
        if enable_whatsapp:
            settings = {
                "token_env": "WHATSAPP_ACCESS_TOKEN",
                "phone_number_id_env": "WHATSAPP_PHONE_NUMBER_ID",
                "verify_token_env": "WHATSAPP_VERIFY_TOKEN",
                "app_secret_env": "WHATSAPP_APP_SECRET",
                "graph_version": whatsapp_graph_version,
            }
            numbers = _parse_list(whatsapp_allowed_numbers)
            if numbers:
                settings["allowed_numbers"] = numbers
            channels.append({"type": "whatsapp", "enabled": True, "settings": settings})

        config_path = Path(__file__).resolve().parents[1] / "config" / "channels.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps({"channels": channels}, indent=2, ensure_ascii=True) + "\n")
        channels_config_path = str(config_path)
        persisted.append(channels_config_path)

    return {
        "persisted": persisted,
        "local_base_url": local_base,
        "env_file": env_path,
        "channels_config_path": channels_config_path,
    }


async def index(request: web.Request) -> web.Response:
    ui_root: Path = request.app["ui_root"]
    html = (ui_root / "index.html").read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")


async def setup_config(request: web.Request) -> web.Response:
    env_defaults = _read_env_file()
    defaults = {
        "XAI_API_KEY": env_defaults.get("XAI_API_KEY") or _read_secret("xai", "xai_api"),
        "VERA_LLM_BASE_URL": env_defaults.get("VERA_LLM_BASE_URL") or _read_secret("local", "llm_base_url"),
        "VERA_LLM_API_KEY": env_defaults.get("VERA_LLM_API_KEY") or _read_secret("local", "llm_api_key"),
        "VERA_MODEL": env_defaults.get("VERA_MODEL") or _read_secret("local", "model_id"),
        "BRAVE_API_KEY": env_defaults.get("BRAVE_API_KEY") or _read_secret("brave", "brave_api"),
        "GITHUB_PERSONAL_ACCESS_TOKEN": env_defaults.get("GITHUB_PERSONAL_ACCESS_TOKEN") or _read_secret("git", "git_token"),
        "SEARXNG_BASE_URL": env_defaults.get("SEARXNG_BASE_URL") or _read_secret("searxng", "searxng_url"),
        "OBSIDIAN_VAULT_PATH": env_defaults.get("OBSIDIAN_VAULT_PATH") or _read_secret("obsidian", "vault_path"),
        "MCP_HUB_COMMAND": env_defaults.get("MCP_HUB_COMMAND") or _read_secret("hub", "command"),
        "MCP_HUB_ARGS": env_defaults.get("MCP_HUB_ARGS") or _read_secret("hub", "args"),
        "COMPOSIO_API_KEY": env_defaults.get("COMPOSIO_API_KEY") or _read_secret("hub", "composio_api_key"),
        "VERA_BROWSER": env_defaults.get("VERA_BROWSER", ""),
        "GOOGLE_WORKSPACE_USER_EMAIL": env_defaults.get("GOOGLE_WORKSPACE_USER_EMAIL") or _read_secret("google", "user_email"),
        "GOOGLE_OAUTH_CLIENT_ID": env_defaults.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        "GOOGLE_OAUTH_CLIENT_SECRET": env_defaults.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        "GOOGLE_OAUTH_REDIRECT_URI": env_defaults.get("GOOGLE_OAUTH_REDIRECT_URI", ""),
        "TELEGRAM_BOT_TOKEN": env_defaults.get("TELEGRAM_BOT_TOKEN") or _read_secret("telegram", "bot_token"),
        "TELEGRAM_ALLOWED_CHATS": env_defaults.get("TELEGRAM_ALLOWED_CHATS", ""),
        "TELEGRAM_ALLOWED_USERS": env_defaults.get("TELEGRAM_ALLOWED_USERS", ""),
        "TELEGRAM_COMMAND_PREFIX": env_defaults.get("TELEGRAM_COMMAND_PREFIX", "/"),
        "WHATSAPP_ACCESS_TOKEN": env_defaults.get("WHATSAPP_ACCESS_TOKEN") or _read_secret("whatsapp", "access_token"),
        "WHATSAPP_PHONE_NUMBER_ID": env_defaults.get("WHATSAPP_PHONE_NUMBER_ID") or _read_secret("whatsapp", "phone_number_id"),
        "WHATSAPP_VERIFY_TOKEN": env_defaults.get("WHATSAPP_VERIFY_TOKEN") or _read_secret("whatsapp", "verify_token"),
        "WHATSAPP_APP_SECRET": env_defaults.get("WHATSAPP_APP_SECRET") or _read_secret("whatsapp", "app_secret"),
        "WHATSAPP_ALLOWED_NUMBERS": env_defaults.get("WHATSAPP_ALLOWED_NUMBERS", ""),
        "WHATSAPP_GRAPH_VERSION": env_defaults.get("WHATSAPP_GRAPH_VERSION", "v20.0"),
        "DISCORD_BOT_TOKEN": env_defaults.get("DISCORD_BOT_TOKEN") or _read_secret("discord", "bot_token"),
        "DISCORD_ALLOWED_GUILDS": env_defaults.get("DISCORD_ALLOWED_GUILDS", ""),
        "DISCORD_ALLOWED_USERS": env_defaults.get("DISCORD_ALLOWED_USERS", ""),
        "DISCORD_COMMAND_PREFIX": env_defaults.get("DISCORD_COMMAND_PREFIX", "!"),
    }
    return web.json_response({"main_url": request.app["main_url"], "defaults": defaults})


async def save_setup(request: web.Request) -> web.Response:
    payload = await request.json()
    xai_key = (payload.get("XAI_API_KEY") or "").strip()
    local_base = _normalize_url(payload.get("VERA_LLM_BASE_URL", ""))
    if not xai_key and not local_base:
        return web.json_response(
            {"ok": False, "error": "Provide XAI_API_KEY or a local endpoint."}, status=400
        )
    enable_telegram = _parse_bool(payload.get("ENABLE_TELEGRAM"))
    enable_whatsapp = _parse_bool(payload.get("ENABLE_WHATSAPP"))
    enable_discord = _parse_bool(payload.get("ENABLE_DISCORD"))

    if enable_telegram and not (payload.get("TELEGRAM_BOT_TOKEN") or "").strip():
        return web.json_response(
            {"ok": False, "error": "Telegram enabled but TELEGRAM_BOT_TOKEN is missing."}, status=400
        )
    if enable_whatsapp:
        access_token = (payload.get("WHATSAPP_ACCESS_TOKEN") or "").strip()
        phone_id = (payload.get("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
        if not access_token or not phone_id:
            return web.json_response(
                {"ok": False, "error": "WhatsApp enabled but access token or phone number ID is missing."},
                status=400,
            )
    if enable_discord and not (payload.get("DISCORD_BOT_TOKEN") or "").strip():
        return web.json_response(
            {"ok": False, "error": "Discord enabled but DISCORD_BOT_TOKEN is missing."}, status=400
        )
    result = _persist_payload(payload)
    return web.json_response({"ok": True, **result})


async def complete_setup(request: web.Request) -> web.Response:
    payload = await request.json() if request.can_read_body else {}
    delay_seconds = float(payload.get("delay_seconds", 0))
    creds_dir = _creds_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)
    sentinel = creds_dir / ".vera_bootstrap_complete"
    _atomic_write(sentinel, "complete\n")

    async def _shutdown_after() -> None:
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        request.app["shutdown_event"].set()

    asyncio.create_task(_shutdown_after())
    return web.json_response({"ok": True})


async def main() -> None:
    parser = argparse.ArgumentParser(description="VERA setup wizard server")
    parser.add_argument("--host", default=os.getenv("VERA_SETUP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("VERA_SETUP_PORT", "8787")))
    parser.add_argument("--main-host", default=os.getenv("VERA_API_HOST", "127.0.0.1"))
    parser.add_argument("--main-port", type=int, default=int(os.getenv("VERA_API_PORT", "8000")))
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()

    ui_root = Path(__file__).resolve().parents[1] / "ui" / "setup-wizard"
    if not ui_root.exists():
        raise SystemExit(f"Setup UI not found at {ui_root}")

    app = web.Application()
    app["ui_root"] = ui_root
    app["shutdown_event"] = asyncio.Event()
    app["main_url"] = f"http://{args.main_host}:{args.main_port}"
    app.router.add_get("/", index)
    app.router.add_get("/api/setup/config", setup_config)
    app.router.add_static("/assets", ui_root, show_index=False)
    app.router.add_post("/api/setup/save", save_setup)
    app.router.add_post("/api/setup/complete", complete_setup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    try:
        await site.start()
    except OSError as exc:
        print(f"[SETUP] Unable to start wizard on {args.host}:{args.port} ({exc})")
        await runner.cleanup()
        raise SystemExit(1) from exc

    loop = asyncio.get_running_loop()

    def _handle_shutdown(sig_name: str) -> None:
        print(f"[SETUP] Received {sig_name}, shutting down.")
        app["shutdown_event"].set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_shutdown, sig.name)
        except NotImplementedError:
            continue

    url = f"http://{args.host}:{args.port}"
    print(f"[SETUP] Wizard running at {url}")
    if args.open_browser:
        if args.host in {"0.0.0.0", "::"}:
            url = f"http://127.0.0.1:{args.port}"
        asyncio.create_task(asyncio.to_thread(webbrowser.open, url, new=1))

    try:
        await app["shutdown_event"].wait()
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

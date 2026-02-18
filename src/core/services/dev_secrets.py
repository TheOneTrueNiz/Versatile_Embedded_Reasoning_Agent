"""
Developer Secret Helpers
========================

Keychain-backed secret lookup for local developer workflows.

Behavior:
- Prefer existing environment variables.
- If missing, try OS keychain backends:
  - Linux: secret-tool (libsecret)
  - macOS: security
- Optionally prime os.environ for known runtime variables.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Dict, Iterable, Optional, Tuple

DEFAULT_SECRET_ENV_VARS: Tuple[str, ...] = (
    "XAI_API_KEY",
    "API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "BRAVE_API_KEY",
    "GITHUB_PERSONAL_ACCESS_TOKEN",
    "SEARXNG_BASE_URL",
    "COMPOSIO_API_KEY",
    "MCP_HUB_COMMAND",
    "MCP_HUB_ARGS",
    "YOUTUBE_API_KEY",
    "BROWSERBASE_API_KEY",
    "BROWSERBASE_PROJECT_ID",
    "SCRAPELESS_KEY",
    "TWITTER_API_KEY",
    "TWITTER_API_SECRET",
    "TWITTER_ACCESS_TOKEN",
    "TWITTER_ACCESS_TOKEN_SECRET",
    "TWITTER_BEARER_TOKEN",
    "CALLME_NGROK_AUTHTOKEN",
    "NGROK_AUTHTOKEN",
    "CALLME_NGROK_DOMAIN",
    "CALLME_PHONE_AUTH_TOKEN",
    "CALLME_PHONE_ACCOUNT_SID",
    "CALLME_TELNYX_PUBLIC_KEY",
    "CALLME_PHONE_NUMBER",
    "CALLME_SMS_FROM_NUMBER",
    "CALLME_MESSAGING_PROFILE_ID",
    "CALLME_USER_PHONE_NUMBER",
    "CALLME_USER_NAME",
    "GOOGLE_WORKSPACE_USER_EMAIL",
    "OBSIDIAN_VAULT_PATH",
    "VERA_LLM_BASE_URL",
    "VERA_LLM_API_KEY",
    "VERA_MODEL",
)


def _run_command(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _backend_preference() -> str:
    return (os.getenv("VERA_KEYCHAIN_BACKEND") or "auto").strip().lower()


def _service_name() -> str:
    return (os.getenv("VERA_KEYCHAIN_SERVICE") or "vera.dev").strip()


def _lookup_linux_secret(name: str, service: str) -> str:
    return _run_command(["secret-tool", "lookup", "service", service, "account", name])


def _lookup_macos_secret(name: str, service: str) -> str:
    return _run_command(["security", "find-generic-password", "-s", service, "-a", name, "-w"])


def read_secret_from_keychain(name: str, service: Optional[str] = None) -> str:
    service_name = service or _service_name()
    pref = _backend_preference()
    system = platform.system().lower()

    candidates: list[str]
    if pref in {"secret-tool", "libsecret", "linux"}:
        candidates = ["linux"]
    elif pref in {"security", "macos", "osx"}:
        candidates = ["macos"]
    elif pref in {"none", "off", "disabled"}:
        candidates = []
    else:
        # auto
        candidates = []
        if "linux" in system:
            candidates.append("linux")
            candidates.append("macos")
        elif "darwin" in system:
            candidates.append("macos")
            candidates.append("linux")
        else:
            candidates.extend(["linux", "macos"])

    for candidate in candidates:
        if candidate == "linux":
            value = _lookup_linux_secret(name, service_name)
        else:
            value = _lookup_macos_secret(name, service_name)
        if value:
            return value
    return ""


def get_secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    return read_secret_from_keychain(name)


def prime_environment_from_keychain(
    names: Optional[Iterable[str]] = None,
    overwrite: bool = False,
) -> Dict[str, str]:
    loaded: Dict[str, str] = {}
    target_names = tuple(names) if names is not None else DEFAULT_SECRET_ENV_VARS
    for name in target_names:
        current = (os.getenv(name) or "").strip()
        if current and not overwrite:
            continue
        value = read_secret_from_keychain(name)
        if value:
            os.environ[name] = value
            loaded[name] = value

    # Compatibility alias for legacy callers.
    if not os.getenv("API_KEY") and os.getenv("XAI_API_KEY"):
        os.environ["API_KEY"] = os.environ["XAI_API_KEY"]
        loaded["API_KEY"] = os.environ["XAI_API_KEY"]

    return loaded

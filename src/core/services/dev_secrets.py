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
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

DEFAULT_SECRET_ENV_VARS: Tuple[str, ...] = (
    "XAI_VIDEO_API_KEY",
    "XAI_IMAGE_API_KEY",
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
    "VERA_API_KEY",
)

DEFAULT_CREDS_DIR = Path(
    os.getenv("VERA_CREDS_DIR") or os.getenv("CREDS_DIR") or "~/.config/vera/creds"
).expanduser()
CREDS_FALLBACK_PATHS: Dict[str, str] = {
    "XAI_VIDEO_API_KEY": "xai/xai_video_api",
    "XAI_IMAGE_API_KEY": "xai/xai_image_api",
    "XAI_API_KEY": "xai/xai_api",
    "API_KEY": "xai/xai_api",
    "ANTHROPIC_API_KEY": "anthropic/anthropic_api",
    "OPENAI_API_KEY": "openai/openai_api",
    "GOOGLE_API_KEY": "google/google_api",
    "GEMINI_API_KEY": "google/google_api",
    "BRAVE_API_KEY": "brave/brave_api",
    "GITHUB_PERSONAL_ACCESS_TOKEN": "git/git_token",
    "SEARXNG_BASE_URL": "searxng/searxng_url",
    "COMPOSIO_API_KEY": "composio/composio_api",
    "YOUTUBE_API_KEY": "google/youtube_api_key",
    "BROWSERBASE_API_KEY": "browserbase/browserbase_api_key",
    "BROWSERBASE_PROJECT_ID": "browserbase/browserbase_project_id",
    "SCRAPELESS_KEY": "scrapeless/scrapeless_api",
    "TWITTER_API_KEY": "X/X_API_KEY",
    "TWITTER_API_SECRET": "X/X_API_KEY_SECRET",
    "TWITTER_ACCESS_TOKEN": "X/Access_Token",
    "TWITTER_ACCESS_TOKEN_SECRET": "X/Access_Token_Secret",
    "TWITTER_BEARER_TOKEN": "X/Bearer_Token",
    "CALLME_NGROK_AUTHTOKEN": "ngrok/ngrok_auth_token",
    "NGROK_AUTHTOKEN": "ngrok/ngrok_auth_token",
    "CALLME_NGROK_DOMAIN": "ngrok/domain",
    "CALLME_PHONE_AUTH_TOKEN": "telnyx/telnyx_api_key",
    "CALLME_PHONE_ACCOUNT_SID": "telnyx/connection_id",
    "CALLME_TELNYX_PUBLIC_KEY": "telnyx/public_key",
    "CALLME_PHONE_NUMBER": "telnyx/phone_number",
    "CALLME_SMS_FROM_NUMBER": "telnyx/sms_from_number",
    "CALLME_MESSAGING_PROFILE_ID": "telnyx/messaging_profile_id",
    "CALLME_USER_PHONE_NUMBER": "telnyx/user_phone_number",
    "CALLME_USER_NAME": "vera/user_name",
    "GOOGLE_WORKSPACE_USER_EMAIL": "google/user_email",
    "OBSIDIAN_VAULT_PATH": "obsidian/vault_path",
    "VERA_LLM_BASE_URL": "local/llm_base_url",
    "VERA_LLM_API_KEY": "local/llm_api_key",
    "VERA_MODEL": "local/model_id",
    "VERA_API_KEY": "vera/api_key",
}


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


def _normalize_creds_value(name: str, raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        lower = candidate.lower()
        prefix = f"export {name.lower()}="
        if lower.startswith(prefix):
            candidate = candidate[len(prefix):].strip()
        elif candidate.startswith(f"{name}="):
            candidate = candidate[len(name) + 1:].strip()
        if (candidate.startswith('"') and candidate.endswith('"')) or (
            candidate.startswith("'") and candidate.endswith("'")
        ):
            candidate = candidate[1:-1]
        candidate = candidate.strip()
        if candidate:
            return candidate
    return ""


def read_secret_from_creds(name: str, creds_dir: Optional[Path] = None) -> str:
    rel = CREDS_FALLBACK_PATHS.get(name)
    if not rel:
        return ""
    base = (creds_dir or DEFAULT_CREDS_DIR).expanduser()
    path = base / rel
    candidates = [path]
    if path.is_dir():
        candidates.extend(
            [
                path / name,
                path / name.lower(),
                path / name.upper(),
            ]
        )
    else:
        parent = path.parent
        candidates.extend(
            [
                parent / name,
                parent / name.lower(),
                parent / name.upper(),
            ]
        )
    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            if not candidate.exists() or not candidate.is_file():
                continue
            raw = candidate.read_text(encoding="utf-8", errors="ignore")
            value = _normalize_creds_value(name, raw)
            if value:
                return value
        except OSError:
            continue
    return ""


def get_secret(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if value:
        return value
    value = read_secret_from_keychain(name)
    if value:
        return value
    return read_secret_from_creds(name)


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
        if not value:
            value = read_secret_from_creds(name)
        if value:
            os.environ[name] = value
            loaded[name] = value

    # Compatibility alias for legacy callers.
    if not os.getenv("API_KEY") and os.getenv("XAI_API_KEY"):
        os.environ["API_KEY"] = os.environ["XAI_API_KEY"]
        loaded["API_KEY"] = os.environ["XAI_API_KEY"]

    return loaded

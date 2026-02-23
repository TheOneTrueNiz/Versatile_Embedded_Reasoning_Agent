"""
Layered Credential Resolution
==============================

Resolves API credentials for LLM providers using a layered approach
ported from Moltbot's auth-profiles pattern:

    1. Config file credentials (vera_config.yaml)
    2. Environment variables (XAI_API_KEY, ANTHROPIC_API_KEY, etc.)
    3. Credentials directory files (~/Documents/creds/)

Supports credential rotation and last-good tracking.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from orchestration.providers.base import ProviderCredential

logger = logging.getLogger(__name__)

# Default env var names per provider
PROVIDER_ENV_VARS: Dict[str, List[str]] = {
    "grok": ["VERA_LLM_API_KEY", "XAI_API_KEY", "API_KEY"],
    "claude": ["ANTHROPIC_API_KEY"],
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
}

# Default base URLs per provider
PROVIDER_BASE_URLS: Dict[str, str] = {
    "grok": "https://api.x.ai/v1",
    "claude": "https://api.anthropic.com",
    "gemini": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
}

# Credentials directory file paths per provider
PROVIDER_CRED_FILES: Dict[str, str] = {
    "grok": "xai/xai_api",
    "claude": "anthropic/anthropic_api",
    "gemini": "google/google_api",
    "openai": "openai/openai_api",
}


@dataclass
class AuthProfile:
    """A single authentication profile for a provider."""
    profile_id: str
    provider_id: str
    credential: ProviderCredential
    last_used_at: Optional[float] = None
    last_good_at: Optional[float] = None
    failure_count: int = 0
    source: str = ""  # "config", "env:VAR_NAME", "creds:path"


@dataclass
class AuthProfileStore:
    """Persisted credential store with rotation and last-good tracking.

    Stores multiple profiles per provider, tracks which ones work,
    and supports round-robin rotation for load distribution.
    """
    version: int = 1
    profiles: Dict[str, AuthProfile] = field(default_factory=dict)
    # Ordered list of profile IDs per provider
    rotation_order: Dict[str, List[str]] = field(default_factory=dict)
    # Last known good profile per provider
    last_good: Dict[str, str] = field(default_factory=dict)

    def add_profile(self, profile: AuthProfile) -> None:
        """Add or update a profile."""
        key = f"{profile.provider_id}:{profile.profile_id}"
        self.profiles[key] = profile
        if profile.provider_id not in self.rotation_order:
            self.rotation_order[profile.provider_id] = []
        if key not in self.rotation_order[profile.provider_id]:
            self.rotation_order[profile.provider_id].append(key)

    def get_profiles_for_provider(self, provider_id: str) -> List[AuthProfile]:
        """Get all profiles for a provider, ordered by rotation preference."""
        order = self.rotation_order.get(provider_id, [])
        # Prioritize last-good profile
        last_good_key = self.last_good.get(provider_id)
        if last_good_key and last_good_key in order:
            order = [last_good_key] + [k for k in order if k != last_good_key]
        return [self.profiles[k] for k in order if k in self.profiles]

    def mark_good(self, provider_id: str, profile_id: str) -> None:
        """Mark a profile as the last known good for its provider."""
        key = f"{provider_id}:{profile_id}"
        if key in self.profiles:
            self.profiles[key].last_good_at = time.time()
            self.profiles[key].last_used_at = time.time()
            self.profiles[key].failure_count = 0
            self.last_good[provider_id] = key

    def mark_bad(self, provider_id: str, profile_id: str) -> None:
        """Record a failure for a profile."""
        key = f"{provider_id}:{profile_id}"
        if key in self.profiles:
            self.profiles[key].failure_count += 1
            self.profiles[key].last_used_at = time.time()

    def save(self, path: Path) -> None:
        """Persist store to disk."""
        data = {
            "version": self.version,
            "last_good": self.last_good,
            "rotation_order": self.rotation_order,
            "profiles": {
                k: {
                    "profile_id": p.profile_id,
                    "provider_id": p.provider_id,
                    "source": p.source,
                    "last_used_at": p.last_used_at,
                    "last_good_at": p.last_good_at,
                    "failure_count": p.failure_count,
                    # Never persist actual keys to the store file
                }
                for k, p in self.profiles.items()
            },
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        tmp.rename(path)

    @classmethod
    def load(cls, path: Path) -> "AuthProfileStore":
        """Load store from disk (metadata only, not credentials)."""
        store = cls()
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                store.version = data.get("version", 1)
                store.last_good = data.get("last_good", {})
                store.rotation_order = data.get("rotation_order", {})
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load auth profile store: {e}")
        return store


def _read_cred_file(creds_dir: Path, relative_path: str) -> Optional[str]:
    """Read a credential from a file, stripping whitespace."""
    path = creds_dir / relative_path
    if path.exists():
        try:
            content = path.read_text().strip()
            if content:
                return content
        except OSError as e:
            logger.debug(f"Failed to read credential file {path}: {e}")
    return None


def resolve_credential(
    provider_id: str,
    config_credentials: Optional[Dict[str, Any]] = None,
    creds_dir: Optional[Path] = None,
    store: Optional[AuthProfileStore] = None,
) -> Optional[ProviderCredential]:
    """Resolve a credential for a provider using layered lookup.

    Resolution order:
        1. Config file credentials (passed as config_credentials dict)
        2. Environment variables (provider-specific)
        3. Credentials directory files

    Args:
        provider_id: Provider to resolve for ('grok', 'claude', 'gemini', 'openai')
        config_credentials: Credentials from config file (optional)
        creds_dir: Credentials directory path (defaults to ~/Documents/creds)
        store: AuthProfileStore for tracking which credential was used

    Returns:
        ProviderCredential if found, None otherwise
    """
    if creds_dir is None:
        creds_dir = Path(os.getenv("CREDS_DIR", "~/Documents/creds")).expanduser()

    base_url_env = os.getenv("VERA_LLM_BASE_URL", "").strip()
    default_url = PROVIDER_BASE_URLS.get(provider_id, "https://api.x.ai/v1")
    if base_url_env:
        from orchestration.llm_bridge import _validate_llm_base_url
        base_url = _validate_llm_base_url(base_url_env, default_url)
    else:
        base_url = default_url

    # Layer 1: Config file credentials
    if config_credentials and provider_id in config_credentials:
        cred_config = config_credentials[provider_id]
        api_key = cred_config.get("api_key", "")
        if api_key:
            cred = ProviderCredential(
                provider_id=provider_id,
                credential_type="api_key",
                key=api_key,
                base_url=cred_config.get("base_url", base_url),
                extra=cred_config.get("extra", {}),
            )
            logger.debug(f"Resolved {provider_id} credential from config")
            if store:
                profile = AuthProfile(
                    profile_id="config",
                    provider_id=provider_id,
                    credential=cred,
                    source="config",
                )
                store.add_profile(profile)
            return cred

    # Layer 2: Environment variables
    env_vars = PROVIDER_ENV_VARS.get(provider_id, [])
    for var_name in env_vars:
        api_key = os.getenv(var_name, "").strip()
        if api_key:
            cred = ProviderCredential(
                provider_id=provider_id,
                credential_type="api_key",
                key=api_key,
                base_url=base_url,
            )
            logger.debug(f"Resolved {provider_id} credential from env:{var_name}")
            if store:
                profile = AuthProfile(
                    profile_id=f"env_{var_name}",
                    provider_id=provider_id,
                    credential=cred,
                    source=f"env:{var_name}",
                )
                store.add_profile(profile)
            return cred

    # Layer 3: Credentials directory files
    cred_file = PROVIDER_CRED_FILES.get(provider_id)
    if cred_file:
        api_key = _read_cred_file(creds_dir, cred_file)
        if api_key:
            cred = ProviderCredential(
                provider_id=provider_id,
                credential_type="api_key",
                key=api_key,
                base_url=base_url,
            )
            logger.debug(f"Resolved {provider_id} credential from creds dir")
            if store:
                profile = AuthProfile(
                    profile_id=f"file_{cred_file}",
                    provider_id=provider_id,
                    credential=cred,
                    source=f"creds:{cred_file}",
                )
                store.add_profile(profile)
            return cred

    logger.debug(f"No credential found for provider {provider_id}")
    return None


def resolve_all_credentials(
    provider_ids: Optional[List[str]] = None,
    config_credentials: Optional[Dict[str, Any]] = None,
    creds_dir: Optional[Path] = None,
) -> Dict[str, ProviderCredential]:
    """Resolve credentials for all (or specified) providers.

    Returns:
        Dict mapping provider_id to ProviderCredential for all providers
        that have valid credentials.
    """
    if provider_ids is None:
        provider_ids = list(PROVIDER_ENV_VARS.keys())

    results = {}
    for pid in provider_ids:
        cred = resolve_credential(pid, config_credentials, creds_dir)
        if cred:
            results[pid] = cred

    found = list(results.keys())
    missing = [p for p in provider_ids if p not in results]
    if found:
        logger.info(f"Credentials resolved for: {', '.join(found)}")
    if missing:
        logger.debug(f"No credentials for: {', '.join(missing)}")

    return results

"""
Native Push Notification Service
================================

Stores native device tokens and dispatches push notifications via FCM.
Designed so APNs-specific transport can be added later without changing
the HTTP API contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from core.atomic_io import atomic_json_write, safe_json_read

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except Exception:  # pragma: no cover - handled at runtime in status
    GoogleAuthRequest = None
    service_account = None

DEFAULT_STORAGE = Path("vera_memory") / "native_push_devices.json"
FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_platform(value: Any) -> str:
    platform = str(value or "").strip().lower()
    if platform in {"android", "ios", "web"}:
        return platform
    return "unknown"


def _normalize_tags(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, Sequence):
        values = [str(item).strip() for item in raw]
    else:
        return []
    seen: set[str] = set()
    tags: List[str] = []
    for value in values:
        if not value:
            continue
        tag = value.lower()
        if tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags


def _safe_data_map(data: Any) -> Dict[str, str]:
    if not isinstance(data, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in data.items():
        skey = str(key).strip()
        if not skey:
            continue
        if isinstance(value, (dict, list)):
            out[skey] = json.dumps(value, ensure_ascii=True)
        elif value is None:
            out[skey] = ""
        else:
            out[skey] = str(value)
    return out


@dataclass
class NativePushConfig:
    enabled: bool
    provider: str
    configured: bool
    project_id: str
    reason: str = ""
    service_account_path: str = ""


class NativePushNotificationService:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = Path(storage_path or DEFAULT_STORAGE)
        self._lock = asyncio.Lock()
        self._service_account_info: Dict[str, Any] = {}
        self._config = self._load_config()
        self._access_token: str = ""
        self._access_token_expiry: float = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._config.enabled)

    @property
    def configured(self) -> bool:
        return bool(self._config.configured)

    def status(self) -> Dict[str, Any]:
        devices = self.list_devices()
        return {
            "enabled": self._config.enabled,
            "provider": self._config.provider,
            "configured": self._config.configured,
            "project_id": self._config.project_id,
            "service_account_path": self._config.service_account_path,
            "reason": self._config.reason,
            "device_count": len(devices),
            "google_auth_available": bool(GoogleAuthRequest and service_account),
        }

    def list_devices(self) -> List[Dict[str, Any]]:
        state = self._load_state()
        devices = state.get("devices", [])
        return devices if isinstance(devices, list) else []

    def register_device(self, payload: Dict[str, Any]) -> Tuple[bool, str]:
        token = str(payload.get("token") or payload.get("device_token") or "").strip()
        if len(token) < 20:
            return False, "Invalid token"

        provider = str(payload.get("provider") or self._config.provider or "fcm").strip().lower()
        if provider != "fcm":
            return False, "Only provider=fcm is supported in Vera 2.0"

        platform = _normalize_platform(payload.get("platform"))
        tags = _normalize_tags(payload.get("tags"))
        user_id = str(payload.get("user_id") or "").strip()
        app_id = str(payload.get("app_id") or "").strip()
        label = str(payload.get("label") or "").strip()
        now = _now_iso()

        state = self._load_state()
        devices = state.get("devices", [])
        if not isinstance(devices, list):
            devices = []

        existing_idx: Optional[int] = None
        for idx, item in enumerate(devices):
            if isinstance(item, dict) and item.get("token") == token and item.get("provider") == provider:
                existing_idx = idx
                break

        normalized = {
            "token": token,
            "provider": provider,
            "platform": platform,
            "tags": tags,
            "user_id": user_id,
            "app_id": app_id,
            "label": label,
            "updated_at": now,
        }

        if existing_idx is not None:
            existing = devices[existing_idx] if isinstance(devices[existing_idx], dict) else {}
            normalized["created_at"] = str(existing.get("created_at") or now)
            devices[existing_idx] = normalized
        else:
            normalized["created_at"] = now
            devices.append(normalized)

        state["devices"] = devices
        self._save_state(state)
        return True, token

    def unregister_device(self, token: str, provider: str = "fcm") -> bool:
        normalized_token = str(token or "").strip()
        normalized_provider = str(provider or "fcm").strip().lower()
        if not normalized_token:
            return False
        state = self._load_state()
        devices = state.get("devices", [])
        if not isinstance(devices, list):
            return False
        filtered = [
            item for item in devices
            if not (
                isinstance(item, dict)
                and str(item.get("token") or "").strip() == normalized_token
                and str(item.get("provider") or "").strip().lower() == normalized_provider
            )
        ]
        if len(filtered) == len(devices):
            return False
        state["devices"] = filtered
        self._save_state(state)
        return True

    async def broadcast(
        self,
        payload: Dict[str, Any],
        *,
        provider: str = "fcm",
        platforms: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self._config.enabled:
            return {"ok": False, "error": "native_push_disabled"}
        if not self._config.configured:
            return {"ok": False, "error": "native_push_not_configured", "reason": self._config.reason}
        if provider != "fcm":
            return {"ok": False, "error": "unsupported_provider"}

        title = str(payload.get("title") or "Vera").strip()
        body = str(payload.get("body") or "").strip()
        data = _safe_data_map(payload.get("data"))
        if not body:
            return {"ok": False, "error": "missing_body"}

        platform_set = {
            _normalize_platform(value)
            for value in (platforms or [])
            if str(value or "").strip()
        }
        tag_set = set(_normalize_tags(tags))

        devices = self._filter_devices(provider=provider, platform_set=platform_set, tag_set=tag_set)
        if not devices:
            return {"ok": False, "error": "no_devices"}

        results: Dict[str, Any] = {
            "ok": True,
            "provider": provider,
            "attempted": len(devices),
            "sent": 0,
            "failed": 0,
            "removed": 0,
            "errors": [],
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            for device in devices:
                sent, remove, detail = await self._send_one_fcm(client, device, title, body, data)
                if sent:
                    results["sent"] += 1
                else:
                    results["failed"] += 1
                    if detail and len(results["errors"]) < 5:
                        results["errors"].append(detail)
                if remove:
                    token = str(device.get("token") or "")
                    if token and self.unregister_device(token, provider="fcm"):
                        results["removed"] += 1

        if results["sent"] == 0:
            results["ok"] = False
            if not results["errors"]:
                results["errors"] = ["No pushes were delivered."]
        return results

    def preview_targets(
        self,
        *,
        provider: str = "fcm",
        platforms: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        normalized_provider = str(provider or "fcm").strip().lower() or "fcm"
        if normalized_provider != "fcm":
            return {"ok": False, "error": "unsupported_provider"}

        platform_set = {
            _normalize_platform(value)
            for value in (platforms or [])
            if str(value or "").strip()
        }
        tag_set = set(_normalize_tags(tags))
        devices = self._filter_devices(
            provider=normalized_provider,
            platform_set=platform_set,
            tag_set=tag_set,
        )

        return {
            "ok": True,
            "provider": normalized_provider,
            "filters": {
                "platforms": sorted(platform_set),
                "tags": sorted(tag_set),
            },
            "total_devices": len(self.list_devices()),
            "matched": len(devices),
            "devices": [self._sanitize_device(item) for item in devices],
        }

    def _filter_devices(
        self,
        *,
        provider: str,
        platform_set: set[str],
        tag_set: set[str],
    ) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in self.list_devices():
            if not isinstance(item, dict):
                continue
            if str(item.get("provider") or "").strip().lower() != provider:
                continue
            platform = _normalize_platform(item.get("platform"))
            if platform_set and platform not in platform_set:
                continue
            item_tags = set(_normalize_tags(item.get("tags")))
            if tag_set and not (item_tags & tag_set):
                continue
            out.append(item)
        return out

    def _sanitize_device(self, item: Dict[str, Any]) -> Dict[str, Any]:
        token = str(item.get("token") or "").strip()
        token_preview = ""
        if token:
            if len(token) > 20:
                token_preview = token[:8] + "..." + token[-6:]
            else:
                token_preview = token
        return {
            "provider": str(item.get("provider") or "").strip().lower(),
            "platform": _normalize_platform(item.get("platform")),
            "tags": _normalize_tags(item.get("tags")),
            "label": str(item.get("label") or "").strip(),
            "user_id": str(item.get("user_id") or "").strip(),
            "app_id": str(item.get("app_id") or "").strip(),
            "token_preview": token_preview,
            "created_at": str(item.get("created_at") or "").strip(),
            "updated_at": str(item.get("updated_at") or "").strip(),
        }

    async def _send_one_fcm(
        self,
        client: httpx.AsyncClient,
        device: Dict[str, Any],
        title: str,
        body: str,
        data: Dict[str, str],
    ) -> Tuple[bool, bool, str]:
        token = str(device.get("token") or "").strip()
        if not token:
            return False, False, "empty_token"

        headers = {"Content-Type": "application/json"}
        payload = {
            "message": {
                "token": token,
                "notification": {"title": title, "body": body},
                "data": data,
                "android": {"priority": "high"},
                "apns": {"headers": {"apns-priority": "10"}},
            }
        }

        for attempt in range(2):
            access_token = await asyncio.to_thread(self._get_fcm_access_token)
            headers["Authorization"] = f"Bearer {access_token}"
            response = await client.post(
                f"https://fcm.googleapis.com/v1/projects/{self._config.project_id}/messages:send",
                headers=headers,
                json=payload,
            )

            if response.status_code < 300:
                return True, False, ""

            detail, remove = self._parse_fcm_error(response)
            if response.status_code == 401 and attempt == 0:
                self._access_token = ""
                self._access_token_expiry = 0.0
                continue
            masked = token[:8] + "..." + token[-6:] if len(token) > 20 else token
            return False, remove, f"token={masked} {detail}"

        return False, False, "unknown_fcm_error"

    def _parse_fcm_error(self, response: httpx.Response) -> Tuple[str, bool]:
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:400]}
        error = payload.get("error") if isinstance(payload, dict) else {}
        status = str(error.get("status") or "").strip()
        message = str(error.get("message") or "").strip() or str(payload)
        remove = False
        details = error.get("details") if isinstance(error, dict) else None
        if isinstance(details, list):
            for item in details:
                if not isinstance(item, dict):
                    continue
                code = str(item.get("errorCode") or "").strip().upper()
                if code == "UNREGISTERED":
                    remove = True
                    break
        if status.upper() == "NOT_FOUND":
            remove = True
        return f"http={response.status_code} status={status} msg={message}", remove

    def _get_fcm_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < (self._access_token_expiry - 60):
            return self._access_token

        if not self._service_account_info:
            raise RuntimeError("FCM service account is not configured")
        if not service_account or not GoogleAuthRequest:
            raise RuntimeError("google-auth is not available")

        credentials = service_account.Credentials.from_service_account_info(
            self._service_account_info,
            scopes=[FCM_SCOPE],
        )
        credentials.refresh(GoogleAuthRequest())
        token = str(credentials.token or "").strip()
        if not token:
            raise RuntimeError("Failed to obtain FCM access token")
        self._access_token = token
        expiry = getattr(credentials, "expiry", None)
        self._access_token_expiry = expiry.timestamp() if expiry else (now + 3000)
        return token

    def _load_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._storage_path, default={"devices": []}) or {}
        if not isinstance(payload, dict):
            return {"devices": []}
        devices = payload.get("devices")
        if not isinstance(devices, list):
            payload["devices"] = []
        return payload

    def _save_state(self, state: Dict[str, Any]) -> None:
        atomic_json_write(self._storage_path, state, indent=2, sort_keys=False)

    def _load_config(self) -> NativePushConfig:
        enabled = _parse_bool(os.getenv("VERA_NATIVE_PUSH_ENABLED"), True)
        provider = str(os.getenv("VERA_NATIVE_PUSH_PROVIDER", "fcm")).strip().lower() or "fcm"
        if provider != "fcm":
            return NativePushConfig(
                enabled=enabled,
                provider=provider,
                configured=False,
                project_id="",
                reason=f"Unsupported provider: {provider}",
            )

        service_account_info, service_account_path = self._load_service_account()
        self._service_account_info = service_account_info
        project_id = str(os.getenv("VERA_FCM_PROJECT_ID", "")).strip()
        if not project_id:
            project_id = str(service_account_info.get("project_id") or "").strip()

        if not enabled:
            return NativePushConfig(
                enabled=False,
                provider=provider,
                configured=False,
                project_id=project_id,
                reason="VERA_NATIVE_PUSH_ENABLED is disabled",
                service_account_path=service_account_path,
            )
        if not service_account_info:
            return NativePushConfig(
                enabled=True,
                provider=provider,
                configured=False,
                project_id=project_id,
                reason="Missing FCM service account credentials",
                service_account_path=service_account_path,
            )
        if not project_id:
            return NativePushConfig(
                enabled=True,
                provider=provider,
                configured=False,
                project_id="",
                reason="Missing VERA_FCM_PROJECT_ID (or project_id in service account JSON)",
                service_account_path=service_account_path,
            )
        return NativePushConfig(
            enabled=True,
            provider=provider,
            configured=True,
            project_id=project_id,
            reason="",
            service_account_path=service_account_path,
        )

    def _load_service_account(self) -> Tuple[Dict[str, Any], str]:
        env_json = str(os.getenv("VERA_FCM_SERVICE_ACCOUNT_JSON", "")).strip()
        env_path = str(os.getenv("VERA_FCM_SERVICE_ACCOUNT_PATH", "")).strip()

        if env_json:
            if env_json.startswith("{"):
                try:
                    payload = json.loads(env_json)
                    if isinstance(payload, dict):
                        return payload, "env:VERA_FCM_SERVICE_ACCOUNT_JSON"
                except Exception:
                    return {}, "env:VERA_FCM_SERVICE_ACCOUNT_JSON (invalid JSON)"
            else:
                parsed = self._read_json_file(Path(env_json).expanduser())
                if parsed:
                    return parsed, str(Path(env_json).expanduser())
                return {}, str(Path(env_json).expanduser())

        candidates: List[Path] = []
        if env_path:
            candidates.append(Path(env_path).expanduser())
        creds_dir = Path(os.getenv("CREDS_DIR", "")).expanduser() if os.getenv("CREDS_DIR") else (Path.home() / "Documents" / "creds")
        candidates.extend([
            creds_dir / "firebase" / "service_account.json",
            creds_dir / "firebase" / "fcm_service_account.json",
            Path("config") / "firebase_service_account.json",
            Path("config") / "fcm_service_account.json",
        ])
        for path in candidates:
            parsed = self._read_json_file(path)
            if parsed:
                return parsed, str(path)
        return {}, (str(candidates[0]) if candidates else "")

    def _read_json_file(self, path: Path) -> Dict[str, Any]:
        try:
            if not path.exists():
                return {}
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

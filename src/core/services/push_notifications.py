"""
Web Push Notification Service
=============================

Stores browser subscriptions and sends Web Push notifications using VAPID.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pywebpush import webpush, WebPushException

from core.atomic_io import atomic_json_write, safe_json_read

logger = logging.getLogger(__name__)

DEFAULT_STORAGE = Path("vera_memory") / "push_subscriptions.json"
DEFAULT_VAPID_CONFIG = Path("config") / "vapid.json"


@dataclass
class VapidConfig:
    public_key: str
    private_key: str
    subject: str

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.private_key and self.subject)


def _load_vapid_config() -> VapidConfig:
    public_key = os.getenv("VAPID_PUBLIC_KEY", "") or os.getenv("VERA_VAPID_PUBLIC_KEY", "")
    private_key = os.getenv("VAPID_PRIVATE_KEY", "") or os.getenv("VERA_VAPID_PRIVATE_KEY", "")
    subject = os.getenv("VAPID_SUBJECT", "") or os.getenv("VERA_VAPID_SUBJECT", "")

    if not (public_key and private_key):
        if DEFAULT_VAPID_CONFIG.exists():
            try:
                payload = json.loads(DEFAULT_VAPID_CONFIG.read_text(encoding="utf-8"))
                public_key = public_key or payload.get("public_key", "")
                private_key = private_key or payload.get("private_key", "")
                subject = subject or payload.get("subject", "")
            except Exception as exc:
                logger.warning("Failed to read VAPID config: %s", exc)

    if not subject:
        subject = "mailto:vera@localhost"

    return VapidConfig(
        public_key=public_key.strip(),
        private_key=private_key.strip(),
        subject=subject.strip(),
    )


class PushNotificationService:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._storage_path = Path(storage_path or DEFAULT_STORAGE)
        self._vapid = _load_vapid_config()
        self._lock = asyncio.Lock()

    @property
    def vapid_public_key(self) -> str:
        return self._vapid.public_key

    @property
    def enabled(self) -> bool:
        return self._vapid.enabled

    @property
    def subject(self) -> str:
        return self._vapid.subject

    def _load_state(self) -> Dict[str, Any]:
        payload = safe_json_read(self._storage_path, default={"subscriptions": []}) or {}
        if not isinstance(payload, dict):
            return {"subscriptions": []}
        subs = payload.get("subscriptions")
        if not isinstance(subs, list):
            payload["subscriptions"] = []
        return payload

    def _save_state(self, state: Dict[str, Any]) -> None:
        atomic_json_write(self._storage_path, state, indent=2, sort_keys=False)

    def list_subscriptions(self) -> List[Dict[str, Any]]:
        state = self._load_state()
        subs = state.get("subscriptions", [])
        return subs if isinstance(subs, list) else []

    def add_subscription(self, subscription: Dict[str, Any]) -> Tuple[bool, str]:
        normalized = _normalize_subscription(subscription)
        if not normalized:
            return False, "Invalid subscription payload"

        state = self._load_state()
        subs = state.get("subscriptions", [])
        if not isinstance(subs, list):
            subs = []

        endpoint = normalized["endpoint"]
        existing = [s for s in subs if s.get("endpoint") == endpoint]
        if existing:
            for idx, sub in enumerate(subs):
                if sub.get("endpoint") == endpoint:
                    subs[idx] = normalized
                    break
        else:
            subs.append(normalized)

        state["subscriptions"] = subs
        self._save_state(state)
        return True, endpoint

    def remove_subscription(self, endpoint: str) -> bool:
        if not endpoint:
            return False
        state = self._load_state()
        subs = state.get("subscriptions", [])
        if not isinstance(subs, list):
            return False
        filtered = [s for s in subs if s.get("endpoint") != endpoint]
        if len(filtered) == len(subs):
            return False
        state["subscriptions"] = filtered
        self._save_state(state)
        return True

    async def broadcast(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "push_not_configured"}

        subs = self.list_subscriptions()
        if not subs:
            return {"ok": False, "error": "no_subscriptions"}

        results = {
            "ok": True,
            "sent": 0,
            "failed": 0,
            "removed": 0,
        }

        for sub in list(subs):
            ok, removed = await self._send_one(sub, payload)
            if ok:
                results["sent"] += 1
            else:
                results["failed"] += 1
            if removed:
                results["removed"] += 1

        return results

    async def _send_one(self, subscription: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[bool, bool]:
        data = json.dumps(payload, ensure_ascii=True)
        try:
            await asyncio.to_thread(
                webpush,
                subscription_info=subscription,
                data=data,
                vapid_private_key=self._vapid.private_key,
                vapid_claims={"sub": self._vapid.subject},
            )
            return True, False
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in {404, 410}:
                endpoint = subscription.get("endpoint", "")
                if endpoint:
                    self.remove_subscription(endpoint)
                return False, True
            logger.warning("Web push failed: %s", exc)
            return False, False
        except Exception as exc:
            logger.warning("Web push error: %s", exc)
            return False, False


def _normalize_subscription(subscription: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(subscription, dict):
        return None
    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}
    if not endpoint or not isinstance(keys, dict):
        return None
    normalized = {
        "endpoint": endpoint,
        "keys": {
            "p256dh": keys.get("p256dh", ""),
            "auth": keys.get("auth", ""),
        },
    }
    if subscription.get("expirationTime") is not None:
        normalized["expirationTime"] = subscription.get("expirationTime")
    return normalized

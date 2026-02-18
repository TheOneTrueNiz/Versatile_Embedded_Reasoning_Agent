"""
Tool Quota Manager
==================

Tracks hourly and daily tool call limits to prevent runaway API spend.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

try:
    from atomic_io import atomic_json_write, safe_json_read
    HAS_ATOMIC = True
except ImportError:
    HAS_ATOMIC = False


@dataclass
class QuotaLimits:
    daily: int = 0
    hourly: int = 0


DEFAULT_LIMITS: Dict[str, QuotaLimits] = {
    # Web search providers
    "brave": QuotaLimits(daily=200, hourly=40),
    "searxng": QuotaLimits(daily=200, hourly=60),

    # Media search
    "youtube": QuotaLimits(daily=100, hourly=20),

    # Paid scraping / browser automation
    "browserbase": QuotaLimits(daily=60, hourly=10),
    "scrapeless": QuotaLimits(daily=80, hourly=20),

    # Social APIs
    "twitter": QuotaLimits(daily=120, hourly=30),

    # Voice / telephony
    "call-me": QuotaLimits(daily=30, hourly=6),
}


class ToolQuotaManager:
    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self.storage_path = Path(
            storage_path
            or os.getenv(
                "VERA_TOOL_QUOTA_PATH",
                os.path.join("~", ".cache", "vera", "tool_quotas.json"),
            )
        ).expanduser()
        self.limits = self._load_limits()
        self._state = self._load_state()

    def _load_limits(self) -> Dict[str, QuotaLimits]:
        limits = {key: QuotaLimits(value.daily, value.hourly) for key, value in DEFAULT_LIMITS.items()}

        default_daily = os.getenv("VERA_TOOL_QUOTA_DEFAULT_DAILY")
        default_hourly = os.getenv("VERA_TOOL_QUOTA_DEFAULT_HOURLY")
        if default_daily or default_hourly:
            limits.setdefault("_default", QuotaLimits())
            if default_daily:
                try:
                    limits["_default"].daily = int(default_daily)
                except ValueError:
                    pass
            if default_hourly:
                try:
                    limits["_default"].hourly = int(default_hourly)
                except ValueError:
                    pass

        raw_overrides = os.getenv("VERA_TOOL_QUOTA_OVERRIDES", "").strip()
        if raw_overrides:
            try:
                overrides = json.loads(raw_overrides)
            except json.JSONDecodeError:
                overrides = {}
            if isinstance(overrides, dict):
                for key, value in overrides.items():
                    if not isinstance(value, dict):
                        continue
                    limits.setdefault(key, QuotaLimits())
                    if "daily" in value:
                        try:
                            limits[key].daily = int(value["daily"])
                        except (TypeError, ValueError):
                            pass
                    if "hourly" in value:
                        try:
                            limits[key].hourly = int(value["hourly"])
                        except (TypeError, ValueError):
                            pass

        return limits

    def _load_state(self) -> Dict[str, Dict[str, int]]:
        if not self.storage_path.exists():
            return {"day": "", "hour": "", "daily": {}, "hourly": {}}
        try:
            if HAS_ATOMIC:
                data = safe_json_read(self.storage_path)
            else:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {"day": "", "hour": "", "daily": {}, "hourly": {}}
        if not isinstance(data, dict):
            return {"day": "", "hour": "", "daily": {}, "hourly": {}}
        data.setdefault("day", "")
        data.setdefault("hour", "")
        data.setdefault("daily", {})
        data.setdefault("hourly", {})
        if not isinstance(data["daily"], dict):
            data["daily"] = {}
        if not isinstance(data["hourly"], dict):
            data["hourly"] = {}
        return data

    def _save_state(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        if HAS_ATOMIC:
            atomic_json_write(self.storage_path, self._state)
            return
        self.storage_path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")

    def _get_limits(self, key: str) -> Optional[QuotaLimits]:
        if key in self.limits:
            return self.limits[key]
        return self.limits.get("_default")

    def _tick_windows(self) -> Tuple[str, str]:
        now = datetime.now(timezone.utc)
        day = now.strftime("%Y-%m-%d")
        hour = now.strftime("%Y-%m-%dT%H")
        if self._state.get("day") != day:
            self._state["day"] = day
            self._state["daily"] = {}
        if self._state.get("hour") != hour:
            self._state["hour"] = hour
            self._state["hourly"] = {}
        return day, hour

    def check_and_record(self, key: str) -> Tuple[bool, str]:
        limits = self._get_limits(key)
        if not limits:
            return True, ""

        daily_limit = max(0, int(limits.daily)) if limits.daily else 0
        hourly_limit = max(0, int(limits.hourly)) if limits.hourly else 0

        if daily_limit == 0 and hourly_limit == 0:
            return True, ""

        self._tick_windows()
        daily_counts = self._state.get("daily", {})
        hourly_counts = self._state.get("hourly", {})

        daily_count = int(daily_counts.get(key, 0))
        hourly_count = int(hourly_counts.get(key, 0))

        if daily_limit and daily_count >= daily_limit:
            return False, f"daily limit {daily_limit} reached ({daily_count}/{daily_limit})"
        if hourly_limit and hourly_count >= hourly_limit:
            return False, f"hourly limit {hourly_limit} reached ({hourly_count}/{hourly_limit})"

        daily_counts[key] = daily_count + 1
        hourly_counts[key] = hourly_count + 1
        self._state["daily"] = daily_counts
        self._state["hourly"] = hourly_counts
        self._save_state()

        return True, ""

    def get_counts(self, key: str) -> Dict[str, int]:
        self._tick_windows()
        return {
            "daily": int(self._state.get("daily", {}).get(key, 0)),
            "hourly": int(self._state.get("hourly", {}).get(key, 0)),
        }

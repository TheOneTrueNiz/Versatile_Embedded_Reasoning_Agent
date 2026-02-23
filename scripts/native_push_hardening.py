#!/usr/bin/env python3
"""
Native push hardening + filter validation for Vera_2.0.

What this script does:
1) Verifies native push service status.
2) Optionally applies a default tag profile to locally registered devices.
3) Validates filter targeting via /api/push/native/targets.
4) Optionally runs one live targeted send via /api/push/native/test.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> Tuple[bool, Any, str]:
    try:
        response = client.request(method, url, **kwargs)
    except Exception as exc:
        return False, None, f"request failed: {exc}"

    try:
        payload = response.json()
    except Exception:
        payload = response.text

    if response.status_code >= 400:
        detail = json.dumps(payload, ensure_ascii=True) if isinstance(payload, (dict, list)) else str(payload)
        return False, payload, f"HTTP {response.status_code}: {detail[:240]}"
    return True, payload, ""


def _wait_for_api(client: httpx.Client, base_url: str, wait_seconds: float) -> bool:
    deadline = time.time() + max(0.0, wait_seconds)
    while time.time() < deadline:
        ok, data, _ = _request_json(client, "GET", f"{base_url}/api/health")
        if ok and isinstance(data, dict) and data.get("ok") is True:
            return True
        time.sleep(1.0)
    return False


def _normalize_tags(values: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for value in values:
        tag = str(value or "").strip().lower()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def _load_local_devices(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    devices = payload.get("devices")
    if not isinstance(devices, list):
        return []
    return [item for item in devices if isinstance(item, dict)]


def _print_step(ok: bool, label: str, detail: str = "") -> None:
    status = "OK" if ok else "FAIL"
    print(f"[{status}] {label}" + (f" - {detail}" if detail else ""), flush=True)


def _target_preview(
    client: httpx.Client,
    base_url: str,
    provider: str,
    platforms: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
) -> Tuple[bool, Dict[str, Any], str]:
    payload: Dict[str, Any] = {"provider": provider}
    if platforms:
        payload["platforms"] = platforms
    if tags:
        payload["tags"] = tags
    ok, data, err = _request_json(
        client,
        "POST",
        f"{base_url}/api/push/native/targets",
        json=payload,
    )
    return ok, data if isinstance(data, dict) else {"raw": data}, err


def main() -> int:
    parser = argparse.ArgumentParser(description="Harden and validate native push filters")
    parser.add_argument(
        "--base-url",
        default="",
        help="API base URL (overrides --host/--port), e.g. http://127.0.0.1:8788",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--wait", type=float, default=45.0, help="Seconds to wait for API")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds")
    parser.add_argument("--provider", default="fcm")
    parser.add_argument(
        "--default-tags",
        default="vera-prod,niz-primary,high-priority",
        help="Comma-separated tags to ensure on registered devices",
    )
    parser.add_argument(
        "--no-apply-tags",
        action="store_true",
        help="Do not update local device registrations with --default-tags",
    )
    parser.add_argument(
        "--no-live-send",
        action="store_true",
        help="Skip live push send and only validate targeting previews",
    )
    parser.add_argument(
        "--devices-file",
        default="vera_memory/native_push_devices.json",
        help="Local device storage JSON path",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output report path (default: tmp/native_push_hardening_<ts>.json)",
    )
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (root_dir / "tmp" / f"native_push_hardening_{ts}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    devices_path = Path(args.devices_file)
    if not devices_path.is_absolute():
        devices_path = root_dir / devices_path

    provider = str(args.provider or "fcm").strip().lower() or "fcm"
    ensure_tags = _normalize_tags([part.strip() for part in args.default_tags.split(",") if part.strip()])
    base_url_raw = str(args.base_url or "").strip()
    if base_url_raw:
        if "://" not in base_url_raw:
            base_url_raw = f"http://{base_url_raw}"
        parsed = urlparse(base_url_raw)
        if not parsed.scheme or not parsed.netloc:
            parser.error(f"invalid --base-url: {args.base_url!r}")
        base_url = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base_url = f"http://{args.host}:{args.port}"
    report: Dict[str, Any] = {
        "ok": False,
        "timestamp_utc": ts,
        "base_url": base_url,
        "provider": provider,
        "apply_tags": not args.no_apply_tags,
        "default_tags": ensure_tags,
        "checks": {},
        "cases": [],
        "live_send": {},
        "errors": [],
    }

    all_ok = True

    with httpx.Client(timeout=args.timeout) as client:
        if not _wait_for_api(client, base_url, args.wait):
            _print_step(False, "api", "API not ready")
            report["errors"].append("API not ready")
            output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
            return 1
        _print_step(True, "api", "ready")

        ok, data, err = _request_json(client, "GET", f"{base_url}/api/push/native/status")
        report["checks"]["native_status"] = {"ok": ok, "error": err, "data": data}
        if not ok or not isinstance(data, dict):
            _print_step(False, "native_status", err or "invalid response")
            all_ok = False
        else:
            enabled = bool(data.get("enabled"))
            configured = bool(data.get("configured"))
            device_count = int(data.get("device_count") or 0)
            detail = f"enabled={enabled}, configured={configured}, devices={device_count}"
            status_ok = enabled and configured and device_count > 0
            _print_step(status_ok, "native_status", detail)
            all_ok = all_ok and status_ok

        if not args.no_apply_tags:
            local_devices = _load_local_devices(devices_path)
            updates = 0
            failures = 0
            for item in local_devices:
                token = str(item.get("token") or "").strip()
                if not token:
                    continue
                current_tags = _normalize_tags(item.get("tags") if isinstance(item.get("tags"), list) else [])
                merged_tags = _normalize_tags(current_tags + ensure_tags)
                payload = {
                    "token": token,
                    "provider": str(item.get("provider") or provider).strip().lower() or provider,
                    "platform": str(item.get("platform") or "unknown"),
                    "tags": merged_tags,
                    "label": str(item.get("label") or "").strip(),
                    "user_id": str(item.get("user_id") or "").strip(),
                    "app_id": str(item.get("app_id") or "").strip(),
                }
                ok, data, err = _request_json(
                    client,
                    "POST",
                    f"{base_url}/api/push/native/register",
                    json=payload,
                )
                if ok:
                    updates += 1
                else:
                    failures += 1
                    report["errors"].append(f"register failed for token={token[:8]}...: {err}")
            apply_ok = failures == 0
            report["checks"]["apply_tag_profile"] = {
                "ok": apply_ok,
                "devices_seen": len(local_devices),
                "updated": updates,
                "failed": failures,
            }
            _print_step(apply_ok, "apply_tag_profile", f"updated={updates}, failed={failures}")
            all_ok = all_ok and apply_ok

        ok, targets_data, err = _target_preview(client, base_url, provider=provider)
        report["checks"]["targets_unfiltered"] = {"ok": ok, "error": err, "data": targets_data}
        if not ok:
            _print_step(False, "targets_unfiltered", err)
            all_ok = False
            available_platforms: List[str] = []
            available_tags: List[str] = []
        else:
            matched = int(targets_data.get("matched") or 0)
            _print_step(matched > 0, "targets_unfiltered", f"matched={matched}")
            all_ok = all_ok and (matched > 0)
            devices = targets_data.get("devices") if isinstance(targets_data, dict) else []
            available_platforms = []
            available_tags = []
            if isinstance(devices, list):
                for item in devices:
                    if not isinstance(item, dict):
                        continue
                    platform = str(item.get("platform") or "").strip().lower()
                    if platform and platform not in available_platforms:
                        available_platforms.append(platform)
                    tags = item.get("tags")
                    if isinstance(tags, list):
                        for tag in tags:
                            normalized = str(tag or "").strip().lower()
                            if normalized and normalized not in available_tags:
                                available_tags.append(normalized)

        primary_platform = available_platforms[0] if available_platforms else "android"
        primary_tag = available_tags[0] if available_tags else (ensure_tags[0] if ensure_tags else "vera-prod")
        missing_platform = next((p for p in ["android", "ios", "web"] if p not in set(available_platforms)), "web")
        missing_tag = "nonexistent-tag-for-filter-check"

        cases = [
            ("platform_match", {"platforms": [primary_platform]}, True),
            ("platform_miss", {"platforms": [missing_platform]}, False),
            ("tag_match", {"tags": [primary_tag]}, True),
            ("tag_miss", {"tags": [missing_tag]}, False),
            ("combined_match", {"platforms": [primary_platform], "tags": [primary_tag]}, True),
            ("combined_miss", {"platforms": [primary_platform], "tags": [missing_tag]}, False),
        ]

        for name, filters, should_match in cases:
            ok, data, err = _target_preview(
                client,
                base_url,
                provider=provider,
                platforms=filters.get("platforms"),
                tags=filters.get("tags"),
            )
            matched = int(data.get("matched") or 0) if ok and isinstance(data, dict) else 0
            case_ok = ok and ((matched > 0) == should_match)
            report["cases"].append(
                {
                    "name": name,
                    "filters": filters,
                    "expect_match": should_match,
                    "ok": case_ok,
                    "matched": matched,
                    "error": err if not ok else "",
                    "data": data,
                }
            )
            _print_step(case_ok, name, f"matched={matched}, expected_match={should_match}")
            all_ok = all_ok and case_ok

        if args.no_live_send:
            report["live_send"] = {"ok": True, "skipped": True}
            _print_step(True, "live_send", "skipped")
        else:
            live_payload = {
                "provider": provider,
                "title": "Vera",
                "body": f"[native-push-hardening:{ts}] targeted send",
                "data": {"source": "native_push_hardening", "ts": ts},
                "platforms": [primary_platform],
                "tags": [primary_tag],
            }
            ok, data, err = _request_json(
                client,
                "POST",
                f"{base_url}/api/push/native/test",
                json=live_payload,
            )
            send_ok = bool(ok and isinstance(data, dict) and data.get("ok") is True and int(data.get("sent") or 0) > 0)
            report["live_send"] = {
                "ok": send_ok,
                "request": live_payload,
                "error": err if not ok else "",
                "response": data,
            }
            _print_step(send_ok, "live_send", err if not send_ok else f"sent={data.get('sent')}")
            all_ok = all_ok and send_ok

    report["ok"] = bool(all_ok)
    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Report written to {output_path}", flush=True)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

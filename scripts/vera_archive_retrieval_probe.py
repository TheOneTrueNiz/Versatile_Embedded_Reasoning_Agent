#!/usr/bin/env python3
"""
Archive retrieval probe for native `search_archive`.

Creates controlled low-retention duplicate events so consolidation archives them,
then verifies the archive tool returns hits for the marker.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib import error, request


def _request_json(
    method: str,
    url: str,
    payload: Dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> Tuple[bool, Dict[str, Any], str]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=body, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return True, json.loads(raw), ""
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {raw}"
    except Exception as exc:
        return False, {}, str(exc)


def _wait_ready(base_url: str, timeout_seconds: int = 180) -> Dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last = {}
    while time.time() < deadline:
        ok, data, _ = _request_json("GET", f"{base_url}/api/readiness", timeout=5.0)
        if ok:
            last = data
            if data.get("ready"):
                return data
        time.sleep(2)
    return last


def _search_archive_count(base_url: str, marker: str) -> Tuple[int, Dict[str, Any]]:
    payload = {
        "name": "search_archive",
        "arguments": {"query": marker, "max_results": 20},
    }
    ok, data, _ = _request_json("POST", f"{base_url}/api/tools/call", payload=payload)
    if not ok:
        return 0, {}
    result = data.get("result") or {}
    try:
        count = int(result.get("count") or 0)
    except (TypeError, ValueError):
        count = 0
    return count, data


def _encode_seed_batch(base_url: str, marker: str, count: int) -> Tuple[int, int]:
    encoded_ok = 0
    encoded_fail = 0
    for _ in range(max(0, count)):
        payload = {
            "name": "encode_event",
            "arguments": {
                "content": f"{marker} duplicate payload",
                "type": "system_event",
                "timestamp": "2020-01-01T00:00:00",
                "tags": ["archive-probe", "duplicate"],
                "provenance": {"source_type": "system", "source_id": "archive_probe"},
            },
        }
        ok, data, _ = _request_json("POST", f"{base_url}/api/tools/call", payload=payload)
        if ok and data.get("type") == "native" and isinstance(data.get("result"), dict) and data["result"].get("status") == "encoded":
            encoded_ok += 1
        else:
            encoded_fail += 1
    return encoded_ok, encoded_fail


def run_probe(base_url: str, seed_events: int) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    marker = f"archive_retrieval_probe_marker_{ts}"
    report: Dict[str, Any] = {
        "timestamp_utc": ts,
        "base_url": base_url,
        "marker": marker,
        "seed_events": seed_events,
        "checks": {},
    }

    report["readiness"] = _wait_ready(base_url)

    ok_stats_pre, stats_pre, err_stats_pre = _request_json("GET", f"{base_url}/api/memory/stats")
    report["checks"]["memory_stats_pre"] = {"ok": ok_stats_pre, "error": err_stats_pre}
    if ok_stats_pre:
        report["checks"]["memory_stats_pre"]["archive_total"] = (
            ((stats_pre.get("stats") or {}).get("archive") or {}).get("total_archived")
        )

    before_count, before_resp = _search_archive_count(base_url, marker)
    report["checks"]["archive_search_before"] = {
        "count": before_count,
        "response": before_resp,
    }

    encoded_ok, encoded_fail = _encode_seed_batch(base_url, marker, max(1, seed_events))
    report["checks"]["encode_seed"] = {
        "ok": encoded_fail == 0,
        "encoded_ok": encoded_ok,
        "encoded_fail": encoded_fail,
    }

    # Give consolidation a short window to complete, then adaptively top up
    # if the fast-network threshold has not been crossed yet.
    time.sleep(3.0)
    after_count, after_resp = _search_archive_count(base_url, marker)
    adaptive_rounds = []
    for round_idx in range(1, 7):
        if after_count > 0:
            break
        extra_ok, extra_fail = _encode_seed_batch(base_url, marker, 10)
        encoded_ok += extra_ok
        encoded_fail += extra_fail
        time.sleep(1.0)
        after_count, after_resp = _search_archive_count(base_url, marker)
        adaptive_rounds.append({
            "round": round_idx,
            "extra_encoded_ok": extra_ok,
            "extra_encoded_fail": extra_fail,
            "after_count": after_count,
        })

    report["checks"]["encode_seed"]["encoded_ok"] = encoded_ok
    report["checks"]["encode_seed"]["encoded_fail"] = encoded_fail
    report["checks"]["encode_seed"]["ok"] = encoded_fail == 0
    report["checks"]["encode_seed"]["adaptive_rounds"] = adaptive_rounds
    report["checks"]["archive_search_after"] = {
        "count": after_count,
        "response": after_resp,
    }

    ok_stats_post, stats_post, err_stats_post = _request_json("GET", f"{base_url}/api/memory/stats")
    report["checks"]["memory_stats_post"] = {"ok": ok_stats_post, "error": err_stats_post}
    if ok_stats_post:
        post_stats = stats_post.get("stats") or {}
        report["checks"]["memory_stats_post"]["archive_total"] = (post_stats.get("archive") or {}).get("total_archived")
        report["checks"]["memory_stats_post"]["slow_events_archived"] = (post_stats.get("slow_network") or {}).get("events_archived")

    report["overall_ok"] = (
        report["checks"]["encode_seed"]["ok"]
        and after_count > 0
        and report["checks"]["memory_stats_post"]["ok"]
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive retrieval probe")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--seed-events", type=int, default=42)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = run_probe(args.base_url.rstrip("/"), seed_events=args.seed_events)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or f"tmp/archive_retrieval_probe_{ts}.json"
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(output_path)
    print(json.dumps({
        "overall_ok": report.get("overall_ok"),
        "marker": report.get("marker"),
        "before_count": report["checks"]["archive_search_before"]["count"],
        "after_count": report["checks"]["archive_search_after"]["count"],
        "encoded_ok": report["checks"]["encode_seed"]["encoded_ok"],
        "encoded_fail": report["checks"]["encode_seed"]["encoded_fail"],
    }, indent=2))

    return 0 if report.get("overall_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

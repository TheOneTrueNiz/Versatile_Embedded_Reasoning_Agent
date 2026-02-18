#!/usr/bin/env python3
"""
Doctor/Professor native memory probe.

Validates that native memory tools are discoverable and usable end-to-end:
- retrieve_memory
- search_archive
- encode_event
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
    timeout: float = 20.0,
) -> Tuple[bool, Dict[str, Any], str]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return True, json.loads(body), ""
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return False, {}, f"HTTP {exc.code}: {body}"
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


def _contains_marker(results: list[Dict[str, Any]], marker: str) -> bool:
    for item in results:
        content = str(item.get("content") or "")
        if marker in content:
            return True
    return False


def run_probe(base_url: str) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    marker = f"doctor_professor_native_memory_marker_{ts}"
    report: Dict[str, Any] = {
        "timestamp_utc": ts,
        "base_url": base_url,
        "marker": marker,
        "checks": {},
    }

    readiness = _wait_ready(base_url)
    report["readiness"] = readiness

    ok, tools_list, err = _request_json("GET", f"{base_url}/api/tools/list")
    report["checks"]["tools_list"] = {
        "ok": ok,
        "error": err,
        "has_native_tools": bool(ok and "native_tools" in tools_list),
    }

    ok_defs, tools_defs, err_defs = _request_json("GET", f"{base_url}/api/tools/defs")
    report["checks"]["tools_defs"] = {
        "ok": ok_defs,
        "error": err_defs,
        "has_native_tools": bool(ok_defs and "native_tools" in tools_defs),
    }

    native_names = set(tools_list.get("native_tools", [])) if ok else set()
    native_def_names = {
        tool.get("function", {}).get("name")
        for tool in tools_defs.get("native_tools", [])
        if isinstance(tool, dict)
    } if ok_defs else set()
    expected = {"retrieve_memory", "search_archive", "encode_event"}
    report["checks"]["native_presence"] = {
        "in_list": sorted(expected.intersection(native_names)),
        "missing_from_list": sorted(expected.difference(native_names)),
        "in_defs": sorted(expected.intersection(native_def_names)),
        "missing_from_defs": sorted(expected.difference(native_def_names)),
    }

    doctor_encode_payload = {
        "name": "encode_event",
        "arguments": {
            "content": (
                f"[Doctor] Persist marker for professor recall: {marker}. "
                "User wants explicit native memory tooling validated."
            ),
            "type": "system_event",
            "tags": ["doctor", "professor", "native-memory-probe"],
            "provenance": {"source_type": "system", "source_id": "dr_codex_probe"},
        },
    }
    ok_encode, encode_resp, err_encode = _request_json(
        "POST",
        f"{base_url}/api/tools/call",
        payload=doctor_encode_payload,
    )
    report["checks"]["doctor_encode_event"] = {
        "ok": ok_encode,
        "error": err_encode,
        "response": encode_resp,
    }

    doctor_retrieve_payload = {
        "name": "retrieve_memory",
        "arguments": {"query": marker, "max_results": 5},
    }
    ok_retrieve, retrieve_resp, err_retrieve = _request_json(
        "POST",
        f"{base_url}/api/tools/call",
        payload=doctor_retrieve_payload,
    )
    retrieve_results = ((retrieve_resp.get("result") or {}).get("results") or []) if ok_retrieve else []
    report["checks"]["doctor_retrieve_memory"] = {
        "ok": ok_retrieve,
        "error": err_retrieve,
        "type": retrieve_resp.get("type") if ok_retrieve else None,
        "count": (retrieve_resp.get("result") or {}).get("count") if ok_retrieve else 0,
        "marker_found": _contains_marker(retrieve_results, marker),
    }

    search_archive_payload = {
        "name": "search_archive",
        "arguments": {"query": marker, "max_results": 5, "tiers": ["Recent", "Weekly", "Monthly"]},
    }
    ok_archive, archive_resp, err_archive = _request_json(
        "POST",
        f"{base_url}/api/tools/call",
        payload=search_archive_payload,
    )
    archive_results = ((archive_resp.get("result") or {}).get("results") or []) if ok_archive else []
    report["checks"]["doctor_search_archive"] = {
        "ok": ok_archive,
        "error": err_archive,
        "type": archive_resp.get("type") if ok_archive else None,
        "count": (archive_resp.get("result") or {}).get("count") if ok_archive else 0,
        "marker_found": _contains_marker(archive_results, marker),
    }

    professor_retrieve_payload = {
        "name": "retrieve_memory",
        "arguments": {"query": marker, "max_results": 5},
    }
    ok_prof, prof_resp, err_prof = _request_json(
        "POST",
        f"{base_url}/api/tools/call",
        payload=professor_retrieve_payload,
    )
    prof_results = ((prof_resp.get("result") or {}).get("results") or []) if ok_prof else []
    report["checks"]["professor_retrieve_memory"] = {
        "ok": ok_prof,
        "error": err_prof,
        "type": prof_resp.get("type") if ok_prof else None,
        "count": (prof_resp.get("result") or {}).get("count") if ok_prof else 0,
        "marker_found": _contains_marker(prof_results, marker),
    }

    report["overall_ok"] = all([
        report["checks"]["tools_list"]["ok"],
        report["checks"]["tools_defs"]["ok"],
        not report["checks"]["native_presence"]["missing_from_list"],
        not report["checks"]["native_presence"]["missing_from_defs"],
        ok_encode and (encode_resp.get("type") == "native"),
        ok_retrieve and (retrieve_resp.get("type") == "native") and report["checks"]["doctor_retrieve_memory"]["marker_found"],
        ok_prof and (prof_resp.get("type") == "native") and report["checks"]["professor_retrieve_memory"]["marker_found"],
    ])

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Doctor/Professor native memory probe")
    parser.add_argument("--base-url", default="http://127.0.0.1:8788")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    report = run_probe(args.base_url.rstrip("/"))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or f"tmp/doctor_professor_native_memory_probe_{ts}.json"
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(output_path)
    print(json.dumps({
        "overall_ok": report.get("overall_ok"),
        "marker": report.get("marker"),
        "doctor_retrieve_count": report["checks"]["doctor_retrieve_memory"]["count"],
        "archive_count": report["checks"]["doctor_search_archive"]["count"],
        "professor_retrieve_count": report["checks"]["professor_retrieve_memory"]["count"],
    }, indent=2))

    return 0 if report.get("overall_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""
Memvid SDK Sidecar Worker
=========================

Simple JSON line protocol for put/find/seal.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _send(response: dict) -> None:
    sys.stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def main() -> int:
    try:
        from memvid_sdk import create, use
    except Exception as exc:
        _send({"id": None, "error": f"memvid_sdk import failed: {exc}"})
        return 1

    mem_path = Path(os.getenv("MEMVID_PATH", "vera_memory/memvid.mv2"))
    mem_kind = os.getenv("MEMVID_KIND", "basic") or "basic"

    try:
        mem_path.parent.mkdir(parents=True, exist_ok=True)
        if mem_path.exists():
            mem = use(mem_kind, str(mem_path))
        else:
            mem = create(str(mem_path))
    except Exception as exc:
        _send({"id": None, "error": f"memvid init failed: {exc}"})
        return 1

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _send({"id": None, "error": "invalid json"})
            continue

        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        try:
            if method == "ping":
                result = "pong"
            elif method == "put":
                result = mem.put(
                    title=params.get("title"),
                    label=params.get("label"),
                    metadata=params.get("metadata") or {},
                    text=params.get("text") or "",
                    tags=params.get("tags") or [],
                )
            elif method == "find":
                result = mem.find(
                    query=params.get("query") or "",
                    k=int(params.get("k", 5)),
                    mode=params.get("mode", "auto"),
                )
            elif method == "seal":
                mem.seal()
                result = True
            else:
                raise ValueError(f"unknown method: {method}")

            _send({"id": req_id, "result": result})
        except Exception as exc:
            _send({"id": req_id, "error": str(exc)})

    try:
        mem.seal()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

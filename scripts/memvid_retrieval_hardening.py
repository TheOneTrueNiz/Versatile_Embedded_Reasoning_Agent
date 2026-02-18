#!/usr/bin/env python3
"""
Memvid retrieval hardening benchmark.

Exercises VERAMemoryService under retrieval load and reports:
- latency distribution
- relevance hit rate
- memvid hit count
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow direct imports from src/
ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.runtime.config import VERAConfig
from core.services.memory_service import VERAMemoryService


@dataclass
class QueryResult:
    latency_ms: float
    hit: bool
    result_count: int


def _extract_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if "content" in item:
            return str(item.get("content") or "")
        if "text" in item:
            return str(item.get("text") or "")
        return str(item)
    if hasattr(item, "get_content"):
        try:
            return str(item.get_content())
        except Exception:
            return str(item)
    if hasattr(item, "content"):
        try:
            return str(getattr(item, "content"))
        except Exception:
            return str(item)
    return str(item)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return values[0]
    if p >= 100:
        return values[-1]
    rank = (len(values) - 1) * (p / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return values[low]
    weight = rank - low
    return values[low] * (1.0 - weight) + values[high] * weight


def _alpha_token(index: int, width: int = 8) -> str:
    """
    Convert an integer to a deterministic alphabetic token (letters only).
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    value = max(0, int(index))
    chars: List[str] = []
    while value:
        value, remainder = divmod(value, 26)
        chars.append(alphabet[remainder])
    if not chars:
        chars.append("a")
    token = "".join(reversed(chars))
    return f"sig{token.rjust(width, 'a')}"


def _build_event(idx: int, topic_count: int) -> Dict[str, Any]:
    marker = _alpha_token(idx)
    topic = idx % max(1, topic_count)
    subsystem = ["memory", "agent", "voice", "sms", "scheduler", "retrieval"][idx % 6]
    severity = ["info", "notice", "warning", "critical"][idx % 4]
    text = (
        f"Event {idx} for topic-{topic} in {subsystem}. "
        f"Unique marker {marker}. "
        f"Severity {severity}. "
        f"Action: capture retrieval quality for memvid hardening."
    )
    return {
        "type": "user_query",
        "content": text,
        "tags": [f"topic-{topic}", subsystem, severity, marker],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provenance": {"source_type": "system", "source_id": "memvid_hardening"},
    }


async def _run_queries(
    memory: VERAMemoryService,
    queries: List[Tuple[str, str]],
    max_results: int,
    concurrency: int,
) -> List[QueryResult]:
    results: List[Optional[QueryResult]] = [None] * len(queries)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _worker(index: int, query: str, expected_anchor: str) -> None:
        expected = expected_anchor.lower()
        async with semaphore:
            started = time.perf_counter()
            items = await memory.retrieve(query=query, max_results=max_results)
            latency_ms = (time.perf_counter() - started) * 1000.0
            texts = [_extract_text(item).lower() for item in items]
            hit = any(expected in text for text in texts)
            results[index] = QueryResult(
                latency_ms=latency_ms,
                hit=hit,
                result_count=len(items),
            )

    tasks = [
        asyncio.create_task(_worker(i, query, expected_anchor))
        for i, (query, expected_anchor) in enumerate(queries)
    ]
    await asyncio.gather(*tasks)
    return [result for result in results if result is not None]


async def _run(args: argparse.Namespace) -> Tuple[int, Dict[str, Any]]:
    seed = int(args.seed)
    rng = random.Random(seed)

    tmp_dir_obj: Optional[tempfile.TemporaryDirectory[str]] = None
    if args.workdir:
        workdir = Path(args.workdir).expanduser().resolve()
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir_obj = tempfile.TemporaryDirectory(prefix="vera_memvid_hardening_")
        workdir = Path(tmp_dir_obj.name)

    memory_dir = workdir / "vera_memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    memvid_path = workdir / "memvid_hardening.mv2"
    os.environ["VERA_MEMVID_ENABLED"] = "1"
    os.environ["VERA_MEMVID_PATH"] = str(memvid_path)
    os.environ.setdefault("VERA_MEMVID_MODE", "auto")
    os.environ.setdefault("VERA_MEMVID_KIND", "basic")

    default_sidecar = ROOT_DIR / "scripts" / "run_memvid_sdk_worker.sh"
    if "VERA_MEMVID_SIDECAR_CMD" not in os.environ and default_sidecar.exists():
        os.environ["VERA_MEMVID_SIDECAR_CMD"] = str(default_sidecar)

    config = VERAConfig()
    config.memory_dir = memory_dir
    memory = VERAMemoryService(config)

    started_at = time.perf_counter()
    ingest_count = 0
    memvid_store_count = 0
    retrieval_results: List[QueryResult] = []

    try:
        await memory.start()
        memvid_enabled = bool(memory.memvid_sdk and getattr(memory.memvid_sdk, "enabled", False))
        if not memvid_enabled and not args.allow_no_memvid:
            report = {
                "ok": False,
                "error": "Memvid adapter did not initialize (enabled=false).",
                "memvid_enabled": False,
                "workdir": str(workdir),
            }
            return 1, report

        events: List[Dict[str, Any]] = [
            _build_event(i, args.topics)
            for i in range(args.events)
        ]
        rng.shuffle(events)

        print(f"Ingesting {len(events)} synthetic events...", flush=True)
        for event in events:
            cube = await memory.process_event(event)
            if cube is None:
                continue
            ingest_count += 1
            content = _extract_text(cube.get_content())
            metadata = {
                "provenance": cube.metadata.provenance or {},
                "tags": list(cube.metadata.tags),
                "event_type": cube.metadata.event_type.value,
            }
            memory.add_memory(
                content=content,
                importance=float(cube.metadata.importance),
                metadata=metadata,
            )
            store_fn = getattr(memory, "_memvid_store_cube", None)
            if callable(store_fn):
                try:
                    store_fn(cube)
                    memvid_store_count += 1
                except Exception:
                    pass

        if memory.memvid_sdk:
            memory.memvid_sdk.seal()

        stats_before = memory.get_stats()
        retrieval_before = dict(stats_before.get("retrieval", {}))
        memvid_hits_before = int(retrieval_before.get("memvid_hits", 0))

        query_pairs: List[Tuple[str, str]] = []
        for _ in range(args.queries):
            idx = rng.randrange(max(1, args.events))
            marker = _alpha_token(idx)
            query_pairs.append((f"Recall details for marker {marker}", marker))

        warmup = min(8, len(query_pairs))
        for i in range(warmup):
            query, _ = query_pairs[i]
            await memory.retrieve(query=query, max_results=args.max_results)

        print(
            f"Running {len(query_pairs)} retrievals "
            f"(concurrency={args.concurrency}, max_results={args.max_results})...",
            flush=True,
        )
        retrieval_results = await _run_queries(
            memory=memory,
            queries=query_pairs,
            max_results=args.max_results,
            concurrency=args.concurrency,
        )

        stats_after = memory.get_stats()
        retrieval_after = dict(stats_after.get("retrieval", {}))
        memvid_hits_after = int(retrieval_after.get("memvid_hits", 0))
        memvid_hits_delta = max(0, memvid_hits_after - memvid_hits_before)

        latencies = sorted(result.latency_ms for result in retrieval_results)
        hit_rate = (
            sum(1 for result in retrieval_results if result.hit) / len(retrieval_results)
            if retrieval_results
            else 0.0
        )
        p95 = _percentile(latencies, 95.0)
        p99 = _percentile(latencies, 99.0)
        avg_ms = statistics.mean(latencies) if latencies else 0.0

        checks = {
            "relevance_hit_rate_ok": hit_rate >= args.min_relevance,
            "latency_p95_ok": p95 <= args.max_p95_ms,
            "memvid_hits_ok": memvid_hits_delta > 0 if memvid_enabled else bool(args.allow_no_memvid),
            "retrieval_count_ok": len(retrieval_results) == len(query_pairs),
        }
        passed = all(checks.values())

        report = {
            "ok": passed,
            "seed": seed,
            "workdir": str(workdir),
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
            "ingest": {
                "events_requested": args.events,
                "events_ingested": ingest_count,
                "topics": args.topics,
                "memvid_store_attempts": memvid_store_count,
            },
            "retrieval": {
                "queries_requested": len(query_pairs),
                "queries_executed": len(retrieval_results),
                "concurrency": args.concurrency,
                "max_results": args.max_results,
                "hit_rate": round(hit_rate, 4),
                "latency_ms": {
                    "avg": round(avg_ms, 3),
                    "p50": round(_percentile(latencies, 50.0), 3),
                    "p95": round(p95, 3),
                    "p99": round(p99, 3),
                    "max": round(latencies[-1], 3) if latencies else 0.0,
                },
            },
            "memvid": {
                "enabled": bool(memory.memvid_sdk and getattr(memory.memvid_sdk, "enabled", False)),
                "path": str(memvid_path),
                "mode": os.getenv("VERA_MEMVID_MODE", "auto"),
                "hits_before": memvid_hits_before,
                "hits_after": memvid_hits_after,
                "hits_delta": memvid_hits_delta,
            },
            "thresholds": {
                "min_relevance": args.min_relevance,
                "max_p95_ms": args.max_p95_ms,
            },
            "checks": checks,
            "memory_stats": stats_after,
        }

        print(
            "Results: "
            f"hit_rate={hit_rate:.2%}, p95={p95:.1f}ms, p99={p99:.1f}ms, memvid_hits={memvid_hits_delta}",
            flush=True,
        )

        return (0 if passed else 1), report
    finally:
        try:
            await memory.stop()
        except Exception:
            pass
        if tmp_dir_obj and not args.keep_workdir:
            tmp_dir_obj.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Memvid retrieval hardening benchmark")
    parser.add_argument("--events", type=int, default=240, help="Number of synthetic events to ingest")
    parser.add_argument("--queries", type=int, default=120, help="Number of retrieval queries")
    parser.add_argument("--topics", type=int, default=24, help="Distinct topic buckets in synthetic corpus")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent retrieval tasks")
    parser.add_argument("--max-results", type=int, default=6, help="max_results for retrieve()")
    parser.add_argument("--min-relevance", type=float, default=0.85, help="Minimum acceptable relevance hit rate")
    parser.add_argument("--max-p95-ms", type=float, default=700.0, help="Maximum acceptable p95 latency (ms)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--workdir", default="", help="Optional persistent working directory")
    parser.add_argument("--keep-workdir", action="store_true", help="Keep temp workdir when --workdir is not set")
    parser.add_argument("--allow-no-memvid", action="store_true", help="Do not fail if memvid is unavailable")
    parser.add_argument(
        "--output",
        default="",
        help="Write JSON report to this path (default: tmp/memvid_hardening_<ts>.json)",
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = Path(args.output) if args.output else (ROOT_DIR / "tmp" / f"memvid_hardening_{ts}.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        rc, report = asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        report = {"ok": False, "error": str(exc)}
        rc = 1

    output_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Report written to {output_path}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

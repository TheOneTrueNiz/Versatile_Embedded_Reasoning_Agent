#!/usr/bin/env python3
"""
Memvid SDK Adapter
==================

Optional bridge to the memvid-sdk for fast recall.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
import selectors
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

try:
    from memvid_sdk import create, use
    MEMVID_AVAILABLE = True
except Exception:
    MEMVID_AVAILABLE = False
    create = None  # type: ignore
    use = None  # type: ignore


class MemvidSidecarClient:
    """Subprocess-based memvid worker for isolated environments."""

    def __init__(
        self,
        cmd: Sequence[str],
        path: Path,
        kind: str,
        timeout: float = 5.0,
    ) -> None:
        self.cmd = list(cmd)
        self.path = Path(path)
        self.kind = kind
        self.timeout = timeout
        self.proc: Optional[subprocess.Popen[str]] = None
        self._lock = threading.Lock()
        self._next_id = 1

    def start(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        env = os.environ.copy()
        env["MEMVID_PATH"] = str(self.path)
        env["MEMVID_KIND"] = self.kind
        try:
            self.proc = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as exc:
            logger.warning("Memvid sidecar failed to start: %s", exc)
            self.proc = None
            return False

        try:
            pong = self.ping()
            return pong == "pong"
        except Exception:
            return False

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            self.seal()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2.0)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def _readline(self, timeout: float) -> str:
        if not self.proc or not self.proc.stdout:
            return ""
        sel = selectors.DefaultSelector()
        sel.register(self.proc.stdout, selectors.EVENT_READ)
        events = sel.select(timeout)
        sel.close()
        if not events:
            return ""
        return self.proc.stdout.readline()

    def _request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if not self.proc or not self.proc.stdin:
            raise RuntimeError("Memvid sidecar not running")
        request_id = self._next_id
        self._next_id += 1
        payload = {"id": request_id, "method": method, "params": params or {}}
        with self._lock:
            self.proc.stdin.write(json.dumps(payload) + "\n")
            self.proc.stdin.flush()
            line = self._readline(self.timeout)
        if not line:
            raise TimeoutError("Memvid sidecar timeout")
        response = json.loads(line)
        if response.get("id") != request_id:
            raise RuntimeError("Memvid sidecar response mismatch")
        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result")

    def ping(self) -> str:
        return str(self._request("ping"))

    def put(self, payload: Dict[str, Any]) -> Any:
        return self._request("put", payload)

    def find(self, payload: Dict[str, Any]) -> Any:
        return self._request("find", payload)

    def seal(self) -> None:
        self._request("seal")


class MemvidAdapter:
    """Lightweight wrapper around memvid-sdk."""

    def __init__(
        self,
        path: Path,
        enabled: bool = True,
        kind: str = "basic",
    ) -> None:
        self.path = Path(path)
        self.kind = kind
        self.enabled = bool(enabled)
        self._mem = None
        self._sidecar: Optional[MemvidSidecarClient] = None
        self._access_log: Dict[str, Dict[str, Any]] = {}
        self._access_log_path = self.path.parent / "memvid_access_log.json"
        self._load_access_log()

        if not enabled:
            logger.info("Memvid adapter disabled via configuration.")
            return

        if MEMVID_AVAILABLE:
            self._open()
            if self._mem:
                self.enabled = True
                return

        sidecar_cmd = os.getenv("VERA_MEMVID_SIDECAR_CMD", "").strip()
        if not sidecar_cmd:
            default_worker = Path.cwd() / "scripts" / "run_memvid_sdk_worker.sh"
            default_docker = Path.cwd() / "scripts" / "run_memvid_sdk_docker.sh"
            if default_worker.exists():
                sidecar_cmd = str(default_worker)
            elif default_docker.exists():
                sidecar_cmd = str(default_docker)
        if sidecar_cmd:
            cmd = sidecar_cmd.split()
            self._sidecar = MemvidSidecarClient(cmd=cmd, path=self.path, kind=self.kind)
            self.enabled = True
        else:
            self.enabled = False
            logger.warning("memvid-sdk not available; set VERA_MEMVID_SIDECAR_CMD to enable sidecar.")

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.path.exists():
                self._mem = use(self.kind, str(self.path))
            else:
                self._mem = create(str(self.path))
        except Exception as exc:
            logger.warning("Memvid adapter failed to open store: %s", exc)
            self._mem = None
            self.enabled = False

    def put(
        self,
        text: str,
        title: str,
        label: str,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        payload = {
            "title": title,
            "label": label,
            "metadata": metadata or {},
            "text": text,
            "tags": tags or [],
        }
        if self._mem:
            try:
                return self._mem.put(**payload)
            except Exception as exc:
                logger.debug("Memvid put failed: %s", exc)
                return None
        if self._sidecar:
            try:
                return self._sidecar.put(payload)
            except Exception as exc:
                logger.debug("Memvid sidecar put failed: %s", exc)
                return None
        return None

    def find(
        self,
        query: str,
        k: int = 5,
        mode: str = "auto",
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        result = None
        if self._mem:
            try:
                result = self._mem.find(query=query, k=k, mode=mode)
            except Exception as exc:
                logger.debug("Memvid find failed: %s", exc)
                result = None
        elif self._sidecar:
            try:
                result = self._sidecar.find({"query": query, "k": k, "mode": mode})
            except Exception as exc:
                logger.debug("Memvid sidecar find failed: %s", exc)
                result = None
        if not result:
            return []
        hits = []
        if isinstance(result, dict):
            h = result.get("hits")
            if isinstance(h, list):
                hits = h
        if isinstance(result, list):
            hits = result
        # Record access for decay tracking
        if hits:
            self._record_access(hits)
        return hits

    def seal(self) -> None:
        if not self.enabled:
            return
        if self._mem:
            try:
                self._mem.seal()
            except Exception as exc:
                logger.debug("Memvid seal failed: %s", exc)
        if self._sidecar:
            try:
                self._sidecar.seal()
            except Exception as exc:
                logger.debug("Memvid sidecar seal failed: %s", exc)

    def start(self) -> None:
        if self._sidecar and self.enabled:
            if self._sidecar.start():
                logger.info("Memvid sidecar started: %s", " ".join(self._sidecar.cmd))
            else:
                logger.warning("Memvid sidecar failed to start.")
                self.enabled = False

    def stop(self) -> None:
        if self._sidecar:
            self._sidecar.stop()
        self._save_access_log()

    # -----------------------------------------------------------------
    # Access tracking and Ebbinghaus decay
    # -----------------------------------------------------------------

    def _load_access_log(self) -> None:
        """Load access frequency log from disk."""
        if self._access_log_path.exists():
            try:
                with open(self._access_log_path, "r", encoding="utf-8") as f:
                    self._access_log = json.load(f)
            except Exception:
                self._access_log = {}

    def _save_access_log(self) -> None:
        """Persist access log to disk."""
        try:
            self._access_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._access_log_path, "w", encoding="utf-8") as f:
                json.dump(self._access_log, f, indent=2)
        except Exception as e:
            logger.debug("Failed to save access log: %s", e)

    def _record_access(self, hits: List[Dict[str, Any]]) -> None:
        """Record access for each hit returned from find()."""
        now = time.time()
        for hit in hits:
            # Use content hash or text prefix as key
            text = hit.get("text", hit.get("content", ""))[:100]
            key = str(hash(text))
            if key in self._access_log:
                self._access_log[key]["count"] += 1
                self._access_log[key]["last_accessed"] = now
            else:
                self._access_log[key] = {
                    "count": 1,
                    "last_accessed": now,
                    "created": now,
                    "preview": text[:60],
                }

    def compute_retention_scores(
        self, decay_lambda: float = 0.05
    ) -> Dict[str, float]:
        """Compute Ebbinghaus retention scores for tracked entries.

        Uses e^(-λt) with access frequency boost.
        Slower decay than SlowNetwork (λ=0.05 vs 0.1) since memvid is archival.

        Returns: {key: retention_score} where score is 0.0-1.0
        """
        import math
        now = time.time()
        scores = {}
        for key, info in self._access_log.items():
            hours_since_access = (now - info["last_accessed"]) / 3600
            access_boost = min(info["count"] * 0.1, 0.5)  # cap boost at 0.5
            base_retention = math.exp(-decay_lambda * hours_since_access)
            scores[key] = min(1.0, base_retention + access_boost)
        return scores

    def get_prune_candidates(self, threshold: float = 0.1) -> List[Dict[str, Any]]:
        """Get entries below retention threshold that are candidates for pruning.

        Returns list of {key, preview, retention, count, hours_since_access}
        """
        scores = self.compute_retention_scores()
        now = time.time()
        candidates = []
        for key, score in scores.items():
            if score < threshold:
                info = self._access_log.get(key, {})
                candidates.append({
                    "key": key,
                    "preview": info.get("preview", ""),
                    "retention": round(score, 3),
                    "count": info.get("count", 0),
                    "hours_since_access": round(
                        (now - info.get("last_accessed", now)) / 3600, 1
                    ),
                })
        return sorted(candidates, key=lambda x: x["retention"])

    def prune_decayed(self, threshold: float = 0.1) -> Dict[str, Any]:
        """Remove low-retention entries from access log.

        Returns stats: {pruned, remaining}
        """
        candidates = self.get_prune_candidates(threshold)
        pruned_keys = {c["key"] for c in candidates}
        before = len(self._access_log)
        for key in pruned_keys:
            self._access_log.pop(key, None)
        self._save_access_log()
        return {
            "pruned": len(pruned_keys),
            "remaining": len(self._access_log),
            "before": before,
        }

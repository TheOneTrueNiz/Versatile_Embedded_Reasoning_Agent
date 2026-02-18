#!/usr/bin/env python3
"""
Minimal MCP Memvid Server (stdio JSON-RPC)
==========================================

Wraps the memvid library to encode/search memory videos.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional


try:
    from memvid.encoder import MemvidEncoder
    from memvid.retriever import MemvidRetriever
    _memvid_ok = True
except Exception:
    _memvid_ok = False


try:
    import numpy as _np  # Optional: only used for JSON sanitation
except Exception:
    _np = None


TOOLS = [
    {
        "name": "memvid_encode_text",
        "description": (
            "Archive text into QR-code video + semantic index for long-term memory. "
            "Use for LARGE text (10KB+) that needs permanent, searchable storage — conversations, "
            "research notes, documentation dumps. NOT for quick notes (use MCP Memory) or structured "
            "facts (use MARM). Outputs .mp4 video + .json index. Encoding is slow (minutes for large text)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to encode"},
                "output_video": {"type": "string", "description": "Output video path"},
                "output_index": {"type": "string", "description": "Output index path"},
                "chunk_size": {"type": "integer", "description": "Chunk size"},
                "overlap": {"type": "integer", "description": "Chunk overlap"},
                "codec": {"type": "string", "description": "Video codec (mp4v, h264, h265)"}
            },
            "required": ["text", "output_video", "output_index"]
        }
    },
    {
        "name": "memvid_encode_file",
        "description": (
            "Archive a file (text/PDF/EPUB) into QR-code video + semantic index for long-term retrieval. "
            "Use for: archiving books, papers, manuals — anything you'll want to semantic-search later. "
            "Supports .txt, .pdf, .epub. Encoding is slow (minutes for large documents). "
            "For quick document reading, use pdf_reader tools instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Path to source file"},
                "output_video": {"type": "string", "description": "Output video path"},
                "output_index": {"type": "string", "description": "Output index path"},
                "chunk_size": {"type": "integer", "description": "Chunk size"},
                "overlap": {"type": "integer", "description": "Chunk overlap"},
                "codec": {"type": "string", "description": "Video codec (mp4v, h264, h265)"}
            },
            "required": ["file_path", "output_video", "output_index"]
        }
    },
    {
        "name": "memvid_search",
        "description": (
            "Semantic search over archived memvid content. Use for: querying previously encoded "
            "long-form archives (books, conversation logs, research). Returns top_k most relevant "
            "text chunks with similarity scores. For recent/fast memory, use MCP Memory or MARM instead. "
            "Requires video_path and index_path from a prior memvid_encode call."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "video_path": {"type": "string", "description": "Video path"},
                "index_path": {"type": "string", "description": "Index path"},
                "top_k": {"type": "integer", "description": "Top results (default 5)"}
            },
            "required": ["query", "video_path", "index_path"]
        }
    }
]


def _sanitize_for_json(value: Any) -> Any:
    if _np is not None:
        if isinstance(value, _np.generic):
            return value.item()
        if isinstance(value, _np.ndarray):
            return value.tolist()

    if isinstance(value, dict):
        return {key: _sanitize_for_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(val) for val in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _send_response(response: Dict[str, Any]) -> None:
    payload = _sanitize_for_json(response)
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _send_error(req_id: Optional[int], message: str, code: int = -32602) -> None:
    _send_response({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _encode_text(args: Dict[str, Any]) -> Any:
    if not _memvid_ok:
        raise RuntimeError(
            "memvid dependencies not installed. Run: "
            "cd mcp_server_and_tools/memvid && pip install -e . "
            "Requires: qrcode, Pillow, opencv-python, pyzbar, sentence-transformers"
        )

    encoder = MemvidEncoder()
    encoder.add_text(
        args["text"],
        chunk_size=int(args.get("chunk_size", 500)),
        overlap=int(args.get("overlap", 50))
    )
    return encoder.build_video(
        output_file=args["output_video"],
        index_file=args["output_index"],
        codec=args.get("codec", "mp4v"),
        show_progress=False
    )


def _encode_file(args: Dict[str, Any]) -> Any:
    if not _memvid_ok:
        raise RuntimeError(
            "memvid dependencies not installed. Run: "
            "cd mcp_server_and_tools/memvid && pip install -e . "
            "Requires: qrcode, Pillow, opencv-python, pyzbar, sentence-transformers"
        )

    file_path = args["file_path"]
    encoder = MemvidEncoder()
    lower = file_path.lower()
    if lower.endswith(".pdf"):
        encoder.add_pdf(
            file_path,
            chunk_size=int(args.get("chunk_size", 500)),
            overlap=int(args.get("overlap", 50))
        )
    elif lower.endswith(".epub"):
        encoder.add_epub(
            file_path,
            chunk_size=int(args.get("chunk_size", 500)),
            overlap=int(args.get("overlap", 50))
        )
    else:
        with open(file_path, "r", encoding="utf-8") as handle:
            encoder.add_text(
                handle.read(),
                chunk_size=int(args.get("chunk_size", 500)),
                overlap=int(args.get("overlap", 50))
            )

    return encoder.build_video(
        output_file=args["output_video"],
        index_file=args["output_index"],
        codec=args.get("codec", "mp4v"),
        show_progress=False
    )


def _search(args: Dict[str, Any]) -> Any:
    if not _memvid_ok:
        raise RuntimeError(
            "memvid dependencies not installed. Run: "
            "cd mcp_server_and_tools/memvid && pip install -e . "
            "Requires: qrcode, Pillow, opencv-python, pyzbar, sentence-transformers"
        )

    retriever = MemvidRetriever(args["video_path"], args["index_path"])
    top_k = int(args.get("top_k", 5))
    results = retriever.search_with_metadata(args["query"], top_k=top_k)
    return {"results": results}


def _handle_request(request: Dict[str, Any]) -> None:
    req_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return

    if method == "ping":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "pong"})
        return

    if method == "tools/list":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "memvid_encode_text":
                result = _encode_text(args)
            elif name == "memvid_encode_file":
                result = _encode_file(args)
            elif name == "memvid_search":
                result = _search(args)
            else:
                _send_error(req_id, f"Unknown tool '{name}'", code=-32601)
                return
        except Exception as exc:
            _send_error(req_id, str(exc))
            return

        _send_response({"jsonrpc": "2.0", "id": req_id, "result": result})
        return

    if method == "initialize":
        _send_response({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "serverInfo": {"name": "vera-memvid", "version": "1.0"},
                "capabilities": {"tools": {}},
            },
        })
        return

    if method == "shutdown":
        _send_response({"jsonrpc": "2.0", "id": req_id, "result": "ok"})
        sys.exit(0)

    _send_error(req_id, f"Unknown method '{method}'", code=-32601)


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle_request(request)


if __name__ == "__main__":
    main()

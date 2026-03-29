from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.runtime.vera import _cache_generated_media_urls


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"content-type": "video/mp4"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str):
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_cache_generated_media_urls_saves_files_and_manifest(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERA_GENERATED_MEDIA_DIR", str(tmp_path / "generated_media"))
    monkeypatch.setattr(
        "core.runtime.vera.httpx.AsyncClient",
        lambda **kwargs: _FakeClient([_FakeResponse(b"video-bytes")]),
    )

    result = await _cache_generated_media_urls(
        "video",
        "gentle forest stream",
        "grok-imagine-video",
        ["https://example.com/test-video.mp4"],
    )

    assert len(result["local_paths"]) == 1
    saved_path = Path(result["local_paths"][0])
    assert saved_path.exists()
    assert saved_path.read_bytes() == b"video-bytes"

    manifest_path = Path(result["manifest_path"])
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["items"][-1]["remote_url"] == "https://example.com/test-video.mp4"
    assert manifest["items"][-1]["status"] == "cached"


@pytest.mark.asyncio
async def test_cache_generated_media_urls_records_download_failures(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingResponse(_FakeResponse):
        def raise_for_status(self) -> None:
            raise RuntimeError("boom")

    monkeypatch.setenv("VERA_GENERATED_MEDIA_DIR", str(tmp_path / "generated_media"))
    monkeypatch.setattr(
        "core.runtime.vera.httpx.AsyncClient",
        lambda **kwargs: _FakeClient([_FailingResponse(b"")]),
    )

    result = await _cache_generated_media_urls(
        "image",
        "sunrise field",
        "grok-imagine-image",
        ["https://example.com/test-image.png"],
    )

    assert result["local_paths"] == []
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["items"][-1]["status"] == "download_failed"
    assert manifest["items"][-1]["remote_url"] == "https://example.com/test-image.png"

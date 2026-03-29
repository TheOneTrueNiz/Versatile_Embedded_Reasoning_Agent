"""
Tests for auth middleware helpers and rate-limit logic.

Tests the helper functions directly — no running HTTP server needed.
"""

import time
import pytest


# ── _check_rate_limit ─────────────────────────────────────────────────────

class TestCheckRateLimit:
    """Test the generic sliding-window rate limiter."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.server import _check_rate_limit
        self._check = _check_rate_limit

    def _make_app(self):
        return {}

    def test_under_threshold_allowed(self):
        app = self._make_app()
        allowed, _ = self._check(app, "test_bucket", "1.2.3.4", 5, 60)
        assert allowed is True

    def test_over_threshold_blocked(self):
        app = self._make_app()
        for _ in range(10):
            self._check(app, "test_bucket", "1.2.3.4", 10, 60)
        allowed, retry_after = self._check(app, "test_bucket", "1.2.3.4", 10, 60)
        assert allowed is False
        assert retry_after >= 1

    def test_window_expiry(self):
        app = self._make_app()
        # Fill bucket with very short window
        for _ in range(5):
            self._check(app, "test_bucket", "1.2.3.4", 5, 0.01)
        # Wait for window to expire
        time.sleep(0.02)
        allowed, _ = self._check(app, "test_bucket", "1.2.3.4", 5, 0.01)
        assert allowed is True

    def test_per_ip_isolation(self):
        app = self._make_app()
        # Exhaust limit for IP A
        for _ in range(3):
            self._check(app, "test_bucket", "10.0.0.1", 3, 60)
        blocked, _ = self._check(app, "test_bucket", "10.0.0.1", 3, 60)
        assert blocked is False
        # IP B should still be allowed
        allowed, _ = self._check(app, "test_bucket", "10.0.0.2", 3, 60)
        assert allowed is True

    def test_exact_threshold(self):
        app = self._make_app()
        for i in range(5):
            allowed, _ = self._check(app, "test_bucket", "1.2.3.4", 5, 60)
            if i < 5:
                assert allowed is True
        # The 6th should be blocked
        allowed, _ = self._check(app, "test_bucket", "1.2.3.4", 5, 60)
        assert allowed is False


# ── rate-limit bucket routing ──────────────────────────────────────────────

class TestResolveRateLimitBucket:
    """Ensure heavy/poll paths do not share the default global bucket."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.server import _resolve_rate_limit_bucket
        self._resolve = _resolve_rate_limit_bucket

    @staticmethod
    def _fake_request(path: str, method: str = "GET"):
        class FakeReq:
            pass
        req = FakeReq()
        req.path = path
        req.method = method
        return req

    def test_tools_call_uses_dedicated_bucket(self, monkeypatch):
        monkeypatch.setenv("VERA_RATE_LIMIT_TOOLS_CALL_MAX", "321")
        monkeypatch.setenv("VERA_RATE_LIMIT_TOOLS_CALL_WINDOW", "33")
        bucket, max_req, window = self._resolve(self._fake_request("/api/tools/call", method="POST"))
        assert bucket == "tools_call_rate_limit"
        assert max_req == 321
        assert window == 33.0

    def test_polling_get_uses_poll_bucket(self, monkeypatch):
        monkeypatch.setenv("VERA_RATE_LIMIT_POLL_MAX", "456")
        monkeypatch.setenv("VERA_RATE_LIMIT_POLL_WINDOW", "45")
        bucket, max_req, window = self._resolve(self._fake_request("/api/editor", method="GET"))
        assert bucket == "poll_rate_limit"
        assert max_req == 456
        assert window == 45.0

    def test_local_outbox_get_uses_poll_bucket(self, monkeypatch):
        monkeypatch.setenv("VERA_RATE_LIMIT_POLL_MAX", "456")
        monkeypatch.setenv("VERA_RATE_LIMIT_POLL_WINDOW", "45")
        bucket, max_req, window = self._resolve(self._fake_request("/api/channels/local/outbox", method="GET"))
        assert bucket == "poll_rate_limit"
        assert max_req == 456
        assert window == 45.0

    def test_non_poll_post_uses_global_bucket(self, monkeypatch):
        monkeypatch.setenv("VERA_RATE_LIMIT_MAX", "77")
        monkeypatch.setenv("VERA_RATE_LIMIT_WINDOW", "70")
        bucket, max_req, window = self._resolve(self._fake_request("/v1/chat/completions", method="POST"))
        assert bucket == "global_rate_limit"
        assert max_req == 77
        assert window == 70.0


# ── Auth skip-path logic ──────────────────────────────────────────────────

class TestAuthSkipPaths:
    """Test the auth middleware skip-path constants."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.server import _AUTH_SKIP_PREFIXES, _AUTH_SKIP_EXACT
        self.prefixes = _AUTH_SKIP_PREFIXES
        self.exact = _AUTH_SKIP_EXACT

    def test_health_is_skipped(self):
        assert any("/api/health".startswith(p) for p in self.prefixes)

    def test_readiness_is_skipped(self):
        assert any("/api/readiness".startswith(p) for p in self.prefixes)

    def test_ws_requires_auth(self):
        """WebSocket paths must NOT be in auth skip list (H2 fix)."""
        assert not any("/ws".startswith(p) for p in self.prefixes)

    def test_root_is_exact_skip(self):
        assert "/" in self.exact

    def test_favicon_is_exact_skip(self):
        assert "/favicon.ico" in self.exact

    def test_api_tools_not_skipped(self):
        path = "/api/tools"
        assert path not in self.exact
        assert not any(path.startswith(p) for p in self.prefixes)


# ── Auth middleware behaviour (unit-level) ────────────────────────────────

class TestAuthMiddlewareBehaviour:
    """Validate auth_middleware by calling it with fake request/handler."""

    @pytest.fixture(autouse=True)
    def _import(self):
        from api.server import auth_middleware
        self.middleware = auth_middleware

    @staticmethod
    def _fake_request(path, method="GET", headers=None, app=None):
        class FakeReq:
            pass
        r = FakeReq()
        r.path = path
        r.method = method
        r.headers = headers or {}
        r.app = app or {}
        return r

    @staticmethod
    async def _ok_handler(request):
        from aiohttp import web
        return web.Response(text="ok")

    @pytest.mark.asyncio
    async def test_auth_disabled_when_no_key(self):
        req = self._fake_request("/api/tools", app={"vera_api_key": ""})
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_valid_bearer_accepted(self):
        req = self._fake_request(
            "/api/tools",
            headers={"Authorization": "Bearer secret123"},
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_invalid_bearer_rejected(self):
        req = self._fake_request(
            "/api/tools",
            headers={"Authorization": "Bearer wrong"},
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_missing_token_rejected(self):
        req = self._fake_request(
            "/api/tools",
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 401

    @pytest.mark.asyncio
    async def test_health_skips_auth(self):
        req = self._fake_request(
            "/api/health",
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_static_assets_skip_auth(self):
        req = self._fake_request(
            "/index.html",
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_options_skips_auth(self):
        req = self._fake_request(
            "/api/tools",
            method="OPTIONS",
            app={"vera_api_key": "secret123"},
        )
        resp = await self.middleware(req, self._ok_handler)
        assert resp.status == 200

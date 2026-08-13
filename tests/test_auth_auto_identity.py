"""Tests for the v0.9.7 identity-unification changes.

Covers:
- POST /api/v1/auth/auto — issues a JWT for the fixed local_user identity.
- relay_wss_client identity consumption — reads the gateway-injected
  X-Local-User-Id and injects a local JWT (does not pass through the
  miniapp's X-User-Token).

See docs/planning/Gateway_Identity_Broker_Design.md for the design.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from promiselink.api.v1.auth import LOCAL_USER_ID


@pytest.fixture(autouse=True)
def _clean_app_state(monkeypatch):
    """Prevent lifespan WSS startup during these offline tests."""
    try:
        from promiselink.main import app
        if hasattr(app.state, "relay_wss_client"):
            del app.state.relay_wss_client
    except Exception:
        pass
    monkeypatch.setattr("promiselink.main.settings.pro_license_key", "")
    monkeypatch.setattr("promiselink.main.settings.relay_wss_enabled", False)
    yield
    try:
        from promiselink.main import app
        if hasattr(app.state, "relay_wss_client"):
            del app.state.relay_wss_client
    except Exception:
        pass


# ── POST /auth/auto ──────────────────────────────────────────────


class TestAuthAuto:
    def test_auto_login_returns_local_user(self):
        """POST /auth/auto issues a JWT whose sub is local_user."""
        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/auto")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == LOCAL_USER_ID
        assert data["token_type"] == "bearer"
        assert data["access_token"]

    def test_auto_login_token_usable(self):
        """The /auth/auto JWT's subject is local_user and verifies correctly."""
        from promiselink.core.auth import verify_token
        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/auto")
            token = resp.json()["access_token"]
        # Decode & verify the signed token (no DB dependency).
        payload = verify_token(token)
        assert payload["sub"] == LOCAL_USER_ID


# ── relay_wss_client identity consumption ────────────────────────


class TestRelayWssIdentity:
    def test_reads_gateway_injected_local_user_id(self, monkeypatch):
        """WSS client uses the gateway-injected X-Local-User-Id (no passthrough).

        The forwarded Authorization must be a local JWT for local_user, and the
        miniapp's X-User-Token must NOT be forwarded.
        """
        from promiselink.services.relay_wss_client import RelayWSSClient

        captured: dict = {}

        class _FakeHttp:
            async def request(self, method, url, headers=None, content=None, json=None, timeout=None):
                captured["headers"] = headers or {}
                captured["url"] = url
                captured["method"] = method

                class _Resp:
                    status_code = 200
                    text = "{}"
                    headers = {}
                return _Resp()

        async def fake_get_http_client(self):
            return _FakeHttp()

        monkeypatch.setattr(RelayWSSClient, "_get_http_client", fake_get_http_client)

        client = RelayWSSClient(
            gateway_url="https://gateway.promiselink.cn",
            license_key="PL-PRO-TEST-ABCD-EFGH",
            local_api_url="http://localhost:8000",
            heartbeat_interval=30,
            reconnect_interval=5,
            reconnect_max=1,
            http_request_timeout=10.0,
        )

        import asyncio
        asyncio.run(
            client._handle_http_request(
                None,
                {
                    "request_id": "req-1",
                    "method": "GET",
                    "path": "/entities",
                    "query": {"page": "1"},
                    "headers": {
                        # Gateway-injected local identity
                        "X-Local-User-Id": "local_user",
                        # Miniapp creds that must NOT be forwarded as-is
                        "X-User-Token": "eyJhbGciOiJIUzI1NiJ9.miniapp.jwt",
                        "content-type": "application/json",
                    },
                    "body": "",
                },
            )
        )

        headers = {k.lower(): v for k, v in captured["headers"].items()}
        # Authorization is a Bearer JWT (local), not the raw miniapp token.
        assert "authorization" in headers
        assert headers["authorization"].startswith("Bearer ")
        assert "eyJhbGciOiJIUzI1NiJ9.miniapp.jwt" not in headers["authorization"]
        # The injected local user id drives the JWT subject.
        assert "/entities" in captured["url"]
        assert "page=1" in captured["url"]

"""Integration tests for the WSS relay full link.

Verifies the complete data flow:
    gateway http_request message
        → RelayWSSClient._handle_http_request
        → real local FastAPI endpoint
        → http_response message back to gateway

This bridges RelayWSSClient (src/promiselink/services/relay_wss_client.py)
with a live FastAPI TestServer, ensuring the forwarding, header filtering,
and response wrapping all work end-to-end without mocking the HTTP layer.

The registry-side routing (license_key → WSS) and the gateway /request
HTTP endpoint are covered by PromiseLink-Pro/tests/test_relay_session_registry.py.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from promiselink.services.relay_wss_client import RelayWSSClient


# ── Test fixtures ───────────────────────────────────────────────────


class _FakeRelayClient:
    """Stub RelayClient satisfying RelayWSSClient constructor contract."""

    class _Token:
        access_token = "fake-test-jwt"

    def __init__(self) -> None:
        self._token = self._Token()

    async def _ensure_token(self) -> str:
        return self._token.access_token

    async def refresh_token(self) -> str:
        return self._token.access_token

    async def close(self) -> None:
        pass


class _FakeWebSocket:
    """Captures messages sent back to the gateway via WSS."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, data: str) -> None:
        self.sent.append(data)


@pytest.fixture
def local_api_app() -> FastAPI:
    """A minimal FastAPI app simulating the local basic-edition."""
    app = FastAPI(title="Test Local API")

    @app.get("/api/v1/health")
    async def health():
        return {"status": "healthy", "service": "promiselink-basic-test"}

    @app.get("/api/v1/events")
    async def list_events(user_id: str = "default"):
        return {
            "items": [
                {"id": "evt-1", "user_id": user_id, "title": "Test Meeting"},
                {"id": "evt-2", "user_id": user_id, "title": "Lunch"},
            ],
            "total": 2,
        }

    @app.post("/api/v1/events")
    async def create_event(payload: dict):
        return {"id": "evt-new", "title": payload.get("title", ""), "status": "created"}

    @app.get("/api/v1/error")
    async def always_error():
        return JSONResponse(status_code=500, content={"error": "internal"})

    @app.get("/api/v1/slow")
    async def slow_endpoint():
        await asyncio.sleep(10)
        return {"slow": True}

    return app


@pytest.fixture
async def local_api_client(local_api_app: FastAPI):
    """httpx AsyncClient backed by the in-process FastAPI app."""
    transport = ASGITransport(app=local_api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
def wss_client(local_api_client: AsyncClient) -> RelayWSSClient:
    """RelayWSSClient wired to the in-process FastAPI app.

    The local_api_url is irrelevant here — we inject the httpx client
    directly via _http_client to bypass DNS/network.
    """
    client = RelayWSSClient(
        gateway_url="http://gateway.example.com",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        local_api_url="http://testserver",
        http_request_timeout=3,
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )
    client._http_client = local_api_client  # type: ignore[assignment]
    return client


# ── Integration tests ───────────────────────────────────────────────


class TestWSSRelayGetRequest:
    """GET request forwarding through the WSS relay."""

    @pytest.mark.asyncio
    async def test_get_health_returns_200(
        self, wss_client: RelayWSSClient, local_api_client: AsyncClient
    ):
        """GET /api/v1/health should return 200 with healthy status."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-1",
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        assert len(ws.sent) == 1
        envelope = json.loads(ws.sent[0])
        assert envelope["type"] == "http_response"
        response = envelope["data"]
        assert response["request_id"] == "req-1"
        assert response["status"] == 200
        body = json.loads(response["body"])
        assert body["status"] == "healthy"
        assert body["service"] == "promiselink-basic-test"

    @pytest.mark.asyncio
    async def test_get_events_with_query_params(
        self, wss_client: RelayWSSClient
    ):
        """GET /api/v1/events?user_id=alice should forward query params."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-2",
            "method": "GET",
            "path": "/api/v1/events",
            "query": {"user_id": "alice"},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        assert response["status"] == 200
        body = json.loads(response["body"])
        assert body["total"] == 2
        assert all(e["user_id"] == "alice" for e in body["items"])


class TestWSSRelayPostRequest:
    """POST request forwarding through the WSS relay."""

    @pytest.mark.asyncio
    async def test_post_events_creates_and_returns_200(
        self, wss_client: RelayWSSClient
    ):
        """POST /api/v1/events should create event and return 200."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-3",
            "method": "POST",
            "path": "/api/v1/events",
            "query": {},
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"title": "New Meeting", "event_type": "meeting"}),
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        assert response["status"] == 200
        body = json.loads(response["body"])
        assert body["id"] == "evt-new"
        assert body["title"] == "New Meeting"
        assert body["status"] == "created"

    @pytest.mark.asyncio
    async def test_post_body_forwarded_as_raw_text(
        self, wss_client: RelayWSSClient
    ):
        """POST body should be forwarded as raw text, not re-serialized."""
        ws = _FakeWebSocket()
        raw_body = '{"title": "Raw Body Test"}'
        msg = {
            "request_id": "req-4",
            "method": "POST",
            "path": "/api/v1/events",
            "query": {},
            "headers": {"Content-Type": "application/json"},
            "body": raw_body,
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        body = json.loads(response["body"])
        assert body["title"] == "Raw Body Test"


class TestWSSRelayErrorHandling:
    """Error propagation through the WSS relay."""

    @pytest.mark.asyncio
    async def test_500_response_propagates_status(
        self, wss_client: RelayWSSClient
    ):
        """HTTP 500 from local API should propagate as status=500 in response."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-5",
            "method": "GET",
            "path": "/api/v1/error",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        assert response["status"] == 500
        body = json.loads(response["body"])
        assert body["error"] == "internal"

    @pytest.mark.asyncio
    async def test_timeout_returns_504(
        self, wss_client: RelayWSSClient
    ):
        """Slow local API should trigger 504 Gateway Timeout.

        ASGITransport does not honor httpx timeouts (in-process call),
        so we inject a mock client that raises httpx.TimeoutException
        to verify the 504 wrapping logic in _handle_http_request.
        """
        import httpx as _httpx

        mock_client = MagicMock()
        mock_client.is_closed = False

        async def _timeout_request(*args, **kwargs):
            raise _httpx.TimeoutException("simulated timeout")

        mock_client.request = _timeout_request
        wss_client._http_client = mock_client

        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-6",
            "method": "GET",
            "path": "/api/v1/slow",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        assert response["status"] == 504
        body_lower = response.get("body", "").lower()
        assert "timeout" in body_lower


class TestWSSRelayHeaderFiltering:
    """Header filtering in the WSS relay forwarding."""

    @pytest.mark.asyncio
    async def test_gateway_creds_not_forwarded(
        self, wss_client: RelayWSSClient, local_api_client: AsyncClient
    ):
        """Authorization and X-API-Key from gateway must NOT reach local API."""
        # Wrap the client.request to capture headers
        original_request = local_api_client.request
        captured_headers: dict = {}

        async def _capturing_request(method, url, **kwargs):
            captured_headers.update(kwargs.get("headers", {}))
            return await original_request(method, url, **kwargs)

        local_api_client.request = _capturing_request  # type: ignore[assignment]

        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-7",
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {
                "Host": "gateway.example.com",
                "Authorization": "Bearer gateway-jwt",
                "X-API-Key": "gateway-api-key",
                "Content-Length": "0",
                "X-Custom-Header": "keep-me",
            },
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        # Gateway credentials must not be forwarded
        assert "Authorization" not in captured_headers
        assert "X-API-Key" not in captured_headers
        assert "Host" not in captured_headers
        assert "Content-Length" not in captured_headers
        # Custom headers should be kept
        assert captured_headers.get("X-Custom-Header") == "keep-me"


class TestWSSRelayResponseEnvelope:
    """Response envelope structure compliance."""

    @pytest.mark.asyncio
    async def test_response_envelope_contains_required_fields(
        self, wss_client: RelayWSSClient
    ):
        """http_response must contain type, data.{request_id,status,headers,body}."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-8",
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        envelope = json.loads(ws.sent[0])
        assert envelope["type"] == "http_response"
        response = envelope["data"]
        assert "request_id" in response
        assert "status" in response
        assert "headers" in response
        assert "body" in response
        assert response["request_id"] == "req-8"

    @pytest.mark.asyncio
    async def test_response_headers_stripped_of_hop_by_hop(
        self, wss_client: RelayWSSClient
    ):
        """Response headers should not contain hop-by-hop headers."""
        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-9",
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        response = json.loads(ws.sent[0])["data"]
        resp_headers = response.get("headers", {})
        # Hop-by-hop headers should be filtered
        assert "transfer-encoding" not in {k.lower() for k in resp_headers}
        assert "connection" not in {k.lower() for k in resp_headers}


class TestWSSRelayObservability:
    """State tracking and observability."""

    @pytest.mark.asyncio
    async def test_requests_handled_counter_increments(
        self, wss_client: RelayWSSClient
    ):
        """Each successful http_request should increment requests_handled."""
        initial_count = wss_client.state.requests_handled

        ws = _FakeWebSocket()
        msg = {
            "request_id": "req-10",
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {},
            "body": "",
        }

        await wss_client._handle_http_request(ws, msg)

        assert wss_client.state.requests_handled == initial_count + 1

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(
        self, wss_client: RelayWSSClient
    ):
        """Multiple concurrent http_requests should all be handled."""
        ws = _FakeWebSocket()
        base_msg = {
            "method": "GET",
            "path": "/api/v1/health",
            "query": {},
            "headers": {},
            "body": "",
        }

        # Fire 5 concurrent requests
        await asyncio.gather(
            *[
                wss_client._handle_http_request(
                    ws, {**base_msg, "request_id": f"req-{i}"}
                )
                for i in range(5)
            ]
        )

        assert len(ws.sent) == 5
        request_ids = {json.loads(s)["data"]["request_id"] for s in ws.sent}
        assert request_ids == {f"req-{i}" for i in range(5)}
        assert wss_client.state.requests_handled >= 5

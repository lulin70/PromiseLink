"""Tests for promiselink.services.relay_wss_client.

Verifies the WSS long-connection client that bridges the local
basic-edition to the cloud gateway. The WSS connection allows the
mini-app to relay HTTP business requests through the gateway to this
local instance.

Coverage:
- ws_url construction (ws:// vs wss:// based on gateway scheme)
- _safe_url masks JWT in log output
- _handle_http_request forwards requests to local FastAPI and
  responds with http_response envelope
- _handle_http_request handles local API errors gracefully (502)
- _handle_http_request handles local API timeouts (504)
- State tracking (connected/disconnected/reconnect_count)
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from promiselink.services.relay_models import _TokenState
from promiselink.services.relay_wss_client import RelayWSSClient, RelayWSSState


class _FakeRelayClient:
    """Minimal RelayClient stub for WSS client tests."""

    def __init__(self, token: str = "fake-jwt-token") -> None:
        self._token = _TokenState()
        self._token.access_token = token
        self._token.expires_at = 9999999999.0  # far future
        self.closed = False

    async def _ensure_token(self) -> str:  # noqa: SLF001
        return self._token.access_token

    async def close(self) -> None:
        self.closed = True


class _FakeWebSocket:
    """Captures sent messages for assertion."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


# ── ws_url / _safe_url ────────────────────────────────────────────


def test_ws_url_uses_ws_scheme_for_http_gateway():
    client = RelayWSSClient(
        gateway_url="http://47.116.219.15:8001",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=_FakeRelayClient(token="jwt-123"),  # type: ignore[arg-type]
    )
    url = client.ws_url
    assert url.startswith("ws://")
    assert "47.116.219.15:8001" in url
    assert "token=jwt-123" in url


def test_ws_url_uses_wss_scheme_for_https_gateway():
    client = RelayWSSClient(
        gateway_url="https://gw.promiselink.cn",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=_FakeRelayClient(token="jwt-456"),  # type: ignore[arg-type]
    )
    url = client.ws_url
    assert url.startswith("wss://")
    assert "gw.promiselink.cn" in url
    assert "token=jwt-456" in url


def test_ws_url_includes_ws_path():
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )
    assert "/api/v1/pro/relay/ws" in client.ws_url


def test_safe_url_masks_jwt():
    long_token = "abcdefghijklmnopqrstuvwxyz123456"
    url = f"wss://gw/api/v1/pro/relay/ws?token={long_token}"
    masked = RelayWSSClient._safe_url(url)  # noqa: SLF001
    assert "abcdef" in masked  # first 6 chars visible
    assert "3456" in masked  # last 4 chars visible
    assert long_token not in masked  # full token NOT visible


# ── _handle_http_request ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_handle_http_request_forwards_to_local_api_and_responds():
    """Verify http_request is forwarded to local FastAPI and response is sent back."""
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        local_api_url="http://localhost:8000",
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )

    # Mock the internal httpx client to return a controlled response.
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.headers = {"Content-Type": "application/json"}
    fake_response.text = '{"items": ["event1"]}'

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=fake_response)
    mock_http_client.is_closed = False
    client._http_client = mock_http_client  # noqa: SLF001

    ws = _FakeWebSocket()
    msg_data = {
        "request_id": "req-123",
        "method": "GET",
        "path": "/api/v1/events",
        "query": {"limit": "20"},
        "headers": {"Content-Type": "application/json"},
        "body": "",
    }

    await client._handle_http_request(ws, msg_data)  # noqa: SLF001

    # Verify the request was forwarded with the right method + URL.
    mock_http_client.request.assert_called_once()
    call_kwargs = mock_http_client.request.call_args.kwargs
    assert call_kwargs["method"] == "GET"
    assert "/api/v1/events" in call_kwargs["url"]
    assert "limit=20" in call_kwargs["url"]

    # Verify the WSS response envelope.
    assert len(ws.sent) == 1
    envelope = json.loads(ws.sent[0])
    assert envelope["type"] == "http_response"
    assert envelope["data"]["request_id"] == "req-123"
    assert envelope["data"]["status"] == 200
    assert envelope["data"]["body"] == '{"items": ["event1"]}'
    assert client.state.requests_handled == 1


@pytest.mark.asyncio
async def test_handle_http_request_returns_502_on_local_api_error():
    """If local FastAPI is unreachable, return 502 with error body."""
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        local_api_url="http://localhost:8000",
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
    mock_http_client.is_closed = False
    client._http_client = mock_http_client  # noqa: SLF001

    ws = _FakeWebSocket()
    msg_data = {
        "request_id": "req-err",
        "method": "POST",
        "path": "/api/v1/events",
        "query": {},
        "headers": {},
        "body": "{}",
    }

    await client._handle_http_request(ws, msg_data)  # noqa: SLF001

    envelope = json.loads(ws.sent[0])
    assert envelope["type"] == "http_response"
    assert envelope["data"]["status"] == 502
    assert "local_api_unreachable" in envelope["data"]["body"]


@pytest.mark.asyncio
async def test_handle_http_request_returns_504_on_timeout():
    """If local FastAPI is slow, return 504."""
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        local_api_url="http://localhost:8000",
        http_request_timeout=1,
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_http_client.is_closed = False
    client._http_client = mock_http_client  # noqa: SLF001

    ws = _FakeWebSocket()
    msg_data = {
        "request_id": "req-timeout",
        "method": "GET",
        "path": "/api/v1/slow-endpoint",
        "query": {},
        "headers": {},
        "body": "",
    }

    await client._handle_http_request(ws, msg_data)  # noqa: SLF001

    envelope = json.loads(ws.sent[0])
    assert envelope["data"]["status"] == 504
    assert "local_api_timeout" in envelope["data"]["body"]


@pytest.mark.asyncio
async def test_handle_http_request_strips_hop_by_hop_headers():
    """Authorization/Host/Content-Length headers should NOT be forwarded to local API."""
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        local_api_url="http://localhost:8000",
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.headers = {}
    fake_response.text = "{}"

    mock_http_client = MagicMock()
    mock_http_client.request = AsyncMock(return_value=fake_response)
    mock_http_client.is_closed = False
    client._http_client = mock_http_client  # noqa: SLF001

    ws = _FakeWebSocket()
    msg_data = {
        "request_id": "req-1",
        "method": "POST",
        "path": "/api/v1/events",
        "query": {},
        "headers": {
            "Host": "gateway.example",
            "Content-Length": "42",
            "Authorization": "Bearer gateway-jwt",
            "X-API-Key": "gateway-key",
            "Content-Type": "application/json",  # should be kept
            "X-Custom": "custom-value",  # should be kept
        },
        "body": '{"event_type": "meeting"}',
    }

    await client._handle_http_request(ws, msg_data)  # noqa: SLF001

    forwarded_headers = mock_http_client.request.call_args.kwargs["headers"]
    assert "Host" not in forwarded_headers
    assert "Content-Length" not in forwarded_headers
    assert "Authorization" not in forwarded_headers
    assert "X-API-Key" not in forwarded_headers
    assert forwarded_headers.get("Content-Type") == "application/json"
    assert forwarded_headers.get("X-Custom") == "custom-value"


# ── start / stop lifecycle ────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_creates_background_task():
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=_FakeRelayClient(),  # type: ignore[arg-type]
    )
    # Patch _run_forever so it exits immediately after start.
    with patch.object(client, "_run_forever", new=AsyncMock()):
        await client.start()
        assert client._task is not None  # noqa: SLF001
        # Give the task a chance to run.
        await asyncio.sleep(0.05)
        # Stop to clean up.
        await client.stop()


@pytest.mark.asyncio
async def test_stop_closes_relay_client():
    fake_relay = _FakeRelayClient()
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=fake_relay,  # type: ignore[arg-type]
    )
    await client.stop()
    assert fake_relay.closed is True


# ── State tracking ────────────────────────────────────────────────


def test_state_as_dict_returns_observability_fields():
    state = RelayWSSState()
    state.connected = True
    state.reconnect_count = 3
    state.requests_handled = 42
    state.last_error = "test error"

    d = state.as_dict()
    assert d["connected"] is True
    assert d["reconnect_count"] == 3
    assert d["requests_handled"] == 42
    assert d["last_error"] == "test error"

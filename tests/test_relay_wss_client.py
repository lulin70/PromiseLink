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

from promiselink.services.relay_models import (
    RelayAuthError,
    RelayUnavailableError,
    _TokenState,
)
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


class _RejectingRelayClient(_FakeRelayClient):
    """Relay client whose license is rejected by the gateway (HTTP 403).

    ``gateway_code`` mirrors the real ``RelayAuthError.details["gateway_code"]``
    that :mod:`relay_client` now attaches (② 2026-09-21). Left as ``None`` the
    exception carries no code at all — the fallback path the WSS client must
    survive.
    """

    def __init__(
        self, attempts: list[int] | None = None, gateway_code: str | None = None
    ) -> None:
        super().__init__(token="")
        self.attempts = attempts if attempts is not None else []
        self._token.expires_at = 0.0  # force needs_refresh
        self._gateway_code = gateway_code

    async def _ensure_token(self) -> str:  # noqa: SLF001
        self.attempts.append(len(self.attempts) + 1)
        details: dict[str, Any] = {"status_code": 403}
        if self._gateway_code is not None:
            details["gateway_code"] = self._gateway_code
        raise RelayAuthError(
            message="License activation rejected (HTTP 403): LicenseExpired",
            details=details,
        )


class _UnavailableRelayClient(_FakeRelayClient):
    """Relay client whose gateway is unreachable (transient failure)."""

    def __init__(self) -> None:
        super().__init__(token="")
        self.attempts: list[int] = []
        self._token.expires_at = 0.0

    async def _ensure_token(self) -> str:  # noqa: SLF001
        self.attempts.append(len(self.attempts) + 1)
        raise RelayUnavailableError(message="Cannot reach gateway to refresh token")


class _FakeWebSocket:
    """Captures sent messages for assertion."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, payload: str) -> None:
        self.sent.append(payload)


# ── ws_url / _safe_url ────────────────────────────────────────────


def test_ws_url_uses_ws_scheme_for_http_gateway():
    client = RelayWSSClient(
        gateway_url="http://staging-gateway.example.com:8001",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        relay_client=_FakeRelayClient(token="jwt-123"),  # type: ignore[arg-type]
    )
    url = client.ws_url
    assert url.startswith("ws://")
    assert "staging-gateway.example.com:8001" in url
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
    # v0.9.7: gateway Authorization (gateway-jwt) is NOT forwarded; instead a
    # local identity JWT (sub=local_user) is injected for the local API.
    auth = forwarded_headers.get("Authorization", "")
    assert auth.startswith("Bearer ")
    assert "gateway-jwt" not in auth
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
    state.auth_failures = 2
    state.terminal_reason = "license_rejected"

    d = state.as_dict()
    assert d["connected"] is True
    assert d["reconnect_count"] == 3
    assert d["requests_handled"] == 42
    assert d["last_error"] == "test error"
    assert d["auth_failures"] == 2
    assert d["terminal_reason"] == "license_rejected"


# ── L-1: license rejection must NOT become an unbounded 403 storm ──
#
# Production symptom (nginx log, reviewed 2026-09-18): 6124 hits of
# POST /api/v1/pro/license/activate -> 403, roughly one every 30 seconds,
# from a single desktop process (UA python-httpx). Root cause: the WSS
# reconnect backoff saturates at reconnect_max (30s) while
# _ensure_token() -> refresh_token() -> _activate_license() re-POSTs
# /activate on every single reconnect, forever.


async def _drain(client: RelayWSSClient) -> None:
    """Stop the client's background task and wait for it to finish."""
    client._stop_event.set()  # noqa: SLF001
    task = client._task  # noqa: SLF001
    if task is not None:
        await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_auth_rejection_becomes_terminal_after_max_attempts():
    """403 activation rejection stops the loop after max_auth_failures attempts."""
    rejecting = _RejectingRelayClient()
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.01,
        reconnect_max=0.02,
        max_auth_failures=3,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.2)  # old code would keep firing here
    await _drain(client)

    assert len(rejecting.attempts) == 3
    assert client.state.auth_failures == 3
    assert client.state.terminal_reason == "license_rejected"
    assert client.state.connected is False
    assert "RelayAuthError" in client.state.last_error


@pytest.mark.asyncio
async def test_auth_rejection_attempt_count_is_capped_not_time_bounded():
    """Repeated 403s stop at the cap: attempts must not grow with wall time.

    This is the actual L-1 regression: with an 18ms cap the old loop produced
    ~55 attempts/second; the fix pins the total to max_auth_failures no matter
    how long the process stays alive.
    """
    rejecting = _RejectingRelayClient()
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.005,
        reconnect_max=0.01,
        max_auth_failures=4,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.1)
    first_window = len(rejecting.attempts)
    await asyncio.sleep(0.3)  # ten more windows' worth of idling
    second_window = len(rejecting.attempts)
    await _drain(client)

    assert first_window == 4
    assert second_window == 4, "403 attempts kept growing after the cap was reached"
    assert client.state.terminal_reason == "license_rejected"


@pytest.mark.asyncio
async def test_transient_gateway_errors_still_retry_beyond_the_auth_cap():
    """Network/5xx failures are NOT terminal — they keep retrying with backoff."""
    unavailable = _UnavailableRelayClient()
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.005,
        reconnect_max=0.01,
        max_auth_failures=3,
        relay_client=unavailable,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.15)
    attempts = len(unavailable.attempts)
    await _drain(client)

    assert attempts > 3, "transient failures must keep retrying, not go terminal"
    assert client.state.terminal_reason == ""
    assert client.state.auth_failures == 0
    assert "RelayUnavailableError" in client.state.last_error


@pytest.mark.asyncio
async def test_restart_clears_terminal_state_and_resumes_attempts():
    """Re-activation path: start() must clear a latched terminal state."""
    rejecting = _RejectingRelayClient()
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.005,
        reconnect_max=0.01,
        max_auth_failures=2,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.1)
    await _drain(client)
    assert client.state.terminal_reason == "license_rejected"
    first_round = len(rejecting.attempts)

    await client.start()
    await asyncio.sleep(0.1)
    await _drain(client)

    assert len(rejecting.attempts) > first_round, "restart did not resume the loop"
    assert client.state.auth_failures == 2


# ── ②（2026-09-21）: 网关原因码必须随终态一起暴露给配对页 ──
#
# 背景：配对页要区分「许可证无效 / 已被占用 / 不存在」三类文案，而
# RelayAuthError 里唯一的机器可读线索是 details["gateway_code"]。
# 若 WSS 客户端不把它取出来，配对页只能一律回退到"许可证无效"。
#
# 反向探针：下面第一条用例给的 gateway_code 是 LICENSE_NOT_FOUND。若有人把
# 传播逻辑删掉（terminal_code 恒为 ""），用例必然变红 —— 不可能静默通过。


def test_state_as_dict_exposes_terminal_code():
    """terminal_code 必须进入可观测快照（/health 与配对页都读它）。"""
    state = RelayWSSState()
    assert state.terminal_code == ""
    state.terminal_reason = "license_rejected"
    state.terminal_code = "DEVICE_LIMIT_EXCEEDED"
    d = state.as_dict()
    assert d["terminal_code"] == "DEVICE_LIMIT_EXCEEDED"
    assert d["terminal_reason"] == "license_rejected"


@pytest.mark.asyncio
async def test_terminal_code_is_propagated_from_gateway_code():
    """终态被拒时必须把网关原因码取出，而不是只留一句 "被拒"。"""
    rejecting = _RejectingRelayClient(gateway_code="LICENSE_NOT_FOUND")
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.01,
        reconnect_max=0.02,
        max_auth_failures=2,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.15)
    await _drain(client)

    assert client.state.terminal_reason == "license_rejected"
    assert client.state.terminal_code == "LICENSE_NOT_FOUND"


@pytest.mark.asyncio
async def test_terminal_code_is_empty_when_gateway_omits_it():
    """兜底：details 里没有 gateway_code 时必须是空串（不是 "None"）。

    旧版网关、或者异常在更早的层被包装时都可能没有这个键；此时配对页按
    "许可证无效"兜底，但绝不能拿到字符串 "None" —— 那会命中不了任何映射
    而静默显示错文案。
    """
    rejecting = _RejectingRelayClient()  # 不带 gateway_code
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.01,
        reconnect_max=0.02,
        max_auth_failures=2,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.15)
    await _drain(client)

    assert client.state.terminal_reason == "license_rejected"
    assert client.state.terminal_code == ""


@pytest.mark.asyncio
async def test_restart_clears_terminal_code():
    """重新激活后原因码必须清空，否则新一次配对会读到上一次的旧原因。"""
    rejecting = _RejectingRelayClient(gateway_code="LICENSE_EXPIRED")
    client = RelayWSSClient(
        gateway_url="http://gateway.example",
        license_key="PL-PRO-aaaa-bbbb-cccc",
        reconnect_interval=0.005,
        reconnect_max=0.01,
        max_auth_failures=1,
        relay_client=rejecting,  # type: ignore[arg-type]
    )

    await client.start()
    await asyncio.sleep(0.1)
    await _drain(client)
    assert client.state.terminal_code == "LICENSE_EXPIRED"

    # Second start: the stale code must not survive into the new session.
    # `_connect_and_serve` is stubbed so the assertion stays offline and
    # deterministic (no DNS/WS attempt against gateway.example).
    with patch.object(client, "_connect_and_serve", new=AsyncMock()):
        await client.start()
        assert client.state.terminal_code == ""
        assert client.state.terminal_reason == ""
        await _drain(client)

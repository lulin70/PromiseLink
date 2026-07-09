"""WebSocket long-connection client for the Pro edition gateway relay.

Bridges the local basic-edition Docker to the cloud AI gateway via a
persistent WSS connection. The gateway uses this connection to route
HTTP business requests from the mini-app (received via
``/api/v1/pro/relay/request``) back to the user's local FastAPI
instance, so the mini-app can transparently access local data without
the user's computer needing a public IP or port forwarding.

Design goals (WSS中继与网关HTTP代理实现计划.md §3 Phase A1):

* **PC-initiated outbound WSS** — the local basic-edition actively
  dials out to the gateway, so no public IP or port mapping is needed
  on the user's computer (§2.3 principle 2).
* **Heartbeat + exponential backoff reconnect** — 30s ping/pong;
  reconnect on disconnect with 1s→2s→...→30s backoff.
* **JWT auto-refresh** — uses the embedded :class:`RelayClient` for
  license activation and token refresh; the WSS connection is rebuilt
  with the fresh JWT after each reconnect.
* **HTTP request forwarding** — listens for ``http_request`` messages
  from the gateway and forwards them to the local FastAPI
  (``localhost:8000`` by default), returning ``http_response``.

Lifecycle:
- Instantiated in :mod:`promiselink.main` lifespan when
  ``settings.relay_wss_enabled`` and license key are configured.
- Started as a background ``asyncio.Task``; stopped on shutdown.

Reference: Pro_Edition_Architecture.md §2.1 L3 layer
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from promiselink.services.relay_client import RelayClient
from promiselink.services.relay_models import _RELAY_PREFIX

logger = logging.getLogger("promiselink.relay_wss")

__all__ = [
    "RelayWSSClient",
    "RelayWSSState",
]


class RelayWSSState:
    """Snapshot of the WSS client state for observability."""

    def __init__(self) -> None:
        self.connected: bool = False
        self.last_connected_at: float = 0.0
        self.last_disconnect_at: float = 0.0
        self.reconnect_count: int = 0
        self.requests_handled: int = 0
        self.last_error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "last_connected_at": self.last_connected_at,
            "last_disconnect_at": self.last_disconnect_at,
            "reconnect_count": self.reconnect_count,
            "requests_handled": self.requests_handled,
            "last_error": self.last_error,
        }


class RelayWSSClient:
    """Persistent WSS client bridging local FastAPI to the cloud gateway.

    Args:
        gateway_url: Gateway base URL, e.g. ``https://gateway.promiselink.cn``
            or ``http://staging-gateway:8001``. The scheme is rewritten
            to ``ws://`` or ``wss://`` automatically.
        license_key: Pro license key (``PL-PRO-xxxx-xxxx-xxxx``).
        local_api_url: Local FastAPI base URL for forwarding
            ``http_request`` messages, e.g. ``http://localhost:8000``.
        heartbeat_interval: Seconds between ping messages (default 30).
        reconnect_interval: Initial reconnect backoff in seconds (default 1).
        reconnect_max: Max reconnect backoff in seconds (default 30).
        http_request_timeout: Timeout for forwarding a single HTTP
            request to the local FastAPI (default 30).
        relay_client: Optional pre-configured :class:`RelayClient` for
            JWT management. If omitted, one is created internally.
    """

    def __init__(
        self,
        gateway_url: str,
        license_key: str,
        local_api_url: str = "http://localhost:8000",
        *,
        heartbeat_interval: int = 30,
        reconnect_interval: int = 1,
        reconnect_max: int = 30,
        http_request_timeout: int = 30,
        relay_client: RelayClient | None = None,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.license_key = license_key.strip()
        self.local_api_url = local_api_url.rstrip("/")
        self.heartbeat_interval = heartbeat_interval
        self.reconnect_interval = reconnect_interval
        self.reconnect_max = reconnect_max
        self.http_request_timeout = http_request_timeout

        self._relay_client = relay_client or RelayClient(
            gateway_url=self.gateway_url,
            license_key=self.license_key,
        )
        self._http_client: httpx.AsyncClient | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._ws: Any = None
        self.state = RelayWSSState()

    @property
    def ws_url(self) -> str:
        """Build the WSS URL with the current JWT as a query parameter."""
        token = self._relay_client._token.access_token  # noqa: SLF001
        scheme = "wss" if self.gateway_url.startswith("https") else "ws"
        host = self.gateway_url.split("://", 1)[-1]
        return f"{scheme}://{host}{_RELAY_PREFIX}/ws?token={token}"

    async def start(self) -> None:
        """Start the WSS background task. Returns immediately.

        The task runs forever (connect → heartbeat → handle messages →
        reconnect on failure) until :meth:`stop` is called.
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_forever(), name="relay_wss")
        logger.info(
            "relay_wss_start_scheduled: gateway=%s local=%s",
            self.gateway_url,
            self.local_api_url,
        )

    async def stop(self) -> None:
        """Signal the background task to stop and wait for it to drain."""
        self._stop_event.set()
        # Close the active WSS so any pending recv() returns immediately.
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client and relay client."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        await self._relay_client.close()

    # ── Main loop ──────────────────────────────────────────────────

    async def _run_forever(self) -> None:
        """Outer reconnect loop with exponential backoff."""
        backoff = self.reconnect_interval
        while not self._stop_event.is_set():
            try:
                await self._connect_and_serve()
                # If we exited cleanly without stop signal, treat as
                # disconnect and reconnect with backoff.
                backoff = self.reconnect_interval
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.state.last_error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning(
                    "relay_wss_session_ended: error=%s backoff=%ss",
                    self.state.last_error,
                    backoff,
                )

            self.state.connected = False
            self.state.last_disconnect_at = time.time()

            if self._stop_event.is_set():
                break

            self.state.reconnect_count += 1
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=backoff
                )
                break  # stop_event set during sleep
            except TimeoutError:
                pass
            backoff = min(backoff * 2, self.reconnect_max)

    async def _connect_and_serve(self) -> None:
        """Connect to the gateway, register, and serve until disconnect."""
        # 1. Ensure we have a valid JWT (refresh if needed).
        await self._relay_client._ensure_token()  # noqa: SLF001

        # 2. Open WSS connection.
        url = self.ws_url
        logger.info("relay_wss_connecting: url=%s", self._safe_url(url))
        try:
            async with websockets.connect(
                url,
                ping_interval=None,  # we send our own ping
                ping_timeout=None,
                close_timeout=5,
                max_size=10 * 1024 * 1024,  # 10MB for large OCR payloads
                open_timeout=10,
            ) as ws:
                self._ws = ws
                self.state.connected = True
                self.state.last_connected_at = time.time()
                self.state.last_error = ""
                logger.info(
                    "relay_wss_connected: license_key=%s",
                    self.license_key[:8] + "...",
                )

                # 3. Wait for the "connected" ack from the gateway.
                ack = await asyncio.wait_for(ws.recv(), timeout=10)
                ack_msg = json.loads(ack)
                if ack_msg.get("type") != "connected":
                    raise RuntimeError(
                        f"Expected 'connected' ack, got: {ack_msg.get('type')}"
                    )

                # 4. Run heartbeat + message handler concurrently.
                heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(ws), name="relay_wss_heartbeat"
                )
                try:
                    await self._message_loop(ws)
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except (asyncio.CancelledError, Exception):
                        pass
        finally:
            self._ws = None

    async def _heartbeat_loop(self, ws: Any) -> None:
        """Send periodic ping messages to keep the connection alive."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self.heartbeat_interval)
                await ws.send(json.dumps({"type": "ping"}))
                logger.debug("relay_wss_ping_sent")
            except asyncio.CancelledError:
                raise
            except (ConnectionClosed, Exception) as exc:
                logger.warning("relay_wss_heartbeat_failed: %s", exc)
                # Trigger reconnect by closing the socket from this side.
                try:
                    await ws.close()
                except Exception:
                    pass
                return

    async def _message_loop(self, ws: Any) -> None:
        """Receive messages and dispatch by type until disconnect."""
        async for raw in ws:
            if self._stop_event.is_set():
                break
            try:
                msg = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                logger.warning("relay_wss_invalid_json: %s", str(raw)[:200])
                continue

            msg_type = msg.get("type", "")
            msg_data = msg.get("data", {})

            if msg_type == "pong":
                continue
            if msg_type == "http_request":
                # Handle in a fire-and-forget task so the receive loop
                # is not blocked by slow local FastAPI calls.
                asyncio.create_task(
                    self._handle_http_request(ws, msg_data),
                    name="relay_wss_http_req",
                )
                continue
            if msg_type == "error":
                logger.warning(
                    "relay_wss_gateway_error: code=%s message=%s",
                    msg_data.get("code"),
                    msg_data.get("message"),
                )
                continue

            logger.debug("relay_wss_unhandled_message: type=%s", msg_type)

    # ── HTTP request forwarding ────────────────────────────────────

    async def _handle_http_request(self, ws: Any, msg_data: dict[str, Any]) -> None:
        """Forward a single http_request to the local FastAPI and respond."""
        request_id = msg_data.get("request_id", "")
        method = msg_data.get("method", "GET").upper()
        path = msg_data.get("path", "")
        query = msg_data.get("query", {}) or {}
        headers = msg_data.get("headers", {}) or {}
        body = msg_data.get("body")

        # Strip hop-by-hop headers that should not be forwarded.
        # Also drop Content-Length — httpx will recompute it.
        # Drop Authorization and X-API-Key — these are gateway creds
        # (relay JWT + gateway API key), not for the local FastAPI which
        # has its own auth (or none in localhost mode).
        forwarded_headers = {
            k: v
            for k, v in headers.items()
            if k.lower() not in {
                "host", "content-length", "connection", "transfer-encoding",
                "authorization", "x-api-key",
            }
        }

        url = f"{self.local_api_url}{path}"
        if query:
            # query is a dict[str, str] from the gateway
            url += "?" + "&".join(f"{k}={v}" for k, v in query.items() if k != "path")

        response_envelope: dict[str, Any] = {"request_id": request_id}
        try:
            client = await self._get_http_client()
            response = await client.request(
                method=method,
                url=url,
                headers=forwarded_headers,
                content=body if isinstance(body, (str, bytes)) else None,
                json=body if isinstance(body, (dict, list)) else None,
                timeout=httpx.Timeout(self.http_request_timeout, connect=5.0),
            )
            response_envelope["status"] = response.status_code
            response_envelope["headers"] = dict(response.headers)
            response_envelope["body"] = response.text
            self.state.requests_handled += 1
            logger.debug(
                "relay_wss_http_forwarded: method=%s path=%s status=%s",
                method,
                path,
                response.status_code,
            )
        except httpx.TimeoutException:
            response_envelope["status"] = 504
            response_envelope["headers"] = {"Content-Type": "application/json"}
            response_envelope["body"] = json.dumps(
                {"error": "local_api_timeout", "message": "Local FastAPI did not respond in time"}
            )
            logger.warning("relay_wss_http_timeout: method=%s path=%s", method, path)
        except Exception as exc:
            response_envelope["status"] = 502
            response_envelope["headers"] = {"Content-Type": "application/json"}
            response_envelope["body"] = json.dumps(
                {"error": "local_api_unreachable", "message": str(exc)[:200]}
            )
            logger.warning(
                "relay_wss_http_error: method=%s path=%s error=%s",
                method,
                path,
                str(exc)[:200],
            )

        # Send the response back to the gateway.
        try:
            await ws.send(json.dumps({"type": "http_response", "data": response_envelope}))
        except (ConnectionClosed, Exception) as exc:
            logger.warning("relay_wss_response_send_failed: request_id=%s err=%s", request_id, exc)

    async def _get_http_client(self) -> httpx.AsyncClient:
        """Lazily create the shared httpx client for local forwarding."""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.http_request_timeout, connect=5.0),
            )
        return self._http_client

    @staticmethod
    def _safe_url(url: str) -> str:
        """Mask the JWT in log output."""
        if "token=" in url:
            base, _, token = url.partition("token=")
            if len(token) > 12:
                return f"{base}token={token[:6]}...{token[-4:]}"
        return url

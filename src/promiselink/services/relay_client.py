"""Cloud gateway relay client for PromiseLink Pro edition.

This module provides ``RelayClient`` — an async HTTP client that bridges
the local PromiseLink app to the cloud AI gateway. It supports four
relay channels (LLM / ASR / TTS / OCR) and implements the
:class:`promiselink.services.llm_provider.LLMProvider` Protocol so it
can transparently replace the local ``LLMClient`` when ``ai_mode=relay``.

Design goals (Pro Edition Tech Design Phase0 §4.3.4-§4.3.7, §8):

* **HTTP-only** — uses ``httpx.AsyncClient`` for simplicity (no WebSocket).
* **License-key auth** — activates the license to obtain a relay JWT,
  then refreshes it automatically before expiry or on 401.
* **Graceful degradation** — gateway errors are raised as
  :class:`RelayError` with clear codes; the caller decides whether to
  fall back to a local provider.
* **Protocol compatible** — implements ``call`` / ``call_json`` /
  ``generate`` / ``close`` so it can be injected anywhere an
  ``LLMProvider`` is expected.

The endpoint methods (LLM/ASR/TTS/OCR + HTTP helpers) live in
:mod:`relay_endpoints` (``RelayEndpointsMixin``); constants and
exceptions live in :mod:`relay_models`.

License: GNU AGPL v3 — see LICENSE file for details.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from promiselink.core.logging import get_logger
from promiselink.services.relay_endpoints import RelayEndpointsMixin
from promiselink.services.relay_models import (
    _DEFAULT_ASR_MODEL,
    _DEFAULT_LLM_MODEL,
    _DEFAULT_OCR_MODEL,
    _DEFAULT_TTS_MODEL,
    _HEALTH_PATH,
    _LICENSE_PREFIX,
    _RELAY_PREFIX,
    _TOKEN_REFRESH_MARGIN,
    RelayAuthError,
    RelayError,
    RelayUnavailableError,
    _TokenState,
    safe_error_detail,
)

logger = get_logger("promiselink.relay_client")

__all__ = [
    "RelayClient",
    "RelayError",
    "RelayAuthError",
    "RelayUnavailableError",
    "create_relay_client_from_settings",
    "get_shared_relay_client",
    "close_relay_client",
    # Re-exported constants for backward compatibility
    "_RELAY_PREFIX",
    "_LICENSE_PREFIX",
    "_HEALTH_PATH",
    "_DEFAULT_LLM_MODEL",
    "_DEFAULT_ASR_MODEL",
    "_DEFAULT_TTS_MODEL",
    "_DEFAULT_OCR_MODEL",
    "_TOKEN_REFRESH_MARGIN",
    "_TokenState",
]


class RelayClient(RelayEndpointsMixin):
    """Cloud gateway relay client for Pro edition.

    Bridges local PromiseLink to the cloud AI gateway via HTTP. Supports
    LLM chat completion, ASR, TTS, and OCR relay channels with automatic
    JWT refresh and graceful degradation.

    Usage::

        client = RelayClient(
            gateway_url="https://gateway.promiselink.cn",
            license_key="PL-PRO-XXXX-XXXX-XXXX",
        )
        # LLM call (LLMProvider protocol)
        text = await client.call("Extract entities from: ...")
        # Or direct chat completion
        result = await client.chat_completion(messages=[...], model="...")
        await client.close()

    Args:
        gateway_url: Gateway base URL (e.g. ``https://gateway.promiselink.cn``).
        license_key: Pro license key in ``PL-PRO-xxxx-xxxx-xxxx`` format.
        user_token: Optional pre-issued relay JWT (skips activation).
        api_key: Optional X-API-Key value. Defaults to ``license_key``
            for the simplified basic-Pro flow.
        timeout: HTTP request timeout in seconds.
        max_retries: Max retry attempts for transient errors.
        device_fingerprint: Optional device fingerprint. If omitted, a
            deterministic one is derived from the license key.
    """

    def __init__(
        self,
        gateway_url: str,
        license_key: str,
        *,
        user_token: str = "",
        api_key: str = "",
        timeout: int = 60,
        max_retries: int = 3,
        device_fingerprint: str = "",
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.license_key = license_key.strip()
        # In the simplified basic-Pro flow the license key doubles as the
        # X-API-Key. Callers that have a separate gateway API key can pass it.
        self.api_key = api_key or self.license_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.device_fingerprint = device_fingerprint or self._derive_device_fingerprint(self.license_key)

        self._token = _TokenState()
        if user_token:
            self._token.access_token = user_token
            # Assume the token is valid for the full refresh interval;
            # the first 401 will trigger a refresh.
            self._token.expires_at = time.time() + 900

        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ──────────────────────────────────────────────────

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or lazily create the shared httpx async client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={"X-API-Key": self.api_key},
            )
            logger.debug("relay_httpx_client_created", gateway=self.gateway_url)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client. Call on app shutdown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
            logger.info("relay_httpx_client_closed")

    # ── Token management ───────────────────────────────────────────

    @staticmethod
    def _derive_device_fingerprint(license_key: str) -> str:
        """Derive a deterministic device fingerprint from the license key.

        Format: ``sha256:`` + 64 hex chars (matches gateway schema).
        """
        digest = hashlib.sha256(license_key.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _auth_headers(self) -> dict[str, str]:
        """Build the Authorization header from the cached JWT."""
        return {"Authorization": f"Bearer {self._token.access_token}"}

    async def refresh_token(self) -> str:
        """Refresh the relay JWT using the license key.

        Calls the gateway license activation endpoint with the license
        key and device fingerprint. The returned access token is cached
        and used for subsequent relay requests.

        Returns:
            The new access token (JWT string).

        Raises:
            RelayAuthError: If the license key is invalid or expired.
            RelayUnavailableError: If the gateway is unreachable.
        """
        async with self._token.refresh_lock:
            # Double-check after acquiring the lock (another coroutine may
            # have already refreshed).
            if not self._token.needs_refresh:
                return self._token.access_token

            url = f"{self.gateway_url}{_LICENSE_PREFIX}/activate"
            payload = {
                "license_key": self.license_key,
                "device_fingerprint": self.device_fingerprint,
            }

            try:
                client = await self._get_client()
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=httpx.Timeout(15.0, connect=5.0),
                )
            except httpx.HTTPError as exc:
                logger.error("relay_token_refresh_network_error", error=str(exc)[:200])
                raise RelayUnavailableError(
                    message=f"Cannot reach gateway to refresh token: {exc}",
                    details={"gateway_url": self.gateway_url, "error": str(exc)[:200]},
                ) from exc

            if response.status_code in (401, 403):
                detail = safe_error_detail(response)
                logger.error("relay_token_refresh_auth_failed", status=response.status_code, detail=detail)
                raise RelayAuthError(
                    message=f"License activation rejected (HTTP {response.status_code}): {detail}",
                    details={"status_code": response.status_code, "detail": detail},
                )
            if response.status_code >= 400:
                detail = safe_error_detail(response)
                logger.error("relay_token_refresh_failed", status=response.status_code, detail=detail)
                raise RelayError(
                    message=f"License activation failed (HTTP {response.status_code}): {detail}",
                    code="RELAY_LICENSE_ERROR",
                    details={"status_code": response.status_code, "detail": detail},
                )

            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise RelayError(
                    message=f"Invalid JSON in activation response: {exc}",
                    code="RELAY_PARSE_ERROR",
                ) from exc

            # The gateway returns a UnifiedResponse with data.tokens
            token_data = self._extract_token_data(data)
            self._token.access_token = token_data["access_token"]
            self._token.refresh_token = token_data.get("refresh_token", "")
            self._token.expires_at = time.time() + token_data.get("expires_in", 900)

            logger.info(
                "relay_token_refreshed",
                expires_in=token_data.get("expires_in", 900),
                has_refresh=bool(self._token.refresh_token),
            )
            return self._token.access_token

    @staticmethod
    def _extract_token_data(data: dict[str, Any]) -> dict[str, Any]:
        """Extract the token pair from the gateway response.

        Handles both the ``UnifiedResponse`` envelope (``data.tokens``)
        and a flat ``{access_token, refresh_token, expires_in}`` dict.
        """
        if "data" in data and isinstance(data["data"], dict):
            inner = data["data"]
            if "tokens" in inner and isinstance(inner["tokens"], dict):
                return inner["tokens"]
            if "access_token" in inner:
                return inner
        if "tokens" in data:
            tokens: dict[str, Any] = data["tokens"]
            return tokens
        if "access_token" in data:
            return data
        raise RelayError(
            message="Activation response missing token data",
            code="RELAY_PARSE_ERROR",
            details={"keys": list(data.keys())},
        )

    async def _ensure_token(self) -> str:
        """Ensure a valid relay JWT is cached, refreshing if needed."""
        if self._token.needs_refresh:
            await self.refresh_token()
        return self._token.access_token

    # ── Health check ───────────────────────────────────────────────

    async def health_check(self) -> bool:
        """Check gateway connectivity.

        Returns:
            True if the gateway health endpoint responds with HTTP 200,
            False otherwise (including network errors).
        """
        url = f"{self.gateway_url}{_HEALTH_PATH}"
        try:
            client = await self._get_client()
            response = await client.get(url, timeout=httpx.Timeout(5.0, connect=3.0))
            ok = response.status_code == 200
            logger.debug("relay_health_check", status=response.status_code, ok=ok)
            return ok
        except httpx.HTTPError as exc:
            logger.warning("relay_health_check_error", error=str(exc)[:200])
            return False


# ── Factory: create RelayClient from Settings ─────────────────────


def create_relay_client_from_settings(
    settings: Any,
) -> RelayClient:
    """Create a RelayClient from application Settings.

    Reads ``relay_gateway_url``, ``pro_license_key``, and
    ``relay_user_token`` from the settings object.

    Args:
        settings: A :class:`promiselink.config.Settings` instance (or
            any object with the same attributes).

    Returns:
        A configured :class:`RelayClient` instance.

    Raises:
        ValueError: If ``relay_gateway_url`` or ``pro_license_key`` is
            not set.
    """
    gateway_url = getattr(settings, "relay_gateway_url", "") or ""
    license_key = getattr(settings, "pro_license_key", "") or ""
    user_token = getattr(settings, "relay_user_token", "") or ""

    if not gateway_url:
        raise ValueError("relay_gateway_url is not configured")
    if not license_key:
        raise ValueError("pro_license_key is not configured")

    return RelayClient(
        gateway_url=gateway_url,
        license_key=license_key,
        user_token=user_token,
        timeout=getattr(settings, "llm_timeout", 60),
        max_retries=getattr(settings, "llm_max_retries", 3),
    )


# ── Module-level singleton management ──────────────────────────────

_shared_client: RelayClient | None = None
_client_lock = asyncio.Lock()


async def get_shared_relay_client(settings: Any = None) -> RelayClient:
    """Get or create the module-level shared RelayClient.

    Reuses a single RelayClient (and its httpx connection pool) across
    the application lifecycle. The client is lazily created from
    settings on first access.

    Args:
        settings: Optional settings object. Only used on first creation;
            subsequent calls ignore this argument. If None on first
            creation, application settings are loaded.

    Returns:
        The shared RelayClient instance.

    Raises:
        ValueError: If relay is not configured (no gateway URL or
            license key) on first creation.
    """
    global _shared_client
    if _shared_client is None:
        async with _client_lock:
            # Double-check after acquiring the lock
            if _shared_client is None:
                if settings is None:
                    from promiselink.config import get_settings
                    settings = get_settings()
                _shared_client = create_relay_client_from_settings(settings)
                logger.info("shared_relay_client_created")
    return _shared_client


async def close_relay_client() -> None:
    """Close the shared RelayClient. Call on app shutdown.

    Closes the underlying httpx connection pool and resets the
    singleton. Safe to call even if no client was created.
    """
    global _shared_client
    if _shared_client is not None:
        try:
            await _shared_client.close()
        except Exception as e:  # Startup/shutdown — keep broad catch for resilience
            logger.warning("relay_client_close_error", error=str(e))
        finally:
            _shared_client = None
            logger.info("shared_relay_client_closed")

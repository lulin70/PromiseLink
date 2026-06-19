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

License: GNU AGPL v3 — see LICENSE file for details.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from promiselink.core.exceptions import (
    LLMError,
    LLMResponseParseError,
    LLMTimeoutError,
)
from promiselink.core.logging import get_logger
from promiselink.core.text_utils import extract_json_from_text

logger = get_logger("promiselink.relay_client")

# ── Gateway API paths (must match gateway/api/v1/relay.py) ──
_RELAY_PREFIX = "/api/v1/pro/relay"
_LICENSE_PREFIX = "/api/v1/pro/license"
_HEALTH_PATH = "/api/v1/pro/health"

# Default relay model (gateway selects the actual backend model)
_DEFAULT_LLM_MODEL = "moka/claude-sonnet-4-6"
_DEFAULT_ASR_MODEL = "whisper-1"
_DEFAULT_TTS_MODEL = "moka-tts"
_DEFAULT_OCR_MODEL = "moka-vision"

# Token refresh safety margin (refresh 60s before expiry)
_TOKEN_REFRESH_MARGIN = 60


class RelayError(LLMError):
    """Relay gateway error.

    Raised when the gateway is unreachable, returns an error status,
    or the license is invalid/expired. Subclasses ``LLMError`` so that
    existing error-handling code that catches ``LLMError`` also covers
    relay failures.
    """

    def __init__(self, message: str, code: str = "RELAY_ERROR", details: dict | None = None):
        super().__init__(message=message, code=code, details=details or {})


class RelayAuthError(RelayError):
    """Relay authentication / license error (HTTP 401/403)."""

    def __init__(self, message: str = "Relay authentication failed", details: dict | None = None):
        super().__init__(message=message, code="RELAY_AUTH_ERROR", details=details or {})


class RelayUnavailableError(RelayError):
    """Relay gateway is unreachable or returned 5xx."""

    def __init__(self, message: str = "Relay gateway unavailable", details: dict | None = None):
        super().__init__(message=message, code="RELAY_UNAVAILABLE", details=details or {})


@dataclass
class _TokenState:
    """Internal mutable state for the cached relay JWT."""

    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # unix timestamp
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def needs_refresh(self) -> bool:
        """Return True if the token is missing or about to expire."""
        if not self.access_token:
            return True
        return time.time() >= (self.expires_at - _TOKEN_REFRESH_MARGIN)


class RelayClient:
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
                detail = self._safe_error_detail(response)
                logger.error("relay_token_refresh_auth_failed", status=response.status_code, detail=detail)
                raise RelayAuthError(
                    message=f"License activation rejected (HTTP {response.status_code}): {detail}",
                    details={"status_code": response.status_code, "detail": detail},
                )
            if response.status_code >= 400:
                detail = self._safe_error_detail(response)
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

    # ── LLM relay ──────────────────────────────────────────────────

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = _DEFAULT_LLM_MODEL,
        *,
        stream: bool = False,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """LLM chat completion via the gateway.

        Args:
            messages: Chat messages in OpenAI format
                (``[{"role": "user", "content": "..."}]``).
            model: Model name (gateway maps to the actual backend).
            stream: If True, returns a dict with ``stream`` set to an
                async iterator of SSE events. If False, returns the
                full response dict.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            For non-streaming: a dict with ``content``, ``model``,
            ``usage``, and ``billing`` keys (matches gateway
            ``LLMRelayResponse``).
            For streaming: ``{"stream": <async iterator>}``.

        Raises:
            RelayError: On gateway errors.
            RelayAuthError: On auth failures (after auto-refresh attempt).
            RelayUnavailableError: If the gateway is unreachable.
        """
        url = f"{self.gateway_url}{_RELAY_PREFIX}/llm"
        payload: dict[str, Any] = {
            "provider": "moka_ai",
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }

        if stream:
            return {"stream": self._stream_llm(url, payload)}

        response_data = await self._post_with_auth(url, payload)
        return self._parse_llm_response(response_data)

    async def _stream_llm(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> Any:
        """Yield SSE events from the streaming LLM relay endpoint.

        Pre-checks token validity via ``_ensure_token`` (refreshes when
        expiry is within ``_TOKEN_REFRESH_MARGIN`` seconds). On HTTP 401,
        refreshes the token and rebuilds the stream connection once
        (no infinite retry).
        """
        await self._ensure_token()
        client = await self._get_client()

        async def event_stream() -> Any:
            retried = False
            while True:
                async with client.stream(
                    "POST",
                    url,
                    json=payload,
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                ) as response:
                    if response.status_code == 401 and not retried:
                        # I6: refresh token then rebuild the stream connection (retry at most once)
                        logger.warning("relay_stream_401_refreshing", url=url)
                        await self.refresh_token()
                        retried = True
                        continue  # exit current async with and re-issue the stream request
                    if response.status_code == 401:
                        # Still 401 after retry — give up to avoid infinite retry
                        yield {"event": "error", "data": {"code": "RELAY_AUTH_REFRESHED"}}
                        return
                    if response.status_code >= 400:
                        body = await response.aread()
                        yield {
                            "event": "error",
                            "data": {
                                "code": "RELAY_ERROR",
                                "status": response.status_code,
                                "body": body.decode("utf-8", errors="replace")[:500],
                            },
                        }
                        return
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                yield {"event": "token", "data": json.loads(line[5:].strip())}
                            except json.JSONDecodeError:
                                continue
                    return  # streaming finished, exit the loop

        return event_stream()

    @staticmethod
    def _parse_llm_response(data: dict[str, Any]) -> dict[str, Any]:
        """Extract the LLM content from the gateway response.

        Handles the ``UnifiedResponse`` envelope (``data.content``) and
        a flat ``{content, model, usage, billing}`` dict.
        """
        inner = data.get("data", data) if isinstance(data.get("data"), dict) else data
        content = inner.get("content", "")
        if not content:
            # Some responses may nest content under choices (OpenAI format)
            choices = inner.get("choices", [])
            if choices and isinstance(choices, list):
                content = choices[0].get("message", {}).get("content", "")
        return {
            "content": content,
            "model": inner.get("model", ""),
            "usage": inner.get("usage", {}),
            "billing": inner.get("billing", {}),
        }

    # ── ASR relay ──────────────────────────────────────────────────

    async def asr(
        self,
        audio_bytes: bytes,
        *,
        model: str = _DEFAULT_ASR_MODEL,
        language: str = "zh",
        filename: str = "audio.mp3",
    ) -> dict[str, Any]:
        """ASR relay — speech to text via the gateway.

        Args:
            audio_bytes: Raw audio file bytes (mp3/wav/m4a).
            model: ASR model name.
            language: Language code (default ``zh``).
            filename: Filename for content-type detection.

        Returns:
            Dict with ``text``, ``language``, ``duration_seconds``,
            and ``billing`` keys.

        Raises:
            RelayError: On gateway errors.
        """
        url = f"{self.gateway_url}{_RELAY_PREFIX}/asr"
        files = {"audio": (filename, audio_bytes, "application/octet-stream")}
        data = {"model": model, "language": language}
        response = await self._post_multipart_with_auth(url, files=files, data=data)
        result: dict[str, Any] = response.get("data", response)
        return result

    # ── TTS relay ──────────────────────────────────────────────────

    async def tts(
        self,
        text: str,
        *,
        model: str = _DEFAULT_TTS_MODEL,
        voice: str = "zh-female-1",
        speed: float = 1.0,
        response_format: str = "mp3",
    ) -> bytes:
        """TTS relay — text to speech via the gateway.

        Args:
            text: Text to synthesize (max 500 chars per gateway schema).
            model: TTS model name.
            voice: Voice name.
            speed: Speech speed (0.5–2.0).
            response_format: Audio format (``mp3`` or ``wav``).

        Returns:
            Raw audio bytes.

        Raises:
            RelayError: On gateway errors.
        """
        url = f"{self.gateway_url}{_RELAY_PREFIX}/tts"
        payload = {
            "text": text,
            "model": model,
            "voice": voice,
            "speed": speed,
            "response_format": response_format,
        }

        await self._ensure_token()
        client = await self._get_client()

        try:
            response = await client.post(
                url,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        except httpx.TimeoutException as exc:
            raise RelayError(
                message=f"TTS relay timeout after {self.timeout}s",
                code="RELAY_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise RelayUnavailableError(
                message=f"TTS relay network error: {exc}",
                details={"error": str(exc)[:200]},
            ) from exc

        if response.status_code == 401:
            await self.refresh_token()
            response = await client.post(
                url,
                json=payload,
                headers={**self._auth_headers(), "Content-Type": "application/json"},
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )

        if response.status_code >= 400:
            detail = self._safe_error_detail(response)
            raise RelayError(
                message=f"TTS relay failed (HTTP {response.status_code}): {detail}",
                code="RELAY_TTS_ERROR",
                details={"status_code": response.status_code, "detail": detail},
            )

        return response.content

    # ── OCR relay ──────────────────────────────────────────────────

    async def ocr(
        self,
        image_bytes: bytes,
        *,
        task: str = "general",
        model: str = _DEFAULT_OCR_MODEL,
        filename: str = "image.png",
    ) -> dict[str, Any]:
        """OCR relay — image text recognition via the gateway.

        Args:
            image_bytes: Raw image file bytes (jpg/png).
            task: OCR task type (``general``, ``business_card``, etc.).
            model: Vision model name.
            filename: Filename for content-type detection.

        Returns:
            Dict with ``task``, ``structured``, ``raw_text``, and
            ``billing`` keys.

        Raises:
            RelayError: On gateway errors.
        """
        url = f"{self.gateway_url}{_RELAY_PREFIX}/ocr"
        files = {"image": (filename, image_bytes, "application/octet-stream")}
        data = {"task": task, "model": model}
        response = await self._post_multipart_with_auth(url, files=files, data=data)
        ocr_result: dict[str, Any] = response.get("data", response)
        return ocr_result

    # ── LLMProvider Protocol (compatible with LLMClient) ───────────

    async def call(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a prompt and return the raw text response.

        Implements the :class:`LLMProvider` Protocol so this client can
        replace the local ``LLMClient``.

        Args:
            prompt: User prompt text.
            system_prompt: Optional system prompt.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            Raw text response from the LLM via the gateway.

        Raises:
            RelayError: On gateway errors.
            LLMResponseParseError: If the response has no content.
        """
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        result = await self.chat_completion(
            messages=messages,
            stream=False,
            max_tokens=max_tokens or 2000,
            temperature=temperature if temperature is not None else 0.7,
        )
        content: str = result.get("content", "")
        if not content:
            raise LLMResponseParseError(parse_error="Relay returned empty content")
        return content.strip()

    async def call_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Send a prompt and parse the response as JSON.

        Implements the :class:`LLMProvider` Protocol.

        Args:
            prompt: User prompt text.
            system_prompt: Optional system prompt.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            Parsed JSON dict from the LLM response.

        Raises:
            LLMResponseParseError: If JSON cannot be extracted.
            RelayError: On gateway errors.
        """
        text = await self.call(
            prompt,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        try:
            return extract_json_from_text(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseParseError(parse_error=str(exc)) from exc

    async def generate(self, prompt: str, max_tokens: int = 10) -> str:
        """Generate a short text response (convenience method).

        Implements the :class:`LLMProvider` Protocol. Uses low
        temperature (0.0) for deterministic output.

        Args:
            prompt: The user prompt text.
            max_tokens: Maximum tokens, defaults to 10 for short outputs.

        Returns:
            The generated short text response.
        """
        return await self.call(prompt, max_tokens=max_tokens, temperature=0.0)

    # ── Internal HTTP helpers ──────────────────────────────────────

    async def _post_with_auth(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """POST JSON with auto token refresh and retry on 401.

        Args:
            url: Full gateway URL.
            payload: JSON body.

        Returns:
            Parsed JSON response dict.

        Raises:
            RelayError: On non-retryable errors.
            RelayAuthError: On auth failure after refresh.
            RelayUnavailableError: On network errors.
            LLMTimeoutError: On timeout.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            await self._ensure_token()
            client = await self._get_client()

            try:
                response = await client.post(
                    url,
                    json=payload,
                    headers={**self._auth_headers(), "Content-Type": "application/json"},
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                )
            except httpx.TimeoutException:
                last_error = LLMTimeoutError(provider="relay", timeout=self.timeout)
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_error
            except httpx.HTTPError as exc:
                last_error = RelayUnavailableError(
                    message=f"Relay network error: {exc}",
                    details={"error": str(exc)[:200]},
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_error from exc

            # Auto-refresh on 401 (once per call)
            if response.status_code == 401 and attempt == 0:
                logger.warning("relay_401_refreshing", url=url)
                await self.refresh_token()
                continue

            if response.status_code in (401, 403):
                detail = self._safe_error_detail(response)
                raise RelayAuthError(
                    message=f"Relay auth failed (HTTP {response.status_code}): {detail}",
                    details={"status_code": response.status_code, "detail": detail},
                )

            if response.status_code == 429:
                last_error = RelayError(
                    message="Relay rate limit exceeded",
                    code="RELAY_RATE_LIMIT",
                    details={"status_code": 429},
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                raise last_error

            if response.status_code >= 500:
                detail = self._safe_error_detail(response)
                last_error = RelayUnavailableError(
                    message=f"Relay server error (HTTP {response.status_code}): {detail}",
                    details={"status_code": response.status_code, "detail": detail},
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise last_error

            if response.status_code >= 400:
                detail = self._safe_error_detail(response)
                raise RelayError(
                    message=f"Relay request failed (HTTP {response.status_code}): {detail}",
                    code="RELAY_HTTP_ERROR",
                    details={"status_code": response.status_code, "detail": detail},
                )

            try:
                json_result: dict[str, Any] = response.json()
                return json_result
            except json.JSONDecodeError as exc:
                raise RelayError(
                    message=f"Invalid JSON in relay response: {exc}",
                    code="RELAY_PARSE_ERROR",
                ) from exc

        if last_error is not None:
            raise last_error
        # Loop exited via `continue` after a 401 refresh on the final attempt:
        # we refreshed the token but had no remaining retry to use it.
        raise RelayAuthError(
            message="Relay auth failed: token refreshed but no retries remaining",
            details={"status_code": 401},
        )

    async def _post_multipart_with_auth(
        self,
        url: str,
        *,
        files: dict[str, Any],
        data: dict[str, str],
    ) -> dict[str, Any]:
        """POST multipart form with auto token refresh on 401.

        Used by ASR and OCR endpoints that accept file uploads.

        Args:
            url: Full gateway URL.
            files: Files dict for httpx multipart upload.
            data: Form fields.

        Returns:
            Parsed JSON response dict.

        Raises:
            RelayError: On gateway errors.
        """
        await self._ensure_token()
        client = await self._get_client()

        try:
            response = await client.post(
                url,
                files=files,
                data=data,
                headers=self._auth_headers(),
                timeout=httpx.Timeout(self.timeout, connect=10.0),
            )
        except httpx.TimeoutException as exc:
            raise RelayError(
                message=f"Relay multipart timeout after {self.timeout}s",
                code="RELAY_TIMEOUT",
            ) from exc
        except httpx.HTTPError as exc:
            raise RelayUnavailableError(
                message=f"Relay multipart network error: {exc}",
                details={"error": str(exc)[:200]},
            ) from exc

        # Auto-refresh on 401 (single retry)
        if response.status_code == 401:
            logger.warning("relay_multipart_401_refreshing", url=url)
            await self.refresh_token()
            try:
                response = await client.post(
                    url,
                    files=files,
                    data=data,
                    headers=self._auth_headers(),
                    timeout=httpx.Timeout(self.timeout, connect=10.0),
                )
            except httpx.HTTPError as exc:
                raise RelayUnavailableError(
                    message=f"Relay multipart retry failed: {exc}",
                    details={"error": str(exc)[:200]},
                ) from exc

        if response.status_code in (401, 403):
            detail = self._safe_error_detail(response)
            raise RelayAuthError(
                message=f"Relay auth failed (HTTP {response.status_code}): {detail}",
                details={"status_code": response.status_code, "detail": detail},
            )
        if response.status_code >= 400:
            detail = self._safe_error_detail(response)
            raise RelayError(
                message=f"Relay multipart failed (HTTP {response.status_code}): {detail}",
                code="RELAY_HTTP_ERROR",
                details={"status_code": response.status_code, "detail": detail},
            )

        try:
            multipart_result: dict[str, Any] = response.json()
            return multipart_result
        except json.JSONDecodeError as exc:
            raise RelayError(
                message=f"Invalid JSON in relay response: {exc}",
                code="RELAY_PARSE_ERROR",
            ) from exc

    @staticmethod
    def _safe_error_detail(response: httpx.Response) -> str:
        """Safely extract an error detail string from a response."""
        try:
            data = response.json()
            if isinstance(data, dict):
                # UnifiedResponse envelope
                if "detail" in data:
                    return str(data["detail"])[:300]
                if "message" in data:
                    return str(data["message"])[:300]
                if "error" in data:
                    return str(data["error"])[:300]
            return response.text[:300]
        except (json.JSONDecodeError, ValueError):
            return response.text[:300]


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
        except Exception as e:
            logger.warning("relay_client_close_error", error=str(e))
        finally:
            _shared_client = None
            logger.info("shared_relay_client_closed")

"""Models, constants, and exceptions for the relay client.

Extracted from :mod:`relay_client` to keep the main module under 600 lines.
Contains:

* Gateway API path constants and default model names.
* The relay exception hierarchy (:class:`RelayError` →
  :class:`RelayAuthError` / :class:`RelayUnavailableError`).
* :class:`_TokenState` — internal mutable state for the cached relay JWT.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx

from promiselink.core.exceptions import LLMError

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

__all__ = [
    "_RELAY_PREFIX",
    "_LICENSE_PREFIX",
    "_HEALTH_PATH",
    "_DEFAULT_LLM_MODEL",
    "_DEFAULT_ASR_MODEL",
    "_DEFAULT_TTS_MODEL",
    "_DEFAULT_OCR_MODEL",
    "_TOKEN_REFRESH_MARGIN",
    "RelayError",
    "RelayAuthError",
    "RelayUnavailableError",
    "_TokenState",
    "safe_error_detail",
]


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


def safe_error_detail(response: httpx.Response) -> str:
    """Safely extract an error detail string from an HTTP response.

    Tries to parse the response body as JSON and look for ``detail``,
    ``message``, or ``error`` keys (UnifiedResponse envelope). Falls
    back to the raw response text.
    """
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

"""Redis async client for the gateway.

Provides a lazily-initialised ``redis.asyncio`` client used for:
- WebSocket connection mapping
- Rate-limit counters
- JWT blacklist (CRL)
- API Key pool runtime state cache
"""

from __future__ import annotations

from typing import Any

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover - redis is a hard dependency
    aioredis = None  # type: ignore[assignment]

from gateway.config import get_settings

_client: Any | None = None


def get_redis() -> Any:
    """Return the global async Redis client, creating it on first call.

    Returns ``None`` if the ``redis`` package is not installed so that
    unit tests that do not exercise Redis can still import this module.
    """
    global _client
    if _client is None and aioredis is not None:
        settings = get_settings()
        _client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
        )
    return _client


async def close_redis() -> None:
    """Close the Redis connection pool."""
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def set_redis_client(client: Any) -> None:
    """Inject a custom Redis client (for testing)."""
    global _client
    _client = client

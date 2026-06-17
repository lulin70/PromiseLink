"""Redis client wrapper.

Provides an async Redis interface. For testing, an in-memory fake can be
injected via ``set_redis_client``.
"""

from __future__ import annotations

from typing import Any

try:
    from redis.asyncio import Redis  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Redis = None  # type: ignore[assignment, misc]

from gateway.config import Settings, get_settings

_redis: Any = None


async def get_redis(settings: Settings | None = None) -> Any:
    """Return the global async Redis client, creating it on first call."""
    global _redis
    if _redis is None:
        s = settings or get_settings()
        if Redis is not None:
            _redis = Redis.from_url(s.redis_url, decode_responses=True)
        else:
            _redis = InMemoryRedis()
    return _redis


def set_redis_client(client: Any) -> None:
    """Override the global Redis client (for testing)."""
    global _redis
    _redis = client


async def close_redis() -> None:
    """Close the Redis connection."""
    global _redis
    if _redis is not None and hasattr(_redis, "close"):
        await _redis.close()
    _redis = None


class InMemoryRedis:
    """Simple in-memory Redis mock for testing.

    Implements the subset of Redis commands used by the gateway:
    ``get``, ``set``, ``delete``, ``incr``, ``expire``, ``exists``,
    ``hset``, ``hget``, ``hgetall``, ``hdel``.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._ttls: dict[str, float] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    async def get(self, key: str) -> str | None:
        if self._is_expired(key):
            self._cleanup(key)
            return None
        return self._data.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> str:
        self._data[key] = str(value)
        if ex is not None:
            import time

            self._ttls[key] = time.time() + ex
        return "OK"

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._data or key in self._hashes:
                self._data.pop(key, None)
                self._hashes.pop(key, None)
                self._ttls.pop(key, None)
                count += 1
        return count

    async def incr(self, key: str) -> int:
        current = int(self._data.get(key, "0")) + 1
        self._data[key] = str(current)
        return current

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._data:
            import time

            self._ttls[key] = time.time() + seconds
            return True
        return False

    async def exists(self, key: str) -> bool:
        if self._is_expired(key):
            self._cleanup(key)
            return False
        return key in self._data or key in self._hashes

    async def hset(self, name: str, key: str | None = None, value: Any = None, mapping: dict | None = None) -> int:
        if name not in self._hashes:
            self._hashes[name] = {}
        count = 0
        if mapping:
            for k, v in mapping.items():
                self._hashes[name][k] = str(v)
                count += 1
        if key is not None and value is not None:
            self._hashes[name][key] = str(value)
            count += 1
        return count

    async def hget(self, name: str, key: str) -> str | None:
        return self._hashes.get(name, {}).get(key)

    async def hgetall(self, name: str) -> dict[str, str]:
        return dict(self._hashes.get(name, {}))

    async def hdel(self, name: str, *keys: str) -> int:
        h = self._hashes.get(name, {})
        count = 0
        for key in keys:
            if key in h:
                del h[key]
                count += 1
        return count

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    def _is_expired(self, key: str) -> bool:
        import time

        return key in self._ttls and time.time() > self._ttls[key]

    def _cleanup(self, key: str) -> None:
        self._data.pop(key, None)
        self._ttls.pop(key, None)

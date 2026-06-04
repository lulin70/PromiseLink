"""Redis cache client for EventLink.

Provides caching for:
- LLM API responses (avoid duplicate calls)
- User sessions
- Rate limiting
"""

import json
from typing import Any

from eventlink.config import get_settings
from eventlink.core.logging import get_logger

logger = get_logger("eventlink.redis")

_redis_client = None

async def get_redis():
    """Get or create Redis client (singleton)."""
    global _redis_client
    settings = get_settings()
    if not settings.redis_enabled:
        return None
    if _redis_client is None:
        try:
            import redis.asyncio as aioredis
            _redis_client = aioredis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await _redis_client.ping()
            logger.info("redis_connected", url=settings.redis_url)
        except Exception as e:
            logger.warning("redis_connection_failed", error=str(e))
            _redis_client = None
    return _redis_client

async def close_redis():
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None

class CacheService:
    """Application-level cache service with Redis backend and in-memory fallback."""

    def __init__(self):
        self._memory_cache: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        """Get cached value by key."""
        redis = await get_redis()
        if redis:
            try:
                val = await redis.get(f"eventlink:{key}")
                if val:
                    return json.loads(val)
            except Exception as e:
                logger.warning("redis_get_failed", key=key, error=str(e))
        # Fallback to memory cache
        return self._memory_cache.get(key)

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set cached value with TTL in seconds."""
        redis = await get_redis()
        if redis:
            try:
                await redis.set(f"eventlink:{key}", json.dumps(value, default=str), ex=ttl)
                return
            except Exception as e:
                logger.warning("redis_set_failed", key=key, error=str(e))
        # Fallback to memory cache (no TTL)
        self._memory_cache[key] = value

    async def delete(self, key: str) -> None:
        """Delete cached value."""
        redis = await get_redis()
        if redis:
            try:
                await redis.delete(f"eventlink:{key}")
            except Exception as e:
                logger.warning("redis_delete_failed", key=key, error=str(e))
        self._memory_cache.pop(key, None)

    async def llm_cache_key(self, prompt: str, model: str) -> str:
        """Generate cache key for LLM response."""
        import hashlib
        prompt_hash = hashlib.sha256(f"{model}:{prompt}".encode()).hexdigest()[:16]
        return f"llm:{prompt_hash}"

# Singleton
cache_service = CacheService()

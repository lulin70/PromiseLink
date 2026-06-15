"""Sliding window rate limiter with Redis backend and in-memory fallback.

Supports per-user and per-IP rate limiting with separate limits for
LLM-heavy endpoints (/voice/, /media/).
"""

import time
from collections import defaultdict
from typing import Optional

from promiselink.config import get_settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.rate_limiter")

# Window duration in seconds (1 minute)
WINDOW_SECONDS = 60


class InMemorySlidingWindow:
    """In-memory sliding window rate limiter (fallback when Redis is disabled).

    Uses a list of timestamps per key to implement a true sliding window.
    Thread safety is not a concern for single-process async FastAPI.
    """

    # Seconds between periodic cleanups of expired windows
    CLEANUP_INTERVAL = 300

    def __init__(self) -> None:
        # key -> list of timestamps
        self._windows: dict[str, list[float]] = defaultdict(list)
        self._last_cleanup: float = time.time()

    async def is_allowed(self, key: str, limit: int) -> tuple[bool, int, float]:
        """Check if a request is allowed under the rate limit.

        Returns:
            (allowed, remaining, retry_after)
            - allowed: True if request is permitted
            - remaining: number of requests remaining in current window
            - retry_after: seconds until next request would be allowed (0 if allowed)
        """
        now = time.time()
        window_start = now - WINDOW_SECONDS

        # Periodic cleanup: remove expired windows every CLEANUP_INTERVAL seconds
        if now - self._last_cleanup > self.CLEANUP_INTERVAL:
            expired_keys = [
                k for k, timestamps in self._windows.items()
                if not timestamps or all(ts <= window_start for ts in timestamps)
            ]
            for k in expired_keys:
                del self._windows[k]
            self._last_cleanup = now
        elif len(self._windows) > 1000:
            # Also clean up when total keys exceed 1000 (immediate pressure relief)
            expired_keys = [
                k for k, timestamps in self._windows.items()
                if not timestamps or all(ts <= window_start for ts in timestamps)
            ]
            for k in expired_keys:
                del self._windows[k]

        # Remove expired entries
        timestamps = self._windows[key]
        self._windows[key] = [ts for ts in timestamps if ts > window_start]
        timestamps = self._windows[key]

        current_count = len(timestamps)

        if current_count >= limit:
            # Calculate when the oldest request in the window will expire
            oldest = min(timestamps)
            retry_after = oldest + WINDOW_SECONDS - now
            return False, 0, max(retry_after, 0.1)

        # Allow the request and record the timestamp
        timestamps.append(now)
        remaining = limit - len(timestamps)
        return True, remaining, 0

    def reset(self, key: Optional[str] = None) -> None:
        """Reset rate limit state for testing."""
        if key:
            self._windows.pop(key, None)
        else:
            self._windows.clear()


class RedisSlidingWindow:
    """Redis-backed sliding window rate limiter.

    Uses a Redis sorted set (ZSET) where scores are timestamps.
    This provides a true sliding window with atomic operations.
    """

    def __init__(self) -> None:
        self._prefix = "promiselink:rate_limit:"

    async def is_allowed(self, key: str, limit: int) -> tuple[bool, int, float]:
        """Check if a request is allowed under the rate limit using Redis.

        Returns:
            (allowed, remaining, retry_after)
        """
        from promiselink.core.redis import get_redis

        redis = await get_redis()
        if redis is None:
            # Redis unavailable, fall back to in-memory
            return await _memory_limiter.is_allowed(key, limit)

        now = time.time()
        window_start = now - WINDOW_SECONDS
        redis_key = f"{self._prefix}{key}"

        try:
            # Use a pipeline for atomicity
            pipe = redis.pipeline()
            # Remove expired entries
            pipe.zremrangebyscore(redis_key, 0, window_start)
            # Count current entries
            pipe.zcard(redis_key)
            # Add new entry (score=timestamp, member=unique)
            pipe.zadd(redis_key, {f"{now}:{key}": now})
            # Set expiry on the key
            pipe.expire(redis_key, WINDOW_SECONDS + 1)
            results = await pipe.execute()

            current_count = results[1]  # zcard result before adding

            if current_count >= limit:
                # Get the oldest entry to calculate retry_after
                oldest_entries = await redis.zrange(redis_key, 0, 0, withscores=True)
                if oldest_entries:
                    oldest_score = oldest_entries[0][1]
                    retry_after = oldest_score + WINDOW_SECONDS - now
                else:
                    retry_after = WINDOW_SECONDS
                return False, 0, max(retry_after, 0.1)

            remaining = limit - current_count - 1
            return True, remaining, 0

        except Exception as e:
            logger.warning("redis_rate_limit_failed", error=str(e))
            # Fall back to in-memory
            return await _memory_limiter.is_allowed(key, limit)


# Singleton instances
_memory_limiter = InMemorySlidingWindow()
_redis_limiter = RedisSlidingWindow()


async def check_rate_limit(
    key: str,
    limit: int,
) -> tuple[bool, int, float]:
    """Check rate limit for a given key and limit.

    Automatically uses Redis when available, falls back to in-memory.

    Args:
        key: Rate limit key (e.g. "user:<user_id>" or "ip:<ip>")
        limit: Maximum requests per minute

    Returns:
        (allowed, remaining, retry_after)
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return True, limit, 0

    if settings.redis_enabled:
        return await _redis_limiter.is_allowed(key, limit)
    return await _memory_limiter.is_allowed(key, limit)


def reset_rate_limits(key: Optional[str] = None) -> None:
    """Reset in-memory rate limit state (for testing)."""
    _memory_limiter.reset(key)

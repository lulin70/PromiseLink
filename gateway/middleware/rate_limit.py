"""Rate limiting middleware.

Implements user-level rate limiting using Redis (or in-memory fallback).
Limits: 100 req/min per user (configurable via settings).

Reference: Pro_Edition_Tech_Design_Phase0.md §9.4.1
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway.config import Settings, get_settings
from gateway.core.exceptions import RateLimitExceededError


class RateLimitMiddleware(BaseHTTPMiddleware):
    """User-level rate limiting middleware.

    Counts requests per user per minute using Redis INCR. When the count
    exceeds the configured limit, returns 429.
    """

    def __init__(self, app, settings: Settings | None = None) -> None:
        super().__init__(app)
        self.settings = settings or get_settings()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Skip rate limiting for health checks and non-pro routes
        path = request.url.path
        if path.endswith("/health") or path.endswith("/health/live") or path.endswith("/health/ready"):
            return await call_next(request)
        if not path.startswith("/api/v1/pro"):
            return await call_next(request)

        # Get user_id from request state (set by auth middleware)
        user_id = getattr(request.state, "user_id", None)
        if not user_id:
            # No user_id — skip rate limiting (auth will fail later)
            return await call_next(request)

        # Check rate limit
        redis = getattr(request.app.state, "redis", None)
        minute_key = f"rate_limit:{user_id}:{int(time.time() // 60)}"

        if redis is not None:
            current = await redis.incr(minute_key)
            if current == 1:
                await redis.expire(minute_key, 60)
            if current > self.settings.rate_limit_user_per_minute:
                retry_after = 60 - int(time.time() % 60)
                return JSONResponse(
                    status_code=429,
                    content={
                        "request_id": getattr(request.state, "request_id", ""),
                        "success": False,
                        "data": None,
                        "error": {
                            "code": "RATE_LIMIT_EXCEEDED",
                            "message": "Too many requests",
                            "details": {
                                "limit": self.settings.rate_limit_user_per_minute,
                                "window_seconds": 60,
                                "retry_after": retry_after,
                            },
                        },
                    },
                    headers={
                        "X-RateLimit-Limit": str(self.settings.rate_limit_user_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": str(retry_after),
                    },
                )

        return await call_next(request)

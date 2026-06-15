"""FastAPI dependency injection for rate limiting and other shared concerns."""

from fastapi import Depends, Request, status

from promiselink.config import get_settings
from promiselink.core.auth import get_optional_user_id
from promiselink.core.exceptions import BusinessError
from promiselink.core.logging import get_logger
from promiselink.core.rate_limiter import check_rate_limit

logger = get_logger("promiselink.dependencies")


async def rate_limit_dependency(
    request: Request,
    user_id: str | None = Depends(get_optional_user_id),
) -> None:
    """Standard rate limit dependency for general API endpoints.

    Uses authenticated user limit when a valid JWT is present,
    otherwise falls back to the unauthenticated limit.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if user_id:
        key = f"user:{user_id}"
        limit = settings.rate_limit_authenticated
    else:
        # Use client IP for unauthenticated requests
        # Support X-Forwarded-For for reverse proxy scenarios
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        key = f"ip:{client_ip}"
        limit = settings.rate_limit_unauthenticated

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise BusinessError(
            "Rate limit exceeded",
            code="RATE_LIMITED",
            details={"retry_after": int(retry_after) + 1},
        )


async def rate_limit_llm_dependency(
    request: Request,
    user_id: str | None = Depends(get_optional_user_id),
) -> None:
    """Rate limit dependency for LLM-heavy endpoints (/voice/, /media/).

    Uses a lower limit than standard endpoints to protect LLM API quotas.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return

    if user_id:
        key = f"llm:user:{user_id}"
    else:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        key = f"llm:ip:{client_ip}"

    limit = settings.rate_limit_llm

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise BusinessError(
            "Rate limit exceeded for LLM endpoint",
            code="RATE_LIMITED",
            details={"retry_after": int(retry_after) + 1},
        )

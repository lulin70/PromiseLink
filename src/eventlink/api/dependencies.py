"""FastAPI dependency injection for rate limiting and other shared concerns."""

from fastapi import Depends, HTTPException, Request, status

from eventlink.config import get_settings
from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger
from eventlink.core.rate_limiter import check_rate_limit

logger = get_logger("eventlink.dependencies")


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
        client_ip = request.client.host if request.client else "unknown"
        key = f"ip:{client_ip}"
        limit = settings.rate_limit_unauthenticated

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(int(retry_after) + 1)},
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
        client_ip = request.client.host if request.client else "unknown"
        key = f"llm:ip:{client_ip}"

    limit = settings.rate_limit_llm

    allowed, remaining, retry_after = await check_rate_limit(key, limit)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded for LLM endpoint",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

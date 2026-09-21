"""Health check endpoints with dependency verification."""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.config import get_settings
from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger
from promiselink.database import get_async_session
from promiselink.schemas.api_responses import HealthResponse

logger = get_logger("promiselink.health")

router = APIRouter()


@router.get("/health")
async def health_check() -> Any:
    """
    Basic health check endpoint (unauthenticated, no sensitive info).

    Returns application status without dependency checks.
    Use /health/full for comprehensive dependency verification (requires auth).
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "promiselink",
        "version": get_settings().app_version,
        "edition": get_settings().app_edition,
    }


@router.get("/health/db", response_model=HealthResponse)
async def health_check_db(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> HealthResponse:
    """
    Health check with database connectivity test (requires authentication).
    """
    try:
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:  # Health check — keep broad catch for resilience
        db_status = "error"
        logger.warning("health_db_check_failed", error=str(exc))

    return HealthResponse(
        status="healthy" if db_status == "connected" else "unhealthy",
        timestamp=datetime.now(UTC),
        service="promiselink",
        components={"database": db_status},
    )


@router.get("/health/full", response_model=HealthResponse)
async def health_check_full(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> HealthResponse:
    """
    Full health check with all dependency verification (requires authentication).

    Checks: Database, Redis cache, LLM API availability, relay WSS link.
    Returns individual component status and overall health.
    """
    components: dict[str, Any] = {}
    overall_healthy = True

    # 1. Database check
    try:
        await session.execute(text("SELECT 1"))
        components["database"] = {"status": "healthy", "type": "sqlite"}
    except Exception as exc:  # Health check — keep broad catch for resilience
        components["database"] = {"status": "unhealthy"}
        overall_healthy = False
        logger.warning("health_full_db_check_failed", error=str(exc))

    # 2. Redis / Cache check
    try:
        from promiselink.core.redis import CacheService
        cache = CacheService()
        test_key = "__health_check__"
        await cache.set(test_key, "ok", ttl=10)
        result = await cache.get(test_key)
        if result == "ok":
            components["cache"] = {"status": "healthy", "backend": "redis" if cache._redis else "memory"}
        else:
            components["cache"] = {"status": "degraded", "backend": "memory"}
        try:
            await cache.delete(test_key)
        except Exception as exc:  # Health check — keep broad catch for resilience
            logger.debug("health_cache_cleanup_failed", error=str(exc))
    except Exception as exc:  # Health check — keep broad catch for resilience
        components["cache"] = {"status": "degraded", "backend": "memory"}
        logger.warning("health_cache_check_failed", error=str(exc))

    # 3. LLM API check (lightweight — just verify config exists, no URL/model exposure)
    try:
        from promiselink.config import get_settings
        settings = get_settings()
        if settings.llm_api_key and settings.llm_base_url:
            components["llm"] = {"status": "configured"}
        else:
            components["llm"] = {"status": "not_configured"}
            overall_healthy = False
    except Exception as exc:  # Health check — keep broad catch for resilience
        components["llm"] = {"status": "error"}
        overall_healthy = False
        logger.warning("health_llm_check_failed", error=str(exc))

    # 4. Relay WSS link (Pro edition bridge to the cloud gateway).
    # L-1 (2026-09-21): surfaces the terminal state so a license rejection is
    # visible to the user/operator instead of silently retrying forever.
    # Only reported when the relay is actually configured; a basic-edition
    # install with no relay shows "disabled" and is NOT counted as degraded.
    try:
        relay_wss = getattr(request.app.state, "relay_wss_client", None)
        if relay_wss is None:
            components["relay"] = {"status": "disabled"}
        else:
            relay_state = relay_wss.state.as_dict()
            terminal_reason = relay_state.get("terminal_reason", "")
            if terminal_reason:
                components["relay"] = {
                    "status": "unhealthy",
                    "connected": False,
                    "terminal_reason": terminal_reason,
                    "auth_failures": relay_state.get("auth_failures", 0),
                }
                overall_healthy = False
            else:
                components["relay"] = {
                    "status": "healthy" if relay_state.get("connected") else "degraded",
                    "connected": bool(relay_state.get("connected")),
                    "reconnect_count": relay_state.get("reconnect_count", 0),
                }
    except Exception as exc:  # Health check — keep broad catch for resilience
        components["relay"] = {"status": "error"}
        logger.warning("health_relay_check_failed", error=str(exc))

    return HealthResponse(
        status="healthy" if overall_healthy else "degraded",
        timestamp=datetime.now(UTC),
        service="promiselink",
        version=get_settings().app_version,
        components=components,
    )

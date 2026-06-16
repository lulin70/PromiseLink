"""Health check endpoints with dependency verification."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.config import get_settings
from promiselink.core.auth import get_current_user_id
from promiselink.database import get_async_session
from promiselink.schemas.api_responses import HealthResponse

router = APIRouter()


@router.get("/health")
async def health_check():
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
    except Exception:
        db_status = "error"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "unhealthy",
        timestamp=datetime.now(UTC),
        service="promiselink",
        components={"database": db_status},
    )


@router.get("/health/full", response_model=HealthResponse)
async def health_check_full(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> HealthResponse:
    """
    Full health check with all dependency verification (requires authentication).

    Checks: Database, Redis cache, LLM API availability.
    Returns individual component status and overall health.
    """
    components = {}
    overall_healthy = True

    # 1. Database check
    try:
        await session.execute(text("SELECT 1"))
        components["database"] = {"status": "healthy", "type": "sqlite"}
    except Exception:
        components["database"] = {"status": "unhealthy"}
        overall_healthy = False

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
        except Exception:
            pass
    except Exception:
        components["cache"] = {"status": "degraded", "backend": "memory"}

    # 3. LLM API check (lightweight — just verify config exists, no URL/model exposure)
    try:
        from promiselink.config import get_settings
        settings = get_settings()
        if settings.llm_api_key and settings.llm_base_url:
            components["llm"] = {"status": "configured"}
        else:
            components["llm"] = {"status": "not_configured"}
            overall_healthy = False
    except Exception:
        components["llm"] = {"status": "error"}
        overall_healthy = False

    return HealthResponse(
        status="healthy" if overall_healthy else "degraded",
        timestamp=datetime.now(UTC),
        service="promiselink",
        version=get_settings().app_version,
        components=components,
    )

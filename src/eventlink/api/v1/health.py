"""Health check endpoints with dependency verification."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.database import get_async_session

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Basic health check endpoint.

    Returns application status without dependency checks.
    Use /health/full for comprehensive dependency verification.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "eventlink",
    }


@router.get("/health/db")
async def health_check_db(session: AsyncSession = Depends(get_async_session)):
    """
    Health check with database connectivity test.

    Verifies that the database connection is working.
    """
    try:
        await session.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "eventlink",
        "database": db_status,
    }


@router.get("/health/full")
async def health_check_full(session: AsyncSession = Depends(get_async_session)):
    """
    Full health check with all dependency verification.

    Checks: Database, Redis cache, LLM API availability.
    Returns individual component status and overall health.
    """
    components = {}
    overall_healthy = True

    # 1. Database check
    try:
        await session.execute(text("SELECT 1"))
        components["database"] = {"status": "healthy", "type": "sqlite"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}
        overall_healthy = False

    # 2. Redis / Cache check
    try:
        from eventlink.core.redis import CacheService
        cache = CacheService()
        # Try a simple set/get to verify cache works
        test_key = "__health_check__"
        await cache.set(test_key, "ok", ttl=10)
        result = await cache.get(test_key)
        if result == "ok":
            components["cache"] = {"status": "healthy", "backend": "redis" if cache._redis else "memory"}
        else:
            components["cache"] = {"status": "degraded", "backend": "memory", "note": "Redis unavailable, using memory fallback"}
        # Cleanup
        try:
            await cache.delete(test_key)
        except Exception:
            pass
    except Exception as e:
        components["cache"] = {"status": "degraded", "backend": "memory", "error": str(e)}

    # 3. LLM API check (lightweight — just verify config exists)
    try:
        from eventlink.config import get_settings
        settings = get_settings()
        if settings.llm_api_key and settings.llm_base_url:
            components["llm"] = {
                "status": "configured",
                "base_url": settings.llm_base_url,
                "model": settings.llm_model,
            }
        else:
            components["llm"] = {"status": "not_configured", "note": "LLM API key or base URL not set"}
            overall_healthy = False
    except Exception as e:
        components["llm"] = {"status": "error", "error": str(e)}
        overall_healthy = False

    return {
        "status": "healthy" if overall_healthy else "degraded",
        "timestamp": datetime.now(UTC).isoformat(),
        "service": "eventlink",
        "version": "0.3.0",
        "components": components,
    }

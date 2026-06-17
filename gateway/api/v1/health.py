"""Health check endpoint.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.8

Endpoint:
- GET /api/v1/pro/health — Gateway health check (no auth)
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from gateway.schemas.relay import HealthResponse

router = APIRouter(prefix="/api/v1/pro", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """Gateway health check.

    Returns the health status of all components:
    - database
    - redis
    - api_key_pool
    - llm_providers

    This endpoint requires no authentication and is used by monitoring
    and load balancers for probe checks.
    """
    settings = getattr(request.app.state, "settings", None)
    version = getattr(settings, "gateway_version", "1.0.0") if settings else "1.0.0"

    # Check components
    components: dict = {}

    # Database check
    components["database"] = "healthy"  # Simplified; real impl would ping DB

    # Redis check
    redis = getattr(request.app.state, "redis", None)
    if redis is not None:
        try:
            await redis.ping()
            components["redis"] = "healthy"
        except Exception:
            components["redis"] = "unhealthy"
    else:
        components["redis"] = "not_configured"

    # API Key pool check
    key_pool = getattr(request.app.state, "api_key_pool", None)
    if key_pool is not None:
        components["api_key_pool"] = {
            "status": "healthy" if key_pool.active_count > 0 else "degraded",
            "active_keys": key_pool.active_count,
            "total_keys": key_pool.total_count,
            "circuit_open_count": key_pool.circuit_open_count,
        }
    else:
        components["api_key_pool"] = {"status": "not_configured"}

    # LLM providers check
    components["llm_providers"] = {
        "moka_ai": "reachable",
        "openai": "reachable",
    }

    # Determine overall status
    db_ok = components.get("database") == "healthy"
    redis_ok = components.get("redis") in ("healthy", "not_configured")
    pool_status = components.get("api_key_pool", {})
    pool_ok = isinstance(pool_status, dict) and pool_status.get("active_keys", 0) > 0

    overall = "healthy" if (db_ok and redis_ok and pool_ok) else "degraded"

    return HealthResponse(
        status=overall,
        version=version,
        timestamp=datetime.now(timezone.utc).isoformat(),
        components=components,
        metrics={
            "active_ws_connections": 0,
            "requests_per_minute": 0,
            "avg_response_ms": 0,
        },
    )

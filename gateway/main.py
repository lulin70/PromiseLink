"""FastAPI application entry point for PromiseLink Cloud AI Gateway.

Reference: Pro_Edition_Tech_Design_Phase0.md §2.1, §4, §8

Creates the FastAPI app, registers routes, middleware, exception handlers,
and startup/shutdown events.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from gateway.api.v1.health import router as health_router
from gateway.api.v1.license import router as license_router
from gateway.api.v1.relay import router as relay_router
from gateway.api.v1.usage import router as usage_router
from gateway.config import Settings, get_settings
from gateway.core.exceptions import GatewayError
from gateway.core.jwt_handler import JWTHandler
from gateway.middleware.audit_log import AuditLogMiddleware
from gateway.middleware.rate_limit import RateLimitMiddleware
from gateway.middleware.request_id import RequestIDMiddleware
from gateway.models.redis_client import InMemoryRedis
from gateway.services.api_key_pool import APIKeyPool, create_default_key_pool
from gateway.services.billing_service import BillingService
from gateway.services.license_service import LicenseService
from gateway.services.relay_service import RelayService

logger = logging.getLogger("gateway")


def create_app(
    settings: Settings | None = None,
    *,
    api_key_pool: APIKeyPool | None = None,
    license_service: LicenseService | None = None,
    billing_service: BillingService | None = None,
    relay_service: RelayService | None = None,
    redis_client: Any = None,
    jwt_handler: JWTHandler | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    All services can be injected for testing. If not provided, default
    implementations are created from settings.

    Args:
        settings: Gateway settings (loaded from env if None).
        api_key_pool: API key pool (default created if None).
        license_service: License service (default created if None).
        billing_service: Billing service (default created if None).
        relay_service: Relay service (default created if None).
        redis_client: Redis client (in-memory if None).
        jwt_handler: JWT handler (default created if None).

    Returns:
        Configured FastAPI application instance.
    """
    s = settings or get_settings()

    # Initialize services
    jwt_handler = jwt_handler or JWTHandler(s)
    api_key_pool = api_key_pool or create_default_key_pool(s)

    # Share license store between license and billing services
    license_store: dict = {}
    license_service = license_service or LicenseService(jwt_handler=jwt_handler, settings=s, licenses=license_store)
    billing_service = billing_service or BillingService(settings=s, licenses=license_store)
    # Ensure billing service shares the same license store
    billing_service.set_licenses(license_service._licenses)

    relay_service = relay_service or RelayService(
        api_key_pool=api_key_pool,
        billing_service=billing_service,
        settings=s,
    )

    redis = redis_client or InMemoryRedis()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Application lifespan: startup and shutdown."""
        # Startup
        app.state.settings = s
        app.state.jwt_handler = jwt_handler
        app.state.api_key_pool = api_key_pool
        app.state.license_service = license_service
        app.state.billing_service = billing_service
        app.state.relay_service = relay_service
        app.state.redis = redis
        logger.info("Gateway started (env=%s, version=%s)", s.gateway_env, s.gateway_version)
        yield
        # Shutdown
        if hasattr(redis, "close"):
            await redis.close()
        logger.info("Gateway stopped")

    app = FastAPI(
        title="PromiseLink Cloud AI Gateway",
        description="Cloud AI Gateway for PromiseLink Pro Edition — LLM/ASR/TTS/OCR relay",
        version=s.gateway_version,
        lifespan=lifespan,
    )

    # ── Middleware (order: outermost first) ──
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if not s.is_production else ["https://promiselink.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(AuditLogMiddleware)
    app.add_middleware(RateLimitMiddleware, settings=s)
    app.add_middleware(RequestIDMiddleware)

    # ── Routes ──
    app.include_router(health_router)
    app.include_router(license_router)
    app.include_router(usage_router)
    app.include_router(relay_router)

    # ── Exception handlers ──

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
        """Handle all GatewayError subclasses uniformly."""
        request_id = getattr(request.state, "request_id", "")
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details or None,
                },
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        request_id = getattr(request.state, "request_id", "")
        logger.exception("Unhandled exception: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "request_id": request_id,
                "success": False,
                "data": None,
                "error": {
                    "code": "GATEWAY_INTERNAL_ERROR",
                    "message": "Internal server error",
                    "details": None,
                },
            },
        )

    return app


# Default app instance for uvicorn
app = create_app()

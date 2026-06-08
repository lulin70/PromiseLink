"""FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from eventlink.api.v1 import associations, auth, dashboard, demand_input, email_sync, entities, events, export, health, import_csv, media, privacy, relationship_briefs, todos, voice, voice_query, wechat_forward
from eventlink.config import get_settings
from eventlink.core.exceptions import BusinessError, EventLinkError, LLMError
from eventlink.database import close_db, init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    print("🚀 EventLink starting up...")
    await init_db()
    print("✅ Database initialized")

    yield

    # Shutdown
    print("🛑 EventLink shutting down...")
    from eventlink.core.redis import close_redis
    await close_redis()
    await close_db()
    print("✅ Database connections closed")


app = FastAPI(
    title=settings.app_name,
    description="AI驱动的个人商务关系经营助手",
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.api_prefix}/openapi.json",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── Exception Handlers ──


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    """Handle business logic errors with structured error response."""
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError):
    """Handle LLM-related errors."""
    status_code = 503  # Service Unavailable
    if exc.code == "LLM_RATE_LIMIT":
        status_code = 429
    elif exc.code == "LLM_TIMEOUT":
        status_code = 504
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(EventLinkError)
async def eventlink_error_handler(request: Request, exc: EventLinkError):
    """Handle all other EventLink errors."""
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            }
        },
    )


@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors."""
    return JSONResponse(
        status_code=404,
        content={"error": {"code": "NOT_FOUND", "message": "Resource not found"}},
    )


@app.exception_handler(500)
async def internal_error_handler(request, exc):
    """Handle 500 errors."""
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "Internal server error"}},
    )


# Include routers
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(auth.router, prefix=settings.api_prefix, tags=["Auth"])
app.include_router(events.router, prefix=settings.api_prefix, tags=["Events"])
app.include_router(entities.router, prefix=settings.api_prefix, tags=["Entities"])
app.include_router(associations.router, prefix=settings.api_prefix, tags=["Associations"])
app.include_router(todos.router, prefix=settings.api_prefix, tags=["Todos"])
app.include_router(dashboard.router, prefix=settings.api_prefix, tags=["Dashboard"])
app.include_router(relationship_briefs.router, prefix=settings.api_prefix, tags=["RelationshipBriefs"])
app.include_router(voice.router, prefix=settings.api_prefix, tags=["Voice"])
app.include_router(voice_query.router, prefix=settings.api_prefix, tags=["Voice"])
app.include_router(demand_input.router, prefix=settings.api_prefix, tags=["DemandInput"])
app.include_router(export.router, prefix=settings.api_prefix, tags=["Export"])
app.include_router(import_csv.router, prefix=settings.api_prefix, tags=["Import"])
app.include_router(email_sync.router, prefix=settings.api_prefix, tags=["Email"])
app.include_router(wechat_forward.router, prefix=settings.api_prefix, tags=["WeChatForward"])
app.include_router(media.router, prefix=settings.api_prefix, tags=["Media"])
app.include_router(privacy.router, prefix=settings.api_prefix, tags=["Privacy"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "eventlink.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )

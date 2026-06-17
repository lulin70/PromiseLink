"""FastAPI application entry point."""

import asyncio
import signal
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from promiselink.api.v1 import (
    associations,
    auth,
    dashboard,
    demand_input,
    entities,
    events,
    export,
    health,
    promises,
    relationship_briefs,
    reminders,
    scheduled_events,
    todos,
)
from promiselink.config import get_settings
from promiselink.core.exceptions import BusinessError, LLMError, PromiseLinkError
from promiselink.database import close_db, init_db

settings = get_settings()

# Graceful shutdown state
_shutdown_event = asyncio.Event()
_pending_tasks: set[asyncio.Task] = set()


async def _scheduled_event_maintenance():
    """Background task: periodically mark overdue scheduled events and cleanup cancelled ones.

    Runs every 5 minutes. First run after 30 seconds delay.
    """
    import structlog
    logger = structlog.get_logger()

    # Initial delay to let app fully start
    await asyncio.sleep(30)

    while not _shutdown_event.is_set():
        try:
            from promiselink.api.v1.scheduled_events import (
                cleanup_cancelled_scheduled_events,
                mark_overdue_scheduled_events,
            )
            from promiselink.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                overdue_count = await mark_overdue_scheduled_events(session)
                cleaned_count = await cleanup_cancelled_scheduled_events(session)

                if overdue_count > 0 or cleaned_count > 0:
                    logger.info(
                        "scheduled_event_maintenance",
                        overdue_marked=overdue_count,
                        cancelled_cleaned=cleaned_count,
                    )

        except Exception as e:
            logger.error("scheduled_event_maintenance_error", error=str(e))

        # Wait 5 minutes or until shutdown
        try:
            await asyncio.wait_for(_shutdown_event.wait(), timeout=300)
            break  # Shutdown requested
        except TimeoutError:
            pass  # Normal: continue loop


def _track_task(task: asyncio.Task):
    """Track background tasks for graceful shutdown."""
    _pending_tasks.add(task)
    task.add_done_callback(_pending_tasks.discard)


def _signal_handler(signum, frame):
    """Handle SIGTERM/SIGINT for graceful shutdown."""
    import structlog
    logger = structlog.get_logger()
    logger.info("shutdown_signal_received", signal=signum, pending_tasks=len(_pending_tasks))
    _shutdown_event.set()


# Register signal handlers
signal.signal(signal.SIGTERM, _signal_handler)
signal.signal(signal.SIGINT, _signal_handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with graceful shutdown."""
    # Startup
    import structlog
    logger = structlog.get_logger()
    logger.info("promiselink_starting")
    logger.info("PromiseLink v0.5.4 — AGPL v3. Commercial use requires compliance. https://promiselink.app")

    # Check for default secret key
    if settings.secret_key == "change-me-in-production" and settings.app_env != "test":
        if settings.allow_insecure_key:
            logger.warning(
                "DEFAULT SECRET KEY DETECTED",
                note="Secret key is still the default value 'change-me-in-production'. "
                     "Set SECRET_KEY env var immediately. This is insecure for any deployment.",
            )
        else:
            logger.critical(
                "INSECURE DEFAULT SECRET KEY - STARTUP BLOCKED",
                note="Secret key is still the default value 'change-me-in-production'. "
                     "Set SECRET_KEY env var or set ALLOW_INSECURE_KEY=true for development.",
            )
            raise SystemExit(1)

    await init_db()
    logger.info("database_initialized")

    # Start scheduled event background tasks (overdue marking + cancelled cleanup)
    _se_task = asyncio.create_task(_scheduled_event_maintenance())
    _pending_tasks.add(_se_task)
    _se_task.add_done_callback(_pending_tasks.discard)

    yield

    # Shutdown — drain pending tasks
    logger.info("promiselink_shutting_down", pending_tasks=len(_pending_tasks))

    if _pending_tasks:
        logger.info("waiting_for_pending_tasks", count=len(_pending_tasks))
        # Wait up to 30 seconds for pending tasks to complete
        try:
            done, pending = await asyncio.wait(
                _pending_tasks, timeout=30.0
            )
            if pending:
                logger.warning(
                    "cancelling_pending_tasks",
                    cancelled_count=len(pending),
                )
                for task in pending:
                    task.cancel()
                # Wait for cancellation to propagate
                await asyncio.gather(*pending, return_exceptions=True)
        except Exception as e:
            logger.error("shutdown_task_error", error=str(e))

    from promiselink.core.redis import close_redis
    await close_redis()

    # Close shared LLM httpx client
    from promiselink.services.llm_client import close_shared_client
    await close_shared_client()

    await close_db()
    logger.info("shutdown_complete")


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
_cors_origins = settings.cors_origins
if _cors_origins == ["*"]:
    import structlog as _structlog
    _structlog.get_logger().warning(
        "CORS_ALLOW_ORIGINS_WILDCARD",
        note="cors_origins is set to '*' which allows all origins. "
             "This is insecure for production. Set CORS_ORIGINS to specific domains.",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)


# ── X-Powered-By Header Middleware ──

@app.middleware("http")
async def add_powered_by_header(request: Request, call_next):
    """Add X-Powered-By: PromiseLink to all HTTP responses."""
    response = await call_next(request)
    response.headers["X-Powered-By"] = "PromiseLink"
    return response


# ── Exception Handlers ──


# Map BusinessError subclass / code to HTTP status code
_BUSINESS_ERROR_STATUS: dict[str, int] = {
    "NOT_FOUND": 404,
    "VALIDATION_ERROR": 400,
    "BAD_REQUEST": 400,
    "FORBIDDEN": 403,
    "UNAUTHORIZED": 401,
    "CONFLICT": 409,
    "RATE_LIMITED": 429,
    "BAD_GATEWAY": 502,
    "SERVICE_UNAVAILABLE": 503,
    "ENTITY_NOT_FOUND": 404,
    "INVALID_TODO_TYPE": 400,
    "DUPLICATE_ENTITY": 409,
    "INVALID_TRANSITION": 400,
    "SENSITIVITY_VIOLATION": 403,
}


@app.exception_handler(BusinessError)
async def business_error_handler(request: Request, exc: BusinessError):
    """Handle business logic errors with structured error response."""
    status_code = _BUSINESS_ERROR_STATUS.get(exc.code, 400)
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


@app.exception_handler(PromiseLinkError)
async def promiselink_error_handler(request: Request, exc: PromiseLinkError):
    """Handle all other PromiseLink errors."""
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


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    """Handle request validation errors with standard error format."""
    # Sanitize errors: convert bytes to str to avoid JSON serialization TypeError
    safe_errors = []
    for err in exc.errors():
        safe_err = {}
        for k, v in err.items():
            if isinstance(v, bytes):
                safe_err[k] = v.decode("utf-8", errors="replace")
            elif isinstance(v, (list, dict)):
                safe_err[k] = _sanitize_bytes_recursive(v)
            else:
                safe_err[k] = v
        safe_errors.append(safe_err)
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "VALIDATION_ERROR", "message": str(exc), "details": safe_errors}},
    )


def _sanitize_bytes_recursive(obj):
    """Recursively convert bytes to str in nested structures."""
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, list):
        return [_sanitize_bytes_recursive(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_bytes_recursive(v) for k, v in obj.items()}
    return obj


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


# Include routers — Basic routes (always registered)
app.include_router(health.router, prefix=settings.api_prefix, tags=["Health"])
app.include_router(auth.router, prefix=settings.api_prefix, tags=["Auth"])
app.include_router(events.router, prefix=settings.api_prefix, tags=["Events"])
app.include_router(entities.router, prefix=settings.api_prefix, tags=["Entities"])
app.include_router(associations.router, prefix=settings.api_prefix, tags=["Associations"])
app.include_router(todos.router, prefix=settings.api_prefix, tags=["Todos"])
app.include_router(dashboard.router, prefix=settings.api_prefix, tags=["Dashboard"])
app.include_router(relationship_briefs.router, prefix=settings.api_prefix, tags=["RelationshipBriefs"])
app.include_router(demand_input.router, prefix=settings.api_prefix, tags=["DemandInput"])
app.include_router(export.router, prefix=settings.api_prefix, tags=["Export"])
app.include_router(promises.router, prefix=settings.api_prefix, tags=["Promises"])
app.include_router(reminders.router, prefix=settings.api_prefix, tags=["Reminders"])
app.include_router(scheduled_events.router, prefix=settings.api_prefix, tags=["ScheduledEvents"])

# Pro-only routes (only registered when app_edition == "pro")
if settings.app_edition == "pro":
    from promiselink.api.v1 import (
        email_sync,
        import_csv,
        media,
        privacy,
        voice,
        voice_query,
        wechat_forward,
    )
    app.include_router(voice.router, prefix=settings.api_prefix, tags=["Voice"])
    app.include_router(voice_query.router, prefix=settings.api_prefix, tags=["VoiceQuery"])
    app.include_router(media.router, prefix=settings.api_prefix, tags=["Media"])
    app.include_router(email_sync.router, prefix=settings.api_prefix, tags=["EmailSync"])
    app.include_router(wechat_forward.router, prefix=settings.api_prefix, tags=["WeChatForward"])
    app.include_router(import_csv.router, prefix=settings.api_prefix, tags=["ImportCSV"])
    app.include_router(privacy.router, prefix=settings.api_prefix, tags=["Privacy"])


# ── Static Files (H5 Frontend) ──
# Mount AFTER API routes so /api/v1/* takes priority.
# Docker: /app/static | Local: ./frontend/dist
STATIC_DIR = None
for candidate in [Path("/app/static"), Path(__file__).parent.parent.parent / "frontend" / "dist"]:
    if candidate.is_dir() and (candidate / "index.html").exists():
        STATIC_DIR = candidate
        break

if STATIC_DIR:
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
else:
    import sys
    print("[PromiseLink] WARNING: Frontend static files not found. Run 'cd frontend && npm run build:h5'", file=sys.stderr)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "promiselink.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )

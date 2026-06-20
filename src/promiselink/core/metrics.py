"""Prometheus metrics definitions and middleware for PromiseLink.

Exposes standard HTTP request metrics (counter + histogram) and application-level
gauges that align with the alerting rules in monitoring/alerts.yml.

Metrics exposed at /api/v1/metrics (Prometheus text format).
"""

import time
from typing import Any

from fastapi import Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from promiselink.config import get_settings

# Use a dedicated registry to avoid duplicate metric errors in tests
REGISTRY = CollectorRegistry()

# ── HTTP request metrics (align with monitoring/alerts.yml) ──

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
    registry=REGISTRY,
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ── Application-level metrics ──

promiselink_info = Gauge(
    "promiselink_info",
    "PromiseLink application info",
    ["version", "edition"],
    registry=REGISTRY,
)

event_processing_total = Counter(
    "event_processing_total",
    "Total events processed through the pipeline",
    ["status"],  # status: success, error, partial
    registry=REGISTRY,
)

event_processing_duration_seconds = Histogram(
    "event_processing_duration_seconds",
    "Event pipeline processing duration in seconds",
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0),
    registry=REGISTRY,
)

active_sessions = Gauge(
    "promiselink_active_sessions",
    "Number of active user sessions",
    registry=REGISTRY,
)


def init_app_metrics() -> None:
    """Initialize application-level gauge with current version/edition.

    Call once at application startup to populate promiselink_info.
    """
    settings = get_settings()
    promiselink_info.labels(
        version=settings.app_version,
        edition=settings.app_edition,
    ).set(1)


async def metrics_middleware(request: Request, call_next: Any) -> Response:
    """FastAPI middleware: record HTTP request count and duration.

    Usage in main.py:
        app.middleware("http")(metrics_middleware)

    Args:
        request: FastAPI Request object.
        call_next: Next middleware/endpoint callable.

    Returns:
        Response from downstream handler.
    """
    start_time = time.perf_counter()

    # Extract route path for label stability (avoid high-cardinality URL paths)
    endpoint = request.url.path
    method = request.method

    try:
        response: Response = await call_next(request)
        status = str(response.status_code)
    except Exception:
        status = "500"
        # Re-raise after recording the error metric
        duration = time.perf_counter() - start_time
        http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        http_request_duration_seconds.labels(
            method=method, endpoint=endpoint, status=status
        ).observe(duration)
        raise

    duration = time.perf_counter() - start_time
    http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
    http_request_duration_seconds.labels(
        method=method, endpoint=endpoint, status=status
    ).observe(duration)

    return response


def generate_metrics() -> tuple[bytes, str]:
    """Generate Prometheus-format metrics payload.

    Returns:
        Tuple of (metrics_bytes, content_type).
    """
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def record_event_processing(duration_seconds: float, status: str = "success") -> None:
    """Record an event pipeline processing result.

    Args:
        duration_seconds: Processing time in seconds.
        status: One of "success", "error", "partial".
    """
    event_processing_total.labels(status=status).inc()
    event_processing_duration_seconds.observe(duration_seconds)

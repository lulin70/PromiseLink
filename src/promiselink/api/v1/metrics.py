"""Prometheus metrics endpoint for PromiseLink.

Exposes application metrics in Prometheus text format at /api/v1/metrics.
This endpoint is unauthenticated (like /health) to allow Prometheus scraping.
"""

from fastapi import APIRouter, Response

from promiselink.core.metrics import generate_metrics

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    """Prometheus metrics endpoint (unauthenticated, for scraping).

    Returns application metrics in Prometheus text exposition format,
    including HTTP request counters, histograms, and application gauges.

    Aligns with monitoring/prometheus.yml scrape config and
    monitoring/alerts.yml alerting rules.
    """
    payload, content_type = generate_metrics()
    return Response(content=payload, media_type=content_type)

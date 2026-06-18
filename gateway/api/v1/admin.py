"""Admin monitoring API endpoints.

Endpoints:
- POST /api/v1/admin/token — Obtain an admin JWT (requires X-Admin-API-Key + passphrase)
- GET /api/v1/admin/usage/summary — Global usage overview
- GET /api/v1/admin/usage/users — Paginated user usage list
- GET /api/v1/admin/usage/users/{license_key} — Single user usage detail
- GET /api/v1/admin/usage/export — Export usage as CSV
- GET /api/v1/admin/health — Gateway health (provider key pool status)

Authentication: Two-factor (X-Admin-API-Key header + admin JWT Bearer token).
The admin JWT is obtained via POST /api/v1/admin/token by presenting the
admin API key and the admin passphrase.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import UTC, datetime
from typing import Any

import jwt as pyjwt
from fastapi import APIRouter, Depends, Query, Request, Security
from fastapi.responses import StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field

from gateway.config import Settings, get_settings
from gateway.core.exceptions import APIKeyInvalidError, LicenseNotFound, PermissionDeniedError
from gateway.middleware.auth import _constant_time_compare, verify_admin
from gateway.models.tables import License, UsageRecord
from gateway.schemas.errors import UnifiedResponse
from gateway.services.billing_service import BillingService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# Security scheme for OpenAPI docs (used by the token endpoint)
_admin_api_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)

# Traffic-light thresholds (must match usage_service.py)
_YELLOW_THRESHOLD = 0.80
_RED_THRESHOLD = 1.00

# Admin JWT constants (must match middleware/auth.py verify_admin)
_ADMIN_JWT_ISSUER = "promiselink-gateway-admin"
_ADMIN_JWT_AUDIENCE = "promiselink-admin-client"


# ── Request models ─────────────────────────────────────────────────


class AdminTokenRequest(BaseModel):
    """Request body for POST /api/v1/admin/token."""

    passphrase: str = Field(..., description="Admin passphrase (second factor)")


# ── Service accessors ───────────────────────────────────────────────


def get_billing_service(request: Request) -> BillingService:
    """Get the BillingService from app state."""
    service: BillingService | None = getattr(request.app.state, "billing_service", None)
    if service is None:
        raise RuntimeError("BillingService not initialized")
    return service


# ── Admin token endpoint (B1: two-factor auth) ──────────────────────


@router.post("/token")
async def admin_token(
    request: Request,
    body: AdminTokenRequest,
    admin_api_key: str | None = Security(_admin_api_key_header),
) -> UnifiedResponse[dict[str, Any]]:
    """Obtain an admin JWT by presenting the admin API key + passphrase.

    This is the first step of the two-factor admin authentication flow:
    1. POST /api/v1/admin/token with X-Admin-API-Key + passphrase → admin JWT
    2. Use the admin JWT (Bearer) + X-Admin-API-Key for all other admin endpoints

    Factor 1: X-Admin-API-Key header (something you have)
    Factor 2: admin passphrase in the request body (something you know)
    """
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()

    # Factor 1: Admin API Key
    if not admin_api_key:
        raise APIKeyInvalidError("X-Admin-API-Key header is missing")
    if not _constant_time_compare(admin_api_key, settings.admin_api_key):
        raise APIKeyInvalidError("Invalid admin API key")

    # Factor 2: Admin passphrase
    if not _constant_time_compare(body.passphrase, settings.admin_passphrase):
        raise PermissionDeniedError("Invalid admin passphrase")

    # Issue admin JWT (HS256, signed with admin_jwt_secret)
    now = int(time.time())
    payload = {
        "admin_id": settings.admin_id,
        "role": "admin",
        "iat": now,
        "exp": now + settings.admin_jwt_ttl,
        "iss": _ADMIN_JWT_ISSUER,
        "aud": _ADMIN_JWT_AUDIENCE,
    }
    token = pyjwt.encode(payload, settings.admin_jwt_secret, algorithm="HS256")

    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data={
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": settings.admin_jwt_ttl,
        },
    )


# ── Helpers ─────────────────────────────────────────────────────────


def _compute_traffic_light(used: int, limit: int) -> str:
    """Compute traffic-light colour from usage and limit.

    * green  — usage < 80% of limit
    * yellow — 80% ≤ usage < 100%
    * red    — usage ≥ 100% (or limit ≤ 0)
    """
    if limit <= 0:
        return "red"
    ratio = used / limit
    if ratio >= _RED_THRESHOLD:
        return "red"
    if ratio >= _YELLOW_THRESHOLD:
        return "yellow"
    return "green"


def _build_user_usage_row(lic: License, records: list[UsageRecord]) -> dict[str, Any]:
    """Build a usage summary dict for a single license."""
    llm_calls = sum(1 for r in records if r.request_type == "llm")
    asr_calls = sum(1 for r in records if r.request_type == "asr")
    tts_calls = sum(1 for r in records if r.request_type == "tts")
    ocr_calls = sum(1 for r in records if r.request_type == "ocr")
    total_calls = len(records)
    traffic_light = _compute_traffic_light(
        lic.quota_used_tokens, lic.quota_limit_tokens
    )
    return {
        "license_key": lic.license_key,
        "user_id": lic.user_id or "",
        "plan_type": lic.plan_type,
        "status": lic.status,
        "quota_limit_tokens": lic.quota_limit_tokens,
        "quota_used_tokens": lic.quota_used_tokens,
        "quota_limit_asr": lic.quota_limit_asr,
        "quota_used_asr": lic.quota_used_asr,
        "quota_limit_tts": lic.quota_limit_tts,
        "quota_used_tts": lic.quota_used_tts,
        "quota_limit_ocr": lic.quota_limit_ocr,
        "quota_used_ocr": lic.quota_used_ocr,
        "llm_calls": llm_calls,
        "asr_calls": asr_calls,
        "tts_calls": tts_calls,
        "ocr_calls": ocr_calls,
        "total_calls": total_calls,
        "traffic_light": traffic_light,
    }


# ── Endpoints ───────────────────────────────────────────────────────


@router.get("/usage/summary")
async def usage_summary(
    request: Request,
    _admin: dict = Depends(verify_admin),
) -> UnifiedResponse[dict[str, Any]]:
    """Global usage overview.

    Returns total users, active users, total calls, today's calls,
    this month's calls, and per-service call counts.
    """
    billing = get_billing_service(request)
    licenses: list[License] = billing.get_all_licenses()
    records: list[UsageRecord] = billing.get_usage_records()

    total_users = len(licenses)
    active_users = sum(1 for lic in licenses if lic.status == "active")
    total_calls = len(records)

    # Per-service breakdown
    llm_calls = sum(1 for r in records if r.request_type == "llm")
    asr_calls = sum(1 for r in records if r.request_type == "asr")
    tts_calls = sum(1 for r in records if r.request_type == "tts")
    ocr_calls = sum(1 for r in records if r.request_type == "ocr")

    # Time-based counts
    now = datetime.now(UTC)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")
    today_calls = sum(
        1 for r in records
        if r.created_at is not None and r.created_at.strftime("%Y-%m-%d") == today_str
    )
    month_calls = sum(
        1 for r in records
        if r.created_at is not None and r.created_at.strftime("%Y-%m") == month_str
    )

    data = {
        "total_users": total_users,
        "active_users": active_users,
        "total_calls": total_calls,
        "today_calls": today_calls,
        "month_calls": month_calls,
        "service_breakdown": {
            "llm": llm_calls,
            "asr": asr_calls,
            "tts": tts_calls,
            "ocr": ocr_calls,
        },
    }
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=data,
    )


@router.get("/usage/users")
async def usage_users(
    request: Request,
    page: int = Query(default=1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Items per page"),
    sort_by: str = Query(
        default="total_calls",
        description="Sort field: total_calls|llm|asr|tts|ocr|tokens_used",
    ),
    order: str = Query(default="desc", description="Sort order: asc|desc"),
    _admin: dict = Depends(verify_admin),
) -> UnifiedResponse[dict[str, Any]]:
    """Paginated user usage list, sortable by call volume."""
    billing = get_billing_service(request)
    licenses: list[License] = billing.get_all_licenses()
    records: list[UsageRecord] = billing.get_usage_records()

    # Build per-user rows
    rows: list[dict[str, Any]] = []
    for lic in licenses:
        user_records = [r for r in records if r.license_key == lic.license_key]
        rows.append(_build_user_usage_row(lic, user_records))

    # Sort
    sort_field_map = {
        "total_calls": "total_calls",
        "llm": "llm_calls",
        "asr": "asr_calls",
        "tts": "tts_calls",
        "ocr": "ocr_calls",
        "tokens_used": "quota_used_tokens",
    }
    field = sort_field_map.get(sort_by, "total_calls")
    reverse = order == "desc"
    rows.sort(key=lambda r: r.get(field, 0), reverse=reverse)

    # Paginate
    total = len(rows)
    start = (page - 1) * page_size
    end = start + page_size
    page_rows = rows[start:end]

    data = {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
        "items": page_rows,
    }
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=data,
    )


@router.get("/usage/users/{license_key}")
async def usage_user_detail(
    request: Request,
    license_key: str,
    _admin: dict = Depends(verify_admin),
) -> UnifiedResponse[dict[str, Any]]:
    """Single user usage detail by license key."""
    billing = get_billing_service(request)
    lic: License | None = billing.get_license(license_key)
    if lic is None:
        raise LicenseNotFound(
            message=f"License not found: {license_key}",
            details={"license_key": license_key},
        )

    user_records: list[UsageRecord] = billing.get_usage_records(license_key)
    row = _build_user_usage_row(lic, user_records)

    # Add recent records (last 50)
    recent = sorted(user_records, key=lambda r: r.created_at, reverse=True)[:50]
    row["recent_records"] = [
        {
            "request_id": r.request_id,
            "request_type": r.request_type,
            "provider": r.provider,
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "total_tokens": r.total_tokens,
            "duration_ms": r.duration_ms,
            "cost_cny": float(r.cost_cny),
            "status_code": r.status_code,
            "success": r.success,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent
    ]

    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=row,
    )


@router.get("/usage/export")
async def usage_export(
    request: Request,
    _admin: dict = Depends(verify_admin),
) -> StreamingResponse:
    """Export all user usage as a CSV file."""
    billing = get_billing_service(request)
    licenses: list[License] = billing.get_all_licenses()
    records: list[UsageRecord] = billing.get_usage_records()

    rows: list[dict[str, Any]] = []
    for lic in licenses:
        user_records = [r for r in records if r.license_key == lic.license_key]
        rows.append(_build_user_usage_row(lic, user_records))

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "license_key", "user_id", "plan_type", "status",
        "quota_limit_tokens", "quota_used_tokens",
        "quota_limit_asr", "quota_used_asr",
        "quota_limit_tts", "quota_used_tts",
        "quota_limit_ocr", "quota_used_ocr",
        "llm_calls", "asr_calls", "tts_calls", "ocr_calls",
        "total_calls", "traffic_light",
    ])
    for row in rows:
        writer.writerow([
            row["license_key"], row["user_id"], row["plan_type"], row["status"],
            row["quota_limit_tokens"], row["quota_used_tokens"],
            row["quota_limit_asr"], row["quota_used_asr"],
            row["quota_limit_tts"], row["quota_used_tts"],
            row["quota_limit_ocr"], row["quota_used_ocr"],
            row["llm_calls"], row["asr_calls"], row["tts_calls"], row["ocr_calls"],
            row["total_calls"], row["traffic_light"],
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility
    filename = f"usage_export_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/health")
async def admin_health(
    request: Request,
    _admin: dict = Depends(verify_admin),
) -> UnifiedResponse[dict[str, Any]]:
    """Gateway health status — provider key pool status."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    key_pool = getattr(request.app.state, "api_key_pool", None)
    redis = getattr(request.app.state, "redis", None)

    # Key pool status
    if key_pool is not None:
        pool_status = key_pool.get_status()
        all_keys = key_pool.get_all_keys()
        providers = {}
        # Group keys by provider
        for key_info in all_keys:
            provider = key_info.provider
            if provider not in providers:
                providers[provider] = {
                    "total_keys": 0,
                    "active_keys": 0,
                    "circuit_open": 0,
                    "rate_limited": 0,
                    "avg_health": 0.0,
                }
            providers[provider]["total_keys"] += 1
            if key_info.status == "active":
                providers[provider]["active_keys"] += 1
            elif key_info.status == "circuit_open":
                providers[provider]["circuit_open"] += 1
            elif key_info.status == "rate_limited":
                providers[provider]["rate_limited"] += 1
        # Compute average health per provider
        for provider, info in providers.items():
            provider_keys = [k for k in all_keys if k.provider == provider]
            if provider_keys:
                info["avg_health"] = round(
                    sum(k.health_score for k in provider_keys) / len(provider_keys), 2
                )
        pool_detail = {
            "status": "healthy" if pool_status.get("active_keys", 0) > 0 else "degraded",
            "total_keys": pool_status.get("total_keys", 0),
            "active_keys": pool_status.get("active_keys", 0),
            "circuit_open_count": pool_status.get("circuit_open_count", 0),
            "providers": providers,
        }
    else:
        pool_detail = {"status": "not_configured"}

    # Redis status
    redis_status = "not_configured"
    if redis is not None:
        try:
            await redis.ping()
            redis_status = "healthy"
        except Exception:
            redis_status = "unhealthy"

    data = {
        "status": pool_detail.get("status", "degraded"),
        "version": getattr(settings, "gateway_version", "1.0.0"),
        "timestamp": datetime.now(UTC).isoformat(),
        "components": {
            "api_key_pool": pool_detail,
            "redis": redis_status,
            "database": "healthy",
        },
    }
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=data,
    )

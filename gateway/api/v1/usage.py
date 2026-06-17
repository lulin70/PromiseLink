"""Usage API endpoint.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.3

Endpoint:
- GET /api/v1/pro/usage — Query usage (relay_token)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from gateway.middleware.auth import get_license_key, get_user_id, verify_relay_token
from gateway.schemas.errors import UnifiedResponse
from gateway.schemas.usage import UsageResponse
from gateway.services.billing_service import BillingService

router = APIRouter(prefix="/api/v1/pro", tags=["usage"])


def get_billing_service(request: Request) -> BillingService:
    """Get the BillingService from app state."""
    service = getattr(request.app.state, "billing_service", None)
    if service is None:
        raise RuntimeError("BillingService not initialized")
    return service


@router.get("/usage", response_model=UnifiedResponse[UsageResponse])
async def get_usage(
    request: Request,
    month: str | None = Query(default=None, description="Month in YYYY-MM format"),
    detail: bool = Query(default=False, description="Include per-type breakdown"),
    jwt_payload: dict = Depends(verify_relay_token),
) -> UnifiedResponse[UsageResponse]:
    """Query usage for the current or specified month.

    Returns quota usage, traffic light status, cost, and history.
    """
    billing = get_billing_service(request)
    user_id = get_user_id(request)
    license_key = get_license_key(request)

    usage_data = billing.get_usage(user_id, license_key, month)
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=usage_data,
    )

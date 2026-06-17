"""License API endpoints.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.1-§4.3.2, §6.1-§6.3

Endpoints:
- POST /api/v1/pro/license/activate — Activate license (API Key + JWT)
- POST /api/v1/pro/license/verify — Verify license (relay_token)
- POST /api/v1/pro/license/refresh — Refresh relay_token
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from gateway.middleware.auth import verify_api_key, verify_relay_token
from gateway.schemas.errors import UnifiedResponse
from gateway.schemas.license import (
    LicenseActivateRequest,
    LicenseActivateResponse,
    LicenseRefreshRequest,
    LicenseVerifyRequest,
    LicenseVerifyResponse,
    RelayConfig,
    TokenPair,
)
from gateway.services.license_service import LicenseService

router = APIRouter(prefix="/api/v1/pro/license", tags=["license"])


def get_license_service(request: Request) -> LicenseService:
    """Get the LicenseService from app state."""
    service = getattr(request.app.state, "license_service", None)
    if service is None:
        raise RuntimeError("LicenseService not initialized")
    return service


@router.post("/activate", response_model=UnifiedResponse[LicenseActivateResponse])
async def activate_license(
    request: Request,
    body: LicenseActivateRequest,
    _api_key: str = Depends(verify_api_key),
    jwt_payload: dict = Depends(verify_relay_token),
) -> UnifiedResponse[LicenseActivateResponse]:
    """Activate a license.

    Requires both API Key (X-API-Key) and user JWT (Authorization: Bearer).
    The user_id is extracted from the JWT, NOT from the request body (P0-5).

    Flow (§6.1):
    1. Verify user JWT and extract user_id
    2. Validate license_key and device_fingerprint format
    3. Query license from database
    4. Check license status (active/expired/cancelled)
    5. Check user binding (anti-hijack: first binding is permanent)
    6. Check device binding
    7. Bind user + device, set status=active
    8. Issue relay JWT (access_token + refresh_token)
    9. Return license info + tokens + relay config
    """
    service = get_license_service(request)
    # user_id from JWT (P0-5: not from request body)
    user_id = jwt_payload.get("user_id", "")

    result = await service.activate_license(
        license_key=body.license_key,
        user_id=user_id,
        device_fingerprint=body.device_fingerprint,
    )

    response_data = LicenseActivateResponse(
        license=result["license"],  # type: ignore[arg-type]
        tokens=result["tokens"],  # type: ignore[arg-type]
        relay_config=RelayConfig(),
    )
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=response_data,
    )


@router.post("/verify", response_model=UnifiedResponse[LicenseVerifyResponse])
async def verify_license(
    request: Request,
    body: LicenseVerifyRequest,
    jwt_payload: dict = Depends(verify_relay_token),
) -> UnifiedResponse[LicenseVerifyResponse]:
    """Verify a license and optionally refresh the relay token.

    Requires relay_token (JWT). If the token expires in < 5 minutes,
    a new access_token is issued (silent refresh, §6.3).
    """
    service = get_license_service(request)
    result = await service.verify_license(
        token_payload=jwt_payload,
        device_fingerprint=body.device_fingerprint,
    )
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=result,
    )


@router.post("/refresh", response_model=UnifiedResponse[TokenPair])
async def refresh_token(
    request: Request,
    body: LicenseRefreshRequest,
    _api_key: str = Depends(verify_api_key),
) -> UnifiedResponse[TokenPair]:
    """Refresh an access token using a refresh token.

    Requires API Key. The refresh_token is provided in the request body.
    """
    service = get_license_service(request)
    result = await service.refresh_token(body.refresh_token)
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=result,
    )

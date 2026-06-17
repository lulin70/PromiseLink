"""Authentication middleware and dependencies.

Provides FastAPI dependency functions for verifying API keys, relay JWT
tokens, and admin credentials.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.1.2, §6.5
"""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from gateway.config import Settings, get_settings
from gateway.core.exceptions import (
    APIKeyInvalidError,
    JWTExpiredError,
    JWTInvalidError,
    JWTMissingError,
    JWTRevokedError,
    PermissionDeniedError,
)
from gateway.core.jwt_handler import JWTHandler

# Security schemes for OpenAPI docs
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)
admin_api_key_header = APIKeyHeader(name="X-Admin-API-Key", auto_error=False)


def _constant_time_compare(a: str, b: str) -> bool:
    """Compare two strings in constant time to prevent timing attacks."""
    return hmac.compare_digest(a.encode(), b.encode())


async def verify_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> str:
    """Verify the X-API-Key header.

    Used by the license activation endpoint (alongside user JWT).

    Raises:
        APIKeyInvalidError: If the API key is missing or invalid.
    """
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    if not api_key:
        raise APIKeyInvalidError("X-API-Key header is missing")
    if not _constant_time_compare(api_key, settings.api_key):
        raise APIKeyInvalidError("Invalid API key")
    return api_key


async def verify_relay_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict[str, Any]:
    """Verify the relay JWT (Bearer token).

    Used by all relay, usage, and license verify endpoints. Extracts the
    JWT payload and injects user_id / license_key into request.state.

    Raises:
        JWTMissingError: If Authorization header is missing.
        JWTInvalidError: If JWT signature is invalid.
        JWTExpiredError: If JWT has expired.
        JWTRevokedError: If JWT is in the CRL blacklist.
    """
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()
    jwt_handler: JWTHandler = getattr(request.app.state, "jwt_handler", None) or JWTHandler(settings)

    if credentials is None or not credentials.credentials:
        raise JWTMissingError("Authorization Bearer token is required")

    token = credentials.credentials
    payload = jwt_handler.verify_token(token, expected_type="access")

    # Check CRL blacklist (Redis)
    jti = payload.get("jti", "")
    if jti:
        redis = getattr(request.app.state, "redis", None)
        if redis is not None:
            is_revoked = await redis.exists(f"jwt_blacklist:{jti}")
            if is_revoked:
                raise JWTRevokedError("JWT has been revoked")

    # Inject into request state for downstream handlers
    request.state.user_id = payload.get("user_id", "")
    request.state.license_key = payload.get("license_key", "")
    request.state.device_fingerprint = payload.get("device_fingerprint", "")
    request.state.jwt_payload = payload

    return payload


async def verify_admin(
    request: Request,
    admin_api_key: str | None = Security(admin_api_key_header),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> dict[str, Any]:
    """Verify admin credentials (double factor: admin API key + admin JWT).

    Reference: §6.5 Admin Authentication

    Raises:
        APIKeyInvalidError: If admin API key is missing/invalid.
        JWTInvalidError: If admin JWT is invalid.
        PermissionDeniedError: If JWT is not an admin token.
    """
    settings: Settings = getattr(request.app.state, "settings", None) or get_settings()

    # Factor 1: Admin API Key
    if not admin_api_key:
        raise APIKeyInvalidError("X-Admin-API-Key header is missing")
    if not _constant_time_compare(admin_api_key, settings.admin_api_key):
        raise APIKeyInvalidError("Invalid admin API key")

    # Factor 2: Admin JWT
    if credentials is None or not credentials.credentials:
        raise JWTMissingError("Admin Authorization Bearer token is required")

    # Verify admin JWT with admin secret
    import jwt as pyjwt

    try:
        payload = pyjwt.decode(
            credentials.credentials,
            settings.admin_jwt_secret,
            algorithms=["HS256"],
            issuer="promiselink-gateway-admin",
            audience="promiselink-admin-client",
        )
    except pyjwt.ExpiredSignatureError as exc:
        raise JWTExpiredError("Admin JWT has expired") from exc
    except pyjwt.InvalidTokenError as exc:
        raise JWTInvalidError(f"Invalid admin JWT: {exc}") from exc

    if payload.get("role") != "admin":
        raise PermissionDeniedError("JWT does not have admin role")

    request.state.admin_id = payload.get("admin_id", "")
    request.state.is_admin = True

    return payload


def get_user_id(request: Request) -> str:
    """Extract user_id from request state (set by verify_relay_token)."""
    return getattr(request.state, "user_id", "")


def get_license_key(request: Request) -> str:
    """Extract license_key from request state (set by verify_relay_token)."""
    return getattr(request.state, "license_key", "")

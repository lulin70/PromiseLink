"""JWT authentication and authorization utilities."""

import os
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from promiselink.config import get_settings

security = HTTPBearer(auto_error=False)

# Allowed IPs for poc_anonymous_access (default: localhost only)
_POC_ALLOWED_IPS = {"127.0.0.1", "::1"}


def _get_client_ip(request: Request) -> str:
    """Get client IP, ignoring X-Forwarded-For unless trusted proxies configured."""
    # Direct connection IP is always reliable
    direct_ip = request.client.host if request.client else "unknown"

    # Only trust X-Forwarded-For if trusted proxies are configured
    # and the direct connection is from a trusted proxy
    settings = get_settings()
    if settings.trusted_proxies and direct_ip in settings.trusted_proxies:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()

    return direct_ip


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> str:
    """Extract and validate user_id from JWT token. Raises 401 if invalid."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    payload = verify_token(token)
    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


async def get_optional_user_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str | None:
    """Extract user_id from JWT token.

    Returns None if no valid token. Callers must handle None appropriately.
    For PoC compatibility, set PROMISELINK_POC_ANONYMOUS_ACCESS=true to allow
    a default user ID when no token is provided.

    Security: When poc_anonymous_access is enabled:
    - Only allowed from configured IPs (default: localhost)
    - Every access is logged with client IP and timestamp
    - Set POC_ALLOWED_IPS env var to customize (comma-separated)
    """
    if credentials is None:
        settings = get_settings()
        if settings.poc_anonymous_access:
            import structlog
            logger = structlog.get_logger()

            # IP whitelist check
            client_ip = _get_client_ip(request)
            allowed_ips = set(os.environ.get("POC_ALLOWED_IPS", "127.0.0.1,::1").split(","))

            if client_ip not in allowed_ips:
                logger.error(
                    "poc_anonymous_access_blocked",
                    client_ip=client_ip,
                    allowed_ips=list(allowed_ips),
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Anonymous access not allowed from IP: {client_ip}",
                )

            # Audit log with prominent warning
            logger.warning(
                "poc_anonymous_access_used",
                client_ip=client_ip,
                user_id="00000000-0000-0000-0000-000000000001",
                _emoji="⚠️",
                _message="INSECURE: poc_anonymous_access is enabled! Disable in production!",
            )
            return "00000000-0000-0000-0000-000000000001"
        return None

    token = credentials.credentials
    try:
        payload = verify_token(token)
    except HTTPException:
        return None
    user_id: str | None = payload.get("sub")
    return user_id


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for the given user_id."""
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode = {
        "sub": user_id,
        "iat": datetime.now(UTC),
        "exp": expire,
        "iss": "promiselink",
        "aud": "promiselink-api",
    }
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt  # type: ignore[no-any-return]


def verify_token(token: str) -> dict[Any, Any]:
    """Verify and decode a JWT token. Returns the payload dict."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.algorithm],
            issuer="promiselink",
            audience="promiselink-api",
        )
        return cast(dict[Any, Any], payload)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

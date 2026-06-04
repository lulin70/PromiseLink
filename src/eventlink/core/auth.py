"""JWT authentication and authorization utilities."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from eventlink.config import get_settings

security = HTTPBearer(auto_error=False)


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
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]
) -> str:
    """Extract user_id from JWT token. Returns test user if no token (PoC compat)."""
    TEST_USER_ID = "00000000-0000-0000-0000-000000000001"

    if credentials is None:
        return TEST_USER_ID

    token = credentials.credentials
    payload = verify_token(token)
    user_id: str | None = payload.get("sub")
    if user_id is None:
        return TEST_USER_ID
    return user_id


def create_access_token(user_id: str) -> str:
    """Create a JWT access token for the given user_id."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    to_encode = {"sub": user_id, "exp": expire}
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def verify_token(token: str) -> dict:
    """Verify and decode a JWT token. Returns the payload dict."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

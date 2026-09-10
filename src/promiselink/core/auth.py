"""JWT authentication and authorization utilities."""

import base64
import hashlib
import hmac
import json
import os
import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from promiselink.config import get_settings
from promiselink.core.exceptions import CandidateTokenError

security = HTTPBearer(auto_error=False)

W5_CANDIDATE_TOKEN_VERSION = "w5-token-v1"
W5_CANDIDATE_TOKEN_FIELDS = (
    "version",
    "key_version",
    "user_id",
    "event_id",
    "scope_type",
    "extracted_entity_id_or_source_todo_id",
    "candidate_digest",
    "operation_key",
    "resolver_version",
    "score_version",
    "embedding_space",
    "issued_at",
    "expires_at",
    "nonce",
)
_W5_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_W5_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_W5_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _candidate_token_error(message: str) -> CandidateTokenError:
    return CandidateTokenError("CANDIDATE_TOKEN_INVALID", message)


def _candidate_token_secret(key_version: str) -> str:
    settings = get_settings()
    secrets_by_version = {
        "1": settings.candidate_token_secret_v1,
    }
    secret = secrets_by_version.get(key_version, "")
    if not secret:
        raise _candidate_token_error("candidate token secret is unavailable")
    return secret


def candidate_token_hash(token: str) -> str:
    """Return the non-reversible operation lookup digest for an opaque token."""
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def issue_candidate_token(
    *,
    user_id: str,
    event_id: str,
    scope_type: str,
    resource_id: str,
    candidate_digest: str,
    operation_key: str,
    resolver_version: str,
    score_version: str,
    embedding_space: str,
    now: datetime | None = None,
) -> tuple[str, dict[str, Any]]:
    """Issue a W5-CJ-v1 token and return it with its canonical payload."""
    settings = get_settings()
    issued_at = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    expires_at = issued_at + timedelta(seconds=settings.candidate_token_ttl_seconds)
    payload: dict[str, Any] = {
        "version": W5_CANDIDATE_TOKEN_VERSION,
        "key_version": settings.candidate_token_key_version,
        "user_id": user_id,
        "event_id": event_id,
        "scope_type": scope_type,
        "extracted_entity_id_or_source_todo_id": resource_id,
        "candidate_digest": candidate_digest,
        "operation_key": operation_key,
        "resolver_version": resolver_version,
        "score_version": score_version,
        "embedding_space": embedding_space,
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
        # Hex nonce (not base64url) so the first char is always alphanumeric —
        # base64url can start with "-" or "_", which _W5_ID_RE rejects.
        "nonce": os.urandom(16).hex(),
    }
    payload_bytes = _canonical_candidate_payload(payload)
    signature = hmac.new(
        _candidate_token_secret(payload["key_version"]).encode("utf-8"),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest().encode("ascii")
    token = base64.urlsafe_b64encode(payload_bytes + b"." + signature).rstrip(b"=").decode("ascii")
    return token, payload


def _canonical_candidate_payload(payload: Mapping[str, Any]) -> bytes:
    if tuple(payload.keys()) != W5_CANDIDATE_TOKEN_FIELDS:
        raise _candidate_token_error("candidate token payload fields are invalid")

    def normalize(value: Any) -> Any:
        if isinstance(value, str):
            return unicodedata.normalize("NFC", value)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    try:
        return json.dumps(
            normalize(dict(payload)),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise _candidate_token_error("candidate token payload is not canonicalizable") from exc


def _parse_candidate_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise _candidate_token_error(f"candidate token {field} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _candidate_token_error(f"candidate token {field} is invalid") from exc
    if parsed.tzinfo is None:
        raise _candidate_token_error(f"candidate token {field} must include timezone")
    return parsed.astimezone(UTC)


def verify_candidate_token(
    token: str,
    *,
    authenticated_user_id: str,
    event_id: str,
    scope_type: str,
    extracted_entity_id: str | None = None,
    source_todo_id: str | None = None,
    candidate_digest: str | None = None,
    operation_key: str | None = None,
    resolver_version: str | None = None,
    score_version: str | None = None,
    embedding_space: str | None = None,
    now: datetime | None = None,
    allow_expired_for_replay: bool = False,
) -> dict[str, Any]:
    """Verify a W5-CJ-v1 opaque candidate token at the auth boundary."""
    if not isinstance(token, str) or not token or not _W5_BASE64URL_RE.fullmatch(token):
        raise _candidate_token_error("candidate token encoding is invalid")
    try:
        padded = token + "=" * (-len(token) % 4)
        decoded = base64.b64decode(
            padded.encode("ascii"), altchars=b"-_", validate=True
        )
    except (UnicodeEncodeError, ValueError, base64.binascii.Error) as exc:
        raise _candidate_token_error("candidate token encoding is invalid") from exc

    if decoded.count(b".") != 1:
        raise _candidate_token_error("candidate token envelope is invalid")
    payload_bytes, signature_bytes = decoded.split(b".", 1)
    if len(signature_bytes) != 64 or not re.fullmatch(rb"[0-9a-f]{64}", signature_bytes):
        raise _candidate_token_error("candidate token signature is invalid")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _candidate_token_error("candidate token payload is invalid") from exc
    if not isinstance(payload, dict):
        raise _candidate_token_error("candidate token payload is invalid")
    canonical = _canonical_candidate_payload(payload)
    if canonical != payload_bytes:
        raise _candidate_token_error("candidate token payload is not canonical")

    settings = get_settings()
    if payload["version"] != W5_CANDIDATE_TOKEN_VERSION:
        raise _candidate_token_error("candidate token version is unsupported")
    key_version = payload["key_version"]
    if not isinstance(key_version, str) or not _W5_ID_RE.fullmatch(key_version):
        raise _candidate_token_error("candidate token key version is invalid")
    if key_version in settings.candidate_token_revoked_key_versions:
        raise _candidate_token_error("candidate token key version is revoked")
    if key_version != settings.candidate_token_key_version:
        raise _candidate_token_error("candidate token key version is unsupported")
    secret = _candidate_token_secret(key_version)
    expected_signature = hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).hexdigest().encode("ascii")
    if not hmac.compare_digest(signature_bytes, expected_signature):
        raise _candidate_token_error("candidate token signature is invalid")

    for field in ("user_id", "event_id", "operation_key", "nonce"):
        if not isinstance(payload[field], str) or not _W5_ID_RE.fullmatch(payload[field]):
            raise _candidate_token_error(f"candidate token {field} is invalid")
    if payload["scope_type"] not in {"entity", "todo"}:
        raise _candidate_token_error("candidate token scope is invalid")
    if payload["scope_type"] != scope_type:
        raise _candidate_token_error("candidate token scope does not match")
    bound_id = extracted_entity_id if scope_type == "entity" else source_todo_id
    resource_id = payload.get("extracted_entity_id_or_source_todo_id")
    if (
        not bound_id
        or not isinstance(resource_id, str)
        or not _W5_ID_RE.fullmatch(resource_id)
        or resource_id != bound_id
    ):
        raise _candidate_token_error("candidate token resource does not match")
    if payload["user_id"] != authenticated_user_id or payload["event_id"] != event_id:
        raise _candidate_token_error("candidate token authentication scope does not match")
    if not isinstance(payload["candidate_digest"], str) or not _W5_DIGEST_RE.fullmatch(payload["candidate_digest"]):
        raise _candidate_token_error("candidate token candidate digest is invalid")
    for field, expected in (
        ("candidate_digest", candidate_digest),
        ("operation_key", operation_key),
        ("resolver_version", resolver_version),
        ("score_version", score_version),
        ("embedding_space", embedding_space),
    ):
        if expected is not None and payload[field] != expected:
            raise _candidate_token_error(f"candidate token {field} does not match")

    issued_at = _parse_candidate_timestamp(payload["issued_at"], "issued_at")
    expires_at = _parse_candidate_timestamp(payload["expires_at"], "expires_at")
    if expires_at <= issued_at:
        raise _candidate_token_error("candidate token expiry is invalid")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if expires_at <= current and not allow_expired_for_replay:
        raise CandidateTokenError("CANDIDATE_TOKEN_EXPIRED", "candidate token has expired")
    if issued_at > current:
        raise _candidate_token_error("candidate token issued_at is in the future")
    ttl = (expires_at - issued_at).total_seconds()
    if ttl > settings.candidate_token_max_ttl_seconds:
        raise _candidate_token_error("candidate token lifetime exceeds the configured maximum")
    return cast(dict[str, Any], payload)



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
    return cast(str, encoded_jwt)


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

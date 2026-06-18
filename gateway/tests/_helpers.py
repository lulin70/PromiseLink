"""Shared test helpers for E2E and security tests.

Provides an :class:`InMemoryLicenseService` that implements the interface
expected by ``gateway.api.v1.license`` endpoints, using an in-memory license
store and the project's real :class:`JWTHandler` for token signing.

This avoids the database/Redis dependencies of the production
``LicenseService`` while still exercising the full HTTP request → response
cycle through FastAPI's ``TestClient``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from gateway.core.exceptions import (
    DeviceFingerprintMismatch,
    InvalidDeviceFingerprint,
    InvalidLicenseKeyFormat,
    JWTInvalid,
    LicenseAlreadyActivated,
    LicenseCancelled,
    LicenseExpired,
    LicenseInactive,
    LicenseNotFound,
)
from gateway.models.tables import License

# Regex validators (must match license_service.py)
_LICENSE_KEY_RE = re.compile(r"^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
_DEVICE_FP_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


class InMemoryLicenseService:
    """In-memory license service compatible with license API endpoints.

    Implements ``activate_license``, ``verify_license``, ``refresh_token``,
    and ``revoke_license`` using a plain dict store and the real JWTHandler.
    """

    def __init__(
        self,
        *,
        jwt_handler: Any,
        licenses: dict[str, License] | None = None,
    ) -> None:
        self._jwt_handler = jwt_handler
        self._licenses: dict[str, License] = licenses if licenses is not None else {}
        self._blacklisted_jtis: set[str] = set()

    # ── Activation ──────────────────────────────────────────────────

    async def activate_license(
        self,
        *,
        license_key: str,
        jwt_user_id: str,
        device_fingerprint: str,
    ) -> dict[str, Any]:
        """Activate a license and issue relay tokens.

        Returns a dict with ``license`` and ``tokens`` keys matching the
        ``LicenseActivateResponse`` schema.
        """
        self._validate_license_key_format(license_key)
        self._validate_device_fingerprint_format(device_fingerprint)

        lic = self._licenses.get(license_key)
        if lic is None:
            raise LicenseNotFound()

        self._check_license_status(lic)

        # Anti-hijacking: reject if bound to a different user
        if lic.user_id is not None and lic.user_id != jwt_user_id:
            raise LicenseAlreadyActivated()

        # Device binding: first activation binds the fingerprint
        if lic.device_fingerprint is not None:
            if lic.device_fingerprint != device_fingerprint:
                raise DeviceFingerprintMismatch()

        # Persist binding
        now = datetime.now(UTC)
        lic.user_id = jwt_user_id
        lic.device_fingerprint = device_fingerprint
        lic.device_bound_at = now
        lic.status = "active"
        lic.updated_at = now

        # Issue tokens
        access_token = self._jwt_handler.create_access_token(
            user_id=jwt_user_id,
            license_key=license_key,
            plan_type=lic.plan_type,
            device_fingerprint=device_fingerprint,
        )
        refresh_token = self._jwt_handler.create_refresh_token(
            user_id=jwt_user_id,
            license_key=license_key,
            plan_type=lic.plan_type,
            device_fingerprint=device_fingerprint,
        )

        return {
            "license": {
                "license_key": lic.license_key,
                "plan_type": lic.plan_type,
                "status": lic.status,
                "expires_at": lic.expires_at.isoformat(),
                "quota_limit_tokens": lic.quota_limit_tokens,
                "quota_limit_asr": lic.quota_limit_asr,
                "quota_limit_tts": lic.quota_limit_tts,
                "quota_limit_ocr": lic.quota_limit_ocr,
            },
            "tokens": {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_in": self._jwt_handler.access_ttl,
            },
        }

    # ── Verification ────────────────────────────────────────────────

    async def verify_license(
        self,
        *,
        token_payload: dict[str, Any],
        device_fingerprint: str,
    ) -> dict[str, Any]:
        """Verify a license from the JWT payload.

        Returns a dict matching the ``LicenseVerifyResponse`` schema.
        """
        license_key = token_payload.get("license_key", "")
        lic = self._licenses.get(license_key)
        if lic is None:
            raise LicenseNotFound()

        self._check_license_status(lic)

        # Device fingerprint match
        jwt_fp = token_payload.get("device_fingerprint", "")
        if jwt_fp != lic.device_fingerprint:
            raise DeviceFingerprintMismatch()
        if device_fingerprint != jwt_fp:
            raise DeviceFingerprintMismatch()

        # Compute traffic light
        traffic_light = self._compute_traffic_light(
            lic.quota_used_tokens, lic.quota_limit_tokens
        )

        return {
            "valid": True,
            "license": {
                "license_key": lic.license_key,
                "plan_type": lic.plan_type,
                "status": lic.status,
                "expires_at": lic.expires_at.isoformat(),
                "quota_limit_tokens": lic.quota_limit_tokens,
                "quota_limit_asr": lic.quota_limit_asr,
                "quota_limit_tts": lic.quota_limit_tts,
                "quota_limit_ocr": lic.quota_limit_ocr,
            },
            "quota": {
                "tokens": {
                    "limit": lic.quota_limit_tokens,
                    "used": lic.quota_used_tokens,
                    "remaining": max(0, lic.quota_limit_tokens - lic.quota_used_tokens),
                    "percentage": round(
                        lic.quota_used_tokens / lic.quota_limit_tokens * 100, 1
                    ) if lic.quota_limit_tokens > 0 else 0.0,
                },
            },
            "traffic_light": traffic_light,
        }

    # ── Refresh ─────────────────────────────────────────────────────

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh an access token using a refresh token.

        Returns a dict matching the ``TokenPair`` schema.
        """
        try:
            payload = self._jwt_handler.verify_token(
                refresh_token, expected_type="refresh"
            )
        except Exception as exc:
            raise JWTInvalid(f"Invalid refresh token: {exc}") from exc

        license_key = payload.get("license_key", "")
        lic = self._licenses.get(license_key)
        if lic is None:
            raise LicenseNotFound()
        self._check_license_status(lic)

        user_id = payload.get("user_id", "")
        device_fp = payload.get("device_fingerprint", "")
        plan_type = payload.get("plan_type", "pro")

        new_access = self._jwt_handler.create_access_token(
            user_id=user_id,
            license_key=license_key,
            plan_type=plan_type,
            device_fingerprint=device_fp,
        )
        new_refresh = self._jwt_handler.create_refresh_token(
            user_id=user_id,
            license_key=license_key,
            plan_type=plan_type,
            device_fingerprint=device_fp,
        )

        return {
            "access_token": new_access,
            "refresh_token": new_refresh,
            "token_type": "Bearer",
            "expires_in": self._jwt_handler.access_ttl,
        }

    # ── Revocation ──────────────────────────────────────────────────

    async def revoke_license(
        self,
        *,
        user_id: str,
        reason: str,
        license_key: str | None = None,
        active_jtis: list[str] | None = None,
    ) -> None:
        """Revoke a license and blacklist its active JWTs."""
        for lic in self._licenses.values():
            if lic.user_id != user_id:
                continue
            if license_key is not None and lic.license_key != license_key:
                continue
            lic.status = "cancelled"
            lic.updated_at = datetime.now(UTC)

        for jti in active_jtis or []:
            self._blacklisted_jtis.add(jti)

    def is_jti_blacklisted(self, jti: str) -> bool:
        """Check if a JWT jti has been revoked."""
        return jti in self._blacklisted_jtis

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_license_key_format(license_key: str) -> None:
        if not _LICENSE_KEY_RE.match(license_key):
            raise InvalidLicenseKeyFormat()

    @staticmethod
    def _validate_device_fingerprint_format(device_fingerprint: str) -> None:
        if not _DEVICE_FP_RE.match(device_fingerprint):
            raise InvalidDeviceFingerprint()

    @staticmethod
    def _check_license_status(lic: License) -> None:
        now = datetime.now(UTC)
        expires_at = lic.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at < now and lic.status == "active":
            lic.status = "expired"
            lic.updated_at = now

        if lic.status == "expired":
            raise LicenseExpired()
        if lic.status == "cancelled":
            raise LicenseCancelled()
        if lic.status != "active":
            raise LicenseInactive(f"Unexpected status: {lic.status}")

    @staticmethod
    def _compute_traffic_light(used: int, limit: int) -> str:
        """Compute traffic-light colour (must match admin.py logic)."""
        if limit <= 0:
            return "red"
        ratio = used / limit
        if ratio >= 1.0:
            return "red"
        if ratio >= 0.80:
            return "yellow"
        return "green"


# ── Factory helpers ─────────────────────────────────────────────────


def make_license(
    license_key: str,
    *,
    user_id: str | None = None,
    device_fingerprint: str | None = None,
    status: str = "active",
    plan_type: str = "pro",
    quota_limit_tokens: int = 500000,
    quota_limit_asr: int = 200,
    quota_limit_tts: int = 200,
    quota_limit_ocr: int = 100,
    quota_used_tokens: int = 0,
    quota_used_asr: int = 0,
    quota_used_tts: int = 0,
    quota_used_ocr: int = 0,
    expires_in_days: int = 365,
) -> License:
    """Build a License ORM row with test defaults."""
    now = datetime.now(UTC)
    return License(
        license_key=license_key,
        user_id=user_id,
        plan_type=plan_type,
        quota_limit_tokens=quota_limit_tokens,
        quota_limit_asr=quota_limit_asr,
        quota_limit_tts=quota_limit_tts,
        quota_limit_ocr=quota_limit_ocr,
        quota_used_tokens=quota_used_tokens,
        quota_used_asr=quota_used_asr,
        quota_used_tts=quota_used_tts,
        quota_used_ocr=quota_used_ocr,
        quota_reset_at=now,
        status=status,
        started_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        device_fingerprint=device_fingerprint,
        device_bound_at=now if device_fingerprint else None,
        max_devices=1,
    )


def make_device_fingerprint(seed: str = "") -> str:
    """Return a valid SHA256 device fingerprint for testing."""
    import hashlib

    if seed:
        h = hashlib.sha256(seed.encode()).hexdigest()
    else:
        import secrets

        h = secrets.token_hex(32)
    return f"sha256:{h}"


def make_license_key(seed: str = "") -> str:
    """Return a valid license key for testing."""
    if seed and len(seed) >= 12:
        chars = "".join(c.upper() for c in seed if c.isalnum())[:12]
    else:
        import uuid

        chars = uuid.uuid4().hex.upper()[:12]
    while len(chars) < 12:
        chars += "0"
    return f"PL-PRO-{chars[:4]}-{chars[4:8]}-{chars[8:12]}"


def make_user_id(seed: str = "") -> str:
    """Return a deterministic user ID for testing."""
    import hashlib

    if seed:
        h = hashlib.sha256(seed.encode()).hexdigest()[:16]
        return f"u_{h}"
    import uuid

    return f"u_{uuid.uuid4().hex[:16]}"


# ── Admin JWT helper ────────────────────────────────────────────────

_ADMIN_JWT_ISSUER = "promiselink-gateway-admin"
_ADMIN_JWT_AUDIENCE = "promiselink-admin-client"


def make_admin_jwt(settings: Any) -> str:
    """Create a valid admin JWT for testing (matches POST /api/v1/admin/token)."""
    import time

    import jwt as pyjwt

    now = int(time.time())
    payload = {
        "admin_id": settings.admin_id,
        "role": "admin",
        "iat": now,
        "exp": now + settings.admin_jwt_ttl,
        "iss": _ADMIN_JWT_ISSUER,
        "aud": _ADMIN_JWT_AUDIENCE,
    }
    return pyjwt.encode(payload, settings.admin_jwt_secret, algorithm="HS256")


def make_admin_headers(settings: Any) -> dict[str, str]:
    """Return headers with valid admin API key + admin JWT (two-factor)."""
    return {
        "X-Admin-API-Key": settings.admin_api_key,
        "Authorization": f"Bearer {make_admin_jwt(settings)}",
    }

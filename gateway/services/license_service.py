"""License verification service for the PromiseLink gateway.

Implements the four core flows from tech design §6:

* **Activation** (§6.1) — bind a license key to a user (extracted from
  the user JWT, never from the request body) and device fingerprint,
  then sign a relay JWT.
* **Verification** (§6.2) — validate the relay JWT signature, check the
  CRL blacklist, license status, and device fingerprint match.
* **Refresh** (§6.3) — accept a token up to 5 minutes past expiry,
  issue a new token, and revoke the old one.
* **Revocation** (§6.4) — admin-driven license cancellation; all active
  JWTs are added to the CRL blacklist.

Security highlights (I-4 / P0-5):

* RS256 asymmetric JWT signing (private key signs, public key verifies).
* ``user_id`` is always taken from the JWT, never from the client.
* License-to-user binding is immutable after first activation
  (anti-hijacking / 防抢绑).
* Device fingerprint must match the one stored on the license.
* Revoked JWTs are tracked in Redis under ``jwt_blacklist:{jti}`` with a
  TTL equal to the JWT's remaining lifetime.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gateway.core.exceptions import (
    DeviceFingerprintMismatch,
    InvalidDeviceFingerprint,
    InvalidLicenseKeyFormat,
    JWTRevoked,
    LicenseAlreadyActivated,
    LicenseCancelled,
    LicenseExpired,
    LicenseInactive,
    LicenseNotFound,
    LicenseSuspended,
)
from gateway.core.jwt_handler import (
    DEFAULT_ACCESS_TOKEN_TTL,
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    DEFAULT_REFRESH_TOKEN_TTL,
    sign_token,
    verify_token,
)
from gateway.models.tables import AuditLog, License

# ── Regex validators (tech design §4.3.1) ───────────────────────────

_LICENSE_KEY_RE = re.compile(r"^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$")
_DEVICE_FP_RE = re.compile(r"^sha256:[a-f0-9]{64}$")

# CRL Redis key prefix and refresh leeway (tech design §6.3, §3.7)
_BLACKLIST_PREFIX = "jwt_blacklist:"
_REFRESH_LEEWAY_SECONDS = 300  # 5 minutes grace for refresh


@dataclass
class ActivationResult:
    """Result of :meth:`LicenseService.activate_license`.

    Attributes:
        license_key: The activated license key.
        plan_type: ``pro`` or ``trial``.
        status: License status after activation (``active``).
        expires_at: License expiry timestamp.
        quota_limit_tokens: Monthly token quota.
        quota_limit_asr: Monthly ASR call quota.
        quota_limit_tts: Monthly TTS call quota.
        quota_limit_ocr: Monthly OCR call quota.
        access_token: Signed relay JWT (RS256, 15 min TTL).
        refresh_token: Signed refresh JWT (RS256, 7 day TTL).
        expires_in: Access token lifetime in seconds.
    """

    license_key: str
    plan_type: str
    status: str
    expires_at: datetime
    quota_limit_tokens: int
    quota_limit_asr: int
    quota_limit_tts: int
    quota_limit_ocr: int
    access_token: str
    refresh_token: str
    expires_in: int


@dataclass
class VerificationResult:
    """Result of :meth:`LicenseService.verify_relay_token`.

    Attributes:
        user_id: User identifier from the JWT.
        license_key: Bound license key.
        plan_type: ``pro`` or ``trial``.
        device_fingerprint: Device fingerprint from the JWT.
        jti: JWT unique ID.
        expires_at: JWT expiry timestamp.
    """

    user_id: str
    license_key: str
    plan_type: str
    device_fingerprint: str
    jti: str
    expires_at: datetime


class LicenseService:
    """License activation, JWT issuance, verification, refresh, and revocation.

    The service is stateless apart from its injected dependencies (DB
    session, Redis client, JWT keys), making it safe to instantiate once
    per request.
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        redis_client: redis_asyncio.Redis,
        private_key_pem: str,
        public_key_pem: str,
        issuer: str = DEFAULT_ISSUER,
        audience: str = DEFAULT_AUDIENCE,
        access_token_ttl: int = DEFAULT_ACCESS_TOKEN_TTL,
        refresh_token_ttl: int = DEFAULT_REFRESH_TOKEN_TTL,
    ) -> None:
        """Initialize the license service.

        Args:
            db_session: Async SQLAlchemy session for license/audit writes.
            redis_client: Async Redis client for CRL blacklist operations.
            private_key_pem: RSA private key (PEM) for signing JWTs.
            public_key_pem: RSA public key (PEM) for verifying JWTs.
            issuer: JWT ``iss`` claim.
            audience: JWT ``aud`` claim.
            access_token_ttl: Access token lifetime in seconds.
            refresh_token_ttl: Refresh token lifetime in seconds.
        """
        self._db = db_session
        self._redis = redis_client
        self._private_key = private_key_pem
        self._public_key = public_key_pem
        self._issuer = issuer
        self._audience = audience
        self._access_ttl = access_token_ttl
        self._refresh_ttl = refresh_token_ttl

    # ── Activation (tech design §6.1) ───────────────────────────────

    async def activate_license(
        self,
        *,
        jwt_user_id: str,
        license_key: str,
        device_fingerprint: str,
    ) -> ActivationResult:
        """Activate a license and issue relay tokens.

        The ``jwt_user_id`` is extracted from the caller's user JWT by
        the API layer — it is **never** read from the request body
        (P0-5 anti-hijacking fix).

        Flow (tech design §6.1):

        1. Validate ``license_key`` and ``device_fingerprint`` formats.
        2. Load the license row.
        3. Check license status (active/expired/cancelled/suspended).
        4. Anti-hijacking: if ``user_id`` is already bound to a
           *different* user, reject with 409.
        5. Device binding: first activation binds the fingerprint;
           subsequent activations must match.
        6. Persist the binding and set ``status='active'``.
        7. Sign access + refresh JWTs (RS256).
        8. Write an audit log entry.

        Args:
            jwt_user_id: User ID extracted from the user JWT.
            license_key: License key matching ``PL-PRO-xxxx-xxxx-xxxx``.
            device_fingerprint: Device fingerprint matching
                ``sha256:`` + 64 hex chars.

        Returns:
            :class:`ActivationResult` with tokens and license info.

        Raises:
            InvalidLicenseKeyFormat: Bad license key format.
            InvalidDeviceFingerprint: Bad device fingerprint format.
            LicenseNotFound: License key not in database.
            LicenseExpired: License status is ``expired`` or
                ``expires_at`` is in the past.
            LicenseCancelled: License status is ``cancelled``.
            LicenseSuspended: License status is ``suspended``.
            LicenseAlreadyActivated: License bound to another user.
            DeviceFingerprintMismatch: Device fingerprint does not match
                the bound one.
        """
        # Step 1: format validation
        self._validate_license_key_format(license_key)
        self._validate_device_fingerprint_format(device_fingerprint)

        # Step 2: load license
        license_row = await self._load_license(license_key)
        if license_row is None:
            raise LicenseNotFound()

        # Step 3: status check
        await self._check_license_status(license_row)

        # Step 4: anti-hijacking (P0-5)
        if license_row.user_id is not None and license_row.user_id != jwt_user_id:
            await self._audit(
                user_id=jwt_user_id,
                action="license_activate_denied",
                resource_id=license_key,
                metadata={"reason": "already_activated_by_other",
                          "bound_user": license_row.user_id},
            )
            raise LicenseAlreadyActivated()

        # Step 5: device binding check
        if license_row.device_fingerprint is not None:
            if license_row.device_fingerprint != device_fingerprint:
                raise DeviceFingerprintMismatch()

        # Step 6: persist binding
        now = datetime.now(UTC)
        license_row.user_id = jwt_user_id
        license_row.device_fingerprint = device_fingerprint
        license_row.device_bound_at = now
        license_row.status = "active"
        license_row.updated_at = now
        await self._db.flush()

        # Step 7: sign tokens
        access_token = sign_token(
            user_id=jwt_user_id,
            license_key=license_key,
            plan_type=license_row.plan_type,
            device_fingerprint=device_fingerprint,
            private_key_pem=self._private_key,
            ttl=self._access_ttl,
            issuer=self._issuer,
            audience=self._audience,
            token_type="access",
        )
        refresh_token = sign_token(
            user_id=jwt_user_id,
            license_key=license_key,
            plan_type=license_row.plan_type,
            device_fingerprint=device_fingerprint,
            private_key_pem=self._private_key,
            ttl=self._refresh_ttl,
            issuer=self._issuer,
            audience=self._audience,
            token_type="refresh",
        )

        # Step 8: audit log
        await self._audit(
            user_id=jwt_user_id,
            action="license_activate",
            resource_id=license_key,
            metadata={"device_fingerprint": device_fingerprint},
        )
        await self._db.commit()

        return ActivationResult(
            license_key=license_key,
            plan_type=license_row.plan_type,
            status=license_row.status,
            expires_at=license_row.expires_at,
            quota_limit_tokens=license_row.quota_limit_tokens,
            quota_limit_asr=license_row.quota_limit_asr,
            quota_limit_tts=license_row.quota_limit_tts,
            quota_limit_ocr=license_row.quota_limit_ocr,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self._access_ttl,
        )

    # ── Verification (tech design §6.2) ─────────────────────────────

    async def verify_relay_token(
        self,
        token: str,
        *,
        expected_device_fingerprint: str | None = None,
    ) -> VerificationResult:
        """Verify a relay JWT and the bound license.

        Flow (tech design §6.2):

        1. Verify RS256 signature, ``iss``/``aud``/``exp`` claims.
        2. Check the CRL blacklist (Redis ``jwt_blacklist:{jti}``).
        3. Load the license and check ``status='active'``.
        4. Verify the device fingerprint matches the JWT payload (and
           optionally the request header).

        Args:
            token: Compact JWT string.
            expected_device_fingerprint: If provided, must match the
                fingerprint in the JWT payload.

        Returns:
            :class:`VerificationResult` with session info.

        Raises:
            JWTInvalid: Signature/claims invalid.
            JWTExpired: Token past ``exp``.
            JWTRevoked: ``jti`` in CRL blacklist.
            LicenseInactive: License status not ``active``.
            LicenseExpired: License ``expires_at`` in the past.
            DeviceFingerprintMismatch: Fingerprint mismatch.
        """
        # Step 1: signature + claims
        payload = verify_token(
            token,
            public_key_pem=self._public_key,
            issuer=self._issuer,
            audience=self._audience,
        )

        # Step 2: CRL blacklist
        if await self._is_blacklisted(payload.jti):
            raise JWTRevoked()

        # Step 3: license status
        license_row = await self._load_license(payload.license_key)
        if license_row is None:
            raise LicenseInactive("License not found")
        await self._check_license_status(license_row)

        # Step 4: device fingerprint match
        if payload.device_fingerprint != license_row.device_fingerprint:
            raise DeviceFingerprintMismatch()
        if (
            expected_device_fingerprint is not None
            and expected_device_fingerprint != payload.device_fingerprint
        ):
            raise DeviceFingerprintMismatch()

        return VerificationResult(
            user_id=payload.user_id,
            license_key=payload.license_key,
            plan_type=payload.plan_type,
            device_fingerprint=payload.device_fingerprint,
            jti=payload.jti,
            expires_at=datetime.fromtimestamp(payload.exp, tz=UTC),
        )

    # ── Refresh (tech design §6.3) ──────────────────────────────────

    async def refresh_relay_token(self, token: str) -> tuple[str, str]:
        """Refresh an access token, returning ``(new_access, new_refresh)``.

        Accepts tokens up to 5 minutes past expiry (leeway). The old
        token's ``jti`` is added to the CRL blacklist so it cannot be
        reused.

        Args:
            token: The previous access or refresh token.

        Returns:
            Tuple of ``(new_access_token, new_refresh_token)``.

        Raises:
            JWTInvalid: Signature/claims invalid.
            JWTExpired: Token more than 5 minutes past expiry.
            JWTRevoked: Old token already revoked.
            LicenseInactive: License no longer active.
        """
        # Verify with 5-minute leeway (tech design §6.3)
        payload = verify_token(
            token,
            public_key_pem=self._public_key,
            issuer=self._issuer,
            audience=self._audience,
            leeway=_REFRESH_LEEWAY_SECONDS,
        )

        # Old token must not already be revoked
        if await self._is_blacklisted(payload.jti):
            raise JWTRevoked()

        # License must still be active
        license_row = await self._load_license(payload.license_key)
        if license_row is None:
            raise LicenseInactive("License not found")
        await self._check_license_status(license_row)

        # Issue new tokens
        new_access = sign_token(
            user_id=payload.user_id,
            license_key=payload.license_key,
            plan_type=payload.plan_type,
            device_fingerprint=payload.device_fingerprint,
            private_key_pem=self._private_key,
            ttl=self._access_ttl,
            issuer=self._issuer,
            audience=self._audience,
            token_type="access",
        )
        new_refresh = sign_token(
            user_id=payload.user_id,
            license_key=payload.license_key,
            plan_type=payload.plan_type,
            device_fingerprint=payload.device_fingerprint,
            private_key_pem=self._private_key,
            ttl=self._refresh_ttl,
            issuer=self._issuer,
            audience=self._audience,
            token_type="refresh",
        )

        # Revoke old token (CRL TTL = remaining lifetime, min 1s)
        remaining = max(payload.exp - int(datetime.now(UTC).timestamp()), 1)
        await self._blacklist_jti(payload.jti, remaining)

        await self._audit(
            user_id=payload.user_id,
            action="license_refresh",
            resource_id=payload.license_key,
            metadata={"old_jti": payload.jti},
        )
        await self._db.commit()

        return new_access, new_refresh

    # ── Revocation (tech design §6.4) ───────────────────────────────

    async def revoke_license(
        self,
        *,
        user_id: str,
        reason: str,
        license_key: str | None = None,
        active_jtis: list[str] | None = None,
    ) -> None:
        """Revoke a license and blacklist all known active JWTs.

        This is the admin-driven revocation flow (tech design §6.4).
        The caller (admin API layer) is responsible for authentication;
        this method performs the state mutation.

        Args:
            user_id: User whose license is being revoked.
            reason: Revocation reason (e.g. ``user_refund``).
            license_key: Optional license key to revoke. If omitted, all
                licenses for ``user_id`` are revoked.
            active_jtis: List of active JWT ``jti`` values to blacklist.
                In production these are obtained from relay session
                records; tests can pass them directly.

        Raises:
            LicenseNotFound: No matching license found.
        """
        # Step 1: update license status
        stmt = select(License).where(License.user_id == user_id)
        if license_key is not None:
            stmt = stmt.where(License.license_key == license_key)
        result = await self._db.execute(stmt)
        licenses = list(result.scalars().all())

        if not licenses:
            raise LicenseNotFound()

        now = datetime.now(UTC)
        for lic in licenses:
            lic.status = "cancelled"
            lic.updated_at = now
        await self._db.flush()

        # Step 2: blacklist all active JTIs
        if active_jtis:
            for jti in active_jtis:
                # TTL = access token TTL (worst case remaining lifetime)
                await self._blacklist_jti(jti, self._access_ttl)

        # Step 3: audit log
        await self._audit(
            user_id=user_id,
            action="license_revoke",
            resource_id=license_key or ",".join(l.license_key for l in licenses),
            metadata={"reason": reason, "blacklisted_jtis": len(active_jtis or [])},
        )
        await self._db.commit()

    # ── Helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_license_key_format(license_key: str) -> None:
        """Validate the license key format (tech design §4.3.1)."""
        if not _LICENSE_KEY_RE.match(license_key):
            raise InvalidLicenseKeyFormat()

    @staticmethod
    def _validate_device_fingerprint_format(device_fingerprint: str) -> None:
        """Validate the device fingerprint format (tech design §4.3.1)."""
        if not _DEVICE_FP_RE.match(device_fingerprint):
            raise InvalidDeviceFingerprint()

    async def _load_license(self, license_key: str) -> License | None:
        """Load a license row by key."""
        result = await self._db.execute(
            select(License).where(License.license_key == license_key)
        )
        return result.scalar_one_or_none()

    async def _check_license_status(self, license_row: License) -> None:
        """Check the license status and expiry (tech design §6.1 step 3).

        If the license is past its ``expires_at`` but still marked
        ``active``, it is auto-expired and the change is flushed so it
        persists even when the caller raises an exception.
        """
        now = datetime.now(UTC)
        # SQLite stores datetimes as naive; normalize both to aware UTC.
        expires_at = license_row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        # Auto-expire if past expires_at
        if expires_at < now and license_row.status == "active":
            license_row.status = "expired"
            license_row.updated_at = now
            await self._db.flush()

        status = license_row.status
        if status == "expired":
            raise LicenseExpired()
        if status == "cancelled":
            raise LicenseCancelled()
        if status == "suspended":
            raise LicenseSuspended()
        if status != "active":
            raise LicenseInactive(f"Unexpected status: {status}")

    async def _is_blacklisted(self, jti: str) -> bool:
        """Check if a JWT ``jti`` is in the CRL blacklist."""
        return bool(await self._redis.exists(f"{_BLACKLIST_PREFIX}{jti}"))

    async def _blacklist_jti(self, jti: str, ttl_seconds: int) -> None:
        """Add a JWT ``jti`` to the CRL blacklist with the given TTL."""
        key = f"{_BLACKLIST_PREFIX}{jti}"
        await self._redis.set(key, "revoked", ex=ttl_seconds)

    async def _audit(
        self,
        *,
        user_id: str,
        action: str,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write an audit log entry (tech design §3.6.3)."""
        log = AuditLog(
            user_id=user_id,
            request_id=str(uuid.uuid4()),
            action=action,
            resource_type="license",
            resource_id=resource_id,
            metadata_json=json.dumps(metadata or {}),
        )
        self._db.add(log)

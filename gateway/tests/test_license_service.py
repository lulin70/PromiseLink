"""Unit tests for :mod:`gateway.services.license_service`.

Covers the test cases from the Phase 0 test plan §2.2:

* Activation flow (UT-LIC-001 … UT-LIC-016)
* JWT signing/verification (UT-LIC-020 … UT-LIC-030)
* Device fingerprint binding (UT-LIC-040 … UT-LIC-046)
* CRL blacklist (UT-LIC-050 … UT-LIC-055)
* Refresh flow (UT-LIC-060 … UT-LIC-065)
* Anti-hijacking (P0-5)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from sqlalchemy import select

from gateway.core.exceptions import (
    DeviceFingerprintMismatch,
    InvalidDeviceFingerprint,
    InvalidLicenseKeyFormat,
    JWTExpired,
    JWTInvalid,
    JWTRevoked,
    LicenseAlreadyActivated,
    LicenseCancelled,
    LicenseExpired,
    LicenseInactive,
    LicenseNotFound,
    LicenseSuspended,
)
from gateway.core.jwt_handler import (
    ALGORITHM,
    DEFAULT_ACCESS_TOKEN_TTL,
    sign_token,
    verify_token,
)
from gateway.models.tables import AuditLog, License
from gateway.services.license_service import (
    LicenseService,
    _BLACKLIST_PREFIX,
)
from gateway.tests.conftest import (
    make_device_fingerprint,
    make_license_key,
    make_user_id,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _make_service(
    db_session,
    redis_client,
    private_key_pem,
    public_key_pem,
    **kwargs,
) -> LicenseService:
    """Build a LicenseService with the standard test dependencies."""
    return LicenseService(
        db_session=db_session,
        redis_client=redis_client,
        private_key_pem=private_key_pem,
        public_key_pem=public_key_pem,
        **kwargs,
    )


# ── Activation flow tests (UT-LIC-001 … UT-LIC-016) ─────────────────


@pytest.mark.asyncio
async def test_activate_license_success(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-001 / UT-LIC-010 / UT-LIC-014 / UT-LIC-015: normal activation."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    user_id = make_user_id("alice")
    device_fp = make_device_fingerprint("alice-pc")

    result = await service.activate_license(
        jwt_user_id=user_id,
        license_key=active_license.license_key,
        device_fingerprint=device_fp,
    )

    assert result.license_key == active_license.license_key
    assert result.plan_type == "pro"
    assert result.status == "active"
    assert result.expires_in == DEFAULT_ACCESS_TOKEN_TTL
    assert result.access_token  # non-empty
    assert result.refresh_token  # non-empty
    assert result.quota_limit_tokens == 500000

    # Verify the license was bound
    await db_session.refresh(active_license)
    assert active_license.user_id == user_id
    assert active_license.device_fingerprint == device_fp
    assert active_license.status == "active"
    assert active_license.device_bound_at is not None

    # Verify audit log was written
    audit_result = await db_session.execute(select(AuditLog))
    audits = audit_result.scalars().all()
    assert any(a.action == "license_activate" for a in audits)


@pytest.mark.asyncio
async def test_activate_license_invalid_key_format(
    db_session, redis_client, private_key_pem, public_key_pem
):
    """UT-LIC-002: invalid license key format → 400."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(InvalidLicenseKeyFormat):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key="INVALID-KEY",
            device_fingerprint=make_device_fingerprint(),
        )


@pytest.mark.asyncio
async def test_activate_license_not_found(
    db_session, redis_client, private_key_pem, public_key_pem
):
    """UT-LIC-003: license key not in DB → 404."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(LicenseNotFound):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=make_license_key("XXXX-YYYY-ZZZZ"),
            device_fingerprint=make_device_fingerprint(),
        )


@pytest.mark.asyncio
async def test_activate_license_invalid_device_fingerprint(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-004 / UT-LIC-046: invalid device fingerprint → 400."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(InvalidDeviceFingerprint):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=active_license.license_key,
            device_fingerprint="md5:abc123",
        )


@pytest.mark.asyncio
async def test_activate_license_expired(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-005: expired license → 410."""
    active_license.status = "expired"
    await db_session.commit()

    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(LicenseExpired):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=active_license.license_key,
            device_fingerprint=make_device_fingerprint(),
        )


@pytest.mark.asyncio
async def test_activate_license_cancelled(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-006: cancelled license → 410."""
    active_license.status = "cancelled"
    await db_session.commit()

    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(LicenseCancelled):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=active_license.license_key,
            device_fingerprint=make_device_fingerprint(),
        )


@pytest.mark.asyncio
async def test_activate_license_suspended(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-007: suspended license → 403."""
    active_license.status = "suspended"
    await db_session.commit()

    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(LicenseSuspended):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=active_license.license_key,
            device_fingerprint=make_device_fingerprint(),
        )


@pytest.mark.asyncio
async def test_activate_license_auto_expired(
    db_session, redis_client, private_key_pem, public_key_pem, active_license
):
    """UT-LIC-008: expires_at < NOW but status still active → auto-expire → 410."""
    active_license.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()

    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    with pytest.raises(LicenseExpired):
        await service.activate_license(
            jwt_user_id=make_user_id(),
            license_key=active_license.license_key,
            device_fingerprint=make_device_fingerprint(),
        )

    # Verify status was updated to expired
    await db_session.refresh(active_license)
    assert active_license.status == "expired"


@pytest.mark.asyncio
async def test_activate_license_already_activated_by_other(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-009 / P0-5 anti-hijacking: different user → 409."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)
    attacker_id = make_user_id("attacker")

    with pytest.raises(LicenseAlreadyActivated):
        await service.activate_license(
            jwt_user_id=attacker_id,
            license_key=bound_license.license_key,
            device_fingerprint=make_device_fingerprint("attacker-pc"),
        )

    # Verify the binding was NOT changed
    await db_session.refresh(bound_license)
    assert bound_license.user_id != attacker_id


@pytest.mark.asyncio
async def test_activate_license_same_user_reactivate(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-041: same user + same device → idempotent reactivation."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )
    assert result.status == "active"
    assert result.access_token


@pytest.mark.asyncio
async def test_activate_license_device_mismatch(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-011 / UT-LIC-042: different device → 403."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    with pytest.raises(DeviceFingerprintMismatch):
        await service.activate_license(
            jwt_user_id=bound_license.user_id,
            license_key=bound_license.license_key,
            device_fingerprint=make_device_fingerprint("other-device"),
        )


# ── JWT signing/verification tests (UT-LIC-020 … UT-LIC-030) ────────


@pytest.mark.asyncio
async def test_jwt_rs256_sign_and_verify(private_key_pem, public_key_pem):
    """UT-LIC-020 / UT-LIC-021: RS256 sign + verify round-trip."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
    )
    payload = verify_token(token, public_key_pem=public_key_pem)
    assert payload.user_id == "u_test"
    assert payload.license_key == "PL-PRO-A1B2-C3D4-E5F6"
    assert payload.plan_type == "pro"
    assert payload.jti  # non-empty UUID


def test_jwt_header_algorithm_is_rs256(private_key_pem):
    """UT-LIC-020: JWT header.alg must be RS256."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
    )
    header = pyjwt.get_unverified_header(token)
    assert header["alg"] == "RS256"


def test_jwt_invalid_signature(public_key_pem, private_key_pem):
    """UT-LIC-022: tampered payload → JWTInvalid."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
    )
    # Tamper with the payload
    parts = token.split(".")
    tampered = parts[0] + "." + parts[1][:-2] + "xx." + parts[2]
    with pytest.raises(JWTInvalid):
        verify_token(tampered, public_key_pem=public_key_pem)


def test_jwt_malformed_token(public_key_pem):
    """UT-LIC-023: malformed token → JWTInvalid."""
    with pytest.raises(JWTInvalid):
        verify_token("not.a.jwt", public_key_pem=public_key_pem)


def test_jwt_expired(public_key_pem, private_key_pem):
    """UT-LIC-024: expired token → JWTExpired."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
        ttl=-10,  # already expired
    )
    with pytest.raises(JWTExpired):
        verify_token(token, public_key_pem=public_key_pem)


def test_jwt_unique_jti(private_key_pem):
    """UT-LIC-027: each signed token has a unique jti."""
    tokens = [
        sign_token(
            user_id="u_test",
            license_key="PL-PRO-A1B2-C3D4-E5F6",
            plan_type="pro",
            device_fingerprint=make_device_fingerprint(),
            private_key_pem=private_key_pem,
        )
        for _ in range(10)
    ]
    jtis = [pyjwt.get_unverified_header(t) for t in tokens]
    # Decode payloads to get jti
    payloads = [pyjwt.decode(t, options={"verify_signature": False}) for t in tokens]
    jti_set = {p["jti"] for p in payloads}
    assert len(jti_set) == 10  # all unique


def test_jwt_ttl_15_minutes(private_key_pem):
    """UT-LIC-028: default TTL = 900s (15 min)."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
    )
    payload = pyjwt.decode(token, options={"verify_signature": False})
    assert payload["exp"] - payload["iat"] == 900


def test_jwt_contains_required_fields(private_key_pem):
    """UT-LIC-029: JWT contains all required fields."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
    )
    payload = pyjwt.decode(token, options={"verify_signature": False})
    required = {"user_id", "license_key", "plan_type", "device_fingerprint",
                "jti", "iat", "exp", "iss", "aud"}
    assert required.issubset(payload.keys())


def test_jwt_hs256_rejected(public_key_pem, private_key_pem):
    """UT-LIC-030: HS256-signed token must be rejected (only RS256 allowed)."""
    # Sign with HS256 using the public key as the HMAC secret (invalid usage)
    payload = {
        "user_id": "u_test",
        "license_key": "PL-PRO-A1B2-C3D4-E5F6",
        "plan_type": "pro",
        "device_fingerprint": make_device_fingerprint(),
        "jti": "test-jti",
        "iat": int(time.time()),
        "exp": int(time.time()) + 900,
        "iss": "promiselink-gateway",
        "aud": "promiselink-relay",
    }
    hs256_token = pyjwt.encode(payload, "some-secret", algorithm="HS256")
    with pytest.raises(JWTInvalid):
        verify_token(hs256_token, public_key_pem=public_key_pem)


def test_jwt_wrong_issuer_rejected(public_key_pem, private_key_pem):
    """JWT with wrong iss → JWTInvalid."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
        issuer="wrong-issuer",
    )
    with pytest.raises(JWTInvalid):
        verify_token(token, public_key_pem=public_key_pem)


def test_jwt_wrong_audience_rejected(public_key_pem, private_key_pem):
    """JWT with wrong aud → JWTInvalid."""
    token = sign_token(
        user_id="u_test",
        license_key="PL-PRO-A1B2-C3D4-E5F6",
        plan_type="pro",
        device_fingerprint=make_device_fingerprint(),
        private_key_pem=private_key_pem,
        audience="wrong-audience",
    )
    with pytest.raises(JWTInvalid):
        verify_token(token, public_key_pem=public_key_pem)


# ── CRL blacklist tests (UT-LIC-050 … UT-LIC-055) ───────────────────


@pytest.mark.asyncio
async def test_crl_blacklisted_jwt_rejected(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-050 / UT-LIC-052: JWT in CRL → JWTRevoked."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    # Activate to get a token
    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )

    # Manually blacklist the jti
    payload = pyjwt.decode(result.access_token, options={"verify_signature": False})
    await redis_client.set(f"{_BLACKLIST_PREFIX}{payload['jti']}", "revoked", ex=900)

    with pytest.raises(JWTRevoked):
        await service.verify_relay_token(result.access_token)


@pytest.mark.asyncio
async def test_crl_ttl_set_correctly(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-051: CRL TTL = JWT remaining lifetime."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )
    old_payload = pyjwt.decode(result.access_token, options={"verify_signature": False})

    # Refresh to blacklist the old token
    new_access, _ = await service.refresh_relay_token(result.access_token)

    # Check the old jti is blacklisted with a reasonable TTL
    ttl = await redis_client.ttl(f"{_BLACKLIST_PREFIX}{old_payload['jti']}")
    # TTL should be close to the remaining lifetime (≤ 900s, > 0)
    assert 0 < ttl <= DEFAULT_ACCESS_TOKEN_TTL


@pytest.mark.asyncio
async def test_admin_revoke_license_blacklists_active_jtis(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-054: admin revocation blacklists all active JTIs."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )
    payload = pyjwt.decode(result.access_token, options={"verify_signature": False})

    # Revoke
    await service.revoke_license(
        user_id=bound_license.user_id,
        reason="user_refund",
        active_jtis=[payload["jti"]],
    )

    # License should be cancelled
    await db_session.refresh(bound_license)
    assert bound_license.status == "cancelled"

    # JWT should be blacklisted
    exists = await redis_client.exists(f"{_BLACKLIST_PREFIX}{payload['jti']}")
    assert exists

    # Verification should fail with JWTRevoked
    with pytest.raises(JWTRevoked):
        await service.verify_relay_token(result.access_token)


# ── Refresh flow tests (UT-LIC-060 … UT-LIC-065) ────────────────────


@pytest.mark.asyncio
async def test_refresh_token_success(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-060 / UT-LIC-065: refresh issues new token and revokes old."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )
    old_payload = pyjwt.decode(result.access_token, options={"verify_signature": False})

    new_access, new_refresh = await service.refresh_relay_token(result.access_token)

    assert new_access != result.access_token
    assert new_refresh != result.refresh_token

    # Old token should be blacklisted
    exists = await redis_client.exists(f"{_BLACKLIST_PREFIX}{old_payload['jti']}")
    assert exists

    # Old token should now be rejected
    with pytest.raises(JWTRevoked):
        await service.verify_relay_token(result.access_token)

    # New token should verify successfully
    verify_result = await service.verify_relay_token(new_access)
    assert verify_result.user_id == bound_license.user_id


@pytest.mark.asyncio
async def test_refresh_expired_within_leeway(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-060: refresh accepts tokens up to 5 min past expiry."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    # Sign a token that expired 2 minutes ago (within 5-min leeway)
    now = int(time.time())
    expired_token = sign_token(
        user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        plan_type="pro",
        device_fingerprint=bound_license.device_fingerprint,
        private_key_pem=private_key_pem,
        ttl=-120,  # expired 2 min ago
    )

    new_access, _ = await service.refresh_relay_token(expired_token)
    assert new_access


@pytest.mark.asyncio
async def test_refresh_expired_beyond_leeway(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """Refresh rejects tokens > 5 min past expiry → JWTExpired."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    expired_token = sign_token(
        user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        plan_type="pro",
        device_fingerprint=bound_license.device_fingerprint,
        private_key_pem=private_key_pem,
        ttl=-400,  # expired ~6.6 min ago, beyond 5-min leeway
    )

    with pytest.raises(JWTExpired):
        await service.refresh_relay_token(expired_token)


@pytest.mark.asyncio
async def test_refresh_revoked_token_rejected(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """UT-LIC-064: already-revoked token cannot be refreshed."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )

    # First refresh succeeds
    new_access, _ = await service.refresh_relay_token(result.access_token)

    # Second refresh with the old (now-blacklisted) token fails
    with pytest.raises(JWTRevoked):
        await service.refresh_relay_token(result.access_token)


# ── Verification flow tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_verify_relay_token_success(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """Verify a valid relay token → returns session info."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )

    verify_result = await service.verify_relay_token(
        result.access_token,
        expected_device_fingerprint=bound_license.device_fingerprint,
    )
    assert verify_result.user_id == bound_license.user_id
    assert verify_result.license_key == bound_license.license_key
    assert verify_result.plan_type == "pro"
    assert verify_result.device_fingerprint == bound_license.device_fingerprint
    assert verify_result.jti


@pytest.mark.asyncio
async def test_verify_relay_token_device_mismatch(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """Verify with wrong device fingerprint header → 403."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )

    with pytest.raises(DeviceFingerprintMismatch):
        await service.verify_relay_token(
            result.access_token,
            expected_device_fingerprint=make_device_fingerprint("wrong"),
        )


@pytest.mark.asyncio
async def test_verify_relay_token_license_inactive(
    db_session, redis_client, private_key_pem, public_key_pem, bound_license
):
    """Verify token after license is suspended → 403."""
    service = _make_service(db_session, redis_client, private_key_pem, public_key_pem)

    result = await service.activate_license(
        jwt_user_id=bound_license.user_id,
        license_key=bound_license.license_key,
        device_fingerprint=bound_license.device_fingerprint,
    )

    # Suspend the license
    bound_license.status = "suspended"
    await db_session.commit()

    with pytest.raises(LicenseSuspended):
        await service.verify_relay_token(result.access_token)


# ── Device fingerprint format tests (UT-LIC-045 / UT-LIC-046) ──────


def test_device_fingerprint_format_valid():
    """UT-LIC-045: valid sha256 fingerprint passes validation."""
    from gateway.services.license_service import LicenseService
    LicenseService._validate_device_fingerprint_format(make_device_fingerprint())


def test_device_fingerprint_format_invalid():
    """UT-LIC-046: invalid fingerprint raises InvalidDeviceFingerprint."""
    from gateway.services.license_service import LicenseService
    with pytest.raises(InvalidDeviceFingerprint):
        LicenseService._validate_device_fingerprint_format("md5:abc123")
    with pytest.raises(InvalidDeviceFingerprint):
        LicenseService._validate_device_fingerprint_format("sha256:short")


def test_license_key_format_valid():
    """Valid license key format passes validation."""
    from gateway.services.license_service import LicenseService
    LicenseService._validate_license_key_format("PL-PRO-A1B2-C3D4-E5F6")


def test_license_key_format_invalid():
    """Invalid license key format raises InvalidLicenseKeyFormat."""
    from gateway.services.license_service import LicenseService
    with pytest.raises(InvalidLicenseKeyFormat):
        LicenseService._validate_license_key_format("INVALID")
    with pytest.raises(InvalidLicenseKeyFormat):
        LicenseService._validate_license_key_format("PL-PRO-abc")

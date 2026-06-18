"""End-to-end test scenarios for the PromiseLink gateway.

These tests exercise the full HTTP request → middleware → endpoint → response
cycle through FastAPI's ``TestClient``. No service methods are mocked — only
the upstream LLM provider is simulated via ``httpx.MockTransport``.

Scenario 1: License activation full flow
    Admin creates license → user activates → gets JWT → calls LLM relay →
    checks usage → refreshes token → revokes license → verifies old token fails.

Scenario 2: Usage quota management
    Activate license (quota 100 tokens) → call LLM relay in green/yellow/red
    zones → verify traffic-light colours via admin API → verify over-quota
    rejection.
"""

from __future__ import annotations

import jwt as pyjwt
from fastapi.testclient import TestClient

from gateway.tests._helpers import (
    make_admin_headers,
    make_device_fingerprint,
    make_license,
    make_license_key,
    make_user_id,
)

# ── Constants ────────────────────────────────────────────────────────

TEST_API_KEY = "pl_gateway_client_dev_key"


# ── Helpers ──────────────────────────────────────────────────────────


def _create_user_jwt(jwt_handler, user_id: str) -> str:
    """Create a user identity JWT (pre-activation, no license bound)."""
    return jwt_handler.create_access_token(
        user_id=user_id,
        license_key="",
        plan_type="pro",
        device_fingerprint="",
    )


def _extract_jti(token: str, settings) -> str:
    """Decode a JWT (without verification) to extract its jti claim."""
    payload = pyjwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        options={"verify_exp": False},
    )
    return payload.get("jti", "")


# ── Scenario 1: License activation full flow ─────────────────────────


class TestE2ELicenseActivationFlow:
    """E2E scenario 1: complete license lifecycle from activation to revocation.

    Verifies the full user journey:
    1. Admin creates a license (directly in the store)
    2. User activates the license via POST /api/v1/pro/license/activate
    3. User receives relay JWT (access + refresh tokens)
    4. User calls LLM relay with the JWT
    5. User checks usage via GET /api/v1/pro/usage
    6. User refreshes the token via POST /api/v1/pro/license/refresh
    7. Admin revokes the license (direct service call)
    8. Old JWT is blacklisted → subsequent calls return 401
    """

    def test_full_license_lifecycle(
        self,
        app_client: TestClient,
        license_store,
        license_service,
        jwt_handler,
        test_settings,
    ):
        """Verify the complete license activation → usage → revocation flow.

        Scenario:
            - Admin creates a license in the store.
            - User activates it and receives relay tokens.
            - User calls the LLM relay endpoint successfully.
            - User queries usage and sees recorded consumption.
            - User refreshes the token and gets new tokens.
            - Admin revokes the license and blacklists the old JWT.
            - The old JWT is rejected with 401 JWT_REVOKED.

        Expected results:
            - Activation returns 200 with access_token and refresh_token.
            - LLM relay returns 200 with content and usage.
            - Usage endpoint returns 200 with non-zero token count.
            - Refresh returns 200 with new tokens.
            - After revocation, old token → 401 JWT_REVOKED.
        """
        # ── Step 1: Admin creates a license ──
        license_key = make_license_key("SCENARIO1")
        user_id = make_user_id("alice")
        device_fp = make_device_fingerprint("alice-laptop")

        lic = make_license(license_key, status="active")
        license_store[license_key] = lic

        # ── Step 2: User activates the license ──
        user_jwt = _create_user_jwt(jwt_handler, user_id)
        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": license_key,
                "device_fingerprint": device_fp,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert resp.status_code == 200, f"Activation failed: {resp.text}"
        activate_data = resp.json()["data"]
        assert activate_data["license"]["license_key"] == license_key
        assert activate_data["license"]["status"] == "active"

        # ── Step 3: User receives relay JWT ──
        access_token = activate_data["tokens"]["access_token"]
        refresh_token = activate_data["tokens"]["refresh_token"]
        assert access_token, "access_token must be non-empty"
        assert refresh_token, "refresh_token must be non-empty"

        relay_headers = {
            "X-API-Key": TEST_API_KEY,
            "Authorization": f"Bearer {access_token}",
        }

        # ── Step 4: User calls LLM relay ──
        relay_resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Hello, world!"}],
                "stream": False,
            },
            headers=relay_headers,
        )
        assert relay_resp.status_code == 200, f"LLM relay failed: {relay_resp.text}"
        relay_data = relay_resp.json()["data"]
        assert relay_data["content"] == "Mock LLM response"
        assert relay_data["usage"]["total_tokens"] == 20

        # ── Step 5: User checks usage ──
        usage_resp = app_client.get(
            "/api/v1/pro/usage",
            headers=relay_headers,
        )
        assert usage_resp.status_code == 200, f"Usage query failed: {usage_resp.text}"
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["used"] == 20
        assert usage_data["quota"]["tokens"]["limit"] == 500000
        assert usage_data["traffic_light"] == "green"

        # ── Step 6: User refreshes the token ──
        refresh_resp = app_client.post(
            "/api/v1/pro/license/refresh",
            json={"refresh_token": refresh_token},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert refresh_resp.status_code == 200, f"Refresh failed: {refresh_resp.text}"
        new_tokens = refresh_resp.json()["data"]
        assert new_tokens["access_token"], "New access_token must be non-empty"
        assert new_tokens["refresh_token"], "New refresh_token must be non-empty"
        assert new_tokens["access_token"] != access_token, "New token must differ"

        # ── Step 7: Admin revokes the license ──
        old_jti = _extract_jti(access_token, test_settings)
        # Blacklist the old access token's jti in Redis (CRL).
        # InMemoryRedis stores data in a plain dict; we set the key directly
        # to avoid cross-thread event-loop issues with the TestClient.
        redis = app_client._app.state.redis  # type: ignore[attr-defined]
        redis._data[f"jwt_blacklist:{old_jti}"] = "revoked"

        # Also revoke via the license service (sets status=cancelled)
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(
                license_service.revoke_license(
                    user_id=user_id,
                    reason="test_revocation",
                    license_key=license_key,
                    active_jtis=[old_jti],
                )
            )
        finally:
            loop.close()

        # ── Step 8: Old token is now revoked ──
        revoked_resp = app_client.get(
            "/api/v1/pro/usage",
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {access_token}",
            },
        )
        assert revoked_resp.status_code == 401, (
            f"Revoked token should be rejected, got {revoked_resp.status_code}"
        )
        error_code = revoked_resp.json()["error"]["code"]
        assert error_code == "JWT_REVOKED", (
            f"Expected JWT_REVOKED, got {error_code}"
        )


# ── Scenario 2: Usage quota management ───────────────────────────────


class TestE2EUsageQuotaManagement:
    """E2E scenario 2: quota enforcement with traffic-light transitions.

    Verifies that the gateway correctly tracks token usage and transitions
    through green → yellow → red traffic-light states, ultimately rejecting
    requests when the quota is exhausted.
    """

    def test_quota_traffic_light_transitions(
        self,
        app_client: TestClient,
        license_store,
        license_service,
        jwt_handler,
        test_settings,
    ):
        """Verify traffic-light transitions as quota is consumed.

        Scenario:
            - Activate a license with quota_limit_tokens=100.
            - Each LLM relay call consumes 20 tokens (10 input + 10 output).
            - Call 1–3: 60 tokens used (60%) → green.
            - Call 4: 80 tokens used (80%) → yellow.
            - Call 5: 100 tokens used (100%) → red.
            - Call 6: quota exceeded → 402 QUOTA_EXCEEDED.

        Expected results:
            - Calls 1–3 succeed and traffic_light is "green".
            - Call 4 succeeds and traffic_light is "yellow".
            - Call 5 succeeds and traffic_light is "red".
            - Call 6 is rejected with 402 QUOTA_EXCEEDED.
            - Admin API shows correct traffic_light for the license.
        """
        # ── Setup: create and activate a license with quota=100 tokens ──
        license_key = make_license_key("QUOTA100")
        user_id = make_user_id("quota-user")
        device_fp = make_device_fingerprint("quota-device")

        lic = make_license(
            license_key,
            status="active",
            quota_limit_tokens=100,
            quota_limit_asr=10,
            quota_limit_tts=10,
            quota_limit_ocr=10,
        )
        license_store[license_key] = lic

        user_jwt = _create_user_jwt(jwt_handler, user_id)
        activate_resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": license_key,
                "device_fingerprint": device_fp,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert activate_resp.status_code == 200
        access_token = activate_resp.json()["data"]["tokens"]["access_token"]
        relay_headers = {
            "X-API-Key": TEST_API_KEY,
            "Authorization": f"Bearer {access_token}",
        }

        # ── Calls 1–3: 60 tokens (60%) → green ──
        for i in range(3):
            resp = app_client.post(
                "/api/v1/pro/relay/llm",
                json={
                    "model": "moka-chat",
                    "messages": [{"role": "user", "content": f"Call {i + 1}"}],
                    "stream": False,
                },
                headers=relay_headers,
            )
            assert resp.status_code == 200, (
                f"Call {i + 1} should succeed (green zone), got {resp.status_code}"
            )

        # Check usage — should be green
        usage_resp = app_client.get("/api/v1/pro/usage", headers=relay_headers)
        assert usage_resp.status_code == 200
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["used"] == 60
        assert usage_data["quota"]["tokens"]["percentage"] == 60.0
        assert usage_data["traffic_light"] == "green", (
            f"Expected green at 60%, got {usage_data['traffic_light']}"
        )

        # ── Call 4: 80 tokens (80%) → yellow ──
        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Call 4"}],
                "stream": False,
            },
            headers=relay_headers,
        )
        assert resp.status_code == 200, (
            f"Call 4 should succeed (yellow zone), got {resp.status_code}"
        )

        usage_resp = app_client.get("/api/v1/pro/usage", headers=relay_headers)
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["used"] == 80
        assert usage_data["quota"]["tokens"]["percentage"] == 80.0
        assert usage_data["traffic_light"] == "yellow", (
            f"Expected yellow at 80%, got {usage_data['traffic_light']}"
        )

        # ── Call 5: 100 tokens (100%) → red ──
        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Call 5"}],
                "stream": False,
            },
            headers=relay_headers,
        )
        assert resp.status_code == 200, (
            f"Call 5 should succeed (reaching 100%), got {resp.status_code}"
        )

        usage_resp = app_client.get("/api/v1/pro/usage", headers=relay_headers)
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["used"] == 100
        assert usage_data["quota"]["tokens"]["percentage"] == 100.0
        assert usage_data["traffic_light"] == "red", (
            f"Expected red at 100%, got {usage_data['traffic_light']}"
        )

        # ── Call 6: quota exceeded → 402 ──
        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Call 6 - over quota"}],
                "stream": False,
            },
            headers=relay_headers,
        )
        assert resp.status_code == 402, (
            f"Call 6 should be rejected (quota exceeded), got {resp.status_code}"
        )
        error = resp.json()["error"]
        assert error["code"] == "QUOTA_EXCEEDED", (
            f"Expected QUOTA_EXCEEDED, got {error['code']}"
        )

        # ── Verify admin API shows correct traffic light ──
        admin_headers = make_admin_headers(test_settings)
        admin_resp = app_client.get(
            f"/api/v1/admin/usage/users/{license_key}",
            headers=admin_headers,
        )
        assert admin_resp.status_code == 200, (
            f"Admin usage detail failed: {admin_resp.text}"
        )
        admin_data = admin_resp.json()["data"]
        assert admin_data["license_key"] == license_key
        assert admin_data["traffic_light"] == "red", (
            f"Admin API should show red, got {admin_data['traffic_light']}"
        )
        assert admin_data["quota_used_tokens"] == 100
        assert admin_data["quota_limit_tokens"] == 100
        assert admin_data["llm_calls"] == 5, (
            f"Expected 5 LLM calls, got {admin_data['llm_calls']}"
        )

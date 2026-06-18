"""P0 security tests for the PromiseLink gateway.

Each test verifies a critical security control (P0 priority). Tests exercise
the full HTTP stack via ``TestClient`` — no middleware or endpoint logic is
mocked.

Test matrix:
    1.  JWT forgery          — invalid signature → 401
    2.  JWT expired          — past-exp token → 401
    3.  JWT algorithm confusion — HS256 token against RS256 config → 401
    4.  Admin auth: no key   — missing X-Admin-API-Key → 401
    5.  Admin auth: bad key  — wrong X-Admin-API-Key → 401
    6.  Quota bypass         — over-quota relay call → 402
    7.  License hijacking    — second user activates same license → 409
    8.  SQL injection        — SQL in license_key → 422 (Pydantic pattern)
    9.  Path traversal       — traversal in license_key → 422 (Pydantic pattern)
    10. XSS                  — script in request body → accepted but not executed
"""

from __future__ import annotations

import time

import jwt as pyjwt
from fastapi.testclient import TestClient

from gateway.tests._helpers import (
    make_device_fingerprint,
    make_license,
    make_license_key,
    make_user_id,
)

# ── Constants ────────────────────────────────────────────────────────

TEST_API_KEY = "pl_gateway_client_dev_key"
TEST_ADMIN_API_KEY = "dev-admin-api-key-min-32-chars-padding!!"


# ── 1. JWT Forgery ───────────────────────────────────────────────────


class TestJWTForgery:
    """P0-1: Verify that JWTs with invalid signatures are rejected."""

    def test_forged_jwt_rejected(self, app_client: TestClient, test_settings):
        """A JWT signed with a different secret must be rejected with 401.

        Scenario:
            - An attacker crafts a JWT with a guessed/leaked wrong secret key.
            - The attacker sends it in the Authorization header to a protected
              endpoint (GET /api/v1/pro/usage).

        Expected result:
            - HTTP 401 with error code JWT_INVALID.
        """
        # Forge a JWT with a wrong secret
        now = int(time.time())
        forged_payload = {
            "user_id": "u_attacker",
            "license_key": "PL-PRO-ATTACK-0000-0000",
            "plan_type": "pro",
            "device_fingerprint": make_device_fingerprint("attacker"),
            "jti": "forged-jti-001",
            "iat": now,
            "exp": now + 3600,
            "iss": test_settings.jwt_issuer,
            "aud": test_settings.jwt_audience,
            "token_type": "access",
        }
        forged_token = pyjwt.encode(
            forged_payload,
            "wrong-secret-key-that-is-32-chars-long!!",
            algorithm=test_settings.jwt_algorithm,
        )

        resp = app_client.get(
            "/api/v1/pro/usage",
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {forged_token}",
            },
        )
        assert resp.status_code == 401, (
            f"Forged JWT should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "JWT_INVALID"


# ── 2. JWT Expired ───────────────────────────────────────────────────


class TestJWTExpired:
    """P0-2: Verify that expired JWTs are rejected."""

    def test_expired_jwt_rejected(self, app_client: TestClient, jwt_handler, test_settings):
        """An expired JWT must be rejected with 401 JWT_EXPIRED.

        Scenario:
            - A legitimate token has passed its expiry time.
            - The user attempts to use it for an authenticated request.

        Expected result:
            - HTTP 401 with error code JWT_EXPIRED.
        """
        # Create a token that's already expired
        token = jwt_handler.create_access_token(
            user_id="u_expired_user",
            license_key="PL-PRO-EXPIR-0000-0000",
            plan_type="pro",
            device_fingerprint=make_device_fingerprint("expired-device"),
        )

        # Decode without verifying expiry, then re-encode with past exp
        payload = pyjwt.decode(
            token,
            test_settings.jwt_secret_key,
            algorithms=[test_settings.jwt_algorithm],
            audience=test_settings.jwt_audience,
            options={"verify_exp": False},
        )
        payload["exp"] = int(time.time()) - 3600  # Expired 1 hour ago
        expired_token = pyjwt.encode(
            payload,
            test_settings.jwt_secret_key,
            algorithm=test_settings.jwt_algorithm,
        )

        resp = app_client.get(
            "/api/v1/pro/usage",
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {expired_token}",
            },
        )
        assert resp.status_code == 401, (
            f"Expired JWT should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "JWT_EXPIRED"


# ── 3. JWT Algorithm Confusion ──────────────────────────────────────


class TestJWTAlgorithmConfusion:
    """P0-3: Verify that JWTs using a different algorithm are rejected."""

    def test_wrong_algorithm_rejected(self, app_client: TestClient, test_settings):
        """A JWT signed with HS256 when the server expects a different algorithm
        must be rejected.

        Scenario:
            - The gateway is configured with jwt_algorithm=HS256 (test default).
            - An attacker signs a token with the "none" algorithm or a
              different algorithm to bypass verification.

        Expected result:
            - HTTP 401 with error code JWT_INVALID.
        """
        now = int(time.time())
        payload = {
            "user_id": "u_algo_attacker",
            "license_key": "PL-PRO-ALGOO-0000-0000",
            "plan_type": "pro",
            "device_fingerprint": make_device_fingerprint("algo-attacker"),
            "jti": "algo-confusion-jti",
            "iat": now,
            "exp": now + 3600,
            "iss": test_settings.jwt_issuer,
            "aud": test_settings.jwt_audience,
            "token_type": "access",
        }

        # Try signing with a different algorithm than configured
        # The server expects HS256, so RS256 should be rejected
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        rs256_token = pyjwt.encode(payload, private_pem, algorithm="RS256")

        resp = app_client.get(
            "/api/v1/pro/usage",
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {rs256_token}",
            },
        )
        assert resp.status_code == 401, (
            f"Wrong-algorithm JWT should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "JWT_INVALID"


# ── 4. Admin Auth: No Key ────────────────────────────────────────────


class TestAdminAuthNoKey:
    """P0-4: Verify that admin endpoints reject requests without X-Admin-API-Key."""

    def test_no_admin_key_rejected(self, app_client: TestClient, test_settings):
        """A request to an admin endpoint without X-Admin-API-Key must return 401.

        Scenario:
            - An attacker calls GET /api/v1/admin/usage/summary with only a
              Bearer token (no X-Admin-API-Key header).

        Expected result:
            - HTTP 401 with error code API_KEY_INVALID.
        """
        from gateway.tests._helpers import make_admin_jwt

        admin_jwt = make_admin_jwt(test_settings)
        resp = app_client.get(
            "/api/v1/admin/usage/summary",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )
        assert resp.status_code == 401, (
            f"Missing admin key should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"


# ── 5. Admin Auth: Wrong Key ─────────────────────────────────────────


class TestAdminAuthWrongKey:
    """P0-5: Verify that admin endpoints reject wrong X-Admin-API-Key values."""

    def test_wrong_admin_key_rejected(self, app_client: TestClient, test_settings):
        """A request with an incorrect X-Admin-API-Key must return 401.

        Scenario:
            - An attacker guesses an admin API key and sends it with a
              valid-looking admin JWT.

        Expected result:
            - HTTP 401 with error code API_KEY_INVALID.
        """
        from gateway.tests._helpers import make_admin_jwt

        admin_jwt = make_admin_jwt(test_settings)
        resp = app_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": "wrong-admin-key-xxxxxxxxxxxxxxxxxxx",
                "Authorization": f"Bearer {admin_jwt}",
            },
        )
        assert resp.status_code == 401, (
            f"Wrong admin key should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"


# ── 6. Quota Bypass ──────────────────────────────────────────────────


class TestQuotaBypass:
    """P0-6: Verify that over-quota requests are rejected."""

    def test_over_quota_rejected(
        self,
        app_client: TestClient,
        license_store,
        jwt_handler,
        activated_license_and_token,
    ):
        """A relay call that exceeds the token quota must be rejected with 402.

        Scenario:
            - A license has quota_limit_tokens=20 (enough for one call).
            - The first LLM relay call succeeds (20 tokens consumed).
            - A second call is attempted — quota is now exhausted.

        Expected result:
            - First call: 200 OK.
            - Second call: 402 QUOTA_EXCEEDED.
        """
        license_key = activated_license_and_token["license_key"]
        access_token = activated_license_and_token["access_token"]

        # Set quota to exactly 20 tokens (one call consumes 20)
        lic = license_store[license_key]
        lic.quota_limit_tokens = 20
        lic.quota_used_tokens = 0

        headers = {
            "X-API-Key": TEST_API_KEY,
            "Authorization": f"Bearer {access_token}",
        }

        # First call — should succeed (20 tokens consumed, 100%)
        resp1 = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "First call"}],
                "stream": False,
            },
            headers=headers,
        )
        assert resp1.status_code == 200, (
            f"First call should succeed, got {resp1.status_code}: {resp1.text}"
        )

        # Second call — should be rejected (quota exceeded)
        resp2 = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Second call"}],
                "stream": False,
            },
            headers=headers,
        )
        assert resp2.status_code == 402, (
            f"Over-quota call should be rejected with 402, got {resp2.status_code}"
        )
        assert resp2.json()["error"]["code"] == "QUOTA_EXCEEDED"


# ── 7. License Hijacking ─────────────────────────────────────────────


class TestLicenseHijacking:
    """P0-7: Verify that a license bound to one user cannot be activated by another."""

    def test_hijack_rejected(
        self,
        app_client: TestClient,
        license_store,
        jwt_handler,
    ):
        """A second user attempting to activate an already-bound license must
        get 409.

        Scenario:
            - User A activates license L.
            - User B attempts to activate the same license L.

        Expected result:
            - User A activation: 200 OK.
            - User B activation: 409 LICENSE_ALREADY_ACTIVATED.
        """
        license_key = make_license_key("HIJACK")
        device_a = make_device_fingerprint("device-a")
        device_b = make_device_fingerprint("device-b")
        user_a = make_user_id("user-a")
        user_b = make_user_id("user-b")

        lic = make_license(license_key, status="active")
        license_store[license_key] = lic

        # User A activates
        jwt_a = jwt_handler.create_access_token(
            user_id=user_a, license_key="", plan_type="pro", device_fingerprint=""
        )
        resp_a = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": license_key, "device_fingerprint": device_a},
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {jwt_a}",
            },
        )
        assert resp_a.status_code == 200, (
            f"User A activation should succeed, got {resp_a.status_code}"
        )

        # User B tries to hijack
        jwt_b = jwt_handler.create_access_token(
            user_id=user_b, license_key="", plan_type="pro", device_fingerprint=""
        )
        resp_b = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": license_key, "device_fingerprint": device_b},
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {jwt_b}",
            },
        )
        assert resp_b.status_code == 409, (
            f"User B hijack should be rejected with 409, got {resp_b.status_code}"
        )
        assert resp_b.json()["error"]["code"] == "LICENSE_ALREADY_ACTIVATED"


# ── 8. SQL Injection ─────────────────────────────────────────────────


class TestSQLInjection:
    """P0-8: Verify that SQL injection in the license_key field is blocked."""

    def test_sql_injection_in_license_key_rejected(self, app_client: TestClient, jwt_handler):
        """A license_key containing SQL injection payloads must be rejected by
        Pydantic validation (422) before reaching the database.

        Scenario:
            - An attacker submits a license_key like
              ``' OR '1'='1'; DROP TABLE licenses; --``.
            - The Pydantic pattern validator rejects it.

        Expected result:
            - HTTP 422 (Pydantic validation error).
        """
        sql_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE licenses; --",
            "PL-PRO-AAAA-BBBB-CCCC' UNION SELECT * FROM users--",
            "PL-PRO-AAAA-BBBB-CCCC'; --",
        ]

        user_jwt = jwt_handler.create_access_token(
            user_id="u_sqli_attacker", license_key="", plan_type="pro"
        )

        for payload in sql_payloads:
            resp = app_client.post(
                "/api/v1/pro/license/activate",
                json={
                    "license_key": payload,
                    "device_fingerprint": make_device_fingerprint("sqli"),
                },
                headers={
                    "X-API-Key": TEST_API_KEY,
                    "Authorization": f"Bearer {user_jwt}",
                },
            )
            assert resp.status_code == 422, (
                f"SQL injection payload '{payload}' should be rejected with 422, "
                f"got {resp.status_code}"
            )


# ── 9. Path Traversal ────────────────────────────────────────────────


class TestPathTraversal:
    """P0-9: Verify that path traversal in API parameters is blocked."""

    def test_path_traversal_in_license_key_rejected(self, app_client: TestClient, jwt_handler):
        """A license_key containing path traversal sequences must be rejected
        by Pydantic validation (422).

        Scenario:
            - An attacker submits a license_key like
              ``../../etc/passwd`` or ``PL-PRO-..\\..\\..\\etc``.
            - The Pydantic pattern validator rejects it.

        Expected result:
            - HTTP 422 (Pydantic validation error).
        """
        traversal_payloads = [
            "../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "PL-PRO-..../..../..../etc",
            "PL-PRO-AAAA-BBBB-CCCC/../../../etc/passwd",
            "....//....//....//etc/shadow",
        ]

        user_jwt = jwt_handler.create_access_token(
            user_id="u_traversal_attacker", license_key="", plan_type="pro"
        )

        for payload in traversal_payloads:
            resp = app_client.post(
                "/api/v1/pro/license/activate",
                json={
                    "license_key": payload,
                    "device_fingerprint": make_device_fingerprint("traversal"),
                },
                headers={
                    "X-API-Key": TEST_API_KEY,
                    "Authorization": f"Bearer {user_jwt}",
                },
            )
            assert resp.status_code == 422, (
                f"Path traversal payload '{payload}' should be rejected with 422, "
                f"got {resp.status_code}"
            )


# ── 10. XSS ──────────────────────────────────────────────────────────


class TestXSS:
    """P0-10: Verify that XSS payloads in request bodies do not cause harm."""

    def test_xss_in_messages_accepted_but_not_executed(
        self,
        app_client: TestClient,
        license_store,
        activated_license_and_token,
    ):
        """An XSS payload in the LLM messages field is accepted by the API
        (it's valid JSON content) but is treated as plain text — it does not
        execute in the gateway or alter the response structure.

        Scenario:
            - A user sends an LLM relay request with a message containing
              ``<script>alert('xss')</script>``.
            - The gateway forwards it to the LLM provider (mocked).
            - The response content is the mock LLM response, not the script.

        Expected result:
            - HTTP 200 (the payload is valid JSON, accepted by Pydantic).
            - Response content is the mock LLM response, not the injected script.
            - The XSS payload is not reflected in the response.
        """
        access_token = activated_license_and_token["access_token"]
        xss_payload = "<script>alert('XSS')</script>"

        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": xss_payload}],
                "stream": False,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {access_token}",
            },
        )
        assert resp.status_code == 200, (
            f"XSS payload in content should be accepted as valid input, "
            f"got {resp.status_code}"
        )

        # The response content should be the mock LLM response, not the script
        data = resp.json()["data"]
        assert data["content"] == "Mock LLM response", (
            f"Response should be mock LLM response, not reflected XSS: {data['content']}"
        )
        # The XSS payload must not appear in the response
        assert xss_payload not in resp.text, (
            "XSS payload must not be reflected in the response body"
        )

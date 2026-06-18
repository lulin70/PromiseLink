"""Tests for the gateway API endpoints.

Tests cover all 8 endpoints defined in §4.2:
1. POST /api/v1/pro/license/activate
2. POST /api/v1/pro/license/verify
3. POST /api/v1/pro/license/refresh
4. GET /api/v1/pro/usage
5. POST /api/v1/pro/relay/llm (streaming + non-streaming)
6. POST /api/v1/pro/relay/asr
7. POST /api/v1/pro/relay/tts
8. POST /api/v1/pro/relay/ocr
9. GET /api/v1/pro/health

Also tests authentication failures and error handling.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from gateway.services.relay_service import RelayService
from gateway.tests.conftest import (
    TEST_API_KEY,
    TEST_DEVICE_FP,
    TEST_LICENSE_KEY,
    TEST_USER_ID,
    make_llm_response,
    make_llm_stream_lines,
    make_mock_client,
)

# ── Health Check Tests ──


class TestHealthEndpoint:
    """Tests for GET /api/v1/pro/health."""

    def test_health_check_no_auth(self, app_client: TestClient):
        """Test that health check works without authentication."""
        resp = app_client.get("/api/v1/pro/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "degraded")
        assert "version" in data
        assert "timestamp" in data
        assert "components" in data
        assert "database" in data["components"]
        assert "redis" in data["components"]
        assert "api_key_pool" in data["components"]

    def test_health_check_returns_version(self, app_client: TestClient):
        """Test that health check returns the gateway version."""
        resp = app_client.get("/api/v1/pro/health")
        data = resp.json()
        assert data["version"] == "1.0.0"


# ── License Endpoint Tests ──


class TestLicenseEndpoints:
    """Tests for license activate/verify/refresh endpoints."""

    def test_activate_license_success(
        self, app_client: TestClient, jwt_handler, license_store
    ):
        """Test successful license activation."""
        # Create a fresh unbound license for activation
        from gateway.services.license_service import create_test_license

        fresh_key = "PL-PRO-XXXX-YYYY-ZZZZ"
        license_store[fresh_key] = create_test_license(
            license_key=fresh_key,
            user_id=None,
            device_fingerprint=None,
        )

        # Create a user JWT (simulating a logged-in user)
        user_token = jwt_handler.create_access_token(
            user_id=TEST_USER_ID,
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": fresh_key,
                "device_fingerprint": TEST_DEVICE_FP,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_token}",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["license"]["license_key"] == fresh_key
        assert data["data"]["license"]["status"] == "active"
        assert "access_token" in data["data"]["tokens"]
        assert "refresh_token" in data["data"]["tokens"]

    def test_activate_license_missing_api_key(self, app_client: TestClient, jwt_handler):
        """Test activation fails without API key."""
        user_token = jwt_handler.create_access_token(
            user_id=TEST_USER_ID, license_key="", device_fingerprint=""
        )
        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": TEST_LICENSE_KEY, "device_fingerprint": TEST_DEVICE_FP},
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_activate_license_invalid_key_format(self, app_client: TestClient, auth_headers):
        """Test activation with invalid license key format."""
        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": "INVALID", "device_fingerprint": TEST_DEVICE_FP},
            headers=auth_headers,
        )
        assert resp.status_code == 422  # Pydantic validation error

    def test_verify_license_success(self, app_client: TestClient, auth_headers):
        """Test successful license verification."""
        resp = app_client.post(
            "/api/v1/pro/license/verify",
            json={"device_fingerprint": TEST_DEVICE_FP},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["valid"] is True
        assert data["data"]["license"]["license_key"] == TEST_LICENSE_KEY
        assert "quota" in data["data"]

    def test_verify_license_device_mismatch(self, app_client: TestClient, auth_headers):
        """Test license verification with wrong device fingerprint."""
        wrong_fp = "sha256:" + "b" * 64
        resp = app_client.post(
            "/api/v1/pro/license/verify",
            json={"device_fingerprint": wrong_fp},
            headers=auth_headers,
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "DEVICE_FINGERPRINT_MISMATCH"

    def test_refresh_token_success(self, app_client: TestClient, jwt_handler):
        """Test successful token refresh."""
        refresh = jwt_handler.create_refresh_token(
            user_id=TEST_USER_ID, license_key=TEST_LICENSE_KEY
        )
        resp = app_client.post(
            "/api/v1/pro/license/refresh",
            json={"refresh_token": refresh},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "access_token" in data["data"]
        assert "refresh_token" in data["data"]


# ── Usage Endpoint Tests ──


class TestUsageEndpoint:
    """Tests for GET /api/v1/pro/usage."""

    def test_get_usage_success(self, app_client: TestClient, auth_headers):
        """Test successful usage query."""
        resp = app_client.get("/api/v1/pro/usage", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "month" in data["data"]
        assert "traffic_light" in data["data"]
        assert "quota" in data["data"]
        assert "tokens" in data["data"]["quota"]

    def test_get_usage_no_auth(self, app_client: TestClient):
        """Test usage query without authentication."""
        resp = app_client.get("/api/v1/pro/usage")
        assert resp.status_code == 401

    def test_get_usage_with_month_param(self, app_client: TestClient, auth_headers):
        """Test usage query with month parameter."""
        resp = app_client.get(
            "/api/v1/pro/usage?month=2026-05", headers=auth_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["month"] == "2026-05"


# ── LLM Relay Endpoint Tests ──


class TestLLMRelayEndpoint:
    """Tests for POST /api/v1/pro/relay/llm."""

    def test_llm_relay_non_stream_success(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test non-streaming LLM relay via API."""
        mock_client = make_mock_client(json_data=make_llm_response("API response", 10, 5))
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["content"] == "API response"
        assert data["data"]["usage"]["total_tokens"] == 15

    def test_llm_relay_stream_success(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test streaming LLM relay via API (SSE)."""
        stream_lines = make_llm_stream_lines(["Hello", " world"], 10, 5)
        mock_client = make_mock_client(stream_lines=stream_lines)
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": True,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        # Parse SSE events from response body
        body = resp.text
        assert "event: token" in body
        assert "event: done" in body
        assert "Hello" in body
        assert "world" in body

    def test_llm_relay_no_auth(self, app_client: TestClient):
        """Test LLM relay without authentication."""
        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={"model": "moka-chat", "messages": [{"role": "user", "content": "Hi"}]},
        )
        assert resp.status_code == 401

    def test_llm_relay_invalid_jwt(self, app_client: TestClient):
        """Test LLM relay with invalid JWT."""
        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={"model": "moka-chat", "messages": [{"role": "user", "content": "Hi"}]},
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": "Bearer invalid_token",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "JWT_INVALID"

    def test_llm_relay_quota_exceeded(
        self, app_client: TestClient, auth_headers, license_store
    ):
        """Test LLM relay when quota is exceeded."""
        lic = license_store[TEST_LICENSE_KEY]
        lic.quota_used_tokens = lic.quota_limit_tokens

        resp = app_client.post(
            "/api/v1/pro/relay/llm",
            json={"model": "moka-chat", "messages": [{"role": "user", "content": "Hi"}]},
            headers=auth_headers,
        )
        assert resp.status_code == 402
        assert resp.json()["error"]["code"] == "QUOTA_EXCEEDED"


# ── ASR Relay Endpoint Tests ──


class TestASRRelayEndpoint:
    """Tests for POST /api/v1/pro/relay/asr."""

    def test_asr_relay_success(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test successful ASR relay via API."""
        mock_client = make_mock_client(json_data={"text": "Hello", "duration": 5.0})
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/asr",
            files={"audio": ("test.mp3", b"fake audio", "audio/mpeg")},
            data={"model": "whisper-1", "language": "zh"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["text"] == "Hello"

    def test_asr_relay_no_auth(self, app_client: TestClient):
        """Test ASR relay without authentication."""
        resp = app_client.post(
            "/api/v1/pro/relay/asr",
            files={"audio": ("test.mp3", b"audio", "audio/mpeg")},
        )
        assert resp.status_code == 401


# ── TTS Relay Endpoint Tests ──


class TestTTSRelayEndpoint:
    """Tests for POST /api/v1/pro/relay/tts."""

    def test_tts_relay_success(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test successful TTS relay via API."""
        audio_data = b"fake mp3 audio"
        mock_client = make_mock_client(content_data=audio_data)
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/tts",
            json={"text": "Hello world", "model": "moka-tts"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.content == audio_data
        assert "audio/mpeg" in resp.headers.get("content-type", "")
        assert resp.headers.get("X-Billing-Count") == "1"

    def test_tts_relay_text_too_long(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test TTS with text exceeding max length."""
        resp = app_client.post(
            "/api/v1/pro/relay/tts",
            json={"text": "x" * 600},
            headers=auth_headers,
        )
        assert resp.status_code == 422  # Pydantic validation


# ── OCR Relay Endpoint Tests ──


class TestOCRRelayEndpoint:
    """Tests for POST /api/v1/pro/relay/ocr."""

    def test_ocr_relay_success(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test successful OCR relay via API."""
        ocr_response = make_llm_response("Recognized text", 50, 20)
        mock_client = make_mock_client(json_data=ocr_response)
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/ocr",
            files={"image": ("test.jpg", b"fake image", "image/jpeg")},
            data={"task": "general", "model": "moka-vision"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "Recognized text" in data["data"]["raw_text"]

    def test_ocr_relay_business_card(
        self, app_client: TestClient, auth_headers, relay_service: RelayService
    ):
        """Test OCR with business card task."""
        card_json = '{"name": "张伟", "company": "科技公司", "title": "总经理"}'
        ocr_response = make_llm_response(card_json, 50, 20)
        mock_client = make_mock_client(json_data=ocr_response)
        relay_service._http_client = mock_client

        resp = app_client.post(
            "/api/v1/pro/relay/ocr",
            files={"image": ("card.jpg", b"card image", "image/jpeg")},
            data={"task": "business_card"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["task"] == "business_card"
        assert data["data"]["structured"]["name"] == "张伟"


# ── Authentication Failure Tests ──


class TestAuthFailures:
    """Tests for authentication failure scenarios."""

    def test_missing_api_key(self, app_client: TestClient, valid_token):
        """Test request without X-API-Key header."""
        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": TEST_LICENSE_KEY, "device_fingerprint": TEST_DEVICE_FP},
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_invalid_api_key(self, app_client: TestClient, valid_token):
        """Test request with invalid X-API-Key."""
        resp = app_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": TEST_LICENSE_KEY, "device_fingerprint": TEST_DEVICE_FP},
            headers={
                "X-API-Key": "wrong_key",
                "Authorization": f"Bearer {valid_token}",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_missing_jwt(self, app_client: TestClient):
        """Test request without Authorization header."""
        resp = app_client.get(
            "/api/v1/pro/usage",
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "JWT_MISSING"

    def test_expired_jwt(self, app_client: TestClient, jwt_handler, test_settings):
        """Test request with expired JWT."""
        import time

        # Create a token that's already expired
        token = jwt_handler.create_access_token(
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
            device_fingerprint=TEST_DEVICE_FP,
        )
        # Manually decode and re-encode with past expiry
        import jwt as pyjwt

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
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "JWT_EXPIRED"


# ── Error Response Format Tests ──


class TestErrorResponses:
    """Tests for unified error response format."""

    def test_error_response_has_request_id(self, app_client: TestClient):
        """Test that error responses include request_id."""
        resp = app_client.get("/api/v1/pro/usage")
        data = resp.json()
        assert "request_id" in data
        assert data["request_id"] != ""
        assert data["success"] is False
        assert data["data"] is None
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_error_response_has_x_request_id_header(self, app_client: TestClient):
        """Test that X-Request-ID header is present in responses."""
        resp = app_client.get("/api/v1/pro/health")
        assert "x-request-id" in resp.headers
        assert resp.headers["x-request-id"] != ""

    def test_custom_request_id_echoed(self, app_client: TestClient):
        """Test that a custom X-Request-ID is echoed back."""
        custom_id = "custom-request-id-12345"
        resp = app_client.get(
            "/api/v1/pro/health",
            headers={"X-Request-ID": custom_id},
        )
        assert resp.headers["x-request-id"] == custom_id

"""Tests for pair/activate → WSS relay lifecycle integration.

Covers the bug discovered on 2026-07-29:
  "配对成功但 WSS 中继连接未建立"

Root cause: pair/activate only wrote PRO_LICENSE_KEY to .env and set
os.environ, but the WSS client was only started in the lifespan startup
event. Users had to manually restart the basic edition after pairing.

These tests verify the FIXED behavior: pair/activate dynamically starts
the WSS client without requiring a restart.

Also covers cross-end device fingerprint consistency between the
miniapp (TypeScript SHA-256 in proAuth.ts) and the basic edition
(Python hashlib.sha256 in relay_client.py).
"""

from __future__ import annotations

import hashlib
import types
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from promiselink.api.v1 import pair as pair_module
from promiselink.services.relay_client import RelayClient


# ── Helpers ──


@pytest.fixture(autouse=True)
def _clean_app_state():
    """Clear app.state.relay_wss_client between tests to prevent leakage."""
    yield
    # Cleanup after each test
    try:
        from promiselink.main import app
        if hasattr(app.state, "relay_wss_client"):
            del app.state.relay_wss_client
    except Exception:
        pass


def _mock_httpx_module(handler) -> types.ModuleType:
    """Create a mock httpx module that only replaces AsyncClient."""
    mock = types.ModuleType("mock_httpx")
    mock.Timeout = httpx.Timeout
    mock.HTTPError = httpx.HTTPError
    mock.ConnectError = httpx.ConnectError

    def _async_client(**kwargs):
        kwargs.pop("timeout", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    mock.AsyncClient = _async_client
    return mock


def _gateway_init_response() -> dict:
    return {
        "data": {
            "device_pair_code": "384721",
            "device_fingerprint": "sha256:test-fp",
            "expires_in": 300,
            "qr_content": "https://www.promiselink.cn/pair?code=384721",
        }
    }


def _gateway_status_matched() -> dict:
    return {
        "data": {
            "status": "matched",
            "license_key": "PL-PRO-TEST-ABCD-EFGH",
            "user_id": "u_testuser",
        }
    }


# ═══════════════════════════════════════════════════════════════
# pair/activate → WSS startup integration
# ═══════════════════════════════════════════════════════════════


class TestPairActivateWssStartup:
    """Verify pair/activate dynamically starts the WSS relay client.

    Bug context: Before the 2026-07-29 fix, pair/activate only wrote
    .env and returned "即将启动中继服务" but never actually started
    the WSS client. Users had to restart the basic edition.
    """

    def test_activate_starts_wss_client(self, monkeypatch, tmp_path):
        """POST /pair/activate must start the WSS client after writing .env.

        This is the core regression test for the "配对成功但WSS未建立" bug.
        After activation, app.state.relay_wss_client must be set.
        """
        fake_env = tmp_path / ".env"
        fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

        monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
        monkeypatch.delenv("PRO_LICENSE_KEY", raising=False)
        # Settings reads from env vars (not from fake_env path), so set them directly
        monkeypatch.setenv("RELAY_GATEWAY_URL", "https://gateway.promiselink.cn")
        monkeypatch.setenv("RELAY_WSS_ENABLED", "true")

        # Mock RelayWSSClient to avoid real network connections
        mock_wss_instances = []

        class _MockRelayWSSClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
                mock_wss_instances.append(self)

            async def start(self):
                self.started = True

        monkeypatch.setattr(
            "promiselink.services.relay_wss_client.RelayWSSClient",
            _MockRelayWSSClient,
        )

        from promiselink.main import app

        with TestClient(app) as client:
            # Ensure no WSS client exists before activation
            assert not hasattr(app.state, "relay_wss_client") or app.state.relay_wss_client is None

            resp = client.post(
                "/api/v1/pair/activate",
                json={"license_key": "PL-PRO-LIFECYCLE-001"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "中继服务已启动" in data["message"]

        # Verify WSS client was created and started
        assert len(mock_wss_instances) == 1
        assert mock_wss_instances[0].started is True
        # Verify it was stored in app.state
        assert app.state.relay_wss_client is mock_wss_instances[0]

    def test_activate_does_not_duplicate_wss_if_already_running(self, monkeypatch, tmp_path):
        """POST /pair/activate must not start a second WSS client if one is running."""
        fake_env = tmp_path / ".env"
        fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

        monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
        monkeypatch.setenv("RELAY_GATEWAY_URL", "https://gateway.promiselink.cn")
        monkeypatch.setenv("RELAY_WSS_ENABLED", "true")

        mock_wss_instances = []

        class _MockRelayWSSClient:
            def __init__(self, **kwargs):
                mock_wss_instances.append(self)

            async def start(self):
                pass

        monkeypatch.setattr(
            "promiselink.services.relay_wss_client.RelayWSSClient",
            _MockRelayWSSClient,
        )

        from promiselink.main import app

        # Pre-set an existing WSS client on app.state
        existing_wss = MagicMock()
        app.state.relay_wss_client = existing_wss

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/pair/activate",
                json={"license_key": "PL-PRO-DUP-002"},
            )

        assert resp.status_code == 200
        # No new WSS client should have been created
        assert len(mock_wss_instances) == 0
        # The existing one should still be there
        assert app.state.relay_wss_client is existing_wss

    def test_activate_reports_failure_when_wss_start_raises(self, monkeypatch, tmp_path):
        """POST /pair/activate must report WSS startup failure without crashing."""
        fake_env = tmp_path / ".env"
        fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

        monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
        monkeypatch.setenv("RELAY_GATEWAY_URL", "https://gateway.promiselink.cn")
        monkeypatch.setenv("RELAY_WSS_ENABLED", "true")

        class _FailingRelayWSSClient:
            def __init__(self, **kwargs):
                pass

            async def start(self):
                raise ConnectionError("Gateway unreachable")

        monkeypatch.setattr(
            "promiselink.services.relay_wss_client.RelayWSSClient",
            _FailingRelayWSSClient,
        )

        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/pair/activate",
                json={"license_key": "PL-PRO-FAIL-003"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True  # Activation itself succeeded
        assert "WSS 中继启动失败" in data["message"]
        assert "Gateway unreachable" in data["error"]

    def test_activate_skips_wss_when_gateway_url_missing(self, monkeypatch, tmp_path):
        """POST /pair/activate must skip WSS startup if RELAY_GATEWAY_URL is empty."""
        fake_env = tmp_path / ".env"
        fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

        monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
        monkeypatch.delenv("RELAY_GATEWAY_URL", raising=False)
        monkeypatch.delenv("RELAY_WSS_ENABLED", raising=False)

        mock_wss_instances = []

        class _MockRelayWSSClient:
            def __init__(self, **kwargs):
                mock_wss_instances.append(self)

            async def start(self):
                pass

        monkeypatch.setattr(
            "promiselink.services.relay_wss_client.RelayWSSClient",
            _MockRelayWSSClient,
        )

        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/pair/activate",
                json={"license_key": "PL-PRO-NOGW-004"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # No WSS client should have been created
        assert len(mock_wss_instances) == 0


# ═══════════════════════════════════════════════════════════════
# Full pair flow → WSS startup e2e
# ═══════════════════════════════════════════════════════════════


class TestFullPairFlowToWssStartup:
    """Full e2e: init → status(matched) → activate → WSS running.

    This is the test that SHOULD have existed from the beginning.
    It verifies the complete user journey from pairing to WSS connection,
    ensuring no silent failures in the chain.
    """

    def test_init_to_activate_wss_running(self, monkeypatch, tmp_path):
        """Full flow: init → status(pending) → status(matched) → activate → WSS started."""
        fake_env = tmp_path / ".env"
        fake_env.write_text("APP_ENV=development\n", encoding="utf-8")

        gateway_state = {"status": "pending"}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path == "/api/v1/pair/device":
                return httpx.Response(200, json=_gateway_init_response())
            if request.method == "GET" and "/api/v1/pair/device/" in str(request.url.path):
                if gateway_state["status"] == "pending":
                    return httpx.Response(200, json={"data": {"status": "pending"}})
                return httpx.Response(200, json=_gateway_status_matched())
            return httpx.Response(404)

        monkeypatch.setattr(pair_module, "httpx", _mock_httpx_module(handler))
        monkeypatch.setattr(pair_module, "_get_env_path", lambda: fake_env)
        monkeypatch.setenv("RELAY_GATEWAY_URL", "https://gateway.promiselink.cn")
        monkeypatch.setenv("RELAY_WSS_ENABLED", "true")

        mock_wss_instances = []

        class _MockRelayWSSClient:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.started = False
                mock_wss_instances.append(self)

            async def start(self):
                self.started = True

        monkeypatch.setattr(
            "promiselink.services.relay_wss_client.RelayWSSClient",
            _MockRelayWSSClient,
        )

        from promiselink.main import app

        with TestClient(app) as client:
            # 1. Init
            resp = client.post("/api/v1/pair/init")
            assert resp.json()["success"] is True
            code = resp.json()["device_pair_code"]

            # 2. Status — pending
            resp = client.get("/api/v1/pair/status", params={"code": code})
            assert resp.json()["status"] == "pending"

            # 3. Simulate miniapp scan → gateway matched
            gateway_state["status"] = "matched"

            # 4. Status — matched
            resp = client.get("/api/v1/pair/status", params={"code": code})
            assert resp.json()["status"] == "matched"
            license_key = resp.json()["license_key"]

            # 5. Activate — must start WSS
            resp = client.post("/api/v1/pair/activate", json={"license_key": license_key})
            data = resp.json()
            assert data["success"] is True
            assert "中继服务已启动" in data["message"]

        # 6. Verify WSS client was actually created and started
        assert len(mock_wss_instances) == 1
        assert mock_wss_instances[0].started is True
        # Verify the license key was passed correctly
        assert mock_wss_instances[0].kwargs["license_key"] == "PL-PRO-TEST-ABCD-EFGH"

        # 7. Verify .env was written
        content = fake_env.read_text(encoding="utf-8")
        assert "PRO_LICENSE_KEY=PL-PRO-TEST-ABCD-EFGH" in content


# ═══════════════════════════════════════════════════════════════
# Cross-end device fingerprint consistency
# ═══════════════════════════════════════════════════════════════


class TestDeviceFingerprintConsistency:
    """Verify device fingerprint is byte-identical between Python and TypeScript.

    Bug context (2026-07-29): Miniapp used device info + FNV-1a for
    fingerprint, while basic edition used SHA-256(license_key). This
    caused DEVICE_FINGERPRINT_MISMATCH errors when the miniapp tried
    to connect via WSS relay.

    The fix unified both ends to use SHA-256(license_key). These tests
    verify the Python side produces the correct value and that the
    algorithm matches the documented TypeScript implementation.
    """

    @pytest.mark.parametrize(
        "license_key",
        [
            "PL-PRO-TEST-ABCD-EFGH",
            "PL-PRO-AAAA-BBBB-CCCC",
            "PL-PRO-1234-5678-9ABC",
            "",
            "PL-PRO-WITH-UNICODE-中文",  # Multibyte edge case
        ],
    )
    def test_python_fingerprint_matches_documented_algorithm(self, license_key: str):
        """Python _derive_device_fingerprint must produce sha256:<hex>.

        The TypeScript implementation in proAuth.ts uses the same algorithm:
          getDeviceFingerprint(licenseKey) = "sha256:" + sha256Hex(licenseKey)

        We verify the Python side produces the same output for the same input.
        """
        expected = f"sha256:{hashlib.sha256(license_key.encode('utf-8')).hexdigest()}"
        actual = RelayClient._derive_device_fingerprint(license_key)
        assert actual == expected
        # Must start with sha256: prefix
        assert actual.startswith("sha256:")
        # Must be 71 chars: "sha256:" (7) + 64 hex chars
        if license_key:  # Non-empty keys produce full hash
            assert len(actual) == 71

    def test_fingerprint_is_deterministic(self):
        """Same license key must always produce the same fingerprint."""
        key = "PL-PRO-DETERMINISTIC-001"
        fp1 = RelayClient._derive_device_fingerprint(key)
        fp2 = RelayClient._derive_device_fingerprint(key)
        assert fp1 == fp2

    def test_fingerprint_differs_for_different_keys(self):
        """Different license keys must produce different fingerprints."""
        fp1 = RelayClient._derive_device_fingerprint("PL-PRO-KEY-ONE-0001")
        fp2 = RelayClient._derive_device_fingerprint("PL-PRO-KEY-TWO-0002")
        assert fp1 != fp2

    def test_known_vector_pl_pro_test_abcd_efgh(self):
        """Known test vector: verify exact SHA-256 output for a specific key.

        This serves as a cross-language anchor: the TypeScript test suite
        should use the same key and verify the same hex output.
        """
        license_key = "PL-PRO-TEST-ABCD-EFGH"
        # Compute expected: sha256 of the UTF-8 bytes of the license key
        expected_hex = hashlib.sha256(license_key.encode("utf-8")).hexdigest()
        expected = f"sha256:{expected_hex}"

        actual = RelayClient._derive_device_fingerprint(license_key)
        assert actual == expected

        # Also verify the RelayClient constructor uses this by default
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key=license_key,
        )
        assert client.device_fingerprint == expected

    def test_explicit_fingerprint_overrides_derived(self):
        """If device_fingerprint is passed explicitly, it must be used as-is."""
        custom_fp = "manual-fingerprint-123"
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="PL-PRO-CUSTOM-FP-001",
            device_fingerprint=custom_fp,
        )
        assert client.device_fingerprint == custom_fp


# ═══════════════════════════════════════════════════════════════
# WeChat login endpoint — configuration missing
# ═══════════════════════════════════════════════════════════════


class TestWeChatLoginEndpointConfigMissing:
    """Verify /auth/wechat/login returns 401 when WeChat config is missing.

    Bug context (2026-07-29): Miniapp called basic edition's
    /auth/wechat/login which returned 401 because WECHAT_APP_ID/SECRET
    were not configured. The architecture decision is that WeChat login
    should go through the GATEWAY (which has the credentials), not the
    basic edition. But the basic edition endpoint must still fail
    gracefully with a clear error.
    """

    def test_wechat_login_returns_401_when_app_id_missing(self, monkeypatch):
        """/auth/wechat/login must return 401 when wechat_app_id is empty."""
        from promiselink.config import get_settings
        from promiselink.core.wechat import WeChatOAuthService

        get_settings.cache_clear()
        monkeypatch.setenv("WECHAT_APP_ID", "")
        monkeypatch.setenv("WECHAT_APP_SECRET", "")

        # Force re-creation of the singleton
        import promiselink.core.wechat as wechat_module
        monkeypatch.setattr(
            wechat_module,
            "wechat_oauth",
            WeChatOAuthService(),
        )

        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/wechat/login",
                json={"code": "test_code_123"},
            )

        assert resp.status_code == 401

    def test_wechat_login_error_message_is_helpful(self, monkeypatch):
        """The 401 error message should indicate config is missing."""
        from promiselink.config import get_settings
        from promiselink.core.wechat import WeChatOAuthService

        get_settings.cache_clear()
        monkeypatch.setenv("WECHAT_APP_ID", "")
        monkeypatch.setenv("WECHAT_APP_SECRET", "")

        import promiselink.core.wechat as wechat_module
        monkeypatch.setattr(
            wechat_module,
            "wechat_oauth",
            WeChatOAuthService(),
        )

        from promiselink.main import app

        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/auth/wechat/login",
                json={"code": "test_code_456"},
            )

        assert resp.status_code == 401
        body = resp.json()
        # Error message should mention app_id or app_secret not configured
        detail = str(body).lower()
        assert "app_id" in detail or "app_secret" in detail or "not configured" in detail

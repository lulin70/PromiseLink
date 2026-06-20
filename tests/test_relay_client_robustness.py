"""Robustness tests for relay_client.py and title_generator.py.

Covers initialization, token management, error handling, lifecycle,
singleton management, and title generation edge cases.

Focus: system robustness (Happy Path + Error Case + Boundary), not
just line coverage. Follows the Iron Rule: API signatures confirmed
from source code, not memory.
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio

from promiselink.services.relay_client import (
    RelayAuthError,
    RelayClient,
    RelayError,
    RelayUnavailableError,
    close_relay_client,
    create_relay_client_from_settings,
    get_shared_relay_client,
)
from promiselink.services.title_generator import generate_event_title

# ── Helpers ──


def _make_httpx_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
    json_side_effect: Exception | None = None,
) -> MagicMock:
    """Build a mock httpx.Response with controllable status/json/text.

    Args:
        status_code: HTTP status code.
        json_data: Dict to return from response.json().
        text: Response body text (fallback for safe_error_detail).
        json_side_effect: Exception to raise from response.json().
    """
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or ""
    if json_side_effect is not None:
        resp.json.side_effect = json_side_effect
    elif json_data is not None:
        resp.json.return_value = json_data
        if not text:
            resp.text = json.dumps(json_data)
    else:
        resp.json.side_effect = json.JSONDecodeError("", "", 0)
    return resp


def _make_mock_http_client(
    post_return=None,
    post_side_effect=None,
    get_return=None,
    get_side_effect=None,
) -> MagicMock:
    """Build a mock httpx.AsyncClient with is_closed=False.

    The is_closed=False is necessary because _get_client() checks
    self._client.is_closed and would create a new real client otherwise.
    """
    mock = MagicMock(spec=httpx.AsyncClient)
    mock.is_closed = False
    if post_side_effect is not None:
        mock.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock.post = AsyncMock(return_value=post_return)
    if get_side_effect is not None:
        mock.get = AsyncMock(side_effect=get_side_effect)
    else:
        mock.get = AsyncMock(return_value=get_return)
    return mock


def _make_token_response(access_token: str = "new-token", expires_in: int = 900) -> dict:
    """Build a UnifiedResponse token activation response (data.tokens)."""
    return {
        "data": {
            "tokens": {
                "access_token": access_token,
                "refresh_token": "refresh-token",
                "expires_in": expires_in,
            }
        }
    }


# ── Fixtures ──


@pytest.fixture
def relay_client():
    """Create a RelayClient for testing (no user_token, token needs refresh)."""
    return RelayClient(
        gateway_url="https://gateway.example.com",
        license_key="PL-PRO-TEST-XXXX-XXXX",
    )


@pytest.fixture
def relay_client_with_token():
    """Create a RelayClient with a pre-set valid token (expires in 900s)."""
    return RelayClient(
        gateway_url="https://gateway.example.com",
        license_key="PL-PRO-TEST-XXXX-XXXX",
        user_token="preset-token",
    )


@pytest_asyncio.fixture
async def reset_relay_singleton():
    """Reset the module-level shared relay client singleton.

    Creates a fresh asyncio.Lock bound to the current event loop so
    that get_shared_relay_client / close_relay_client work correctly
    across tests.
    """
    import promiselink.services.relay_client as rc_module

    rc_module._shared_client = None
    rc_module._client_lock = asyncio.Lock()
    yield
    rc_module._shared_client = None


# ── RelayClient initialization tests ──


class TestRelayClientInit:
    """Test RelayClient.__init__ — parameter handling and cleanup."""

    def test_init_normal_stores_params(self):
        """Normal initialization stores gateway_url, license_key, and defaults."""
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="PL-PRO-TEST-XXXX-XXXX",
        )
        assert client.gateway_url == "https://gateway.example.com"
        assert client.license_key == "PL-PRO-TEST-XXXX-XXXX"
        assert client.api_key == "PL-PRO-TEST-XXXX-XXXX"
        assert client.timeout == 60
        assert client.max_retries == 3

    def test_init_gateway_url_trailing_slash_stripped(self):
        """gateway_url with trailing slash is stripped via rstrip('/')."""
        client = RelayClient(
            gateway_url="https://gateway.example.com/",
            license_key="PL-PRO-TEST-XXXX-XXXX",
        )
        assert client.gateway_url == "https://gateway.example.com"

    def test_init_license_key_spaces_stripped(self):
        """license_key with surrounding spaces is stripped via .strip()."""
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="  PL-PRO-TEST-XXXX-XXXX  ",
        )
        assert client.license_key == "PL-PRO-TEST-XXXX-XXXX"

    def test_init_user_token_sets_expires_at(self):
        """user_token preset sets access_token and expires_at ~900s in future."""
        before = time.time()
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="PL-PRO-TEST-XXXX-XXXX",
            user_token="my-jwt-token",
        )
        after = time.time()
        assert client._token.access_token == "my-jwt-token"
        assert client._token.expires_at >= before + 900
        assert client._token.expires_at <= after + 900

    def test_init_device_fingerprint_auto_derived_sha256(self):
        """Omitted device_fingerprint is auto-derived in sha256:<64hex> format."""
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="PL-PRO-TEST-XXXX-XXXX",
        )
        fp = client.device_fingerprint
        assert fp.startswith("sha256:")
        hex_part = fp[7:]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_init_device_fingerprint_custom_used_as_is(self):
        """Custom device_fingerprint is used as-is (no derivation)."""
        client = RelayClient(
            gateway_url="https://gateway.example.com",
            license_key="PL-PRO-TEST-XXXX-XXXX",
            device_fingerprint="custom-fp-123",
        )
        assert client.device_fingerprint == "custom-fp-123"


# ── _derive_device_fingerprint tests ──


class TestDeriveDeviceFingerprint:
    """Test RelayClient._derive_device_fingerprint — deterministic sha256."""

    def test_derive_fingerprint_format_sha256_hex(self):
        """Fingerprint format is 'sha256:' + exactly 64 lowercase hex chars."""
        fp = RelayClient._derive_device_fingerprint("PL-PRO-TEST-XXXX-XXXX")
        assert fp.startswith("sha256:")
        hex_part = fp[7:]
        assert len(hex_part) == 64
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_derive_fingerprint_same_key_same_result(self):
        """Same license_key produces the same fingerprint (deterministic)."""
        fp1 = RelayClient._derive_device_fingerprint("PL-PRO-TEST-XXXX-XXXX")
        fp2 = RelayClient._derive_device_fingerprint("PL-PRO-TEST-XXXX-XXXX")
        assert fp1 == fp2

    def test_derive_fingerprint_different_key_different_result(self):
        """Different license_keys produce different fingerprints."""
        fp1 = RelayClient._derive_device_fingerprint("PL-PRO-TEST-XXXX-XXXX")
        fp2 = RelayClient._derive_device_fingerprint("PL-PRO-TEST-YYYY-YYYY")
        assert fp1 != fp2


# ── _auth_headers tests ──


class TestAuthHeaders:
    """Test RelayClient._auth_headers — Authorization header construction."""

    def test_auth_headers_with_token_returns_bearer(self, relay_client_with_token):
        """Returns {'Authorization': 'Bearer {token}'} when token is set."""
        headers = relay_client_with_token._auth_headers()
        assert headers == {"Authorization": "Bearer preset-token"}

    def test_auth_headers_empty_token_returns_bearer_empty(self, relay_client):
        """Returns {'Authorization': 'Bearer '} when token is empty string."""
        headers = relay_client._auth_headers()
        assert headers == {"Authorization": "Bearer "}


# ── refresh_token robustness tests ──


class TestRefreshToken:
    """Test RelayClient.refresh_token — error handling, caching, concurrency."""

    async def test_refresh_token_network_error_raises_unavailable(self, relay_client):
        """httpx.HTTPError → RelayUnavailableError (gateway unreachable)."""
        mock_client = _make_mock_http_client(
            post_side_effect=httpx.HTTPError("connection refused")
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayUnavailableError) as exc_info:
            await relay_client.refresh_token()
        assert "Cannot reach gateway" in exc_info.value.message

    async def test_refresh_token_401_raises_auth_error(self, relay_client):
        """HTTP 401 → RelayAuthError (license rejected)."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                401, json_data={"detail": "Invalid license"}, text="Unauthorized"
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayAuthError) as exc_info:
            await relay_client.refresh_token()
        assert exc_info.value.details["status_code"] == 401

    async def test_refresh_token_403_raises_auth_error(self, relay_client):
        """HTTP 403 → RelayAuthError (forbidden)."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                403, json_data={"detail": "Forbidden"}, text="Forbidden"
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayAuthError):
            await relay_client.refresh_token()

    async def test_refresh_token_500_raises_relay_error(self, relay_client):
        """HTTP 500 → RelayError with code RELAY_LICENSE_ERROR."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                500, json_data={"detail": "Internal error"}, text="Internal Server Error"
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayError) as exc_info:
            await relay_client.refresh_token()
        assert exc_info.value.code == "RELAY_LICENSE_ERROR"

    async def test_refresh_token_json_parse_error_raises_relay_error(self, relay_client):
        """JSON parse failure → RelayError with code RELAY_PARSE_ERROR."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                200, json_side_effect=json.JSONDecodeError("", "", 0), text="not json"
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayError) as exc_info:
            await relay_client.refresh_token()
        assert exc_info.value.code == "RELAY_PARSE_ERROR"

    async def test_refresh_token_missing_token_data_raises_relay_error(self, relay_client):
        """Response missing all token fields → RelayError (code=RELAY_PARSE_ERROR)."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                200, json_data={"status": "ok", "message": "no tokens here"}
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(RelayError) as exc_info:
            await relay_client.refresh_token()
        assert exc_info.value.code == "RELAY_PARSE_ERROR"

    async def test_refresh_token_success_returns_and_caches_token(self, relay_client):
        """Normal refresh → returns access_token and updates _token state."""
        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(
                200, json_data=_make_token_response("fresh-jwt", expires_in=900)
            )
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        result = await relay_client.refresh_token()
        assert result == "fresh-jwt"
        assert relay_client._token.access_token == "fresh-jwt"
        assert relay_client._token.refresh_token == "refresh-token"
        assert relay_client._token.expires_at > time.time()

    async def test_refresh_token_concurrent_single_http_request(self, relay_client):
        """Concurrent refresh_token calls → only one HTTP request (lock mechanism)."""
        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # Ensure both coroutines are waiting
            return _make_httpx_response(
                200, json_data=_make_token_response("concurrent-token")
            )

        mock_client = _make_mock_http_client(post_side_effect=mock_post)
        relay_client._get_client = AsyncMock(return_value=mock_client)

        results = await asyncio.gather(
            relay_client.refresh_token(),
            relay_client.refresh_token(),
        )

        assert call_count == 1
        assert results[0] == "concurrent-token"
        assert results[1] == "concurrent-token"

    async def test_refresh_token_not_expired_returns_cached(self, relay_client_with_token):
        """Token not expired → returns cached token without HTTP request."""
        relay_client_with_token._get_client = AsyncMock()

        result = await relay_client_with_token.refresh_token()
        assert result == "preset-token"
        relay_client_with_token._get_client.assert_not_called()


# ── _extract_token_data tests ──


class TestExtractTokenData:
    """Test RelayClient._extract_token_data — multi-format response parsing."""

    def test_extract_unified_response_data_tokens(self):
        """UnifiedResponse format: data.tokens is extracted."""
        data = {"data": {"tokens": {"access_token": "t1", "expires_in": 900}}}
        result = RelayClient._extract_token_data(data)
        assert result == {"access_token": "t1", "expires_in": 900}

    def test_extract_flat_dict_access_token_top_level(self):
        """Flat dict format: access_token at top level."""
        data = {"access_token": "t2", "refresh_token": "r2", "expires_in": 600}
        result = RelayClient._extract_token_data(data)
        assert result == data

    def test_extract_data_access_token_inner(self):
        """data.access_token format: access_token inside data dict (no tokens key)."""
        data = {"data": {"access_token": "t3", "expires_in": 300}}
        result = RelayClient._extract_token_data(data)
        assert result == {"access_token": "t3", "expires_in": 300}

    def test_extract_tokens_top_level(self):
        """tokens at top level (no data envelope)."""
        data = {"tokens": {"access_token": "t4", "expires_in": 120}}
        result = RelayClient._extract_token_data(data)
        assert result == {"access_token": "t4", "expires_in": 120}

    def test_extract_missing_all_token_fields_raises(self):
        """No token fields anywhere → RelayError (code=RELAY_PARSE_ERROR)."""
        with pytest.raises(RelayError) as exc_info:
            RelayClient._extract_token_data({"status": "ok"})
        assert exc_info.value.code == "RELAY_PARSE_ERROR"


# ── _ensure_token tests ──


class TestEnsureToken:
    """Test RelayClient._ensure_token — auto-refresh logic."""

    async def test_ensure_token_valid_no_refresh(self, relay_client_with_token):
        """Token valid → _ensure_token does not call refresh_token."""
        relay_client_with_token.refresh_token = AsyncMock()

        result = await relay_client_with_token._ensure_token()
        assert result == "preset-token"
        relay_client_with_token.refresh_token.assert_not_called()

    async def test_ensure_token_expired_triggers_refresh(self, relay_client):
        """Token expired → _ensure_token calls refresh_token and returns new token."""

        async def mock_refresh():
            relay_client._token.access_token = "refreshed-token"
            relay_client._token.expires_at = time.time() + 900
            return "refreshed-token"

        relay_client.refresh_token = AsyncMock(side_effect=mock_refresh)

        result = await relay_client._ensure_token()
        assert result == "refreshed-token"
        relay_client.refresh_token.assert_called_once()


# ── health_check robustness tests ──


class TestHealthCheck:
    """Test RelayClient.health_check — graceful degradation."""

    async def test_health_check_200_returns_true(self, relay_client):
        """HTTP 200 → True."""
        mock_client = _make_mock_http_client(get_return=_make_httpx_response(200))
        relay_client._get_client = AsyncMock(return_value=mock_client)

        result = await relay_client.health_check()
        assert result is True

    async def test_health_check_500_returns_false(self, relay_client):
        """HTTP 500 → False (no exception)."""
        mock_client = _make_mock_http_client(get_return=_make_httpx_response(500))
        relay_client._get_client = AsyncMock(return_value=mock_client)

        result = await relay_client.health_check()
        assert result is False

    async def test_health_check_network_error_returns_false(self, relay_client):
        """Network error → False (no exception raised)."""
        mock_client = _make_mock_http_client(
            get_side_effect=httpx.HTTPError("network unreachable")
        )
        relay_client._get_client = AsyncMock(return_value=mock_client)

        result = await relay_client.health_check()
        assert result is False


# ── close robustness tests ──


class TestClose:
    """Test RelayClient.close — lifecycle and idempotency."""

    async def test_close_normal_closes_and_clears(self, relay_client):
        """Normal close: calls aclose and sets _client to None."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        relay_client._client = mock_client

        await relay_client.close()

        mock_client.aclose.assert_awaited_once()
        assert relay_client._client is None

    async def test_close_idempotent_no_error_on_repeat(self, relay_client):
        """Repeat close: second call does not raise (client already None)."""
        mock_client = MagicMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()
        relay_client._client = mock_client

        await relay_client.close()
        assert relay_client._client is None

        await relay_client.close()  # Should not raise
        assert relay_client._client is None

    async def test_close_no_client_created_no_error(self, relay_client):
        """Close when no client was ever created: does not raise."""
        relay_client._client = None

        await relay_client.close()  # Should not raise
        assert relay_client._client is None


# ── create_relay_client_from_settings tests ──


class TestCreateRelayClientFromSettings:
    """Test create_relay_client_from_settings — factory validation."""

    def test_create_normal_with_all_fields(self):
        """Normal settings → creates RelayClient with correct values."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="my-token",
            llm_timeout=30,
            llm_max_retries=2,
        )
        client = create_relay_client_from_settings(settings)
        assert client.gateway_url == "https://gateway.example.com"
        assert client.license_key == "PL-PRO-TEST-XXXX-XXXX"
        assert client._token.access_token == "my-token"
        assert client.timeout == 30
        assert client.max_retries == 2

    def test_create_missing_gateway_url_raises_value_error(self):
        """Missing relay_gateway_url → ValueError."""
        settings = SimpleNamespace(
            relay_gateway_url="",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="",
        )
        with pytest.raises(ValueError, match="relay_gateway_url"):
            create_relay_client_from_settings(settings)

    def test_create_missing_license_key_raises_value_error(self):
        """Missing pro_license_key → ValueError."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="",
            relay_user_token="",
        )
        with pytest.raises(ValueError, match="pro_license_key"):
            create_relay_client_from_settings(settings)

    def test_create_uses_default_timeout_and_retries(self):
        """Settings without llm_timeout/llm_max_retries → uses defaults (60, 3)."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="",
        )
        client = create_relay_client_from_settings(settings)
        assert client.timeout == 60
        assert client.max_retries == 3


# ── Singleton management tests ──


class TestSingletonManagement:
    """Test get_shared_relay_client / close_relay_client — singleton lifecycle."""

    async def test_get_shared_creates_instance_on_first_call(self, reset_relay_singleton):
        """First call to get_shared_relay_client creates a new instance."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="",
            llm_timeout=30,
            llm_max_retries=2,
        )
        client = await get_shared_relay_client(settings)
        assert client is not None
        assert client.gateway_url == "https://gateway.example.com"

    async def test_get_shared_returns_same_instance_on_second_call(
        self, reset_relay_singleton
    ):
        """Second call returns the same instance (singleton reuse)."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="",
        )
        client1 = await get_shared_relay_client(settings)
        client2 = await get_shared_relay_client(settings)
        assert client1 is client2

    async def test_close_relay_client_resets_singleton(self, reset_relay_singleton):
        """close_relay_client resets the singleton; next get creates new instance."""
        settings = SimpleNamespace(
            relay_gateway_url="https://gateway.example.com",
            pro_license_key="PL-PRO-TEST-XXXX-XXXX",
            relay_user_token="",
        )
        client1 = await get_shared_relay_client(settings)
        assert client1 is not None

        await close_relay_client()

        import promiselink.services.relay_client as rc_module

        assert rc_module._shared_client is None

        client2 = await get_shared_relay_client(settings)
        assert client2 is not client1

    async def test_close_relay_client_exception_still_resets_singleton(
        self, reset_relay_singleton
    ):
        """close_relay_client resets singleton even if close() raises."""
        import promiselink.services.relay_client as rc_module

        mock_client = MagicMock(spec=RelayClient)
        mock_client.close = AsyncMock(side_effect=Exception("close failed"))
        rc_module._shared_client = mock_client

        await close_relay_client()  # Should not raise

        assert rc_module._shared_client is None


# ── generate_event_title robustness tests ──


class TestGenerateEventTitle:
    """Test generate_event_title — edge cases and graceful degradation."""

    async def test_generate_title_empty_text_returns_none(self):
        """Empty text → returns None without calling LLM."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock()

        result = await generate_event_title(llm_client, "")
        assert result is None
        llm_client.generate.assert_not_called()

    async def test_generate_title_short_text_returns_none(self):
        """Short text (<10 chars after strip) → returns None without calling LLM."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock()

        result = await generate_event_title(llm_client, "short")
        assert result is None
        llm_client.generate.assert_not_called()

    async def test_generate_title_normal_response_returns_title(self):
        """LLM normal response → returns the title string."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="投资对接会 - 盛恒资本李总")

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert result == "投资对接会 - 盛恒资本李总"

    async def test_generate_title_llm_exception_returns_none(self):
        """LLM exception → returns None (no raise, graceful degradation)."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(side_effect=Exception("LLM unavailable"))

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert result is None

    async def test_generate_title_long_title_truncated_to_50(self):
        """Title >50 chars → truncated to 47 chars + '...' (total 50)."""
        long_title = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的标题超过五十个字符的测试用例"
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value=long_title)

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert len(result) == 50
        assert result.endswith("...")
        assert result[:47] == long_title[:47]

    async def test_generate_title_empty_response_returns_none(self):
        """Empty LLM response (empty string) → returns None."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="")

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert result is None

    async def test_generate_title_strips_double_quotes(self):
        """Response wrapped in double quotes → quotes stripped."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value='"投资对接会 - 盛恒资本"')

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert result == "投资对接会 - 盛恒资本"

    async def test_generate_title_strips_single_quotes(self):
        """Response wrapped in single quotes → quotes stripped."""
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="'下午茶交流 - 智谱AI张总'")

        result = await generate_event_title(
            llm_client, "这是一段足够长的交流记录内容用于测试标题生成"
        )
        assert result == "下午茶交流 - 智谱AI张总"

    async def test_generate_title_long_raw_text_truncated_in_prompt(self):
        """raw_text >500 chars → processed normally (truncated to 500 in prompt)."""
        long_text = "x" * 600
        llm_client = MagicMock()
        llm_client.generate = AsyncMock(return_value="标题")

        result = await generate_event_title(llm_client, long_text)
        assert result == "标题"

        # Verify the prompt was truncated to 500 chars of raw_text
        call_args = llm_client.generate.call_args
        prompt = call_args.kwargs.get("prompt", "")
        assert "x" * 500 in prompt
        assert "x" * 501 not in prompt

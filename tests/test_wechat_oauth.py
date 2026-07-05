"""Tests for promiselink.core.wechat.

Tests WeChatOAuthService.code_to_session and decrypt_user_info with
mocked httpx.AsyncClient (no real WeChat API calls).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from promiselink.core.wechat import WeChatOAuthError, WeChatOAuthService

# ── Helpers ──


def _make_service(*, configured: bool = False) -> WeChatOAuthService:
    """Create WeChatOAuthService bypassing __init__ to avoid env coupling."""
    svc = WeChatOAuthService.__new__(WeChatOAuthService)
    svc.app_id = "test_app_id" if configured else None
    svc.app_secret = "test_app_secret" if configured else None
    return svc


def _mock_httpx_response(json_data: dict) -> MagicMock:
    """Create a mock httpx.Response that returns the given dict from .json()."""
    resp = MagicMock()
    resp.json.return_value = json_data
    return resp


def _patch_async_client(resp: MagicMock):
    """Patch httpx.AsyncClient to return a mock that yields resp."""
    mock_instance = AsyncMock()
    mock_instance.get = AsyncMock(return_value=resp)
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    return patch("promiselink.core.wechat.httpx.AsyncClient", return_value=mock_instance)


# ═══════════════════════════════════════════════════════════════
# code_to_session — 配置检查
# ═══════════════════════════════════════════════════════════════


class TestCodeToSessionConfig:
    """code_to_session 配置检查."""

    @pytest.mark.asyncio
    async def test_boundary_no_app_id_raises_error(self):
        """未配置 app_id 时应抛 WeChatOAuthError."""
        svc = _make_service(configured=False)
        with pytest.raises(WeChatOAuthError, match="app_id or app_secret not configured"):
            await svc.code_to_session("test_code")

    @pytest.mark.asyncio
    async def test_boundary_no_app_secret_raises_error(self):
        """只配置 app_id 而无 app_secret 时应抛 WeChatOAuthError."""
        svc = _make_service(configured=False)
        svc.app_id = "test_app_id"
        svc.app_secret = None
        with pytest.raises(WeChatOAuthError, match="app_id or app_secret not configured"):
            await svc.code_to_session("test_code")


# ═══════════════════════════════════════════════════════════════
# code_to_session — 成功路径
# ═══════════════════════════════════════════════════════════════


class TestCodeToSessionSuccess:
    """code_to_session 成功路径."""

    @pytest.mark.asyncio
    async def test_happy_returns_openid_and_session_key(self):
        """成功响应应返回包含 openid 和 session_key 的 dict."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "openid": "test_openid_123",
            "session_key": "test_session_key_456",
        })
        with _patch_async_client(mock_resp):
            result = await svc.code_to_session("valid_code")

        assert result["openid"] == "test_openid_123"
        assert result["session_key"] == "test_session_key_456"

    @pytest.mark.asyncio
    async def test_happy_includes_unionid_when_present(self):
        """响应包含 unionid 时应在结果中包含."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "openid": "openid_x",
            "session_key": "sk_y",
            "unionid": "unionid_z",
        })
        with _patch_async_client(mock_resp):
            result = await svc.code_to_session("code")

        assert result["unionid"] == "unionid_z"

    @pytest.mark.asyncio
    async def test_happy_unionid_none_when_absent(self):
        """响应不含 unionid 时应为 None."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "openid": "openid_x",
            "session_key": "sk_y",
        })
        with _patch_async_client(mock_resp):
            result = await svc.code_to_session("code")

        assert result["unionid"] is None

    @pytest.mark.asyncio
    async def test_happy_passes_correct_params_to_httpx(self):
        """应将 appid/secret/js_code/grant_type 传给 WeChat API."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "openid": "x", "session_key": "y",
        })
        with _patch_async_client(mock_resp) as mock_client_cls:
            await svc.code_to_session("my_test_code")

        mock_instance = mock_client_cls.return_value
        mock_instance.get.assert_awaited_once()
        # Check params passed
        call_args = mock_instance.get.await_args
        params = call_args.kwargs.get("params") or call_args.args[1]
        assert params["appid"] == "test_app_id"
        assert params["secret"] == "test_app_secret"
        assert params["js_code"] == "my_test_code"
        assert params["grant_type"] == "authorization_code"


# ═══════════════════════════════════════════════════════════════
# code_to_session — 错误路径
# ═══════════════════════════════════════════════════════════════


class TestCodeToSessionErrors:
    """code_to_session 错误路径."""

    @pytest.mark.asyncio
    async def test_boundary_errcode_non_zero_raises_error(self):
        """响应包含非零 errcode 时应抛 WeChatOAuthError."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "errcode": 40029,
            "errmsg": "invalid code",
        })
        with _patch_async_client(mock_resp):
            with pytest.raises(WeChatOAuthError, match="invalid code"):
                await svc.code_to_session("bad_code")

    @pytest.mark.asyncio
    async def test_boundary_errcode_zero_does_not_raise(self):
        """errcode=0 视为成功 (不抛异常)."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "errcode": 0,
            "openid": "openid_ok",
            "session_key": "sk_ok",
        })
        with _patch_async_client(mock_resp):
            result = await svc.code_to_session("code")

        assert result["openid"] == "openid_ok"

    @pytest.mark.asyncio
    async def test_boundary_unknown_errmsg_uses_default_message(self):
        """errcode 非 0 但无 errmsg 时应使用默认错误消息."""
        svc = _make_service(configured=True)
        mock_resp = _mock_httpx_response({
            "errcode": -1,
        })
        with _patch_async_client(mock_resp):
            with pytest.raises(WeChatOAuthError, match="Unknown error"):
                await svc.code_to_session("code")


# ═══════════════════════════════════════════════════════════════
# decrypt_user_info — 未实现
# ═══════════════════════════════════════════════════════════════


class TestDecryptUserInfo:
    """decrypt_user_info 未实现."""

    def test_raises_not_implemented(self):
        """decrypt_user_info 应抛 NotImplementedError (Phase 1 待实现)."""
        svc = _make_service(configured=True)
        with pytest.raises(NotImplementedError, match="Phase 1"):
            svc.decrypt_user_info("encrypted_data", "session_key", "iv")


# ═══════════════════════════════════════════════════════════════
# WeChatOAuthService — 类属性
# ═══════════════════════════════════════════════════════════════


class TestWeChatOAuthServiceClassAttrs:
    """WeChatOAuthService 类属性."""

    def test_code2session_url_is_correct(self):
        """CODE2SESSION_URL 应指向微信官方接口."""
        assert WeChatOAuthService.CODE2SESSION_URL == (
            "https://api.weixin.qq.com/sns/jscode2session"
        )


# ═══════════════════════════════════════════════════════════════
# WeChatOAuthError — 异常类
# ═══════════════════════════════════════════════════════════════


class TestWeChatOAuthError:
    """WeChatOAuthError 异常类."""

    def test_is_exception_subclass(self):
        assert issubclass(WeChatOAuthError, Exception)

    def test_can_be_raised_with_message(self):
        with pytest.raises(WeChatOAuthError, match="test error"):
            raise WeChatOAuthError("test error")

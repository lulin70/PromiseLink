"""WeChat Mini Program OAuth integration for PromiseLink.

Implements the WeChat Mini Program login flow:
1. Frontend calls wx.login() → gets code
2. Backend exchanges code for session_key + openid
3. Backend creates/finds user → generates JWT

Reference: https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/login.html
"""

from typing import Any

import httpx

from promiselink.config import get_settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.wechat")


class WeChatOAuthService:
    """WeChat Mini Program OAuth service."""

    CODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"

    def __init__(self):
        settings = get_settings()
        self.app_id = settings.wechat_app_id
        self.app_secret = settings.wechat_app_secret

    async def code_to_session(self, code: str) -> dict[str, Any]:
        """Exchange wx.login code for session_key + openid.

        Args:
            code: The code from wx.login()

        Returns:
            Dict with openid, session_key, unionid (optional)

        Raises:
            WeChatOAuthError: If the exchange fails
        """
        if not self.app_id or not self.app_secret:
            raise WeChatOAuthError("WeChat app_id or app_secret not configured")

        params = {
            "appid": self.app_id,
            "secret": self.app_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(self.CODE2SESSION_URL, params=params)
            data = resp.json()

        if "errcode" in data and data["errcode"] != 0:
            logger.error("wechat_code2session_failed", errcode=data.get("errcode"), errmsg=data.get("errmsg"))
            raise WeChatOAuthError(f"WeChat OAuth failed: {data.get('errmsg', 'Unknown error')}")

        return {
            "openid": data["openid"],
            "session_key": data["session_key"],
            "unionid": data.get("unionid"),
        }

    def decrypt_user_info(self, encrypted_data: str, session_key: str, iv: str) -> dict:
        """Decrypt encrypted user info from WeChat.

        Note: This requires the WXBizDataCrypt algorithm.
        For PoC, we skip this and only use openid for identification.
        """
        # Phase 1: Implement full decryption
        # Phase 2: Add phone number decryption
        raise NotImplementedError("User info decryption deferred to Phase 1")


class WeChatOAuthError(Exception):
    """WeChat OAuth error."""
    pass


# Singleton
wechat_oauth = WeChatOAuthService()

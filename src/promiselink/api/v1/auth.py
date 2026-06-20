"""Authentication endpoints."""

import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import create_access_token
from promiselink.core.exceptions import ForbiddenError, UnauthorizedError
from promiselink.database import get_async_session

router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


class LoginRequest(BaseModel):
    user_id: str  # PoC阶段：直接用user_id登录，Phase 1改为微信登录
    poc_secret: str = Field(default="", description="PoC环境专用密钥，生产环境禁用此端点")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> Any:
    """PoC login: 需要poc_secret验证。生产环境应禁用此端点，使用微信OAuth。"""
    from promiselink.config import get_settings
    settings = get_settings()
    poc_secret = settings.poc_secret
    if not poc_secret:
        raise ForbiddenError("PoC login is disabled. Use /auth/wechat/login.")
    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(request.poc_secret, poc_secret):
        raise UnauthorizedError("Invalid PoC secret")
    token = create_access_token(request.user_id)
    return LoginResponse(access_token=token, user_id=request.user_id)


class WeChatLoginRequest(BaseModel):
    code: str = Field(..., description="wx.login() 返回的 code")


class WeChatLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    is_new_user: bool = False


@router.post("/auth/wechat/login", response_model=WeChatLoginResponse)
async def wechat_login(request: WeChatLoginRequest, session: AsyncSession = Depends(get_async_session)) -> Any:
    """微信小程序登录：用code换取openid，创建/查找用户，返回JWT。"""
    from promiselink.core.wechat import WeChatOAuthError, wechat_oauth

    try:
        wx_data = await wechat_oauth.code_to_session(request.code)
    except WeChatOAuthError as e:
        raise UnauthorizedError(str(e))

    openid = wx_data["openid"]

    # Find or create user by openid
    # For PoC: use openid hash as user_id
    user_id = hashlib.sha256(openid.encode()).hexdigest()[:36]
    # Pad to UUID format if needed
    if len(user_id) < 36:
        user_id = user_id + "0" * (36 - len(user_id))

    # Phase 1: Look up user in database by openid
    # For now, just generate token
    token = create_access_token(user_id)

    return WeChatLoginResponse(
        access_token=token,
        user_id=user_id,
        is_new_user=False,  # Phase 1: check from DB
    )

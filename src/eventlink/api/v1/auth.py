"""Authentication endpoints."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.auth import create_access_token
from eventlink.database import get_async_session

router = APIRouter()


class LoginRequest(BaseModel):
    user_id: str  # PoC阶段：直接用user_id登录，Phase 1改为微信登录


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """PoC login: 直接用user_id获取token。Phase 1改为微信OAuth。"""
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
async def wechat_login(request: WeChatLoginRequest, session: AsyncSession = Depends(get_async_session)):
    """微信小程序登录：用code换取openid，创建/查找用户，返回JWT。"""
    from eventlink.core.wechat import wechat_oauth, WeChatOAuthError

    try:
        wx_data = await wechat_oauth.code_to_session(request.code)
    except WeChatOAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

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

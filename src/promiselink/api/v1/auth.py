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
    user_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="PoC阶段：直接用user_id登录，Phase 1改为微信登录",
    )
    poc_secret: str = Field(default="", description="PoC环境专用密钥，生产环境禁用此端点")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str


DEFAULT_POC_SECRET = "promiselink2026"


def _validate_user_id(user_id: str) -> str:
    """对 PoC 登录的 user_id 做最小输入校验（P1-7 修复）。

    PoC 阶段无独立 User 表，"注册"语义为首次以新 user_id 登录（见
    test_new_user_registration_and_login）。因此这里只做输入卫生校验，
    不校验用户是否已存在于数据库——这是 Phase 1（微信登录 + User 表）的工作。

    校验规则：
    - 去除首尾空白后必须非空
    - 拒绝控制字符 / NUL 字节（防注入与日志投毒）
    - 长度由 Pydantic Field 约束在 [1, 128]
    """
    cleaned = (user_id or "").strip()
    if not cleaned:
        raise UnauthorizedError("Invalid user_id: must not be empty")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in cleaned):
        raise UnauthorizedError("Invalid user_id: control characters not allowed")
    return cleaned


@router.post("/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest) -> Any:
    """PoC login: 需要poc_secret验证。生产环境必须修改默认密码。

    Security constraints:
    - Production environment rejects the default poc_secret (must be changed).
    - Uses constant-time comparison to prevent timing attacks.
    - user_id 做输入卫生校验（非空/无控制字符/长度限制）。

    PoC 设计说明（P1-7）：本端点校验共享密钥 poc_secret（即"密码匹配"），
    但**不校验 user_id 是否对应数据库中的已存在用户**——PoC 阶段无 User 表，
    任意新 user_id 配合正确密钥即可首次"注册"登录。用户存在性校验留待
    Phase 1（/auth/wechat/login + User 模型）实现。生产环境应禁用本端点。
    """
    from promiselink.config import get_settings
    settings = get_settings()
    poc_secret = settings.poc_secret
    if not poc_secret:
        raise ForbiddenError("PoC login is disabled. Use /auth/wechat/login.")
    # Block default secret in non-dev/test environments to prevent credential-guessing attacks
    if settings.app_env not in ("development", "test") and poc_secret == DEFAULT_POC_SECRET:
        raise ForbiddenError(
            f"Default PoC secret not allowed in {settings.app_env} environment. Set POC_SECRET env var."
        )
    # Use constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(request.poc_secret, poc_secret):
        raise UnauthorizedError("Invalid PoC secret")
    # Minimal input sanity check on user_id (P1-7): do not verify DB existence by design.
    user_id = _validate_user_id(request.user_id)
    token = create_access_token(user_id)
    return LoginResponse(access_token=token, user_id=user_id)


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

"""Pydantic schemas for license endpoints.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.1-§4.3.2
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LicenseActivateRequest(BaseModel):
    """Request body for POST /api/v1/pro/license/activate."""

    license_key: str = Field(
        ...,
        pattern=r"^PL-PRO-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$",
        description="License key in PL-PRO-xxxx-xxxx-xxxx format",
    )
    wechat_openid: str | None = Field(default=None, description="WeChat OpenID (optional)")
    device_fingerprint: str = Field(
        ...,
        pattern=r"^sha256:[a-f0-9]{64}$",
        description="Device fingerprint (sha256:hex64)",
    )


class LicenseVerifyRequest(BaseModel):
    """Request body for POST /api/v1/pro/license/verify."""

    device_fingerprint: str = Field(
        ...,
        pattern=r"^sha256:[a-f0-9]{64}$",
        description="Device fingerprint to verify",
    )


class LicenseRefreshRequest(BaseModel):
    """Request body for POST /api/v1/pro/license/refresh."""

    refresh_token: str = Field(..., description="Refresh token")


class LicenseInfo(BaseModel):
    """License information in responses."""

    license_key: str
    plan_type: str = "pro"
    status: str = "active"
    expires_at: str
    quota_limit_tokens: int = 500000
    quota_limit_asr: int = 200
    quota_limit_tts: int = 200
    quota_limit_ocr: int = 100


class TokenPair(BaseModel):
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int = 900


class RelayConfig(BaseModel):
    """Relay client configuration."""

    relay_gateway_url: str = "wss://gw.promiselink.ai/relay"
    heartbeat_interval: int = 30
    reconnect_interval: int = 1
    reconnect_max: int = 30


class LicenseActivateResponse(BaseModel):
    """Response for license activation."""

    license: LicenseInfo
    tokens: TokenPair
    relay_config: RelayConfig = RelayConfig()


class QuotaInfo(BaseModel):
    """Quota usage for a single resource type."""

    limit: int
    used: int
    remaining: int
    percentage: float


class LicenseVerifyResponse(BaseModel):
    """Response for license verification."""

    valid: bool = True
    license: LicenseInfo
    quota: dict[str, QuotaInfo] = Field(default_factory=dict)
    traffic_light: str = "green"
    tokens: TokenPair | None = None

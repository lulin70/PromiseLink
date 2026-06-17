"""Pydantic schemas for relay endpoints.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.4-§4.3.7, §8.2
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class LLMMessage(BaseModel):
    """A single chat message."""

    role: str = Field(..., description="system/user/assistant")
    content: str


class LLMRelayRequest(BaseModel):
    """Request body for POST /api/v1/pro/relay/llm."""

    provider: str = Field(default="moka_ai", description="LLM provider")
    model: str = Field(..., max_length=64, description="Model name")
    messages: list[LLMMessage] = Field(..., min_length=1, max_length=50)
    max_tokens: int = Field(default=2000, ge=1, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    stream: bool = Field(default=False)


class LLMUsage(BaseModel):
    """Token usage from LLM response."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class LLMBilling(BaseModel):
    """Billing info attached to LLM response."""

    cost_cny: float = 0.0
    monthly_status: str = "green"
    remaining_tokens: int = 0


class LLMRelayResponse(BaseModel):
    """Non-streaming LLM relay response."""

    content: str
    model: str
    usage: LLMUsage
    billing: LLMBilling


class ASRRelayResponse(BaseModel):
    """Response for POST /api/v1/pro/relay/asr."""

    text: str
    language: str = "zh"
    duration_seconds: float = 0.0
    billing: dict = Field(default_factory=dict)


class TTSRelayRequest(BaseModel):
    """Request body for POST /api/v1/pro/relay/tts."""

    text: str = Field(..., max_length=500)
    model: str = Field(default="moka-tts")
    voice: str = Field(default="zh-female-1")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    response_format: str = Field(default="mp3")


class OCRRelayResponse(BaseModel):
    """Response for POST /api/v1/pro/relay/ocr."""

    task: str = "general"
    structured: dict | None = None
    raw_text: str = ""
    billing: dict = Field(default_factory=dict)


class HealthResponse(BaseModel):
    """Response for GET /api/v1/pro/health."""

    status: str = "healthy"
    version: str = "1.0.0"
    timestamp: str
    components: dict = Field(default_factory=dict)
    metrics: dict = Field(default_factory=dict)

"""Pydantic schemas for usage endpoint.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.3
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UsageQuota(BaseModel):
    """Quota for a single resource type."""

    limit: int
    used: int
    remaining: int
    percentage: float


class UsageHistoryItem(BaseModel):
    """Historical usage for a past month."""

    month: str
    tokens_used: int
    traffic_light: str = "green"


class UsageResponse(BaseModel):
    """Response for GET /api/v1/pro/usage."""

    month: str
    traffic_light: str = "green"
    quota: dict[str, UsageQuota] = Field(default_factory=dict)
    cost_cny: float = 0.0
    request_count: int = 0
    reset_at: str
    history: list[UsageHistoryItem] = Field(default_factory=list)

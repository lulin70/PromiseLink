"""Unified API response schemas.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.1.3
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Error detail in unified response."""

    code: str
    message: str
    details: dict[str, Any] | None = None


class UnifiedResponse(BaseModel, Generic[T]):
    """Unified API response wrapper."""

    request_id: str
    success: bool = True
    data: T | None = None
    error: ErrorDetail | None = None

"""Shared API schemas."""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response with total count."""

    items: list[T]
    total: int
    limit: int
    offset: int

    class Config:
        from_attributes = True

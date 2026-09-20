"""Shared API schemas."""
import uuid
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict

T = TypeVar("T")

# Coerce uuid.UUID to str for Pydantic response models: UUID columns are
# String(36) so stored values are already str, but construction sites may still
# pass uuid.UUID objects. The union base type lets mypy accept both.
UUIDStr = Annotated[str | uuid.UUID, BeforeValidator(lambda v: str(v) if isinstance(v, uuid.UUID) else v)]


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response with total count."""

    items: list[T]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(from_attributes=True)

"""Shared API schemas."""
import uuid
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict

T = TypeVar("T")

# Coerce uuid.UUID (returned by PostgreSQL UUID columns) to str for
# Pydantic response models. SQLite returns str already; the BeforeValidator
# is a no-op in that case. The union base type lets mypy accept both
# str (SQLite) and uuid.UUID (PostgreSQL) inputs at construction sites.
UUIDStr = Annotated[str | uuid.UUID, BeforeValidator(lambda v: str(v) if isinstance(v, uuid.UUID) else v)]


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated list response with total count."""

    items: list[T]
    total: int
    limit: int
    offset: int

    model_config = ConfigDict(from_attributes=True)

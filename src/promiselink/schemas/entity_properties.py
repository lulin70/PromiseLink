"""Pydantic schema validation for Entity.properties JSONB field.

Validates the structure of the properties dict before writing to database.
Provides graceful degradation: if validation fails, logs a warning and
stores the raw dict as-is.
"""

from pydantic import BaseModel


class BasicInfo(BaseModel):
    company: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    wechat: str | None = None
    city: str | None = None


class ConcernItem(BaseModel):
    category: str
    detail: str | None = None


class CapabilityItem(BaseModel):
    category: str
    detail: str | None = None


class EntityProperties(BaseModel):
    basic: BasicInfo | None = None
    concern: list[ConcernItem] | None = None
    capability: list[CapabilityItem] | None = None
    promise: list[str] | None = None
    contribution: list[str] | None = None

"""Pydantic response models for API endpoints that previously returned bare dicts."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class TodoConfirmResponse(BaseModel):
    todo_id: UUID
    confirmation_status: str
    status: str


class FulfillmentUpdateResponse(BaseModel):
    todo_id: UUID
    fulfillment_status: str


class DeleteCountResponse(BaseModel):
    deleted_count: int
    message: str


class ImportCSVResponse(BaseModel):
    imported_count: int
    created_entities: int
    created_todos: int
    message: str


class TTSFallbackResponse(BaseModel):
    text: str
    use_client_tts: bool = True


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    service: str
    version: str | None = None
    components: dict | None = None


class ExportLimitResponse(BaseModel):
    error: dict

"""Event endpoints for receiving and managing input events.

The main router (``router``) hosts the core CRUD endpoints (create,
upload, get, delete) and includes two sub-routers:
  - :mod:`event_pipeline_api` — batch, retry, accept-degraded, correct (纠偏)
  - :mod:`event_search_api` — list/search/filter

All route paths remain identical to the original single-module layout.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import APIRouter, BackgroundTasks, Depends, Form, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError, ValidationError
from promiselink.core.file_utils import decode_content
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models import Entity, Event
from promiselink.models.association import Association
from promiselink.models.todo import Todo as _Todo
from promiselink.services.entity_cleanup import delete_event_cascade
from promiselink.services.event_processor import process_event_background

logger = get_logger("promiselink.api.events")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

__all__ = [
    "router",
    "EventCreateRequest",
    "EventEntityRef",
    "EventEntityDetail",
    "EventAssociationRef",
    "EventResponse",
    "EventTodoRef",
    "EventDetailResponse",
    "EventCreateResponse",
    # Re-exported from event_pipeline_api for backward compatibility
    "BatchEventCreateRequest",
    "BatchEventCreateResponse",
]


# Request/Response schemas
class EventCreateRequest(BaseModel):
    """Request schema for creating an event."""

    event_type: str = Field(..., description="Event type: card_save, meeting, call, manual")
    source: str = Field(..., description="Data source identifier")
    title: str = Field(default="未命名", max_length=200, description="Event title (auto-generated from raw_text if omitted)")
    timestamp: datetime | None = Field(default=None, description="Event timestamp")
    raw_text: str | None = Field(default=None, description="Raw text content (max 500KB)")
    metadata: dict[str, Any] | None = Field(default=None, description="Additional metadata")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "card_save",
                "source": "iamhere_app",
                "title": "Business card from John Doe",
                "timestamp": "2026-06-02T12:00:00Z",
                "raw_text": '{"name": "John Doe", "company": "Tech Corp", ...}',
                "metadata": {
                    "scan_quality": "high",
                    "device": "iPhone 15 Pro"
                }
            }
        }
    )


class EventEntityRef(BaseModel):
    """Lightweight entity reference for event cards."""
    id: str
    name: str


class EventEntityDetail(BaseModel):
    """Detailed entity reference for event detail (纠偏用)."""

    id: str
    name: str
    entity_type: str
    company: str | None = None
    title: str | None = None
    status: str = "confirmed"
    confidence: float = 1.0


class EventAssociationRef(BaseModel):
    """Lightweight association reference for event detail (关系区)."""

    id: str
    source_entity_name: str
    target_entity_name: str
    association_type: str
    strength: float = 0.5


class EventResponse(BaseModel):
    """Response schema for event data."""

    id: str
    user_id: str
    event_type: str
    source: str
    title: str
    timestamp: datetime
    status: str
    created_at: datetime
    entities: list[EventEntityRef] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class EventTodoRef(BaseModel):
    """Lightweight todo reference for event detail."""

    id: str
    todo_type: str
    title: str
    status: str
    description: str | None = None
    due_date: datetime | None = None
    priority: int = 3
    related_entity_id: str | None = None
    confirmation_status: str | None = None
    action_type: str | None = None
    evidence_quote: str | None = None


class EventDetailResponse(EventResponse):
    """Detailed response schema including raw data."""

    raw_text: str | None
    event_metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    pipeline: str | None
    processed_at: datetime | None
    failed_steps: list[str] | None = Field(default=None, description="Steps that failed during pipeline processing (set when status is failed)")
    related_todos: list[EventTodoRef] = Field(default_factory=list, description="Todos generated from this event")
    related_entities: list[EventEntityDetail] = Field(default_factory=list, description="Entities extracted from this event (for 纠偏)")
    related_associations: list[EventAssociationRef] = Field(default_factory=list, description="Associations discovered from this event (关系区)")

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class EventCreateResponse(EventResponse):
    """Response schema for event creation including pipeline status."""

    pipeline_status: str = "pending"
    entity_count: int = 0
    todo_count: int = 0


@router.post("/events", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    request: EventCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> EventCreateResponse:
    """
    Create a new event from external source and trigger processing pipeline.

    This is the primary input endpoint for PromiseLink.
    Accepts events from:
    - Card scan (IAMHERE integration)
    - Meeting transcripts
    - Call records
    - Manual input

    The event is created immediately and the processing pipeline runs
    asynchronously in the background.
    """
    new_request_id()

    # Validate event type
    valid_types = Event.VALID_TYPES
    if request.event_type not in valid_types:
        raise ValidationError(
            f"Invalid event_type. Must be one of: {', '.join(valid_types)}",
            details={"event_type": request.event_type, "valid_types": valid_types},
        )

    # Validate raw_text size (500KB max)
    if request.raw_text and len(request.raw_text.encode('utf-8')) > 512000:
        raise ValidationError(
            "raw_text exceeds 500KB limit",
            details={"size_bytes": len(request.raw_text.encode('utf-8')), "max_bytes": 512000},
        )

    # Create event
    event = Event(
        user_id=user_id,
        event_type=request.event_type,
        source=request.source,
        title=request.title,
        timestamp=request.timestamp or datetime.now(UTC),
        raw_text=request.raw_text,
        metadata_=request.metadata,
        status="pending",
    )

    session.add(event)
    await session.commit()
    await session.refresh(event)

    logger.info(
        "event_created",
        event_id=str(event.id),
        event_type=event.event_type,
    )

    # Trigger async processing pipeline in background
    background_tasks.add_task(process_event_background, event_id=event.id)

    return EventCreateResponse(
        id=str(event.id),
        user_id=str(event.user_id),
        event_type=event.event_type,
        source=event.source,
        title=event.title,
        timestamp=event.timestamp,
        status=event.status,
        created_at=event.created_at,
        pipeline_status="pending",
        entity_count=0,
        todo_count=0,
        entities=[],
    )


@router.post("/events/upload", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
async def upload_event_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    event_type: str = Form(default="meeting"),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> EventCreateResponse:
    """
    Upload a .txt or .md file and create an event from its content.

    The file content is decoded (UTF-8 with GBK fallback), markdown
    formatting is stripped if the file is .md, and an Event is created
    with source='file_upload'. The processing pipeline runs asynchronously.
    """
    new_request_id()

    # ── Validate file extension ──
    if not file.filename:
        raise ValidationError("No filename provided")

    ext = file.filename.lower().rsplit(".", 1)[-1] if "." in file.filename else ""
    if ext not in ("txt", "md"):
        raise ValidationError(
            "Only .txt and .md files are accepted",
            details={"filename": file.filename},
        )

    # ── Read and validate file size (1MB max) ──
    content = await file.read(1_048_577)  # read 1MB + 1 byte to detect oversize
    if len(content) > 1_048_576:
        raise ValidationError(
            "File size exceeds 1MB limit",
            details={"max_bytes": 1_048_576},
        )

    if not content:
        raise ValidationError("Uploaded file is empty")

    # ── Decode content ──
    text = decode_content(content)

    # ── Strip markdown if .md file ──
    if ext == "md":
        text = _strip_markdown(text)

    # ── Validate event type ──
    valid_types = Event.VALID_TYPES
    if event_type not in valid_types:
        raise ValidationError(
            f"Invalid event_type. Must be one of: {', '.join(valid_types)}",
            details={"event_type": event_type, "valid_types": valid_types},
        )

    # ── Create event ──
    event = Event(
        user_id=user_id,
        event_type=event_type,
        source="file_upload",
        title=file.filename,
        timestamp=datetime.now(UTC),
        raw_text=text,
        metadata_={"original_filename": file.filename},
        status="pending",
    )

    session.add(event)
    await session.commit()
    await session.refresh(event)

    logger.info(
        "event_uploaded",
        event_id=str(event.id),
        filename=file.filename,
        event_type=event.event_type,
    )

    # Trigger async processing pipeline in background
    background_tasks.add_task(process_event_background, event_id=event.id)

    return EventCreateResponse(
        id=str(event.id),
        user_id=str(event.user_id),
        event_type=event.event_type,
        source=event.source,
        title=event.title,
        timestamp=event.timestamp,
        status=event.status,
        created_at=event.created_at,
        pipeline_status="pending",
        entity_count=0,
        todo_count=0,
        entities=[],
    )


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> EventDetailResponse:
    """
    Get detailed information about a specific event.
    """
    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    # Fetch related todos
    todo_result = await session.execute(
        select(
            _Todo.id, _Todo.todo_type, _Todo.title, _Todo.status, _Todo.description,
            _Todo.due_date, _Todo.priority, _Todo.related_entity_id,
            _Todo.confirmation_status, _Todo.action_type, _Todo.evidence_quote,
        )
        .where(_Todo.source_event_id == str(event_id))
        .order_by(_Todo.created_at.asc())
    )
    related_todos = [
        EventTodoRef(
            id=str(tid), todo_type=ttype, title=ttitle, status=tstatus,
            description=tdesc, due_date=tddate, priority=tprio,
            related_entity_id=str(tent) if tent else None,
            confirmation_status=tconf, action_type=taction, evidence_quote=tevidence,
        )
        for tid, ttype, ttitle, tstatus, tdesc, tddate, tprio, tent, tconf, taction, tevidence in todo_result.fetchall()
    ]

    # Fetch related entities (extracted from this event) with company/title for 纠偏
    entity_result = await session.execute(
        select(Entity).where(
            Entity.source_event_id == str(event_id),
            Entity.user_id == user_id,
        ).order_by(Entity.created_at.asc())
    )
    related_entities: list[EventEntityDetail] = []
    for ent in entity_result.scalars().all():
        props = ent.properties or {}
        basic = props.get("basic") if isinstance(props, dict) else None
        company = basic.get("company") if isinstance(basic, dict) else None
        title = basic.get("title") if isinstance(basic, dict) else None
        related_entities.append(EventEntityDetail(
            id=str(ent.id), name=ent.name, entity_type=ent.entity_type,
            company=company, title=title, status=ent.status, confidence=ent.confidence,
        ))

    # Fetch related associations (discovered from this event) for 关系区
    assoc_result = await session.execute(
        select(
            Association.id, Association.source_entity_id, Association.target_entity_id,
            Association.association_type, Association.strength,
        )
        .where(Association.source_event_id == str(event_id))
        .order_by(Association.strength.desc())
    )
    assoc_rows = assoc_result.fetchall()
    # Build entity name lookup
    assoc_entity_ids = {str(r[1]) for r in assoc_rows} | {str(r[2]) for r in assoc_rows}
    assoc_entity_names: dict[str, str] = {}
    if assoc_entity_ids:
        name_result = await session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(list(assoc_entity_ids)))
        )
        assoc_entity_names = {str(eid): name for eid, name in name_result.all()}
    related_associations = [
        EventAssociationRef(
            id=str(aid),
            source_entity_name=assoc_entity_names.get(str(src_id), "未知"),
            target_entity_name=assoc_entity_names.get(str(tgt_id), "未知"),
            association_type=atype,
            strength=astrength,
        )
        for aid, src_id, tgt_id, atype, astrength in assoc_rows
    ]

    return EventDetailResponse.model_validate(event, from_attributes=True).model_copy(update={
        "related_todos": related_todos,
        "related_entities": related_entities,
        "related_associations": related_associations,
    })


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """
    Delete an event.

    Note: This will cascade delete related entities if configured.
    """
    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    # Cascade delete related entities, associations, and todos via service
    await delete_event_cascade(session, str(event_id), user_id)

    await session.delete(event)
    await session.commit()

    return None


# ── Helpers ──


def _strip_markdown(text: str) -> str:
    """Strip common markdown formatting while preserving text content.

    Removes: # headers, **bold**, *italic*, [link](url), ```code blocks```,
    > blockquotes, - and * list markers.
    """
    import re

    # Remove code blocks (```...```) but keep content
    text = re.sub(r"```[\s\S]*?```", lambda m: m.group(0).strip("`").strip(), text)

    # Remove inline code (`...`) but keep content
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Remove link syntax [text](url) → keep text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove bold markers (**text** or __text__)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)

    # Remove italic markers (*text* or _text_) — careful not to match bullets
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"\1", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"\1", text)

    # Remove header markers (# ## ### etc.) at line start
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

    # Remove blockquote markers (>) at line start
    text = re.sub(r"^>\s*", "", text, flags=re.MULTILINE)

    # Remove unordered list markers (- or * at line start)
    text = re.sub(r"^[\-\*]\s+", "", text, flags=re.MULTILINE)

    # Remove ordered list markers (1. 2. etc. at line start)
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)

    return text


# ── Sub-router inclusion ──
# Imported AFTER schema definitions above to avoid circular imports:
# the sub-modules import EventResponse / EventEntityRef from this module.
# Backward-compat re-export: batch schemas now live in event_pipeline_api
# but are re-exported here so existing `from promiselink.api.v1.events import
# BatchEventCreateRequest` keeps working.
from promiselink.api.v1.event_pipeline_api import (  # noqa: E402
    BatchEventCreateRequest,
    BatchEventCreateResponse,
    pipeline_router,  # noqa: E402
)
from promiselink.api.v1.event_search_api import search_router  # noqa: E402

router.include_router(
    cast(APIRouter, pipeline_router),  # type: ignore[has-type]
    dependencies=[Depends(rate_limit_dependency)],
)
router.include_router(
    cast(APIRouter, search_router),  # type: ignore[has-type]
    dependencies=[Depends(rate_limit_dependency)],
)

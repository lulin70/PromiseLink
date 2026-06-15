"""Event endpoints for receiving and managing input events."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError, ValidationError
from promiselink.core.file_utils import decode_content
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models import Entity, Event
from promiselink.models.todo import Todo as _Todo
from promiselink.services.entity_cleanup import delete_event_cascade
from promiselink.services.event_processor import process_event_background

logger = get_logger("promiselink.api.events")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


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


class EventDetailResponse(EventResponse):
    """Detailed response schema including raw data."""

    raw_text: str | None
    event_metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    pipeline: str | None
    processed_at: datetime | None
    failed_steps: list[str] | None = Field(default=None, description="Steps that failed during pipeline processing (set when status is failed)")
    related_todos: list[EventTodoRef] = Field(default_factory=list, description="Todos generated from this event")

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
):
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
        id=event.id,
        user_id=event.user_id,
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


class BatchEventCreateRequest(BaseModel):
    """Request schema for batch creating events."""

    events: list[EventCreateRequest] = Field(
        ..., min_length=1, max_length=20,
        description="List of events to create (max 20 per batch)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "events": [
                    {
                        "event_type": "meeting",
                        "source": "manual",
                        "title": "上午与李总讨论合作",
                        "raw_text": "今天上午和李总讨论了新项目的合作方案..."
                    },
                    {
                        "event_type": "call",
                        "source": "manual",
                        "title": "下午与陈宇鑫电话沟通",
                        "raw_text": "和陈宇鑫通了电话，确认了技术对接的时间..."
                    }
                ]
            }
        }
    )


class BatchEventCreateResponse(BaseModel):
    """Response schema for batch event creation."""

    created: list[EventCreateResponse]
    failed: list[dict[str, Any]]
    total_requested: int
    total_created: int


@router.post("/events/batch", response_model=BatchEventCreateResponse, status_code=status.HTTP_201_CREATED)
async def batch_create_events(
    request: BatchEventCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """
    Batch create events and trigger processing pipeline for each.

    Accepts up to 20 events in a single request. Each event is created
    independently — if one fails, others still succeed. Pipeline processing
    runs serially in the background (one at a time) to avoid SQLite lock contention.
    """
    new_request_id()

    valid_types = Event.VALID_TYPES
    created: list[EventCreateResponse] = []
    failed: list[dict[str, Any]] = []

    for idx, event_req in enumerate(request.events):
        try:
            # Validate event type
            if event_req.event_type not in valid_types:
                failed.append({
                    "index": idx,
                    "error": f"Invalid event_type: {event_req.event_type}",
                })
                continue

            # Validate raw_text size
            if event_req.raw_text and len(event_req.raw_text.encode("utf-8")) > 512000:
                failed.append({
                    "index": idx,
                    "error": "raw_text exceeds 500KB limit",
                })
                continue

            event = Event(
                user_id=user_id,
                event_type=event_req.event_type,
                source=event_req.source,
                title=event_req.title,
                timestamp=event_req.timestamp or datetime.now(UTC),
                raw_text=event_req.raw_text,
                metadata_=event_req.metadata,
                status="pending",
            )

            session.add(event)
            await session.commit()
            await session.refresh(event)

            # Queue pipeline processing (runs serially via Pipeline lock)
            background_tasks.add_task(process_event_background, event_id=event.id)

            created.append(EventCreateResponse(
                id=event.id,
                user_id=event.user_id,
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
            ))

            logger.info(
                "batch_event_created",
                event_id=str(event.id),
                batch_index=idx,
                event_type=event.event_type,
            )

        except Exception as e:
            failed.append({
                "index": idx,
                "error": str(e),
            })
            # Rollback this event but continue with others
            await session.rollback()

    return BatchEventCreateResponse(
        created=created,
        failed=failed,
        total_requested=len(request.events),
        total_created=len(created),
    )


@router.post("/events/upload", response_model=EventCreateResponse, status_code=status.HTTP_201_CREATED)
async def upload_event_file(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    event_type: str = Form(default="meeting"),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
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
        id=event.id,
        user_id=event.user_id,
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


@router.get("/events", response_model=PaginatedResponse[EventResponse])
async def list_events(
    event_type: str | None = None,
    status: str | None = None,
    search: str | None = Query(None, description="Search in title and raw_text"),
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """
    List events with optional filtering.
    
    Query parameters:
    - event_type: Filter by event type
    - status: Filter by processing status
    - search: Search in title and raw_text
    - limit: Maximum number of results (default: 100, max: 500)
    - offset: Pagination offset (default: 0)
    """
    query = select(Event).where(Event.user_id == user_id)
    
    if event_type:
        query = query.where(Event.event_type == event_type)
    if status:
        query = query.where(Event.status == status)
    if search:
        query = query.where(Event.title.ilike(f"%{search}%") | Event.raw_text.ilike(f"%{search}%"))
    
    # Count total
    count_query = select(func.count()).select_from(Event).where(Event.user_id == user_id)
    if event_type:
        count_query = count_query.where(Event.event_type == event_type)
    if status:
        count_query = count_query.where(Event.status == status)
    if search:
        count_query = count_query.where(Event.title.ilike(f"%{search}%") | Event.raw_text.ilike(f"%{search}%"))
    total = (await session.execute(count_query)).scalar() or 0
    
    # Fetch paginated
    # TODO(P3): For large datasets, consider cursor-based pagination (e.g., based on
    # created_at + id) instead of offset-based pagination to avoid performance
    # degradation at high offsets. See: https://use-the-index-luke.com/no-offset
    query = query.order_by(Event.created_at.desc()).limit(min(limit, 500)).offset(offset)
    result = await session.execute(query)
    events = result.scalars().all()

    # Fetch entity names for all events
    event_ids = [str(e.id) for e in events]
    event_entities: dict[str, list[EventEntityRef]] = {}
    if event_ids:
        entity_result = await session.execute(
            select(Entity.id, Entity.name, Entity.source_event_id).where(
                Entity.source_event_id.in_(event_ids),
                Entity.user_id == user_id,
            )
        )
        for eid, name, src_event_id in entity_result.all():
            sid = str(src_event_id)
            if sid not in event_entities:
                event_entities[sid] = []
            event_entities[sid].append(EventEntityRef(id=str(eid), name=name))

    items = []
    for e in events:
        items.append(EventResponse(
            id=str(e.id),
            user_id=str(e.user_id),
            event_type=e.event_type,
            source=e.source,
            title=e.title,
            timestamp=e.timestamp,
            status=e.status,
            created_at=e.created_at,
            entities=event_entities.get(str(e.id), []),
        ))

    return PaginatedResponse(items=items, total=total, limit=min(limit, 500), offset=offset)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
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
        select(_Todo.id, _Todo.todo_type, _Todo.title, _Todo.status)
        .where(_Todo.source_event_id == str(event_id))
        .order_by(_Todo.created_at.asc())
    )
    related_todos = [
        EventTodoRef(id=str(tid), todo_type=ttype, title=ttitle, status=tstatus)
        for tid, ttype, ttitle, tstatus in todo_result.fetchall()
    ]

    return EventDetailResponse.model_validate(event, from_attributes=True).model_copy(update={"related_todos": related_todos})


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
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


@router.post("/events/{event_id}/retry", response_model=EventResponse)
async def retry_event(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Retry processing an event that failed or is awaiting retry.

    Resets event status to pending and re-triggers the pipeline.
    Only works for events in 'failed' or 'awaiting_retry' status.
    """

    new_request_id()

    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id,
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    if event.status not in ("failed", "awaiting_retry"):
        raise ValidationError("Event is not in a retryable state")

    # Reset status and re-trigger pipeline
    event.status = "pending"
    event.processed_at = None
    event.failed_steps = None
    await session.commit()

    background_tasks.add_task(process_event_background, event_id=event_id)

    logger.info("event_retry_triggered", event_id=str(event_id))

    # Refresh to get updated state
    await session.refresh(event)
    return event


@router.post("/events/{event_id}/accept-degraded", response_model=EventResponse)
async def accept_degraded_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Accept degraded processing result for an event awaiting retry.

    Marks the event as degraded_completed, preserving whatever partial
    results were generated. User explicitly chooses this over retrying.
    """
    new_request_id()

    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id,
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    if event.status not in ("awaiting_retry", "failed"):
        raise ValidationError("Event is not in a degradable state")

    event.status = "degraded_completed"
    event.processed_at = datetime.now(UTC)
    await session.commit()

    logger.info("event_degraded_accepted", event_id=str(event_id))

    await session.refresh(event)
    return event


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

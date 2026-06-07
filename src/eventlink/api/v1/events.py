"""Event endpoints for receiving and managing input events."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.api.v1.schemas import PaginatedResponse
from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models import Event
from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.todo import Todo

logger = get_logger("eventlink.api.events")
router = APIRouter()


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


class EventResponse(BaseModel):
    """Response schema for event data."""
    
    id: uuid.UUID
    user_id: uuid.UUID
    event_type: str
    source: str
    title: str
    timestamp: datetime
    status: str
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class EventDetailResponse(EventResponse):
    """Detailed response schema including raw data."""
    
    raw_text: str | None
    event_metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    pipeline: str | None
    processed_at: datetime | None

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
    user_id: str = Depends(get_optional_user_id),
):
    """
    Create a new event from external source and trigger processing pipeline.
    
    This is the primary input endpoint for EventLink.
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
    valid_types = ["card_save", "meeting", "call", "manual", "email", "wechat_forward"]
    if request.event_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid event_type. Must be one of: {', '.join(valid_types)}"
        )
    
    # Validate raw_text size (500KB max)
    if request.raw_text and len(request.raw_text.encode('utf-8')) > 512000:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="raw_text exceeds 500KB limit"
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
    background_tasks.add_task(_process_event_background, event_id=event.id)

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
    )


@router.get("/events", response_model=PaginatedResponse[EventResponse])
async def list_events(
    event_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
):
    """
    List events with optional filtering.
    
    Query parameters:
    - event_type: Filter by event type
    - status: Filter by processing status
    - limit: Maximum number of results (default: 100, max: 500)
    - offset: Pagination offset (default: 0)
    """
    query = select(Event).where(Event.user_id == user_id)
    
    if event_type:
        query = query.where(Event.event_type == event_type)
    if status:
        query = query.where(Event.status == status)
    
    # Count total
    count_query = select(func.count()).select_from(Event).where(Event.user_id == user_id)
    if event_type:
        count_query = count_query.where(Event.event_type == event_type)
    if status:
        count_query = count_query.where(Event.status == status)
    total = (await session.execute(count_query)).scalar() or 0
    
    # Fetch paginated
    query = query.order_by(Event.created_at.desc()).limit(min(limit, 500)).offset(offset)
    result = await session.execute(query)
    events = result.scalars().all()
    
    return PaginatedResponse(items=events, total=total, limit=min(limit, 500), offset=offset)


@router.get("/events/{event_id}", response_model=EventDetailResponse)
async def get_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )
    
    return event


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    # Cascade delete related entities, associations, and todos
    entity_result = await session.execute(
        select(Entity).where(Entity.source_event_id == str(event_id))
    )
    entity_ids = [str(e.id) for e in entity_result.scalars().all()]

    if entity_ids:
        # Delete associations involving these entities
        for eid in entity_ids:
            await session.execute(
                Association.__table__.delete().where(
                    (Association.source_entity_id == eid) | (Association.target_entity_id == eid)
                )
            )
        # Delete todos referencing these entities
        await session.execute(
            Todo.__table__.delete().where(Todo.related_entity_id.in_(entity_ids))
        )
        # Delete todos from this event
        await session.execute(
            Todo.__table__.delete().where(Todo.source_event_id == str(event_id))
        )
        # Delete entities
        for eid in entity_ids:
            await session.execute(
                Entity.__table__.delete().where(Entity.id == eid)
            )
    else:
        # Still delete todos from this event even if no entities
        await session.execute(
            Todo.__table__.delete().where(Todo.source_event_id == str(event_id))
        )

    await session.delete(event)
    await session.commit()
    
    return None


# ── Background Pipeline Processing ──


async def _process_event_background(event_id: uuid.UUID) -> None:
    """Process an event through the pipeline in the background.

    Delegates to the unified pipeline entry point in event_pipeline.py.
    This is the single entry point for all background event processing.

    Args:
        event_id: The ID of the event to process.
    """
    from eventlink.services.event_pipeline import process_event_with_short_transactions

    await process_event_with_short_transactions(event_id=str(event_id))

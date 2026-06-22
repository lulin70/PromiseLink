"""ScheduledEvent API endpoints — CRUD, record conversion, and cancel."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ConflictError, NotFoundError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models import Event
from promiselink.models.scheduled_event import ScheduledEvent
from promiselink.services.event_processor import process_event_background

logger = get_logger("promiselink.api.scheduled_events")
router = APIRouter(
    prefix="/scheduled-events",
    dependencies=[Depends(rate_limit_dependency)],
    tags=["ScheduledEvents"],
)


# ── Pydantic Schemas ──


class ParticipantItem(BaseModel):
    """A participant in a scheduled event."""

    name: str = Field(..., min_length=1, max_length=100)
    entity_id: str | None = Field(None, description="Matched Entity ID if found")
    company: str | None = None


class ScheduledEventCreateRequest(BaseModel):
    """Request schema for creating a scheduled event."""

    scheduled_at: datetime = Field(..., description="Planned date/time (ISO 8601)")
    topic: str = Field(..., min_length=1, max_length=200, description="Schedule topic")
    participants: list[ParticipantItem] = Field(default_factory=list)
    location: str | None = Field(None, max_length=200)
    event_type: str = Field(
        default="meeting",
        description="Expected event type: meeting, call, manual",
    )
    reminder_at: datetime | None = Field(None, description="When to send reminder")
    metadata: dict[str, Any] | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "scheduled_at": "2026-06-20T14:00:00+08:00",
                "topic": "与张总讨论新项目合作",
                "participants": [{"name": "张总", "company": "ABC科技"}],
                "location": "望京SOHO",
                "event_type": "meeting",
            }
        }
    )


class ScheduledEventUpdateRequest(BaseModel):
    """Request schema for updating a scheduled event (pending only)."""

    scheduled_at: datetime | None = None
    topic: str | None = Field(None, min_length=1, max_length=200)
    participants: list[ParticipantItem] | None = None
    location: str | None = Field(None, max_length=200)
    event_type: str | None = None
    reminder_at: datetime | None = None


class ScheduledEventResponse(BaseModel):
    """Response schema for scheduled event data."""

    id: str
    user_id: str
    scheduled_at: datetime
    topic: str
    participants: list[dict[str, Any]] | None
    location: str | None
    event_type: str
    status: str
    linked_event_id: str | None
    cancel_reason: str | None
    reminder_at: datetime | None
    event_metadata: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime
    updated_at: datetime
    recorded_at: datetime | None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class RecordRequest(BaseModel):
    """Request schema for recording a scheduled event."""

    raw_text: str = Field(..., min_length=1, description="Actual conversation content")
    event_type: str | None = Field(
        None,
        description="Override event type (defaults to scheduled event_type)",
    )


class RecordResponse(BaseModel):
    """Response schema after recording a scheduled event."""

    scheduled_event_id: str
    event_id: str
    pipeline_status: str


class CancelRequest(BaseModel):
    """Request schema for cancelling a scheduled event."""

    cancel_reason: str | None = Field(None, max_length=500)


# ── Endpoints ──


@router.post("", response_model=ScheduledEventResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_event(
    request: ScheduledEventCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Create a new scheduled event (planned future interaction)."""
    new_request_id()

    # Validate event_type
    if request.event_type not in ScheduledEvent.VALID_EVENT_TYPES:
        raise ValidationError(
            f"Invalid event_type. Must be one of: {', '.join(ScheduledEvent.VALID_EVENT_TYPES)}",
            details={"event_type": request.event_type},
        )

    # Determine initial status: if scheduled_at is in the past, mark overdue
    now = datetime.now(UTC)
    initial_status = "overdue" if request.scheduled_at <= now else "pending"

    # Try to match participants with existing entities
    participants_data = [p.model_dump() for p in request.participants]
    if participants_data:
        participants_data = await _match_participants(session, user_id, participants_data)

    se = ScheduledEvent(
        user_id=user_id,
        scheduled_at=request.scheduled_at,
        topic=request.topic,
        participants=participants_data or None,
        location=request.location,
        event_type=request.event_type,
        status=initial_status,
        reminder_at=request.reminder_at,
        metadata_=request.metadata,
    )

    session.add(se)
    await session.commit()
    await session.refresh(se)

    logger.info(
        "scheduled_event_created",
        scheduled_event_id=str(se.id),
        status=se.status,
        scheduled_at=se.scheduled_at.isoformat(),
    )

    return se


@router.get("", response_model=PaginatedResponse[ScheduledEventResponse])
async def list_scheduled_events(
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    scheduled_from: datetime | None = Query(None, description="From date (inclusive)"),
    scheduled_to: datetime | None = Query(None, description="To date (inclusive)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """List scheduled events with optional filtering."""
    new_request_id()

    query = select(ScheduledEvent).where(ScheduledEvent.user_id == user_id)
    count_query = select(func.count()).select_from(ScheduledEvent).where(
        ScheduledEvent.user_id == user_id
    )

    if status_filter:
        if status_filter not in ScheduledEvent.VALID_STATUSES:
            raise ValidationError(
                f"Invalid status filter. Must be one of: {', '.join(ScheduledEvent.VALID_STATUSES)}",
            )
        query = query.where(ScheduledEvent.status == status_filter)
        count_query = count_query.where(ScheduledEvent.status == status_filter)

    if scheduled_from:
        query = query.where(ScheduledEvent.scheduled_at >= scheduled_from)
        count_query = count_query.where(ScheduledEvent.scheduled_at >= scheduled_from)

    if scheduled_to:
        query = query.where(ScheduledEvent.scheduled_at <= scheduled_to)
        count_query = count_query.where(ScheduledEvent.scheduled_at <= scheduled_to)

    total = (await session.execute(count_query)).scalar() or 0

    query = query.order_by(ScheduledEvent.scheduled_at.asc()).limit(limit).offset(offset)
    result = await session.execute(query)
    items = result.scalars().all()

    return PaginatedResponse(items=list(items), total=total, limit=limit, offset=offset)


@router.get("/{scheduled_event_id}", response_model=ScheduledEventResponse)
async def get_scheduled_event(
    scheduled_event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Get detailed information about a specific scheduled event."""
    new_request_id()

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.id == str(scheduled_event_id),
                ScheduledEvent.user_id == user_id,
            )
        )
    )
    se = result.scalar_one_or_none()

    if not se:
        raise NotFoundError("Scheduled event not found")

    return se


@router.patch("/{scheduled_event_id}", response_model=ScheduledEventResponse)
async def update_scheduled_event(
    scheduled_event_id: uuid.UUID,
    request: ScheduledEventUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Update a pending scheduled event."""
    new_request_id()

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.id == str(scheduled_event_id),
                ScheduledEvent.user_id == user_id,
            )
        )
    )
    se = result.scalar_one_or_none()

    if not se:
        raise NotFoundError("Scheduled event not found")

    if se.status not in ("pending", "overdue"):
        raise ValidationError("Only pending or overdue scheduled events can be updated")

    # Apply updates
    if request.scheduled_at is not None:
        se.scheduled_at = request.scheduled_at
        # Re-check overdue status
        now = datetime.now(UTC)
        if se.scheduled_at <= now and se.status == "pending":
            se.status = "overdue"
        elif se.scheduled_at > now and se.status == "overdue":
            se.status = "pending"

    if request.topic is not None:
        se.topic = request.topic
    if request.participants is not None:
        se.participants = [p.model_dump() for p in request.participants]
    if request.location is not None:
        se.location = request.location
    if request.event_type is not None:
        if request.event_type not in ScheduledEvent.VALID_EVENT_TYPES:
            raise ValidationError(
                f"Invalid event_type. Must be one of: {', '.join(ScheduledEvent.VALID_EVENT_TYPES)}",
            )
        se.event_type = request.event_type
    if request.reminder_at is not None:
        se.reminder_at = request.reminder_at

    await session.commit()
    await session.refresh(se)

    logger.info("scheduled_event_updated", scheduled_event_id=str(se.id))

    return se


@router.delete("/{scheduled_event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scheduled_event(
    scheduled_event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> None:
    """Delete a pending scheduled event."""
    new_request_id()

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.id == str(scheduled_event_id),
                ScheduledEvent.user_id == user_id,
            )
        )
    )
    se = result.scalar_one_or_none()

    if not se:
        raise NotFoundError("Scheduled event not found")

    if se.status not in ("pending", "overdue"):
        raise ValidationError("Only pending or overdue scheduled events can be deleted")

    await session.delete(se)
    await session.commit()

    logger.info("scheduled_event_deleted", scheduled_event_id=str(scheduled_event_id))

    return None


@router.post("/{scheduled_event_id}/record", response_model=RecordResponse)
async def record_scheduled_event(
    scheduled_event_id: uuid.UUID,
    request: RecordRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> RecordResponse:
    """Record actual content for a scheduled event.

    Creates an Event from the recorded content, links it to the
    ScheduledEvent, and triggers the 13-step parsing pipeline.
    """
    new_request_id()

    # Validate raw_text size (same as Event: 500KB max)
    if len(request.raw_text.encode("utf-8")) > 512000:
        raise ValidationError(
            "raw_text exceeds 500KB limit",
            details={"size_bytes": len(request.raw_text.encode("utf-8"))},
        )

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.id == str(scheduled_event_id),
                ScheduledEvent.user_id == user_id,
            )
        )
    )
    se = result.scalar_one_or_none()

    if not se:
        raise NotFoundError("Scheduled event not found")

    if se.status not in ("pending", "overdue"):
        raise ConflictError(
            "Scheduled event is not in a recordable state",
            details={"current_status": se.status, "expected": ["pending", "overdue"]},
        )

    # Determine event_type (allow override)
    final_event_type = request.event_type or se.event_type
    if final_event_type not in Event.VALID_TYPES:
        raise ValidationError(
            f"Invalid event_type. Must be one of: {', '.join(Event.VALID_TYPES)}",
        )

    # Build participants context for raw_text prefix
    participants_prefix = ""
    if se.participants:
        names = [p.get("name", "") for p in se.participants if p.get("name")]
        if names:
            participants_prefix = f"（与{'、'.join(names)}）"

    # Create Event
    event = Event(
        user_id=user_id,
        event_type=final_event_type,
        source="scheduled_record",
        title=se.topic,
        timestamp=datetime.now(UTC),
        raw_text=participants_prefix + request.raw_text if request.raw_text else participants_prefix,
        metadata_={
            "scheduled_event_id": str(se.id),
            "scheduled_at": se.scheduled_at.isoformat(),
            "original_participants": se.participants,
            "location": se.location,
        },
        status="pending",
    )

    session.add(event)

    # Update ScheduledEvent
    se.status = "recorded"
    se.recorded_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(event)

    # Link after commit (event.id is now available)
    se.linked_event_id = event.id
    await session.commit()

    # Trigger async processing pipeline
    background_tasks.add_task(process_event_background, event_id=event.id)

    logger.info(
        "scheduled_event_recorded",
        scheduled_event_id=str(se.id),
        event_id=str(event.id),
    )

    return RecordResponse(
        scheduled_event_id=str(se.id),
        event_id=str(event.id),
        pipeline_status="pending",
    )


@router.post("/{scheduled_event_id}/cancel", response_model=ScheduledEventResponse)
async def cancel_scheduled_event(
    scheduled_event_id: uuid.UUID,
    request: CancelRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Cancel a scheduled event (pending or overdue only)."""
    new_request_id()

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.id == str(scheduled_event_id),
                ScheduledEvent.user_id == user_id,
            )
        )
    )
    se = result.scalar_one_or_none()

    if not se:
        raise NotFoundError("Scheduled event not found")

    if se.status not in ("pending", "overdue"):
        raise ConflictError(
            "Scheduled event is not in a cancellable state",
            details={"current_status": se.status, "expected": ["pending", "overdue"]},
        )

    se.status = "cancelled"
    se.cancel_reason = request.cancel_reason

    await session.commit()
    await session.refresh(se)

    logger.info(
        "scheduled_event_cancelled",
        scheduled_event_id=str(se.id),
        has_reason=bool(request.cancel_reason),
    )

    return se


# ── Overdue Marking (called by background task) ──


async def mark_overdue_scheduled_events(session: AsyncSession) -> int:
    """Mark pending scheduled events as overdue if past their scheduled_at.

    Returns the number of events marked as overdue.
    """
    now = datetime.now(UTC)

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.status == "pending",
                ScheduledEvent.scheduled_at <= now,
            )
        )
    )
    overdue_events = result.scalars().all()

    count = 0
    for se in overdue_events:
        se.status = "overdue"
        count += 1

    if count > 0:
        await session.commit()

    logger.info("overdue_scheduled_events_marked", count=count)
    return count


# ── Cancelled Cleanup (30-day auto-cleanup) ──


async def cleanup_cancelled_scheduled_events(session: AsyncSession) -> int:
    """Delete cancelled scheduled events older than 30 days.

    Returns the number of events deleted.
    """
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(days=30)

    result = await session.execute(
        select(ScheduledEvent).where(
            and_(
                ScheduledEvent.status == "cancelled",
                ScheduledEvent.updated_at <= cutoff,
            )
        )
    )
    old_cancelled = result.scalars().all()

    count = 0
    for se in old_cancelled:
        await session.delete(se)
        count += 1

    if count > 0:
        await session.commit()

    logger.info("cancelled_scheduled_events_cleaned", count=count)
    return count


# ── Helpers ──


async def _match_participants(
    session: AsyncSession,
    user_id: str,
    participants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Try to match participant names with existing Entity records."""
    from promiselink.models import Entity

    for p in participants:
        name = p.get("name", "").strip()
        if not name or p.get("entity_id"):
            continue

        # Try exact match on canonical_name or alias.
        # Entity.status legal values: provisional/confirmed/merged/deleted.
        # Match active (non-deleted, non-merged) entities only.
        result = await session.execute(
            select(Entity.id, Entity.name).where(
                and_(
                    Entity.user_id == user_id,
                    Entity.status.in_(["confirmed", "provisional"]),
                    (Entity.canonical_name == name) | (Entity.name == name),
                )
            ).limit(1)
        )
        match = result.first()
        if match:
            p["entity_id"] = str(match.id)

    return participants

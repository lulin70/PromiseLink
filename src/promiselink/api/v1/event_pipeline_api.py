"""Pipeline-related endpoints for events.

Contains endpoints for retrying failed events, accepting degraded
processing results, and applying user corrections (纠偏) to parsed
event results. Registered as a sub-router of the main events router.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.v1.events import EventCreateRequest, EventCreateResponse, EventResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models import Entity, Event
from promiselink.models.todo import Todo as _Todo
from promiselink.services.event_processor import process_event_background

logger = get_logger("promiselink.api.events")
pipeline_router = APIRouter()

__all__ = ["pipeline_router"]


class BatchEventCreateRequest(BaseModel):
    """Request schema for batch creating events."""

    events: list[EventCreateRequest] = Field(
        ..., min_length=1, max_length=20,
        description="List of events to create (max 20 per batch)"
    )

    model_config = {
        "json_schema_extra": {
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
    }


class BatchEventCreateResponse(BaseModel):
    """Response schema for batch event creation."""

    created: list[EventCreateResponse]
    failed: list[dict[str, Any]]
    total_requested: int
    total_created: int


@pipeline_router.post("/events/batch", response_model=BatchEventCreateResponse, status_code=201)
async def batch_create_events(
    request: BatchEventCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> BatchEventCreateResponse:
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
            ))

            logger.info(
                "batch_event_created",
                event_id=str(event.id),
                batch_index=idx,
                event_type=event.event_type,
            )

        except SQLAlchemyError as e:
            logger.warning("batch_event_create_failed", index=idx, error=str(e))
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


@pipeline_router.post("/events/{event_id}/retry", response_model=EventResponse)
async def retry_event(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
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


@pipeline_router.post("/events/{event_id}/accept-degraded", response_model=EventResponse)
async def accept_degraded_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
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


# ── Event Correction (纠偏) ──


class CorrectedEntityItem(BaseModel):
    """User-corrected entity mapping (人脉纠偏)."""

    extracted_entity_id: str = Field(..., description="AI 提取的实体 ID")
    action: str = Field(..., description="select_existing | create_new | ignore")
    selected_entity_id: str | None = Field(default=None, description="选择已有实体 ID (select_existing)")
    new_name: str | None = Field(default=None, description="新名称 (create_new)")
    new_company: str | None = Field(default=None, description="新公司 (create_new)")
    new_title: str | None = Field(default=None, description="新职位 (create_new)")


class CorrectedTodoItem(BaseModel):
    """User-corrected todo (待办纠偏)."""

    id: str | None = Field(default=None, description="已有待办 ID，None 表示新增")
    title: str
    description: str | None = None
    due_date: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    related_entity_id: str | None = None
    action: str = Field(..., description="edit | delete | add")


class CorrectedPromiseItem(BaseModel):
    """User-corrected promise (承诺纠偏)."""

    id: str = Field(..., description="已有承诺(待办) ID")
    content: str | None = Field(default=None, description="修改后的内容")
    due_date: datetime | None = Field(default=None, description="修改后的截止日期")
    promise_type: str | None = Field(default=None, description="my_promise | their_promise")
    action: str = Field(..., description="confirm | ignore | modify")


class EventCorrectRequest(BaseModel):
    """Request schema for event correction (纠偏提交)."""

    corrected_entities: list[CorrectedEntityItem] = Field(default_factory=list)
    corrected_todos: list[CorrectedTodoItem] = Field(default_factory=list)
    corrected_promises: list[CorrectedPromiseItem] = Field(default_factory=list)


class EventCorrectResponse(BaseModel):
    """Response schema for event correction."""

    event_id: str
    entities_updated: int = 0
    entities_created: int = 0
    entities_ignored: int = 0
    todos_updated: int = 0
    todos_deleted: int = 0
    todos_created: int = 0
    promises_confirmed: int = 0
    promises_ignored: int = 0
    promises_modified: int = 0


@pipeline_router.post("/events/{event_id}/correct", response_model=EventCorrectResponse)
async def correct_event(
    event_id: uuid.UUID,
    request: EventCorrectRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> EventCorrectResponse:
    """Apply user corrections to parsed event results (解析后纠偏).

    三类纠偏:
    - 人脉: select_existing(合并到已有) / create_new(更新提取实体信息) / ignore(忽略)
    - 待办: edit(修改) / delete(删除) / add(新增)
    - 承诺: confirm(确认) / ignore(忽略) / modify(修改)
    """
    new_request_id()

    # Verify event exists and belongs to user
    event_result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id,
        )
    )
    event = event_result.scalar_one_or_none()
    if not event:
        raise NotFoundError("Event not found")

    resp = EventCorrectResponse(event_id=str(event_id))

    # ── 人脉纠偏 ──
    for ent_item in request.corrected_entities:
        # Fetch the extracted entity
        ent_result = await session.execute(
            select(Entity).where(
                Entity.id == ent_item.extracted_entity_id,
                Entity.user_id == user_id,
            )
        )
        extracted = ent_result.scalar_one_or_none()
        if not extracted:
            continue

        if ent_item.action == "select_existing" and ent_item.selected_entity_id:
            # Mark extracted entity as merged, re-point todos to selected entity
            extracted.status = "merged"
            # Update todos that referenced the extracted entity
            todo_update_result = await session.execute(
                select(_Todo).where(_Todo.related_entity_id == ent_item.extracted_entity_id)
            )
            for todo in todo_update_result.scalars().all():
                todo.related_entity_id = ent_item.selected_entity_id  # type: ignore[assignment]
            resp.entities_updated += 1

        elif ent_item.action == "create_new":
            # Update extracted entity with user-provided info
            if ent_item.new_name:
                extracted.name = ent_item.new_name
                extracted.canonical_name = ent_item.new_name
            if ent_item.new_company or ent_item.new_title:
                props = dict(extracted.properties or {})
                basic = dict(props.get("basic") if isinstance(props.get("basic"), dict) else {})  # type: ignore[arg-type]
                if ent_item.new_company:
                    basic["company"] = ent_item.new_company
                if ent_item.new_title:
                    basic["title"] = ent_item.new_title
                props["basic"] = basic
                extracted.properties = props
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(extracted, "properties")
            extracted.status = "confirmed"
            resp.entities_created += 1

        elif ent_item.action == "ignore":
            extracted.status = "deleted"
            resp.entities_ignored += 1

    # ── 待办纠偏 ──
    for todo_item in request.corrected_todos:
        if todo_item.action == "add":
            new_todo = _Todo(
                user_id=user_id,
                todo_type="followup",
                title=todo_item.title,
                description=todo_item.description,
                due_date=todo_item.due_date,
                priority=todo_item.priority,
                related_entity_id=todo_item.related_entity_id,
                source_event_id=str(event_id),
                status="pending",
            )
            session.add(new_todo)
            resp.todos_created += 1

        elif todo_item.action == "delete" and todo_item.id:
            del_result = await session.execute(
                select(_Todo).where(
                    _Todo.id == todo_item.id,
                    _Todo.user_id == user_id,
                )
            )
            todo_to_delete: _Todo | None = del_result.scalar_one_or_none()
            if todo_to_delete:
                await session.delete(todo_to_delete)
                resp.todos_deleted += 1

        elif todo_item.action == "edit" and todo_item.id:
            edit_result = await session.execute(
                select(_Todo).where(
                    _Todo.id == todo_item.id,
                    _Todo.user_id == user_id,
                )
            )
            todo_to_edit: _Todo | None = edit_result.scalar_one_or_none()
            if todo_to_edit:
                todo_to_edit.title = todo_item.title
                if todo_item.description is not None:
                    todo_to_edit.description = todo_item.description
                todo_to_edit.due_date = todo_item.due_date
                todo_to_edit.priority = todo_item.priority
                todo_to_edit.related_entity_id = todo_item.related_entity_id  # type: ignore[assignment]
                resp.todos_updated += 1

    # ── 承诺纠偏 ──
    for prom_item in request.corrected_promises:
        prom_result = await session.execute(
            select(_Todo).where(
                _Todo.id == prom_item.id,
                _Todo.user_id == user_id,
            )
        )
        promise: _Todo | None = prom_result.scalar_one_or_none()
        if not promise:
            continue

        if prom_item.action == "confirm":
            promise.confirmation_status = "confirmed"
            resp.promises_confirmed += 1

        elif prom_item.action == "ignore":
            promise.confirmation_status = "rejected"
            promise.status = "dismissed"
            resp.promises_ignored += 1

        elif prom_item.action == "modify":
            if prom_item.content is not None:
                promise.description = prom_item.content
            if prom_item.due_date is not None:
                promise.due_date = prom_item.due_date
            if prom_item.promise_type is not None:
                promise.action_type = prom_item.promise_type
            promise.confirmation_status = "confirmed"
            resp.promises_modified += 1

    await session.commit()

    logger.info(
        "event_corrected",
        event_id=str(event_id),
        entities_updated=resp.entities_updated,
        todos_created=resp.todos_created,
        promises_confirmed=resp.promises_confirmed,
    )

    return resp

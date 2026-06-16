"""Todo CRUD API endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.todo import Todo
from promiselink.schemas.api_responses import TodoConfirmResponse
from promiselink.services.todo_state_machine import TodoStateMachine

logger = get_logger("promiselink.api.todos")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


# ── Pydantic Models ──


class TodoResponse(BaseModel):
    id: uuid.UUID | str
    user_id: uuid.UUID | str
    todo_type: str
    title: str
    description: str | None = None
    related_entity_id: uuid.UUID | str | None = None
    related_entity_name: str | None = None
    priority: int
    priority_override: str | None = None
    priority_source: str = "ai"
    status: str
    due_date: datetime | None = None
    source_event_id: uuid.UUID | str | None = None
    source_event_title: str | None = None
    source_event_date: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TodoDetailResponse(TodoResponse):
    properties: dict | None = None
    snoozed_until: datetime | None = None
    completed_at: datetime | None = None


class TodoUpdateRequest(BaseModel):
    status: str | None = None
    snoozed_until: datetime | None = None
    feedback: str | None = None
    priority_override: str | None = None


class ConfirmRequest(BaseModel):
    confirmation_status: str  # "confirmed" | "rejected"
    description: str | None = None
    due_date: datetime | None = None


class ConfirmationItem(BaseModel):
    todo_id: str
    todo_type: str
    title: str
    description: str | None = None
    action_type: str | None = None
    due_date: datetime | None = None
    confirmation_status: str
    evidence_quote: str | None = None


# ── Endpoints ──


@router.get("/todos", response_model=PaginatedResponse[TodoResponse])
async def list_todos(
    todo_type: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    search: str | None = Query(None, description="Search in description"),
    sort_by: str = "urgency",
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """List todos with optional filtering, sorting, and pagination.

    Sort modes:
    - urgency (default): priority ASC (1=high first), due_date ASC (soonest first)
    - due_date: due_date ASC (soonest first), NULLs last
    - priority: priority ASC (most urgent first)
    - created: created_at DESC (newest first)
    """
    new_request_id()

    query = select(Todo).where(Todo.user_id == user_id)

    if todo_type:
        query = query.where(Todo.todo_type == todo_type)
    if status:
        query = query.where(Todo.status == status)
    if priority is not None:
        query = query.where(Todo.priority == priority)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Todo.description.ilike(f"%{escaped}%", escape="\\"))

    # Count total
    count_query = select(func.count()).select_from(Todo).where(Todo.user_id == user_id)
    if todo_type:
        count_query = count_query.where(Todo.todo_type == todo_type)
    if status:
        count_query = count_query.where(Todo.status == status)
    if priority is not None:
        count_query = count_query.where(Todo.priority == priority)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        count_query = count_query.where(Todo.description.ilike(f"%{escaped}%", escape="\\"))
    total = (await session.execute(count_query)).scalar() or 0

    # Apply sort
    # For priority-based sorts, user-set priorities sort above AI-calculated at same level
    # priority_source: "user" → 0 (first), "ai" → 1 (second)
    _source_order = case(
        (Todo.priority_source == "user", 0),
        (Todo.priority_source == "ai", 1),
        else_=1,
    )
    if sort_by == "urgency":
        query = query.order_by(
            Todo.priority.asc(), _source_order, Todo.due_date.asc().nulls_last()
        )
    elif sort_by == "due_date":
        query = query.order_by(Todo.due_date.asc().nulls_last())
    elif sort_by == "priority":
        query = query.order_by(Todo.priority.asc(), _source_order)
    else:  # created
        query = query.order_by(Todo.created_at.desc())

    query = query.limit(min(limit, 500)).offset(offset)

    result = await session.execute(query)
    todos = result.scalars().all()

    # Fetch entity names for related_entity_ids
    entity_ids = [t.related_entity_id for t in todos if t.related_entity_id]
    entity_names: dict[str, str] = {}
    if entity_ids:
        from promiselink.models.entity import Entity
        entity_result = await session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_([str(eid) for eid in entity_ids]))
        )
        entity_names = {str(eid): name for eid, name in entity_result.all()}

    # Fetch event titles and dates for source_event_ids
    event_ids = [t.source_event_id for t in todos if t.source_event_id]
    event_titles: dict[str, str] = {}
    event_dates: dict[str, str] = {}
    if event_ids:
        from promiselink.models.event import Event
        event_result = await session.execute(
            select(Event.id, Event.title, Event.created_at).where(Event.id.in_([str(eid) for eid in event_ids]))
        )
        for eid, title, created in event_result.all():
            event_titles[str(eid)] = title
            event_dates[str(eid)] = created.strftime("%m-%d") if created else None

    items = []
    for t in todos:
        item = TodoResponse(
            id=t.id,
            user_id=t.user_id,
            todo_type=t.todo_type,
            title=t.title,
            description=t.description,
            related_entity_id=t.related_entity_id,
            related_entity_name=entity_names.get(str(t.related_entity_id)) if t.related_entity_id else None,
            priority=t.priority,
            priority_override=t.priority_override,
            priority_source=t.priority_source,
            status=t.status,
            due_date=t.due_date,
            source_event_id=t.source_event_id,
            source_event_title=event_titles.get(str(t.source_event_id)) if t.source_event_id else None,
            source_event_date=event_dates.get(str(t.source_event_id)) if t.source_event_id else None,
            created_at=t.created_at,
        )
        items.append(item)

    return PaginatedResponse(items=items, total=total, limit=min(limit, 500), offset=offset)


@router.get("/todos/pending-confirmations", response_model=list[ConfirmationItem])
async def list_pending_confirmations(
    event_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """List promise-type todos pending user confirmation.

    Filters by event_id if provided, otherwise returns all pending confirmations.
    Only returns todos with confirmation_status in (PENDING, AUTO_SET) and
    action_type in (my_promise, their_promise).
    """
    new_request_id()

    conditions = [
        Todo.user_id == user_id,
        Todo.confirmation_status.in_(["pending", "auto_set"]),
        Todo.action_type.in_(["my_promise", "their_promise"]),
    ]
    if event_id:
        conditions.append(Todo.source_event_id == event_id)

    q = (
        select(Todo)
        .where(*conditions)
        .order_by(Todo.created_at.asc())
    )
    results = (await session.execute(q)).scalars().all()

    return [
        ConfirmationItem(
            todo_id=str(t.id),
            todo_type=t.todo_type,
            title=t.title,
            description=t.description,
            action_type=t.action_type,
            due_date=t.due_date,
            confirmation_status=t.confirmation_status or "pending",
            evidence_quote=t.evidence_quote,
        )
        for t in results
    ]


@router.get("/todos/{todo_id}", response_model=TodoDetailResponse)
async def get_todo(
    todo_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Get detailed information about a specific todo."""
    new_request_id()

    result = await session.execute(
        select(Todo).where(
            Todo.id == str(todo_id),
            Todo.user_id == user_id,
        )
    )
    todo = result.scalar_one_or_none()

    if not todo:
        raise NotFoundError("Todo not found")

    return todo


@router.patch("/todos/{todo_id}", response_model=TodoResponse)
async def update_todo(
    todo_id: uuid.UUID,
    request: TodoUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Update a todo (including state transitions via TodoStateMachine)."""
    new_request_id()

    result = await session.execute(
        select(Todo).where(
            Todo.id == str(todo_id),
            Todo.user_id == user_id,
        )
    )
    todo = result.scalar_one_or_none()

    if not todo:
        raise NotFoundError("Todo not found")

    # If status change, use state machine
    if request.status and request.status != todo.status:
        state_machine = TodoStateMachine(session=session)
        todo = await state_machine.transition(
            todo=todo,
            new_status=request.status,
            snoozed_until=request.snoozed_until,
            feedback=request.feedback,
        )
    else:
        # Simple field update
        if request.feedback:
            todo.properties = todo.properties or {}
            todo.properties["feedback"] = request.feedback

    # Handle priority_override (F-59)
    if "priority_override" in request.model_fields_set:
        if request.priority_override is not None:
            todo.priority_override = request.priority_override
            todo.priority_source = "user"
        else:
            todo.priority_override = None
            todo.priority_source = "ai"

    await session.commit()
    await session.refresh(todo)

    logger.info(
        "todo_updated",
        todo_id=str(todo.id),
    )

    return todo


@router.delete("/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Delete a todo."""
    new_request_id()

    result = await session.execute(
        select(Todo).where(Todo.id == str(todo_id), Todo.user_id == user_id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise NotFoundError("Todo not found")

    await session.delete(todo)
    await session.commit()

    logger.info(
        "todo_deleted",
        todo_id=str(todo_id),
    )

    return None


@router.patch("/todos/{todo_id}/confirm", response_model=TodoConfirmResponse)
async def confirm_todo(
    todo_id: uuid.UUID,
    req: ConfirmRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Confirm or reject an AI-extracted promise todo.

    - confirmed: mark as confirmed, apply optional corrections
    - rejected: mark as rejected (excluded from stats/scoring)
    """
    new_request_id()

    if req.confirmation_status not in ("confirmed", "rejected"):
        from promiselink.core.exceptions import ValidationError
        raise ValidationError("confirmation_status must be 'confirmed' or 'rejected'")

    result = await session.execute(
        select(Todo).where(
            Todo.id == str(todo_id),
            Todo.user_id == user_id,
        )
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise NotFoundError("Todo not found")

    todo.confirmation_status = req.confirmation_status

    if req.confirmation_status == "confirmed":
        # Apply optional corrections
        if req.description:
            todo.description = req.description
        if req.due_date:
            todo.due_date = req.due_date
        # Update status to pending-active
        if todo.status == "pending":
            pass  # keep as-is, already actionable
    elif req.confirmation_status == "rejected":
        # Rejected todos are dismissed
        todo.status = "dismissed"

    await session.commit()

    logger.info(
        "todo_confirmed",
        todo_id=str(todo_id),
        status=req.confirmation_status,
        user_id=user_id,
    )

    return TodoConfirmResponse(
        todo_id=todo_id,
        confirmation_status=req.confirmation_status,
        status=todo.status,
    )

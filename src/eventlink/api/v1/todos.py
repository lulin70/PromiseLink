"""Todo CRUD API endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.api.v1.schemas import PaginatedResponse
from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models.todo import Todo
from eventlink.services.todo_state_machine import TodoStateMachine

logger = get_logger("eventlink.api.todos")
router = APIRouter()


# ── Pydantic Models ──


class TodoResponse(BaseModel):
    id: uuid.UUID | str
    user_id: uuid.UUID | str
    todo_type: str
    title: str
    description: str | None = None
    related_entity_id: uuid.UUID | str | None = None
    priority: int
    status: str
    due_date: datetime | None = None
    source_event_id: uuid.UUID | str | None = None
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


# ── Endpoints ──


@router.get("/todos", response_model=PaginatedResponse[TodoResponse])
async def list_todos(
    todo_type: str | None = None,
    status: str | None = None,
    priority: int | None = None,
    sort_by: str = "urgency",
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
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

    # Count total
    count_query = select(func.count()).select_from(Todo).where(Todo.user_id == user_id)
    if todo_type:
        count_query = count_query.where(Todo.todo_type == todo_type)
    if status:
        count_query = count_query.where(Todo.status == status)
    if priority is not None:
        count_query = count_query.where(Todo.priority == priority)
    total = (await session.execute(count_query)).scalar() or 0

    # Apply sort
    if sort_by == "urgency":
        query = query.order_by(Todo.priority.asc(), Todo.due_date.asc().nulls_last())
    elif sort_by == "due_date":
        query = query.order_by(Todo.due_date.asc().nulls_last())
    elif sort_by == "priority":
        query = query.order_by(Todo.priority.asc())
    else:  # created
        query = query.order_by(Todo.created_at.desc())

    query = query.limit(min(limit, 500)).offset(offset)

    result = await session.execute(query)
    todos = result.scalars().all()

    return PaginatedResponse(items=todos, total=total, limit=min(limit, 500), offset=offset)


@router.get("/todos/{todo_id}", response_model=TodoDetailResponse)
async def get_todo(
    todo_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
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
        raise HTTPException(status_code=404, detail="Todo not found")

    return todo


@router.patch("/todos/{todo_id}", response_model=TodoResponse)
async def update_todo(
    todo_id: uuid.UUID,
    request: TodoUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
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
        raise HTTPException(status_code=404, detail="Todo not found")

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
    user_id: str = Depends(get_optional_user_id),
):
    """Delete a todo."""
    new_request_id()

    result = await session.execute(
        select(Todo).where(Todo.id == str(todo_id), Todo.user_id == user_id)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    await session.delete(todo)
    await session.commit()

    logger.info(
        "todo_deleted",
        todo_id=str(todo_id),
    )

    return None

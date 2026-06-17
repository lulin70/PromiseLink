"""Dashboard Range View endpoint — Phase 1.2: 多日范围视图."""

from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.core.natural_date import parse_natural_date
from promiselink.database import get_async_session
from promiselink.models.event import Event
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.dashboard.range_view")
router = APIRouter(tags=["Dashboard"])


# ── Pydantic Models ──


class RangeViewEventItem(BaseModel):
    id: str
    event_type: str
    title: str
    timestamp: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class RangeViewTodoItem(BaseModel):
    id: str
    todo_type: str
    title: str
    status: str
    due_date: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RangeViewResponse(BaseModel):
    range_start: str
    range_end: str
    label: str
    total_events: int = 0
    total_todos: int = 0
    events: list[RangeViewEventItem] = []
    todos: list[RangeViewTodoItem] = []


# ── Endpoint ──


@router.get("/range-view", response_model=RangeViewResponse, tags=["Dashboard"])
async def get_range_view(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    range_text: str | None = Query(None, description="如 '本周'/'下周'"),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> RangeViewResponse:
    """Get multi-day range view (Phase 1.2).

    Supports explicit start/end dates or natural language week expressions.
    Returns aggregated data across the specified date range.
    """
    new_request_id()

    if range_text:
        parsed = parse_natural_date(range_text)
        range_start = parsed.start_date
        range_end = parsed.end_date
    elif start_date and end_date:
        range_start = parse_natural_date(start_date).start_date
        range_end = parse_natural_date(end_date).start_date
    else:
        raise ValidationError("必须提供 range_text 或 start_date + end_date")

    logger.info(
        "range_view_request",
        user_id=user_id,
        range_start=str(range_start),
        range_end=str(range_end),
    )

    # Use UTC+8 offset so "local date 00:00" maps to correct UTC range
    _CST = timezone(timedelta(hours=8))
    range_start_local = datetime(range_start.year, range_start.month, range_start.day, 0, 0, 0, tzinfo=_CST)
    range_end_local = datetime(range_end.year, range_end.month, range_end.day, 23, 59, 59, tzinfo=_CST)
    range_start_dt = range_start_local.astimezone(UTC).replace(tzinfo=None)
    range_end_dt = range_end_local.astimezone(UTC).replace(tzinfo=None)

    # Fetch events in range
    event_result = await session.execute(
        select(Event)
        .where(Event.user_id == user_id)
        .where(Event.timestamp >= range_start_dt)
        .where(Event.timestamp <= range_end_dt)
        .order_by(Event.timestamp.asc())
    )
    events_in_range = event_result.scalars().all()

    # Fetch todos due in range
    todo_result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.due_date.isnot(None))
        .where(Todo.due_date >= range_start_dt)
        .where(Todo.due_date <= range_end_dt)
        .order_by(Todo.due_date.asc())
    )
    todos_in_range = todo_result.scalars().all()

    return RangeViewResponse(
        range_start=range_start.isoformat(),
        range_end=range_end.isoformat(),
        label=getattr(parsed, "label", f"{range_start} ~ {range_end}") if range_text else f"{range_start} ~ {range_end}",
        total_events=len(events_in_range),
        total_todos=len(todos_in_range),
        events=[
            RangeViewEventItem(
                id=str(e.id),
                event_type=e.event_type,
                title=e.title,
                timestamp=(e.timestamp + timedelta(hours=8)).isoformat() if e.timestamp else None,
                status=e.status,
            )
            for e in events_in_range
        ],
        todos=[
            RangeViewTodoItem(
                id=str(t.id),
                todo_type=t.todo_type,
                title=t.title,
                status=t.status,
                due_date=t.due_date.isoformat() if t.due_date else None,
            )
            for t in todos_in_range
        ],
    )

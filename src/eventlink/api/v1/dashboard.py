"""Dashboard API - Day view and range view endpoints for EventLink.

F-49: 日视图 Dashboard API — 聚合展示指定日期的事件与待办.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.auth import get_current_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.core.natural_date import parse_natural_date, NaturalDateResult
from eventlink.database import get_async_session
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.models.entity import Entity

logger = get_logger("eventlink.api.dashboard")
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


# ── Pydantic Models ──


class DayViewEventItem(BaseModel):
    id: uuid.UUID | str
    event_type: str
    title: str
    time: str | None = None  # HH:MM format from timestamp
    status: str
    input_scope: str | None = None
    entities: list[str] = []  # Person names extracted from related entities
    todo_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DayViewTodoItem(BaseModel):
    id: uuid.UUID | str
    title: str
    todo_type: str
    action_type: str | None = None
    status: str
    due_date: date | None = None
    related_person: str | None = None
    is_overdue: bool = False

    model_config = ConfigDict(from_attributes=True)


class DayViewSummary(BaseModel):
    total_events: int = 0
    total_todos: int = 0
    overdue_todos: int = 0
    pending_promises: int = 0
    upcoming_meetings: int = 0


class AdjacentDates(BaseModel):
    previous_day: str  # ISO format
    next_day: str  # ISO format


class DayViewResponse(BaseModel):
    date: str  # ISO format YYYY-MM-DD
    date_label: str  # e.g., "今天 (周四)"
    events: list[DayViewEventItem] = []
    todos: list[DayViewTodoItem] = []
    summary: DayViewSummary = Field(default_factory=DayViewSummary)
    adjacent_dates: AdjacentDates


# ── Endpoints ──


@router.get("/day-view", response_model=DayViewResponse, tags=["Dashboard"])
async def get_day_view(
    date_param: str | None = Query(
        None, alias="date", description="自然语言日期: 今天/明天/2026-06-04"
    ),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> DayViewResponse:
    """Get day view dashboard for a specific date.

    Shows all events and actionable todos for the given date.
    Supports natural language dates (Chinese + English + ISO).
    """
    new_request_id()

    # Parse natural date expression
    parsed = parse_natural_date(date_param)
    target_date = parsed.start_date

    logger.info(
        "day_view_request",
        user_id=user_id,
        target_date=str(target_date),
        original_input=parsed.original,
    )

    # ── Fetch events for target date ──
    day_start = datetime(
        target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=timezone.utc
    )
    day_end = day_start + timedelta(days=1)

    event_result = await session.execute(
        select(Event)
        .where(Event.user_id == user_id)
        .where(Event.timestamp >= day_start)
        .where(Event.timestamp < day_end)
        .order_by(Event.timestamp.asc())
    )
    events = event_result.scalars().all()

    # Batch fetch entity names and todo counts (avoid N+1 queries)
    event_ids = [str(evt.id) for evt in events]
    entity_map: dict[str, list[str]] = {}
    todo_count_map: dict[str, int] = {}

    if event_ids:
        # Batch: entity names per event
        entity_result = await session.execute(
            select(Entity.source_event_id, Entity.name)
            .where(Entity.source_event_id.in_(event_ids), Entity.entity_type == "person")
        )
        for source_event_id, name in entity_result.fetchall():
            entity_map.setdefault(source_event_id, []).append(name)

        # Batch: todo counts per event
        todo_count_result = await session.execute(
            select(Todo.source_event_id, func.count())
            .where(Todo.source_event_id.in_(event_ids))
            .group_by(Todo.source_event_id)
        )
        todo_count_map = dict(todo_count_result.fetchall())

    # Build event items with entity names and todo counts
    event_items = []
    for evt in events:
        entity_names = entity_map.get(str(evt.id), [])
        todo_count = todo_count_map.get(str(evt.id), 0)

        time_str = evt.timestamp.strftime("%H:%M") if evt.timestamp else None
        event_items.append(
            DayViewEventItem(
                id=evt.id,
                event_type=evt.event_type,
                title=evt.title,
                time=time_str,
                status=evt.status,
                input_scope=evt.input_scope,
                entities=entity_names,
                todo_count=todo_count,
            )
        )

    # ── Fetch todos due on target date ──
    # Todos with due_date falling on target_date (compare as dates, not datetimes)
    todo_result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.due_date.isnot(None))
        .where(func.date(Todo.due_date) == target_date)
        .order_by(Todo.due_date.asc(), Todo.priority.asc())
    )
    todos = todo_result.scalars().all()

    # Batch fetch related entity names (avoid N+1 queries)
    related_entity_ids = [str(td.related_entity_id) for td in todos if td.related_entity_id]
    entity_name_map: dict[str, str] = {}
    if related_entity_ids:
        name_result = await session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(related_entity_ids))
        )
        entity_name_map = {str(row[0]): row[1] for row in name_result.fetchall()}

    today_for_overdue = date.today()
    todo_items = []
    for td in todos:
        # Resolve related person name from entity
        related_person_name = entity_name_map.get(str(td.related_entity_id)) if td.related_entity_id else None

        # Determine if overdue
        is_overdue = False
        if td.due_date and td.status not in ("done", "dismissed"):
            due_date_only = td.due_date.date() if isinstance(td.due_date, datetime) else td.due_date
            is_overdue = due_date_only < today_for_overdue

        due_date_only = (
            td.due_date.date() if isinstance(td.due_date, datetime) else td.due_date
        )

        todo_items.append(
            DayViewTodoItem(
                id=td.id,
                title=td.title,
                todo_type=td.todo_type,
                action_type=td.action_type,
                status=td.status,
                due_date=due_date_only,
                related_person=related_person_name,
                is_overdue=is_overdue,
            )
        )

    # ── Build summary ──
    total_events = len(event_items)
    total_todos = len(todo_items)
    overdue_todos = sum(1 for t in todo_items if t.is_overdue)
    pending_promises = sum(
        1
        for t in todo_items
        if t.todo_type == "promise" and t.status == "pending"
    )
    upcoming_meetings = sum(1 for e in event_items if e.event_type == "meeting")

    summary = DayViewSummary(
        total_events=total_events,
        total_todos=total_todos,
        overdue_todos=overdue_todos,
        pending_promises=pending_promises,
        upcoming_meetings=upcoming_meetings,
    )

    # ── Adjacent dates ──
    prev_day = target_date - timedelta(days=1)
    next_day = target_date + timedelta(days=1)

    return DayViewResponse(
        date=target_date.isoformat(),
        date_label=parsed.label,
        events=event_items,
        todos=todo_items,
        summary=summary,
        adjacent_dates=AdjacentDates(previous_day=prev_day.isoformat(), next_day=next_day.isoformat()),
    )


@router.get("/range-view", response_model=dict, tags=["Dashboard"])
async def get_range_view(
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    range_text: str | None = Query(None, description="如 '本周'/'下周'"),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> dict:
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
        raise HTTPException(status_code=400, detail="必须提供 range_text 或 start_date + end_date")

    logger.info(
        "range_view_request",
        user_id=user_id,
        range_start=str(range_start),
        range_end=str(range_end),
    )

    range_start_dt = datetime(
        range_start.year, range_start.month, range_start.day, 0, 0, 0, tzinfo=timezone.utc
    )
    range_end_dt = datetime(
        range_end.year, range_end.month, range_end.day, 23, 59, 59, tzinfo=timezone.utc
    )

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

    return {
        "range_start": range_start.isoformat(),
        "range_end": range_end.isoformat(),
        "label": getattr(parsed, "label", f"{range_start} ~ {range_end}") if range_text else f"{range_start} ~ {range_end}",
        "total_events": len(events_in_range),
        "total_todos": len(todos_in_range),
        "events": [
            {
                "id": str(e.id),
                "event_type": e.event_type,
                "title": e.title,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "status": e.status,
            }
            for e in events_in_range
        ],
        "todos": [
            {
                "id": str(t.id),
                "todo_type": t.todo_type,
                "title": t.title,
                "status": t.status,
                "due_date": t.due_date.isoformat() if t.due_date else None,
            }
            for t in todos_in_range
        ],
    }


class MorningBriefResponse(BaseModel):
    """Morning brief summary for the day."""
    date: str
    greeting: str
    pending_promises: int
    pending_cares: int
    overdue_todos: int
    today_events: int
    today_todos: int
    key_persons: list[str] = []
    summary_text: str


@router.get("/morning-brief", response_model=MorningBriefResponse, tags=["Dashboard"])
async def get_morning_brief(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> MorningBriefResponse:
    """Get morning brief — daily summary for proactive relationship management."""
    new_request_id()
    today = date.today()

    # Count pending promises
    promise_result = await session.execute(
        select(func.count()).select_from(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.todo_type == "promise")
        .where(Todo.status == "pending")
    )
    pending_promises = promise_result.scalar() or 0

    # Count pending cares
    care_result = await session.execute(
        select(func.count()).select_from(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.todo_type == "care")
        .where(Todo.status == "pending")
    )
    pending_cares = care_result.scalar() or 0

    # Count overdue todos
    overdue_result = await session.execute(
        select(func.count()).select_from(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.status.notin_(["done", "dismissed"]))
        .where(Todo.due_date.isnot(None))
        .where(func.date(Todo.due_date) < today)
    )
    overdue_todos = overdue_result.scalar() or 0

    # Count today's events
    day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    event_result = await session.execute(
        select(func.count()).select_from(Event)
        .where(Event.user_id == user_id)
        .where(Event.timestamp >= day_start)
        .where(Event.timestamp < day_end)
    )
    today_events = event_result.scalar() or 0

    # Count today's todos
    todo_result = await session.execute(
        select(func.count()).select_from(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.due_date.isnot(None))
        .where(func.date(Todo.due_date) == today)
    )
    today_todos = todo_result.scalar() or 0

    # Key persons from pending todos
    person_result = await session.execute(
        select(Entity.name)
        .join(Todo, Todo.related_entity_id == Entity.id)
        .where(Todo.user_id == user_id)
        .where(Todo.status == "pending")
        .distinct()
        .limit(5)
    )
    key_persons = [row[0] for row in person_result.fetchall()]

    # Build greeting and summary
    hour = datetime.now(timezone.utc).hour
    if hour < 12:
        greeting = "早上好"
    elif hour < 18:
        greeting = "下午好"
    else:
        greeting = "晚上好"

    summary_parts = []
    if pending_promises > 0:
        summary_parts.append(f"{pending_promises}个待回应承诺")
    if pending_cares > 0:
        summary_parts.append(f"{pending_cares}个关注跟进")
    if overdue_todos > 0:
        summary_parts.append(f"{overdue_todos}个已逾期")
    if today_events > 0:
        summary_parts.append(f"今天{today_events}个互动")
    if today_todos > 0:
        summary_parts.append(f"{today_todos}个今日待办")

    summary_text = "，".join(summary_parts) if summary_parts else "今天暂无待处理事项"

    return MorningBriefResponse(
        date=today.isoformat(),
        greeting=greeting,
        pending_promises=pending_promises,
        pending_cares=pending_cares,
        overdue_todos=overdue_todos,
        today_events=today_events,
        today_todos=today_todos,
        key_persons=key_persons,
        summary_text=summary_text,
    )

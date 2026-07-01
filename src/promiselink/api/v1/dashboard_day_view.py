"""Dashboard Day View endpoint — F-49: 日视图 Dashboard API."""

from datetime import UTC, date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.v1.schemas import UUIDStr
from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.core.natural_date import parse_natural_date
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.scheduled_event import ScheduledEvent
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.dashboard.day_view")
router = APIRouter(tags=["Dashboard"])


# ── Pydantic Models ──


class DayViewEventItem(BaseModel):
    id: UUIDStr
    event_type: str
    title: str
    time: str | None = None  # HH:MM format from timestamp
    status: str
    input_scope: str | None = None
    entities: list[str] = []  # Person names extracted from related entities
    todo_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class DayViewTodoItem(BaseModel):
    id: UUIDStr
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
    pending_schedules: int = 0
    overdue_schedules: int = 0


class DayViewScheduledItem(BaseModel):
    id: UUIDStr
    topic: str
    scheduled_at: datetime
    event_type: str
    status: str
    participants: list[dict] | None = None
    location: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AdjacentDates(BaseModel):
    previous_day: str  # ISO format
    next_day: str  # ISO format


class DayViewResponse(BaseModel):
    date: str  # ISO format YYYY-MM-DD
    date_label: str  # e.g., "今天 (周四)"
    events: list[DayViewEventItem] = []
    todos: list[DayViewTodoItem] = []
    scheduled_events: list[DayViewScheduledItem] = []
    summary: DayViewSummary = Field(default_factory=DayViewSummary)
    adjacent_dates: AdjacentDates


# ── Endpoint ──


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
    # Use UTC+8 offset so "local date 00:00" maps to correct UTC range
    _CST = timezone(timedelta(hours=8))
    day_start_local = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=_CST)
    day_end_local = day_start_local + timedelta(days=1)
    # Convert to UTC for database comparison (timestamps stored as naive UTC in SQLite)
    day_start = day_start_local.astimezone(UTC).replace(tzinfo=None)
    day_end = day_end_local.astimezone(UTC).replace(tzinfo=None)

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
        todo_count_map = dict(todo_count_result.fetchall())  # type: ignore[arg-type]

    # Build event items with entity names and todo counts
    event_items = []
    for evt in events:
        entity_names = entity_map.get(str(evt.id), [])
        todo_count = todo_count_map.get(str(evt.id), 0)

        # Convert UTC timestamp to local time (Asia/Shanghai, UTC+8)
        if evt.timestamp:
            local_ts = evt.timestamp + timedelta(hours=8)
            time_str = local_ts.strftime("%H:%M")
        else:
            time_str = None
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
    # Exclude fulfilled/broken promises (they're tracked in promises page)
    todo_result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.due_date.isnot(None))
        .where(func.date(Todo.due_date) == target_date)
        .where(
            or_(
                Todo.todo_type != "promise",
                Todo.fulfillment_status.notin_(["fulfilled", "broken"]),
            )
        )
        .order_by(Todo.due_date.asc(), Todo.priority.asc())
    )
    due_todos = todo_result.scalars().all()

    # Also fetch pending actionable todos (no due-date or overdue) for completeness
    # These are items the user needs to act on but may not have a specific deadline
    actionable_result = await session.execute(
        select(Todo)
        .where(Todo.user_id == user_id)
        .where(Todo.status.notin_(["done", "dismissed"]))
        .where(
            or_(
                Todo.todo_type != "promise",
                Todo.fulfillment_status.notin_(["fulfilled", "broken"]),
            )
        )
        .where(
            or_(
                Todo.due_date.is_(None),
                func.date(Todo.due_date) < target_date,
            )
        )
        .order_by(Todo.priority.asc(), Todo.created_at.asc())
        .limit(20)
    )
    actionable_todos = actionable_result.scalars().all()

    # Merge: due_todos first, then actionable (dedup by id)
    seen_ids = {str(td.id) for td in due_todos}
    all_todos = list(due_todos)
    for td in actionable_todos:
        if str(td.id) not in seen_ids:
            all_todos.append(td)
            seen_ids.add(str(td.id))

    # Batch fetch related entity names (avoid N+1 queries)
    related_entity_ids = [str(td.related_entity_id) for td in all_todos if td.related_entity_id]
    entity_name_map: dict[str, str] = {}
    if related_entity_ids:
        name_result = await session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_(related_entity_ids))
        )
        entity_name_map = {str(row[0]): row[1] for row in name_result.fetchall()}

    today_for_overdue = date.today()
    todo_items = []
    for td in all_todos:
        # Resolve related person name from entity
        related_person_name = entity_name_map.get(str(td.related_entity_id)) if td.related_entity_id else None

        # Determine if overdue
        is_overdue = False
        if td.due_date and td.status not in ("done", "dismissed"):
            due_date_only = td.due_date.date() if isinstance(td.due_date, datetime) else td.due_date
            is_overdue = due_date_only < today_for_overdue

        due_date_only = (
            td.due_date.date() if isinstance(td.due_date, datetime) else td.due_date  # type: ignore[assignment]
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

    # ── Fetch scheduled events for target date ──
    se_result = await session.execute(
        select(ScheduledEvent)
        .where(ScheduledEvent.user_id == user_id)
        .where(ScheduledEvent.status.in_(["pending", "overdue"]))
        .where(ScheduledEvent.scheduled_at >= day_start)
        .where(ScheduledEvent.scheduled_at < day_end)
        .order_by(ScheduledEvent.scheduled_at.asc())
    )
    scheduled_events = se_result.scalars().all()

    # Also fetch overdue scheduled events (regardless of date)
    overdue_se_result = await session.execute(
        select(ScheduledEvent)
        .where(ScheduledEvent.user_id == user_id)
        .where(ScheduledEvent.status == "overdue")
        .order_by(ScheduledEvent.scheduled_at.asc())
        .limit(10)
    )
    overdue_scheduled = overdue_se_result.scalars().all()

    # Merge: today's scheduled + overdue (dedup by id)
    se_seen = {str(se.id) for se in scheduled_events}
    all_scheduled = list(scheduled_events)
    for se in overdue_scheduled:
        if str(se.id) not in se_seen:
            all_scheduled.append(se)
            se_seen.add(str(se.id))

    scheduled_items = [
        DayViewScheduledItem(
            id=se.id,
            topic=se.topic,
            scheduled_at=se.scheduled_at,
            event_type=se.event_type,
            status=se.status,
            participants=se.participants,
            location=se.location,
        )
        for se in all_scheduled
    ]

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
    pending_schedules = sum(1 for se in all_scheduled if se.status == "pending")
    overdue_schedules = sum(1 for se in all_scheduled if se.status == "overdue")

    summary = DayViewSummary(
        total_events=total_events,
        total_todos=total_todos,
        overdue_todos=overdue_todos,
        pending_promises=pending_promises,
        upcoming_meetings=upcoming_meetings,
        pending_schedules=pending_schedules,
        overdue_schedules=overdue_schedules,
    )

    # ── Adjacent dates ──
    prev_day = target_date - timedelta(days=1)
    next_day = target_date + timedelta(days=1)

    return DayViewResponse(
        date=target_date.isoformat(),
        date_label=parsed.label,
        events=event_items,
        todos=todo_items,
        scheduled_events=scheduled_items,
        summary=summary,
        adjacent_dates=AdjacentDates(previous_day=prev_day.isoformat(), next_day=next_day.isoformat()),
    )

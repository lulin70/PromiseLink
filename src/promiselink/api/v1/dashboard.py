"""Dashboard API - Day view and range view endpoints for PromiseLink.

F-49: 日视图 Dashboard API — 聚合展示指定日期的事件与待办.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.core.natural_date import parse_natural_date, NaturalDateResult
from promiselink.database import get_async_session
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.models.entity import Entity
from promiselink.models.scheduled_event import ScheduledEvent

logger = get_logger("promiselink.api.dashboard")
router = APIRouter(prefix="/dashboard", tags=["Dashboard"], dependencies=[Depends(rate_limit_dependency)])


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
    pending_schedules: int = 0
    overdue_schedules: int = 0


class DayViewScheduledItem(BaseModel):
    id: uuid.UUID | str
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


class RangeViewEventItem(BaseModel):
    id: uuid.UUID | str
    event_type: str
    title: str
    timestamp: str | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


class RangeViewTodoItem(BaseModel):
    id: uuid.UUID | str
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
    # Use UTC+8 offset so "local date 00:00" maps to correct UTC range
    _CST = timezone(timedelta(hours=8))
    day_start_local = datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0, tzinfo=_CST)
    day_end_local = day_start_local + timedelta(days=1)
    # Convert to UTC for database comparison (timestamps stored as naive UTC in SQLite)
    day_start = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    day_end = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)

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
    range_start_dt = range_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    range_end_dt = range_end_local.astimezone(timezone.utc).replace(tzinfo=None)

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
                id=e.id,
                event_type=e.event_type,
                title=e.title,
                timestamp=(e.timestamp + timedelta(hours=8)).isoformat() if e.timestamp else None,
                status=e.status,
            )
            for e in events_in_range
        ],
        todos=[
            RangeViewTodoItem(
                id=t.id,
                todo_type=t.todo_type,
                title=t.title,
                status=t.status,
                due_date=t.due_date.isoformat() if t.due_date else None,
            )
            for t in todos_in_range
        ],
    )


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
        .where(
            or_(
                Todo.todo_type != "promise",
                Todo.fulfillment_status.notin_(["fulfilled", "broken"]),
            )
        )
        .where(Todo.due_date.isnot(None))
        .where(func.date(Todo.due_date) < today)
    )
    overdue_todos = overdue_result.scalar() or 0

    # Count today's events (use UTC+8 to match local date)
    _CST = timezone(timedelta(hours=8))
    day_start_local = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=_CST)
    day_end_local = day_start_local + timedelta(days=1)
    day_start = day_start_local.astimezone(timezone.utc).replace(tzinfo=None)
    day_end = day_end_local.astimezone(timezone.utc).replace(tzinfo=None)
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


# ── F-E4: Supply-Demand Matching ──


class SupplyDemandMatch(BaseModel):
    demander_name: str
    demander_company: str | None = None
    demand_text: str
    supplier_name: str | None = None
    supplier_company: str | None = None
    supply_text: str | None = None
    match_score: float
    match_reason: str


class SupplyDemandResponse(BaseModel):
    matches: list[SupplyDemandMatch]
    total: int


@router.get("/supply-demand", response_model=SupplyDemandResponse)
async def get_supply_demand(
    limit: int = Query(5, ge=1, le=20),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Find supply-demand matching opportunities across contacts.

    Matches entities that have demands against those that have supplies.
    Uses entity.properties resource field for structured matching.
    """
    new_request_id()

    # Get all person entities with resource info in properties
    result = await session.execute(
        select(Entity).where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
        )
        .limit(limit)
        .offset(offset)
    )
    entities = list(result.scalars().all())

    # Extract demand/supply from properties
    demanders: list[tuple[Entity, str]] = []  # (entity, demand_text)
    suppliers: list[tuple[Entity, str]] = []  # (entity, supply_text)

    for e in entities:
        props = e.properties or {}
        res = props.get("resource", {})
        if isinstance(res, dict):
            demand = res.get("demand")
            if demand and isinstance(demand, str):
                demanders.append((e, demand))
            supply = res.get("capabilities") or res.get("supply")
            if supply:
                if isinstance(supply, list):
                    supply_text = "、".join(supply[:3])
                elif isinstance(supply, str):
                    supply_text = supply
                else:
                    continue
                suppliers.append((e, supply_text))

    # Simple keyword-based matching
    matches: list[SupplyDemandMatch] = []
    for dem_entity, dem_text in demanders:
        best_match = None
        best_score = 0.0

        for sup_entity, sup_text in suppliers:
            if sup_entity.id == dem_entity.id:
                continue  # Don't match self

            # Keyword overlap scoring
            dem_words = set(dem_text.replace("，", ",").replace("、", ",").split(","))
            sup_words = set(sup_text.replace("，", ",").replace("、", ",").split(","))

            overlap = dem_words & sup_words
            if overlap:
                score = len(overlap) / max(len(dem_words), len(sup_words))
                if score > best_score:
                    best_score = score
                    best_match = (sup_entity, sup_text)

        if best_match and best_score >= 0.2:
            sup_entity, sup_text = best_match
            dem_company = _extract_company_from_props(dem_entity.properties)
            sup_company = _extract_company_from_props(sup_entity.properties)

            matches.append(SupplyDemandMatch(
                demander_name=dem_entity.name,
                demander_company=dem_company,
                demand_text=dem_text,
                supplier_name=sup_entity.name,
                supplier_company=sup_company,
                supply_text=sup_text,
                match_score=round(best_score, 2),
                match_reason=f"关键词匹配: {', '.join(dem_words & set(sup_text.split('、')))}" if best_match else "资源互补",
            ))

    # Sort by score descending
    matches.sort(key=lambda m: m.match_score, reverse=True)

    return SupplyDemandResponse(
        matches=matches[:limit],
        total=len(matches),
    )


def _extract_company_from_props(properties: dict | None) -> str | None:
    """Extract company name from entity properties."""
    if not properties:
        return None
    basic = properties.get("basic", {})
    if isinstance(basic, dict):
        return basic.get("company")
    return None


# ── F-G1: Relationship Health Diagnostic ──


class HealthItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    stage: str
    stage_label: str
    stage_color: str
    health_score: float
    health_level: str  # "healthy" / "attention" / "at_risk"
    interaction_count: int
    last_interaction: str | None = None
    days_since_last: int | None = None
    pending_todos: int = 0
    pending_promises: int = 0
    suggestion: str = ""


class RelationshipHealthResponse(BaseModel):
    total_entities: int = 0
    healthy_count: int = 0
    attention_count: int = 0
    at_risk_count: int = 0
    items: list[HealthItem] = []
    summary_text: str = ""


@router.get("/relationship-health", response_model=RelationshipHealthResponse)
async def get_relationship_health(
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> RelationshipHealthResponse:
    """F-G1: Scan all person entities and compute relationship health scores."""
    from promiselink.services.health_diagnostic import scan_all_entity_health

    rid = new_request_id()
    logger.info("rid=%s get_relationship_health user_id=%s limit=%d", rid, user_id, limit)

    items_data = await scan_all_entity_health(session, user_id, limit)

    healthy = sum(1 for i in items_data if i["health_level"] == "healthy")
    attention = sum(1 for i in items_data if i["health_level"] == "attention")
    at_risk = sum(1 for i in items_data if i["health_level"] == "at_risk")

    # Generate summary text
    total = len(items_data)
    if total == 0:
        summary = "暂无联系人数据，记录第一次互动后即可查看关系健康度。"
    elif at_risk > 0:
        summary = f"共{total}位联系人，{at_risk}位需要立即关注，{attention}位建议保持互动。"
    elif attention > 0:
        summary = f"共{total}位联系人，整体健康。{attention}位可适当增加互动频率。"
    else:
        summary = f"共{total}位联系人，关系状态良好，继续保持！"

    items = [HealthItem(**item) for item in items_data]

    return RelationshipHealthResponse(
        total_entities=total,
        healthy_count=healthy,
        attention_count=attention,
        at_risk_count=at_risk,
        items=items,
        summary_text=summary,
    )


# ── F-G3: Care Reminders ──


PERSONAL_KEYWORDS = {
    "family_milestone": [
        "孩子", "子女", "儿子", "女儿", "高考", "中考", "留学",
        "毕业", "入学", "升学", "开学", "录取", "考研", "考博",
        "结婚", "生子", "宝宝", "夫人", "太太", "先生",
        "满月", "百日", "周岁", "生日", "寿辰",
    ],
    "personal_health": [
        "手术", "住院", "体检", "康复", "生病", "身体", "健康",
    ],
    "hobby_interest": [
        "跑步", "马拉松", "健身", "高尔夫", "网球", "摄影",
        "茶", "咖啡", "酒", "旅行", "旅游", "书法", "画画",
    ],
    "project_milestone": [
        "上线", "发布", "融资", "A轮", "B轮", "搬", "迁",
        "扩张", "招人", "扩团队", "新产品",
    ],
    "life_change": [
        "搬家", "换房", "换城市", "回国", "离职", "跳槽", "创业",
    ],
}

CARE_TYPE_ICONS = {
    "family_milestone": "\U0001f3e0",   # house
    "personal_health": "\U0001febf",     # medical
    "hobby_interest": "\U0001f3c3",      # runner
    "project_milestone": "\U0001f3af",   # flag
    "life_change": "\U0001f4cb",         # clipboard
}

ACTION_TEMPLATES = {
    "family_milestone": "可以问一句{detail}怎么样了",
    "personal_health": "合适的时候问候一下{detail}的情况",
    "hobby_interest": "聊聊{detail}的近况，这是个很好的破冰话题",
    "project_milestone": "恭喜{detail}，可以问进展如何",
    "life_change": "{detail}后适应得怎么样",
    "default": "记得{detail}，可以在下次交流时提起",
}


class CareReminderItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    concern_category: str = ""
    concern_detail: str = ""
    care_type: str = ""           # "personal" / "business" / "mixed"
    relevance_score: float = 0.0
    source_event_title: str | None = None
    days_since_mentioned: int = 0
    suggested_action: str = ""
    care_icon: str = ""


class CareRemindersResponse(BaseModel):
    total: int = 0
    personal_items: list[CareReminderItem] = []
    business_items: list[CareReminderItem] = []
    summary_text: str = ""


def _classify_care_type(detail_text: str) -> tuple[str, float]:
    """Classify a concern detail into a care type using keyword matching.

    Returns (care_type, relevance_score).
    """
    if not detail_text:
        return ("business", 0.0)

    best_type = "business"
    best_score = 0.0

    for ctype, keywords in PERSONAL_KEYWORDS.items():
        hit_count = sum(1 for kw in keywords if kw in detail_text)
        if hit_count > 0:
            score = min(1.0, hit_count * 0.35)
            if score > best_score:
                best_score = score
                best_type = ctype

    return (best_type, best_score)


def _generate_care_action(care_type: str, detail: str) -> str:
    """Generate a suggested action for a care reminder."""
    template = ACTION_TEMPLATES.get(care_type, ACTION_TEMPLATES["default"])
    try:
        return template.format(detail=detail[:50])
    except (KeyError, IndexError):
        return f"记得{detail[:30]}，可以适时关心"


@router.get("/care-reminders", response_model=CareRemindersResponse)
async def get_care_reminders(
    limit: int = Query(10, ge=1, le=30),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> CareRemindersResponse:
    """F-G3: Scan entity concerns and identify personal care reminders."""
    from datetime import date as _date

    rid = new_request_id()
    logger.info("rid=%s get_care_reminders user_id=%s limit=%d", rid, user_id, limit)

    today = _date.today()

    # Get all person entities with concerns
    entity_q = select(Entity).where(
        Entity.user_id == user_id,
        Entity.entity_type == "person",
        Entity.status.in_(["provisional", "confirmed"]),
    )
    entity_result = await session.execute(entity_q)
    entities = entity_result.scalars().all()

    # Batch-fetch source event titles to avoid N+1 queries
    source_event_ids = [e.source_event_id for e in entities if e.source_event_id]
    event_title_map: dict[str, str] = {}
    if source_event_ids:
        evt_result = await session.execute(
            select(Event.id, Event.title).where(Event.id.in_(source_event_ids))
        )
        event_title_map = {str(row[0]): row[1] for row in evt_result.fetchall()}

    personal_items = []
    business_items = []

    for entity in entities:
        props = entity.properties or {}
        concerns = props.get("concern", [])
        if not concerns or not isinstance(concerns, list):
            continue

        # Find source event title from batch-fetched map
        source_title = event_title_map.get(str(entity.source_event_id)) if entity.source_event_id else None

        # Days since entity created (proxy for when mentioned)
        days_since = 999
        if entity.created_at:
            if isinstance(entity.created_at, datetime):
                days_since = (today - entity.created_at.date()).days
            else:
                days_since = (today - entity.created_at).days

        # Company
        company = None
        basic = props.get("basic", {})
        if isinstance(basic, dict):
            company = basic.get("company")

        # Process each concern entry
        best_personal = None  # Keep only the best personal match per entity

        for concern_entry in concerns:
            if isinstance(concern_entry, dict):
                category = concern_entry.get("category", "")
                detail = concern_entry.get("detail", "")
            elif isinstance(concern_entry, str):
                detail = concern_entry
                category = ""
            else:
                continue

            if not detail:
                continue

            care_type, relevance = _classify_care_type(detail)

            icon = CARE_TYPE_ICONS.get(care_type, "\U0001f4a1")
            action = _generate_care_action(care_type, detail)

            item_data = {
                "entity_id": str(entity.id),
                "name": entity.name,
                "company": company,
                "concern_category": category,
                "concern_detail": detail,
                "care_type": care_type,
                "relevance_score": round(relevance, 2),
                "source_event_title": source_title,
                "days_since_mentioned": days_since,
                "suggested_action": action,
                "care_icon": icon,
            }

            if care_type != "business":
                # Personal/mixed care type
                if best_personal is None or relevance > best_personal.get("relevance_score", 0):
                    best_personal = item_data
            else:
                # Business concern - add to business list (limit later)
                business_items.append(CareReminderItem(**item_data))

        if best_personal:
            personal_items.append(CareReminderItem(**best_personal))

    # Sort personal by relevance * recency
    personal_items.sort(
        key=lambda c: c.relevance_score * (1.0 / (c.days_since_mentioned + 1)),
        reverse=True,
    )

    # Sort business by relevance
    business_items.sort(key=lambda c: c.relevance_score, reverse=True)
    business_items = business_items[:5]

    total = len(personal_items) + len(business_items)

    # Summary text
    if total == 0:
        summary = "暂无关怀提醒。多记录互动，AI会发现更多值得关心的细节。"
    elif len(personal_items) > 0:
        names = [p.name for p in personal_items[:3]]
        summary = f"发现{len(personal_items)}条个人关怀点：{'、'.join(names)}等。合适的时机表达关心，让关系更有温度。"
    else:
        summary = f"关注了{len(business_items)}位联系人的业务关切，继续深挖可能发现更多个人层面的关怀点。"

    return CareRemindersResponse(
        total=total,
        personal_items=personal_items[:limit],
        business_items=business_items,
        summary_text=summary,
    )

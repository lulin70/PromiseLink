"""Dashboard Morning Brief endpoint — 每日晨间摘要."""

from datetime import UTC, date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.dashboard.morning_brief")
router = APIRouter(tags=["Dashboard"])


# ── Pydantic Models ──


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


# ── Endpoint ──


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
                Todo.fulfillment_status.notin_(["fulfilled", "expired"]),
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
    day_start = day_start_local.astimezone(UTC).replace(tzinfo=None)
    day_end = day_end_local.astimezone(UTC).replace(tzinfo=None)
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
    hour = datetime.now(UTC).hour
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

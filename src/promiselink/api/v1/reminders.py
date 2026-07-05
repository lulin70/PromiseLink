"""Smart Follow-up Reminder API endpoints (F-69)."""

from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import UUIDStr
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.reminder import ReminderLog, ReminderPreference
from promiselink.models.todo import Todo

router = APIRouter(prefix="/reminders", dependencies=[Depends(rate_limit_dependency)])
logger = get_logger("promiselink.api.reminders")


# ── Pydantic Models ──


class ReminderItem(BaseModel):
    todo_id: UUIDStr
    todo_type: str
    title: str
    description: str | None = None
    priority: int
    dynamic_score: float | None = None
    due_date: datetime | None = None
    reminder_type: str
    related_entity_id: UUIDStr | None = None


class DailyReminderResponse(BaseModel):
    items: list[ReminderItem]
    total_pending: int
    fatigue_remaining: int
    is_quiet_hours: bool


class ReminderActionRequest(BaseModel):
    action: str = Field(..., description="completed / snoozed / dismissed")
    snooze_hours: int | None = Field(None, description="Required when action=snoozed")


class ReminderActionResponse(BaseModel):
    todo_id: UUIDStr
    action: str
    new_status: str


class BatchReminderActionRequest(BaseModel):
    """Batch action payload for 1.3 提醒页批量操作.

    Security: 每个 todo_id 服务端校验归属权（user_id 来自 JWT）；
    action 枚举白名单 complete/snooze/dismiss。
    """

    todo_ids: list[UUIDStr] = Field(..., min_length=1, max_length=50)
    action: str = Field(..., description="completed / snoozed / dismissed")
    snooze_hours: int | None = Field(None, description="Required when action=snoozed")


class BatchReminderActionItemResult(BaseModel):
    todo_id: UUIDStr
    new_status: str


class BatchReminderActionResponse(BaseModel):
    success: list[BatchReminderActionItemResult]
    failed: list[dict[str, str]]  # {"todo_id": "...", "error": "..."}


class PreferenceResponse(BaseModel):
    user_id: UUIDStr
    preferred_times: list[str]
    fatigue_threshold: int
    quiet_hours_start: str
    quiet_hours_end: str


class PreferenceUpdateRequest(BaseModel):
    preferred_times: list[str] | None = None
    fatigue_threshold: int | None = Field(None, ge=1, le=20)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None


# ── Helpers ──


def _is_quiet_hours(quiet_start: time, quiet_end: time, now: time | None = None) -> bool:
    """Check if current time falls within quiet hours."""
    if now is None:
        now = datetime.now(UTC).time()
    if quiet_start <= quiet_end:
        return quiet_start <= now < quiet_end
    # Crosses midnight, e.g. 22:00 → 08:00
    return now >= quiet_start or now < quiet_end


def _classify_reminder_type(todo: Todo) -> str:
    """Determine reminder_type based on todo attributes."""
    now = datetime.now(UTC)
    if todo.todo_type == "promise" and todo.due_date:
        due = todo.due_date.replace(tzinfo=UTC) if todo.due_date.tzinfo is None else todo.due_date
        if due <= now:
            return "promise_due"
    if todo.todo_type == "followup":
        return "followup"
    # Check properties for stage_suggestion / dormant_contact hints
    props = todo.properties or {}
    if props.get("reminder_hint") == "dormant_contact":
        return "dormant_contact"
    if props.get("reminder_hint") == "stage_suggestion":
        return "stage_suggestion"
    # Default classification by todo_type
    type_map = {
        "care": "stage_suggestion",
        "cooperation_signal": "stage_suggestion",
        "risk": "followup",
        "help": "followup",
    }
    return type_map.get(todo.todo_type, "followup")


# ── Endpoints ──


@router.get("/daily", response_model=DailyReminderResponse)
async def get_daily_reminders(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """Get daily reminder list with fatigue and quiet-hours filtering.

    Algorithm:
    1. Query all pending todos for the user
    2. Sort by dynamic_score descending (highest priority first)
    3. Check fatigue: today's sent count < fatigue_threshold
    4. Check quiet hours: skip if currently in quiet period
    5. Return top N reminders (N = fatigue_remaining)
    """
    new_request_id()

    # Load user preferences (or defaults)
    pref_result = await session.execute(
        select(ReminderPreference).where(ReminderPreference.user_id == user_id)
    )
    pref = pref_result.scalar_one_or_none()

    fatigue_threshold = pref.fatigue_threshold if pref else 5
    quiet_start = pref.quiet_hours_start if pref else time(22, 0)
    quiet_end = pref.quiet_hours_end if pref else time(8, 0)

    quiet = _is_quiet_hours(quiet_start, quiet_end)  # type: ignore[arg-type]

    # Count reminders already sent today
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    sent_count_result = await session.execute(
        select(func.count()).select_from(ReminderLog).where(
            and_(
                ReminderLog.user_id == user_id,
                ReminderLog.sent_at >= today_start,
            )
        )
    )
    sent_today = sent_count_result.scalar() or 0
    fatigue_remaining = max(0, fatigue_threshold - sent_today)

    # Query pending todos
    query = (
        select(Todo)
        .where(
            and_(
                Todo.user_id == user_id,
                Todo.status.in_(["pending", "in_progress", "snoozed"]),
            )
        )
        .order_by(Todo.dynamic_score.desc().nulls_last(), Todo.priority.asc())
    )
    result = await session.execute(query)
    todos = result.scalars().all()

    total_pending = len(todos)

    # Build reminder items, limited by fatigue_remaining
    items: list[ReminderItem] = []
    for todo in todos:
        if len(items) >= fatigue_remaining:
            break
        items.append(
            ReminderItem(
                todo_id=str(todo.id),
                todo_type=todo.todo_type,
                title=todo.title,
                description=todo.description,
                priority=todo.priority,
                dynamic_score=todo.dynamic_score,
                due_date=todo.due_date,
                reminder_type=_classify_reminder_type(todo),
                related_entity_id=str(todo.related_entity_id) if todo.related_entity_id else None,
            )
        )

    # Log that these reminders were sent (for fatigue tracking)
    now = datetime.now(UTC)
    for item in items:
        log_entry = ReminderLog(
            user_id=user_id,
            todo_id=item.todo_id,
            reminder_type=item.reminder_type,
            sent_at=now,
        )
        session.add(log_entry)

    await session.commit()

    return DailyReminderResponse(
        items=items,
        total_pending=total_pending,
        fatigue_remaining=fatigue_remaining - len(items),
        is_quiet_hours=quiet,
    )


@router.post("/{todo_id}/action", response_model=ReminderActionResponse)
async def take_reminder_action(
    todo_id: str,
    req: ReminderActionRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """One-click action on a reminder: completed / snoozed / dismissed.

    Also records the action in reminder_logs for response latency tracking.
    """
    new_request_id()

    if req.action not in ("completed", "snoozed", "dismissed"):
        raise ValidationError("Invalid action. Must be completed/snoozed/dismissed")

    if req.action == "snoozed" and req.snooze_hours is None:
        raise ValidationError("snooze_hours is required when action=snoozed")

    # Find the todo
    result = await session.execute(
        select(Todo).where(and_(Todo.id == todo_id, Todo.user_id == user_id))
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise NotFoundError("Todo not found")

    # Apply action
    if req.action == "completed":
        todo.status = "done"
        todo.completed_at = datetime.now(UTC)
        new_status = "done"
    elif req.action == "snoozed":
        todo.status = "snoozed"
        todo.reminder_at = datetime.now(UTC) + timedelta(hours=req.snooze_hours or 24)
        new_status = "snoozed"
    else:  # dismissed
        todo.status = "dismissed"
        new_status = "dismissed"

    # Update the most recent reminder_log for this todo+user
    log_result = await session.execute(
        select(ReminderLog)
        .where(and_(ReminderLog.user_id == user_id, ReminderLog.todo_id == todo_id))
        .order_by(ReminderLog.sent_at.desc())
        .limit(1)
    )
    log_entry = log_result.scalar_one_or_none()
    if log_entry:
        log_entry.action_taken = req.action
        # sent_at 可能是 naive datetime（PostgreSQL timestamp without tz），
        # 需补 tzinfo=UTC 才能与 datetime.now(UTC) 相减
        sent_at = log_entry.sent_at.replace(tzinfo=UTC) if log_entry.sent_at.tzinfo is None else log_entry.sent_at
        latency = (datetime.now(UTC) - sent_at).total_seconds()
        log_entry.response_latency_seconds = int(latency)

    await session.commit()

    logger.info(
        "reminder_action_taken",
        todo_id=todo_id,
        action=req.action,
        user_id=user_id,
    )

    return ReminderActionResponse(todo_id=todo_id, action=req.action, new_status=new_status)


@router.post("/batch-action", response_model=BatchReminderActionResponse)
async def take_batch_reminder_action(
    req: BatchReminderActionRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """Batch one-click action on multiple reminders (1.3 提醒页批量操作).

    Security:
    - action 枚举白名单：completed / snoozed / dismissed
    - 每个 todo_id 服务端校验归属权（user_id 取自 JWT，IDOR 防护）
    - 单次最多 50 条，防止滥用
    - 部分失败不阻塞：成功的提交，失败的逐条返回原因
    """
    new_request_id()

    if req.action not in ("completed", "snoozed", "dismissed"):
        raise ValidationError("Invalid action. Must be completed/snoozed/dismissed")

    if req.action == "snoozed" and req.snooze_hours is None:
        raise ValidationError("snooze_hours is required when action=snoozed")

    # 一次性查询当前用户的所有 todo_id（IDOR 防护：只查归属当前用户的）
    result = await session.execute(
        select(Todo).where(
            and_(
                Todo.user_id == user_id,
                Todo.id.in_(req.todo_ids),
            )
        )
    )
    owned_todos: dict[str, Todo] = {str(t.id): t for t in result.scalars().all()}

    success: list[BatchReminderActionItemResult] = []
    failed: list[dict[str, str]] = []

    now = datetime.now(UTC)
    for raw_id in req.todo_ids:
        todo_id = str(raw_id)
        todo = owned_todos.get(todo_id)
        if todo is None:
            failed.append({"todo_id": todo_id, "error": "not_found_or_forbidden"})
            continue
        try:
            if req.action == "completed":
                todo.status = "done"
                todo.completed_at = now
                new_status = "done"
            elif req.action == "snoozed":
                todo.status = "snoozed"
                todo.reminder_at = now + timedelta(hours=req.snooze_hours or 24)
                new_status = "snoozed"
            else:  # dismissed
                todo.status = "dismissed"
                new_status = "dismissed"
            success.append(BatchReminderActionItemResult(todo_id=todo_id, new_status=new_status))
        except Exception as e:  # noqa: BLE001 — 批量操作需收集失败而非中断
            failed.append({"todo_id": todo_id, "error": str(e)[:120]})

    await session.commit()

    logger.info(
        "reminder_batch_action_taken",
        user_id=user_id,
        action=req.action,
        success_count=len(success),
        failed_count=len(failed),
    )

    return BatchReminderActionResponse(success=success, failed=failed)


@router.get("/preferences", response_model=PreferenceResponse)
async def get_preferences(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """Get current reminder preferences for the user."""
    new_request_id()

    result = await session.execute(
        select(ReminderPreference).where(ReminderPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        # Return defaults
        return PreferenceResponse(
            user_id=user_id,
            preferred_times=["09:00", "20:00"],
            fatigue_threshold=5,
            quiet_hours_start="22:00",
            quiet_hours_end="08:00",
        )

    return PreferenceResponse(
        user_id=pref.user_id,
        preferred_times=pref.preferred_times or ["09:00", "20:00"],
        fatigue_threshold=pref.fatigue_threshold,
        quiet_hours_start=pref.quiet_hours_start.strftime("%H:%M") if pref.quiet_hours_start else "22:00",
        quiet_hours_end=pref.quiet_hours_end.strftime("%H:%M") if pref.quiet_hours_end else "08:00",
    )


@router.patch("/preferences", response_model=PreferenceResponse)
async def update_preferences(
    req: PreferenceUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """Update reminder preferences. Only provided fields are updated."""
    new_request_id()

    result = await session.execute(
        select(ReminderPreference).where(ReminderPreference.user_id == user_id)
    )
    pref = result.scalar_one_or_none()

    if not pref:
        # Create with defaults first
        pref = ReminderPreference(
            user_id=user_id,
            preferred_times=["09:00", "20:00"],
            fatigue_threshold=5,
            quiet_hours_start=time(22, 0),
            quiet_hours_end=time(8, 0),
        )
        session.add(pref)
        await session.flush()

    # Apply updates
    if req.preferred_times is not None:
        pref.preferred_times = req.preferred_times
    if req.fatigue_threshold is not None:
        pref.fatigue_threshold = req.fatigue_threshold
    if req.quiet_hours_start is not None:
        try:
            pref.quiet_hours_start = datetime.strptime(req.quiet_hours_start, "%H:%M").time()
        except ValueError:
            raise ValidationError("Invalid quiet_hours_start format. Use HH:MM")
    if req.quiet_hours_end is not None:
        try:
            pref.quiet_hours_end = datetime.strptime(req.quiet_hours_end, "%H:%M").time()
        except ValueError:
            raise ValidationError("Invalid quiet_hours_end format. Use HH:MM")

    pref.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(pref)

    return PreferenceResponse(
        user_id=pref.user_id,
        preferred_times=pref.preferred_times or ["09:00", "20:00"],
        fatigue_threshold=pref.fatigue_threshold,
        quiet_hours_start=pref.quiet_hours_start.strftime("%H:%M") if pref.quiet_hours_start else "22:00",
        quiet_hours_end=pref.quiet_hours_end.strftime("%H:%M") if pref.quiet_hours_end else "08:00",
    )

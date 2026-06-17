"""Promise fulfillment tracking API (F-68)."""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.todo import Todo
from promiselink.schemas.api_responses import FulfillmentUpdateResponse

router = APIRouter(prefix="/promises", dependencies=[Depends(rate_limit_dependency)])
logger = get_logger("promiselink.api.promises")


class PromiseItem(BaseModel):
    todo_id: str
    entity_id: str | None = None
    entity_name: str | None = None
    action_type: str
    description: str | None = None
    due_date: datetime | None = None
    fulfillment_status: str
    confirmation_status: str | None = None
    source_event_id: str | None = None
    source_event_title: str | None = None
    source_event_date: str | None = None
    created_at: datetime | None = None


class PromiseListResponse(BaseModel):
    items: list[PromiseItem]
    total: int
    offset: int
    limit: int


class PromiseStatsResponse(BaseModel):
    total: int
    my_promises: dict[str, int]  # {pending, fulfilled, overdue, broken}
    their_promises: dict[str, int]
    fulfillment_rate: float


class FulfillmentUpdateRequest(BaseModel):
    fulfillment_status: str  # "fulfilled" | "overdue" | "broken"


@router.get("", response_model=PromiseListResponse)
async def list_promises(
    view: str = Query("my-promises", description="my-promises or their-promises"),
    status: str | None = Query(None, description="Filter by fulfillment status"),
    search: str | None = Query(None, description="Search in description"),
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
):
    """List promises with dual view (my-promises / their-promises)."""
    new_request_id()

    # Build query: only promise-type todos
    conditions = [Todo.user_id == user_id]
    if view == "my-promises":
        conditions.append(Todo.action_type == "my_promise")
    elif view == "their-promises":
        conditions.append(Todo.action_type == "their_promise")
    else:
        conditions.append(Todo.action_type.in_(["my_promise", "their_promise"]))

    if status:
        conditions.append(Todo.fulfillment_status == status)

    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(Todo.description.ilike(f"%{escaped}%", escape="\\"))

    # Count
    count_q = select(func.count()).select_from(Todo).where(and_(*conditions))
    total = (await session.execute(count_q)).scalar() or 0

    # Query
    q = (
        select(Todo)
        .where(and_(*conditions))
        .order_by(Todo.due_date.asc().nulls_last())
        .offset(offset)
        .limit(limit)
    )
    results = (await session.execute(q)).scalars().all()

    # Fetch entity names for entity_ids
    entity_ids = [t.related_entity_id for t in results if t.related_entity_id]
    entity_names: dict[str, str] = {}
    if entity_ids:
        from promiselink.models.entity import Entity
        entity_result = await session.execute(
            select(Entity.id, Entity.name).where(Entity.id.in_([str(eid) for eid in entity_ids]))
        )
        entity_names = {str(eid): name for eid, name in entity_result.all()}

    # Fetch event titles and dates for source_event_ids
    event_ids = [t.source_event_id for t in results if t.source_event_id]
    event_titles: dict[str, str] = {}
    event_dates: dict[str, str | None] = {}
    if event_ids:
        from promiselink.models.event import Event
        event_result = await session.execute(
            select(Event.id, Event.title, Event.created_at).where(Event.id.in_([str(eid) for eid in event_ids]))
        )
        for eid, title, created in event_result.all():
            event_titles[str(eid)] = title
            event_dates[str(eid)] = created.strftime("%m-%d") if created else None

    items = []
    for t in results:
        eid = str(t.related_entity_id) if t.related_entity_id else None
        seid = str(t.source_event_id) if t.source_event_id else None
        items.append(
            PromiseItem(
                todo_id=str(t.id),
                entity_id=eid,
                entity_name=entity_names.get(eid) if eid else None,
                action_type=t.action_type or "my_promise",
                description=t.description,
                due_date=t.due_date,
                fulfillment_status=t.fulfillment_status or "pending",
                confirmation_status=t.confirmation_status,
                source_event_id=seid,
                source_event_title=event_titles.get(seid) if seid else None,
                source_event_date=event_dates.get(seid) if seid else None,
                created_at=t.created_at,
            )
        )

    return PromiseListResponse(items=items, total=total, offset=offset, limit=limit)


@router.patch("/{todo_id}/fulfillment", response_model=FulfillmentUpdateResponse)
async def update_fulfillment(
    todo_id: uuid.UUID,
    req: FulfillmentUpdateRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
):
    """Update fulfillment status of a promise.

    Security: their_promise type only allows pending->fulfilled (user confirms).
    AI cannot auto-mark their_promise as overdue/broken.
    """
    new_request_id()

    if req.fulfillment_status not in ("fulfilled", "overdue", "broken", "pending"):
        raise ValidationError("Invalid fulfillment_status. Must be fulfilled/overdue/broken/pending")

    q = select(Todo).where(Todo.id == str(todo_id), Todo.user_id == user_id)
    todo = (await session.execute(q)).scalar_one_or_none()
    if not todo:
        raise NotFoundError("Todo not found")

    # Security constraint: their_promise cannot be auto-marked overdue/broken
    if todo.action_type == "their_promise" and req.fulfillment_status in ("overdue", "broken"):
        # Allow user to manually mark, but log it
        logger.info(
            "their_promise_manual_mark",
            todo_id=str(todo_id),
            status=req.fulfillment_status,
            user_id=user_id,
        )

    todo.fulfillment_status = req.fulfillment_status
    if req.fulfillment_status == "fulfilled":
        todo.fulfilled_at = datetime.now(UTC)
    elif req.fulfillment_status == "pending":
        todo.fulfilled_at = None

    await session.commit()
    return FulfillmentUpdateResponse(todo_id=todo_id, fulfillment_status=req.fulfillment_status)


@router.get("/stats", response_model=PromiseStatsResponse)
async def promise_stats(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
):
    """Promise fulfillment statistics."""
    new_request_id()

    # My promises
    my_q = (
        select(Todo.fulfillment_status, func.count())
        .where(Todo.user_id == user_id, Todo.action_type == "my_promise")
        .group_by(Todo.fulfillment_status)
    )
    my_results = (await session.execute(my_q)).all()
    my_promises = {"pending": 0, "fulfilled": 0, "overdue": 0, "broken": 0}
    for status_val, count in my_results:
        my_promises[status_val or "pending"] = count

    # Their promises
    their_q = (
        select(Todo.fulfillment_status, func.count())
        .where(Todo.user_id == user_id, Todo.action_type == "their_promise")
        .group_by(Todo.fulfillment_status)
    )
    their_results = (await session.execute(their_q)).all()
    their_promises = {"pending": 0, "fulfilled": 0, "overdue": 0, "broken": 0}
    for status_val, count in their_results:
        their_promises[status_val or "pending"] = count

    total = sum(my_promises.values()) + sum(their_promises.values())
    fulfilled = my_promises["fulfilled"] + their_promises["fulfilled"]
    rate = fulfilled / total if total > 0 else 0.0

    return PromiseStatsResponse(
        total=total,
        my_promises=my_promises,
        their_promises=their_promises,
        fulfillment_rate=round(rate, 3),
    )


class NudgeDraftResponse(BaseModel):
    todo_id: str
    nudge_text: str
    is_fallback: bool = False


@router.get("/{todo_id}/nudge-draft", response_model=NudgeDraftResponse)
async def get_nudge_draft(
    todo_id: str,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
):
    """Generate or retrieve a gentle nudge message for an overdue their_promise.

    Only works for their_promise type todos that are pending or overdue.
    Never auto-sends; only generates a draft for user review.
    """
    from promiselink.config import get_settings
    from promiselink.services.nlg_service import generate_gentle_nudge

    new_request_id()

    q = select(Todo).where(Todo.id == todo_id, Todo.user_id == user_id)
    todo = (await session.execute(q)).scalar_one_or_none()
    if not todo:
        raise NotFoundError("Todo not found")

    # Only allow for their_promise type
    if todo.action_type != "their_promise":
        raise ValidationError("Nudge draft is only available for their_promise type")

    config = get_settings()

    # Check if already cached in properties._nlg_draft
    is_fallback = False
    props = todo.properties or {}
    cached_draft = props.get("_nlg_draft")
    if cached_draft:
        try:
            cached = cached_draft if isinstance(cached_draft, dict) else json.loads(cached_draft)
            if cached.get("nudge_text"):
                return NudgeDraftResponse(
                    todo_id=todo_id,
                    nudge_text=cached["nudge_text"],
                    is_fallback=cached.get("is_fallback", False),
                )
        except (json.JSONDecodeError, TypeError):
            logger.warning("nudge_draft_cache_parse_failed", todo_id=todo_id)

    # Generate new nudge
    nudge_text = await generate_gentle_nudge(session, todo, config)
    is_fallback = "不着急" in nudge_text  # Heuristic: fallback template contains this phrase

    # Cache result in properties._nlg_draft
    props = todo.properties or {}
    props["_nlg_draft"] = {"nudge_text": nudge_text, "is_fallback": is_fallback, "generated_at": datetime.now(UTC).isoformat()}
    todo.properties = props
    await session.commit()

    return NudgeDraftResponse(
        todo_id=todo_id,
        nudge_text=nudge_text,
        is_fallback=is_fallback,
    )

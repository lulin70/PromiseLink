"""Search and filter endpoints for events.

Contains the ``GET /events`` list endpoint with filtering and full-text
search. Registered as a sub-router of the main events router.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.v1.events import EventEntityRef, EventResponse
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.database import get_async_session
from promiselink.models import Entity, Event

search_router = APIRouter()

__all__ = ["search_router"]


@search_router.get("/events", response_model=PaginatedResponse[EventResponse])
async def list_events(
    event_type: str | None = None,
    status: str | None = None,
    search: str | None = Query(None, description="Search in title and raw_text"),
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> PaginatedResponse[EventResponse]:
    """
    List events with optional filtering.

    Query parameters:
    - event_type: Filter by event type
    - status: Filter by processing status
    - search: Search in title and raw_text
    - limit: Maximum number of results (default: 100, max: 500)
    - offset: Pagination offset (default: 0)
    """
    query = select(Event).where(Event.user_id == user_id)

    if event_type:
        query = query.where(Event.event_type == event_type)
    if status:
        query = query.where(Event.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Event.title.ilike(f"%{escaped}%", escape="\\") | Event.raw_text.ilike(f"%{escaped}%", escape="\\"))

    # Count total
    count_query = select(func.count()).select_from(Event).where(Event.user_id == user_id)
    if event_type:
        count_query = count_query.where(Event.event_type == event_type)
    if status:
        count_query = count_query.where(Event.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        count_query = count_query.where(Event.title.ilike(f"%{escaped}%", escape="\\") | Event.raw_text.ilike(f"%{escaped}%", escape="\\"))
    total = (await session.execute(count_query)).scalar() or 0

    # Fetch paginated
    # TODO(P3): For large datasets, consider cursor-based pagination (e.g., based on
    # created_at + id) instead of offset-based pagination to avoid performance
    # degradation at high offsets. See: https://use-the-index-luke.com/no-offset
    query = query.order_by(Event.created_at.desc()).limit(min(limit, 500)).offset(offset)
    result = await session.execute(query)
    events = result.scalars().all()

    # Fetch entity names for all events
    event_ids = [str(e.id) for e in events]
    event_entities: dict[str, list[EventEntityRef]] = {}
    if event_ids:
        entity_result = await session.execute(
            select(Entity.id, Entity.name, Entity.source_event_id).where(
                Entity.source_event_id.in_(event_ids),
                Entity.user_id == user_id,
            )
        )
        for eid, name, src_event_id in entity_result.all():
            sid = str(src_event_id)
            if sid not in event_entities:
                event_entities[sid] = []
            event_entities[sid].append(EventEntityRef(id=str(eid), name=name))

    items = []
    for e in events:
        items.append(EventResponse(
            id=str(e.id),
            user_id=str(e.user_id),
            event_type=e.event_type,
            source=e.source,
            title=e.title,
            timestamp=e.timestamp,
            status=e.status,
            created_at=e.created_at,
            entities=event_entities.get(str(e.id), []),
        ))

    return PaginatedResponse(items=items, total=total, limit=min(limit, 500), offset=offset)

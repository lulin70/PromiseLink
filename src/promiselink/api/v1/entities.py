"""Entity CRUD API endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.entities_credit import router as credit_router
from promiselink.api.v1.entities_stages import router as stages_router
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.crypto import (
    decrypt_pii_in_properties,
    encrypt_pii_in_properties,
)
from promiselink.core.exceptions import NotFoundError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.entity_cleanup import delete_entity_cascade

logger = get_logger("promiselink.api.entities")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])
router.include_router(stages_router)
router.include_router(credit_router)


# ── Pydantic Models ──


class EntityResponse(BaseModel):
    id: uuid.UUID | str
    user_id: uuid.UUID | str
    entity_type: str
    name: str
    canonical_name: str
    aliases: list[str] | None = None
    properties: dict | None = None
    confidence: float
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EntityDetailResponse(EntityResponse):
    source_event_id: uuid.UUID | str | None = None
    updated_at: datetime | None = None


class EntityUpdateRequest(BaseModel):
    name: str | None = None
    aliases: list[str] | None = None
    properties: dict | None = None
    status: str | None = None


# ── Endpoints ──


@router.get("/entities", response_model=PaginatedResponse[EntityResponse])
async def list_entities(
    entity_type: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """List entities with optional filtering and pagination."""
    new_request_id()

    query = select(Entity).where(Entity.user_id == user_id)

    if entity_type:
        query = query.where(Entity.entity_type == entity_type)
    if status:
        query = query.where(Entity.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(Entity.name.ilike(f"%{escaped}%", escape="\\"))

    # Count total
    count_query = select(func.count()).select_from(Entity).where(Entity.user_id == user_id)
    if entity_type:
        count_query = count_query.where(Entity.entity_type == entity_type)
    if status:
        count_query = count_query.where(Entity.status == status)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        count_query = count_query.where(Entity.name.ilike(f"%{escaped}%", escape="\\"))
    total = (await session.execute(count_query)).scalar() or 0

    # Fetch paginated
    query = query.order_by(Entity.created_at.desc()).limit(min(limit, 500)).offset(offset)

    result = await session.execute(query)
    entities = result.scalars().all()

    # Decrypt PII fields before returning
    for entity in entities:
        if entity.properties:
            entity.properties = decrypt_pii_in_properties(entity.properties)

    return PaginatedResponse(items=entities, total=total, limit=min(limit, 500), offset=offset)


# ── F-E3: Dormant Contacts Endpoint (MUST be before /{entity_id} to avoid route conflict) ──


class DormantContactItem(BaseModel):
    entity_id: str
    name: str
    company: str | None = None
    dormant_days: int
    reactivation_score: float
    last_interaction: str | None = None
    last_event_summary: str | None = None
    reason: str
    icebreaker_topic: str
    pending_their_promises: int = 0
    relationship_stage: str = "unknown"


class DormantContactsResponse(BaseModel):
    items: list[DormantContactItem]
    total: int
    limit: int
    min_days: int


@router.get("/entities/dormant", response_model=DormantContactsResponse)
async def get_dormant_contacts(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    min_days: int = Query(60, ge=1, le=730),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Scan for dormant person contacts and return reactivation candidates.

    Returns contacts with no interaction for >= min_days, sorted by
    reactivation potential score (descending). Includes AI-generated
    icebreaker suggestions.
    """
    from promiselink.services.dormant_scanner import scan_dormant_contacts

    new_request_id()

    items, total = await scan_dormant_contacts(
        session=session,
        user_id=user_id,
        limit=limit,
        offset=offset,
        min_days=min_days,
    )

    return DormantContactsResponse(
        items=[DormantContactItem(**r.to_dict()) for r in items],
        total=total,
        limit=limit,
        min_days=min_days,
    )


@router.get("/entities/{entity_id}", response_model=EntityDetailResponse)
async def get_entity(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Get detailed information about a specific entity."""
    new_request_id()

    result = await session.execute(
        select(Entity).where(
            Entity.id == str(entity_id),
            Entity.user_id == user_id,
        )
    )
    entity = result.scalar_one_or_none()

    if not entity:
        raise NotFoundError("Entity not found")

    # Decrypt PII fields before returning
    if entity.properties:
        entity.properties = decrypt_pii_in_properties(entity.properties)

    return entity


@router.patch("/entities/{entity_id}", response_model=EntityResponse)
async def update_entity(
    entity_id: uuid.UUID,
    request: EntityUpdateRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Update an entity's fields."""
    new_request_id()

    result = await session.execute(
        select(Entity).where(
            Entity.id == str(entity_id),
            Entity.user_id == user_id,
        )
    )
    entity = result.scalar_one_or_none()

    if not entity:
        raise NotFoundError("Entity not found")

    # Apply updates
    if request.name is not None:
        entity.name = request.name
    if request.aliases is not None:
        entity.aliases = request.aliases
    if request.properties is not None:
        entity.properties = encrypt_pii_in_properties(request.properties)
    if request.status is not None:
        entity.status = request.status

    await session.commit()
    await session.refresh(entity)

    logger.info(
        "entity_updated",
        entity_id=str(entity.id),
    )

    return entity


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Delete an entity and its associations."""
    new_request_id()

    result = await session.execute(
        select(Entity).where(Entity.id == str(entity_id), Entity.user_id == user_id)
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError("Entity not found")

    # Delete entity and its related associations/todos via service
    await delete_entity_cascade(session, str(entity_id), user_id)

    await session.commit()

    logger.info(
        "entity_deleted",
        entity_id=str(entity_id),
    )

    return None


# ── Entity History Endpoint ──


class EventBriefResponse(BaseModel):
    """Brief event info for entity history."""
    id: uuid.UUID | str
    event_type: str
    title: str
    timestamp: datetime | None = None
    status: str
    raw_text_preview: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TodoBriefResponse(BaseModel):
    """Brief todo info for entity history."""
    id: uuid.UUID | str
    todo_type: str
    title: str
    priority: int
    status: str
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class AssociationBriefResponse(BaseModel):
    """Brief association info for entity history."""
    id: uuid.UUID | str
    association_type: str
    target_entity_name: str | None = None
    strength: float

    model_config = ConfigDict(from_attributes=True)


class EntityHistoryResponse(BaseModel):
    """Complete interaction history for an entity."""
    entity: EntityDetailResponse
    events: list[EventBriefResponse]
    todos: list[TodoBriefResponse]
    associations: list[AssociationBriefResponse]


@router.get("/entities/{entity_id}/history", response_model=EntityHistoryResponse)
async def get_entity_history(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Get the complete interaction history for a specific entity.

    Returns all events, todos, and associations related to this entity.
    Events are found via source_event_id and properties.event_ids.
    """
    new_request_id()

    # 1. Fetch entity
    result = await session.execute(
        select(Entity).where(
            Entity.id == str(entity_id),
            Entity.user_id == user_id,
        )
    )
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError("Entity not found")

    # 2. Find related event IDs
    event_ids = set()
    # From source_event_id
    if entity.source_event_id:
        event_ids.add(str(entity.source_event_id))
    # From properties.event_ids (accumulated through merges)
    props = entity.properties or {}
    for eid in props.get("event_ids", []):
        event_ids.add(str(eid))

    # 3. Fetch related events
    events = []
    if event_ids:
        event_result = await session.execute(
            select(Event).where(
                Event.id.in_(list(event_ids)),
                Event.user_id == user_id,
            ).order_by(Event.timestamp.asc())
        )
        for e in event_result.scalars().all():
            preview = (e.raw_text or "")[:150].replace("\n", " ")
            events.append(EventBriefResponse(
                id=e.id,
                event_type=e.event_type,
                title=e.title,
                timestamp=e.timestamp,
                status=e.status,
                raw_text_preview=preview,
            ))

    # 4. Fetch related todos
    todo_result = await session.execute(
        select(Todo).where(
            Todo.source_event_id.in_(list(event_ids)),
            Todo.user_id == user_id,
        ).order_by(Todo.created_at.desc())
    )
    todos = [
        TodoBriefResponse(
            id=t.id,
            todo_type=t.todo_type,
            title=t.title,
            priority=t.priority or 3,
            status=t.status,
            created_at=t.created_at,
        )
        for t in todo_result.scalars().all()
    ]

    # 5. Fetch related associations
    assoc_result = await session.execute(
        select(Association).where(
            (Association.source_entity_id == str(entity_id))
            | (Association.target_entity_id == str(entity_id)),
            Association.user_id == user_id,
        )
    )
    # Build entity name map for display
    assoc_entity_ids = set()
    raw_assocs = list(assoc_result.scalars().all())
    for a in raw_assocs:
        assoc_entity_ids.add(str(a.source_entity_id))
        assoc_entity_ids.add(str(a.target_entity_id))
    # Fetch names
    name_map = {}
    if assoc_entity_ids:
        name_result = await session.execute(
            select(Entity.id, Entity.name).where(
                Entity.id.in_(list(assoc_entity_ids)),
                Entity.user_id == user_id,
            )
        )
        for row in name_result:
            name_map[str(row[0])] = row[1]

    associations = []
    for a in raw_assocs:
        # Show the OTHER entity's name
        other_id = (
            str(a.target_entity_id)
            if str(a.source_entity_id) == str(entity_id)
            else str(a.source_entity_id)
        )
        associations.append(AssociationBriefResponse(
            id=a.id,
            association_type=a.association_type,
            target_entity_name=name_map.get(other_id, "???"),
            strength=a.strength or 0.0,
        ))

    return EntityHistoryResponse(
        entity=EntityDetailResponse.model_validate(entity),
        events=events,
        todos=todos,
        associations=associations,
    )


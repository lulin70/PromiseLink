"""Association CRUD API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import PaginatedResponse, UUIDStr
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.association import Association

logger = get_logger("promiselink.api.associations")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


# ── Pydantic Models ──


class AssociationResponse(BaseModel):
    id: UUIDStr
    user_id: UUIDStr
    source_entity_id: UUIDStr
    target_entity_id: UUIDStr
    association_type: str
    strength: float
    confidence: float
    status: str
    properties: dict[str, Any] | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Endpoints ──


@router.get("/associations", response_model=PaginatedResponse[AssociationResponse])
async def list_associations(
    association_type: str | None = None,
    status: str | None = None,
    limit: int = Query(20, ge=1),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """List associations with optional filtering."""
    new_request_id()

    stmt = select(Association).where(Association.user_id == user_id)

    if association_type:
        stmt = stmt.where(Association.association_type == association_type)
    if status:
        stmt = stmt.where(Association.status == status)

    # Count total
    count_query = select(func.count()).select_from(Association).where(Association.user_id == user_id)
    if association_type:
        count_query = count_query.where(Association.association_type == association_type)
    if status:
        count_query = count_query.where(Association.status == status)
    total = (await session.execute(count_query)).scalar() or 0

    # Fetch paginated
    stmt = stmt.order_by(Association.created_at.desc()).offset(offset).limit(min(limit, 500))

    result = await session.execute(stmt)
    associations = result.scalars().all()

    return PaginatedResponse(items=list(associations), total=total, limit=min(limit, 500), offset=offset)


@router.get(
    "/associations/{association_id}", response_model=AssociationResponse
)
async def get_association(
    association_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Get a specific association by ID."""
    new_request_id()

    stmt = select(Association).where(
        Association.id == str(association_id),
        Association.user_id == user_id,
    )
    result = await session.execute(stmt)
    association = result.scalar_one_or_none()

    if not association:
        raise NotFoundError("Association not found")

    return association

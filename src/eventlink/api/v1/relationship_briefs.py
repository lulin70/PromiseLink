"""RelationshipBrief API endpoints — F-47: Relationship progress tracking card CRUD.

Endpoints:
- GET   /api/v1/persons/{entity_id}/relationship-brief  — Get brief for a person
- GET   /api/v1/relationship-briefs                       — List user's briefs (stage filter)
- PATCH /api/v1/relationship-briefs/{brief_id}            — Update brief (optimistic lock)
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.api.v1.schemas import PaginatedResponse
from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.services.relationship_brief_service import (
    RelationshipBriefService,
)

logger = get_logger("eventlink.api.relationship_briefs")
router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────


class RelationshipBriefResponse(BaseModel):
    """Full relationship brief response."""

    id: uuid.UUID | str
    user_id: uuid.UUID | str
    person_entity_id: uuid.UUID | str
    relationship_stage: str
    brief_data: dict
    version: int
    last_updated_at: object | None = None
    created_at: object | None = None

    model_config = ConfigDict(from_attributes=True)


class UpdateRelationshipBriefRequest(BaseModel):
    """Partial update request for a relationship brief."""

    notes: str | None = Field(default=None, description="Manual notes to update")
    brief_data_partial: dict | None = Field(
        default=None, description="Partial dict to merge into brief_data"
    )
    expected_version: int = Field(
        ..., description="Current version for optimistic locking"
    )


# ── Endpoints ────────────────────────────────────────────────


@router.get(
    "/persons/{entity_id}/relationship-brief",
    response_model=RelationshipBriefResponse,
)
async def get_relationship_brief(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
):
    """Get the relationship progress tracking card for a specific person entity."""
    new_request_id()

    service = RelationshipBriefService(session)
    try:
        brief = await service.get_brief(user_id, str(entity_id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    return RelationshipBriefResponse.model_validate(brief)


@router.get(
    "/relationship-briefs",
    response_model=PaginatedResponse[RelationshipBriefResponse],
)
async def list_relationship_briefs(
    stage: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
):
    """List all relationship briefs for the current user.

    Supports optional filtering by relationship_stage.
    """
    new_request_id()

    service = RelationshipBriefService(session)
    briefs, total = await service.list_briefs(
        user_id=user_id, stage=stage, limit=limit, offset=offset
    )

    items = [RelationshipBriefResponse.model_validate(b) for b in briefs]
    return PaginatedResponse(
        items=items,
        total=total,
        limit=min(limit, 500),
        offset=offset,
    )


@router.patch(
    "/relationship-briefs/{brief_id}",
    response_model=RelationshipBriefResponse,
    status_code=status.HTTP_200_OK,
)
async def update_relationship_brief(
    brief_id: uuid.UUID,
    body: UpdateRelationshipBriefRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
):
    """Partially update a relationship brief with optimistic locking.

    Uses expected_version for conflict detection.
    Returns 409 Conflict if version mismatch.
    """
    new_request_id()

    # Verify ownership first
    result = await session.execute(
        select(RelationshipBrief).where(
            RelationshipBrief.id == str(brief_id),
            RelationshipBrief.user_id == user_id,
        )
    )
    existing = result.scalar_one_or_none()
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RelationshipBrief not found or access denied",
        )

    service = RelationshipBriefService(session)
    try:
        updated = await service.update_brief_partial(
            brief_id=str(brief_id),
            notes=body.notes,
            brief_data_partial=body.brief_data_partial,
            expected_version=body.expected_version,
        )
    except ValueError as exc:
        if "Optimistic lock" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    await session.refresh(updated)

    logger.info(
        "relationship_brief_updated",
        brief_id=str(brief_id),
        version=updated.version,
    )

    return RelationshipBriefResponse.model_validate(updated)

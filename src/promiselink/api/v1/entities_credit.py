"""Entity credit score API endpoints (F-E5: Per-Person Credit Score)."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.entities_credit")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


# ── Pydantic Models ──


class CreditScoreBreakdown(BaseModel):
    my_fulfillment_rate: float = 0.0
    their_fulfillment_rate: float = 0.0
    interaction_consistency: float = 0.0
    total_interactions: int = 0


class CreditScoreResponse(BaseModel):
    entity_id: str
    name: str
    score: float  # 0-100
    grade: str  # A+/A/B/C/D
    breakdown: CreditScoreBreakdown


class CreditScoreListResponse(BaseModel):
    items: list[CreditScoreResponse]
    total: int


@router.get("/entities/{entity_id}/credit-score", response_model=CreditScoreResponse)
async def get_entity_credit_score(
    entity_id: str,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Calculate per-entity relationship credit score (0-100).

    Score = my_fulfillment*40% + their_fulfillment*35% + consistency*15% + timeliness*10%
    Grade: A+(>=90) A(80-89) B(70-79) C(60-69) D(<60)
    Requires at least 2 interactions to calculate.
    """
    new_request_id()

    # Verify entity exists and belongs to user
    entity_result = await session.execute(
        select(Entity).where(Entity.id == entity_id, Entity.user_id == user_id)
    )
    entity = entity_result.scalar_one_or_none()
    if not entity:
        raise NotFoundError("Entity not found")

    score_data = await _calculate_credit_score(session, entity_id, user_id)

    return CreditScoreResponse(
        entity_id=entity_id,
        name=entity.name,
        score=round(score_data["score"], 1),
        grade=score_data["grade"],
        breakdown=CreditScoreBreakdown(
            **{k: v for k, v in score_data.items()
               if k != "score" and k != "grade"}
        ),
    )


@router.get("/entities/credit-scores", response_model=CreditScoreListResponse)
async def list_credit_scores(
    min_interactions: int = Query(2, ge=0),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """List all entities with credit scores, sorted by score descending."""
    new_request_id()

    # Get all person entities with enough interactions
    # Count todos per entity as proxy for interaction count
    todo_count_q = (
        select(Todo.related_entity_id, func.count())
        .where(Todo.user_id == user_id, Todo.related_entity_id.isnot(None))
        .group_by(Todo.related_entity_id)
        .having(func.count() >= min_interactions)
    )
    entity_counts: dict[str, int] = dict((await session.execute(todo_count_q)).all())  # type: ignore[arg-type]

    if not entity_counts:
        return CreditScoreListResponse(items=[], total=0)

    # Filter to person entities only — bulk query instead of N+1
    qualified_ids = list(entity_counts.keys())
    entities_result = await session.execute(
        select(Entity).where(Entity.id.in_(qualified_ids), Entity.user_id == user_id)
    )
    entities_map = {str(e.id): e for e in entities_result.scalars().all()}

    # Keep only person entities
    qualified_ids = []
    entity_name_map = {}
    for eid_str, entity in entities_map.items():
        if entity.entity_type == "person":
            qualified_ids.append(eid_str)
            entity_name_map[eid_str] = entity.name

    # Batch calculate all credit scores in 3 queries instead of N*4
    from promiselink.services.credit_score import CreditScoreService
    scores = await CreditScoreService.batch_calculate(session, qualified_ids, user_id)

    results = []
    for eid_str in qualified_ids:
        score_data = scores.get(eid_str)
        if not score_data:
            continue
        results.append(CreditScoreResponse(
            entity_id=eid_str,
            name=entity_name_map[eid_str],
            score=round(score_data["score"], 1),
            grade=score_data["grade"],
            breakdown=CreditScoreBreakdown(
                **{k: v for k, v in score_data.items()
                   if k not in ("score", "grade")}
            ),
        ))

    results.sort(key=lambda r: r.score, reverse=True)
    return CreditScoreListResponse(items=results[offset:offset + limit], total=len(results))


async def _calculate_credit_score(
    session: AsyncSession,
    entity_id: str,
    user_id: str,
) -> dict:
    """Core credit score calculation logic — delegates to CreditScoreService."""
    from promiselink.services.credit_score import CreditScoreService
    return await CreditScoreService.calculate(session, entity_id, user_id)

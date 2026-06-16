"""Dashboard Supply-Demand Matching endpoint — F-E4: 供需匹配."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity

logger = get_logger("promiselink.api.dashboard.supply_demand")
router = APIRouter(tags=["Dashboard"])


# ── Pydantic Models ──


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


# ── Helper ──


def _extract_company_from_props(properties: dict | None) -> str | None:
    """Extract company name from entity properties."""
    if not properties:
        return None
    basic = properties.get("basic", {})
    if isinstance(basic, dict):
        return basic.get("company")
    return None


# ── Endpoint ──


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

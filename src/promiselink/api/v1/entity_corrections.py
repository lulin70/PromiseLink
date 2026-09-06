"""EntityCorrections API — W3 纠偏回流只读端点.

Endpoints:
- GET /entity-corrections         : 用户自查最近纠偏（audit-only projection）
- GET /entity-corrections/aggregations : 按 (correction_type, action) 聚合；零原文字段

Privacy contract (FR-W3-3 / FR-W3-4):
- Never return original_extracted_text
- Never return candidate_entity_ids list (raw)
- Aggregation never includes entity_id, event_id, or any selectable identifier
  beyond the (correction_type, action) tuple
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.database import get_async_session
from promiselink.models.entity_correction import EntityCorrection

router = APIRouter(
    prefix="/entity-corrections",
    tags=["EntityCorrections"],
    dependencies=[],
)


@router.get("")
async def list_recent_corrections(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    correction_type: str | None = Query(None, pattern="^(entity|todo|promise|association)$"),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """List recent corrections for current user (audit-only projection)."""
    stmt = (
        select(EntityCorrection)
        .where(EntityCorrection.user_id == user_id)
        .order_by(EntityCorrection.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if correction_type:
        stmt = stmt.where(EntityCorrection.correction_type == correction_type)
    rows = (await session.execute(stmt)).scalars().all()
    return [r.to_audit_dict() for r in rows]


@router.get("/aggregations")
async def get_correction_aggregations(
    days: int = Query(30, ge=1, le=365),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> list[dict]:
    """Aggregate corrections over the last N days.

    Returns ONLY: [{correction_type, action, count, last_seen}].
    No raw text, no candidate ids, no selectable identifiers.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    rows = (
        await session.execute(
            text(
                "SELECT correction_type, action, COUNT(*) AS cnt, MAX(created_at) AS last_seen "
                "FROM entity_corrections "
                "WHERE user_id = :uid AND created_at >= :since "
                "GROUP BY correction_type, action "
                "ORDER BY cnt DESC"
            ),
            {"uid": user_id, "since": cutoff},
        )
    ).fetchall()

    out: list[dict] = []
    for r in rows:
        last_seen = r.last_seen
        if last_seen and not isinstance(last_seen, str):
            last_seen = last_seen.isoformat()
        out.append(
            {
                "correction_type": r.correction_type,
                "action": r.action,
                "count": int(r.cnt),
                "last_seen": last_seen,
            }
        )
    return out

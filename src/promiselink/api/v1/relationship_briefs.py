"""RelationshipBrief API endpoints — F-47: Relationship progress tracking card CRUD.

Endpoints:
- GET   /api/v1/persons/{entity_id}/relationship-brief  — Get brief for a person
- GET   /api/v1/persons/{entity_id}/relationship-brief/aggregated  — Aggregated 12-module view
- GET   /api/v1/relationship-briefs                       — List user's briefs (stage filter)
- PATCH /api/v1/relationship-briefs/{brief_id}            — Update brief (optimistic lock)
"""

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ConflictError, NotFoundError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.relationship_brief import RelationshipBrief
from promiselink.services.relationship_brief_service import (
    RelationshipBriefService,
)
from promiselink.services.relationship_stage import STAGE_METADATA, RelationshipStage

logger = get_logger("promiselink.api.relationship_briefs")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


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


# ── Aggregated View Schemas ───────────────────────────────────


# 12-module metadata mapping: (display_name, icon, default_priority)
_MODULE_META: dict[str, tuple[str, str, str]] = {
    "basic_info": ("基本信息", "\U0001f464", "low"),
    "relationship_stage": ("关系阶段", "\U0001f4c8", "high"),
    "last_interaction": ("最近互动", "\U0001f4ac", "medium"),
    "interaction_freq": ("互动频率", "\U0001f4ca", "medium"),
    "open_promises": ("待兑现承诺", "\U0001f91d", "medium"),
    "their_concerns": ("对方关心", "\u2764\ufe0f", "medium"),
    "my_contributions": ("我的贡献", "\U0001f381", "medium"),
    "cooperation_signals": ("合作信号", "\U0001f91d", "medium"),
    "risk_flags": ("风险预警", "\u26a0\ufe0f", "medium"),
    "next_actions": ("建议行动", "\u2705", "high"),
    "strength_score": ("关系强度", "\U0001f4aa", "medium"),
    "notes": ("备注", "\U0001f4dd", "low"),
}


def _strength_label(score: int) -> tuple[str, str]:
    """Return (label, color) for strength score."""
    if score >= 80:
        return ("关系稳固", "#A0C4A8")
    elif score >= 60:
        return ("关系良好", "#C4C0A0")
    elif score >= 40:
        return ("关系发展中", "#A0B0C4")
    elif score >= 20:
        return ("关系初期", "#B0A0C4")
    else:
        return ("刚建立联系", "#C4C4C4")


def _module_has_meaningful_data(key: str, data: dict) -> bool:
    """Check if a module's data is non-empty / meaningful."""
    module_data = data.get(key)
    if module_data is None:
        return False
    if isinstance(module_data, dict):
        # Exclude empty dicts and dicts with only empty values
        return bool([v for v in module_data.values() if v])
    if isinstance(module_data, (list, str)):
        return bool(len(module_data))
    if isinstance(module_data, (int, float)):
        return True
    return bool(module_data)


def _compute_module_priority(key: str, data: dict) -> str:
    """Compute priority based on content presence for conditional-high modules."""
    default_prio = _MODULE_META.get(key, ("", "", "medium"))[2]

    # Modules that become high priority when they have data
    _conditional_high = {
        "open_promises",
        "their_concerns",
        "cooperation_signals",
        "risk_flags",
    }

    if key in _conditional_high and _module_has_meaningful_data(key, data):
        return "high"
    return default_prio


def _summarize_module(key: str, data: dict) -> str:
    """Generate a one-line human-readable summary for a module."""
    module_data = data.get(key)
    if not _module_has_meaningful_data(key, data):
        return "暂无数据"

    summaries: dict[str, Callable[[dict], str]] = {
        "basic_info": lambda d: f"姓名: {d.get('basic_info', {}).get('name', '未知')}",
        "relationship_stage": lambda d: STAGE_METADATA.get(
            RelationshipStage(d.get("relationship_stage", "new_connection")),
            {},
        ).get("description", d.get("relationship_stage", "")),
        "last_interaction": lambda d: d.get("last_interaction", {}).get(
            summary_key(d), "最近无互动记录"
        ),
        "interaction_freq": lambda d: f"共{d.get('interaction_freq', {}).get('total_count', 0)}次互动, 近30天{d.get('interaction_freq', {}).get('last_30_days', 0)}次",
        "open_promises": lambda d: _count_promises_summary(d),
        "their_concerns": lambda d: f"关注{len(d.get('their_concerns', []))}个方面",
        "my_contributions": lambda d: f"已贡献{len(d.get('my_contributions', []))}项",
        "cooperation_signals": lambda d: f"发现{len(d.get('cooperation_signals', []))}个合作信号",
        "risk_flags": lambda d: f"{len(d.get('risk_flags', []))}个风险点需注意",
        "next_actions": lambda d: f"{len(d.get('next_actions', []))}条建议待执行",
        "strength_score": lambda d: f"综合评分: {d.get('strength_score', 0)}/100",
        "notes": lambda d: (d.get("notes") or "")[:50] or "暂无备注",
    }
    fn = summaries.get(key)
    if fn:
        try:
            return fn(data)
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            logger.debug("brief_summary_format_failed", key=key, error=str(exc))
            return "数据异常"

    return str(module_data)[:80] if module_data else "暂无数据"


def summary_key(d: dict) -> str:
    """Get the best summary key from last_interaction data."""
    li = d.get("last_interaction", {})
    if li.get("summary"):
        return "summary"
    if li.get("title"):
        return "title"
    if li.get("event_type"):
        return "event_type"
    return "date"


def _count_promises_summary(data: dict) -> str:
    """Generate summary for open_promises."""
    promises = data.get("open_promises", {})
    my_count = len(promises.get("my_promises", []))
    their_count = len(promises.get("their_promises", []))
    parts = []
    if my_count > 0:
        parts.append(f"我方{my_count}项待兑现")
    if their_count > 0:
        parts.append(f"对方{their_count}项待兑现")
    if not parts:
        return "暂无待兑现承诺"
    return ", ".join(parts)


class BriefModuleItem(BaseModel):
    """Single module data in the aggregated view."""

    module_name: str
    display_name: str
    icon: str
    has_data: bool
    summary: str
    detail: object | None = None
    priority: str | None = None

    model_config = ConfigDict(from_attributes=True)


class RelationshipBriefAggregatedResponse(BaseModel):
    """Aggregated relationship brief with structured 12-module view."""

    id: uuid.UUID | str
    person_entity_id: uuid.UUID | str
    person_name: str | None = None
    person_company: str | None = None
    relationship_stage: str
    stage_label: str = ""
    stage_color: str = ""
    stage_icon: str = ""
    strength_score: int = 0
    strength_label: str = ""
    last_interaction_date: str | None = None
    last_interaction_summary: str | None = None
    interaction_freq_summary: str | None = None
    modules: list[BriefModuleItem] = []
    suggested_actions: list[str] = []
    version: int = 1
    last_updated_at: object | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Endpoints ────────────────────────────────────────────────


@router.get(
    "/persons/{entity_id}/relationship-brief",
    response_model=RelationshipBriefResponse,
)
async def get_relationship_brief(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Get the relationship progress tracking card for a specific person entity."""
    new_request_id()

    service = RelationshipBriefService(session)
    try:
        brief = await service.get_brief(user_id, str(entity_id))
    except ValueError as exc:
        raise NotFoundError(str(exc))

    return RelationshipBriefResponse.model_validate(brief)


@router.get(
    "/persons/{entity_id}/relationship-brief/aggregated",
    response_model=RelationshipBriefAggregatedResponse,
    tags=["RelationshipBrief"],
)
async def get_relationship_brief_aggregated(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Get aggregated relationship brief with structured 12-module view.

    Resolves entity name/company, formats each module into human-readable form,
    computes strength label, and provides quick action suggestions.
    """
    new_request_id()

    # 1. Fetch the brief
    service = RelationshipBriefService(session)
    try:
        brief = await service.get_brief(user_id, str(entity_id))
    except ValueError as exc:
        raise NotFoundError(str(exc))

    data = brief.brief_data or {}

    # 2. Resolve entity name + company
    person_name: str | None = None
    person_company: str | None = None
    try:
        entity_result = await session.execute(
            select(Entity).where(Entity.id == str(entity_id))
        )
        entity = entity_result.scalar_one_or_none()
        if entity:
            person_name = entity.name
            props = entity.properties or {}
            person_company = (
                props.get("company")
                or (props.get("basic") or {}).get("company")
                or None
            )
    except SQLAlchemyError as exc:
        logger.warning("failed_to_resolve_entity", entity_id=str(entity_id), error=str(exc))

    # 3. Stage metadata
    stage_str = brief.relationship_stage
    try:
        stage_enum = RelationshipStage(stage_str)
        stage_meta = STAGE_METADATA.get(stage_enum, {})
        stage_label = stage_meta.get("label", stage_str)
        stage_color = stage_meta.get("color", "#C4C4C4")
        stage_icon = stage_meta.get("icon", "")
    except ValueError:
        stage_label = stage_str
        stage_color = "#C4C4C4"
        stage_icon = ""

    # 4. Strength score & label
    raw_score = data.get("strength_score", 0)
    score = int(raw_score) if isinstance(raw_score, (int, float)) else 0
    label_str, _label_color = _strength_label(score)

    # 5. Last interaction summary
    li_data = data.get("last_interaction", {})
    last_interaction_date = li_data.get("date") if isinstance(li_data, dict) else None
    last_interaction_summary = None
    if isinstance(li_data, dict):
        last_interaction_summary = (
            li_data.get("summary") or li_data.get("title") or None
        )

    # 6. Interaction frequency summary
    freq_data = data.get("interaction_freq", {})
    interaction_freq_summary = None
    if isinstance(freq_data, dict) and freq_data.get("total_count") is not None:
        interaction_freq_summary = (
            f"近30天互动{freq_data.get('last_30_days', 0)}次"
        )

    # 7. Build 12 modules list
    modules: list[BriefModuleItem] = []
    for module_key in _MODULE_META:
        display_name, icon, _default_prio = _MODULE_META[module_key]
        has_data = _module_has_meaningful_data(module_key, data)
        priority = _compute_module_priority(module_key, data)
        summary = _summarize_module(module_key, data)
        detail = data.get(module_key)

        modules.append(
            BriefModuleItem(
                module_name=module_key,
                display_name=display_name,
                icon=icon,
                has_data=has_data,
                summary=summary,
                detail=detail if has_data else None,
                priority=priority,
            )
        )

    # 8. Suggested actions (top 3 from next_actions)
    next_acts = data.get("next_actions", [])
    suggested_actions: list[str] = []
    if isinstance(next_acts, list):
        for act in next_acts[:3]:
            if isinstance(act, dict):
                suggested_actions.append(act.get("action", ""))
            elif isinstance(act, str):
                suggested_actions.append(act)
    suggested_actions = [a for a in suggested_actions if a]

    return RelationshipBriefAggregatedResponse(
        id=brief.id,
        person_entity_id=brief.person_entity_id,
        person_name=person_name,
        person_company=person_company,
        relationship_stage=brief.relationship_stage,
        stage_label=stage_label,
        stage_color=stage_color,
        stage_icon=stage_icon,
        strength_score=score,
        strength_label=label_str,
        last_interaction_date=last_interaction_date,
        last_interaction_summary=last_interaction_summary,
        interaction_freq_summary=interaction_freq_summary,
        modules=modules,
        suggested_actions=suggested_actions,
        version=brief.version,
        last_updated_at=brief.last_updated_at,
    )


@router.get(
    "/relationship-briefs",
    response_model=PaginatedResponse[RelationshipBriefResponse],
)
async def list_relationship_briefs(
    stage: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
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
    user_id: str = Depends(get_current_user_id),
) -> Any:
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
        raise NotFoundError("RelationshipBrief not found or access denied")

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
            raise ConflictError(str(exc))
        raise ValidationError(str(exc))

    await session.refresh(updated)

    logger.info(
        "relationship_brief_updated",
        brief_id=str(brief_id),
        version=updated.version,
    )

    return RelationshipBriefResponse.model_validate(updated)

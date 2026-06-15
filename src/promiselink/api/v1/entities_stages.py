"""Entity stage-related API endpoints (F-G2: Relationship Stage)."""

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import NotFoundError
from promiselink.core.logging import get_logger
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.entities_stages")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])


# ── Pydantic Models ──


class StageSuggestion(BaseModel):
    target_stage: str = ""
    target_stage_label: str = ""
    target_stage_color: str = ""
    reason: str = ""
    action_hint: str = ""
    requires_confirmation: bool = False


class StageInfoResponse(BaseModel):
    entity_id: str
    name: str
    current_stage: str
    current_stage_label: str
    current_stage_color: str
    current_stage_desc: str
    stage_order: int
    suggestion: StageSuggestion | None = None


class StageMapItem(BaseModel):
    value: str
    label: str
    color: str
    icon: str
    description: str
    order: int


class StageMapResponse(BaseModel):
    stages: list[StageMapItem]


def _build_action_hint(target_stage: str, reason: str) -> str:
    hints = {
        "understanding_needs": "安排一次深入交流，了解对方的业务痛点和需求",
        "value_response": "寻找机会为对方提供帮助或价值，如分享资源、介绍人脉",
        "deep_trust": "继续保持高频互动，在关键节点主动提供支持",
        "active_cooperation": "探讨正式合作的可能性，明确双方可交换的价值",
        "long_term_partner": "维护长期伙伴关系，定期互访和信息同步",
        "dormant": "建议通过沉睡联系人活化功能重新建立联系",
    }
    return hints.get(target_stage, f"考虑将关系推进到：{reason}")


@router.get("/entities/stage-map", response_model=StageMapResponse)
async def get_stage_map() -> StageMapResponse:
    """F-G2: Return all 7 relationship stages as a roadmap."""
    from promiselink.services.relationship_stage import RelationshipStageMachine
    raw_stages = RelationshipStageMachine.get_all_stages()
    stages = [StageMapItem(**s) for s in raw_stages]
    return StageMapResponse(stages=stages)


@router.get("/entities/{entity_id}/stage-info", response_model=StageInfoResponse)
async def get_stage_info(
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> StageInfoResponse:
    """F-G2: Get entity's current relationship stage and transition suggestion."""
    from promiselink.services.relationship_stage import (
        STAGE_METADATA,
        RelationshipStage,
        RelationshipStageMachine,
    )
    entity_q = select(Entity).where(
        Entity.id == str(entity_id), Entity.user_id == user_id
    )
    result = await session.execute(entity_q)
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError(f"Entity {entity_id} not found")

    props = entity.properties or {}
    stage_val = props.get("relationship_stage", "new_connection")
    stage_enum = None
    for s in RelationshipStage:
        if s.value == stage_val:
            stage_enum = s
            break
    if stage_enum and stage_enum in STAGE_METADATA:
        meta = dict(STAGE_METADATA[stage_enum])
    else:
        meta = {
            "label": stage_val, "color": "#C4C4C4",
            "description": "", "order": 0,
        }

    interaction_data: dict = {}

    # Use entity's source_event_id + todos for interaction data
    source_evt_q = select(Event.created_at).select_from(Event).where(
        Event.user_id == user_id, Event.id == entity.source_event_id
    )
    source_dt = (await session.execute(source_evt_q)).scalar()
    if source_dt:
        interaction_data["last_interaction_date"] = source_dt

    # Count todos as interaction evidence
    todo_count_q = select(func.count()).select_from(Todo).where(
        Todo.user_id == user_id, Todo.related_entity_id == str(entity_id)
    )
    interaction_data["value_exchange_count"] = (
        (await session.execute(todo_count_q)).scalar() or 0
    )

    care_q = select(func.count()).select_from(Todo).where(
        Todo.user_id == user_id,
        Todo.related_entity_id == str(entity_id),
        Todo.todo_type == "care",
    )
    interaction_data["care_todo_count"] = (
        (await session.execute(care_q)).scalar() or 0
    )

    machine = RelationshipStageMachine()
    current_stage = stage_enum or RelationshipStage.NEW_CONNECTION
    suggestion_result = machine.suggest_transition(current_stage, interaction_data)

    suggestion = None
    if suggestion_result:
        target_meta = dict(
            STAGE_METADATA.get(suggestion_result.current_stage, {})
        )
        suggestion = StageSuggestion(
            target_stage=suggestion_result.current_stage.value,
            target_stage_label=target_meta.get("label", ""),
            target_stage_color=target_meta.get("color", "#C4C4C4"),
            reason=suggestion_result.reason,
            action_hint=_build_action_hint(
                suggestion_result.current_stage.value,
                suggestion_result.reason,
            ),
            requires_confirmation=suggestion_result.requires_confirmation,
        )

    return StageInfoResponse(
        entity_id=str(entity_id),
        name=entity.name,
        current_stage=stage_val,
        current_stage_label=meta.get("label", stage_val),
        current_stage_color=meta.get("color", "#C4C4C4"),
        current_stage_desc=meta.get("description", ""),
        stage_order=meta.get("order", 0),
        suggestion=suggestion,
    )

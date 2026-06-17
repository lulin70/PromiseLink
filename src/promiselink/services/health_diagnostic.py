"""F-G1: Relationship Health Diagnostic Service.

Computes a 0-100 health score for each entity based on:
  - Stage progression (30%)
  - Interaction frequency (25%)
  - Recency (20%)
  - Promise health (15%)
  - Todo density (10%)

Source: brainstorm-ai-usecases #6 (Quick Win 3.50/2.25).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.relationship_stage import (
    STAGE_METADATA,
    RelationshipStage,
)

# ── Health Score Constants ──

_STAGE_ORDER = {
    RelationshipStage.NEW_CONNECTION.value: 1,
    RelationshipStage.UNDERSTANDING_NEEDS.value: 2,
    RelationshipStage.VALUE_RESPONSE.value: 3,
    RelationshipStage.DEEP_TRUST.value: 4,
    RelationshipStage.ACTIVE_COOPERATION.value: 5,
    RelationshipStage.LONG_TERM_PARTNER.value: 6,
    RelationshipStage.DORMANT.value: 7,
}

_SUGGESTION_TEMPLATES = [
    ("new_connection", lambda d: "刚认识不久，建议安排一次深入交流，了解对方业务痛点"),
    ("understanding_needs", lambda d: f"已了解需求但超过{min(d,999)}天未联系，建议跟进近况或分享有价值信息" if d > 14 else "已了解对方需求，可考虑提供价值或深化交流"),
    ("value_response", lambda d: "有过价值交换，可考虑深化合作或请求引荐"),
    ("dormant", lambda d: "关系已沉寂，建议参考沉睡联系人活化建议"),
]


def _get_stage_order(stage_val: str) -> int:
    return _STAGE_ORDER.get(stage_val, 1)


def _get_stage_metadata(stage_val: str) -> dict[str, Any]:
    stage = None
    for s in RelationshipStage:
        if s.value == stage_val:
            stage = s
            break
    if stage:
        return dict(STAGE_METADATA.get(stage, {}))
    return {"label": stage_val or "未知", "color": "#C4C4C4", "order": 0}


def compute_health_score(
    stage_val: str | None,
    interaction_count: int,
    days_since_last: int | None,
    has_overdue_promise: bool,
    has_pending_promise: bool,
    pending_todo_count: int,
) -> tuple[float, str]:
    """Compute health score and return (score, level).

    Args:
        stage_val: Current relationship_stage value.
        interaction_count: Total events/todos for this entity.
        days_since_last: Days since last interaction (None = never).
        has_overdue_promise: Whether there are overdue promises.
        has_pending_promise: Whether there are non-overdue pending promises.
        pending_todo_count: Number of incomplete todos.

    Returns:
        (health_score_0_100, health_level_string)
    """
    # 1. Stage weight (30%): higher stage = higher score
    order = _get_stage_order(stage_val or "new_connection")
    stage_score = (order / 7.0) * 100

    # 2. Interaction frequency (25%)
    interaction_score = min(100.0, float(interaction_count) * 8)

    # 3. Recency (20%)
    if days_since_last is None:
        recency_score = 30.0  # Never interacted
    elif days_since_last <= 7:
        recency_score = 100.0
    elif days_since_last <= 30:
        recency_score = 60.0
    elif days_since_last <= 90:
        recency_score = 30.0
    else:
        recency_score = 0.0

    # 4. Promise health (15%)
    if has_overdue_promise:
        promise_score = 40.0
    elif has_pending_promise:
        promise_score = 100.0
    else:
        promise_score = 70.0  # No promises is neutral

    # 5. Todo density (10%): fewer pending = better
    todo_score = max(0.0, 100.0 - float(pending_todo_count) * 10)

    # Weighted total
    total = (
        stage_score * 0.30 +
        interaction_score * 0.25 +
        recency_score * 0.20 +
        promise_score * 0.15 +
        todo_score * 0.10
    )

    # Level classification
    if total >= 70:
        level = "healthy"
    elif total >= 40:
        level = "attention"
    else:
        level = "at_risk"

    return round(total, 1), level


def generate_suggestion(stage_val: str | None, days_since_last: int | None) -> str:
    """Generate a management suggestion based on stage and recency."""
    stage = stage_val or "new_connection"
    d = days_since_last or 999

    for tpl_stage, tpl_fn in _SUGGESTION_TEMPLATES:
        if stage == tpl_stage:
            return tpl_fn(d)

    return "保持当前节奏，关注待办事项的按时完成"


async def scan_all_entity_health(
    session: AsyncSession,
    user_id: str,
    limit: int = 20,
) -> list[dict]:
    """Scan all person entities and compute health scores.

    Returns a list of dicts with health data for each entity.
    """
    today = date.today()

    # Get all person entities for this user (active or confirmed)
    entity_q = select(Entity).where(
        Entity.user_id == user_id,
        Entity.entity_type == "person",
        Entity.status.in_(["provisional", "confirmed"]),
    ).order_by(Entity.created_at.desc())
    entity_result = await session.execute(entity_q)
    entities = entity_result.scalars().all()

    items = []
    for entity in entities:
        entity_id = str(entity.id)

        # Count ALL events that produced this entity or its merged sources.
        # Primary: events where this entity was extracted (via source_event_id).
        # Secondary: count todos as interaction proxy (todos = actions taken).
        event_count_q = select(func.count()).select_from(Event).where(
            Event.user_id == user_id,
            Event.id == entity.source_event_id,
        )
        primary_event_count = (await session.execute(event_count_q)).scalar() or 0

        # Also count todos as interaction evidence (broader measure)
        all_todo_q = select(func.count()).select_from(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
        )
        total_todos = (await session.execute(all_todo_q)).scalar() or 0

        # Interaction count = direct events + todos (actions = interactions)
        event_count = primary_event_count + total_todos

        # Count todos for this entity
        todo_q = select(func.count()).select_from(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
            Todo.status != "completed",
            Todo.status != "dismissed",
        )
        pending_todos = (await session.execute(todo_q)).scalar() or 0

        # Count pending promises (my_promise + their_promise, not fulfilled/overdue)
        promise_q = select(func.count()).select_from(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
            Todo.action_type.in_(["my_promise", "their_promise"]),
            Todo.status.not_in(["completed", "dismissed"]),
        )
        pending_promises = (await session.execute(promise_q)).scalar() or 0

        # Check for overdue promises
        overdue_q = select(func.count()).select_from(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
            Todo.action_type.in_(["my_promise", "their_promise"]),
            Todo.fulfillment_status == "overdue",
        )
        has_overdue = ((await session.execute(overdue_q)).scalar() or 0) > 0

        # Last interaction date: use max of (entity's source event, latest todo)
        # Method 1: Check the event that created this entity
        last_event_q = select(Event.created_at).select_from(Event).where(
            Event.user_id == user_id,
            Event.id == entity.source_event_id,
        )
        source_event_time = (await session.execute(last_event_q)).scalar()

        # Method 2: Check latest todo for this entity (more comprehensive)
        last_todo_q = select(func.max(Todo.created_at)).select_from(Todo).where(
            Todo.user_id == user_id,
            Todo.related_entity_id == entity_id,
        )
        last_todo_time = (await session.execute(last_todo_q)).scalar()

        # Use the more recent of the two
        last_interaction_dt = None
        if source_event_time and last_todo_time:
            last_interaction_dt = max(source_event_time, last_todo_time)
        elif source_event_time:
            last_interaction_dt = source_event_time
        elif last_todo_time:
            last_interaction_dt = last_todo_time
        else:
            # Fallback to entity's own updated_at
            last_interaction_dt = entity.updated_at

        days_since = None
        if last_interaction_dt:
            if isinstance(last_interaction_dt, datetime):
                last_date = last_interaction_dt.date()
            else:
                last_date = last_interaction_dt
            days_since = (today - last_date).days

        # Get stage from properties or default
        props = entity.properties or {}
        stage_val = props.get("relationship_stage", "new_connection")

        # Compute health score
        health_score, health_level = compute_health_score(
            stage_val=stage_val,
            interaction_count=event_count,
            days_since_last=days_since,
            has_overdue_promise=has_overdue,
            has_pending_promise=pending_promises > 0,
            pending_todo_count=pending_todos,
        )

        # Stage metadata
        stage_meta = _get_stage_metadata(stage_val)

        # Suggestion
        suggestion = generate_suggestion(stage_val, days_since)

        # Company from properties
        company = None
        basic = props.get("basic", {})
        if isinstance(basic, dict):
            company = basic.get("company")

        items.append({
            "entity_id": entity_id,
            "name": entity.name,
            "company": company,
            "stage": stage_val,
            "stage_label": stage_meta.get("label", stage_val),
            "stage_color": stage_meta.get("color", "#C4C4C4"),
            "health_score": health_score,
            "health_level": health_level,
            "interaction_count": event_count,
            "last_interaction": last_interaction_dt.isoformat() if last_interaction_dt else None,
            "days_since_last": days_since,
            "pending_todos": pending_todos,
            "pending_promises": pending_promises,
            "suggestion": suggestion,
        })

    # Sort by health_score descending
    items.sort(key=lambda x: x["health_score"], reverse=True)

    return items[:limit]

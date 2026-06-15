"""Dormant Contact Scanner (F-E3) — identifies and scores contacts needing reactivation.

Scans all person entities, calculates last interaction time, filters by
dormancy threshold, and computes reactivation potential score.

Simplified 3-dimension scoring (per PRD risk mitigation):
  1. Relationship depth (40%): historical events + promise interactions
  2. Time decay (35%): days since last interaction (60-day baseline)
  3. Resource signal (25%): pending their_promises + cooperation signals
"""

from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

# Beijing timezone
_TZ_CN = timezone(timedelta(hours=8))


class DormantContactResult:
    """Result item for a dormant contact."""

    def __init__(
        self,
        entity_id: str,
        name: str,
        company: str | None,
        dormant_days: int,
        reactivation_score: float,
        last_interaction: str | None,
        last_event_summary: str | None,
        reason: str,
        icebreaker_topic: str,
        pending_their_promises: int = 0,
        relationship_stage: str = "unknown",
    ):
        self.entity_id = entity_id
        self.name = name
        self.company = company
        self.dormant_days = dormant_days
        self.reactivation_score = reactivation_score
        self.last_interaction = last_interaction
        self.last_event_summary = last_event_summary
        self.reason = reason
        self.icebreaker_topic = icebreaker_topic
        self.pending_their_promises = pending_their_promises
        self.relationship_stage = relationship_stage

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "company": self.company,
            "dormant_days": self.dormant_days,
            "reactivation_score": round(self.reactivation_score, 1),
            "last_interaction": self.last_interaction,
            "last_event_summary": self.last_event_summary,
            "reason": self.reason,
            "icebreaker_topic": self.icebreaker_topic,
            "pending_their_promises": self.pending_their_promises,
            "relationship_stage": self.relationship_stage,
        }


def _extract_company(properties: dict | None) -> str | None:
    """Extract company name from entity properties."""
    if not properties:
        return None
    basic = properties.get("basic", {})
    if isinstance(basic, dict):
        return basic.get("company")
    return None


def _extract_concerns(properties: dict | None) -> list[str]:
    """Extract concerns from entity properties."""
    if not properties:
        return []
    # Concern can be at top level or nested
    concern = properties.get("concern")
    if isinstance(concern, str):
        return [concern]
    if isinstance(concern, list):
        return concern
    return []


async def scan_dormant_contacts(
    session: AsyncSession,
    user_id: str,
    limit: int = 10,
    offset: int = 0,
    min_days: int = 60,
) -> tuple[list[DormantContactResult], int]:
    """Scan for dormant person contacts and score reactivation potential.

    Args:
        session: Database session.
        user_id: User ID for data isolation.
        limit: Max results to return.
        offset: Number of results to skip.
        min_days: Minimum days since last interaction to qualify as dormant.

    Returns:
        Tuple of (items, total_count) where items is sorted by
        reactivation_score descending and total_count is the total
        number of dormant contacts (before limit/offset).
    """
    today = datetime.now(_TZ_CN).date()

    # Step 1: Get all person entities for this user
    entity_result = await session.execute(
        select(Entity)
        .where(Entity.user_id == user_id, Entity.entity_type == "person")
        .order_by(Entity.created_at.desc())
    )
    entities = list(entity_result.scalars().all())

    if not entities:
        return [], 0

    results: list[DormantContactResult] = []
    entity_ids = [e.id for e in entities]

    # Step 2: Get last interaction per entity via source_event_id + todos
    # Event model has no entity_id or related_entity_ids field
    # Use: Entity.source_event_id → Event, and Todo.related_entity_id → latest todo
    all_events = []  # Simplified: use entity's own data instead

    # Group events by entity_id to find latest per entity
    entity_events: dict[str, tuple[datetime, str, str | None]] = {}
    for evt in all_events:
        eid = evt[0]  # entity_id stored in event (if applicable)
        # Also check raw_text for entity name mentions
        if eid and eid not in entity_events:
            entity_events[eid] = (evt[1], evt[2], evt[3])

    # Step 3: Count todos per entity (for relationship depth)
    todo_count_q = (
        select(Todo.related_entity_id, func.count())
        .where(Todo.user_id == user_id, Todo.related_entity_id.in_(entity_ids))
        .group_by(Todo.related_entity_id)
    )
    todo_counts = dict((await session.execute(todo_count_q)).all())

    # Count pending their_promises per entity
    promise_q = (
        select(Todo.related_entity_id, func.count())
        .where(
            Todo.user_id == user_id,
            Todo.related_entity_id.in_(entity_ids),
            Todo.action_type == "their_promise",
            Todo.fulfillment_status == "pending",
        )
        .group_by(Todo.related_entity_id)
    )
    promise_counts = dict((await session.execute(promise_q)).all())

    # Step 4: Score each entity
    for entity in entities:
        eid_str = str(entity.id)

        # Find last interaction time
        last_event = entity_events.get(eid_str)
        last_time: datetime | None = None
        last_title = ""
        last_raw = ""

        if last_event:
            last_time = last_event[0]
            last_title = last_event[1]
            last_raw = last_event[2] or ""

        # If no event found via entity_events, check entity's own created_at as fallback
        if not last_time:
            # Try to find any event mentioning this entity's name
            name_matches = [
                e for e in all_events
                if e[2] and entity.name in e[2]
            ]
            if name_matches:
                last_time = name_matches[0][0]
                last_title = name_matches[0][1]
                last_raw = name_matches[0][2] or ""
            else:
                last_time = entity.created_at

        # Calculate dormant days
        try:
            last_date = last_time.date() if hasattr(last_time, 'date') else last_time
        except (ValueError, AttributeError):
            last_date = today

        dormant_days = (today - last_date).days

        # Skip if not dormant enough
        if dormant_days < min_days:
            continue

        # ── Scoring (simplified 3-dimension model) ──

        # Dimension 1: Relationship depth (40%)
        total_todos = todo_counts.get(eid_str, 0)
        depth_score = min(100, total_todos * 15)  # ~7 events = max

        # Dimension 2: Time decay (35%)
        # 60 days = full points, linear decay after
        if dormant_days <= 60:
            decay_score = 100
        elif dormant_days <= 180:
            decay_score = 100 - ((dormant_days - 60) / 120) * 50  # 100→50 over 60-180 days
        else:
            decay_score = max(20, 50 - ((dormant_days - 180) / 180) * 30)  # 50→20 over 180-360 days

        # Dimension 3: Resource/recent signal (25%)
        pending_promises = promise_counts.get(eid_str, 0)
        signal_score = min(100, pending_promises * 33 + (1 if total_todos > 3 else 0) * 20)

        # Weighted total
        reactivation_score = (
            depth_score * 0.40 +
            decay_score * 0.35 +
            signal_score * 0.25
        )

        # Generate reason text
        company = _extract_company(entity.properties)
        concerns = _extract_concerns(entity.properties)

        reason_parts = []
        if total_todos >= 5:
            reason_parts.append(f"曾深度互动({total_todos}次)")
        elif total_tools := total_todos > 0:
            reason_parts.append(f"有{total_todos}次互动记录")
        if pending_promises > 0:
            reason_parts.append(f"对方有{pending_promises}条未兑现承诺")
        if concerns:
            reason_parts.append(f"关心{concerns[0][:10]}")

        reason = "，".join(reason_parts) if reason_parts else "值得重新建立联系"

        # Generate icebreaker topic
        icebreaker = _generate_icebreaker(
            entity.name,
            last_title or last_raw[:50] if last_raw else "",
            concerns,
            dormant_days,
        )

        # Determine relationship stage from properties
        rel_stage = "unknown"
        if entity.properties and isinstance(entity.properties, dict):
            rel = entity.properties.get("relationship", {})
            if isinstance(rel, dict):
                rel_stage = rel.get("stage", "unknown")

        results.append(DormantContactResult(
            entity_id=eid_str,
            name=entity.name,
            company=company,
            dormant_days=dormant_days,
            reactivation_score=reactivation_score,
            last_interaction=last_time.isoformat() if last_time else None,
            last_event_summary=last_title or None,
            reason=reason,
            icebreaker_topic=icebreaker,
            pending_their_promises=pending_promises,
            relationship_stage=rel_stage,
        ))

    # Sort by score descending
    results.sort(key=lambda r: r.reactivation_score, reverse=True)
    total_count = len(results)
    return results[offset:offset + limit], total_count


def _generate_icebreaker(
    name: str,
    last_topic: str,
    concerns: list[str],
    days_ago: int,
) -> str:
    """Generate a simple icebreaker opening line (non-LLM fallback).

    For PoC, uses template-based generation without LLM dependency.
    Phase 2 should integrate LLM-based generation.
    """
    templates = []

    # Based on concerns
    if concerns:
        concern_text = concerns[0][:15] if len(concerns[0]) > 15 else concerns[0]
        templates.append(f"{name}，最近在{concern_text}方面有什么进展吗？")

    # Based on time elapsed
    if days_ago < 90:
        templates.append(f"{name}，好久不见！最近一切都好吧？")
    elif days_ago < 180:
        templates.append(f"{name}，几个月没联系了，最近怎么样？")
    else:
        templates.append(f"{name}，很久没聊了，想起之前交流过，问候一下")

    # Based on last topic
    if last_topic and len(last_topic) > 4:
        templates.append(f"{name}，上次聊到{last_topic[:10]}，不知后来情况如何？")

    # Default
    templates.append(f"{name}，好久不见！有空的话约个时间聊聊？")

    # Return first non-empty template (prioritizes concern-based)
    for t in templates:
        if t:
            return t

    return f"{name}，好久不见！"

"""F-50: Voice Query Service — data retrieval for voice query intents.

Handles the actual database queries for each query intent type:
  - schedule_query: Query Event table for today/tomorrow's meeting/call events
  - promise_query: Query Todo table for pending promise/care type todos
  - relationship_query: Query Entity + Association + RelationshipBrief

PRD v4.4 F-50 Phase 1.1
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.models.todo import Todo
from eventlink.services.nlu_intent_classifier import VoiceIntent

# Beijing timezone
_TZ_CN = timezone(timedelta(hours=8))


async def query_schedule(
    session: AsyncSession, user_id: str, slots: dict
) -> dict[str, Any]:
    """Query events for schedule_query intent.

    Returns events for the date specified in slots (defaults to today).
    Filters by event_type meeting/call.
    """
    today = datetime.now(_TZ_CN).date()
    date_str = slots.get("date", today.isoformat())

    try:
        target_date = datetime.fromisoformat(date_str).date()
    except (ValueError, TypeError):
        target_date = today

    day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=_TZ_CN)
    day_end = day_start + timedelta(days=1)

    result = await session.execute(
        select(Event)
        .where(Event.user_id == user_id)
        .where(Event.event_type.in_(["meeting", "call"]))
        .where(Event.timestamp >= day_start)
        .where(Event.timestamp < day_end)
        .order_by(Event.timestamp.asc())
    )
    events = list(result.scalars().all())

    events_data = []
    for evt in events:
        t = evt.timestamp.astimezone(_TZ_CN).strftime("%H:%M") if evt.timestamp else "??:??"
        events_data.append({
            "id": str(evt.id),
            "title": evt.title,
            "event_type": evt.event_type,
            "time": t,
            "timestamp": evt.timestamp.isoformat() if evt.timestamp else None,
        })

    return {"events": events_data, "date": date_str, "count": len(events_data)}


async def query_promises(
    session: AsyncSession, user_id: str, slots: dict
) -> dict[str, Any]:
    """Query pending promise/care todos for promise_tracker intent.

    Optionally filters by person name from slots.
    """
    person_name = slots.get("person", "")

    query = select(Todo).where(
        Todo.user_id == user_id,
        Todo.todo_type.in_(["promise", "care"]),
        Todo.status.in_(["pending", "in_progress"]),
    )
    if person_name:
        query = query.where(Todo.title.contains(person_name))

    result = await session.execute(query.order_by(Todo.priority.asc(), Todo.created_at.asc()))
    todos = list(result.scalars().all())

    todos_data = []
    for t in todos:
        todos_data.append({
            "id": str(t.id),
            "title": t.title,
            "todo_type": t.todo_type,
            "status": t.status,
            "priority": t.priority,
            "due_date": t.due_date.isoformat() if t.due_date else None,
        })

    return {"todos": todos_data, "person": person_name or None, "count": len(todos_data)}


async def query_relationship(
    session: AsyncSession, user_id: str, slots: dict
) -> dict[str, Any]:
    """Query relationship status for relationship_status intent.

    Queries Entity + RelationshipBrief + Association data.
    Optionally filters by person name from slots.
    """
    person_name = slots.get("person", "")

    # Query relationship briefs
    briefs_result = await session.execute(
        select(RelationshipBrief)
        .where(RelationshipBrief.user_id == user_id)
        .order_by(RelationshipBrief.last_updated_at.desc())
    )
    all_briefs = list(briefs_result.scalars().all())

    # Match by person name if provided
    matched_briefs = []
    if person_name:
        for b in all_briefs:
            bname = (b.brief_data or {}).get("basic_info", {}).get("name", "")
            if person_name in bname or bname in person_name:
                matched_briefs.append(b)
    else:
        matched_briefs = all_briefs[:5]

    relationships_data = []
    for brief in matched_briefs:
        # Get entity info
        entity_result = await session.execute(
            select(Entity).where(Entity.id == brief.person_entity_id)
        )
        entity = entity_result.scalar_one_or_none()

        # Get associations for this entity
        assoc_result = await session.execute(
            select(Association).where(
                Association.user_id == user_id,
                (Association.source_entity_id == brief.person_entity_id)
                | (Association.target_entity_id == brief.person_entity_id),
            )
        )
        associations = list(assoc_result.scalars().all())

        data = brief.brief_data or {}
        name = data.get("basic_info", {}).get("name", person_name or "对方")

        relationships_data.append({
            "person_entity_id": str(brief.person_entity_id),
            "name": name,
            "relationship_stage": brief.relationship_stage,
            "strength_score": data.get("strength_score"),
            "last_interaction": data.get("last_interaction", {}).get("summary", "")[:100] if data.get("last_interaction") else None,
            "entity_name": entity.name if entity else None,
            "association_count": len(associations),
            "last_updated_at": brief.last_updated_at.isoformat() if brief.last_updated_at else None,
        })

    return {"relationships": relationships_data, "person": person_name or None, "count": len(relationships_data)}


async def execute_query(
    session: AsyncSession, user_id: str, intent: VoiceIntent, slots: dict
) -> dict[str, Any]:
    """Dispatch query based on intent type and return structured data.

    Args:
        session: DB session.
        user_id: User ID for data isolation.
        intent: Classified NLU intent.
        slots: Extracted slots (person name, date, etc.).

    Returns:
        Dict with query-specific data structure.
    """
    if intent == VoiceIntent.SCHEDULE_QUERY:
        return await query_schedule(session, user_id, slots)
    elif intent == VoiceIntent.PROMISE_TRACKER:
        return await query_promises(session, user_id, slots)
    elif intent == VoiceIntent.RELATIONSHIP_STATUS:
        return await query_relationship(session, user_id, slots)
    else:
        return {}

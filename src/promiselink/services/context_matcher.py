"""ContextMatcher — Event-driven context matching for Todo priority scoring.

Implements F-56: Context dimension for Phase 1 four-dimensional priority model.
Boosts Todo priority when the related person has an upcoming meeting/call.

Design reference: PromiseLink_技术设计_v1.md v2.7 §4.10.1a
"""

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

logger = get_logger("promiselink.context_matcher")


class ContextMatcher:
    """Match Todos to upcoming events for context-aware priority boosting.

    Phase 1: Event table driven
    - Scan upcoming meeting/call events (next 24h)
    - Match related Entities to pending Todos
    - Linear decay: closer events = higher score

    Score formula: context_score = max(0, 1 - hours_until_meeting / 24)
    """

    CONTEXT_WINDOW_HOURS = 24  # Look-ahead window

    async def compute_context_score(self, todo: Todo, session: AsyncSession) -> float:
        """Compute context match score for a Todo (0.0 ~ 1.0).

        Todos without a related_entity_id return 0.0.

        Args:
            todo: The Todo to score
            session: AsyncSession for DB queries

        Returns:
            Context match score between 0.0 and 1.0
        """
        if not todo.related_entity_id:
            return 0.0

        now = datetime.now(UTC)

        # Step 1: Find upcoming meeting/call events in the next 24h
        # We look for events with event_type meeting/call that were recently created
        # and have entities associated with them
        window_start = now - timedelta(hours=1)  # Allow slight lookback
        window_end = now + timedelta(hours=self.CONTEXT_WINDOW_HOURS)

        result = await session.execute(
            select(Event).where(
                Event.user_id == todo.user_id,
                Event.event_type.in_(["meeting", "call"]),
            )
        )
        all_events = result.scalars().all()

        # Filter to recent/upcoming events
        upcoming_events = []
        for e in all_events:
            # Use created_at as proxy for event timing
            # In Phase 2, we'll have a proper scheduled_at field
            if not e.created_at:
                continue
            # Normalize to offset-aware UTC for comparison
            evt_time = e.created_at
            if evt_time.tzinfo is None:
                evt_time = evt_time.replace(tzinfo=UTC)
            if window_start <= evt_time <= window_end:
                upcoming_events.append(e)

        if not upcoming_events:
            return 0.0

        # Step 2: Find entities associated with these events
        event_ids = [str(e.id) for e in upcoming_events]
        result = await session.execute(
            select(Entity).where(
                Entity.source_event_id.in_(event_ids),
            )
        )
        upcoming_entities = cast(list[Entity], result.scalars().all())

        # Step 3: Check if Todo's related entity is in upcoming list
        todo_entity_id = str(todo.related_entity_id)
        matching_entity: Entity | None = None
        matching_event: Event | None = None

        for entity in upcoming_entities:
            if str(entity.id) == todo_entity_id:
                matching_entity = entity
                # Find the event this entity came from
                for e in upcoming_events:
                    if str(entity.source_event_id) == str(e.id):
                        matching_event = e
                        break
                break

        if not matching_entity or not matching_event:
            return 0.0

        # Step 4: Compute context score based on time until event
        if matching_event.created_at:
            evt_time = matching_event.created_at
            if evt_time.tzinfo is None:
                evt_time = evt_time.replace(tzinfo=UTC)
            hours_until = max(
                0, (evt_time - now).total_seconds() / 3600
            )
        else:
            hours_until = self.CONTEXT_WINDOW_HOURS

        # Linear decay: closer = higher score
        context_score = max(0.0, 1.0 - hours_until / self.CONTEXT_WINDOW_HOURS)

        logger.debug(
            "context_score_computed",
            todo_id=str(todo.id),
            score=context_score,
            hours_until=round(hours_until, 2),
            entity_name=matching_entity.name,
        )

        return round(context_score, 4)

    async def get_upcoming_context(
        self, user_id: str, session: AsyncSession
    ) -> list[dict]:
        """Get upcoming context information for a user.

        Useful for dashboard display and proactive suggestions.

        Args:
            user_id: User ID
            session: AsyncSession

        Returns:
            List of dicts with event, entity, and hours_until info
        """
        now = datetime.now(UTC)
        window_end = now + timedelta(hours=self.CONTEXT_WINDOW_HOURS)

        result = await session.execute(
            select(Event).where(
                Event.user_id == user_id,
                Event.event_type.in_(["meeting", "call"]),
            )
        )
        all_events = result.scalars().all()

        upcoming = []
        for e in all_events:
            if not e.created_at:
                continue
            evt_time = e.created_at
            if evt_time.tzinfo is None:
                evt_time = evt_time.replace(tzinfo=UTC)
            if now <= evt_time <= window_end:
                hours_until = (evt_time - now).total_seconds() / 3600

                # Find associated entities
                result = await session.execute(
                    select(Entity).where(Entity.source_event_id == str(e.id))
                )
                entities: list[Entity] = list(result.scalars().all())

                upcoming.append({
                    "event_id": str(e.id),
                    "event_title": e.title,
                    "event_type": e.event_type,
                    "hours_until": round(hours_until, 2),
                    "entities": [
                        {"id": str(ent.id), "name": ent.name}
                        for ent in entities
                    ],
                })

        return sorted(upcoming, key=lambda x: x["hours_until"])

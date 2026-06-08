"""Step 13: Mark event as completed."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.event import Event
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step13_CompleteEvent(PipelineStep):
    """Mark event as completed."""

    name = "step13_complete_event"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal

        event_id = context.event_id

        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if event:
                    event.status = "completed"
                    event.processed_at = datetime.now(timezone.utc)

        context.result.status = "completed"
        context.result.completed_at = datetime.now(timezone.utc)

        logger.info(
            "pipeline_completed",
            event_id=event_id,
            entity_count=len(context.entities),
            todo_count=len(context.result.todos),
        )

        return context

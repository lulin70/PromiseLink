"""Step 09: Store raw data to memory provider."""

from __future__ import annotations

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.event import Event
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step09_MemoryStorage(PipelineStep):
    """Store raw data to memory provider."""

    name = "step09_memory_storage"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal

        event_id = context.event_id
        entities = context.entities
        extraction = context.extraction
        memory = context.memory

        try:
            # Re-fetch event to get raw_text and metadata
            async with AsyncSessionLocal() as session:
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()

            if event and memory is not None:
                entity_ids = [str(e.id) for e in entities] if entities else []
                await memory.store_raw(
                    event_id=event_id,
                    raw_text=event.raw_text or "",
                    metadata={"event_type": event.event_type, "source": event.source},
                    entity_ids=entity_ids,
                    summary=extraction.summary if extraction else "",
                )
        except Exception as mem_err:  # External API — keep broad catch for resilience
            logger.error(
                "pipeline_memory_failed",
                event_id=event_id,
                error=str(mem_err),
            )
            context.should_stop = True
            context.failed_steps.append(self.name)

        return context

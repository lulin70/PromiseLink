"""Step 04: Todo generation."""

from __future__ import annotations

import time

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step04_TodoGeneration(PipelineStep):
    """Todo generation (LLM call + persist + commit)."""

    name = "step04_todo_generation"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        # Import from event_pipeline to preserve test-patch compatibility
        from eventlink.services.event_pipeline import TodoGenerator

        event_id = context.event_id
        llm_client = context.llm_client
        entities = context.entities

        todos: list[Todo] = []
        async with AsyncSessionLocal() as session:
            generator = TodoGenerator(llm_client=llm_client, session=session)

            db_result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            event = db_result.scalar_one_or_none()
            if not event:
                context.result.status = "failed"
                context.result.error = "Event not found during todo generation"
                context.should_stop = True
                return context

            # Re-fetch entities for this event
            entity_result = await session.execute(
                select(Entity).where(Entity.source_event_id == event.id)
            )
            db_entities = list(entity_result.scalars().all())
            if not db_entities and entities:
                db_entities = entities

            _t4 = time.monotonic()
            todos = await generator.generate_todos(
                event=event,
                entities=db_entities,
            )
            context.result.step_timings["step7_todos"] = time.monotonic() - _t4
            await session.commit()

        context.todos = todos
        context.result.todos = todos

        logger.info(
            "pipeline_todos_done",
            event_id=event_id,
            todos_generated=len(todos),
        )

        return context

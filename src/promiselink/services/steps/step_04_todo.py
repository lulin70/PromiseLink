"""Step 04: Todo generation."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step04_TodoGeneration(PipelineStep):
    """Todo generation (LLM call + persist + commit)."""

    name = "step04_todo_generation"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry

        # Import from event_pipeline to preserve test-patch compatibility
        from promiselink.services.event_pipeline import TodoGenerator

        event_id = context.event_id
        llm_client = context.llm_client
        entities = context.entities
        assert context.result is not None
        assert llm_client is not None

        todos: list[Todo] = []
        try:
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
                context.result.step_timings["step4_todos"] = time.monotonic() - _t4
                await commit_with_retry(session)
        except Exception as todo_err:
            logger.warning("pipeline_todo_generation_failed",
                event_id=event_id, error=str(todo_err))
            context.failed_steps.append(self.name)

        context.todos = todos
        context.result.todos = todos

        logger.info(
            "pipeline_todos_done",
            event_id=event_id,
            todos_generated=len(todos),
        )

        # Track todo generation failure for Step13 partial status
        if len(todos) == 0 and len(context.entities) > 0:
            context.failed_steps.append(self.name)

        return context

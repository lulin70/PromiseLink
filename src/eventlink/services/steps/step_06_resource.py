"""Step 06: Resource overuse detection."""

from __future__ import annotations

import time

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.todo import Todo
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step06_ResourceOveruse(PipelineStep):
    """Resource overuse detection (F-39)."""

    name = "step06_resource_overuse"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.resource_overuse_detector import ResourceOveruseDetector

        event_id = context.event_id

        _t83 = time.monotonic()
        try:
            overuse_detector = ResourceOveruseDetector()
            async with AsyncSessionLocal() as overuse_session:
                overuse_todo_q = await overuse_session.execute(
                    select(Todo).where(Todo.source_event_id == event_id)
                )
                overuse_todos = list(overuse_todo_q.scalars().all())

                checked_entities: set[str] = set()
                for todo in overuse_todos:
                    if (
                        todo.action_type == "their_promise"
                        and todo.related_entity_id
                        and str(todo.related_entity_id) not in checked_entities
                    ):
                        checked_entities.add(str(todo.related_entity_id))
                        try:
                            await overuse_detector.check_and_create_warning_todo(
                                user_id=str(todo.user_id),
                                target_entity_id=str(todo.related_entity_id),
                                source_event_id=event_id,
                                session=overuse_session,
                            )
                        except Exception as overuse_err:
                            logger.warning("pipeline_step8_3_overuse_check_failed",
                                entity_id=str(todo.related_entity_id),
                                error=str(overuse_err))

                await overuse_session.commit()
        except Exception as overuse_init_err:
            logger.warning("pipeline_step8_3_overuse_init_failed", error=str(overuse_init_err))

        context.result.step_timings["step8_3_resource_overuse"] = time.monotonic() - _t83

        logger.info("pipeline_step8_3_resource_overuse", event_id=event_id)

        return context

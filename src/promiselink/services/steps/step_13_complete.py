"""Step 13: Mark event as completed."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.event import Event
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step13_CompleteEvent(PipelineStep):
    """Mark event as completed (or partial if critical steps failed)."""

    name = "step13_complete_event"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal

        event_id = context.event_id
        assert context.result is not None

        # Determine final status based on step failures
        if context.failed_steps:
            final_status = "failed"
            result_status = "failed"
            logger.warning(
                "pipeline_step_failures",
                event_id=event_id,
                failed_steps=context.failed_steps,
            )
        else:
            final_status = "completed"
            result_status = "completed"

        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if event:
                    event.status = final_status
                    event.processed_at = datetime.now(UTC)
                    if context.failed_steps:
                        event.failed_steps = list(context.failed_steps)
                    # Fallback: if title is still default, extract from raw_text
                    if event.title in ("未命名", "untitled", "") and event.raw_text:
                        fallback = event.raw_text.strip().replace("\n", " ")[:20]
                        if fallback:
                            event.title = fallback + ("..." if len(event.raw_text.strip()) > 20 else "")
                            logger.info(
                                "pipeline_title_fallback",
                                event_id=event_id,
                                fallback_title=event.title,
                            )

        context.result.status = result_status
        context.result.completed_at = datetime.now(UTC)
        context.result.failed_steps = list(context.failed_steps)

        logger.info(
            "pipeline_completed",
            event_id=event_id,
            entity_count=len(context.entities),
            todo_count=len(context.result.todos),
            status=result_status,
            failed_steps=context.failed_steps,
        )

        return context

"""Step 05: Promise Bidirectional Analysis + Deduplication."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step05_PromiseAnalysis(PipelineStep):
    """Promise Bidirectional Analysis + Deduplication (F-45 + F-46)."""

    name = "step05_promise_analysis"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.promise_bidirectional import PromiseBidirectionalHandler

        event_id = context.event_id
        llm_client = context.llm_client

        promise_handler = PromiseBidirectionalHandler(llm_client=llm_client)
        async with AsyncSessionLocal() as session:
            # Re-fetch todos that were just generated
            todo_result = await session.execute(
                select(Todo).where(Todo.source_event_id == event_id)
            )
            fresh_todos = list(todo_result.scalars().all())

            # Re-fetch event for evidence extraction
            evt_result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            current_event = evt_result.scalar_one()

            # Re-fetch entities for entity mapping
            ent_result = await session.execute(
                select(Entity).where(Entity.source_event_id == event_id)
            )
            fresh_entities = list(ent_result.scalars().all())

            # Parallel promise bidirectional analysis for all todos
            _t5 = time.monotonic()
            analysis_tasks = [
                promise_handler.analyze_todo(
                    todo=todo,
                    event=current_event,
                    entities=fresh_entities,
                )
                for todo in fresh_todos
            ]
            analysis_results = await asyncio.gather(*analysis_tasks, return_exceptions=True)

            for todo, analysis in zip(fresh_todos, analysis_results):
                if isinstance(analysis, Exception):
                    logger.warning("pipeline_promise_analysis_failed",
                        todo_id=str(todo.id), error=str(analysis))
                    continue
                try:
                    todo.action_type = analysis.action_type.value
                    todo.promisor_id = analysis.promisor_entity_id
                    todo.beneficiary_id = analysis.beneficiary_entity_id
                    todo.confirmation_status = analysis.confirmation_status.value
                    todo.evidence_quote = analysis.evidence_quote
                    todo.evidence_event_id = str(current_event.id) if analysis.evidence_quote else None
                except Exception as apply_err:
                    logger.warning("pipeline_promise_apply_failed",
                        todo_id=str(todo.id), error=str(apply_err))

            context.result.step_timings["step8_promise_analysis"] = time.monotonic() - _t5

            await session.commit()

        context.todos = fresh_todos
        context.result.todos = fresh_todos

        logger.info("pipeline_step8_promise_bidirectional",
            event_id=event_id,
            todos_enriched=len(fresh_todos),
        )

        return context

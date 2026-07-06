"""Step 05: Promise Bidirectional Analysis + Deduplication."""

from __future__ import annotations

import asyncio
import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step05_PromiseAnalysis(PipelineStep):
    """Promise Bidirectional Analysis + Deduplication (F-45 + F-46)."""

    name = "step05_promise_analysis"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry
        from promiselink.services.promise_bidirectional import PromiseBidirectionalHandler

        event_id = context.event_id
        llm_client = context.llm_client
        assert context.result is not None
        assert llm_client is not None

        fresh_todos: list[Todo] = []
        try:
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
                    if isinstance(analysis, BaseException):
                        logger.warning("pipeline_promise_analysis_failed",
                            todo_id=str(todo.id), error=str(analysis))
                        continue
                    try:
                        todo.action_type = analysis.action_type.value
                        todo.promisor_id = analysis.promisor_entity_id
                        todo.beneficiary_id = analysis.beneficiary_entity_id
                        todo.confirmation_status = analysis.confirmation_status.value
                        todo.evidence_quote = analysis.evidence_quote
                        todo.evidence_event_id = current_event.id if analysis.evidence_quote else None
                        # F-68: Initialize fulfillment_status for promise-type todos
                        if analysis.action_type.value in ("my_promise", "their_promise"):
                            todo.fulfillment_status = "pending"
                    except Exception as apply_err:  # Broadened — any apply failure skips this todo, continues loop
                        logger.warning("pipeline_promise_apply_failed",
                            todo_id=str(todo.id), error=str(apply_err))

                context.result.step_timings["step5_promise"] = time.monotonic() - _t5

                await commit_with_retry(session)

            context.todos = fresh_todos
            context.result.todos = fresh_todos
        except Exception as promise_err:  # External API — keep broad catch for resilience
            logger.warning("pipeline_promise_step_failed",
                event_id=event_id, error=str(promise_err))
            context.failed_steps.append(self.name)

        logger.info("pipeline_step8_promise_bidirectional",
            event_id=event_id,
            todos_enriched=len(fresh_todos),
        )

        return context

"""Step 07: Priority scoring."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step07_PriorityScoring(PipelineStep):
    """Phase 1 four-dimensional priority scoring (F-55+F-56)."""

    name = "step07_priority_scoring"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry
        from promiselink.services.priority_scorer import PriorityScorerV2

        event_id = context.event_id

        _t85 = time.monotonic()
        try:
            scorer_v2 = PriorityScorerV2()
            async with AsyncSessionLocal() as score_session:
                score_result_q = await score_session.execute(
                    select(Todo).where(Todo.source_event_id == event_id)
                )
                score_todos = list(score_result_q.scalars().all())
                for todo in score_todos:
                    try:
                        score_result = await scorer_v2.score_with_context(todo, score_session)
                        todo.dynamic_score = score_result.score
                        todo.score_calculated_at = datetime.now(timezone.utc)
                    except Exception as score_err:
                        logger.warning("pipeline_step8_5_score_failed",
                            todo_id=str(todo.id), error=str(score_err))
                await commit_with_retry(score_session)
        except Exception as scorer_err:
            logger.warning("pipeline_step8_5_scorer_init_failed", error=str(scorer_err))
            context.failed_steps.append(self.name)

        context.result.step_timings["step7_priority"] = time.monotonic() - _t85

        logger.info("pipeline_step8_5_priority_scored",
            event_id=event_id,
            todos_scored=len(context.todos),
        )

        return context

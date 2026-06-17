"""Step 12: Relationship Brief Update (F-47 + F-48)."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step12_RelationshipBriefUpdate(PipelineStep):
    """Relationship Brief Update (F-47 + F-48)."""

    name = "step12_relationship_brief_update"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry
        from promiselink.services.relationship_brief_service import RelationshipBriefService

        event_id = context.event_id
        user_id = context.user_id
        llm_client = context.llm_client
        assert context.result is not None
        assert user_id is not None

        _t8 = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                brief_service = RelationshipBriefService(session=session, llm_client=llm_client)

                db_entity_result = await session.execute(
                    select(Entity).where(Entity.source_event_id == event_id)
                )
                db_entities = list(db_entity_result.scalars().all())

                db_todo_result = await session.execute(
                    select(Todo).where(Todo.source_event_id == event_id)
                )
                db_todos = list(db_todo_result.scalars().all())

                # Re-fetch event for brief update
                evt_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = evt_result.scalar_one_or_none()

                if event:
                    for entity in db_entities:
                        if entity.entity_type != "person":
                            continue

                        try:
                            brief_result = await brief_service.update_brief_from_event(
                                user_id=user_id,
                                person_entity_id=str(entity.id),
                                event=event,
                                entities=db_entities,
                                todos=db_todos,
                            )
                            if brief_result.is_new or brief_result.modules_updated:
                                logger.info("pipeline_step13_brief_updated",
                                    entity_id=str(entity.id),
                                    is_new=brief_result.is_new,
                                    modules=brief_result.modules_updated,
                                )
                        except Exception as brief_err:
                            logger.warning("pipeline_brief_update_failed",
                                entity_id=str(entity.id),
                                error=str(brief_err),
                            )

                await commit_with_retry(session)
        except ImportError:
            logger.debug("pipeline_step13_skipped_relationship_brief_not_available")
        except Exception as step13_err:
            logger.warning("pipeline_step13_error", error=str(step13_err))
            context.failed_steps.append(self.name)

        context.result.step_timings["step12_briefs"] = time.monotonic() - _t8

        return context

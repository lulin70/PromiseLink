"""Step 02: Entity extraction + Entity resolution."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step02_ExtractEntities(PipelineStep):
    """Entity extraction + Entity resolution (LLM call + persist + commit)."""

    name = "step02_extract_entities"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal, commit_with_retry
        from promiselink.services.entity_extractor import EntityExtractor
        from promiselink.services.entity_resolution import EntityResolutionEngine

        event_id = context.event_id
        settings = context.settings
        llm_client = context.llm_client

        extraction = None
        entities: list[Entity] = []
        raw_text = ""  # Track raw_text for failure detection
        try:
            async with AsyncSessionLocal() as session:
                resolution_engine = EntityResolutionEngine(
                    session=session,
                    auto_merge_threshold=settings.entity_resolution_auto_merge_threshold,
                    confirm_threshold=settings.entity_resolution_human_review_threshold,
                    llm_client=llm_client,
                )
                extractor = EntityExtractor(
                    llm_client=llm_client,
                    session=session,
                    resolution_engine=resolution_engine,
                )

                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if not event:
                    context.result.status = "failed"
                    context.result.error = "Event not found during extraction"
                    context.should_stop = True
                    return context

                raw_text = event.raw_text or ""  # Save before session closes

                _t3 = time.monotonic()
                extraction = await extractor.extract_from_event(event)
                context.result.step_timings["step2_extract"] = time.monotonic() - _t3
                entities = extraction.persisted_entities
                if not entities:
                    entities = list(
                        (await session.execute(
                            select(Entity).where(Entity.source_event_id == event.id)
                        )).scalars().all()
                    )
                await commit_with_retry(session)
        except Exception as extract_err:
            logger.error("pipeline_extraction_failed",
                event_id=event_id, error=str(extract_err))
            context.should_stop = True
            context.failed_steps.append(self.name)
            return context

        context.extraction = extraction
        context.entities = entities
        context.result.extraction = extraction
        context.result.entities = entities

        # Track merged entity IDs for association discovery
        if extraction and hasattr(extraction, "merged_entity_ids"):
            context.merged_entity_ids = extraction.merged_entity_ids

        logger.info(
            "pipeline_extraction_done",
            event_id=event_id,
            persons_extracted=len(extraction.persons) if extraction else 0,
            entities_persisted=len(entities),
        )

        # Track extraction failure for Step13 partial status
        # Case 1: LLM returned persons but none persisted (persistence failure)
        # Case 2: raw_text was non-empty but LLM extracted 0 persons (LLM failure/degradation)
        if extraction and len(extraction.persons) > 0 and len(entities) == 0:
            context.failed_steps.append(self.name)
        elif (extraction is None or len(extraction.persons) == 0) and len(entities) == 0:
            if raw_text.strip():
                logger.warning(
                    "pipeline_extraction_empty",
                    event_id=event_id,
                    note="raw_text non-empty but 0 persons extracted — LLM may have failed",
                )
                context.failed_steps.append(self.name)

        return context

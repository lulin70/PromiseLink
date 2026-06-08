"""Step 02: Entity extraction + Entity resolution."""

from __future__ import annotations

import time

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step02_ExtractEntities(PipelineStep):
    """Entity extraction + Entity resolution (LLM call + persist + commit)."""

    name = "step02_extract_entities"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        # Import from event_pipeline to preserve test-patch compatibility
        from eventlink.services.event_pipeline import (
            EntityExtractor,
            EntityResolutionEngine,
        )

        event_id = context.event_id
        settings = context.settings
        llm_client = context.llm_client

        extraction = None
        entities: list[Entity] = []
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

            _t3 = time.monotonic()
            extraction = await extractor.extract_from_event(event)
            context.result.step_timings["step5_extraction"] = time.monotonic() - _t3
            entities = extraction.persisted_entities
            if not entities:
                entities = list(
                    (await session.execute(
                        select(Entity).where(Entity.source_event_id == event.id)
                    )).scalars().all()
                )
            await session.commit()

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

        return context

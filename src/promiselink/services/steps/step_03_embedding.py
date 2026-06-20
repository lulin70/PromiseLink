"""Step 03: Entity embedding for semantic search."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.event import Event
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step03_SemanticEmbedding(PipelineStep):
    """Entity embedding for semantic search (F-57)."""

    name = "step03_semantic_embedding"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal
        from promiselink.services.embedding_provider import get_shared_provider
        from promiselink.services.semantic_search import get_shared_engine

        event_id = context.event_id
        entities = context.entities
        assert context.result is not None

        _t55 = time.monotonic()
        try:
            embedder = await get_shared_provider()
            search_engine = await get_shared_engine(provider=embedder)

            for entity in entities:
                try:
                    props = entity.properties or {}
                    basic = props.get("basic", {})
                    concern = props.get("concern", [])
                    capability = props.get("capability", [])

                    text_parts = []
                    if entity.name:
                        text_parts.append(f"姓名: {entity.name}")
                    if basic.get("company"):
                        text_parts.append(f"公司: {basic['company']}")
                    if basic.get("industry"):
                        text_parts.append(f"行业: {basic['industry']}")
                    if basic.get("title"):
                        text_parts.append(f"职位: {basic['title']}")
                    for c in concern:
                        if isinstance(c, dict) and c.get("category"):
                            text_parts.append(f"关注: {c['category']} - {c.get('detail', '')}")
                    for c in capability:
                        if isinstance(c, dict) and c.get("category"):
                            text_parts.append(f"能力: {c['category']} - {c.get('detail', '')}")

                    if text_parts:
                        combined_text = " | ".join(text_parts)
                        await search_engine.index_entity(
                            entity_id=str(entity.id),
                            text=combined_text,
                            user_id=str(entity.user_id),
                        )
                except Exception as embed_err:  # External API — keep broad catch for resilience
                    logger.warning("pipeline_step5_5_entity_embed_failed",
                        entity_id=str(entity.id), error=str(embed_err))

            # Also index the event
            async with AsyncSessionLocal() as session:
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if event and event.raw_text:
                    await search_engine.index_event(
                        event_id=str(event.id),
                        text=event.raw_text[:500],
                        user_id=str(event.user_id),
                    )
        except Exception as embed_init_err:  # External API — keep broad catch for resilience
            logger.warning("pipeline_step5_5_init_failed", error=str(embed_init_err))
            context.failed_steps.append(self.name)

        context.result.step_timings["step3_embedding"] = time.monotonic() - _t55

        return context

"""Step 10: Discover associations (incremental — only new/merged entities)."""

from __future__ import annotations

import time

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("eventlink.pipeline_steps")


class Step10_AssociationDiscovery(PipelineStep):
    """Discover associations (incremental — only new/merged entities)."""

    name = "step10_association_discovery"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        # Import from event_pipeline to preserve test-patch compatibility
        from eventlink.services.event_pipeline import AssociationDiscoveryEngine

        event_id = context.event_id
        user_id = context.user_id
        entities = context.entities
        merged_ids = context.merged_entity_ids

        _t6 = time.monotonic()
        async with AsyncSessionLocal() as session:
            async with session.begin():
                discovery = AssociationDiscoveryEngine(session=session)
                new_entity_ids = [str(e.id) for e in entities] if entities else []
                if new_entity_ids:
                    await discovery.discover_incremental(
                        user_id=user_id,
                        new_entity_ids=new_entity_ids,
                        merged_entity_ids=merged_ids,
                        event_id=event_id,
                    )
                else:
                    await discovery.discover_all_pairs(
                        user_id=user_id,
                        event_id=event_id,
                    )

        context.result.step_timings["step11_associations"] = time.monotonic() - _t6

        return context

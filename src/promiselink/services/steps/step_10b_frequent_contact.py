"""Step 10b — Frequent contact scan (W4 co-occurrence rule).

Runs after Step10 (association discovery). The default 3 hits / 90 days rule
is inherited from the user's 2026-09-05 decision (#4) and is configurable
through Settings (``co_occurrence_threshold`` / ``co_occurrence_window_days``).
"""

from __future__ import annotations

import time

from sqlalchemy.exc import SQLAlchemyError

from promiselink.core.logging import get_logger
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step10b_FrequentContactScan(PipelineStep):
    """W4 — scan entities for pair-wise co-occurrence above threshold."""

    name = "step10b_frequent_contact"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.config import get_settings
        from promiselink.database import AsyncSessionLocal
        from promiselink.services.frequent_contact_scanner import (
            scan_frequent_contacts,
        )

        assert context.user_id is not None
        settings = context.settings or get_settings()
        threshold = int(getattr(settings, "co_occurrence_threshold", 3) or 3)
        window_days = int(getattr(settings, "co_occurrence_window_days", 90) or 90)

        _t = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                await scan_frequent_contacts(
                    session,
                    user_id=context.user_id,
                    threshold=threshold,
                    window_days=window_days,
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "pipeline_frequent_contact_failed",
                event_id=context.event_id,
                error=str(exc),
            )
            context.failed_steps.append(self.name)

        if context.result is not None:
            context.result.step_timings[self.name] = time.monotonic() - _t
        return context

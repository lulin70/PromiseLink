"""Step 01: Verify event, mark processing, classify input scope, generate title."""

from __future__ import annotations

import time

from sqlalchemy import select

from promiselink.core.logging import get_logger
from promiselink.models.event import Event
from promiselink.services.steps.context import PipelineContext, PipelineStep

logger = get_logger("promiselink.pipeline_steps")


class Step01_VerifyEvent(PipelineStep):
    """Verify event, mark processing, classify input scope, generate title."""

    name = "step01_verify_event"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from promiselink.database import AsyncSessionLocal
        from promiselink.services.title_generator import generate_event_title

        event_id = context.event_id
        llm_client = context.llm_client
        assert context.result is not None
        assert llm_client is not None

        # Step 1: Quick check if event is still pending
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if not event:
                    logger.warning("pipeline_event_not_found", event_id=event_id)
                    context.result.status = "failed"
                    context.result.error = "Event not found"
                    context.should_stop = True
                    return context
                if event.status != "pending":
                    logger.warning(
                        "pipeline_event_already_processed",
                        event_id=event_id,
                        status=event.status,
                    )
                    context.result.status = "skipped"
                    context.should_stop = True
                    return context
                # Capture user_id for later steps
                context.user_id = str(event.user_id)

        # Step 2: Mark event as processing
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if not event:
                    context.result.status = "failed"
                    context.result.error = "Event not found"
                    context.should_stop = True
                    return context
                event.status = "processing"
                event.pipeline = "full"

        # Step 3: Input Scope Classification (F-44)
        from promiselink.services.input_scope_classifier import InputScopeClassifier

        scope_classifier = InputScopeClassifier(llm_client=llm_client)
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    db_event = await session.execute(select(Event).where(Event.id == event_id))
                    event = db_event.scalar_one_or_none()
                    if not event:
                        context.result.status = "failed"
                        context.result.error = "Event not found"
                        context.should_stop = True
                        return context

                    _t0 = time.monotonic()
                    scope_result = await scope_classifier.classify(event)
                    context.result.step_timings["step1_verify_input_scope"] = time.monotonic() - _t0
                    event.input_scope = scope_result.scope.value
                    event.input_scope_confidence = scope_result.confidence

            logger.info("pipeline_step3_input_scope",
                event_id=event_id,
                scope=scope_result.scope.value,
                confidence=scope_result.confidence,
                method=scope_result.method,
            )
        except Exception as scope_err:  # External API — keep broad catch for resilience
            logger.error("pipeline_step3_input_scope_failed",
                event_id=event_id, error=str(scope_err))
            context.should_stop = True
            context.failed_steps.append(self.name)
            return context

        # Step 4: Auto-generate Event title if empty/placeholder
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_event = await session.execute(select(Event).where(Event.id == event_id))
                event = db_event.scalar_one_or_none()
                if event and (not event.title or event.title.strip() in ("", "untitled", "未命名")):
                    _t05 = time.monotonic()
                    try:
                        generated_title = await generate_event_title(
                            llm_client, event.raw_text or ""
                        )
                        if generated_title:
                            event.title = generated_title
                            logger.info("pipeline_step4_title_generated",
                                event_id=event_id,
                                title=generated_title,
                            )
                    except Exception as title_err:  # External API — keep broad catch for resilience
                        logger.warning("pipeline_step4_title_failed",
                            event_id=event_id,
                            error=str(title_err),
                        )
                    context.result.step_timings["step1_verify_title_gen"] = time.monotonic() - _t05

        return context

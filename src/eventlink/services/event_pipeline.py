"""Event Processing Pipeline — orchestrates the core EventLink loop.

Core loop: 互动记录 → InputScope分类 → 实体抽取 → Todo生成 → Promise双向分析 → 通知 → 原始数据存储 → 关联发现 → RelationshipBrief更新 → 状态机
Implements the full processing pipeline from event ingestion to todo generation.

Pipeline stages (9 steps):
  1. Quick check — verify event exists and is pending
  2. Status update — mark event as processing
  3. Input Scope Classification (InputScopeClassifier) — F-44 classify input scope
  4. Entity extraction (EntityExtractor) — extract persons from raw text
  5. Todo generation (TodoGenerator) — generate action items from event + entities
  6. Promise Bidirectional Analysis (PromiseBidirectionalHandler) — F-45+F-46 enrich todos
  7. Notification — send notifications for new todos
  8. Raw data storage (MemoryProvider) — store original text for traceability
  9. Association discovery (AssociationDiscoveryEngine) — find relationships
 10. Relationship Brief Update (RelationshipBriefService) — F-47+F-48 update person briefs
 11. Status update — mark event as completed

Uses short transactions to avoid holding SQLite write locks during slow LLM calls.
Each step opens its own session/transaction, commits, and releases the lock.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.association_discovery import AssociationDiscoveryEngine
from eventlink.services.entity_extractor import EntityExtractor, ExtractionResult
from eventlink.services.entity_resolution import EntityResolutionEngine
from eventlink.services.llm_client import LLMClient
from eventlink.services.memory_provider import (
    MemoryProvider,
    NullMemoryProvider,
    create_memory_provider,
)
from eventlink.services.todo_generator import TodoGenerator

logger = get_logger("eventlink.pipeline")


@dataclass
class PipelineResult:
    """Result of the full event processing pipeline."""

    event_id: str
    status: str = "completed"
    entities: list[Entity] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)
    extraction: ExtractionResult | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def success(self) -> bool:
        return self.status == "completed" and self.error is None


async def process_event_with_short_transactions(event_id: str) -> PipelineResult:
    """Process an event using short transactions to avoid SQLite lock contention.

    This is the primary entry point for background event processing.
    Each pipeline step opens its own session, commits, and releases the lock
    before the next step begins. This prevents SQLite write locks from
    blocking concurrent API requests during slow LLM calls.

    Args:
        event_id: The ID of the event to process.

    Returns:
        PipelineResult with entities, todos, and status.
    """
    from eventlink.config import get_settings
    from eventlink.database import AsyncSessionLocal

    settings = get_settings()
    llm_client = LLMClient(config=settings)
    memory = create_memory_provider(
        provider_type=settings.memory_provider,
        base_dir=settings.memory_file_base_dir,
        api_url=settings.carrymem_api_url,
        api_key=settings.carrymem_api_key,
    )

    result = PipelineResult(
        event_id=str(event_id),
        started_at=datetime.utcnow(),
    )

    try:
        # Step 1: Quick check if event is still pending (short transaction)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == str(event_id))
                )
                event = db_result.scalar_one_or_none()
                if not event:
                    logger.warning("pipeline_event_not_found", event_id=str(event_id))
                    result.status = "failed"
                    result.error = "Event not found"
                    return result
                if event.status != "pending":
                    logger.warning(
                        "pipeline_event_already_processed",
                        event_id=str(event_id),
                        status=event.status,
                    )
                    result.status = "skipped"
                    return result

        # Step 2: Mark event as processing (short transaction)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == str(event_id))
                )
                event = db_result.scalar_one_or_none()
                if not event:
                    result.status = "failed"
                    result.error = "Event not found"
                    return result
                event.status = "processing"
                event.pipeline = "full"

        # ── NEW Step 0: Input Scope Classification (F-44) ──
        from eventlink.services.input_scope_classifier import InputScopeClassifier

        scope_classifier = InputScopeClassifier(llm_client=llm_client)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_event = await session.execute(select(Event).where(Event.id == str(event_id)))
                event = db_event.scalar_one_or_none()
                if not event:
                    result.status = "failed"
                    result.error = "Event not found"
                    return result

                # Classify input scope
                scope_result = await scope_classifier.classify(event)
                event.input_scope = scope_result.scope.value
                event.input_scope_confidence = scope_result.confidence

        logger.info("pipeline_step0_input_scope",
            event_id=str(event_id),
            scope=scope_result.scope.value,
            confidence=scope_result.confidence,
            method=scope_result.method,
        )

        # Step 3: Entity extraction (LLM call + persist + commit)
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
                select(Event).where(Event.id == str(event_id))
            )
            event = db_result.scalar_one_or_none()
            if not event:
                result.status = "failed"
                result.error = "Event not found during extraction"
                return result

            extraction = await extractor.extract_from_event(event)
            entities = extraction.persisted_entities
            if not entities:
                entities = list(
                    (await session.execute(
                        select(Entity).where(Entity.source_event_id == event.id)
                    )).scalars().all()
                )
            await session.commit()

        result.extraction = extraction
        result.entities = entities

        logger.info(
            "pipeline_extraction_done",
            event_id=str(event_id),
            persons_extracted=len(extraction.persons) if extraction else 0,
            entities_persisted=len(entities),
        )

        # Step 4: Todo generation (LLM call + persist + commit)
        todos: list[Todo] = []
        async with AsyncSessionLocal() as session:
            generator = TodoGenerator(llm_client=llm_client, session=session)

            db_result = await session.execute(
                select(Event).where(Event.id == str(event_id))
            )
            event = db_result.scalar_one_or_none()
            if not event:
                result.status = "failed"
                result.error = "Event not found during todo generation"
                return result

            # Re-fetch entities for this event
            entity_result = await session.execute(
                select(Entity).where(Entity.source_event_id == event.id)
            )
            db_entities = list(entity_result.scalars().all())
            if not db_entities and entities:
                db_entities = entities

            todos = await generator.generate_todos(
                event=event,
                entities=db_entities,
            )
            await session.commit()

        result.todos = todos

        logger.info(
            "pipeline_todos_done",
            event_id=str(event_id),
            todos_generated=len(todos),
        )

        # ── NEW Step 5: Promise Bidirectional Analysis + Deduplication (F-45 + F-46) ──
        # Note: F-46 dedup is already integrated inside TodoGenerator.generate_todos()
        # Here we add F-45 promise bidirectional analysis for each generated todo
        from eventlink.services.promise_bidirectional import PromiseBidirectionalHandler

        promise_handler = PromiseBidirectionalHandler(llm_client=llm_client)
        async with AsyncSessionLocal() as session:
            # Re-fetch todos that were just generated
            todo_result = await session.execute(
                select(Todo).where(Todo.source_event_id == str(event_id))
            )
            fresh_todos = list(todo_result.scalars().all())

            # Re-fetch event for evidence extraction
            evt_result = await session.execute(
                select(Event).where(Event.id == str(event_id))
            )
            current_event = evt_result.scalar_one()

            # Re-fetch entities for entity mapping
            ent_result = await session.execute(
                select(Entity).where(Entity.source_event_id == str(event_id))
            )
            fresh_entities = list(ent_result.scalars().all())

            for todo in fresh_todos:
                try:
                    analysis = await promise_handler.analyze_todo(
                        todo=todo,
                        event=current_event,
                        entities=fresh_entities,
                    )
                    # Apply analysis to todo
                    todo.action_type = analysis.action_type.value
                    todo.promisor_id = analysis.promisor_entity_id
                    todo.beneficiary_id = analysis.beneficiary_entity_id
                    todo.confirmation_status = analysis.confirmation_status.value
                    todo.evidence_quote = analysis.evidence_quote
                    todo.evidence_event_id = str(current_event.id) if analysis.evidence_quote else None
                except Exception as promise_err:
                    logger.warning("pipeline_promise_analysis_failed",
                        todo_id=str(todo.id), error=str(promise_err))

            await session.commit()

        result.todos = fresh_todos  # Update result with enriched todos

        logger.info("pipeline_step5_promise_bidirectional",
            event_id=str(event_id),
            todos_enriched=len(fresh_todos),
        )

        # Step 4.5: Send notifications for new todos
        try:
            from eventlink.services.notification_service import notification_service
            for todo in result.todos:
                await notification_service.notify_todo_created(
                    user_id=str(event.user_id),
                    todo_title=todo.title,
                    todo_type=todo.todo_type,
                    todo_id=str(todo.id),
                )
        except Exception as notif_err:
            logger.warning("pipeline_notification_failed", error=str(notif_err))

        # Step 5: Store raw data to memory provider
        try:
            entity_ids = [str(e.id) for e in entities] if entities else []
            await memory.store_raw(
                event_id=str(event_id),
                raw_text=event.raw_text or "",
                metadata={"event_type": event.event_type, "source": event.source},
                entity_ids=entity_ids,
                summary=extraction.summary if extraction else "",
            )
        except Exception as mem_err:
            logger.warning(
                "pipeline_memory_failed",
                event_id=str(event_id),
                error=str(mem_err),
            )

        # Step 6: Discover associations (incremental — only new/merged entities)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                discovery = AssociationDiscoveryEngine(session=session)
                new_entity_ids = [str(e.id) for e in entities] if entities else []
                # Track merged entities from extraction
                merged_ids = []
                if extraction and hasattr(extraction, "merged_entity_ids"):
                    merged_ids = extraction.merged_entity_ids
                if new_entity_ids:
                    await discovery.discover_incremental(
                        user_id=str(event.user_id),
                        new_entity_ids=new_entity_ids,
                        merged_entity_ids=merged_ids,
                        event_id=str(event_id),
                    )
                else:
                    # Fallback to full scan if no new entities tracked
                    await discovery.discover_all_pairs(
                        user_id=str(event.user_id),
                        event_id=str(event_id),
                    )

        # ── NEW Step 8: Relationship Brief Update (F-47 + F-48) ──
        try:
            from eventlink.services.relationship_brief_service import RelationshipBriefService

            async with AsyncSessionLocal() as session:
                brief_service = RelationshipBriefService(session=session, llm_client=llm_client)

                # For each person entity extracted from this event, update their brief
                for entity in entities:
                    if entity.entity_type != "person":
                        continue

                    try:
                        brief_result = await brief_service.update_brief_from_event(
                            user_id=str(event.user_id),
                            person_entity_id=str(entity.id),
                            event=event,
                            entities=entities,
                            todos=result.todos,
                        )
                        if brief_result.is_new or brief_result.modules_updated:
                            logger.info("pipeline_step8_brief_updated",
                                entity_id=str(entity.id),
                                is_new=brief_result.is_new,
                                modules=brief_result.modules_updated,
                            )
                    except Exception as brief_err:
                        logger.warning("pipeline_brief_update_failed",
                            entity_id=str(entity.id),
                            error=str(brief_err),
                        )
        except ImportError:
            logger.debug("pipeline_step8_skipped_relationship_brief_not_available")
        except Exception as step8_err:
            logger.warning("pipeline_step8_error", error=str(step8_err))

        # Step 7: Mark event as completed (short transaction)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == str(event_id))
                )
                event = db_result.scalar_one_or_none()
                if event:
                    event.status = "completed"
                    event.processed_at = datetime.utcnow()

        result.status = "completed"
        result.completed_at = datetime.utcnow()

        logger.info(
            "pipeline_completed",
            event_id=str(event_id),
            entity_count=len(entities),
            todo_count=len(result.todos),
        )

    except Exception as e:
        logger.exception("pipeline_error", event_id=str(event_id), error=str(e))
        result.status = "failed"
        result.error = str(e)
        result.completed_at = datetime.utcnow()

        # Try to mark event as failed
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    db_result = await session.execute(
                        select(Event).where(Event.id == str(event_id))
                    )
                    event = db_result.scalar_one_or_none()
                    if event and event.status == "processing":
                        event.status = "failed"
                        event.processed_at = datetime.utcnow()
        except Exception:
            logger.error("pipeline_failed_to_mark_failed", event_id=str(event_id))

    finally:
        await llm_client.close()

    return result

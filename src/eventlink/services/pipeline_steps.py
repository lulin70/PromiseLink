"""Pipeline Step classes — each step is independently testable.

Each Step class:
  - Has a ``name`` attribute
  - Has an ``async execute(self, context: PipelineContext) -> PipelineContext`` method
  - Handles its own database transaction (short transaction pattern)

Execution order (matches original process_event_with_short_transactions):
  1. Step1_RawEventToEvent          — verify + mark processing + input scope + title
  2. Step2_EntityExtraction         — entity extraction + resolution
  3. Step3_EntityResolution         — post-extraction resolution validation (no-op, resolution done in Step2)
  4. Step5_5_DependencyAnalysis     — entity embedding for semantic search
  5. Step5_TodoGeneration           — todo generation
  6. Step7_ConcernCapabilityExtraction — promise bidirectional analysis
  7. Step8_3_ContextMatching        — resource overuse detection
  8. Step6_PriorityScoring          — priority scoring
  9. Step9_Notification             — send notifications
 10. Step10_MemoryStorage           — store raw data to memory provider
 11. Step4_AssociationDiscovery     — discover associations
 12. Step8_5_SemanticAssociation    — generate todos from associations
 13. Step13_RelationshipBriefUpdate — update relationship briefs
 14. Step8_EventStatusUpdate        — mark event as completed

NOTE: Services that are patched in tests at ``eventlink.services.event_pipeline``
      are imported from that module at function level to preserve patch compatibility.
      Services patched at their original modules are imported directly.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.entity_extractor import ExtractionResult
from eventlink.services.llm_client import LLMClient

logger = get_logger("eventlink.pipeline_steps")


# ── Pipeline Context ──


@dataclass
class PipelineContext:
    """Shared state carried between pipeline steps."""

    event_id: str
    # Populated after Step1
    user_id: str | None = None
    # Shared services (set by orchestrator)
    llm_client: LLMClient | None = None
    memory: Any = None  # MemoryProvider
    settings: Any = None  # Settings
    # Accumulated result
    result: Any = None  # PipelineResult — set by orchestrator
    # Intermediate results shared between steps
    entities: list[Entity] = field(default_factory=list)
    extraction: ExtractionResult | None = None
    todos: list[Todo] = field(default_factory=list)
    merged_entity_ids: list[str] = field(default_factory=list)
    # Control flow
    should_stop: bool = False


# ── Abstract Step ──


class PipelineStep(ABC):
    """Base class for all pipeline steps."""

    name: str = "unnamed_step"

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute this step, mutating context as needed."""


# ── Step implementations ──


class Step1_RawEventToEvent(PipelineStep):
    """Steps 1-4: Verify event, mark processing, classify input scope, generate title."""

    name = "step1_raw_event_to_event"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        # Import from event_pipeline to preserve test-patch compatibility
        from eventlink.services import event_pipeline as _ep

        event_id = context.event_id
        llm_client = context.llm_client

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
        from eventlink.services.input_scope_classifier import InputScopeClassifier

        scope_classifier = InputScopeClassifier(llm_client=llm_client)
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
                context.result.step_timings["step3_input_scope"] = time.monotonic() - _t0
                event.input_scope = scope_result.scope.value
                event.input_scope_confidence = scope_result.confidence

        logger.info("pipeline_step3_input_scope",
            event_id=event_id,
            scope=scope_result.scope.value,
            confidence=scope_result.confidence,
            method=scope_result.method,
        )

        # Step 4: Auto-generate Event title if empty/placeholder
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_event = await session.execute(select(Event).where(Event.id == event_id))
                event = db_event.scalar_one_or_none()
                if event and (not event.title or event.title.strip() in ("", "untitled", "未命名")):
                    _t05 = time.monotonic()
                    try:
                        generated_title = await _ep._generate_event_title(
                            llm_client, event.raw_text or ""
                        )
                        if generated_title:
                            event.title = generated_title
                            logger.info("pipeline_step4_title_generated",
                                event_id=event_id,
                                title=generated_title,
                            )
                    except Exception as title_err:
                        logger.warning("pipeline_step4_title_failed",
                            event_id=event_id,
                            error=str(title_err),
                        )
                    context.result.step_timings["step4_title_gen"] = time.monotonic() - _t05

        return context


class Step2_EntityExtraction(PipelineStep):
    """Step 5: Entity extraction + Entity resolution (LLM call + persist + commit)."""

    name = "step2_entity_extraction"

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


class Step3_EntityResolution(PipelineStep):
    """Step 6: Entity resolution validation.

    Resolution is already performed inside Step2_EntityExtraction
    (EntityExtractor calls EntityResolutionEngine internally).
    This step exists for interface completeness and future extensibility.
    """

    name = "step3_entity_resolution"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        # Resolution is already done inside Step2_EntityExtraction.
        # This step is a no-op placeholder for future post-resolution work.
        return context


class Step5_5_DependencyAnalysis(PipelineStep):
    """Step 5.5: Entity embedding for semantic search (F-57)."""

    name = "step5_5_dependency_analysis"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.embedding_provider import EmbeddingProvider
        from eventlink.services.semantic_search import SemanticSearchEngine

        event_id = context.event_id
        entities = context.entities

        _t55 = time.monotonic()
        try:
            embedder = EmbeddingProvider()
            search_engine = SemanticSearchEngine(provider=embedder)

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
                except Exception as embed_err:
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
        except Exception as embed_init_err:
            logger.warning("pipeline_step5_5_init_failed", error=str(embed_init_err))

        context.result.step_timings["step5_5_embedding"] = time.monotonic() - _t55

        return context


class Step5_TodoGeneration(PipelineStep):
    """Step 7: Todo generation (LLM call + persist + commit)."""

    name = "step5_todo_generation"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        # Import from event_pipeline to preserve test-patch compatibility
        from eventlink.services.event_pipeline import TodoGenerator

        event_id = context.event_id
        llm_client = context.llm_client
        entities = context.entities

        todos: list[Todo] = []
        async with AsyncSessionLocal() as session:
            generator = TodoGenerator(llm_client=llm_client, session=session)

            db_result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            event = db_result.scalar_one_or_none()
            if not event:
                context.result.status = "failed"
                context.result.error = "Event not found during todo generation"
                context.should_stop = True
                return context

            # Re-fetch entities for this event
            entity_result = await session.execute(
                select(Entity).where(Entity.source_event_id == event.id)
            )
            db_entities = list(entity_result.scalars().all())
            if not db_entities and entities:
                db_entities = entities

            _t4 = time.monotonic()
            todos = await generator.generate_todos(
                event=event,
                entities=db_entities,
            )
            context.result.step_timings["step7_todos"] = time.monotonic() - _t4
            await session.commit()

        context.todos = todos
        context.result.todos = todos

        logger.info(
            "pipeline_todos_done",
            event_id=event_id,
            todos_generated=len(todos),
        )

        return context


class Step7_ConcernCapabilityExtraction(PipelineStep):
    """Step 8: Promise Bidirectional Analysis + Deduplication (F-45 + F-46)."""

    name = "step7_concern_capability_extraction"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.promise_bidirectional import PromiseBidirectionalHandler

        event_id = context.event_id
        llm_client = context.llm_client

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
                if isinstance(analysis, Exception):
                    logger.warning("pipeline_promise_analysis_failed",
                        todo_id=str(todo.id), error=str(analysis))
                    continue
                try:
                    todo.action_type = analysis.action_type.value
                    todo.promisor_id = analysis.promisor_entity_id
                    todo.beneficiary_id = analysis.beneficiary_entity_id
                    todo.confirmation_status = analysis.confirmation_status.value
                    todo.evidence_quote = analysis.evidence_quote
                    todo.evidence_event_id = str(current_event.id) if analysis.evidence_quote else None
                except Exception as apply_err:
                    logger.warning("pipeline_promise_apply_failed",
                        todo_id=str(todo.id), error=str(apply_err))

            context.result.step_timings["step8_promise_analysis"] = time.monotonic() - _t5

            await session.commit()

        context.todos = fresh_todos
        context.result.todos = fresh_todos

        logger.info("pipeline_step8_promise_bidirectional",
            event_id=event_id,
            todos_enriched=len(fresh_todos),
        )

        return context


class Step8_3_ContextMatching(PipelineStep):
    """Step 8.3: Resource overuse detection (F-39)."""

    name = "step8_3_context_matching"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.resource_overuse_detector import ResourceOveruseDetector

        event_id = context.event_id

        _t83 = time.monotonic()
        try:
            overuse_detector = ResourceOveruseDetector()
            async with AsyncSessionLocal() as overuse_session:
                overuse_todo_q = await overuse_session.execute(
                    select(Todo).where(Todo.source_event_id == event_id)
                )
                overuse_todos = list(overuse_todo_q.scalars().all())

                checked_entities: set[str] = set()
                for todo in overuse_todos:
                    if (
                        todo.action_type == "their_promise"
                        and todo.related_entity_id
                        and str(todo.related_entity_id) not in checked_entities
                    ):
                        checked_entities.add(str(todo.related_entity_id))
                        try:
                            await overuse_detector.check_and_create_warning_todo(
                                user_id=str(todo.user_id),
                                target_entity_id=str(todo.related_entity_id),
                                source_event_id=event_id,
                                session=overuse_session,
                            )
                        except Exception as overuse_err:
                            logger.warning("pipeline_step8_3_overuse_check_failed",
                                entity_id=str(todo.related_entity_id),
                                error=str(overuse_err))

                await overuse_session.commit()
        except Exception as overuse_init_err:
            logger.warning("pipeline_step8_3_overuse_init_failed", error=str(overuse_init_err))

        context.result.step_timings["step8_3_resource_overuse"] = time.monotonic() - _t83

        logger.info("pipeline_step8_3_resource_overuse", event_id=event_id)

        return context


class Step6_PriorityScoring(PipelineStep):
    """Step 8.5: Phase 1 four-dimensional priority scoring (F-55+F-56)."""

    name = "step6_priority_scoring"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.priority_scorer import PriorityScorerV2

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
                await score_session.commit()
        except Exception as scorer_err:
            logger.warning("pipeline_step8_5_scorer_init_failed", error=str(scorer_err))

        context.result.step_timings["step8_5_priority_scoring"] = time.monotonic() - _t85

        logger.info("pipeline_step8_5_priority_scored",
            event_id=event_id,
            todos_scored=len(context.todos),
        )

        return context


class Step9_Notification(PipelineStep):
    """Step 9: Send notifications for new todos."""

    name = "step9_notification"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        event_id = context.event_id
        user_id = context.user_id

        try:
            from eventlink.services.notification_service import notification_service
            for todo in context.result.todos:
                await notification_service.notify_todo_created(
                    user_id=user_id,
                    todo_title=todo.title,
                    todo_type=todo.todo_type,
                    todo_id=str(todo.id),
                )
        except Exception as notif_err:
            logger.warning("pipeline_notification_failed", error=str(notif_err))

        return context


class Step10_MemoryStorage(PipelineStep):
    """Step 10: Store raw data to memory provider."""

    name = "step10_memory_storage"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal

        event_id = context.event_id
        entities = context.entities
        extraction = context.extraction
        memory = context.memory

        try:
            # Re-fetch event to get raw_text and metadata
            async with AsyncSessionLocal() as session:
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()

            if event:
                entity_ids = [str(e.id) for e in entities] if entities else []
                await memory.store_raw(
                    event_id=event_id,
                    raw_text=event.raw_text or "",
                    metadata={"event_type": event.event_type, "source": event.source},
                    entity_ids=entity_ids,
                    summary=extraction.summary if extraction else "",
                )
        except Exception as mem_err:
            logger.warning(
                "pipeline_memory_failed",
                event_id=event_id,
                error=str(mem_err),
            )

        return context


class Step4_AssociationDiscovery(PipelineStep):
    """Step 11: Discover associations (incremental — only new/merged entities)."""

    name = "step4_association_discovery"

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


class Step8_5_SemanticAssociation(PipelineStep):
    """Step 12: Generate todos from new associations — Link → Action."""

    name = "step8_5_semantic_association"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal

        event_id = context.event_id
        user_id = context.user_id

        _t7_5 = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                from eventlink.models.association import Association

                assoc_result = await session.execute(
                    select(Association).where(
                        Association.user_id == user_id,
                        Association.source_event_id == event_id,
                    )
                )
                new_assocs = assoc_result.scalars().all()

                if new_assocs:
                    ent_result = await session.execute(
                        select(Entity).where(Entity.user_id == user_id)
                    )
                    entity_map = {str(e.id): e.name for e in ent_result.scalars().all()}

                    for assoc in new_assocs:
                        src_name = entity_map.get(str(assoc.source_entity_id), "")
                        tgt_name = entity_map.get(str(assoc.target_entity_id), "")
                        todo_title = None
                        todo_type = "followup"
                        priority = 3

                        atype = assoc.association_type
                        evidence = (assoc.properties or {}).get("evidence", {})

                        if atype == "industry_chain":
                            rel = evidence.get("relation", "")
                            if rel == "potential_investor_startup":
                                todo_title = f"引荐{src_name}和{tgt_name}（投资-创业链）"
                                todo_type = "cooperation_signal"
                                priority = 1
                            else:
                                todo_title = f"对接{src_name}和{tgt_name}（产业链上下游）"
                                todo_type = "followup"
                                priority = 3
                        elif atype == "supply_demand":
                            matches = evidence.get("matches", [])
                            if matches:
                                m = matches[0]
                                items = ", ".join(m.get("matched_items", [])[:2])
                                todo_title = f"{m.get('supplier', src_name)} 可帮助 {m.get('requester', tgt_name)} ({items})"
                                todo_type = "help"
                                priority = 1
                        elif atype == "topic_overlap":
                            todo_title = f"安排{src_name}和{tgt_name}交流（同领域）"
                            todo_type = "followup"
                            priority = 3
                        elif atype == "same_city":
                            todo_title = f"约{src_name}和{tgt_name}同城见面"
                            todo_type = "care"
                            priority = 4

                        if todo_title:
                            existing = await session.execute(
                                select(Todo).where(
                                    Todo.user_id == user_id,
                                    Todo.title == todo_title,
                                    Todo.status == "pending",
                                )
                            )
                            if not existing.scalar_one_or_none():
                                todo = Todo(
                                    user_id=user_id,
                                    title=todo_title,
                                    todo_type=todo_type,
                                    priority=priority,
                                    status="pending",
                                    source_event_id=event_id,
                                )
                                session.add(todo)

                    await session.commit()
        except Exception as step12_err:
            logger.warning("pipeline_step12_error", error=str(step12_err))

        context.result.step_timings["step12_assoc_todos"] = time.monotonic() - _t7_5

        return context


class Step13_RelationshipBriefUpdate(PipelineStep):
    """Step 13: Relationship Brief Update (F-47 + F-48)."""

    name = "step13_relationship_brief_update"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal
        from eventlink.services.relationship_brief_service import RelationshipBriefService

        event_id = context.event_id
        user_id = context.user_id
        llm_client = context.llm_client

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

                await session.commit()
        except ImportError:
            logger.debug("pipeline_step13_skipped_relationship_brief_not_available")
        except Exception as step13_err:
            logger.warning("pipeline_step13_error", error=str(step13_err))

        context.result.step_timings["step13_briefs"] = time.monotonic() - _t8

        return context


class Step8_EventStatusUpdate(PipelineStep):
    """Step 14: Mark event as completed."""

    name = "step8_event_status_update"

    async def execute(self, context: PipelineContext) -> PipelineContext:
        from eventlink.database import AsyncSessionLocal

        event_id = context.event_id

        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == event_id)
                )
                event = db_result.scalar_one_or_none()
                if event:
                    event.status = "completed"
                    event.processed_at = datetime.now(timezone.utc)

        context.result.status = "completed"
        context.result.completed_at = datetime.now(timezone.utc)

        logger.info(
            "pipeline_completed",
            event_id=event_id,
            entity_count=len(context.entities),
            todo_count=len(context.result.todos),
        )

        return context

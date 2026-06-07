"""Event Processing Pipeline — orchestrates the core EventLink loop.

Core loop: 互动记录 → InputScope分类 → 实体抽取 → Todo生成 → Promise双向分析 → 通知 → 原始数据存储 → 关联发现 → RelationshipBrief更新 → 状态机
Implements the full processing pipeline from event ingestion to todo generation.

Pipeline stages (14 steps):
  Step 1  — Quick check: verify event exists and is pending
  Step 2  — Status update: mark event as processing
  Step 3  — Input Scope Classification (InputScopeClassifier) — F-44
  Step 4  — Auto-generate Event title if empty/placeholder
  Step 5  — Entity extraction (EntityExtractor) + Entity resolution — F-53 concern/capability
  Step 6  — Entity resolution (5-step algorithm) — runs inside Step 5
  Step 7  — Todo generation (TodoGenerator) — F-46 dedup integrated
  Step 8  — Promise Bidirectional Analysis (PromiseBidirectionalHandler) — F-45
  Step 9  — Notification — send notifications for new todos
  Step 10 — Raw data storage (MemoryProvider) — store original text
  Step 11 — Association discovery (AssociationDiscoveryEngine) — incremental
  Step 12 — Association → Todo generation — Link → Action
  Step 13 — Relationship Brief Update (RelationshipBriefService) — F-47+F-48
  Step 14 — Status update: mark event as completed

Uses short transactions to avoid holding SQLite write locks during slow LLM calls.
Each step opens its own session/transaction, commits, and releases the lock.
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.association_discovery import AssociationDiscoveryEngine
from eventlink.services.entity_extractor import EntityExtractor, ExtractionResult
from eventlink.services.entity_resolution import EntityResolutionEngine
from eventlink.services.llm_client import LLMClient
from eventlink.services.memory_provider import create_memory_provider
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
    step_timings: dict[str, float] = field(default_factory=dict)  # step_name → elapsed seconds

    @property
    def success(self) -> bool:
        return self.status == "completed" and self.error is None


async def _generate_event_title(llm_client: LLMClient, raw_text: str) -> str | None:
    """Use LLM to generate a concise event title from raw text.

    Returns a title string (max 50 chars) or None on failure.
    """
    if not raw_text or len(raw_text.strip()) < 10:
        return None

    prompt = (
        "请从以下交流记录中提取一个简洁的事件标题（不超过30个字），"
        "格式为「活动类型 - 关键人物/主题」，例如「投资对接会 - 盛恒资本李总」或「下午茶交流 - 智谱AI张总」。"
        "只输出标题，不要解释。\n\n"
        f"交流记录：\n{raw_text[:500]}"
    )

    try:
        response = await llm_client.generate(
            prompt=prompt,
            max_tokens=60,
        )
        title = response.strip().strip('"').strip("'")
        # Truncate to 50 chars for safety
        if len(title) > 50:
            title = title[:47] + "..."
        return title if title else None
    except Exception:
        return None


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
        started_at=datetime.now(timezone.utc),
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

        # ── Step 3: Input Scope Classification (F-44) ──
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
                _t0 = time.monotonic()
                scope_result = await scope_classifier.classify(event)
                result.step_timings["step3_input_scope"] = time.monotonic() - _t0
                event.input_scope = scope_result.scope.value
                event.input_scope_confidence = scope_result.confidence

        logger.info("pipeline_step3_input_scope",
            event_id=str(event_id),
            scope=scope_result.scope.value,
            confidence=scope_result.confidence,
            method=scope_result.method,
        )

        # ── Step 4: Auto-generate Event title if empty/placeholder ──
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_event = await session.execute(select(Event).where(Event.id == str(event_id)))
                event = db_event.scalar_one_or_none()
                if event and (not event.title or event.title.strip() in ("", "untitled", "未命名")):
                    _t05 = time.monotonic()
                    try:
                        generated_title = await _generate_event_title(llm_client, event.raw_text or "")
                        if generated_title:
                            event.title = generated_title
                            logger.info("pipeline_step4_title_generated",
                                event_id=str(event_id),
                                title=generated_title,
                            )
                    except Exception as title_err:
                        logger.warning("pipeline_step4_title_failed",
                            event_id=str(event_id),
                            error=str(title_err),
                        )
                    result.step_timings["step4_title_gen"] = time.monotonic() - _t05

        # Step 5: Entity extraction + Entity resolution (LLM call + persist + commit)
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

            _t3 = time.monotonic()
            extraction = await extractor.extract_from_event(event)
            result.step_timings["step5_extraction"] = time.monotonic() - _t3
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

        # ── Step 5.5: Entity embedding for semantic search (F-57) ──
        _t55 = time.monotonic()
        try:
            from eventlink.services.embedding_provider import EmbeddingProvider
            from eventlink.services.semantic_search import SemanticSearchEngine

            embedder = EmbeddingProvider()
            search_engine = SemanticSearchEngine(provider=embedder)

            for entity in entities:
                try:
                    # Combine concern + capability + basic info for embedding
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
            if event.raw_text:
                await search_engine.index_event(
                    event_id=str(event.id),
                    text=event.raw_text[:500],  # Truncate for embedding
                    user_id=str(event.user_id),
                )
        except Exception as embed_init_err:
            logger.warning("pipeline_step5_5_init_failed", error=str(embed_init_err))

        result.step_timings["step5_5_embedding"] = time.monotonic() - _t55

        # Step 7: Todo generation (LLM call + persist + commit)
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

            _t4 = time.monotonic()
            todos = await generator.generate_todos(
                event=event,
                entities=db_entities,
            )
            result.step_timings["step7_todos"] = time.monotonic() - _t4
            await session.commit()

        result.todos = todos

        logger.info(
            "pipeline_todos_done",
            event_id=str(event_id),
            todos_generated=len(todos),
        )

        # ── Step 8: Promise Bidirectional Analysis + Deduplication (F-45 + F-46) ──
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
                    # Apply analysis to todo
                    todo.action_type = analysis.action_type.value
                    todo.promisor_id = analysis.promisor_entity_id
                    todo.beneficiary_id = analysis.beneficiary_entity_id
                    todo.confirmation_status = analysis.confirmation_status.value
                    todo.evidence_quote = analysis.evidence_quote
                    todo.evidence_event_id = str(current_event.id) if analysis.evidence_quote else None
                except Exception as apply_err:
                    logger.warning("pipeline_promise_apply_failed",
                        todo_id=str(todo.id), error=str(apply_err))

            result.step_timings["step8_promise_analysis"] = time.monotonic() - _t5

            await session.commit()

        result.todos = fresh_todos  # Update result with enriched todos

        logger.info("pipeline_step8_promise_bidirectional",
            event_id=str(event_id),
            todos_enriched=len(fresh_todos),
        )

        # ── Step 8.3: Resource overuse detection (F-39) ──
        _t83 = time.monotonic()
        try:
            from eventlink.services.resource_overuse_detector import ResourceOveruseDetector

            overuse_detector = ResourceOveruseDetector()
            async with AsyncSessionLocal() as overuse_session:
                # Re-query todos with action_type set by Step 8
                overuse_todo_q = await overuse_session.execute(
                    select(Todo).where(Todo.source_event_id == str(event_id))
                )
                overuse_todos = list(overuse_todo_q.scalars().all())

                # Collect unique (user_id, related_entity_id) pairs for "索取型" todos
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
                                source_event_id=str(event_id),
                                session=overuse_session,
                            )
                        except Exception as overuse_err:
                            logger.warning("pipeline_step8_3_overuse_check_failed",
                                entity_id=str(todo.related_entity_id),
                                error=str(overuse_err))

                await overuse_session.commit()
        except Exception as overuse_init_err:
            logger.warning("pipeline_step8_3_overuse_init_failed", error=str(overuse_init_err))

        result.step_timings["step8_3_resource_overuse"] = time.monotonic() - _t83

        logger.info("pipeline_step8_3_resource_overuse",
            event_id=str(event_id),
        )

        # ── Step 8.5: Phase 1 four-dimensional priority scoring (F-55+F-56) ──
        _t85 = time.monotonic()
        try:
            from eventlink.services.priority_scorer import PriorityScorerV2
            scorer_v2 = PriorityScorerV2()
            async with AsyncSessionLocal() as score_session:
                # Re-query todos in this session to avoid detached instance issues
                score_result_q = await score_session.execute(
                    select(Todo).where(Todo.source_event_id == str(event_id))
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

        result.step_timings["step8_5_priority_scoring"] = time.monotonic() - _t85

        logger.info("pipeline_step8_5_priority_scored",
            event_id=str(event_id),
            todos_scored=len(fresh_todos),
        )

        # Step 9: Send notifications for new todos
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

        # Step 10: Store raw data to memory provider
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

        # Step 11: Discover associations (incremental — only new/merged entities)
        _t6 = time.monotonic()
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

        # ── Step 12: Generate todos from new associations ──
        # The soul of EventLink: Link → Action
        # When a new association is discovered, automatically create a todo
        _t7_5 = time.monotonic()
        try:
            async with AsyncSessionLocal() as session:
                from eventlink.models.association import Association

                # Find associations created in this pipeline run
                assoc_result = await session.execute(
                    select(Association).where(
                        Association.user_id == str(event.user_id),
                        Association.source_event_id == str(event_id),
                    )
                )
                new_assocs = assoc_result.scalars().all()

                if new_assocs:
                    # Build entity name map (Entity already imported at top)
                    ent_result = await session.execute(
                        select(Entity).where(Entity.user_id == str(event.user_id))
                    )
                    entity_map = {str(e.id): e.name for e in ent_result.scalars().all()}

                    for assoc in new_assocs:
                        src_name = entity_map.get(str(assoc.source_entity_id), "")
                        tgt_name = entity_map.get(str(assoc.target_entity_id), "")
                        todo_title = None
                        todo_type = "followup"
                        priority = 3  # 1=highest, 5=lowest; default medium

                        atype = assoc.association_type
                        evidence = (assoc.properties or {}).get("evidence", {})

                        if atype == "industry_chain":
                            rel = evidence.get("relation", "")
                            if rel == "potential_investor_startup":
                                todo_title = f"引荐{src_name}和{tgt_name}（投资-创业链）"
                                todo_type = "cooperation_signal"
                                priority = 1  # highest
                            else:
                                todo_title = f"对接{src_name}和{tgt_name}（产业链上下游）"
                                todo_type = "followup"
                                priority = 3  # medium
                        elif atype == "supply_demand":
                            matches = evidence.get("matches", [])
                            if matches:
                                m = matches[0]
                                items = ", ".join(m.get("matched_items", [])[:2])
                                todo_title = f"{m.get('supplier', src_name)} 可帮助 {m.get('requester', tgt_name)} ({items})"
                                todo_type = "help"
                                priority = 1  # highest
                        elif atype == "topic_overlap":
                            todo_title = f"安排{src_name}和{tgt_name}交流（同领域）"
                            todo_type = "followup"
                            priority = 3  # medium
                        elif atype == "same_city":
                            todo_title = f"约{src_name}和{tgt_name}同城见面"
                            todo_type = "care"
                            priority = 4  # low

                        if todo_title:
                            # Check for duplicate
                            existing = await session.execute(
                                select(Todo).where(
                                    Todo.user_id == str(event.user_id),
                                    Todo.title == todo_title,
                                    Todo.status == "pending",
                                )
                            )
                            if not existing.scalar_one_or_none():
                                todo = Todo(
                                    user_id=str(event.user_id),
                                    title=todo_title,
                                    todo_type=todo_type,
                                    priority=priority,
                                    status="pending",
                                    source_event_id=str(event_id),
                                )
                                session.add(todo)

                    await session.commit()
        except Exception as step12_err:
            logger.warning("pipeline_step12_error", error=str(step12_err))

        result.step_timings["step12_assoc_todos"] = time.monotonic() - _t7_5
        result.step_timings["step11_associations"] = time.monotonic() - _t6

        # ── Step 13: Relationship Brief Update (F-47 + F-48) ──
        _t8 = time.monotonic()
        try:
            from eventlink.services.relationship_brief_service import RelationshipBriefService

            async with AsyncSessionLocal() as session:
                brief_service = RelationshipBriefService(session=session, llm_client=llm_client)

                # Re-fetch entities and todos from DB (avoid detached instance issues)
                db_entity_result = await session.execute(
                    select(Entity).where(Entity.source_event_id == str(event_id))
                )
                db_entities = list(db_entity_result.scalars().all())

                db_todo_result = await session.execute(
                    select(Todo).where(Todo.source_event_id == str(event_id))
                )
                db_todos = list(db_todo_result.scalars().all())

                # For each person entity extracted from this event, update their brief
                for entity in db_entities:
                    if entity.entity_type != "person":
                        continue

                    try:
                        brief_result = await brief_service.update_brief_from_event(
                            user_id=str(event.user_id),
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
        result.step_timings["step13_briefs"] = time.monotonic() - _t8

        # Step 14: Mark event as completed (short transaction)
        async with AsyncSessionLocal() as session:
            async with session.begin():
                db_result = await session.execute(
                    select(Event).where(Event.id == str(event_id))
                )
                event = db_result.scalar_one_or_none()
                if event:
                    event.status = "completed"
                    event.processed_at = datetime.now(timezone.utc)

        result.status = "completed"
        result.completed_at = datetime.now(timezone.utc)

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
        result.completed_at = datetime.now(timezone.utc)

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
                        event.processed_at = datetime.now(timezone.utc)
        except Exception:
            logger.error("pipeline_failed_to_mark_failed", event_id=str(event_id))

    finally:
        await llm_client.close()

    return result

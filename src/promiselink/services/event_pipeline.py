"""Event Processing Pipeline — orchestrates the core PromiseLink loop.

Core loop: 互动记录 → InputScope分类 → 实体抽取 → Todo生成 → Promise双向分析 → 通知 → 原始数据存储 → 关联发现 → RelationshipBrief更新 → 状态机
Implements the full processing pipeline from event ingestion to todo generation.

Pipeline stages (13 steps, sequentially numbered):
  Step01 — Verify event + mark processing + input scope + title
  Step02 — Entity extraction + resolution
  Step03 — Entity embedding for semantic search
  Step04 — Todo generation
  Step05 — Promise bidirectional analysis
  Step06 — Resource overuse detection
  Step07 — Priority scoring
  Step08 — Notification
  Step09 — Memory storage
  Step10 — Association discovery
  Step11 — Association → Todo generation
  Step12 — Relationship brief update
  Step13 — Mark event as completed

Uses short transactions to avoid holding SQLite write locks during slow LLM calls.
Each step opens its own session/transaction, commits, and releases the lock.

The actual step logic lives in ``steps/`` subdirectory; this module provides
the public API (``PipelineResult``, ``process_event_with_short_transactions``)
and re-exports the service classes so that existing test patches continue to work.
"""

from datetime import datetime, timezone

from promiselink.core.logging import get_logger
from promiselink.services.llm_client import LLMClient
from promiselink.services.memory_provider import create_memory_provider
from promiselink.services.steps import (
    Step01_VerifyEvent,
    Step02_ExtractEntities,
    Step03_SemanticEmbedding,
    Step04_TodoGeneration,
    Step05_PromiseAnalysis,
    Step06_ResourceOveruse,
    Step07_PriorityScoring,
    Step08_Notification,
    Step09_MemoryStorage,
    Step10_AssociationDiscovery,
    Step11_AssociationTodos,
    Step12_RelationshipBriefUpdate,
    Step13_CompleteEvent,
)
from promiselink.services.steps.context import PipelineContext, PipelineResult
from promiselink.services.title_generator import generate_event_title
from promiselink.services.todo_generator import TodoGenerator
from promiselink.services.association_discovery import AssociationDiscoveryEngine

logger = get_logger("promiselink.pipeline")


# Backward-compatible alias for existing test patches
_generate_event_title = generate_event_title


# ── Pipeline step order ──
# Steps are imported from the steps/ subdirectory.
# Some steps import names from this module at function level
# for test-patch compatibility.

_PIPELINE_STEPS = [
    "Step01_VerifyEvent",
    "Step02_ExtractEntities",
    "Step03_SemanticEmbedding",
    "Step04_TodoGeneration",
    "Step05_PromiseAnalysis",
    "Step06_ResourceOveruse",
    "Step07_PriorityScoring",
    "Step08_Notification",
    "Step09_MemoryStorage",
    "Step10_AssociationDiscovery",
    "Step11_AssociationTodos",
    "Step12_RelationshipBriefUpdate",
    "Step13_CompleteEvent",
]


async def process_event_with_short_transactions(event_id: str) -> PipelineResult:
    """Process an event using short transactions to avoid SQLite lock contention.

    This is the primary entry point for background event processing.
    Each pipeline step opens its own session, commits, and releases the lock
    before the next step begins. This prevents SQLite write locks from
    blocking concurrent API requests during slow LLM calls.

    A global asyncio.Lock serializes pipeline executions to prevent
    concurrent SQLite writes that cause "database is locked" errors.

    Args:
        event_id: The ID of the event to process.

    Returns:
        PipelineResult with entities, todos, and status.
    """
    from promiselink.config import get_settings
    from promiselink.database import get_pipeline_lock

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

    # Build context shared across all steps
    ctx = PipelineContext(
        event_id=str(event_id),
        llm_client=llm_client,
        memory=memory,
        settings=settings,
        result=result,
    )

    # Serialize pipeline executions to prevent SQLite "database is locked" errors.
    # Per-user locking allows different users to process events concurrently.
    # Real-world usage is sequential (events happen at different times), so this
    # does not impact user experience. For PostgreSQL (Phase 1+), remove this lock.

    # Resolve user_id for per-user locking
    _resolved_user_id = ""
    try:
        from promiselink.database import AsyncSessionLocal
        from sqlalchemy import select as _sel
        from promiselink.models.event import Event as _Evt

        async with AsyncSessionLocal() as _sess:
            _r = await _sess.execute(_sel(_Evt.user_id).where(_Evt.id == str(event_id)))
            _row = _r.scalar_one_or_none()
            if _row:
                _resolved_user_id = str(_row)
    except Exception:
        pass

    pipeline_lock = get_pipeline_lock(user_id=_resolved_user_id)
    async with pipeline_lock:
        try:
            steps = [
                Step01_VerifyEvent(),
                Step02_ExtractEntities(),
                Step03_SemanticEmbedding(),
                Step04_TodoGeneration(),
                Step05_PromiseAnalysis(),
                Step06_ResourceOveruse(),
                Step07_PriorityScoring(),
                Step08_Notification(),
                Step09_MemoryStorage(),
                Step10_AssociationDiscovery(),
                Step11_AssociationTodos(),
                Step12_RelationshipBriefUpdate(),
                Step13_CompleteEvent(),
            ]

            for step in steps:
                if ctx.should_stop:
                    break
                ctx = await step.execute(ctx)

            # If pipeline was stopped early (critical step failure), finalize event status
            if ctx.should_stop and result.status not in ("failed", "skipped"):
                from promiselink.database import AsyncSessionLocal
                from promiselink.models.event import Event as _Event
                from sqlalchemy import select as _select

                # Determine if LLM failure → awaiting_retry (user can retry later)
                # vs other failures → failed
                llm_failed = any(
                    "extract" in s or "verify" in s or "scope" in s
                    for s in ctx.failed_steps
                )
                final_status = "awaiting_retry" if llm_failed else "failed"

                result.status = final_status
                result.failed_steps = list(ctx.failed_steps)
                result.completed_at = datetime.now(timezone.utc)

                try:
                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            db_result = await session.execute(
                                _select(_Event).where(_Event.id == str(event_id))
                            )
                            event = db_result.scalar_one_or_none()
                            if event and event.status == "processing":
                                event.status = final_status
                                event.processed_at = datetime.now(timezone.utc)
                                if ctx.failed_steps:
                                    event.failed_steps = list(ctx.failed_steps)
                except Exception as mark_err:
                    logger.error("pipeline_failed_to_mark_partial", event_id=str(event_id), error=str(mark_err))

        except Exception as e:
            from promiselink.database import AsyncSessionLocal
            from sqlalchemy import select
            from promiselink.models.event import Event as _Event

            logger.exception("pipeline_error", event_id=str(event_id), error=str(e))
            result.status = "failed"
            result.error = str(e)
            result.completed_at = datetime.now(timezone.utc)

            # Try to mark event as failed
            try:
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        db_result = await session.execute(
                            select(_Event).where(_Event.id == str(event_id))
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

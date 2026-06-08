"""Event Processing Pipeline — orchestrates the core EventLink loop.

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

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity
from eventlink.models.todo import Todo
from eventlink.services.association_discovery import AssociationDiscoveryEngine
from eventlink.services.entity_extractor import EntityExtractor, ExtractionResult
from eventlink.services.entity_resolution import EntityResolutionEngine
from eventlink.services.llm_client import LLMClient
from eventlink.services.memory_provider import create_memory_provider
from eventlink.services.steps.context import PipelineContext
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

    Args:
        event_id: The ID of the event to process.

    Returns:
        PipelineResult with entities, todos, and status.
    """
    from eventlink.config import get_settings

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

    try:
        # Instantiate step objects
        from eventlink.services.steps import (
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

    except Exception as e:
        from eventlink.database import AsyncSessionLocal
        from sqlalchemy import select
        from eventlink.models.event import Event as _Event

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

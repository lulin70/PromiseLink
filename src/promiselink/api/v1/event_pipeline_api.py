"""Pipeline-related endpoints for events.

Contains endpoints for retrying failed events, accepting degraded
processing results, and applying user corrections (纠偏) to parsed
event results. Registered as a sub-router of the main events router.

W5 cross-language association (跨语言实体关联) adds server-side candidate
issuance endpoints and a two-phase correction flow: every W5-backed item is
verified (opaque candidate token → candidate digest recomputation → operation
state lookup) BEFORE any business mutation runs, so invalid tokens cause zero
writes (T-W5-15).
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.v1.events import EventCreateRequest, EventCreateResponse, EventResponse
from promiselink.config import get_settings
from promiselink.core.auth import (
    candidate_token_hash,
    get_current_user_id,
    issue_candidate_token,
    verify_candidate_token,
)
from promiselink.core.exceptions import (
    CandidateTokenError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import commit_with_retry, get_async_session, get_pipeline_lock
from promiselink.models import Association, Entity, Event
from promiselink.models.entity_correction import EntityCorrection
from promiselink.models.todo import Todo as _Todo
from promiselink.services.entity_correction_service import record_correction
from promiselink.services.entity_merge_service import merge_entities
from promiselink.services.event_processor import process_event_background
from promiselink.services.w5_operation_service import (
    W5Candidate,
    build_result_summary,
    claim_operation,
    complete_operation,
    compute_candidate_digest,
    create_issued_operation,
    find_operation_by_token_hash,
    generate_entity_candidates,
    generate_todo_candidates,
)

logger = get_logger("promiselink.api.events")
pipeline_router = APIRouter()

__all__ = ["pipeline_router"]


class BatchEventCreateRequest(BaseModel):
    """Request schema for batch creating events."""

    events: list[EventCreateRequest] = Field(
        ..., min_length=1, max_length=20, description="List of events to create (max 20 per batch)"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "events": [
                    {
                        "event_type": "meeting",
                        "source": "manual",
                        "title": "上午与李总讨论合作",
                        "raw_text": "今天上午和李总讨论了新项目的合作方案...",
                    },
                    {
                        "event_type": "call",
                        "source": "manual",
                        "title": "下午与陈宇鑫电话沟通",
                        "raw_text": "和陈宇鑫通了电话，确认了技术对接的时间...",
                    },
                ]
            }
        }
    }


class BatchEventCreateResponse(BaseModel):
    """Response schema for batch event creation."""

    created: list[EventCreateResponse]
    failed: list[dict[str, Any]]
    total_requested: int
    total_created: int


@pipeline_router.post("/events/batch", response_model=BatchEventCreateResponse, status_code=201)
async def batch_create_events(
    request: BatchEventCreateRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> BatchEventCreateResponse:
    """
    Batch create events and trigger processing pipeline for each.

    Accepts up to 20 events in a single request. Each event is created
    independently — if one fails, others still succeed. Pipeline processing
    runs serially in the background (one at a time) to avoid SQLite lock contention.
    """
    new_request_id()

    valid_types = Event.VALID_TYPES
    created: list[EventCreateResponse] = []
    failed: list[dict[str, Any]] = []

    for idx, event_req in enumerate(request.events):
        try:
            # Validate event type
            if event_req.event_type not in valid_types:
                failed.append(
                    {
                        "index": idx,
                        "error": f"Invalid event_type: {event_req.event_type}",
                    }
                )
                continue

            # Validate raw_text size
            if event_req.raw_text and len(event_req.raw_text.encode("utf-8")) > 512000:
                failed.append(
                    {
                        "index": idx,
                        "error": "raw_text exceeds 500KB limit",
                    }
                )
                continue

            event = Event(
                user_id=user_id,
                event_type=event_req.event_type,
                source=event_req.source,
                title=event_req.title,
                timestamp=event_req.timestamp or datetime.now(UTC),
                raw_text=event_req.raw_text,
                metadata_=event_req.metadata,
                status="pending",
            )

            session.add(event)
            await session.commit()
            await session.refresh(event)

            # Queue pipeline processing (runs serially via Pipeline lock)
            background_tasks.add_task(process_event_background, event_id=event.id)

            created.append(
                EventCreateResponse(
                    id=str(event.id),
                    user_id=str(event.user_id),
                    event_type=event.event_type,
                    source=event.source,
                    title=event.title,
                    timestamp=event.timestamp,
                    status=event.status,
                    created_at=event.created_at,
                    pipeline_status="pending",
                    entity_count=0,
                    todo_count=0,
                    entities=[],
                )
            )

            logger.info(
                "batch_event_created",
                event_id=str(event.id),
                batch_index=idx,
                event_type=event.event_type,
            )

        except SQLAlchemyError as e:
            logger.warning("batch_event_create_failed", index=idx, error=str(e))
            failed.append(
                {
                    "index": idx,
                    "error": str(e),
                }
            )
            # Rollback this event but continue with others
            await session.rollback()

    return BatchEventCreateResponse(
        created=created,
        failed=failed,
        total_requested=len(request.events),
        total_created=len(created),
    )


@pipeline_router.post("/events/{event_id}/retry", response_model=EventResponse)
async def retry_event(
    event_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Retry processing an event that failed or is awaiting retry.

    Resets event status to pending and re-triggers the pipeline.
    Only works for events in 'failed' or 'awaiting_retry' status.
    """

    new_request_id()

    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id,
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    if event.status not in ("failed", "awaiting_retry"):
        raise ValidationError("Event is not in a retryable state")

    # Reset status and re-trigger pipeline
    event.status = "pending"
    event.processed_at = None
    event.failed_steps = None
    await session.commit()

    background_tasks.add_task(process_event_background, event_id=event_id)

    logger.info("event_retry_triggered", event_id=str(event_id))

    # Refresh to get updated state
    await session.refresh(event)
    return event


@pipeline_router.post("/events/{event_id}/accept-degraded", response_model=EventResponse)
async def accept_degraded_event(
    event_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> Any:
    """Accept degraded processing result for an event awaiting retry.

    Marks the event as degraded_completed, preserving whatever partial
    results were generated. User explicitly chooses this over retrying.
    """
    new_request_id()

    result = await session.execute(
        select(Event).where(
            Event.id == str(event_id),
            Event.user_id == user_id,
        )
    )
    event = result.scalar_one_or_none()

    if not event:
        raise NotFoundError("Event not found")

    if event.status not in ("awaiting_retry", "failed"):
        raise ValidationError("Event is not in a degradable state")

    event.status = "degraded_completed"
    event.processed_at = datetime.now(UTC)
    await session.commit()

    logger.info("event_degraded_accepted", event_id=str(event_id))

    await session.refresh(event)
    return event


# ── Event Correction (纠偏) ──


class CorrectedEntityItem(BaseModel):
    """User-corrected entity mapping (人脉纠偏).

    W5 跨语言候选决策: 携带 candidate_token + resolution_action(confirm|reject)
    的条目走 W5 token 验证路径; 其余字段走 W3 legacy 路径。客户端提交的
    candidate IDs 仅作兼容展示, 不作为可信事实。
    """

    extracted_entity_id: str = Field(..., description="AI 提取的实体 ID")
    action: str = Field(..., description="select_existing | create_new | ignore")
    selected_entity_id: str | None = Field(
        default=None, description="选择已有实体 ID (select_existing / W5 confirm)"
    )
    new_name: str | None = Field(default=None, description="新名称 (create_new)")
    new_company: str | None = Field(default=None, description="新公司 (create_new)")
    new_title: str | None = Field(default=None, description="新职位 (create_new)")
    # ── W5 跨语言候选决策字段 ──
    candidate_token: str | None = Field(
        default=None,
        description="W5 opaque candidate token (来自 candidates 端点, 原样携带)",
    )
    resolution_action: str | None = Field(
        default=None, description="W5: confirm | reject (confirm-only 语义)"
    )


class CorrectedTodoItem(BaseModel):
    """User-corrected todo (待办纠偏).

    W5 跨语言 Todo 关联: candidate_token + resolution_action 走 token 验证
    路径; id 为 source todo ID, selected_todo_id 为确认的候选 Todo ID。
    """

    id: str | None = Field(default=None, description="已有待办 ID，None 表示新增")
    title: str
    description: str | None = None
    due_date: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    related_entity_id: str | None = None
    action: str = Field(..., description="edit | delete | add")
    # ── W5 跨语言候选决策字段 ──
    candidate_token: str | None = Field(default=None, description="W5 opaque candidate token")
    resolution_action: str | None = Field(
        default=None, description="W5: confirm | reject"
    )
    selected_todo_id: str | None = Field(
        default=None, description="W5 confirm 目标候选 Todo ID"
    )


class CorrectedPromiseItem(BaseModel):
    """User-corrected promise (承诺纠偏)."""

    id: str | None = Field(default=None, description="已有承诺(待办) ID，add 动作时为 None")
    content: str | None = Field(default=None, description="修改后的内容 / add 动作时为承诺内容")
    due_date: datetime | None = Field(default=None, description="截止日期")
    promise_type: str | None = Field(default=None, description="my_promise | their_promise")
    promisor_id: str | None = Field(default=None, description="add 动作时责任人 ID")
    beneficiary_id: str | None = Field(default=None, description="add 动作时受益人 ID")
    action: str = Field(..., description="confirm | ignore | modify | add")


class CorrectedAssociationItem(BaseModel):
    """User-corrected association (关系纠偏)."""

    source_entity_id: str = Field(..., description="源实体 ID")
    target_entity_id: str = Field(..., description="目标实体 ID")
    relationship_type: str | None = Field(default=None, description="修改后的关系类型")
    strength: float | None = Field(default=None, description="修改后的关系强度 0-1")
    action: str = Field(..., description="modify | delete")


class EventCorrectRequest(BaseModel):
    """Request schema for event correction (纠偏提交)."""

    corrected_entities: list[CorrectedEntityItem] = Field(default_factory=list)
    corrected_todos: list[CorrectedTodoItem] = Field(default_factory=list)
    corrected_promises: list[CorrectedPromiseItem] = Field(default_factory=list)
    corrected_associations: list[CorrectedAssociationItem] = Field(default_factory=list)


class W5CorrectionResult(BaseModel):
    """Per-item W5 operation outcome (含 replay 语义)."""

    scope_type: str
    resource_id: str
    action: str
    operation_status: str
    replayed: bool = False
    result_summary: dict[str, Any] | None = None


class EventCorrectResponse(BaseModel):
    """Response schema for event correction."""

    event_id: str
    entities_updated: int = 0
    entities_created: int = 0
    entities_ignored: int = 0
    todos_updated: int = 0
    todos_deleted: int = 0
    todos_created: int = 0
    promises_confirmed: int = 0
    promises_ignored: int = 0
    promises_modified: int = 0
    promises_created: int = 0
    associations_updated: int = 0
    w5_operations: list[W5CorrectionResult] = Field(default_factory=list)


class W5CandidateOut(BaseModel):
    """Sanitized candidate projection (最小化展示字段)."""

    candidate_id: str
    rank: int
    score: float
    method: str
    label: str
    language_pair: str
    confirm_only: bool = True


class W5CandidatesResponse(BaseModel):
    """Server-issued candidate set + opaque candidate token.

    candidate_token 必须原样携带回 correct 端点; 客户端不能拼装或修改。
    candidate_set_id 仅作展示/关联标识, 不能替代 token。
    """

    candidate_set_id: str
    scope_type: str
    resource_id: str
    candidates: list[W5CandidateOut]
    candidate_token: str
    expires_at: str
    confirm_only: bool = True


@dataclass
class _W5Plan:
    """Preflight result for one W5-backed correction item."""

    scope_type: str
    resource_id: str
    action: str  # confirm | reject
    token: str
    payload: dict[str, Any] | None  # None only for terminal replay
    operation: EntityCorrection | None
    selected_id: str | None = None
    candidate: W5Candidate | None = None
    candidate_ids: list[str] = field(default_factory=list)
    candidate_digest: str | None = None
    original_name: str | None = None
    replayed: bool = False


# ── W5 candidate issuance (候选查询不写业务数据/alias, 仅持久化 token hash
#    与 operation metadata — TECH_DESIGN §7.1) ──


def _w5_candidates_out(candidates: list[W5Candidate]) -> list[W5CandidateOut]:
    return [
        W5CandidateOut(
            candidate_id=c.candidate_id,
            rank=c.rank,
            score=c.score,
            method=c.method,
            label=c.label,
            language_pair=c.language_pair,
            confirm_only=c.confirm_only,
        )
        for c in candidates
    ]


@pipeline_router.get(
    "/events/{event_id}/entities/{extracted_entity_id}/candidates",
    response_model=W5CandidatesResponse,
)
async def get_entity_candidates(
    event_id: uuid.UUID,
    extracted_entity_id: str,
    limit: int = Query(default=10, ge=1, le=20),
    include_ambiguous: bool = True,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> W5CandidatesResponse:
    """Issue server-ranked entity candidates + opaque candidate token (W5).

    复用服务端候选生成与评分; 客户端不能控制 score/method/resolver/space。
    仅持久化 token hash 与 operation metadata (operation_status=issued)。
    """
    new_request_id()
    settings = get_settings()
    if not settings.cross_language_enabled:
        raise ValidationError("Cross-language association is disabled")

    event = await _get_owned_event(session, user_id, str(event_id))
    if event is None:
        raise NotFoundError("Event not found")

    extracted = await _get_event_entity(
        session, user_id, str(event_id), extracted_entity_id
    )
    if extracted is None:
        raise NotFoundError("Extracted entity not found for this event")

    candidates = await generate_entity_candidates(
        session,
        user_id=user_id,
        extracted_entity=extracted,
        limit=limit,
        include_ambiguous=include_ambiguous,
    )
    candidate_ids = [c.candidate_id for c in candidates]
    digest = compute_candidate_digest("entity", str(extracted.id), candidate_ids)
    token, payload = issue_candidate_token(
        user_id=user_id,
        event_id=str(event_id),
        scope_type="entity",
        resource_id=str(extracted.id),
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
    )
    await create_issued_operation(
        session,
        user_id=user_id,
        event_id=str(event_id),
        scope_type="entity",
        resource_id=str(extracted.id),
        candidate_ids=candidate_ids,
        candidate_digest=digest,
        token=token,
        token_payload=payload,
    )
    await session.commit()

    logger.info(
        "w5_entity_candidates_issued",
        event_id=str(event_id),
        extracted_entity_id=extracted_entity_id,
        candidate_count=len(candidates),
    )
    return W5CandidatesResponse(
        candidate_set_id=f"w5cs-{payload['nonce'][:12]}",
        scope_type="entity",
        resource_id=str(extracted.id),
        candidates=_w5_candidates_out(candidates),
        candidate_token=token,
        expires_at=str(payload["expires_at"]),
    )


@pipeline_router.get(
    "/events/{event_id}/entities/{extracted_entity_id}/todos/candidates",
    response_model=W5CandidatesResponse,
)
async def get_todo_candidates(
    event_id: uuid.UUID,
    extracted_entity_id: str,
    source_todo_id: str = Query(..., description="新提取的 source Todo ID"),
    limit: int = Query(default=10, ge=1, le=20),
    include_ambiguous: bool = True,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> W5CandidatesResponse:
    """Issue server-ranked todo association candidates + opaque token (W5)."""
    new_request_id()
    settings = get_settings()
    if not settings.cross_language_todo_enabled:
        raise ValidationError("Cross-language todo association is disabled")

    event = await _get_owned_event(session, user_id, str(event_id))
    if event is None:
        raise NotFoundError("Event not found")

    extracted = await _get_event_entity(
        session, user_id, str(event_id), extracted_entity_id
    )
    if extracted is None:
        raise NotFoundError("Extracted entity not found for this event")

    todo_result = await session.execute(
        select(_Todo).where(
            _Todo.id == source_todo_id,
            _Todo.user_id == user_id,
            _Todo.source_event_id == str(event_id),
        )
    )
    source_todo: _Todo | None = todo_result.scalar_one_or_none()
    if source_todo is None:
        raise NotFoundError("Source todo not found for this event")

    candidates = await generate_todo_candidates(
        session,
        user_id=user_id,
        source_todo=source_todo,
        limit=limit,
        include_ambiguous=include_ambiguous,
    )
    candidate_ids = [c.candidate_id for c in candidates]
    digest = compute_candidate_digest("todo", str(source_todo.id), candidate_ids)
    token, payload = issue_candidate_token(
        user_id=user_id,
        event_id=str(event_id),
        scope_type="todo",
        resource_id=str(source_todo.id),
        candidate_digest=digest,
        operation_key=f"w5-{uuid.uuid4()}",
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
    )
    await create_issued_operation(
        session,
        user_id=user_id,
        event_id=str(event_id),
        scope_type="todo",
        resource_id=str(source_todo.id),
        candidate_ids=candidate_ids,
        candidate_digest=digest,
        token=token,
        token_payload=payload,
    )
    await session.commit()

    logger.info(
        "w5_todo_candidates_issued",
        event_id=str(event_id),
        source_todo_id=source_todo_id,
        candidate_count=len(candidates),
    )
    return W5CandidatesResponse(
        candidate_set_id=f"w5cs-{payload['nonce'][:12]}",
        scope_type="todo",
        resource_id=str(source_todo.id),
        candidates=_w5_candidates_out(candidates),
        candidate_token=token,
        expires_at=str(payload["expires_at"]),
    )


# ── W5 two-phase correction helpers ──


async def _get_owned_event(
    session: AsyncSession, user_id: str, event_id: str
) -> Event | None:
    result = await session.execute(
        select(Event).where(Event.id == event_id, Event.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_event_entity(
    session: AsyncSession, user_id: str, event_id: str, entity_id: str
) -> Entity | None:
    """Load an entity bound to user AND event (三界一致校验)."""
    result = await session.execute(
        select(Entity).where(
            Entity.id == entity_id,
            Entity.user_id == user_id,
            Entity.source_event_id == event_id,
        )
    )
    return result.scalar_one_or_none()


def _resolve_w5_action(item_action: str | None) -> str:
    if item_action not in ("confirm", "reject"):
        raise ValidationError("resolution_action must be 'confirm' or 'reject'")
    return item_action


async def _preflight_w5_entity(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    item: CorrectedEntityItem,
    settings: Any,
) -> _W5Plan:
    """Verify token/digest/operation for one W5 entity item (zero writes)."""
    token = item.candidate_token
    if not token:
        raise ValidationError("candidate_token is required for W5 resolution")
    action = _resolve_w5_action(item.resolution_action)

    extracted = await _get_event_entity(
        session, user_id, event_id, item.extracted_entity_id
    )
    if extracted is None:
        raise NotFoundError("Extracted entity not found for this event")

    operation = await find_operation_by_token_hash(
        session, token_hash=candidate_token_hash(token)
    )

    if operation is not None and operation.operation_status in ("confirmed", "rejected"):
        # Terminal replay: full binding re-verification, TTL intentionally
        # bypassed (T-W5-10/T-W5-11 — completed replay 优先于 TTL).
        payload = verify_candidate_token(
            token,
            authenticated_user_id=user_id,
            event_id=event_id,
            scope_type="entity",
            extracted_entity_id=item.extracted_entity_id,
            allow_expired_for_replay=True,
        )
        return _W5Plan(
            scope_type="entity",
            resource_id=item.extracted_entity_id,
            action=action,
            token=token,
            payload=payload,
            operation=operation,
            replayed=True,
        )

    # Server-side candidate recomputation → digest (T-W5-07).
    candidates = await generate_entity_candidates(
        session, user_id=user_id, extracted_entity=extracted
    )
    candidate_ids = [c.candidate_id for c in candidates]
    digest = compute_candidate_digest("entity", item.extracted_entity_id, candidate_ids)

    payload = verify_candidate_token(
        token,
        authenticated_user_id=user_id,
        event_id=event_id,
        scope_type="entity",
        extracted_entity_id=item.extracted_entity_id,
        candidate_digest=digest,
        operation_key=operation.operation_key if operation else None,
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
    )

    selected_id: str | None = None
    selected_candidate: W5Candidate | None = None
    if action == "confirm":
        if not item.selected_entity_id:
            raise ValidationError("selected_entity_id is required to confirm a candidate")
        selected_candidate = next(
            (c for c in candidates if c.candidate_id == item.selected_entity_id), None
        )
        if selected_candidate is None:
            # 客户端提交的候选 ID 不在服务端重算集合内 — 不作为可信事实。
            raise ValidationError("selected entity is not in the verified candidate set")
        selected_id = item.selected_entity_id

    return _W5Plan(
        scope_type="entity",
        resource_id=item.extracted_entity_id,
        action=action,
        token=token,
        payload=payload,
        operation=operation,
        selected_id=selected_id,
        candidate=selected_candidate,
        candidate_ids=candidate_ids,
        candidate_digest=digest,
        original_name=extracted.name,
    )


async def _preflight_w5_todo(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    item: CorrectedTodoItem,
    settings: Any,
) -> _W5Plan:
    """Verify token/digest/operation for one W5 todo item (zero writes)."""
    token = item.candidate_token
    if not token:
        raise ValidationError("candidate_token is required for W5 resolution")
    if not item.id:
        raise ValidationError("source todo id is required for W5 todo resolution")
    action = _resolve_w5_action(item.resolution_action)

    todo_result = await session.execute(
        select(_Todo).where(
            _Todo.id == item.id,
            _Todo.user_id == user_id,
            _Todo.source_event_id == event_id,
        )
    )
    source_todo: _Todo | None = todo_result.scalar_one_or_none()
    if source_todo is None:
        raise NotFoundError("Source todo not found for this event")

    operation = await find_operation_by_token_hash(
        session, token_hash=candidate_token_hash(token)
    )

    if operation is not None and operation.operation_status in ("confirmed", "rejected"):
        payload = verify_candidate_token(
            token,
            authenticated_user_id=user_id,
            event_id=event_id,
            scope_type="todo",
            source_todo_id=item.id,
            allow_expired_for_replay=True,
        )
        return _W5Plan(
            scope_type="todo",
            resource_id=item.id,
            action=action,
            token=token,
            payload=payload,
            operation=operation,
            replayed=True,
        )

    candidates = await generate_todo_candidates(
        session, user_id=user_id, source_todo=source_todo
    )
    candidate_ids = [c.candidate_id for c in candidates]
    digest = compute_candidate_digest("todo", item.id, candidate_ids)

    payload = verify_candidate_token(
        token,
        authenticated_user_id=user_id,
        event_id=event_id,
        scope_type="todo",
        source_todo_id=item.id,
        candidate_digest=digest,
        operation_key=operation.operation_key if operation else None,
        resolver_version=settings.cross_language_resolver_version,
        score_version=settings.cross_language_score_version,
        embedding_space=settings.cross_language_embedding_space,
    )

    selected_id: str | None = None
    selected_candidate: W5Candidate | None = None
    if action == "confirm":
        if not item.selected_todo_id:
            raise ValidationError("selected_todo_id is required to confirm a candidate")
        selected_candidate = next(
            (c for c in candidates if c.candidate_id == item.selected_todo_id), None
        )
        if selected_candidate is None:
            raise ValidationError("selected todo is not in the verified candidate set")
        selected_id = item.selected_todo_id

    return _W5Plan(
        scope_type="todo",
        resource_id=item.id,
        action=action,
        token=token,
        payload=payload,
        operation=operation,
        selected_id=selected_id,
        candidate=selected_candidate,
        candidate_ids=candidate_ids,
        candidate_digest=digest,
        original_name=source_todo.title,
    )


def _w5_replay_result(plan: _W5Plan) -> W5CorrectionResult:
    operation = plan.operation
    assert operation is not None  # replay plans always carry the terminal row
    return W5CorrectionResult(
        scope_type=plan.scope_type,
        resource_id=plan.resource_id,
        action=plan.action,
        operation_status=operation.operation_status,
        replayed=True,
        result_summary=dict(operation.result_summary or {}),
    )


async def _claim_or_fail(plan: _W5Plan, session: AsyncSession) -> EntityCorrection:
    """Claim the operation (CAS) or raise/return-replay for non-issued states."""
    operation = plan.operation
    if operation is None:
        # Submission-time operation row creation (e.g. lost issuance row):
        # metadata comes from the verified token payload.
        assert plan.payload is not None and plan.candidate_digest is not None
        operation = await create_issued_operation(
            session,
            user_id=str(plan.payload["user_id"]),
            event_id=str(plan.payload["event_id"]),
            scope_type=plan.scope_type,
            resource_id=plan.resource_id,
            candidate_ids=plan.candidate_ids,
            candidate_digest=plan.candidate_digest,
            token=plan.token,
            token_payload=plan.payload,
        )
        operation.operation_status = "pending"
        return operation

    outcome = await claim_operation(session, operation)
    if outcome in ("confirmed", "rejected"):
        plan.replayed = True
        return operation
    if outcome == "in_progress":
        raise ConflictError("W5 operation is already in progress")
    if outcome == "expired":
        raise CandidateTokenError(
            "CANDIDATE_TOKEN_EXPIRED", "candidate token operation has expired"
        )
    return operation


async def _execute_w5_entity(
    session: AsyncSession,
    *,
    user_id: str,
    plan: _W5Plan,
    resp: EventCorrectResponse,
) -> W5CorrectionResult:
    operation = await _claim_or_fail(plan, session)
    if plan.replayed:
        return _w5_replay_result(plan)

    if plan.action == "confirm":
        # Server-side re-read of the selected candidate (主数据库权威).
        assert plan.selected_id is not None
        sel_result = await session.execute(
            select(Entity).where(
                Entity.id == plan.selected_id,
                Entity.user_id == user_id,
                Entity.status != "deleted",
            )
        )
        selected_entity = sel_result.scalar_one_or_none()
        if selected_entity is None:
            raise NotFoundError("Selected entity no longer exists")
        original_name = plan.original_name
        await merge_entities(
            session,
            user_id=user_id,
            target_id=plan.selected_id,
            source_id=plan.resource_id,
        )
        complete_operation(
            operation,
            status="confirmed",
            action="select_existing",
            result_summary=build_result_summary(plan.candidate),
            selected_entity_id=plan.selected_id,
            original_canonical_name=original_name,
        )
        resp.entities_updated += 1
    else:
        complete_operation(
            operation,
            status="rejected",
            action="ignore",
            result_summary=build_result_summary(None),
            original_canonical_name=plan.original_name,
        )

    return W5CorrectionResult(
        scope_type="entity",
        resource_id=plan.resource_id,
        action=plan.action,
        operation_status=operation.operation_status,
        replayed=False,
        result_summary=dict(operation.result_summary or {}),
    )


async def _execute_w5_todo(
    session: AsyncSession,
    *,
    user_id: str,
    plan: _W5Plan,
    resp: EventCorrectResponse,
) -> W5CorrectionResult:
    operation = await _claim_or_fail(plan, session)
    if plan.replayed:
        return _w5_replay_result(plan)

    if plan.action == "confirm":
        assert plan.selected_id is not None
        sel_result = await session.execute(
            select(_Todo).where(
                _Todo.id == plan.selected_id,
                _Todo.user_id == user_id,
            )
        )
        selected_todo: _Todo | None = sel_result.scalar_one_or_none()
        if selected_todo is None:
            raise NotFoundError("Selected todo no longer exists")
        src_result = await session.execute(
            select(_Todo).where(
                _Todo.id == plan.resource_id,
                _Todo.user_id == user_id,
            )
        )
        source_todo: _Todo | None = src_result.scalar_one_or_none()
        if source_todo is None:
            raise NotFoundError("Source todo no longer exists")
        # 复用既有 Todo 关联路径: 对齐实体关联 (TECH_DESIGN §8.3).
        source_todo.related_entity_id = selected_todo.related_entity_id
        complete_operation(
            operation,
            status="confirmed",
            action="confirm",
            result_summary=build_result_summary(plan.candidate),
            selected_todo_id=plan.selected_id,
            original_extracted_text=source_todo.title,
        )
        resp.todos_updated += 1
    else:
        # 拒绝不修改原 Todo, 仅记录审计事实 (冷却由审计计算)。
        complete_operation(
            operation,
            status="rejected",
            action="ignore",
            result_summary=build_result_summary(None),
            original_extracted_text=plan.original_name,
        )

    return W5CorrectionResult(
        scope_type="todo",
        resource_id=plan.resource_id,
        action=plan.action,
        operation_status=operation.operation_status,
        replayed=False,
        result_summary=dict(operation.result_summary or {}),
    )


@pipeline_router.post("/events/{event_id}/correct", response_model=EventCorrectResponse)
async def correct_event(
    event_id: uuid.UUID,
    request: EventCorrectRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> EventCorrectResponse:
    """Apply user corrections to parsed event results (解析后纠偏).

    五类纠偏:
    - 人脉: select_existing(合并到已有) / create_new(更新提取实体信息) / ignore(忽略)
    - 关系: modify(修改关系类型/强度) / delete(删除关系)
    - 待办: edit(修改) / delete(删除) / add(新增)
    - 承诺: confirm(确认) / ignore(忽略) / modify(修改) / add(手动补录)

    W5 两阶段执行 (TECH_DESIGN §7.2):
    Phase 1 — 全量 preflight: 所有 W5 条目先完成 token 验证/候选重算/operation
    查询, 任何失败直接抛出, 零业务写入 (T-W5-15)。
    Phase 2 — per-user 锁内执行 legacy 迁移 + W5 认领/变更/审计, 一次提交。
    """
    new_request_id()
    settings = get_settings()

    # Verify event exists and belongs to user
    event = await _get_owned_event(session, user_id, str(event_id))
    if not event:
        raise NotFoundError("Event not found")

    resp = EventCorrectResponse(event_id=str(event_id))

    # ── Phase 1: W5 preflight (zero writes — raise before any mutation) ──
    w5_entity_plans: list[_W5Plan] = []
    legacy_entities: list[CorrectedEntityItem] = []
    for ent_item in request.corrected_entities:
        if ent_item.candidate_token or ent_item.resolution_action:
            w5_entity_plans.append(
                await _preflight_w5_entity(
                    session, user_id=user_id, event_id=str(event_id),
                    item=ent_item, settings=settings,
                )
            )
        else:
            legacy_entities.append(ent_item)

    w5_todo_plans: list[_W5Plan] = []
    legacy_todos: list[CorrectedTodoItem] = []
    for todo_item in request.corrected_todos:
        if todo_item.candidate_token or todo_item.resolution_action:
            w5_todo_plans.append(
                await _preflight_w5_todo(
                    session, user_id=user_id, event_id=str(event_id),
                    item=todo_item, settings=settings,
                )
            )
        else:
            legacy_todos.append(todo_item)

    # ── Phase 2: serialized execution + single commit ──
    lock = get_pipeline_lock(user_id)
    async with lock:
        # ── 人脉纠偏 (W3 legacy path) ──
        for ent_item in legacy_entities:
            # Fetch the extracted entity (user + event 双绑定, 防跨事件操作)
            ent_result = await session.execute(
                select(Entity).where(
                    Entity.id == ent_item.extracted_entity_id,
                    Entity.user_id == user_id,
                    Entity.source_event_id == str(event_id),
                )
            )
            extracted = ent_result.scalar_one_or_none()
            if not extracted:
                continue

            if ent_item.action == "select_existing" and ent_item.selected_entity_id:
                # Reuse the canonical merge path so todos, associations, and embeddings migrate atomically.
                original_name = extracted.name
                await merge_entities(
                    session,
                    user_id=user_id,
                    target_id=ent_item.selected_entity_id,
                    source_id=ent_item.extracted_entity_id,
                )
                resp.entities_updated += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="entity",
                    action="select_existing",
                    entity_id=ent_item.extracted_entity_id,
                    original_canonical_name=original_name,
                    selected_entity_id=ent_item.selected_entity_id,
                )

            elif ent_item.action == "create_new":
                # Update extracted entity with user-provided info
                if ent_item.new_name:
                    extracted.name = ent_item.new_name
                    extracted.canonical_name = ent_item.new_name
                if ent_item.new_company or ent_item.new_title:
                    props = dict(extracted.properties or {})
                    basic_val = props.get("basic")
                    basic = dict(basic_val) if isinstance(basic_val, dict) else {}
                    if ent_item.new_company:
                        basic["company"] = ent_item.new_company
                    if ent_item.new_title:
                        basic["title"] = ent_item.new_title
                    props["basic"] = basic
                    extracted.properties = props
                    from sqlalchemy.orm.attributes import flag_modified

                    flag_modified(extracted, "properties")
                extracted.status = "confirmed"
                resp.entities_created += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="entity",
                    action="create_new",
                    entity_id=extracted.id and str(extracted.id),
                    original_canonical_name=extracted.name,
                    original_extracted_text=f"new_company={ent_item.new_company or ''}; new_title={ent_item.new_title or ''}",
                )

            elif ent_item.action == "ignore":
                extracted.status = "deleted"
                resp.entities_ignored += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="entity",
                    action="ignore",
                    entity_id=extracted.id and str(extracted.id),
                    original_canonical_name=extracted.name,
                )

        # ── 待办纠偏 (W3 legacy path) ──
        for todo_item in legacy_todos:
            if todo_item.action == "add":
                new_todo = _Todo(
                    user_id=user_id,
                    todo_type="followup",
                    title=todo_item.title,
                    description=todo_item.description,
                    due_date=todo_item.due_date,
                    priority=todo_item.priority,
                    related_entity_id=todo_item.related_entity_id,
                    source_event_id=str(event_id),
                    status="pending",
                )
                session.add(new_todo)
                resp.todos_created += 1

            elif todo_item.action == "delete" and todo_item.id:
                del_result = await session.execute(
                    select(_Todo).where(
                        _Todo.id == todo_item.id,
                        _Todo.user_id == user_id,
                        _Todo.source_event_id == str(event_id),
                    )
                )
                todo_to_delete: _Todo | None = del_result.scalar_one_or_none()
                if todo_to_delete:
                    await session.delete(todo_to_delete)
                    resp.todos_deleted += 1

            elif todo_item.action == "edit" and todo_item.id:
                edit_result = await session.execute(
                    select(_Todo).where(
                        _Todo.id == todo_item.id,
                        _Todo.user_id == user_id,
                        _Todo.source_event_id == str(event_id),
                    )
                )
                todo_to_edit: _Todo | None = edit_result.scalar_one_or_none()
                if todo_to_edit:
                    todo_to_edit.title = todo_item.title
                    if todo_item.description is not None:
                        todo_to_edit.description = todo_item.description
                    todo_to_edit.due_date = todo_item.due_date
                    todo_to_edit.priority = todo_item.priority
                    todo_to_edit.related_entity_id = todo_item.related_entity_id  # type: ignore[assignment]
                    resp.todos_updated += 1

        # ── 承诺纠偏 ──
        for prom_item in request.corrected_promises:
            if prom_item.action == "add":
                # 纠偏5：承诺添加（手动补录）
                if not prom_item.content:
                    continue
                promisor_id = prom_item.promisor_id
                beneficiary_id = prom_item.beneficiary_id
                # 如果未指定，尝试从事件关联实体中推断
                if not promisor_id or not beneficiary_id:
                    ent_result = await session.execute(
                        select(Entity).where(
                            Entity.source_event_id == str(event_id),
                            Entity.user_id == user_id,
                            Entity.status != "deleted",
                        )
                    )
                    related_entities = ent_result.scalars().all()
                    if related_entities:
                        # 简单策略：my_promise 时 promisor 为当前用户(隐式)，
                        # beneficiary 为第一个关联实体；their_promise 时反过来
                        counterparty_id = str(related_entities[0].id)
                        if prom_item.promise_type == "their_promise":
                            promisor_id = promisor_id or counterparty_id
                        else:
                            beneficiary_id = beneficiary_id or counterparty_id
                new_promise = _Todo(
                    user_id=user_id,
                    title=prom_item.content[:200],
                    description=prom_item.content,
                    todo_type="promise",
                    action_type=prom_item.promise_type or "my_promise",
                    status="pending",
                    confirmation_status="confirmed",
                    due_date=prom_item.due_date,
                    promisor_id=promisor_id,
                    beneficiary_id=beneficiary_id,
                    related_entity_id=beneficiary_id or promisor_id,
                    source_event_id=str(event_id),
                )
                session.add(new_promise)
                resp.promises_created += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="promise",
                    action="add",
                    entity_id=beneficiary_id or promisor_id,
                    original_extracted_text=prom_item.content,
                )
                continue

            prom_result = await session.execute(
                select(_Todo).where(
                    _Todo.id == prom_item.id,
                    _Todo.user_id == user_id,
                )
            )
            promise: _Todo | None = prom_result.scalar_one_or_none()
            if not promise:
                continue

            if prom_item.action == "confirm":
                promise.confirmation_status = "confirmed"
                resp.promises_confirmed += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="promise",
                    action="confirm",
                    entity_id=promise.related_entity_id and str(promise.related_entity_id),
                    original_extracted_text=promise.description,
                )

            elif prom_item.action == "ignore":
                promise.confirmation_status = "rejected"
                promise.status = "dismissed"
                resp.promises_ignored += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="promise",
                    action="ignore",
                    entity_id=promise.related_entity_id and str(promise.related_entity_id),
                    original_extracted_text=promise.description,
                )

            elif prom_item.action == "modify":
                if prom_item.content is not None:
                    promise.description = prom_item.content
                if prom_item.due_date is not None:
                    promise.due_date = prom_item.due_date
                if prom_item.promise_type is not None:
                    promise.action_type = prom_item.promise_type
                promise.confirmation_status = "confirmed"
                resp.promises_modified += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="promise",
                    action="modify",
                    entity_id=promise.related_entity_id and str(promise.related_entity_id),
                    original_extracted_text=promise.description,
                )

        # ── 关系纠偏 ──
        for assoc_item in request.corrected_associations:
            assoc_result = await session.execute(
                select(Association).where(
                    Association.source_entity_id == assoc_item.source_entity_id,
                    Association.target_entity_id == assoc_item.target_entity_id,
                    Association.user_id == user_id,
                )
            )
            assoc = assoc_result.scalar_one_or_none()
            if not assoc:
                continue

            if assoc_item.action == "modify":
                if assoc_item.relationship_type is not None:
                    assoc.association_type = assoc_item.relationship_type
                if assoc_item.strength is not None:
                    assoc.strength = assoc_item.strength
                resp.associations_updated += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="association",
                    action="modify",
                    entity_id=assoc_item.source_entity_id,
                )
            elif assoc_item.action == "delete":
                await session.delete(assoc)
                resp.associations_updated += 1
                await record_correction(
                    session,
                    user_id=user_id,
                    event_id=str(event_id),
                    correction_type="association",
                    action="delete",
                    entity_id=assoc_item.source_entity_id,
                )

        # ── W5 执行: 认领 operation → 变更 → 审计 → 终态 (同事务) ──
        for plan in w5_entity_plans:
            resp.w5_operations.append(
                await _execute_w5_entity(session, user_id=user_id, plan=plan, resp=resp)
            )
        for plan in w5_todo_plans:
            resp.w5_operations.append(
                await _execute_w5_todo(session, user_id=user_id, plan=plan, resp=resp)
            )

        await commit_with_retry(session)

    logger.info(
        "event_corrected",
        event_id=str(event_id),
        entities_updated=resp.entities_updated,
        todos_created=resp.todos_created,
        promises_confirmed=resp.promises_confirmed,
        promises_created=resp.promises_created,
        associations_updated=resp.associations_updated,
        w5_operations=len(resp.w5_operations),
    )

    return resp

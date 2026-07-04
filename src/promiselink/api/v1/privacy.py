"""Basic edition privacy data management endpoints (1.1 设置页核心项).

基础版（单用户本地部署）隐私数据删除：
- DELETE /privacy/user-data  立即硬删除当前用户的所有数据
- 前端二次确认（要求输入 "DELETE" 短语）
- 写入结构化审计日志（user_id + 删除数量 + 时间戳）

偏差说明（与 UI 整改方案 §4.1 的"30 天软删除保留"对比）：
- 30 天软删除保留是多用户/Pro 版本特性（需要独立 purge 调度任务）
- 基础版为单用户本地部署，执行立即硬删除 + 审计日志即可满足 PIPL/GDPR
- 用户在删除前可通过"导出我的数据"备份
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.relationship_brief import RelationshipBrief
from promiselink.models.reminder import ReminderLog, ReminderPreference
from promiselink.models.scheduled_event import ScheduledEvent
from promiselink.models.score_audit_log import ScoreAuditLog
from promiselink.models.todo import Todo

# Note: SnoozeSchedule lacks user_id; relies on todos FK ondelete=CASCADE.
# PostgreSQL cascades automatically; SQLite orphans are metadata-only (no PII).

router = APIRouter(prefix="/privacy", dependencies=[Depends(rate_limit_dependency)])
logger = get_logger("promiselink.api.privacy")

DELETE_CONFIRM_PHRASE = "DELETE"


class PrivacyDeleteRequest(BaseModel):
    """二次确认请求体：必须显式输入 DELETE 短语。"""

    confirm: str = Field(..., description=f"必须填写 '{DELETE_CONFIRM_PHRASE}' 以确认删除")


class PrivacyDeleteResponse(BaseModel):
    deleted: dict[str, int]
    audit_id: str
    deleted_at: str


@router.delete("/user-data", response_model=PrivacyDeleteResponse)
async def delete_user_data(
    req: PrivacyDeleteRequest,
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> Any:
    """硬删除当前用户的所有数据（基础版 1.1 设置页隐私管理）。

    安全：
    - user_id 取自 JWT，不接受 query/body 传参（多租户隔离）
    - 二次确认：请求体必须包含 confirm='DELETE'
    - 审计日志记录删除范围与数量

    顺序：先删依赖（score_audit_logs/snooze_schedules/reminder_logs/associations/
    relationship_briefs/scheduled_events），再删主表（todos/events/entities/
    reminder_preferences）。
    """
    new_request_id()

    if req.confirm != DELETE_CONFIRM_PHRASE:
        raise ValidationError(
            f"confirm phrase mismatch. Must be '{DELETE_CONFIRM_PHRASE}'."
        )

    deleted_counts: dict[str, int] = {}

    # 1. 依赖表先删（snooze_schedules 由 todos FK CASCADE 自动清理）
    dependent_models: list[tuple[str, type[DeclarativeBase]]] = [
        ("score_audit_logs", ScoreAuditLog),
        ("reminder_logs", ReminderLog),
        ("associations", Association),
        ("relationship_briefs", RelationshipBrief),
        ("scheduled_events", ScheduledEvent),
    ]
    for name, model in dependent_models:
        result = await session.execute(
            delete(model).where(getattr(model, "user_id") == user_id)
        )
        deleted_counts[name] = getattr(result, "rowcount", 0) or 0

    # 2. 主表删除
    main_models: list[tuple[str, type[DeclarativeBase]]] = [
        ("todos", Todo),
        ("events", Event),
        ("entities", Entity),
        ("reminder_preferences", ReminderPreference),
    ]
    for name, model in main_models:
        result = await session.execute(
            delete(model).where(getattr(model, "user_id") == user_id)
        )
        deleted_counts[name] = getattr(result, "rowcount", 0) or 0

    await session.commit()

    audit_id = new_request_id()
    deleted_at = datetime.now(UTC).isoformat()

    logger.info(
        "privacy_user_data_deleted",
        user_id=user_id,
        audit_id=audit_id,
        deleted_counts=deleted_counts,
        deleted_at=deleted_at,
    )

    return PrivacyDeleteResponse(
        deleted=deleted_counts,
        audit_id=audit_id,
        deleted_at=deleted_at,
    )


@router.get("/data-summary")
async def get_data_summary(
    user_id: str = Depends(get_current_user_id),
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    """返回当前用户的数据概览（用于二次确认弹窗展示）。"""
    new_request_id()

    counts: dict[str, int] = {}
    summary_models: list[tuple[str, type[DeclarativeBase]]] = [
        ("todos", Todo),
        ("events", Event),
        ("entities", Entity),
        ("associations", Association),
        ("reminder_logs", ReminderLog),
    ]
    from sqlalchemy import func

    for name, model in summary_models:
        result = await session.execute(
            select(func.count()).select_from(model).where(getattr(model, "user_id") == user_id)
        )
        counts[name] = result.scalar() or 0

    return {"user_id": user_id, "counts": counts}

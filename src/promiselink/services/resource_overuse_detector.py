"""ResourceOveruseDetector — F-39: Resource overuse warning.

Detects when a user has made too many "request-type" todos toward the same
entity within a 30-day window, and generates a warning Todo to prevent
relationship over-drafting.

Threshold: 3+ help/their_promise todos to the same entity in 30 days → warning.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo

logger = get_logger("promiselink.resource_overuse_detector")

# ── Configuration ──
OVERUSE_THRESHOLD = 3  # Number of requests that triggers a warning
WINDOW_DAYS = 30  # Rolling window in days

# Action types that represent "索取" (requesting from others)
REQUEST_ACTION_TYPES = {"their_promise"}


@dataclass
class OveruseWarning:
    """Result of a resource overuse check."""

    entity_id: uuid.UUID
    entity_name: str
    request_count: int
    window_days: int
    severity: str  # "warning" or "critical"


class ResourceOveruseDetector:
    """F-39: Detect resource overuse — too many requests to the same entity.

    Checks whether a user has made OVERUSE_THRESHOLD or more "request-type"
    todos toward the same target entity within a WINDOW_DAYS rolling window.

    Only counts "索取型" todos (action_type = their_promise), not "给予型"
    (action_type = my_promise / my_followup).
    """

    async def check_overuse(
        self,
        user_id: str,
        target_entity_id: str,
        session: AsyncSession,
    ) -> OveruseWarning | None:
        """Check if user has over-requested from a target entity.

        Args:
            user_id: The user making requests.
            target_entity_id: The entity being requested from.
            session: AsyncSession for DB queries.

        Returns:
            OveruseWarning if threshold exceeded, else None.
        """
        window_start = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)

        # Count "索取型" todos toward this entity in the window
        result = await session.execute(
            select(Todo).where(
                and_(
                    Todo.user_id == user_id,
                    Todo.related_entity_id == target_entity_id,
                    Todo.action_type.in_(REQUEST_ACTION_TYPES),
                    Todo.created_at >= window_start,
                )
            )
        )
        request_todos = result.scalars().all()
        request_count = len(request_todos)

        if request_count < OVERUSE_THRESHOLD:
            return None

        # Fetch entity name for the warning
        entity_result = await session.execute(
            select(Entity).where(Entity.id == target_entity_id)
        )
        entity = entity_result.scalar_one_or_none()
        entity_name = entity.name if entity else "未知"

        severity = "warning"
        if request_count >= OVERUSE_THRESHOLD + 3:
            severity = "critical"

        logger.info(
            "resource_overuse_detected",
            user_id=user_id,
            target_entity_id=str(target_entity_id),
            entity_name=entity_name,
            request_count=request_count,
            severity=severity,
        )

        return OveruseWarning(
            entity_id=uuid.UUID(target_entity_id)
            if isinstance(target_entity_id, str)
            else target_entity_id,
            entity_name=entity_name,
            request_count=request_count,
            window_days=WINDOW_DAYS,
            severity=severity,
        )

    async def check_and_create_warning_todo(
        self,
        user_id: str,
        target_entity_id: str,
        source_event_id: str,
        session: AsyncSession,
    ) -> Todo | None:
        """Check overuse and create a warning Todo if threshold exceeded.

        Deduplication: only one warning Todo per (user, entity, 30-day window).

        Args:
            user_id: The user making requests.
            target_entity_id: The entity being requested from.
            source_event_id: The triggering event ID.
            session: AsyncSession for DB queries.

        Returns:
            The created warning Todo, or None if no overuse detected.
        """
        warning = await self.check_overuse(user_id, target_entity_id, session)
        if warning is None:
            return None

        # Dedup: check if a warning Todo already exists for this entity in the window
        # Use Python-side filtering for properties JSON to stay compatible with SQLite
        window_start = datetime.now(UTC) - timedelta(days=WINDOW_DAYS)
        existing = await session.execute(
            select(Todo).where(
                and_(
                    Todo.user_id == user_id,
                    Todo.todo_type == "risk",
                    Todo.related_entity_id == target_entity_id,
                    Todo.created_at >= window_start,
                )
            )
        )
        for existing_todo in existing.scalars().all():
            props = existing_todo.properties or {}
            if props.get("risk_type") == "resource_overuse":
                logger.debug(
                    "resource_overuse_warning_already_exists",
                    user_id=user_id,
                    target_entity_id=str(target_entity_id),
                )
                return None

        # Create warning Todo
        todo = Todo(
            user_id=user_id,
            todo_type="risk",
            title=f"⚠️ 向{warning.entity_name}请求过多（{warning.request_count}次/{warning.window_days}天）",
            description=(
                f"你在{warning.window_days}天内已向{warning.entity_name}请求了{warning.request_count}次，"
                f"可能影响关系健康。建议适当给予回馈或减少索取。"
            ),
            related_entity_id=target_entity_id,
            priority=2,
            status="pending",
            source_event_id=source_event_id,
            properties={
                "risk_type": "resource_overuse",
                "target_entity_id": str(warning.entity_id),
                "request_count": warning.request_count,
                "window_days": warning.window_days,
                "severity": warning.severity,
            },
        )
        session.add(todo)

        logger.info(
            "resource_overuse_warning_created",
            user_id=user_id,
            target_entity_id=str(target_entity_id),
            request_count=warning.request_count,
            severity=warning.severity,
        )

        return todo

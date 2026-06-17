"""Todo model - stores generated action items and notifications."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base, _uuid_default


class Todo(Base):
    """
    Todo model representing action items and notifications.

    Schema aligned with Technical Design v1.7 §3.1
    Supports 6 todo types (v4.0): 🟢 promise, 🟣 help, 🔵 care, 🟡 followup, ⚪ cooperation_signal, 🔴 risk
    """

    __tablename__ = "todos"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )

    # Core fields
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )

    # Todo type with emoji indicators
    todo_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Content
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    # Related entities
    related_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="SET NULL"),
    )
    related_association_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("associations.id", ondelete="SET NULL"),
    )

    # Priority and status
    priority: Mapped[int] = mapped_column(nullable=False, default=3)  # 1=highest, 5=lowest
    status: Mapped[str] = mapped_column(String(15), nullable=False, default="pending", index=True)

    # Scheduling
    due_date: Mapped[datetime | None] = mapped_column(index=True)
    reminder_at: Mapped[datetime | None] = mapped_column()

    # Additional metadata
    properties: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
    )

    # Source tracking
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )

    # F-45: Promise bidirectional model (v4.4)
    action_type: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
        index=True,
    )
    promisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="SET NULL"),
    )
    beneficiary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="SET NULL"),
    )
    confirmation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("events.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Feedback
    feedback: Mapped[str | None] = mapped_column(String(50))  # useful, not_useful, or custom

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column()

    # F-51: Dynamic priority scoring (v4.5)
    dynamic_score: Mapped[float | None] = mapped_column(nullable=True)
    score_calculated_at: Mapped[datetime | None] = mapped_column()

    # F-59: User priority override (v4.6)
    priority_override: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="User-set priority: high/medium/low, null=use AI score"
    )
    priority_source: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ai", server_default="ai",
        comment="Priority source: ai or user"
    )

    # F-52: Implicit feedback tracking (v4.5)
    completed_rank: Mapped[int | None] = mapped_column(nullable=True)

    # F-68: Promise fulfillment status tracking
    fulfillment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column()
    overdue_notified_at: Mapped[datetime | None] = mapped_column()

    # Constraints
    __table_args__ = (
        CheckConstraint(
            """todo_type IN (
                'promise', 'help', 'care', 'followup', 'cooperation_signal', 'risk'
            )""",
            name="todo_type_check",
        ),
        CheckConstraint(
            """status IN ('pending', 'in_progress', 'done', 'dismissed', 'snoozed')""",
            name="todo_status_check",
        ),
        CheckConstraint(
            "priority >= 1 AND priority <= 5",
            name="priority_range_check",
        ),
        CheckConstraint(
            "feedback IS NULL OR length(feedback) > 0",
            name="feedback_check",
        ),
        Index("idx_todos_user_type_status", "user_id", "todo_type", "status"),
        Index("idx_todos_user_due", "user_id", "due_date"),
        Index("idx_todos_user_priority", "user_id", "priority", "status"),
        Index("idx_todos_dynamic_score", "user_id", "dynamic_score"),
        CheckConstraint(
            "dynamic_score IS NULL OR (dynamic_score >= 0.0 AND dynamic_score <= 1.0)",
            name="dynamic_score_range_check",
        ),
        CheckConstraint(
            "completed_rank IS NULL OR completed_rank >= 0",
            name="completed_rank_check",
        ),
        CheckConstraint(
            "priority_override IS NULL OR priority_override IN ('high', 'medium', 'low')",
            name="priority_override_check",
        ),
        CheckConstraint(
            "priority_source IN ('ai', 'user')",
            name="priority_source_check",
        ),
        CheckConstraint(
            "fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'broken')",
            name="fulfillment_status_check",
        ),
    )

    def __repr__(self) -> str:
        return f"<Todo(id={self.id}, type={self.todo_type}, status={self.status}, title={self.title[:30]})>"


class SnoozeSchedule(Base):
    """
    Snooze schedule for todos with status='snoozed'.

    Schema aligned with Technical Design v1.7 §4.6
    """

    __tablename__ = "snooze_schedules"

    # Primary key (same as todo_id)
    todo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("todos.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Original status before snooze
    original_status: Mapped[str] = mapped_column(String(15), nullable=False)

    # When to recover
    if not IS_SQLITE:
        recover_at: Mapped[datetime] = mapped_column(
            TIMESTAMP(timezone=True),
            nullable=False,
            index=True,
        )
    else:
        recover_at: Mapped[str] = mapped_column(  # type: ignore[no-redef]
            String(50),  # ISO format string for SQLite
            nullable=False,
            index=True,
        )

    @property
    def recover_at_datetime(self) -> datetime | None:
        """Convert recover_at to datetime (handles SQLite string storage)."""
        if self.recover_at is None:
            return None
        if isinstance(self.recover_at, datetime):
            return self.recover_at
        try:
            return datetime.fromisoformat(self.recover_at)
        except (ValueError, TypeError):
            return None

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "original_status IN ('pending', 'in_progress')",
            name="original_status_check",
        ),
        Index("idx_snooze_recover_at", "recover_at"),
    )

    def __repr__(self) -> str:
        return f"<SnoozeSchedule(todo_id={self.todo_id}, recover_at={self.recover_at})>"

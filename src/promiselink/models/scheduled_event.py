"""ScheduledEvent model - stores planned future interactions before recording."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base, _uuid_default


class ScheduledEvent(Base):
    """
    ScheduledEvent model representing a planned future interaction.

    Unlike Event (which records past interactions and goes through the
    13-step parsing pipeline), ScheduledEvent is a placeholder that
    waits for the user to record actual content after the meeting/call.

    Flow:
        Create (pending) → [overdue if past scheduled_at] →
        Record (creates Event + triggers pipeline) or Cancel
    """

    VALID_STATUSES = ["pending", "recorded", "cancelled", "overdue"]
    VALID_EVENT_TYPES = ["meeting", "call", "manual"]

    __tablename__ = "scheduled_events"

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
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    participants: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=True,
        comment='[{"name":"张总","entity_id":"...","company":"..."}]',
    )
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Event type for the future recording (meeting/call/manual)
    event_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="meeting",
    )

    # Status lifecycle: pending → recorded | overdue → recorded | cancelled
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )

    # Link to Event after recording
    linked_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=True,
    )

    # Cancellation
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reminder
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB if not IS_SQLITE else JSON,
        nullable=True,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'recorded', 'cancelled', 'overdue')",
            name="se_status_check",
        ),
        CheckConstraint(
            "event_type IN ('meeting', 'call', 'manual')",
            name="se_event_type_check",
        ),
        CheckConstraint(
            "length(topic) > 0",
            name="se_topic_nonempty_check",
        ),
        Index("idx_se_user_status", "user_id", "status"),
        Index("idx_se_user_scheduled", "user_id", "scheduled_at"),
        Index("idx_se_overdue_scan", "status", "scheduled_at"),
    )

    def __repr__(self) -> str:
        return f"<ScheduledEvent(id={self.id}, topic={self.topic[:30]}, status={self.status})>"

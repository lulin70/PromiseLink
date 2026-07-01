"""Reminder models for F-69 Smart Follow-up Reminders."""

import uuid
from datetime import UTC, datetime, time

from sqlalchemy import JSON, CheckConstraint, DateTime, Index, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base, _uuid_default


class ReminderPreference(Base):
    """User preferences for reminder scheduling and fatigue control."""

    __tablename__ = "reminder_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
    )
    preferred_times: Mapped[list[str] | None] = mapped_column(JSON, default=["09:00", "20:00"])
    fatigue_threshold: Mapped[int] = mapped_column(Integer, default=5)
    quiet_hours_start: Mapped[time | None] = mapped_column(Time, default=time(22, 0))
    quiet_hours_end: Mapped[time | None] = mapped_column(Time, default=time(8, 0))
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ReminderLog(Base):
    """Log of sent reminders and user actions for fatigue tracking."""

    __tablename__ = "reminder_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )
    todo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
    )
    reminder_type: Mapped[str] = mapped_column(String(30), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    action_taken: Mapped[str | None] = mapped_column(String(20), nullable=True)
    response_latency_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "reminder_type IN ('promise_due', 'followup', 'stage_suggestion', 'dormant_contact', 'scheduled_due')",
            name="reminder_type_check",
        ),
        CheckConstraint(
            "action_taken IS NULL OR action_taken IN ('completed', 'snoozed', 'dismissed', 'ignored')",
            name="action_taken_check",
        ),
        Index('ix_reminderlog_user_todo', 'user_id', 'todo_id'),
    )

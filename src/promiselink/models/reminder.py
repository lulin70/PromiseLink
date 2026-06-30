"""Reminder models for F-69 Smart Follow-up Reminders."""

from datetime import UTC, datetime, time

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Index, Integer, String, Time
from sqlalchemy.dialects.postgresql import UUID

from promiselink.database import IS_SQLITE, Base, _uuid_default


class ReminderPreference(Base):
    """User preferences for reminder scheduling and fatigue control."""

    __tablename__ = "reminder_preferences"

    user_id = Column(UUID(as_uuid=True) if not IS_SQLITE else String(36), primary_key=True)
    preferred_times = Column(JSON, default=["09:00", "20:00"])
    fatigue_threshold = Column(Integer, default=5)
    quiet_hours_start = Column(Time, default=time(22, 0))
    quiet_hours_end = Column(Time, default=time(8, 0))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))


class ReminderLog(Base):
    """Log of sent reminders and user actions for fatigue tracking."""

    __tablename__ = "reminder_logs"

    id = Column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )
    user_id = Column(UUID(as_uuid=True) if not IS_SQLITE else String(36), nullable=False, index=True)
    todo_id = Column(UUID(as_uuid=True) if not IS_SQLITE else String(36), nullable=False)
    reminder_type = Column(String(30), nullable=False)
    sent_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    action_taken = Column(String(20), nullable=True)
    response_latency_seconds = Column(Integer, nullable=True)

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

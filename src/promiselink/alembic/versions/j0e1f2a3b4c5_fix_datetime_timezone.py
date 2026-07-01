"""Fix datetime column types: convert TIMESTAMP WITHOUT TIME ZONE to WITH TIME ZONE.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
Create Date: 2026-07-01

Root cause: All datetime columns were created as TIMESTAMP WITHOUT TIME ZONE,
but application code uses datetime.now(UTC) which produces tz-aware datetimes.
asyncpg strict type checking rejects the conversion with:
  DataError: can't subtract offset-naive and offset-aware datetimes

This migration converts all datetime columns to TIMESTAMP WITH TIME ZONE
in PostgreSQL. SQLite is skipped (no type enforcement, stores as TEXT).

Columns are populated from existing data via USING clause to preserve values.
For columns previously WITHOUT TIME ZONE, PostgreSQL interprets stored
timestamps as UTC when converting to WITH TIME ZONE.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j0e1f2a3b4c5"
down_revision: str | Sequence[str] | None = "i9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# All (table, column) pairs storing timestamps as TIMESTAMP WITHOUT TIME ZONE
# that need conversion to TIMESTAMP WITH TIME ZONE.
# Extracted from SQLAlchemy models in src/promiselink/models/.
DATETIME_COLUMNS: list[tuple[str, str]] = [
    # events
    ("events", "timestamp"),
    ("events", "created_at"),
    ("events", "processed_at"),
    # entities
    ("entities", "created_at"),
    ("entities", "updated_at"),
    # associations
    ("associations", "created_at"),
    ("associations", "updated_at"),
    ("associations", "last_interaction"),
    # todos
    ("todos", "due_date"),
    ("todos", "reminder_at"),
    ("todos", "created_at"),
    ("todos", "updated_at"),
    ("todos", "completed_at"),
    ("todos", "score_calculated_at"),
    ("todos", "fulfilled_at"),
    ("todos", "overdue_notified_at"),
    # snooze_schedules (recover_at already uses TIMESTAMP(timezone=True))
    ("snooze_schedules", "created_at"),
    # scheduled_events
    ("scheduled_events", "scheduled_at"),
    ("scheduled_events", "reminder_at"),
    ("scheduled_events", "created_at"),
    ("scheduled_events", "updated_at"),
    ("scheduled_events", "recorded_at"),
    # reminder_preferences
    ("reminder_preferences", "updated_at"),
    # reminder_logs
    ("reminder_logs", "sent_at"),
    # relationship_briefs
    ("relationship_briefs", "last_updated_at"),
    ("relationship_briefs", "created_at"),
    # score_audit_logs
    ("score_audit_logs", "created_at"),
]


def upgrade() -> None:
    """Convert all datetime columns to TIMESTAMP WITH TIME ZONE."""
    # Skip on SQLite — no type enforcement, stores as TEXT
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    for table, column in DATETIME_COLUMNS:
        op.alter_column(
            table_name=table,
            column_name=column,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{column} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    """Revert to TIMESTAMP WITHOUT TIME ZONE (data loss: tz info dropped)."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return

    for table, column in DATETIME_COLUMNS:
        op.alter_column(
            table_name=table,
            column_name=column,
            type_=sa.DateTime(timezone=False),
        )

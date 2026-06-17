"""Sprint 0: F-69 Smart Follow-up Reminders tables

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-06-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: str | Sequence[str] | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create reminder_preferences and reminder_logs tables."""
    op.create_table(
        'reminder_preferences',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('preferred_times', sa.JSON, server_default='["09:00", "20:00"]'),
        sa.Column('fatigue_threshold', sa.Integer(), server_default='5'),
        sa.Column('quiet_hours_start', sa.Time(), server_default='22:00:00'),
        sa.Column('quiet_hours_end', sa.Time(), server_default='08:00:00'),
        sa.Column('updated_at', sa.DateTime()),
    )

    op.create_table(
        'reminder_logs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('todo_id', sa.String(36), nullable=False),
        sa.Column('reminder_type', sa.String(30), nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=False),
        sa.Column('action_taken', sa.String(20), nullable=True),
        sa.Column('response_latency_seconds', sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "reminder_type IN ('promise_due', 'followup', 'stage_suggestion', 'dormant_contact')",
            name='reminder_type_check',
        ),
        sa.CheckConstraint(
            "action_taken IS NULL OR action_taken IN ('completed', 'snoozed', 'dismissed', 'ignored')",
            name='action_taken_check',
        ),
    )


def downgrade() -> None:
    """Drop reminder_logs and reminder_preferences tables."""
    op.drop_table('reminder_logs')
    op.drop_table('reminder_preferences')

"""Add scheduled_events table and update reminder_type_check

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-06-15 16:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: str | Sequence[str] | None = 'c3d4e5f6a7b8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create scheduled_events table and update reminder_type constraint."""
    op.create_table(
        'scheduled_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), nullable=False, index=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=False, index=True),
        sa.Column('topic', sa.String(200), nullable=False),
        sa.Column('participants', sa.JSON(), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('event_type', sa.String(20), nullable=False, server_default='meeting'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending', index=True),
        sa.Column('linked_event_id', sa.String(36), nullable=True),
        sa.Column('cancel_reason', sa.Text(), nullable=True),
        sa.Column('reminder_at', sa.DateTime(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'recorded', 'cancelled', 'overdue')",
            name='se_status_check',
        ),
        sa.CheckConstraint(
            "event_type IN ('meeting', 'call', 'manual')",
            name='se_event_type_check',
        ),
        sa.CheckConstraint(
            "length(topic) > 0",
            name='se_topic_nonempty_check',
        ),
    )

    op.create_index('idx_se_user_status', 'scheduled_events', ['user_id', 'status'])
    op.create_index('idx_se_user_scheduled', 'scheduled_events', ['user_id', 'scheduled_at'])
    op.create_index('idx_se_overdue_scan', 'scheduled_events', ['status', 'scheduled_at'])

    # Update reminder_type_check to include 'scheduled_due'
    op.drop_constraint('reminder_type_check', 'reminder_logs', type_='check')
    op.create_check_constraint(
        'reminder_type_check',
        'reminder_logs',
        "reminder_type IN ('promise_due', 'followup', 'stage_suggestion', 'dormant_contact', 'scheduled_due')",
    )


def downgrade() -> None:
    """Drop scheduled_events table and revert reminder_type constraint."""
    # Revert reminder_type_check
    op.drop_constraint('reminder_type_check', 'reminder_logs', type_='check')
    op.create_check_constraint(
        'reminder_type_check',
        'reminder_logs',
        "reminder_type IN ('promise_due', 'followup', 'stage_suggestion', 'dormant_contact')",
    )

    op.drop_index('idx_se_overdue_scan', 'scheduled_events')
    op.drop_index('idx_se_user_scheduled', 'scheduled_events')
    op.drop_index('idx_se_user_status', 'scheduled_events')
    op.drop_table('scheduled_events')

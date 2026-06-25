"""Add fulfillment and score tracking columns to todos

Revision ID: f6a7b8c9d0e1
Revises: e5dfa59687d6
Create Date: 2026-06-25 04:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: str | Sequence[str] | None = 'e5dfa59687d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add score_calculated_at, fulfillment_status, fulfilled_at, overdue_notified_at."""
    # SQLite 不支持 ALTER TABLE ADD CHECK CONSTRAINT，使用 batch 模式重建表。
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.add_column(sa.Column('score_calculated_at', sa.DateTime(), nullable=True))
        batch_op.add_column(
            sa.Column(
                'fulfillment_status',
                sa.String(20),
                nullable=False,
                server_default='pending',
            )
        )
        batch_op.add_column(sa.Column('fulfilled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('overdue_notified_at', sa.DateTime(), nullable=True))
        batch_op.create_index('idx_todos_dynamic_score', ['user_id', 'dynamic_score'])
        batch_op.create_check_constraint(
            'dynamic_score_range_check',
            "dynamic_score IS NULL OR (dynamic_score >= 0.0 AND dynamic_score <= 1.0)",
        )
        batch_op.create_check_constraint(
            'completed_rank_check',
            "completed_rank IS NULL OR completed_rank >= 0",
        )
        batch_op.create_check_constraint(
            'priority_override_check',
            "priority_override IS NULL OR priority_override IN ('high', 'medium', 'low')",
        )
        batch_op.create_check_constraint(
            'priority_source_check',
            "priority_source IN ('ai', 'user')",
        )
        batch_op.create_check_constraint(
            'fulfillment_status_check',
            "fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'broken')",
        )


def downgrade() -> None:
    """Remove fulfillment and score tracking columns from todos."""
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.drop_constraint('fulfillment_status_check', type_='check')
        batch_op.drop_constraint('priority_source_check', type_='check')
        batch_op.drop_constraint('priority_override_check', type_='check')
        batch_op.drop_constraint('completed_rank_check', type_='check')
        batch_op.drop_constraint('dynamic_score_range_check', type_='check')
        batch_op.drop_index('idx_todos_dynamic_score')
        batch_op.drop_column('overdue_notified_at')
        batch_op.drop_column('fulfilled_at')
        batch_op.drop_column('fulfillment_status')
        batch_op.drop_column('score_calculated_at')

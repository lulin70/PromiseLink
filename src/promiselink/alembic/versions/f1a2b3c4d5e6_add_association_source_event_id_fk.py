"""add_association_source_event_id_fk_and_other_fixes

Revision ID: f1a2b3c4d5e6
Revises: e2f3a4b5c6d7
Create Date: 2026-06-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add FK to associations.source_event_id, FK to todos.evidence_event_id,
    update association unique constraint to include user_id,
    add composite index on reminder_logs, and fix snooze_schedules recover_at for SQLite."""

    # 1a: Add FK constraint to associations.source_event_id → events.id
    with op.batch_alter_table('associations') as batch_op:
        batch_op.alter_column('source_event_id', nullable=True)
        batch_op.create_foreign_key(
            'fk_associations_source_event_id_events',
            'events',
            ['source_event_id'],
            ['id'],
            ondelete='SET NULL',
        )

    # 1d: Update unique constraint on associations to include user_id
    with op.batch_alter_table('associations') as batch_op:
        batch_op.drop_constraint('uq_association_source_target_type', type_='unique')
        batch_op.create_unique_constraint(
            'uq_association_user_source_target_type',
            ['user_id', 'source_entity_id', 'target_entity_id', 'association_type'],
        )

    # 1e: Add FK constraint to todos.evidence_event_id → events.id
    with op.batch_alter_table('todos') as batch_op:
        batch_op.create_foreign_key(
            'fk_todos_evidence_event_id_events',
            'events',
            ['evidence_event_id'],
            ['id'],
            ondelete='SET NULL',
        )

    # 1c: Add composite index on reminder_logs (user_id, todo_id)
    op.create_index(
        'ix_reminderlog_user_todo',
        'reminder_logs',
        ['user_id', 'todo_id'],
    )

    # 1b: Fix snooze_schedules recover_at for SQLite — change column type to String(50)
    # For PostgreSQL, TIMESTAMP(timezone=True) is already correct
    # This only needs to change for SQLite where it was None
    with op.batch_alter_table('snooze_schedules') as batch_op:
        batch_op.alter_column(
            'recover_at',
            existing_type=sa.String(50),
            nullable=False,
        )


def downgrade() -> None:
    """Revert all changes from this migration."""

    # Revert 1b: snooze_schedules recover_at (no-op for SQLite, was already broken)
    with op.batch_alter_table('snooze_schedules') as batch_op:
        batch_op.alter_column('recover_at', nullable=False)

    # Revert 1c: drop composite index on reminder_logs
    op.drop_index('ix_reminderlog_user_todo', table_name='reminder_logs')

    # Revert 1e: drop FK on todos.evidence_event_id
    with op.batch_alter_table('todos') as batch_op:
        batch_op.drop_constraint('fk_todos_evidence_event_id_events', type_='foreignkey')

    # Revert 1d: restore original unique constraint on associations
    with op.batch_alter_table('associations') as batch_op:
        batch_op.drop_constraint('uq_association_user_source_target_type', type_='unique')
        batch_op.create_unique_constraint(
            'uq_association_source_target_type',
            ['source_entity_id', 'target_entity_id', 'association_type'],
        )

    # Revert 1a: remove FK on associations.source_event_id, make NOT NULL
    with op.batch_alter_table('associations') as batch_op:
        batch_op.drop_constraint('fk_associations_source_event_id_events', type_='foreignkey')
        batch_op.alter_column('source_event_id', nullable=False)

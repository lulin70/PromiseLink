"""add_todo_source_event_id_fk

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-13 12:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: str | Sequence[str] | None = 'd1e2f3a4b5c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ForeignKey constraint to todos.source_event_id referencing events.id with SET NULL on delete."""
    # First make the column nullable
    with op.batch_alter_table('todos') as batch_op:
        batch_op.alter_column('source_event_id', nullable=True)
        batch_op.create_foreign_key(
            'fk_todos_source_event_id_events',
            'events',
            ['source_event_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """Remove ForeignKey constraint and make source_event_id NOT NULL again."""
    with op.batch_alter_table('todos') as batch_op:
        batch_op.drop_constraint('fk_todos_source_event_id_events', type_='foreignkey')
        batch_op.alter_column('source_event_id', nullable=False)

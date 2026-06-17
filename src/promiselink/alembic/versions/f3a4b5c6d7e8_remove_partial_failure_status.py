"""remove_partial_failure_status

Remove partial_failure from event status CHECK constraint.
Existing partial_failure records are updated to 'failed'.

Revision ID: f3a4b5c6d7e8
Revises: a1b2c3d4e5f7
Create Date: 2026-06-14 22:00:00.000000

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: str | Sequence[str] | None = 'a1b2c3d4e5f7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove partial_failure from status CHECK constraint and migrate existing data."""
    # Update existing partial_failure records to failed
    op.execute("UPDATE events SET status = 'failed' WHERE status = 'partial_failure'")

    # Update CHECK constraint
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'awaiting_retry', 'degraded_completed', "
            "'completed', 'failed')",
        )


def downgrade() -> None:
    """Revert: add partial_failure back to CHECK constraint."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'awaiting_retry', 'degraded_completed', "
            "'completed', 'failed', 'partial_failure')",
        )

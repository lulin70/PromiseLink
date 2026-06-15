"""add_awaiting_retry_degraded_status

Revision ID: d1e2f3a4b5c6
Revises: c05985744996
Create Date: 2026-06-13 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c05985744996'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — add awaiting_retry and degraded_completed to event status check."""
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'awaiting_retry', 'degraded_completed', "
            "'completed', 'failed', 'partial_failure')",
        )


def downgrade() -> None:
    """Downgrade schema — revert to original status values."""
    with op.batch_alter_table('events') as batch_op:
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'completed', 'failed')",
        )

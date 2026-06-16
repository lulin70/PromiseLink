"""sync_check_constraints

Revision ID: a1b2c3d4e5f7
Revises: 4a1cfeaf1eb1
Create Date: 2026-06-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, Sequence[str], None] = '4a1cfeaf1eb1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sync CHECK constraints to match current model."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual', 'email', 'wechat_forward')",
        )
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'completed', 'failed', 'awaiting_retry', 'degraded_completed')",
        )


def downgrade() -> None:
    """Revert CHECK constraints to original values."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual')",
        )
        batch_op.drop_constraint('event_status_check', type_='check')
        batch_op.create_check_constraint(
            'event_status_check',
            condition="status IN ('pending', 'processing', 'completed', 'failed')",
        )

"""remove_email_event_type

Revision ID: h8c9d0e1f2a3
Revises: g7b8c9d0e1f2
Create Date: 2026-06-27 14:00:00.000000

Remove the 'email' event type from the event_type_check constraint.
The email type is a dead type - defined but never used in any UI,
and the pipeline returns empty results for it.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'h8c9d0e1f2a3'
down_revision: str | Sequence[str] | None = 'g7b8c9d0e1f2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop and recreate event_type_check constraint without 'email'."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual', 'wechat_forward')",
        )


def downgrade() -> None:
    """Restore event_type_check constraint with 'email'."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual', 'email', 'wechat_forward')",
        )

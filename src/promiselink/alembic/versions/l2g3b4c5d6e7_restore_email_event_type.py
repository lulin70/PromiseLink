"""restore_email_event_type

Revision ID: l2g3b4c5d6e7
Revises: k1f2a3b4c5d6
Create Date: 2026-07-15 05:00:00.000000

Restore the 'email' event type to the event_type_check constraint.

The 'email' type was removed in h8c9d0e1f2a3 (2026-06-27) because it was
a dead type at that time. Since then, PromiseLink-Pro introduced
pro_api/email_sync.py (PRD §5.17.2) and pro_services/email_adapter.py
which create Events with event_type='email'. The basic edition's Event
model is reused by the pro edition, so the CHECK constraint must allow
'email' to prevent IntegrityError on email sync.
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'l2g3b4c5d6e7'
down_revision: str | Sequence[str] | None = 'k1f2a3b4c5d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop and recreate event_type_check constraint with 'email' restored."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual', 'email', 'wechat_forward')",
        )


def downgrade() -> None:
    """Drop and recreate event_type_check constraint without 'email'."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('event_type_check', type_='check')
        batch_op.create_check_constraint(
            'event_type_check',
            condition="event_type IN ('card_save', 'meeting', 'call', 'manual', 'wechat_forward')",
        )

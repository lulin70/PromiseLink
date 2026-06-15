"""add_failed_steps_to_events

Revision ID: c05985744996
Revises: c3d4e5f6a7b8
Create Date: 2026-06-12 19:07:14.725809

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c05985744996'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — SQLite compatible."""
    # Add failed_steps column to events
    op.add_column('events', sa.Column('failed_steps', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('events', 'failed_steps')

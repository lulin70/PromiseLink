"""Sprint 0: F-59 user priority override fields on todos

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add priority_override and priority_source columns to todos."""
    op.add_column('todos', sa.Column(
        'priority_override', sa.String(10), nullable=True,
        comment="User-set priority: high/medium/low, null=use AI score"
    ))
    op.add_column('todos', sa.Column(
        'priority_source', sa.String(10), nullable=False,
        server_default='ai',
        comment="Priority source: ai or user"
    ))


def downgrade() -> None:
    """Remove priority_override and priority_source columns from todos."""
    op.drop_column('todos', 'priority_source')
    op.drop_column('todos', 'priority_override')

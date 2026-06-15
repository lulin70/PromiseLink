"""Sprint 0: F-52 implicit feedback fields on todos

Revision ID: a1b2c3d4e5f6
Revises: 538083639032
Create Date: 2026-06-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '538083639032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add completed_rank and dynamic_score columns to todos."""
    op.add_column('todos', sa.Column('completed_rank', sa.Integer(), nullable=True))
    op.add_column('todos', sa.Column('dynamic_score', sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove completed_rank and dynamic_score columns from todos."""
    op.drop_column('todos', 'dynamic_score')
    op.drop_column('todos', 'completed_rank')

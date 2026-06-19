"""Sprint 0: F-52 implicit feedback fields on todos

Revision ID: a1b2c3d4e5f6
Revises: 4ff9b21a03b0
Create Date: 2026-06-06 12:00:00.000000

Note: down_revision was changed from '538083639032' (voice_sessions, Pro-only)
to '4ff9b21a03b0' after Pro code migration. See Repo_Split_Decision.md §5.2.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | Sequence[str] | None = '4ff9b21a03b0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add completed_rank and dynamic_score columns to todos."""
    op.add_column('todos', sa.Column('completed_rank', sa.Integer(), nullable=True))
    op.add_column('todos', sa.Column('dynamic_score', sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove completed_rank and dynamic_score columns from todos."""
    op.drop_column('todos', 'dynamic_score')
    op.drop_column('todos', 'completed_rank')

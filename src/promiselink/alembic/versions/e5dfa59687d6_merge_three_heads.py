"""merge_three_heads

Revision ID: e5dfa59687d6
Revises: f1a2b3c4d5e6, d4e5f6a7b8c9, f3a4b5c6d7e8
Create Date: 2026-06-17 10:28:54.304569

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'e5dfa59687d6'
down_revision: str | Sequence[str] | None = ('f1a2b3c4d5e6', 'd4e5f6a7b8c9', 'f3a4b5c6d7e8')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

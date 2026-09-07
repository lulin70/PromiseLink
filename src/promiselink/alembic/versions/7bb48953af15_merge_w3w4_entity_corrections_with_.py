"""merge w3w4_entity_corrections with l2g3b4c5d6e7 line

Revision ID: 7bb48953af15
Revises: l2g3b4c5d6e7, w3w4_entity_corrections
Create Date: 2026-09-07 21:17:31.019587

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '7bb48953af15'
down_revision: str | Sequence[str] | None = ('l2g3b4c5d6e7', 'w3w4_entity_corrections')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

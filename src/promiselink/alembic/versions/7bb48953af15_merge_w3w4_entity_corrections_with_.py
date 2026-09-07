"""merge w3w4 entity corrections with email event type line

Revision ID: 7bb48953af15
Revises: l2g3b4c5d6e7, w3w4_entity_corrections
Create Date: 2026-09-07 21:17:31.019587

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bb48953af15'
down_revision: Union[str, Sequence[str], None] = ('l2g3b4c5d6e7', 'w3w4_entity_corrections')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

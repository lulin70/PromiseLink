"""merge_w5_double_scope_with_7bb48953af15

Revision ID: merge_w5_double_scope_7bb48953af15
Revises: 7bb48953af15, w5_entity_correction_double_scope
Create Date: 2026-09-09

alembic 拓扑合并: 在两条历史 head (7bb48953af15 与 w5_entity_correction_double_scope)
之间加一个空 merge migration, 恢复单 head 拓扑, 不产生任何 DDL.

alembic 约定: merge migration 必须显式声明多个 down_revision 父级 (tuple).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'merge_w5_double_scope_7bb48953af15'
down_revision: tuple[str, ...] = ('7bb48953af15', 'w5_entity_correction_double_scope')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op merge: both parents already converged on the same schema state."""
    pass


def downgrade() -> None:
    """No-op merge: removing this revision restores the two-parent state."""
    pass
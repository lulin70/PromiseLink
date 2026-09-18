"""merge_w5_double_scope_with_7bb48953af15

Revision ID: merge_w5_double_scope
Revises: 7bb48953af15, w5_entity_correction_scope
Create Date: 2026-09-09

alembic 拓扑合并: 在两条历史 head (7bb48953af15 与 w5_entity_correction_scope)
之间加一个空 merge migration, 恢复单 head 拓扑, 不产生任何 DDL.

alembic 约定: merge migration 必须显式声明多个 down_revision 父级 (tuple).

修订 id 长度约束: alembic 的 ``alembic_version.version_num`` 建表时固定为
``VARCHAR(32)``, 超过 32 字符的修订 id 只在 SQLite(不校验长度) 下能跑通,
PostgreSQL 会以 ``StringDataRightTruncation`` 失败 —— CI e2e 门禁即因此长期失败。
本文件与 ``w5_entity_correction_scope.py`` 原名分别长 34/33 字符, 2026-09-18 更名为
短 id; 由于 ``version_num`` 只记录当前 head (``w5a_score_audit_logs``),
已迁移数据库不受影响。
"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = 'merge_w5_double_scope'
down_revision: tuple[str, ...] = ('7bb48953af15', 'w5_entity_correction_scope')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op merge: both parents already converged on the same schema state."""
    pass


def downgrade() -> None:
    """No-op merge: removing this revision restores the two-parent state."""
    pass

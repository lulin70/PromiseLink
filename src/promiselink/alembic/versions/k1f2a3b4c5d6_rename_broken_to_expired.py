"""Rename fulfillment_status broken to expired

Revision ID: k1f2a3b4c5d6
Revises: j0e1f2a3b4c5
Create Date: 2026-07-03 21:00:00.000000

将 todos.fulfillment_status 枚举值 `broken` 统一迁移为 `expired`，
与小程序前端（PromiseLink-miniapp）已采用的 `expired` 保持一致，
修复小程序"已失效"按钮被后端 422 拒绝的 bug。

变更范围：
1. 数据迁移：UPDATE todos SET fulfillment_status='expired' WHERE fulfillment_status='broken'
2. 约束更新：CHECK constraint 从 ('pending','fulfilled','overdue','broken')
   改为 ('pending','fulfilled','overdue','expired')
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'k1f2a3b4c5d6'
down_revision: str | Sequence[str] | None = 'j0e1f2a3b4c5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """将 broken 重命名为 expired，并更新 CHECK 约束。"""
    # 1. 数据迁移：先把存量 broken 数据更新为 expired
    op.execute(
        sa.text(
            "UPDATE todos SET fulfillment_status = 'expired' "
            "WHERE fulfillment_status = 'broken'"
        )
    )

    # 2. 约束更新：SQLite 需 batch 模式重建表
    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.drop_constraint('fulfillment_status_check', type_='check')
        batch_op.create_check_constraint(
            'fulfillment_status_check',
            "fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'expired')",
        )


def downgrade() -> None:
    """回滚：将 expired 改回 broken，并恢复原 CHECK 约束。"""
    op.execute(
        sa.text(
            "UPDATE todos SET fulfillment_status = 'broken' "
            "WHERE fulfillment_status = 'expired'"
        )
    )

    with op.batch_alter_table('todos', schema=None) as batch_op:
        batch_op.drop_constraint('fulfillment_status_check', type_='check')
        batch_op.create_check_constraint(
            'fulfillment_status_check',
            "fulfillment_status IN ('pending', 'fulfilled', 'overdue', 'broken')",
        )

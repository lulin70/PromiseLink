"""sync_association_type_check

Revision ID: g7b8c9d0e1f2
Revises: e5dfa59687d6
Create Date: 2026-06-27 13:00:00.000000

Sync association_type_check constraint to include topic_overlap,
supply_demand, and industry_chain (added to model but missing from
databases created by initial migration 4a1cfeaf1eb1).
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'g7b8c9d0e1f2'
down_revision: str | Sequence[str] | None = 'f6a7b8c9d0e1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sync association_type_check to include all 12 association types."""
    with op.batch_alter_table('associations', schema=None) as batch_op:
        batch_op.drop_constraint('association_type_check', type_='check')
        batch_op.create_check_constraint(
            'association_type_check',
            condition="""association_type IN (
                'alumni', 'ex_colleague', 'same_city', 'competitor',
                'tech_overlap', 'deal_link', 'risk_link', 'supply_chain',
                'co_occurrence',
                'topic_overlap', 'supply_demand', 'industry_chain'
            )""",
        )


def downgrade() -> None:
    """Revert to 9-type constraint (loses topic_overlap, supply_demand, industry_chain)."""
    with op.batch_alter_table('associations', schema=None) as batch_op:
        batch_op.drop_constraint('association_type_check', type_='check')
        batch_op.create_check_constraint(
            'association_type_check',
            condition="""association_type IN (
                'alumni', 'ex_colleague', 'same_city', 'competitor',
                'tech_overlap', 'deal_link', 'risk_link', 'supply_chain',
                'co_occurrence'
            )""",
        )

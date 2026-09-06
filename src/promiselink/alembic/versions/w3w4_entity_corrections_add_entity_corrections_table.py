"""add_entity_corrections_table

Revision ID: w3w4_entity_corrections
Revises: (latest head)
Create Date: 2026-09-05

W3 纠偏回流: 新增 entity_corrections 审计表.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'w3w4_entity_corrections'
down_revision: str | Sequence[str] | None = 'e5dfa59687d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema — create entity_corrections table."""
    op.create_table(
        'entity_corrections',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('event_id', sa.String(length=36), nullable=False),
        sa.Column('correction_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.String(length=36), nullable=True),
        sa.Column('original_extracted_text', sa.Text(), nullable=True),
        sa.Column('original_canonical_name', sa.String(length=200), nullable=True),
        sa.Column('candidate_entity_ids', sa.JSON(), nullable=True),
        sa.Column('selected_entity_id', sa.String(length=36), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "correction_type IN ('entity', 'todo', 'promise', 'association')",
            name='entity_correction_type_check',
        ),
        sa.CheckConstraint(
            "action IN ("
            "'select_existing', 'create_new', 'ignore', "
            "'edit', 'delete', 'add', 'modify', 'confirm'"
            ")",
            name='entity_correction_action_check',
        ),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['entity_id'], ['entities.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_entity_corrections_user_time', 'entity_corrections',
        ['user_id', 'created_at'], unique=False,
    )
    op.create_index(
        'idx_entity_corrections_event', 'entity_corrections',
        ['event_id'], unique=False,
    )
    op.create_index(
        'idx_entity_corrections_type_time', 'entity_corrections',
        ['correction_type', 'created_at'], unique=False,
    )
    op.create_index(
        op.f('ix_entity_corrections_user_id'), 'entity_corrections',
        ['user_id'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema — drop entity_corrections table."""
    op.drop_index(op.f('ix_entity_corrections_user_id'), table_name='entity_corrections')
    op.drop_index('idx_entity_corrections_type_time', table_name='entity_corrections')
    op.drop_index('idx_entity_corrections_event', table_name='entity_corrections')
    op.drop_index('idx_entity_corrections_user_time', table_name='entity_corrections')
    op.drop_table('entity_corrections')

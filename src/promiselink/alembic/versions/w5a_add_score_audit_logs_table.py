"""w5_add_score_audit_logs_table

Revision ID: w5a_score_audit_logs
Revises: merge_w5_double_scope_7bb48953af15
Create Date: 2026-09-10

Closes the migration/ORM parity gap: ``score_audit_logs`` previously relied on
``Base.metadata.create_all()`` at app startup (see j0e1f2a3b4c5 comment) and
had no Alembic migration. After the W5 admission contract switched fixture
backends to ``alembic upgrade head`` only, the table went missing on
migration-managed databases.

The schema mirrors promiselink/models/score_audit_log.py exactly
(UUID ids + JSONB on PostgreSQL, VARCHAR(36) ids + JSON on SQLite).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'w5a_score_audit_logs'
down_revision: str | Sequence[str] | None = 'merge_w5_double_scope_7bb48953af15'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create score_audit_logs (parity with ScoreAuditLog ORM model)."""
    bind = op.get_bind()
    is_pg = bind.dialect.name == 'postgresql'

    def _id() -> sa.types.TypeEngine:
        return postgresql.UUID(as_uuid=True) if is_pg else sa.String(length=36)

    def _json() -> sa.types.TypeEngine:
        return postgresql.JSONB() if is_pg else sa.JSON()

    op.create_table(
        'score_audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('todo_id', _id(), nullable=False),
        sa.Column('user_id', _id(), nullable=False),
        sa.Column('old_score', sa.Float(), nullable=True),
        sa.Column('new_score', sa.Float(), nullable=False),
        sa.Column('score_version', sa.String(length=20), nullable=False),
        sa.Column('calculation_factors', _json(), nullable=False),
        sa.Column('calculated_by', sa.String(length=50), nullable=False),
        sa.Column('triggered_by', sa.String(length=50), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['todo_id'], ['todos.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_score_audit_user_time',
        'score_audit_logs',
        ['user_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'idx_score_audit_todo',
        'score_audit_logs',
        ['todo_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Drop score_audit_logs (restore pre-parity behaviour)."""
    op.drop_index('idx_score_audit_todo', table_name='score_audit_logs')
    op.drop_index('idx_score_audit_user_time', table_name='score_audit_logs')
    op.drop_table('score_audit_logs')

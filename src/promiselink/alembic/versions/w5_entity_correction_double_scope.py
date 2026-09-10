"""w5_entity_correction_double_scope

Revision ID: w5_entity_correction_double_scope
Revises: w3w4_entity_corrections
Create Date: 2026-09-09

W5 跨语言实体关联: 在 entity_corrections 表上扩展双 scope 字段, 供
Entity / Todo 共享 operation / audit 事实源, 不新增独立表.

新增列:
- scope_type        VARCHAR(16) NOT NULL DEFAULT 'entity'
                    CHECK IN ('entity', 'todo')
- source_todo_id    VARCHAR(36) NULL   (Todo correction 时必填)
- selected_todo_id  VARCHAR(36) NULL   (Todo correction 时确认/创建)
- candidate_todo_ids JSON NULL         (Todo correction 候选快照)
- candidate_digest  VARCHAR(64) NULL    (候选 digest hex)
- operation_key     VARCHAR(64) NOT NULL (scope 内幂等键)
- token_hash        VARCHAR(64) NULL    (HMAC-SHA256 token 指纹)
- token_key_version  VARCHAR(32) NULL
- resolver_version   VARCHAR(32) NULL
- score_version     VARCHAR(32) NULL
- embedding_space   VARCHAR(64) NULL
- token_issued_at   DATETIME NULL
- token_expires_at  DATETIME NULL
- operation_status  VARCHAR(16) NOT NULL DEFAULT 'issued'
                    CHECK IN ('issued', 'pending', 'confirmed', 'rejected', 'expired')
- result_summary    JSON NULL (whitelist: candidate_rank/method/score/language_pair)
- completed_at      DATETIME NULL

新约束:
- (scope_type='entity' AND entity_id IS NOT NULL AND selected_todo_id IS NULL)
  OR (scope_type='todo' AND selected_todo_id IS NOT NULL AND entity_id IS NULL)
- operation_key 在 (scope_type, user_id, event_id, entity_id_or_source_todo_id) 内唯一
- result_summary 字段集 ⊇ {candidate_rank, method, score, language_pair}; validator
  在 Python 层校验, 此处仅在文档中固化契约
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'w5_entity_correction_double_scope'
down_revision: str | Sequence[str] | None = 'w3w4_entity_corrections'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add W5 double-scope fields to entity_corrections."""
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Add nullable first so existing rows can be backfilled safely before the
    # operation key becomes NOT NULL.
    op.add_column(
        'entity_corrections',
        sa.Column('scope_type', sa.String(length=16), nullable=False, server_default='entity'),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('source_todo_id', sa.String(length=36), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('selected_todo_id', sa.String(length=36), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('candidate_todo_ids', sa.JSON(), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('candidate_digest', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('operation_key', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('token_hash', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('token_key_version', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('resolver_version', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('score_version', sa.String(length=32), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('embedding_space', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('token_issued_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('operation_status', sa.String(length=16), nullable=False, server_default='issued'),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('result_summary', sa.JSON(), nullable=True),
    )
    op.add_column(
        'entity_corrections',
        sa.Column('completed_at', sa.DateTime(), nullable=True),
    )

    # Every pre-W5 row receives a distinct key. Using the primary key avoids
    # making all legacy rows collide on the former placeholder value.
    op.execute(
        sa.text(
            "UPDATE entity_corrections "
            "SET operation_key = 'w5-legacy-' || CAST(id AS VARCHAR(36)) "
            "WHERE operation_key IS NULL"
        )
    )
    with op.batch_alter_table('entity_corrections') as batch_op:
        batch_op.alter_column(
            'operation_key',
            existing_type=sa.String(length=64),
            nullable=False,
        )

    # SQLite cannot ALTER TABLE to add CHECK constraints. PostgreSQL can add
    # them as NOT VALID so legacy rows remain readable while new writes are
    # checked against the W5 contract.
    if dialect_name == 'postgresql':
        # W5 operation rows are created at token issuance before the user has
        # made any decision, so the W3 action whitelist gains 'issued'.
        op.drop_constraint(
            'entity_correction_action_check', 'entity_corrections', type_='check'
        )
        op.execute(
            sa.text(
                "ALTER TABLE entity_corrections "
                "ADD CONSTRAINT entity_correction_action_check "
                "CHECK (action IN ("
                "'select_existing', 'create_new', 'ignore', "
                "'edit', 'delete', 'add', 'modify', 'confirm', 'issued'"
                ")) NOT VALID"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE entity_corrections "
                "ADD CONSTRAINT entity_correction_scope_type_check "
                "CHECK (scope_type IN ('entity', 'todo')) NOT VALID"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE entity_corrections "
                "ADD CONSTRAINT entity_correction_operation_status_check "
                "CHECK (operation_status IN "
                "('issued', 'pending', 'confirmed', 'rejected', 'expired')) NOT VALID"
            )
        )
        op.execute(
            sa.text(
                "ALTER TABLE entity_corrections "
                "ADD CONSTRAINT entity_correction_scope_xor_check "
                "CHECK ("
                "(scope_type = 'entity' AND correction_type = 'entity' "
                "AND entity_id IS NOT NULL "
                "AND source_todo_id IS NULL AND selected_todo_id IS NULL) "
                "OR (scope_type = 'todo' AND correction_type = 'todo' "
                "AND source_todo_id IS NOT NULL "
                "AND entity_id IS NULL AND (selected_todo_id IS NOT NULL "
                "OR operation_status != 'confirmed')) "
                "OR correction_type IN ('promise', 'association')"
                ") NOT VALID"
            )
        )

    op.create_index(
        'uq_entity_corrections_operation_key',
        'entity_corrections',
        ['scope_type', 'user_id', 'event_id', 'operation_key'],
        unique=True,
    )
    op.create_index(
        'ix_entity_corrections_token_hash',
        'entity_corrections',
        ['token_hash'],
        unique=False,
    )
    op.create_index(
        'ix_entity_corrections_source_todo',
        'entity_corrections',
        ['source_todo_id'],
        unique=False,
    )
    op.create_index(
        'ix_entity_corrections_selected_todo',
        'entity_corrections',
        ['selected_todo_id'],
        unique=False,
    )
    op.create_index(
        'ix_entity_corrections_operation_status',
        'entity_corrections',
        ['operation_status', 'completed_at'],
        unique=False,
    )

    # SQLite path: recreate the W3 action whitelist via table rebuild so the
    # 'issued' placeholder value is accepted for W5 operation rows.
    if dialect_name != 'postgresql':
        with op.batch_alter_table('entity_corrections') as batch_op:
            batch_op.drop_constraint(
                'entity_correction_action_check', type_='check'
            )
            batch_op.create_check_constraint(
                'entity_correction_action_check',
                "action IN ('select_existing', 'create_new', 'ignore', "
                "'edit', 'delete', 'add', 'modify', 'confirm', 'issued')",
            )

    with op.batch_alter_table('entity_corrections') as batch_op:
        batch_op.create_foreign_key(
            'fk_entity_corrections_source_todo',
            'todos',
            ['source_todo_id'],
            ['id'],
        )
        batch_op.create_foreign_key(
            'fk_entity_corrections_selected_todo',
            'todos',
            ['selected_todo_id'],
            ['id'],
        )


def downgrade() -> None:
    """Drop W5 double-scope fields from entity_corrections."""
    with op.batch_alter_table('entity_corrections') as batch_op:
        batch_op.drop_constraint('fk_entity_corrections_selected_todo', type_='foreignkey')
        batch_op.drop_constraint('fk_entity_corrections_source_todo', type_='foreignkey')

    op.drop_index('ix_entity_corrections_operation_status', table_name='entity_corrections')
    op.drop_index('ix_entity_corrections_selected_todo', table_name='entity_corrections')
    op.drop_index('ix_entity_corrections_source_todo', table_name='entity_corrections')
    op.drop_index('ix_entity_corrections_token_hash', table_name='entity_corrections')
    op.drop_index('uq_entity_corrections_operation_key', table_name='entity_corrections')

    if op.get_bind().dialect.name == 'postgresql':
        op.drop_constraint(
            'entity_correction_scope_xor_check',
            'entity_corrections',
            type_='check',
        )
        op.drop_constraint(
            'entity_correction_operation_status_check',
            'entity_corrections',
            type_='check',
        )
        op.drop_constraint(
            'entity_correction_scope_type_check',
            'entity_corrections',
            type_='check',
        )

    op.drop_column('entity_corrections', 'completed_at')
    op.drop_column('entity_corrections', 'result_summary')
    op.drop_column('entity_corrections', 'operation_status')
    op.drop_column('entity_corrections', 'token_expires_at')
    op.drop_column('entity_corrections', 'token_issued_at')
    op.drop_column('entity_corrections', 'embedding_space')
    op.drop_column('entity_corrections', 'score_version')
    op.drop_column('entity_corrections', 'resolver_version')
    op.drop_column('entity_corrections', 'token_key_version')
    op.drop_column('entity_corrections', 'token_hash')
    op.drop_column('entity_corrections', 'operation_key')
    op.drop_column('entity_corrections', 'candidate_digest')
    op.drop_column('entity_corrections', 'candidate_todo_ids')
    op.drop_column('entity_corrections', 'selected_todo_id')
    op.drop_column('entity_corrections', 'source_todo_id')
    op.drop_column('entity_corrections', 'scope_type')

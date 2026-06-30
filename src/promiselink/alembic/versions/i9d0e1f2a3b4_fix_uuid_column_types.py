"""Fix UUID column types: convert String(36) to UUID in PostgreSQL.

Revision ID: i9d0e1f2a3b4
Revises: h8c9d0e1f2a3
Create Date: 2026-06-30

Root cause: alembic migrations created all UUID columns as sa.String(length=36),
but SQLAlchemy models declare them as UUID(as_uuid=True) when not IS_SQLITE.
PostgreSQL strictly enforces type matching in WHERE/JOIN, causing
"operator does not exist: character varying = uuid" errors.

This migration converts all String(36) UUID columns to native UUID type
in PostgreSQL. SQLite is skipped (no type enforcement).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "i9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "h8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# All (table, column) pairs that store UUID values as String(36) and need conversion.
# Extracted from all alembic migrations that use sa.String(length=36) for UUID columns.
UUID_COLUMNS: list[tuple[str, str]] = [
    # events
    ("events", "id"),
    ("events", "user_id"),
    # entities
    ("entities", "id"),
    ("entities", "user_id"),
    ("entities", "source_event_id"),
    # associations
    ("associations", "id"),
    ("associations", "user_id"),
    ("associations", "source_entity_id"),
    ("associations", "target_entity_id"),
    ("associations", "source_event_id"),
    # todos
    ("todos", "id"),
    ("todos", "user_id"),
    ("todos", "related_entity_id"),
    ("todos", "related_association_id"),
    ("todos", "source_event_id"),
    ("todos", "promisor_id"),
    ("todos", "beneficiary_id"),
    ("todos", "evidence_event_id"),
    # snooze_schedules
    ("snooze_schedules", "todo_id"),
    # relationship_briefs
    ("relationship_briefs", "id"),
    ("relationship_briefs", "user_id"),
    ("relationship_briefs", "person_entity_id"),
    # reminder_preferences
    ("reminder_preferences", "user_id"),
    # reminder_logs
    ("reminder_logs", "id"),
    ("reminder_logs", "user_id"),
    ("reminder_logs", "todo_id"),
    # scheduled_events
    ("scheduled_events", "id"),
    ("scheduled_events", "user_id"),
    ("scheduled_events", "linked_event_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Step 1: Drop all foreign key constraints (PG refuses ALTER TYPE with FK active)
    op.execute(
        """
        DO $$
        DECLARE r RECORD;
        BEGIN
            FOR r IN (
                SELECT conname, conrelid::regclass AS table_name
                FROM pg_constraint
                WHERE contype = 'f'
                  AND connamespace = 'public'::regnamespace
            ) LOOP
                EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I',
                    r.table_name, r.conname);
            END LOOP;
        END $$;
        """
    )

    # Step 2: Convert each String(36) column to UUID type
    for table, column in UUID_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE UUID USING {column}::uuid"
        )

    # Step 3: Recreate foreign key constraints (matching model definitions)
    fk_constraints = [
        # entities -> events
        ("fk_entities_source_event_id", "entities", "source_event_id", "events", "id", "CASCADE"),
        # associations -> entities, events
        ("fk_assoc_source_entity", "associations", "source_entity_id", "entities", "id", "CASCADE"),
        ("fk_assoc_target_entity", "associations", "target_entity_id", "entities", "id", "CASCADE"),
        ("fk_assoc_source_event", "associations", "source_event_id", "events", "id", "CASCADE"),
        # todos -> entities, associations, events
        ("fk_todos_related_entity", "todos", "related_entity_id", "entities", "id", "SET NULL"),
        ("fk_todos_related_assoc", "todos", "related_association_id", "associations", "id", "SET NULL"),
        ("fk_todos_source_event", "todos", "source_event_id", "events", "id", "SET NULL"),
        ("fk_todos_promisor", "todos", "promisor_id", "entities", "id", "SET NULL"),
        ("fk_todos_beneficiary", "todos", "beneficiary_id", "entities", "id", "SET NULL"),
        ("fk_todos_evidence_event", "todos", "evidence_event_id", "events", "id", "SET NULL"),
        # snooze_schedules -> todos
        ("fk_snooze_todo", "snooze_schedules", "todo_id", "todos", "id", "CASCADE"),
        # relationship_briefs -> entities
        ("fk_briefs_person_entity", "relationship_briefs", "person_entity_id", "entities", "id", None),
    ]

    for name, table, column, ref_table, ref_column, ondelete in fk_constraints:
        if ondelete:
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column}) "
                f"ON DELETE {ondelete}"
            )
        else:
            op.execute(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({column}) REFERENCES {ref_table}({ref_column})"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    # Drop recreated FK constraints
    fk_names = [
        ("entities", "fk_entities_source_event_id"),
        ("associations", "fk_assoc_source_entity"),
        ("associations", "fk_assoc_target_entity"),
        ("associations", "fk_assoc_source_event"),
        ("todos", "fk_todos_related_entity"),
        ("todos", "fk_todos_related_assoc"),
        ("todos", "fk_todos_source_event"),
        ("todos", "fk_todos_promisor"),
        ("todos", "fk_todos_beneficiary"),
        ("todos", "fk_todos_evidence_event"),
        ("snooze_schedules", "fk_snooze_todo"),
        ("relationship_briefs", "fk_briefs_person_entity"),
    ]

    for table, name in fk_names:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    # Revert columns to String(36)
    for table, column in UUID_COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE VARCHAR(36) USING {column}::text"
        )

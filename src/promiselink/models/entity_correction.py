"""EntityCorrection model — W3 纠偏回流审计行.

Records every user correction (select_existing / create_new / ignore / edit / delete / add /
modify / confirm) performed via POST /events/{event_id}/correct. Written in the SAME
transaction as the business mutation so audit and data are atomic.

Privacy:
- original_extracted_text is auto-redacted via redact_pii_from_text() before insert
  (5 PII classes: phone / email / id_card / bank_card / wechat_id).
- Aggregation endpoints (/entity-corrections/aggregations) NEVER return
  original_extracted_text or candidate_entity_ids.

Retention:
- cleanup_entity_corrections(retention_days=180) is run daily by the
  background worker registered in main.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base


class EntityCorrection(Base):
    """Single user correction entry (纠偏审计行)."""

    __tablename__ = "entity_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("events.id"),
        nullable=False,
    )
    correction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id"),
        nullable=True,
    )
    original_extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_canonical_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    candidate_entity_ids: Mapped[list[str] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=True,
    )
    selected_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ── W5 双 scope 字段 (cross-language entity/todo association) ──────────────
    # 共享 operation/audit 事实源, 不新增独立 token/cooldown 表.
    # 详见 docs/design/TECH_DESIGN_跨语言实体关联_W5_v1.md §3.1.2 + alembic
    # migration w5_entity_correction_double_scope.
    scope_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="entity", default="entity",
    )
    source_todo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("todos.id"),
        nullable=True,
    )
    selected_todo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("todos.id"),
        nullable=True,
    )
    candidate_todo_ids: Mapped[list[str] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=True,
    )
    candidate_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        # Per-row unique key: legacy W3 audit rows get "w3-<uuid4>", W5 operations
        # get an explicit "w5-<uuid4>" key from the operation service. A shared
        # placeholder default would collide on uq_entity_corrections_operation_key
        # as soon as one event produced two audit rows.
        default=lambda: f"w3-{uuid.uuid4()}",
    )
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    token_key_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolver_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    score_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    embedding_space: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_issued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    operation_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="issued", default="issued",
    )
    result_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "correction_type IN ('entity', 'todo', 'promise', 'association')",
            name="entity_correction_type_check",
        ),
        CheckConstraint(
            "action IN ("
            "'select_existing', 'create_new', 'ignore', "
            "'edit', 'delete', 'add', 'modify', 'confirm', "
            "'issued'"
            ")",
            name="entity_correction_action_check",
        ),
        CheckConstraint(
            "scope_type IN ('entity', 'todo')",
            name="entity_correction_scope_type_check",
        ),
        CheckConstraint(
            "operation_status IN ('issued', 'pending', 'confirmed', 'rejected', 'expired')",
            name="entity_correction_operation_status_check",
        ),
        CheckConstraint(
            # W5 entity/todo scopes are strictly bound; legacy promise /
            # association audit rows (scope_type default 'entity', entity_id
            # nullable) are exempt from the XOR contract.
            "(scope_type = 'entity' AND correction_type = 'entity' "
            "AND entity_id IS NOT NULL "
            "AND source_todo_id IS NULL AND selected_todo_id IS NULL) "
            "OR (scope_type = 'todo' AND correction_type = 'todo' "
            "AND source_todo_id IS NOT NULL "
            "AND entity_id IS NULL AND (selected_todo_id IS NOT NULL "
            "OR operation_status != 'confirmed')) "
            "OR correction_type IN ('promise', 'association')",
            name="entity_correction_scope_xor_check",
        ),
        Index("idx_entity_corrections_user_time", "user_id", "created_at"),
        Index("idx_entity_corrections_event", "event_id"),
        Index("idx_entity_corrections_type_time", "correction_type", "created_at"),
        Index(
            "uq_entity_corrections_operation_key",
            "scope_type", "user_id", "event_id", "operation_key",
            unique=True,
        ),
        Index("ix_entity_corrections_operation_status", "operation_status", "completed_at"),
        Index("ix_entity_corrections_source_todo", "source_todo_id"),
        Index("ix_entity_corrections_selected_todo", "selected_todo_id"),
    )

    def to_audit_dict(self) -> dict[str, Any]:
        """Audit-only projection (zero original text, zero candidate ids)."""
        return {
            "id": str(self.id),
            "user_id": str(self.user_id),
            "event_id": str(self.event_id),
            "correction_type": self.correction_type,
            "entity_id": str(self.entity_id) if self.entity_id else None,
            "selected_entity_id": str(self.selected_entity_id) if self.selected_entity_id else None,
            "action": self.action,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return (
            f"<EntityCorrection(id={self.id}, user_id={self.user_id}, "
            f"event_id={self.event_id}, correction_type={self.correction_type}, "
            f"action={self.action})>"
        )

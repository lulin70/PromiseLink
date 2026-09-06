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

    __table_args__ = (
        CheckConstraint(
            "correction_type IN ('entity', 'todo', 'promise', 'association')",
            name="entity_correction_type_check",
        ),
        CheckConstraint(
            "action IN ("
            "'select_existing', 'create_new', 'ignore', "
            "'edit', 'delete', 'add', 'modify', 'confirm'"
            ")",
            name="entity_correction_action_check",
        ),
        Index("idx_entity_corrections_user_time", "user_id", "created_at"),
        Index("idx_entity_corrections_event", "event_id"),
        Index("idx_entity_corrections_type_time", "correction_type", "created_at"),
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

"""Entity model - stores extracted entities (person, organization, etc.)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base, _uuid_default


class Entity(Base):
    """
    Entity model representing extracted business entities.

    Schema aligned with Technical Design v1.7 §3.1
    Supports 5 entity types: person, organization, topic, technology, project
    """

    __tablename__ = "entities"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )

    # Core fields
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    # Entity resolution fields
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
    )

    # Properties (JSONB for PostgreSQL, JSON for SQLite)
    # Contains entity-specific attributes, e.g., for person:
    # {
    #   "basic": {"company": "...", "title": "...", "phone": "..."},
    #   "communication": {"preferred_channel": "...", "response_time": "..."},
    #   "decision": {"role": "...", "authority": "..."},
    #   "resource": {"capabilities": [...], "sensitivity": "matchable"},
    #   "relationship": {"strength": 0.8, "last_contact": "..."}
    # }
    properties: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
    )

    # Source tracking
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("events.id"),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    # Entity status lifecycle: 4 states — provisional / confirmed / merged / deleted
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('person', 'organization', 'topic', 'technology', 'project')",
            name="entity_type_check",
        ),
        CheckConstraint(
            "status IN ('provisional', 'confirmed', 'merged', 'deleted')",
            name="entity_status_check",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_range_check",
        ),
        Index("idx_entities_user_type", "user_id", "entity_type"),
        Index("idx_entities_user_name", "user_id", "name"),
        Index("idx_entities_canonical", "user_id", "canonical_name"),
        Index("idx_entities_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, type={self.entity_type}, name={self.name})>"

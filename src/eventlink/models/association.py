"""Association model - stores relationships between entities."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from eventlink.database import Base, IS_SQLITE, _uuid_default


class Association(Base):
    """
    Association model representing relationships between entities.

    Schema aligned with Technical Design v1.7 §3.1
    Supports 12 association types: 9 structural + 3 semantic
    """

    __tablename__ = "associations"

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
    
    # Source and target entities
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    
    # Association type: 9 structural + 3 semantic
    #   Structural: alumni, ex_colleague, same_city, competitor, tech_overlap,
    #               deal_link, risk_link, supply_chain, co_occurrence
    #   Semantic:   topic_overlap, supply_demand, industry_chain
    association_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    
    # Strength score with time decay
    strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    
    # Properties specific to association type
    properties: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
    )
    
    # Source tracking
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )
    last_interaction: Mapped[datetime | None] = mapped_column()

    # Constraints
    __table_args__ = (
        CheckConstraint(
            """association_type IN (
                'alumni', 'ex_colleague', 'same_city', 'competitor',
                'tech_overlap', 'deal_link', 'risk_link', 'supply_chain',
                'co_occurrence',
                'topic_overlap', 'supply_demand', 'industry_chain'
            )""",
            name="association_type_check",
        ),
        CheckConstraint(
            "status IN ('provisional', 'confirmed', 'rejected')",
            name="association_status_check",
        ),
        CheckConstraint(
            "strength >= 0.0 AND strength <= 1.0",
            name="strength_range_check",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="confidence_range_check",
        ),
        CheckConstraint(
            "source_entity_id != target_entity_id",
            name="no_self_association_check",
        ),
        Index("idx_associations_user_type", "user_id", "association_type"),
        Index("idx_associations_source", "source_entity_id"),
        Index("idx_associations_target", "target_entity_id"),
        Index("idx_associations_strength", "user_id", "strength"),
        UniqueConstraint(
            "source_entity_id", "target_entity_id", "association_type",
            name="uq_association_source_target_type",
        ),
    )

    def __repr__(self) -> str:
        return f"<Association(id={self.id}, type={self.association_type}, strength={self.strength:.2f})>"

"""RelationshipBrief model - relationship progress tracking card (F-47).

Stores the 12-module relationship brief for each person-entity pair.
Schema aligned with Database_Design 0.2.0 §3.6 and Technical Design v2.5 §3.1.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column

from eventlink.database import Base, IS_SQLITE, _uuid_default


class RelationshipBrief(Base):
    """Relationship progress tracking card for a user-person pair.

    12 modules:
      1. basic_info       - Basic info (name, company, role)
      2. relationship_stage - Current stage (new_connection → value_response → ...)
      3. last_interaction  - Last contact time and context
      4. interaction_freq  - Interaction frequency analysis
      5. open_promises     - Outstanding promises (my + their)
      6. their_concerns    - What they care about
      7. my_contributions  - What I've helped with
      8. cooperation_signals - Potential cooperation signals
      9. risk_flags        - Risk indicators
      10. next_actions      - Recommended next steps
      11. strength_score   - Relationship strength (0-100)
      12. notes            - Manual notes
    """

    __tablename__ = "relationship_briefs"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )

    # Owner + Target person
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )
    person_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # F-48: Relationship stage (v4.4)
    # 7 stages: new_connection → understanding_needs → value_response →
    #          deep_trust → active_cooperation → long_term_partner → dormant
    relationship_stage: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="new_connection",
        index=True,
    )

    # Brief data as JSON(B) — contains all 12 modules
    brief_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=False,
        default=dict,
    )

    # Metadata
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_updated_at: Mapped[datetime] = mapped_column(
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    # Constraints
    __table_args__ = (
        CheckConstraint(
            """relationship_stage IN (
                'new_connection', 'understanding_needs', 'value_response',
                'deep_trust', 'active_cooperation', 'long_term_partner', 'dormant'
            )""",
            name="relationship_stage_check",
        ),
        CheckConstraint("version >= 1", name="brief_version_check"),
        Index("idx_briefs_user_person", "user_id", "person_entity_id", unique=True),
        Index("idx_briefs_user_stage", "user_id", "relationship_stage"),
    )

    def __repr__(self) -> str:
        return (
            f"<RelationshipBrief(id={self.id}, stage={self.relationship_stage}, "
            f"person={self.person_entity_id})>"
        )

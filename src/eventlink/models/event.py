"""Event model - stores raw input events from multiple sources."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from eventlink.database import Base, IS_SQLITE, _uuid_default


class Event(Base):
    """
    Event model representing input from card_save, meeting, call, or manual sources.
    
    Schema aligned with Technical Design v1.7 §3.1
    """

    __tablename__ = "events"

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
    event_type: Mapped[str] = mapped_column(
        String(20), 
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, index=True, default=func.now())
    
    # Raw content (max 500KB as per Technical Design §3.1)
    raw_text: Mapped[str | None] = mapped_column(Text)
    
    # Metadata as JSON (SQLite) or JSONB (PostgreSQL)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB if not IS_SQLITE else JSON,
    )
    
    # Processing status
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    pipeline: Mapped[str | None] = mapped_column(String(50))
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column()

    # Constraints
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('card_save', 'meeting', 'call', 'manual')",
            name="event_type_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="event_status_check",
        ),
        CheckConstraint(
            "length(raw_text) <= 512000",  # 500KB = 512000 bytes
            name="raw_text_size_check",
        ),
        Index("idx_events_user_type_time", "user_id", "event_type", "timestamp"),
        Index("idx_events_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Event(id={self.id}, type={self.event_type}, title={self.title[:30]})>"

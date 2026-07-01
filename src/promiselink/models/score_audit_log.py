"""ScoreAuditLog model - audit trail for Todo dynamic priority score changes."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import IS_SQLITE, Base


class ScoreAuditLog(Base):
    """
    Audit log for Todo dynamic priority score changes.

    Records every score recalculation, supporting Insight Engine
    explainability and debugging.

    Schema aligned with Database_Design v2.9 §3.5b.
    """

    __tablename__ = "score_audit_logs"

    # Primary key (INTEGER autoincrement for SQLite/PG compatibility)
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign key to Todo (UUID in PostgreSQL, String(36) in SQLite — matches todos.id type)
    todo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("todos.id", ondelete="CASCADE"),
        nullable=False,
    )

    # User who owns the scored todo
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
    )

    # Score change
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Scoring model version (poc_v1 / phase1_v1)
    score_version: Mapped[str] = mapped_column(String(20), nullable=False)

    # Detailed calculation factors snapshot (JSONB for PG, JSON for SQLite)
    calculation_factors: Mapped[dict[str, Any]] = mapped_column(
        JSONB if not IS_SQLITE else JSON,
        nullable=False,
    )

    # Which scorer produced this result
    calculated_by: Mapped[str] = mapped_column(String(50), nullable=False)

    # What triggered this recalculation
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
    )

    # Constraints and indexes
    __table_args__ = (
        Index("idx_score_audit_user_time", "user_id", "created_at"),
        Index("idx_score_audit_todo", "todo_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ScoreAuditLog(id={self.id}, todo_id={self.todo_id}, "
            f"old={self.old_score}, new={self.new_score}, "
            f"by={self.calculated_by})>"
        )

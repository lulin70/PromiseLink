"""UsageRecord ORM model.

Stores per-request AI usage details for billing and analytics.  In
production this table is partitioned by month on PostgreSQL; the ORM
model is a plain table and partitioning is managed via raw DDL / Alembic.

Reference: Pro_Edition_Tech_Design_Phase0.md §3.4
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from gateway.database import Base


# BigInteger that falls back to Integer on SQLite for autoincrement support.
class BigIntegerForSQLite(TypeDecorator):
    """BigInteger that uses Integer on SQLite for autoincrement compatibility.

    SQLite only supports AUTOINCREMENT on ``INTEGER PRIMARY KEY``; using
    ``BigInteger`` directly causes ``NOT NULL constraint failed`` on insert.
    This variant transparently uses ``Integer`` on SQLite and ``BigInteger``
    on all other backends (PostgreSQL in production).
    """

    impl = BigInteger
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "sqlite":
            return dialect.type_descriptor(Integer())
        return dialect.type_descriptor(BigInteger())


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class UsageRecord(Base):
    """A single AI usage record (LLM / ASR / TTS / OCR).

    Attributes:
        id: Auto-incrementing big-integer primary key.
        user_id: User who made the request.
        provider: LLM provider used.
        model: Model identifier (e.g. ``deepseek-chat``).
        request_type: Call type — ``llm``/``asr``/``tts``/``ocr``.
        tokens_in: Input tokens consumed.
        tokens_out: Output tokens produced.
        cost: Cost in CNY.
        latency_ms: End-to-end latency in milliseconds.
        status: Request outcome — ``success``/``failed``/``timeout``.
        created_at: When the record was written.

    Note:
        PostgreSQL monthly partitioning is set up via DDL::

            CREATE TABLE usage_records_2026_06
            PARTITION OF usage_records
            FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
    """

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(BigIntegerForSQLite, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    request_type: Mapped[str] = mapped_column(String(16), nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=Decimal("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return (
            f"UsageRecord(id={self.id}, user_id={self.user_id!r}, "
            f"request_type={self.request_type!r}, status={self.status!r})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict (for audit / logging)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "model": self.model,
            "request_type": self.request_type,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost": str(self.cost),
            "latency_ms": self.latency_ms,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

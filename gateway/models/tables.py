"""SQLAlchemy ORM models for gateway tables.

Reference: Pro_Edition_Tech_Design_Phase0.md §3 Data Model Design

These models use generic types compatible with both SQLite (testing) and
PostgreSQL (production). JSONB columns fall back to JSON on SQLite.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from decimal import Decimal


class Base(DeclarativeBase):
    """Declarative base for all gateway models."""


class License(Base):
    """License table — stores subscription and device binding info."""

    __tablename__ = "licenses"

    license_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(16), default="pro")
    quota_limit_tokens: Mapped[int] = mapped_column(BigInteger, default=500000)
    quota_limit_asr: Mapped[int] = mapped_column(Integer, default=200)
    quota_limit_tts: Mapped[int] = mapped_column(Integer, default=200)
    quota_limit_ocr: Mapped[int] = mapped_column(Integer, default=100)
    quota_used_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    quota_used_asr: Mapped[int] = mapped_column(Integer, default=0)
    quota_used_tts: Mapped[int] = mapped_column(Integer, default=0)
    quota_used_ocr: Mapped[int] = mapped_column(Integer, default=0)
    quota_reset_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    device_bound_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    max_devices: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ApiKey(Base):
    """API Key pool entry — one row per provider API key."""

    __tablename__ = "api_key_pool"

    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    api_key_encrypted: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    rpm_limit: Mapped[int] = mapped_column(Integer, default=60)
    health_score: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    circuit_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    base_url: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UsageRecord(Base):
    """Usage record — one row per AI API call."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    request_id: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(64))
    license_key: Mapped[str] = mapped_column(String(64))
    request_type: Mapped[str] = mapped_column(String(16))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    key_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_cny: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class MonthlyUsage(Base):
    """Monthly usage summary — one row per (user, year-month).

    Reference: Pro_Edition_Tech_Design_Phase0.md §3.6.2
    """

    __tablename__ = "monthly_usage"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    license_key: Mapped[str] = mapped_column(String(64))
    year_month: Mapped[str] = mapped_column(String(7), primary_key=True)
    total_tokens: Mapped[int] = mapped_column(BigInteger, default=0)
    total_cost_cny: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    asr_count: Mapped[int] = mapped_column(Integer, default=0)
    tts_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="green")
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AuditLog(Base):
    """Audit log — security-relevant events.

    Reference: Pro_Edition_Tech_Design_Phase0.md §3.6.3
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[str] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

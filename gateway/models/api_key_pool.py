"""ApiKeyPool ORM model.

Stores encrypted provider API keys together with runtime health metadata
used by the weighted round-robin selector.

Reference: Pro_Edition_Tech_Design_Phase0.md §3.3
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from gateway.database import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class ApiKeyPool(Base):
    """An entry in the API Key pool.

    The ``api_key_encrypted`` column holds the provider key encrypted with
    AES-256-GCM (see ``gateway.config.encrypt_api_key``).  Runtime health
    state (``health_score``, ``status``, ``cooldown_until`` …) is also
    persisted here so it survives gateway restarts, though the hot path
    reads from an in-memory copy managed by
    :class:`gateway.services.api_key_pool_manager.APIKeyPoolManager`.

    Attributes:
        id: Primary key (UUID string).
        provider: LLM provider — ``deepseek``/``moka_ai``/``openai``/``anthropic``.
        api_key_encrypted: AES-256-GCM encrypted API key.
        base_weight: Round-robin base weight (1-100).
        health_score: Health score 0.00-1.00.
        total_requests: Lifetime request count.
        success_requests: Lifetime successful request count.
        failed_requests: Lifetime failed request count.
        last_used_at: Last time this key was selected.
        cooldown_until: Cooldown expiry (429 → 60 s).
        circuit_breaker_until: Circuit-breaker expiry (3× 5xx → 5 min).
        status: Pool status — ``active``/``rate_limited``/``circuit_open``/``disabled``.
        created_at: Record creation time.
        updated_at: Record last-update time.
    """

    __tablename__ = "api_key_pool"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    # ── Weighted round-robin ──
    base_weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    health_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("1.00")
    )

    # ── Lifetime statistics ──
    total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Runtime state ──
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    circuit_breaker_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    # ── Audit ──
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return (
            f"ApiKeyPool(id={self.id!r}, provider={self.provider!r}, "
            f"status={self.status!r}, health_score={self.health_score})"
        )

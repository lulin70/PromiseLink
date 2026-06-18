"""License ORM model.

Stores professional-edition license information: plan type, token/media
quotas, device binding, and lifecycle timestamps.

Reference: Pro_Edition_Tech_Design_Phase0.md §3.2
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from gateway.database import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


class License(Base):
    """Professional-edition license record.

    Attributes:
        id: Primary key (UUID string).
        user_id: Owning user identifier.
        license_key: Human-readable key ``PL-PRO-xxxx-xxxx-xxxx``.
        plan_type: Subscription plan — ``pro`` or ``trial``.
        quota_limit_tokens: Monthly token allowance.
        quota_used_tokens: Tokens consumed this month.
        quota_limit_media: Monthly media-call allowance (ASR/TTS/OCR).
        quota_used_media: Media calls consumed this month.
        device_fingerprint: SHA-256 device fingerprint for anti-piracy.
        activated_at: When the license was first activated.
        expires_at: Subscription expiry timestamp.
        status: Lifecycle status — ``active``/``expired``/``cancelled``/``suspended``.
        created_at: Record creation time.
        updated_at: Record last-update time.
    """

    __tablename__ = "licenses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    license_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    plan_type: Mapped[str] = mapped_column(String(16), nullable=False, default="pro")

    # ── Quotas ──
    quota_limit_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=500000)
    quota_used_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    quota_limit_media: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    quota_used_media: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Device binding (I-4 anti-piracy) ──
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── Lifecycle ──
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    # ── Audit ──
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return (
            f"License(id={self.id!r}, license_key={self.license_key!r}, "
            f"status={self.status!r})"
        )

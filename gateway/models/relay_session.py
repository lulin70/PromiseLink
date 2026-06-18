"""RelaySession ORM model.

Tracks active WebSocket relay sessions between the gateway and local
Docker relay clients.  Sessions expire after 24 hours and are pruned
by a periodic cleanup task.

Reference: Pro_Edition_Tech_Design_Phase0.md §3.5
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from gateway.database import Base


def _utcnow() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(UTC)


def _default_expiry() -> datetime:
    """Default session expiry = now + 24 h."""
    return _utcnow() + timedelta(hours=24)


class RelaySession(Base):
    """A WebSocket relay session.

    Attributes:
        id: Primary key (UUID string, also the session_id).
        user_id: Owning user.
        jwt_jti: JWT unique ID bound to this session (for revocation).
        device_fingerprint: Device fingerprint from the relay client.
        created_at: Session creation time.
        expires_at: Session expiry time (created_at + 24 h).
        status: Session status — ``active``/``disconnected``/``expired``.
    """

    __tablename__ = "relay_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    jwt_jti: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_default_expiry, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", index=True)

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return (
            f"RelaySession(id={self.id!r}, user_id={self.user_id!r}, "
            f"status={self.status!r})"
        )

    @property
    def is_expired(self) -> bool:
        """Return True if the session has passed its expiry time."""
        if self.expires_at is None:
            return False
        # Handle both tz-aware and tz-naive datetimes.
        now = datetime.now(UTC)
        exp = self.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=UTC)
        return now > exp

"""F-50: Voice Session models — voice_sessions, voice_turns, voice_analytics.

Schema aligned with F-50 Voice Assistant Technical Design.
Supports NLU intent classification, multi-turn dialogue, and daily analytics aggregation.
"""

import uuid
from datetime import date as date_type, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    event as sa_event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from promiselink.database import Base, IS_SQLITE, _uuid_default


class VoiceSession(Base):
    """Main voice session table — stores each voice interaction with NLU results."""

    __tablename__ = "voice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )

    # Session status
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)

    # ASR transcription
    query_text: Mapped[str] = mapped_column(Text, nullable=False)

    # NLU results
    intent: Mapped[str | None] = mapped_column(String(30), index=True)
    intent_confidence: Mapped[float | None] = mapped_column(nullable=True)
    slots: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON
    )

    # ASR metadata
    asr_confidence: Mapped[float | None] = mapped_column(nullable=True)
    asr_provider: Mapped[str | None] = mapped_column(String(30))

    # Response (NLG + TTS)
    response_text: Mapped[str | None] = mapped_column(Text)
    tts_audio_url: Mapped[str | None] = mapped_column(String(500))

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column()

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'completed', 'error')",
            name="voice_session_status_check",
        ),
        Index("idx_voice_sessions_user_status", "user_id", "status"),
        Index("idx_voice_sessions_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<VoiceSession(id={self.id}, intent={self.intent}, "
            f"status={self.status}, query={self.query_text[:30]})>"
        )


class VoiceTurn(Base):
    """Multi-turn dialogue records — each user utterance within a session."""

    __tablename__ = "voice_turns"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        ForeignKey("voice_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    turn_number: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)

    user_input: Mapped[str] = mapped_column(Text, nullable=False)
    system_response: Mapped[str | None] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=func.now())

    __table_args__ = (
        Index("idx_voice_turns_session_turn", "session_id", "turn_number"),
    )

    def __repr__(self) -> str:
        return f"<VoiceTurn(session_id={self.session_id}, turn={self.turn_number})>"


class VoiceAnalytics(Base):
    """Daily aggregated analytics for voice interactions — one row per user per day."""

    __tablename__ = "voice_analytics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        primary_key=True,
        default=_uuid_default,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True) if not IS_SQLITE else String(36),
        nullable=False,
        index=True,
    )
    date: Mapped[date_type] = mapped_column(nullable=False, index=True)

    # Aggregated counters
    total_sessions: Mapped[int] = mapped_column(default=0)
    total_turns: Mapped[int] = mapped_column(default=0)
    avg_confidence: Mapped[float] = mapped_column(default=0.0)
    intent_distribution: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB if not IS_SQLITE else JSON
    )
    error_count: Mapped[int] = mapped_column(default=0)

    __table_args__ = (
        CheckConstraint("total_sessions >= 0", name="analytics_sessions_nonneg"),
        CheckConstraint("total_turns >= 0", name="analytics_turns_nonneg"),
        CheckConstraint("error_count >= 0", name="analytics_errors_nonneg"),
        Index("idx_voice_analytics_user_date", "user_id", "date", unique=True),
    )

    def __repr__(self) -> str:
        return f"<VoiceAnalytics(user_id={self.user_id}, date={self.date})>"


# ── Event Listeners ──


@sa_event.listens_for(VoiceSession, "before_update")
def _voice_session_auto_complete(mapper, connection, target: VoiceSession) -> None:
    """Auto-set completed_at when VoiceSession status changes to 'completed'."""
    if target.status == "completed" and target.completed_at is None:
        target.completed_at = datetime.now()

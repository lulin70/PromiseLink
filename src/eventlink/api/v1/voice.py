"""F-50: Voice API endpoints — voice session management and NLU processing.

Endpoints:
  POST /voice/session   — Create a voice session (ASR + NLU + response generation)
  GET  /voice/sessions   — List user's voice sessions
  DELETE /voice/sessions — Clear user's voice data (GDPR)
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.auth import get_optional_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models.voice_session import VoiceSession, VoiceTurn
from eventlink.services.llm_client import LLMClient
from eventlink.services.nlu_intent_classifier import NLUIntentClassifier, VoiceIntent

logger = get_logger("eventlink.api.voice")
router = APIRouter(prefix="/voice", tags=["Voice"])


# ── Pydantic Models ──


class VoiceSessionRequest(BaseModel):
    """Request body for creating a new voice session."""

    query_text: str = Field(..., min_length=1, max_length=2000, description="ASR转写的用户语音文字")
    asr_confidence: float | None = Field(None, ge=0.0, le=1.0, description="ASR识别置信度")
    asr_provider: str = Field(default="wechat", description="ASR提供商: wechat/whisper")


class VoiceSessionResponse(BaseModel):
    """Response for a created voice session."""

    session_id: uuid.UUID | str
    intent: str | None = None
    response_text: str | None = None
    slots: dict | None = None
    tts_audio_url: str | None = None

    model_config = ConfigDict(from_attributes=True)


class VoiceSessionListItem(BaseModel):
    """Item in the voice session list."""

    session_id: uuid.UUID | str
    query_text: str
    intent: str | None = None
    status: str
    asr_provider: str | None = None
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class VoiceSessionListResponse(BaseModel):
    """Paginated list of voice sessions."""

    total: int = 0
    items: list[VoiceSessionListItem] = []


# ── Endpoints ──


@router.post(
    "/session",
    response_model=VoiceSessionResponse,
    tags=["Voice"],
)
async def create_voice_session(
    body: VoiceSessionRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
) -> VoiceSessionResponse:
    """Create a new voice session with NLU classification.

    Accepts ASR-transcribed text, runs NLU intent classification,
    stores the session record, and returns the classified intent.
    """
    new_request_id()

    logger.info(
        "voice_session_create",
        user_id=user_id,
        query_text=body.query_text[:100],
        asr_provider=body.asr_provider,
        asr_confidence=body.asr_confidence,
    )

    # Run NLU classification
    llm_client = LLMClient()
    classifier = NLUIntentClassifier(llm_client=llm_client)
    nlu_result = await classifier.classify(body.query_text)

    # Generate placeholder response text (NLG will be enhanced in future phases)
    response_text = _generate_response_text(nlu_result.intent, nlu_result.slots)

    # Create voice session record
    voice_session = VoiceSession(
        id=str(uuid.uuid4()),
        user_id=user_id,
        query_text=body.query_text,
        intent=nlu_result.intent.value if nlu_result.intent != VoiceIntent.CHITCHAT else None,
        intent_confidence=nlu_result.confidence,
        slots=nlu_result.slots if nlu_result.slots else None,
        asr_confidence=body.asr_confidence,
        asr_provider=body.asr_provider,
        response_text=response_text,
        status="completed" if nlu_result.intent in (VoiceIntent.EXIT, VoiceIntent.CHITCHAT) else "active",
    )
    session.add(voice_session)
    await session.flush()  # Get the ID without committing yet

    logger.info(
        "voice_session_created",
        session_id=str(voice_session.id),
        intent=nlu_result.intent.value,
        confidence=nlu_result.confidence,
    )

    return VoiceSessionResponse(
        session_id=voice_session.id,
        intent=nlu_result.intent.value,
        response_text=response_text,
        slots=nlu_result.slots if nlu_result.slots else None,
        tts_audio_url=None,
    )


@router.get(
    "/sessions",
    response_model=VoiceSessionListResponse,
    tags=["Voice"],
)
async def list_voice_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
) -> VoiceSessionListResponse:
    """List the current user's voice sessions with pagination."""
    new_request_id()

    logger.info(
        "voice_sessions_list",
        user_id=user_id,
        limit=limit,
        offset=offset,
    )

    # Count total
    count_result = await session.execute(
        select(VoiceSession.__table__.c.id)
        .where(VoiceSession.user_id == user_id)
    )
    total = len(count_result.all())

    # Fetch paginated results
    result = await session.execute(
        select(VoiceSession)
        .where(VoiceSession.user_id == user_id)
        .order_by(VoiceSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    sessions = result.scalars().all()

    items = [
        VoiceSessionListItem(
            session_id=s.id,
            query_text=s.query_text,
            intent=s.intent,
            status=s.status,
            asr_provider=s.asr_provider,
            created_at=s.created_at,
        )
        for s in sessions
    ]

    return VoiceSessionListResponse(total=total, items=items)


@router.delete(
    "/sessions",
    tags=["Voice"],
)
async def delete_voice_sessions(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_optional_user_id),
) -> dict:
    """Delete all voice data for the current user (GDPR compliance)."""
    new_request_id()

    logger.warning(
        "voice_sessions_delete_all",
        user_id=user_id,
    )

    # Delete voice turns first (foreign key dependency), then sessions
    await session.execute(
        delete(VoiceTurn).where(
            VoiceTurn.session_id.in_(
                select(VoiceSession.id).where(VoiceSession.user_id == user_id)
            )
        )
    )
    result = await session.execute(
        delete(VoiceSession).where(VoiceSession.user_id == user_id)
    )
    deleted_count = result.rowcount

    logger.info(
        "voice_sessions_deleted",
        user_id=user_id,
        deleted_count=deleted_count,
    )

    return {
        "deleted_count": deleted_count,
        "message": "All voice data deleted successfully",
    }


# ── Helpers ──


def _generate_response_text(intent, slots: dict) -> str:
    """Generate a simple response text based on classified intent (placeholder NLG).

    Future enhancement: integrate full NLG pipeline.
    """
    responses = {
        VoiceIntent.SCHEDULE_QUERY: "好的，正在为您查询日程安排...",
        VoiceIntent.SCHEDULE_RANGE: "好的，正在为您查询范围内的日程...",
        VoiceIntent.PROMISE_TRACKER: "好的，正在为您查询待完成的承诺事项...",
        VoiceIntent.RELATIONSHIP_STATUS: "好的，正在为您查询关系进展...",
        VoiceIntent.ACTION_SUGGESTION: "让我来分析一下您的下一步行动建议...",
        VoiceIntent.TODO_CREATE: f"已为您记录提醒：{slots.get('content', '事项')}",
        VoiceIntent.UNCLEAR: "抱歉，我没有完全理解您的意思，能再说一遍吗？",
        VoiceIntent.CHITCHAT: None,  # Chitchat returns no business response
        VoiceIntent.EXIT: "好的，再见！",
    }
    return responses.get(intent, "已收到您的指令。")

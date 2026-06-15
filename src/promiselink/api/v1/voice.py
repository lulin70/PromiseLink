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
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_llm_dependency
from promiselink.api.v1.schemas import PaginatedResponse
from promiselink.config import get_settings
from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.voice_session import VoiceSession, VoiceTurn
from promiselink.schemas.api_responses import DeleteCountResponse
from promiselink.services.llm_client import LLMClient
from promiselink.services.nlu_intent_classifier import NLUIntentClassifier, VoiceIntent

logger = get_logger("promiselink.api.voice")
router = APIRouter(prefix="/voice", tags=["Voice"], dependencies=[Depends(rate_limit_llm_dependency)])


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


# ── Endpoints ──


@router.post(
    "/session",
    response_model=VoiceSessionResponse,
    tags=["Voice"],
)
async def create_voice_session(
    body: VoiceSessionRequest,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
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
    llm_client = LLMClient(config=get_settings())
    classifier = NLUIntentClassifier(llm_client=llm_client)
    nlu_result = await classifier.classify(body.query_text)

    # Generate response text using NLG service (queries real DB data)
    from promiselink.services.nlg_service import generate_nlu_response
    response_text = await generate_nlu_response(
        session=session,
        intent=nlu_result.intent,
        slots=nlu_result.slots,
        user_id=user_id,
    )

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
    response_model=PaginatedResponse[VoiceSessionListItem],
    tags=["Voice"],
)
async def list_voice_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> PaginatedResponse[VoiceSessionListItem]:
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
        select(func.count(VoiceSession.id)).where(VoiceSession.user_id == user_id)
    )
    total = count_result.scalar() or 0

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

    return PaginatedResponse(items=items, total=total, limit=min(limit, 500), offset=offset)


@router.delete(
    "/sessions",
    tags=["Voice"],
    response_model=DeleteCountResponse,
)
async def delete_voice_sessions(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> DeleteCountResponse:
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

    return DeleteCountResponse(
        deleted_count=deleted_count,
        message="All voice data deleted successfully",
    )

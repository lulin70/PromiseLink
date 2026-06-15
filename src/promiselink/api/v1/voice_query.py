"""F-50: Voice Query API — dedicated query endpoint for voice assistant.

Endpoint:
  POST /voice/query — Accept voice text, classify intent, query DB, return structured response

PRD v4.4 F-50 Phase 1.1: Supports 3 core query types:
  - schedule_query (日程查询)
  - promise_query (承诺追踪)
  - relationship_query (关系推进查询)
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_llm_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.services.llm_client import LLMClient
from promiselink.services.nlg_service import generate_nlu_response
from promiselink.services.nlu_intent_classifier import NLUIntentClassifier, VoiceIntent
from promiselink.services.voice_query_service import execute_query

logger = get_logger("promiselink.api.voice_query")
router = APIRouter(prefix="/voice", tags=["Voice"], dependencies=[Depends(rate_limit_llm_dependency)])


# ── Pydantic Models ──


class VoiceQueryRequest(BaseModel):
    """Request body for voice query."""

    text: str = Field(..., min_length=1, max_length=2000, description="语音转写的用户查询文字")


class VoiceQueryResponse(BaseModel):
    """Response for voice query with structured data."""

    intent: str
    confidence: float
    response: str
    data: dict | None = None


# ── Endpoint ──


@router.post(
    "/query",
    response_model=VoiceQueryResponse,
    tags=["Voice"],
)
async def voice_query(
    body: VoiceQueryRequest,
    session: AsyncSession = Depends(get_async_session),
    auth_user_id: str = Depends(get_current_user_id),
) -> VoiceQueryResponse:
    """Process a voice query: classify intent, query DB, generate NLG response.

    Accepts voice text, runs NLU intent classification, queries the database
    based on the classified intent, and returns both a natural language
    response and structured data.
    """
    new_request_id()

    # Use authenticated user_id directly
    user_id = auth_user_id

    logger.info(
        "voice_query_received",
        user_id=user_id,
        text=body.text[:100],
    )

    # Step 1: NLU intent classification
    from promiselink.config import get_settings
    settings = get_settings()
    llm_client = LLMClient(config=settings)
    classifier = NLUIntentClassifier(llm_client=llm_client)
    nlu_result = await classifier.classify(body.text)

    intent = nlu_result.intent
    confidence = nlu_result.confidence
    slots = nlu_result.slots or {}

    logger.info(
        "voice_query_classified",
        intent=intent.value,
        confidence=confidence,
        method=nlu_result.method,
    )

    # Step 2: Query DB based on intent (only for query intents)
    data = {}
    query_intents = {VoiceIntent.SCHEDULE_QUERY, VoiceIntent.PROMISE_TRACKER, VoiceIntent.RELATIONSHIP_STATUS}
    if intent in query_intents:
        data = await execute_query(session, user_id, intent, slots)

    # Step 3: Generate NLG response
    response_text = await generate_nlu_response(
        session=session,
        intent=intent,
        slots=slots,
        user_id=user_id,
    )

    logger.info(
        "voice_query_completed",
        intent=intent.value,
        has_data=bool(data),
    )

    return VoiceQueryResponse(
        intent=intent.value,
        confidence=confidence,
        response=response_text,
        data=data if data else None,
    )

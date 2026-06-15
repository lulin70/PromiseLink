"""WeChat Forward API endpoint — PRD §5.17.

Accepts pasted/forwarded WeChat chat content, parses it into a structured Event,
persists it, and triggers the processing pipeline.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.auth import get_current_user_id
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.services.event_processor import process_event_background
from promiselink.services.wechat_forward_adapter import WeChatForwardAdapter

logger = get_logger("promiselink.api.wechat_forward")
router = APIRouter(prefix="/wechat", tags=["WeChatForward"])


# ── Pydantic Models ──


class WeChatForwardRequest(BaseModel):
    """Request body for forwarding WeChat chat content."""

    text: str = Field(..., min_length=1, max_length=512000, description="转发的微信聊天内容")


class WeChatForwardResponse(BaseModel):
    """Response for a successfully parsed WeChat forward."""

    id: uuid.UUID | str
    user_id: uuid.UUID | str
    event_type: str
    source: str
    title: str
    status: str
    speakers: list[str] = []
    message_count: int = 0
    time_range: str = ""
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


# ── Endpoint ──


@router.post(
    "/forward",
    response_model=WeChatForwardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def forward_wechat_message(
    body: WeChatForwardRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> WeChatForwardResponse:
    """Parse forwarded WeChat chat content into an Event.

    Accepts raw pasted/forwarded WeChat chat text, parses it using
    rule-based logic to extract speakers, messages, and time range,
    then creates an Event and triggers the processing pipeline.
    """
    new_request_id()

    logger.info(
        "wechat_forward_request",
        user_id=user_id,
        text_length=len(body.text),
    )

    # Parse the forwarded message
    adapter = WeChatForwardAdapter()
    event = adapter.parse_forwarded_message(text=body.text, user_id=user_id)

    # Persist the event
    session.add(event)
    await session.commit()
    await session.refresh(event)

    logger.info(
        "wechat_forward_event_created",
        event_id=str(event.id),
        speakers=event.metadata_.get("speakers", []) if event.metadata_ else [],
        message_count=event.metadata_.get("message_count", 0) if event.metadata_ else 0,
    )

    # Trigger async processing pipeline in background
    background_tasks.add_task(process_event_background, event_id=event.id)

    metadata = event.metadata_ or {}
    return WeChatForwardResponse(
        id=event.id,
        user_id=event.user_id,
        event_type=event.event_type,
        source=event.source,
        title=event.title,
        status=event.status,
        speakers=metadata.get("speakers", []),
        message_count=metadata.get("message_count", 0),
        time_range=metadata.get("time_range", ""),
        created_at=event.created_at,
    )

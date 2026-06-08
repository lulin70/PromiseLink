"""Media API endpoints — ASR, TTS, OCR processing.

Endpoints:
  POST /media/asr       — Upload audio, return transcribed text
  POST /media/tts       — Accept text, return audio file
  POST /media/ocr       — Upload image, return extracted text
  POST /media/ocr-event — Upload image, OCR + auto-create Event
"""

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.api.dependencies import rate_limit_llm_dependency
from eventlink.config import get_settings
from eventlink.core.auth import get_current_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models import Event
from eventlink.services.asr_service import ASRService
from eventlink.services.ocr_service import OCRService
from eventlink.services.tts_service import TTSService

logger = get_logger("eventlink.api.media")
router = APIRouter(prefix="/media", tags=["Media"], dependencies=[Depends(rate_limit_llm_dependency)])


# ── Pydantic Models ──


class ASRResponse(BaseModel):
    """Response for ASR transcription."""

    text: str
    confidence: float
    provider: str


class TTSRequest(BaseModel):
    """Request body for TTS synthesis."""

    text: str = Field(..., min_length=1, max_length=4096, description="要合成的文本")
    voice: str = Field(default="alloy", description="语音名称")


class OCRResponse(BaseModel):
    """Response for OCR recognition."""

    text: str
    structured_data: dict | None
    provider: str


class OCREventResponse(BaseModel):
    """Response for OCR + Event creation."""

    event_id: str
    ocr_text: str
    structured_data: dict | None


# ── Endpoints ──


@router.post(
    "/asr",
    response_model=ASRResponse,
)
async def asr_endpoint(
    audio: UploadFile,
    user_id: str = Depends(get_current_user_id),
) -> ASRResponse:
    """Upload audio file and return transcribed text.

    Accepts multipart/form-data with audio file (mp3/wav).
    """
    new_request_id()

    settings = get_settings()
    audio_bytes = await audio.read()

    logger.info(
        "asr_request",
        user_id=user_id,
        filename=audio.filename,
        audio_size=len(audio_bytes),
    )

    try:
        service = ASRService(config=settings)
        result = await service.transcribe(
            audio_bytes=audio_bytes,
            filename=audio.filename or "audio.mp3",
        )
        await service.close()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )

    return ASRResponse(
        text=result.text,
        confidence=result.confidence,
        provider=result.provider,
    )


@router.post(
    "/tts",
)
async def tts_endpoint(
    body: TTSRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Accept text and return audio file (mp3).

    Returns audio/mp3 response with streaming content.
    """
    new_request_id()

    settings = get_settings()

    logger.info(
        "tts_request",
        user_id=user_id,
        text_length=len(body.text),
        voice=body.voice,
    )

    try:
        service = TTSService(config=settings)
        result = await service.synthesize(
            text=body.text,
            voice=body.voice,
        )
        await service.close()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if result.audio_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TTS service unavailable",
        )

    from fastapi.responses import Response

    return Response(
        content=result.audio_bytes,
        media_type="audio/mp3",
        headers={
            "Content-Disposition": "attachment; filename=tts_output.mp3",
            "X-Provider": result.provider,
            "X-Duration-Ms": str(result.duration_ms or 0),
        },
    )


@router.post(
    "/ocr",
    response_model=OCRResponse,
)
async def ocr_endpoint(
    image: UploadFile,
    user_id: str = Depends(get_current_user_id),
) -> OCRResponse:
    """Upload image and return extracted text.

    Accepts multipart/form-data with image file (jpg/png).
    """
    new_request_id()

    settings = get_settings()
    image_bytes = await image.read()

    logger.info(
        "ocr_request",
        user_id=user_id,
        filename=image.filename,
        image_size=len(image_bytes),
    )

    try:
        service = OCRService(config=settings)
        result = await service.recognize(
            image_bytes=image_bytes,
            filename=image.filename or "image.jpg",
        )
        await service.close()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    return OCRResponse(
        text=result.text,
        structured_data=result.structured_data,
        provider=result.provider,
    )


@router.post(
    "/ocr-event",
    response_model=OCREventResponse,
)
async def ocr_event_endpoint(
    image: UploadFile,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> OCREventResponse:
    """Upload image, OCR the image, and auto-create an Event via the existing pipeline.

    Accepts multipart/form-data with image file.
    OCR the image → extract text → create an Event → trigger pipeline.
    """
    new_request_id()

    settings = get_settings()
    image_bytes = await image.read()

    logger.info(
        "ocr_event_request",
        user_id=user_id,
        filename=image.filename,
        image_size=len(image_bytes),
    )

    # Step 1: OCR the image
    try:
        ocr_service = OCRService(config=settings)
        ocr_result = await ocr_service.recognize(
            image_bytes=image_bytes,
            filename=image.filename or "image.jpg",
        )
        await ocr_service.close()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    if not ocr_result.text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract text from image",
        )

    # Step 2: Create Event from OCR text
    raw_text = ocr_result.text
    if ocr_result.structured_data:
        raw_text = json.dumps(
            {"text": ocr_result.text, "structured_data": ocr_result.structured_data},
            ensure_ascii=False,
        )

    event = Event(
        user_id=user_id,
        event_type="card_save",
        source="ocr",
        title="名片扫描" if ocr_result.structured_data else "图片OCR",
        timestamp=datetime.now(UTC),
        raw_text=raw_text,
        metadata_={"ocr_provider": ocr_result.provider, "original_filename": image.filename},
        status="pending",
    )

    session.add(event)
    await session.commit()
    await session.refresh(event)

    logger.info(
        "ocr_event_created",
        event_id=str(event.id),
        ocr_provider=ocr_result.provider,
    )

    # Step 3: Trigger async processing pipeline in background
    background_tasks.add_task(_process_event_background, event_id=event.id)

    return OCREventResponse(
        event_id=str(event.id),
        ocr_text=ocr_result.text,
        structured_data=ocr_result.structured_data,
    )


# ── Background Pipeline Processing ──


async def _process_event_background(event_id: uuid.UUID) -> None:
    """Process an event through the pipeline in the background."""
    from eventlink.services.event_pipeline import process_event_with_short_transactions

    await process_event_with_short_transactions(event_id=str(event_id))

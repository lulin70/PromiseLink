"""Relay API endpoints — LLM, ASR, TTS, OCR.

Reference: Pro_Edition_Tech_Design_Phase0.md §4.3.4-§4.3.7, §8

Endpoints:
- POST /api/v1/pro/relay/llm — LLM relay (relay_token, supports SSE)
- POST /api/v1/pro/relay/asr — ASR relay (relay_token)
- POST /api/v1/pro/relay/tts — TTS relay (relay_token)
- POST /api/v1/pro/relay/ocr — OCR relay (relay_token)
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from gateway.core.exceptions import ValidationError
from gateway.middleware.auth import get_license_key, get_user_id, verify_relay_token
from gateway.schemas.errors import UnifiedResponse
from gateway.schemas.relay import (
    ASRRelayResponse,
    LLMRelayRequest,
    LLMRelayResponse,
    OCRRelayResponse,
    TTSRelayRequest,
)
from gateway.services.relay_service import RelayService, format_sse_event

router = APIRouter(prefix="/api/v1/pro/relay", tags=["relay"])


def get_relay_service(request: Request) -> RelayService:
    """Get the RelayService from app state."""
    service = getattr(request.app.state, "relay_service", None)
    if service is None:
        raise RuntimeError("RelayService not initialized")
    return service


@router.post("/llm")
async def relay_llm(
    request: Request,
    body: LLMRelayRequest,
    jwt_payload: dict = Depends(verify_relay_token),
) -> Any:
    """LLM relay request.

    Supports both streaming (SSE) and non-streaming responses.
    When body.stream=True, returns text/event-stream with token events.

    SSE event format:
        event: token
        data: {"content": "...", "index": N}

        event: done
        data: {"usage": {...}, "billing": {...}}
    """
    service = get_relay_service(request)
    user_id = get_user_id(request)
    license_key = get_license_key(request)

    if body.stream:
        # Streaming response with SSE
        result = await service.relay_llm(body, user_id, license_key)

        async def event_generator():
            """Generate SSE events from the relay service."""
            async for event in result:
                yield format_sse_event(event["event"], event["data"])

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Non-streaming response
        result = await service.relay_llm(body, user_id, license_key)
        return UnifiedResponse(
            request_id=getattr(request.state, "request_id", ""),
            success=True,
            data=result,
        )


@router.post("/asr", response_model=UnifiedResponse[ASRRelayResponse])
async def relay_asr(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (mp3/wav/m4a)"),
    model: str = Form(default="whisper-1"),
    language: str = Form(default="zh"),
    jwt_payload: dict = Depends(verify_relay_token),
) -> UnifiedResponse[ASRRelayResponse]:
    """ASR relay — speech to text via Moka AI Whisper.

    Accepts multipart/form-data with an audio file.
    """
    service = get_relay_service(request)
    user_id = get_user_id(request)
    license_key = get_license_key(request)

    # Read audio data
    audio_data = await audio.read()

    # Validate size
    max_size = service.settings.asr_max_audio_size_mb * 1024 * 1024
    if len(audio_data) > max_size:
        raise ValidationError(
            f"Audio file too large: {len(audio_data)} bytes (max {max_size})",
            code="AUDIO_TOO_LARGE",
        )

    result = await service.relay_asr(
        audio_data=audio_data,
        user_id=user_id,
        license_key=license_key,
        model=model,
        language=language,
    )
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=result,
    )


@router.post("/tts")
async def relay_tts(
    request: Request,
    body: TTSRelayRequest,
    jwt_payload: dict = Depends(verify_relay_token),
) -> Any:
    """TTS relay — text to speech via Moka AI TTS.

    Returns binary audio data (audio/mpeg).
    """
    service = get_relay_service(request)
    user_id = get_user_id(request)
    license_key = get_license_key(request)

    audio_bytes, billing_info = await service.relay_tts(
        text=body.text,
        user_id=user_id,
        license_key=license_key,
        model=body.model,
        voice=body.voice,
        speed=body.speed,
        response_format=body.response_format,
    )

    content_type = "audio/mpeg" if body.response_format == "mp3" else "audio/wav"
    return StreamingResponse(
        iter([audio_bytes]),
        media_type=content_type,
        headers={
            "X-Request-ID": getattr(request.state, "request_id", ""),
            "X-Billing-Count": "1",
            "X-Billing-TTS-Used": str(billing_info.get("monthly_tts_used", 0)),
            "X-Billing-TTS-Remaining": str(billing_info.get("monthly_tts_remaining", 0)),
        },
    )


@router.post("/ocr", response_model=UnifiedResponse[OCRRelayResponse])
async def relay_ocr(
    request: Request,
    image: UploadFile = File(..., description="Image file (jpg/png)"),
    task: str = Form(default="general"),
    model: str = Form(default="moka-vision"),
    jwt_payload: dict = Depends(verify_relay_token),
) -> UnifiedResponse[OCRRelayResponse]:
    """OCR relay — image text recognition via Moka AI Vision.

    Accepts multipart/form-data with an image file.
    """
    service = get_relay_service(request)
    user_id = get_user_id(request)
    license_key = get_license_key(request)

    # Read image data
    image_data = await image.read()

    # Validate size
    max_size = service.settings.ocr_max_image_size_mb * 1024 * 1024
    if len(image_data) > max_size:
        raise ValidationError(
            f"Image file too large: {len(image_data)} bytes (max {max_size})",
            code="IMAGE_TOO_LARGE",
        )

    result = await service.relay_ocr(
        image_data=image_data,
        user_id=user_id,
        license_key=license_key,
        task=task,
        model=model,
    )
    return UnifiedResponse(
        request_id=getattr(request.state, "request_id", ""),
        success=True,
        data=result,
    )

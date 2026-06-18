"""Relay service — LLM/ASR/TTS/OCR proxy with SSE streaming and provider degradation.

Reference: Pro_Edition_Tech_Design_Phase0.md §8 Relay Service Design

This module implements the core AI relay functionality:
- LLM relay with streaming SSE support (§8.2)
- ASR relay via Moka AI Whisper
- TTS relay via Moka AI TTS
- OCR relay via Moka AI Vision
- Provider degradation: Moka AI → OpenAI (§8.4)
- 30-second timeout with retry (§8.3)
- Usage recording (§7.4)

The service accepts injectable dependencies (APIKeyPool, BillingService,
httpx.AsyncClient) for easy testing.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from gateway.config import Settings, get_settings
from gateway.core.exceptions import (
    NoAvailableKeyError,
    ProviderRateLimitedError,
    UpstreamError,
    UpstreamTimeoutError,
)
from gateway.schemas.relay import (
    ASRRelayResponse,
    LLMRelayRequest,
    OCRRelayResponse,
)
from gateway.services.api_key_pool import APIKeyPool
from gateway.services.billing_service import BillingService


class RelayService:
    """AI relay service with provider degradation and SSE streaming.

    Attributes:
        api_key_pool: Key pool for selecting provider API keys.
        billing_service: Service for quota checking and usage recording.
        http_client: Optional pre-configured httpx.AsyncClient (for testing).
        settings: Gateway settings.
    """

    def __init__(
        self,
        api_key_pool: APIKeyPool,
        billing_service: BillingService,
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.api_key_pool = api_key_pool
        self.billing_service = billing_service
        self._http_client = http_client
        self.settings = settings or get_settings()

    async def _get_client(self) -> httpx.AsyncClient:
        """Return the HTTP client, creating one if not set."""
        if self._http_client is not None:
            return self._http_client
        return httpx.AsyncClient(timeout=self.settings.llm_request_timeout)

    async def relay_llm(
        self,
        request: LLMRelayRequest,
        user_id: str,
        license_key: str,
    ) -> dict[str, Any] | AsyncIterator[dict[str, Any]]:
        """Relay an LLM request to the provider.

        For non-streaming requests, returns a dict with the complete response.
        For streaming requests (request.stream=True), returns an async generator
        yielding SSE event dicts:
            {"event": "token", "data": {"content": "...", "index": N}}
            {"event": "done", "data": {"usage": {...}, "billing": {...}}}
            {"event": "error", "data": {"code": "...", "message": "..."}}

        Args:
            request: LLM relay request with provider, model, messages.
            user_id: User ID from JWT.
            license_key: License key from JWT.

        Returns:
            Dict (non-streaming) or async generator (streaming).

        Raises:
            QuotaExceededError: If token quota is exhausted.
            NoAvailableKeyError: If all keys are unavailable.
            UpstreamTimeoutError: If provider times out after retries.
            UpstreamError: If provider returns persistent errors.
        """
        # 1. Check quota
        traffic_light = self.billing_service.check_quota(user_id, license_key, "llm")

        # 2. Select provider and attempt relay with degradation
        if request.stream:
            return self._relay_llm_stream(request, user_id, license_key, traffic_light)
        else:
            return await self._relay_llm_non_stream(request, user_id, license_key, traffic_light)

    async def _relay_llm_non_stream(
        self,
        request: LLMRelayRequest,
        user_id: str,
        license_key: str,
        traffic_light: str,
    ) -> dict[str, Any]:
        """Handle non-streaming LLM relay with provider degradation."""
        request_id = str(uuid.uuid4())
        start_time = time.time()

        providers_to_try = self._get_provider_order(request.provider)
        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                result = await self._call_llm_provider(
                    provider=provider,
                    request=request,
                    request_id=request_id,
                )
                # Record usage
                duration_ms = int((time.time() - start_time) * 1000)
                cost = self.billing_service.calculate_cost(provider, result["usage"]["total_tokens"])
                await self.billing_service.record_usage(
                    request_id=request_id,
                    user_id=user_id,
                    license_key=license_key,
                    request_type="llm",
                    provider=provider,
                    model=request.model,
                    key_id=result.get("key_id"),
                    input_tokens=result["usage"]["input_tokens"],
                    output_tokens=result["usage"]["output_tokens"],
                    total_tokens=result["usage"]["total_tokens"],
                    duration_ms=duration_ms,
                    cost_cny=cost,
                )
                # Get remaining tokens after recording
                lic = self.billing_service._licenses.get(license_key)
                remaining = (lic.quota_limit_tokens - lic.quota_used_tokens) if lic else 0
                return {
                    "content": result["content"],
                    "model": request.model,
                    "usage": result["usage"],
                    "billing": {
                        "cost_cny": cost,
                        "monthly_status": traffic_light,
                        "remaining_tokens": max(0, remaining),
                    },
                }
            except (UpstreamTimeoutError, UpstreamError, ProviderRateLimitedError, NoAvailableKeyError) as e:
                last_error = e
                continue

        # All providers failed
        if last_error:
            raise last_error
        raise NoAvailableKeyError("All providers failed")

    async def _relay_llm_stream(
        self,
        request: LLMRelayRequest,
        user_id: str,
        license_key: str,
        traffic_light: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Handle streaming LLM relay with SSE events.

        Yields event dicts:
            {"event": "token", "data": {"content": "...", "index": N}}
            {"event": "done", "data": {"usage": {...}, "billing": {...}}}
            {"event": "error", "data": {"code": "...", "message": "..."}}
        """
        request_id = str(uuid.uuid4())
        start_time = time.time()
        providers_to_try = self._get_provider_order(request.provider)
        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                content_parts: list[str] = []
                usage_data: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
                key_id: str | None = None

                async for chunk in self._stream_llm_provider(provider, request, request_id):
                    if chunk["type"] == "token":
                        content_parts.append(chunk["content"])
                        yield {
                            "event": "token",
                            "data": {"content": chunk["content"], "index": chunk["index"]},
                        }
                    elif chunk["type"] == "usage":
                        usage_data = chunk["usage"]
                        key_id = chunk.get("key_id")
                    elif chunk["type"] == "error":
                        yield {
                            "event": "error",
                            "data": {"code": "UPSTREAM_ERROR", "message": chunk["message"]},
                        }
                        return

                # Record usage
                duration_ms = int((time.time() - start_time) * 1000)
                cost = self.billing_service.calculate_cost(provider, usage_data["total_tokens"])
                await self.billing_service.record_usage(
                    request_id=request_id,
                    user_id=user_id,
                    license_key=license_key,
                    request_type="llm",
                    provider=provider,
                    model=request.model,
                    key_id=key_id,
                    input_tokens=usage_data["input_tokens"],
                    output_tokens=usage_data["output_tokens"],
                    total_tokens=usage_data["total_tokens"],
                    duration_ms=duration_ms,
                    cost_cny=cost,
                )
                lic = self.billing_service._licenses.get(license_key)
                remaining = (lic.quota_limit_tokens - lic.quota_used_tokens) if lic else 0

                yield {
                    "event": "done",
                    "data": {
                        "usage": usage_data,
                        "billing": {
                            "cost_cny": cost,
                            "monthly_status": traffic_light,
                            "remaining_tokens": max(0, remaining),
                        },
                    },
                }
                return  # Success — stop trying providers

            except (UpstreamTimeoutError, UpstreamError, ProviderRateLimitedError, NoAvailableKeyError) as e:
                last_error = e
                continue

        # All providers failed
        if last_error:
            yield {
                "event": "error",
                "data": {
                    "code": getattr(last_error, "code", "UPSTREAM_ERROR"),
                    "message": str(last_error.message) if hasattr(last_error, "message") else str(last_error),
                },
            }
        else:
            yield {
                "event": "error",
                "data": {"code": "NO_AVAILABLE_KEY", "message": "All providers failed"},
            }

    def _get_provider_order(self, requested_provider: str) -> list[str]:
        """Return provider list in priority order (primary first, fallback second).

        If the requested provider fails, the fallback provider is tried.
        """
        primary = self.settings.primary_provider
        fallback = self.settings.fallback_provider
        if requested_provider and requested_provider != primary:
            return [requested_provider, primary, fallback]
        return [primary, fallback]

    async def _call_llm_provider(
        self,
        provider: str,
        request: LLMRelayRequest,
        request_id: str,
    ) -> dict[str, Any]:
        """Call a single LLM provider (non-streaming) with retry on key selection.

        Handles:
        - Key selection from pool
        - 429 → mark rate_limited, retry with different key
        - 5xx → mark 5xx error, retry (circuit breaker after 3)
        - Timeout → mark timeout, retry
        - Network error → mark network error, retry

        Returns dict with content and usage.
        """
        max_retries = self.settings.llm_max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries):
            key = self.api_key_pool.select_key(provider)
            try:
                client = await self._get_client()
                url = f"{key.base_url}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                }
                payload = {
                    "model": request.model,
                    "messages": [{"role": m.role, "content": m.content} for m in request.messages],
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "stream": False,
                }

                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    self.api_key_pool.mark_rate_limited(key.key_id)
                    last_error = ProviderRateLimitedError(f"Provider {provider} rate limited")
                    continue
                if resp.status_code >= 500:
                    self.api_key_pool.mark_5xx_error(key.key_id)
                    last_error = UpstreamError(f"Provider {provider} returned {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    # Client error — don't retry
                    raise UpstreamError(
                        f"Provider {provider} returned {resp.status_code}: {resp.text}"
                    )

                data = resp.json()
                self.api_key_pool.mark_success(key.key_id)

                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return {
                    "content": content,
                    "usage": {
                        "input_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    "key_id": key.key_id,
                }

            except httpx.TimeoutException:
                self.api_key_pool.mark_timeout(key.key_id)
                last_error = UpstreamTimeoutError(f"Provider {provider} timed out")
                continue
            except httpx.ConnectError as e:
                self.api_key_pool.mark_network_error(key.key_id)
                last_error = UpstreamError(f"Network error: {e}")
                continue
            except (ProviderRateLimitedError, UpstreamError):
                continue

        if last_error:
            raise last_error
        raise NoAvailableKeyError(f"No available keys for provider {provider}")

    async def _stream_llm_provider(
        self,
        provider: str,
        request: LLMRelayRequest,
        request_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream LLM response from a provider.

        Yields chunks:
            {"type": "token", "content": "...", "index": N}
            {"type": "usage", "usage": {...}, "key_id": "..."}
            {"type": "error", "message": "..."}
        """
        max_retries = self.settings.llm_max_retries
        last_error: Exception | None = None

        for attempt in range(max_retries):
            key = self.api_key_pool.select_key(provider)
            try:
                client = await self._get_client()
                url = f"{key.base_url}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                }
                payload = {
                    "model": request.model,
                    "messages": [{"role": m.role, "content": m.content} for m in request.messages],
                    "max_tokens": request.max_tokens,
                    "temperature": request.temperature,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }

                token_index = 0
                usage_data: dict[str, int] = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code == 429:
                        self.api_key_pool.mark_rate_limited(key.key_id)
                        last_error = ProviderRateLimitedError(f"Provider {provider} rate limited")
                        continue
                    if resp.status_code >= 500:
                        self.api_key_pool.mark_5xx_error(key.key_id)
                        last_error = UpstreamError(f"Provider {provider} returned {resp.status_code}")
                        continue
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise UpstreamError(
                            f"Provider {provider} returned {resp.status_code}: {body.decode()}"
                        )

                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]  # Strip "data: " prefix
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        # Extract token content from delta
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield {"type": "token", "content": content, "index": token_index}
                                token_index += 1

                        # Extract usage (usually in the last chunk)
                        if "usage" in chunk and chunk["usage"]:
                            u = chunk["usage"]
                            usage_data = {
                                "input_tokens": u.get("prompt_tokens", 0),
                                "output_tokens": u.get("completion_tokens", 0),
                                "total_tokens": u.get("total_tokens", 0),
                            }

                self.api_key_pool.mark_success(key.key_id)
                yield {"type": "usage", "usage": usage_data, "key_id": key.key_id}
                return  # Success

            except httpx.TimeoutException:
                self.api_key_pool.mark_timeout(key.key_id)
                last_error = UpstreamTimeoutError(f"Provider {provider} timed out")
                continue
            except httpx.ConnectError as e:
                self.api_key_pool.mark_network_error(key.key_id)
                last_error = UpstreamError(f"Network error: {e}")
                continue
            except (ProviderRateLimitedError, UpstreamError) as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise NoAvailableKeyError(f"No available keys for provider {provider}")

    async def relay_asr(
        self,
        audio_data: bytes,
        user_id: str,
        license_key: str,
        model: str = "whisper-1",
        language: str = "zh",
    ) -> ASRRelayResponse:
        """Relay an ASR (speech-to-text) request to Moka AI Whisper API.

        Args:
            audio_data: Raw audio bytes (mp3/wav/m4a).
            user_id: User ID from JWT.
            license_key: License key from JWT.
            model: ASR model name (default: whisper-1).
            language: Audio language (default: zh).

        Returns:
            ASRRelayResponse with transcribed text.

        Raises:
            ASRQuotaExceededError: If ASR quota is exhausted.
            UpstreamError: If provider returns an error.
        """
        # Check ASR quota
        self.billing_service.check_quota(user_id, license_key, "asr")

        request_id = str(uuid.uuid4())
        start_time = time.time()
        providers_to_try = self._get_provider_order("moka_ai")
        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                key = self.api_key_pool.select_key(provider)
                client = await self._get_client()
                url = f"{key.base_url}/audio/transcriptions"
                headers = {"Authorization": f"Bearer {key.api_key}", "X-Request-ID": request_id}
                files = {"file": ("audio.mp3", audio_data, "audio/mpeg")}
                data = {"model": model, "language": language}

                resp = await client.post(url, headers=headers, files=files, data=data)

                if resp.status_code == 429:
                    self.api_key_pool.mark_rate_limited(key.key_id)
                    last_error = ProviderRateLimitedError(f"Provider {provider} rate limited")
                    continue
                if resp.status_code >= 500:
                    self.api_key_pool.mark_5xx_error(key.key_id)
                    last_error = UpstreamError(f"Provider {provider} returned {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    raise UpstreamError(
                        f"Provider {provider} returned {resp.status_code}: {resp.text}"
                    )

                self.api_key_pool.mark_success(key.key_id)
                result = resp.json()
                text = result.get("text", "")
                duration = result.get("duration", 0.0)

                # Record usage
                duration_ms = int((time.time() - start_time) * 1000)
                await self.billing_service.record_usage(
                    request_id=request_id,
                    user_id=user_id,
                    license_key=license_key,
                    request_type="asr",
                    provider=provider,
                    model=model,
                    key_id=key.key_id,
                    duration_ms=duration_ms,
                )

                lic = self.billing_service._licenses.get(license_key)
                asr_used = lic.quota_used_asr if lic else 0
                asr_limit = lic.quota_limit_asr if lic else 200

                return ASRRelayResponse(
                    text=text,
                    language=language,
                    duration_seconds=float(duration),
                    billing={
                        "count": 1,
                        "monthly_asr_used": asr_used,
                        "monthly_asr_remaining": max(0, asr_limit - asr_used),
                    },
                )

            except httpx.TimeoutException:
                last_error = UpstreamTimeoutError(f"Provider {provider} timed out")
                continue
            except httpx.ConnectError as e:
                last_error = UpstreamError(f"Network error: {e}")
                continue
            except (ProviderRateLimitedError, UpstreamError) as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise NoAvailableKeyError("All providers failed for ASR")

    async def relay_tts(
        self,
        text: str,
        user_id: str,
        license_key: str,
        model: str = "moka-tts",
        voice: str = "zh-female-1",
        speed: float = 1.0,
        response_format: str = "mp3",
    ) -> tuple[bytes, dict[str, Any]]:
        """Relay a TTS (text-to-speech) request to Moka AI TTS API.

        Args:
            text: Text to synthesize (max 500 chars).
            user_id: User ID from JWT.
            license_key: License key from JWT.
            model: TTS model name.
            voice: Voice ID.
            speed: Speech speed (0.5-2.0).
            response_format: Audio format (mp3/wav).

        Returns:
            Tuple of (audio_bytes, billing_info).

        Raises:
            TTSQuotaExceededError: If TTS quota is exhausted.
            UpstreamError: If provider returns an error.
        """
        # Check TTS quota
        self.billing_service.check_quota(user_id, license_key, "tts")

        request_id = str(uuid.uuid4())
        start_time = time.time()
        providers_to_try = self._get_provider_order("moka_ai")
        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                key = self.api_key_pool.select_key(provider)
                client = await self._get_client()
                url = f"{key.base_url}/audio/speech"
                headers = {
                    "Authorization": f"Bearer {key.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                }
                payload = {
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "speed": speed,
                    "response_format": response_format,
                }

                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    self.api_key_pool.mark_rate_limited(key.key_id)
                    last_error = ProviderRateLimitedError(f"Provider {provider} rate limited")
                    continue
                if resp.status_code >= 500:
                    self.api_key_pool.mark_5xx_error(key.key_id)
                    last_error = UpstreamError(f"Provider {provider} returned {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    raise UpstreamError(
                        f"Provider {provider} returned {resp.status_code}: {resp.text}"
                    )

                self.api_key_pool.mark_success(key.key_id)
                audio_bytes = resp.content

                # Record usage
                duration_ms = int((time.time() - start_time) * 1000)
                await self.billing_service.record_usage(
                    request_id=request_id,
                    user_id=user_id,
                    license_key=license_key,
                    request_type="tts",
                    provider=provider,
                    model=model,
                    key_id=key.key_id,
                    duration_ms=duration_ms,
                )

                lic = self.billing_service._licenses.get(license_key)
                tts_used = lic.quota_used_tts if lic else 0
                tts_limit = lic.quota_limit_tts if lic else 200

                billing_info = {
                    "count": 1,
                    "monthly_tts_used": tts_used,
                    "monthly_tts_remaining": max(0, tts_limit - tts_used),
                }
                return audio_bytes, billing_info

            except httpx.TimeoutException:
                last_error = UpstreamTimeoutError(f"Provider {provider} timed out")
                continue
            except httpx.ConnectError as e:
                last_error = UpstreamError(f"Network error: {e}")
                continue
            except (ProviderRateLimitedError, UpstreamError) as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise NoAvailableKeyError("All providers failed for TTS")

    async def relay_ocr(
        self,
        image_data: bytes,
        user_id: str,
        license_key: str,
        task: str = "general",
        model: str = "moka-vision",
    ) -> OCRRelayResponse:
        """Relay an OCR (image text recognition) request to Moka AI Vision API.

        Args:
            image_data: Raw image bytes (jpg/png).
            user_id: User ID from JWT.
            license_key: License key from JWT.
            task: Recognition task (business_card/general).
            model: Vision model name.

        Returns:
            OCRRelayResponse with recognized text and structured data.

        Raises:
            OCRQuotaExceededError: If OCR quota is exhausted.
            UpstreamError: If provider returns an error.
        """
        # Check OCR quota
        self.billing_service.check_quota(user_id, license_key, "ocr")

        request_id = str(uuid.uuid4())
        start_time = time.time()
        providers_to_try = self._get_provider_order("moka_ai")
        last_error: Exception | None = None

        for provider in providers_to_try:
            try:
                key = self.api_key_pool.select_key(provider)
                client = await self._get_client()
                # Use chat completions API with vision model for OCR
                url = f"{key.base_url}/chat/completions"
                headers = {
                    "Authorization": f"Bearer {key.api_key}",
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                }

                import base64

                image_b64 = base64.b64encode(image_data).decode("utf-8")
                system_prompt = (
                    "Extract text from the image. "
                    "If task is 'business_card', return JSON with name, company, title, phone, email."
                    if task == "business_card"
                    else "Extract all text from the image."
                )
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": f"Task: {task}"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                                },
                            ],
                        },
                    ],
                    "max_tokens": 1000,
                    "temperature": 0.1,
                }

                resp = await client.post(url, json=payload, headers=headers)

                if resp.status_code == 429:
                    self.api_key_pool.mark_rate_limited(key.key_id)
                    last_error = ProviderRateLimitedError(f"Provider {provider} rate limited")
                    continue
                if resp.status_code >= 500:
                    self.api_key_pool.mark_5xx_error(key.key_id)
                    last_error = UpstreamError(f"Provider {provider} returned {resp.status_code}")
                    continue
                if resp.status_code >= 400:
                    raise UpstreamError(
                        f"Provider {provider} returned {resp.status_code}: {resp.text}"
                    )

                self.api_key_pool.mark_success(key.key_id)
                result = resp.json()
                raw_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Try to parse structured data for business card
                structured: dict[str, Any] | None = None
                if task == "business_card":
                    try:
                        # Try to extract JSON from the response
                        import re

                        json_match = re.search(r"\{[^}]+\}", raw_text, re.DOTALL)
                        if json_match:
                            structured = json.loads(json_match.group())
                    except (json.JSONDecodeError, AttributeError):
                        pass

                # Record usage
                duration_ms = int((time.time() - start_time) * 1000)
                usage = result.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)
                cost = self.billing_service.calculate_cost(provider, total_tokens)
                await self.billing_service.record_usage(
                    request_id=request_id,
                    user_id=user_id,
                    license_key=license_key,
                    request_type="ocr",
                    provider=provider,
                    model=model,
                    key_id=key.key_id,
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=total_tokens,
                    duration_ms=duration_ms,
                    cost_cny=cost,
                )

                lic = self.billing_service._licenses.get(license_key)
                ocr_used = lic.quota_used_ocr if lic else 0
                ocr_limit = lic.quota_limit_ocr if lic else 100

                return OCRRelayResponse(
                    task=task,
                    structured=structured,
                    raw_text=raw_text,
                    billing={
                        "count": 1,
                        "monthly_ocr_used": ocr_used,
                        "monthly_ocr_remaining": max(0, ocr_limit - ocr_used),
                    },
                )

            except httpx.TimeoutException:
                last_error = UpstreamTimeoutError(f"Provider {provider} timed out")
                continue
            except httpx.ConnectError as e:
                last_error = UpstreamError(f"Network error: {e}")
                continue
            except (ProviderRateLimitedError, UpstreamError) as e:
                last_error = e
                continue

        if last_error:
            raise last_error
        raise NoAvailableKeyError("All providers failed for OCR")


def format_sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a single SSE event string.

    Format: ``event: <event>\\ndata: <json>\\n\\n``
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

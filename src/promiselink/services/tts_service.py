"""TTS (Text-to-Speech) Service — text-to-audio via Moka AI TTS API.

Fallback: if TTS API unavailable, return None (client will display text only).
"""

import asyncio
import time
from dataclasses import dataclass

import httpx

from promiselink.config import Settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.tts_service")

MAX_TEXT_LENGTH = 4096


@dataclass
class TTSResult:
    """Result of TTS synthesis."""

    audio_bytes: bytes | None
    provider: str
    duration_ms: int | None


class TTSService:
    """Async TTS service using Moka AI TTS API (OpenAI-compatible).

    Features:
        - httpx async client with retry
        - Fallback: returns None audio if API unavailable
        - Text length validation
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.api_key: str = config.llm_api_key
        self.base_url: str = config.llm_base_url.rstrip("/")
        self.timeout: int = config.llm_timeout
        self.max_retries: int = config.llm_max_retries

        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def synthesize(
        self,
        text: str,
        voice: str = "alloy",
    ) -> TTSResult:
        """Synthesize text to audio bytes.

        Args:
            text: Input text to synthesize (max 4096 characters).
            voice: Voice name (default: "alloy").

        Returns:
            TTSResult with audio_bytes, provider, and duration_ms.
            audio_bytes will be None if TTS API is unavailable.

        Raises:
            ValueError: If text exceeds max length.
        """
        if len(text) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Text too long: {len(text)} characters "
                f"(max {MAX_TEXT_LENGTH} characters)"
            )

        if not text.strip():
            return TTSResult(audio_bytes=None, provider="none", duration_ms=None)

        try:
            return await self._synthesize_moka_ai(text, voice)
        except Exception as exc:
            logger.warning("tts_moka_ai_failed", error=str(exc))
            return TTSResult(audio_bytes=None, provider="none", duration_ms=None)

    async def _synthesize_moka_ai(self, text: str, voice: str) -> TTSResult:
        """Synthesize using Moka AI TTS API (OpenAI-compatible: POST /v1/audio/speech)."""
        url = f"{self.base_url}/audio/speech"
        payload = {
            "model": "tts-1",
            "input": text,
            "voice": voice,
            "response_format": "mp3",
        }

        start_time = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                client = self._get_client()
                response = await client.post(url, json=payload)
            except httpx.TimeoutException:
                last_error = RuntimeError(f"Moka AI TTS timeout after {self.timeout}s")
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "tts_timeout_retrying",
                        attempt=attempt + 1,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise last_error
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Moka AI TTS HTTP error: {exc}") from exc

            if response.status_code == 429:
                last_error = RuntimeError("Moka AI TTS rate limited")
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Moka AI TTS API error: HTTP {response.status_code}"
                )

            audio_bytes = response.content
            duration_ms = int((time.monotonic() - start_time) * 1000)

            logger.info(
                "tts_moka_ai_completed",
                audio_size=len(audio_bytes),
                duration_ms=duration_ms,
                attempt=attempt + 1,
            )

            return TTSResult(
                audio_bytes=audio_bytes,
                provider="moka_ai",
                duration_ms=duration_ms,
            )

        raise last_error  # type: ignore[misc]

    async def close(self) -> None:
        """Close the httpx async client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

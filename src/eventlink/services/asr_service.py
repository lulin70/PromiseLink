"""ASR (Automatic Speech Recognition) Service — speech-to-text via Moka AI Whisper API.

Fallback strategy: Moka AI Whisper → local whisper (if available) → return error.
"""

import asyncio
from dataclasses import dataclass

import httpx

from eventlink.config import Settings
from eventlink.core.logging import get_logger

logger = get_logger("eventlink.asr_service")


@dataclass
class ASRResult:
    """Result of ASR transcription."""

    text: str
    confidence: float
    provider: str


class ASRService:
    """Async ASR service using Moka AI Whisper API (OpenAI-compatible).

    Features:
        - httpx async client with retry (same pattern as LLMClient)
        - Fallback to local whisper if available
        - Audio size validation
    """

    def __init__(self, config: Settings) -> None:
        self.config = config
        self.api_key: str = config.llm_api_key
        self.base_url: str = config.llm_base_url.rstrip("/")
        self.timeout: int = config.llm_timeout
        self.max_retries: int = config.llm_max_retries
        self.max_audio_size: int = config.media_max_audio_size_mb * 1024 * 1024

        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client (lazy initialization)."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )
        return self._client

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: str = "audio.mp3",
    ) -> ASRResult:
        """Transcribe audio bytes to text.

        Args:
            audio_bytes: Raw audio file bytes (mp3/wav).
            filename: Original filename for content type detection.

        Returns:
            ASRResult with text, confidence, and provider.

        Raises:
            ValueError: If audio exceeds max size.
            RuntimeError: If all providers fail.
        """
        if len(audio_bytes) > self.max_audio_size:
            raise ValueError(
                f"Audio file too large: {len(audio_bytes)} bytes "
                f"(max {self.max_audio_size} bytes)"
            )

        # Try Moka AI Whisper first
        try:
            return await self._transcribe_moka_ai(audio_bytes, filename)
        except Exception as exc:
            logger.warning("asr_moka_ai_failed", error=str(exc))

        # Fallback: try local whisper
        try:
            return await self._transcribe_local_whisper(audio_bytes, filename)
        except Exception as exc:
            logger.warning("asr_local_whisper_failed", error=str(exc))

        raise RuntimeError("All ASR providers failed")

    async def _transcribe_moka_ai(
        self, audio_bytes: bytes, filename: str
    ) -> ASRResult:
        """Transcribe using Moka AI Whisper API (OpenAI-compatible)."""
        url = f"{self.base_url}/audio/transcriptions"

        files = {"file": (filename, audio_bytes)}
        data = {
            "model": "whisper-1",
            "response_format": "verbose_json",
        }

        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                client = self._get_client()
                response = await client.post(url, files=files, data=data)
            except httpx.TimeoutException:
                last_error = RuntimeError(f"Moka AI ASR timeout after {self.timeout}s")
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        "asr_timeout_retrying",
                        attempt=attempt + 1,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise last_error
            except httpx.HTTPError as exc:
                raise RuntimeError(f"Moka AI ASR HTTP error: {exc}") from exc

            if response.status_code == 429:
                last_error = RuntimeError("Moka AI ASR rate limited")
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                raise last_error

            if response.status_code >= 400:
                raise RuntimeError(
                    f"Moka AI ASR API error: HTTP {response.status_code}"
                )

            result = response.json()
            text = result.get("text", "")
            confidence = 1.0
            # verbose_json may include segments with avg confidence
            segments = result.get("segments", [])
            if segments:
                avg_logprob = sum(
                    s.get("avg_logprob", 0) for s in segments
                ) / len(segments)
                # Convert log probability to approximate confidence [0, 1]
                confidence = min(max(0.0, 1.0 + avg_logprob), 1.0)

            logger.info(
                "asr_moka_ai_completed",
                text_length=len(text),
                confidence=confidence,
                attempt=attempt + 1,
            )

            return ASRResult(
                text=text,
                confidence=round(confidence, 4),
                provider="moka_ai",
            )

        raise last_error  # type: ignore[misc]

    async def _transcribe_local_whisper(
        self, audio_bytes: bytes, filename: str
    ) -> ASRResult:
        """Transcribe using local whisper installation (fallback)."""
        import tempfile
        import os

        try:
            import whisper  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError("Local whisper not available")

        # Write to temp file
        suffix = os.path.splitext(filename)[1] or ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            model = whisper.load_model("base")
            result = model.transcribe(tmp_path)
            text = result.get("text", "")
            segments = result.get("segments", [])
            confidence = 1.0
            if segments:
                avg_logprob = sum(
                    s.get("avg_logprob", 0) for s in segments
                ) / len(segments)
                confidence = min(max(0.0, 1.0 + avg_logprob), 1.0)

            return ASRResult(
                text=text,
                confidence=round(confidence, 4),
                provider="local_whisper",
            )
        finally:
            os.unlink(tmp_path)

    async def close(self) -> None:
        """Close the httpx async client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

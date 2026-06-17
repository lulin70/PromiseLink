"""Tests for TTSService — text-to-audio via Moka AI TTS API."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from promiselink.config import Settings
from promiselink.services.tts_service import MAX_TEXT_LENGTH, TTSService


def _make_config() -> Settings:
    return Settings(
        llm_api_key="test",
        llm_base_url="http://localhost:11434",
        llm_timeout=30,
        llm_max_retries=3,
    )


class TestTTSServiceInit:
    """Test TTSService initialization."""

    def test_init_creates_service_with_config(self):
        """Verify TTSService initializes with Settings."""
        config = _make_config()
        service = TTSService(config)

        assert service.api_key == "test"
        assert service.base_url == "http://localhost:11434"
        assert service.timeout == 30
        assert service.max_retries == 3
        assert service._client is None


class TestGetClient:
    """Test _get_client lazy initialization."""

    def test_get_client_lazy_init(self):
        """Verify _get_client creates client on first call."""
        service = TTSService(_make_config())
        assert service._client is None

        client = service._get_client()

        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        assert service._client is client

    def test_get_client_recreates_after_close(self):
        """Verify _get_client creates new client after close()."""
        service = TTSService(_make_config())
        client1 = service._get_client()
        assert service._client is client1

        # Simulate closed client by setting service._client to None
        # (which is what close() does) and mark old client as closed
        service._client = None

        client2 = service._get_client()
        assert client2 is not client1
        assert service._client is client2


class TestSynthesize:
    """Test synthesize method."""

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_returns_none(self):
        """Verify empty text returns TTSResult(audio_bytes=None, provider='none')."""
        service = TTSService(_make_config())

        result = await service.synthesize("")

        assert result.audio_bytes is None
        assert result.provider == "none"
        assert result.duration_ms is None

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_text_returns_none(self):
        """Verify whitespace-only text returns fallback result."""
        service = TTSService(_make_config())

        result = await service.synthesize("   ")

        assert result.audio_bytes is None
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_synthesize_text_too_long_raises(self):
        """Verify text > MAX_TEXT_LENGTH raises ValueError."""
        service = TTSService(_make_config())
        long_text = "a" * (MAX_TEXT_LENGTH + 1)

        with pytest.raises(ValueError, match="Text too long"):
            await service.synthesize(long_text)

    @pytest.mark.asyncio
    async def test_synthesize_moka_ai_success(self):
        """Mock httpx response, verify successful synthesis."""
        service = TTSService(_make_config())

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"fake_audio_data_mp3"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.is_closed = False

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.synthesize("Hello world")

        assert result.audio_bytes == b"fake_audio_data_mp3"
        assert result.provider == "moka_ai"
        assert result.duration_ms is not None
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_synthesize_moka_ai_timeout_retry(self):
        """Mock TimeoutException, verify retry with backoff."""
        config = Settings(
            llm_api_key="test",
            llm_base_url="http://localhost:11434",
            llm_timeout=30,
            llm_max_retries=2,
        )
        service = TTSService(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"audio_after_retry"

        mock_client = AsyncMock()
        # First call times out, second succeeds
        mock_client.post = AsyncMock(
            side_effect=[httpx.TimeoutException("timeout"), mock_response]
        )
        mock_client.is_closed = False

        with patch.object(service, "_get_client", return_value=mock_client):
            with patch("promiselink.services.tts_service.asyncio.sleep", new_callable=AsyncMock):
                result = await service.synthesize("Hello world")

        assert result.audio_bytes == b"audio_after_retry"
        assert result.provider == "moka_ai"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_synthesize_moka_ai_http_429_retry(self):
        """Mock 429 response, verify retry."""
        config = Settings(
            llm_api_key="test",
            llm_base_url="http://localhost:11434",
            llm_timeout=30,
            llm_max_retries=2,
        )
        service = TTSService(config)

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.content = b"rate limited"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.content = b"audio_after_429"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_429, mock_200])
        mock_client.is_closed = False

        with patch.object(service, "_get_client", return_value=mock_client):
            with patch("promiselink.services.tts_service.asyncio.sleep", new_callable=AsyncMock):
                result = await service.synthesize("Hello world")

        assert result.audio_bytes == b"audio_after_429"
        assert result.provider == "moka_ai"

    @pytest.mark.asyncio
    async def test_synthesize_moka_ai_http_error(self):
        """Mock HTTPError, verify fallback."""
        service = TTSService(_make_config())

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("connection failed")
        )
        mock_client.is_closed = False

        with patch.object(service, "_get_client", return_value=mock_client):
            result = await service.synthesize("Hello world")

        assert result.audio_bytes is None
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_synthesize_moka_ai_retries_exhausted(self):
        """Mock all retries fail, verify raises."""
        config = Settings(
            llm_api_key="test",
            llm_base_url="http://localhost:11434",
            llm_timeout=30,
            llm_max_retries=2,
        )
        service = TTSService(config)

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("timeout")
        )
        mock_client.is_closed = False

        with patch.object(service, "_get_client", return_value=mock_client):
            with patch("promiselink.services.tts_service.asyncio.sleep", new_callable=AsyncMock):
                result = await service.synthesize("Hello world")

        # All retries exhausted → exception caught by synthesize() → fallback
        assert result.audio_bytes is None
        assert result.provider == "none"

    @pytest.mark.asyncio
    async def test_synthesize_exception_returns_fallback(self):
        """Mock general exception in synthesize, verify fallback TTSResult."""
        service = TTSService(_make_config())

        with patch.object(
            service, "_synthesize_moka_ai", side_effect=RuntimeError("unexpected error")
        ):
            result = await service.synthesize("Hello world")

        assert result.audio_bytes is None
        assert result.provider == "none"
        assert result.duration_ms is None


class TestClose:
    """Test close method."""

    @pytest.mark.asyncio
    async def test_close_closes_client(self):
        """Verify close() closes client and sets to None."""
        service = TTSService(_make_config())
        client = service._get_client()
        assert service._client is not None

        await service.close()

        assert service._client is None

    @pytest.mark.asyncio
    async def test_close_when_no_client(self):
        """Verify close() is safe when no client exists."""
        service = TTSService(_make_config())
        assert service._client is None

        # Should not raise
        await service.close()
        assert service._client is None

"""Tests for the relay service (LLM/ASR/TTS/OCR).

Tests cover:
- LLM relay (non-streaming and streaming SSE)
- Provider degradation (Moka AI → OpenAI)
- Error handling (429, 5xx, timeout)
- ASR/TTS/OCR relay
- Quota checking
"""

from __future__ import annotations

import httpx
import pytest

from gateway.core.exceptions import (
    NoAvailableKeyError,
    QuotaExceededError,
    UpstreamError,
)
from gateway.schemas.relay import LLMMessage, LLMRelayRequest
from gateway.services.relay_service import RelayService, format_sse_event
from gateway.tests.conftest import (
    TEST_LICENSE_KEY,
    TEST_USER_ID,
    make_llm_response,
    make_llm_stream_lines,
    make_mock_client,
)

# ── LLM Non-Streaming Tests ──


class TestLLMRelayNonStream:
    """Tests for non-streaming LLM relay."""

    @pytest.mark.asyncio
    async def test_llm_relay_success(self, relay_service: RelayService):
        """Test successful non-streaming LLM relay."""
        mock_client = make_mock_client(json_data=make_llm_response("Hello!", 10, 5))
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
            stream=False,
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        assert result["content"] == "Hello!"
        assert result["usage"]["input_tokens"] == 10
        assert result["usage"]["output_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15
        assert "billing" in result
        assert result["billing"]["monthly_status"] == "green"

    @pytest.mark.asyncio
    async def test_llm_relay_records_usage(self, relay_service: RelayService, billing_service):
        """Test that usage is recorded after LLM relay."""
        mock_client = make_mock_client(json_data=make_llm_response("Response", 20, 10))
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Test")],
        )
        await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        # Check usage was recorded
        records = billing_service._usage_records
        assert len(records) == 1
        assert records[0].request_type == "llm"
        assert records[0].total_tokens == 30
        assert records[0].success is True

    @pytest.mark.asyncio
    async def test_llm_relay_provider_degradation(
        self, relay_service: RelayService, api_key_pool
    ):
        """Test provider degradation: Moka AI fails → OpenAI succeeds."""
        call_count = {"moka": 0, "openai": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "moka.test" in url:
                call_count["moka"] += 1
                return httpx.Response(500, json={"error": "Moka server error"})
            call_count["openai"] += 1
            return httpx.Response(200, json=make_llm_response("OpenAI response", 10, 5))

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        assert result["content"] == "OpenAI response"
        assert call_count["moka"] >= 1
        assert call_count["openai"] >= 1

    @pytest.mark.asyncio
    async def test_llm_relay_429_retries_with_different_key(
        self, relay_service: RelayService, api_key_pool
    ):
        """Test that 429 triggers key cooldown and retry."""
        call_count = {"count": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            call_count["count"] += 1
            if call_count["count"] <= 1:
                return httpx.Response(429, json={"error": "rate limited"})
            return httpx.Response(200, json=make_llm_response("Success after retry", 5, 3))

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        assert result["content"] == "Success after retry"
        assert call_count["count"] >= 2

    @pytest.mark.asyncio
    async def test_llm_relay_all_providers_fail(self, relay_service: RelayService):
        """Test that all providers failing raises NoAvailableKeyError."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        with pytest.raises((UpstreamError, NoAvailableKeyError)):
            await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

    @pytest.mark.asyncio
    async def test_llm_relay_quota_exceeded(
        self, relay_service: RelayService, license_store
    ):
        """Test that quota exceeded raises QuotaExceededError."""
        # Exhaust the token quota
        lic = license_store[TEST_LICENSE_KEY]
        lic.quota_used_tokens = lic.quota_limit_tokens

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        with pytest.raises(QuotaExceededError):
            await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)


# ── LLM Streaming Tests ──


class TestLLMRelayStream:
    """Tests for streaming LLM relay with SSE."""

    @pytest.mark.asyncio
    async def test_llm_stream_success(self, relay_service: RelayService):
        """Test successful streaming LLM relay."""
        stream_lines = make_llm_stream_lines(["Hello", " world"], 10, 5)
        mock_client = make_mock_client(stream_lines=stream_lines)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
            stream=True,
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        events = []
        async for event in result:
            events.append(event)

        # Should have token events + done event
        token_events = [e for e in events if e["event"] == "token"]
        done_events = [e for e in events if e["event"] == "done"]

        assert len(token_events) == 2
        assert token_events[0]["data"]["content"] == "Hello"
        assert token_events[0]["data"]["index"] == 0
        assert token_events[1]["data"]["content"] == " world"
        assert token_events[1]["data"]["index"] == 1
        assert len(done_events) == 1
        assert done_events[0]["data"]["usage"]["total_tokens"] == 15

    @pytest.mark.asyncio
    async def test_llm_stream_provider_degradation(self, relay_service: RelayService):
        """Test streaming with provider degradation."""
        openai_stream = make_llm_stream_lines(["OpenAI", " fallback"], 10, 5)

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "moka.test" in url:
                return httpx.Response(500, json={"error": "Moka error"})
            content = "\n".join(openai_stream)
            return httpx.Response(
                200,
                content=content.encode(),
                headers={"content-type": "text/event-stream"},
            )

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
            stream=True,
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        events = []
        async for event in result:
            events.append(event)

        token_events = [e for e in events if e["event"] == "token"]
        done_events = [e for e in events if e["event"] == "done"]

        assert len(token_events) == 2
        assert token_events[0]["data"]["content"] == "OpenAI"
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_llm_stream_all_fail(self, relay_service: RelayService):
        """Test streaming when all providers fail."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "server error"})

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
            stream=True,
        )
        result = await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        events = []
        async for event in result:
            events.append(event)

        error_events = [e for e in events if e["event"] == "error"]
        assert len(error_events) >= 1
        assert "code" in error_events[0]["data"]


# ── ASR Tests ──


class TestASRRelay:
    """Tests for ASR (speech-to-text) relay."""

    @pytest.mark.asyncio
    async def test_asr_relay_success(self, relay_service: RelayService):
        """Test successful ASR relay."""
        asr_response = {"text": "Hello world", "duration": 5.0}
        mock_client = make_mock_client(json_data=asr_response)
        relay_service._http_client = mock_client

        result = await relay_service.relay_asr(
            audio_data=b"fake audio data",
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
        )

        assert result.text == "Hello world"
        assert result.language == "zh"
        assert result.duration_seconds == 5.0
        assert result.billing["count"] == 1

    @pytest.mark.asyncio
    async def test_asr_relay_records_usage(self, relay_service: RelayService, billing_service):
        """Test that ASR usage is recorded."""
        mock_client = make_mock_client(json_data={"text": "Test", "duration": 3.0})
        relay_service._http_client = mock_client

        await relay_service.relay_asr(
            audio_data=b"audio",
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
        )

        records = [r for r in billing_service._usage_records if r.request_type == "asr"]
        assert len(records) == 1
        assert records[0].success is True

    @pytest.mark.asyncio
    async def test_asr_relay_quota_exceeded(self, relay_service: RelayService, license_store):
        """Test ASR quota exceeded."""
        lic = license_store[TEST_LICENSE_KEY]
        lic.quota_used_asr = lic.quota_limit_asr

        from gateway.core.exceptions import ASRQuotaExceededError

        with pytest.raises(ASRQuotaExceededError):
            await relay_service.relay_asr(
                audio_data=b"audio",
                user_id=TEST_USER_ID,
                license_key=TEST_LICENSE_KEY,
            )


# ── TTS Tests ──


class TestTTSRelay:
    """Tests for TTS (text-to-speech) relay."""

    @pytest.mark.asyncio
    async def test_tts_relay_success(self, relay_service: RelayService):
        """Test successful TTS relay."""
        audio_bytes = b"fake mp3 audio data"
        mock_client = make_mock_client(content_data=audio_bytes)
        relay_service._http_client = mock_client

        audio, billing = await relay_service.relay_tts(
            text="Hello world",
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
        )

        assert audio == audio_bytes
        assert billing["count"] == 1

    @pytest.mark.asyncio
    async def test_tts_relay_quota_exceeded(self, relay_service: RelayService, license_store):
        """Test TTS quota exceeded."""
        lic = license_store[TEST_LICENSE_KEY]
        lic.quota_used_tts = lic.quota_limit_tts

        from gateway.core.exceptions import TTSQuotaExceededError

        with pytest.raises(TTSQuotaExceededError):
            await relay_service.relay_tts(
                text="Hello",
                user_id=TEST_USER_ID,
                license_key=TEST_LICENSE_KEY,
            )


# ── OCR Tests ──


class TestOCRRelay:
    """Tests for OCR (image text recognition) relay."""

    @pytest.mark.asyncio
    async def test_ocr_relay_success(self, relay_service: RelayService):
        """Test successful OCR relay."""
        ocr_response = make_llm_response("张伟\n总经理\n某某公司", 50, 20)
        mock_client = make_mock_client(json_data=ocr_response)
        relay_service._http_client = mock_client

        result = await relay_service.relay_ocr(
            image_data=b"fake image data",
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
        )

        assert "张伟" in result.raw_text
        assert result.task == "general"

    @pytest.mark.asyncio
    async def test_ocr_relay_business_card(self, relay_service: RelayService):
        """Test OCR with business card task."""
        card_text = '{"name": "张伟", "company": "科技公司", "title": "总经理", "phone": "138****1234", "email": "z@e.com"}'
        ocr_response = make_llm_response(card_text, 50, 20)
        mock_client = make_mock_client(json_data=ocr_response)
        relay_service._http_client = mock_client

        result = await relay_service.relay_ocr(
            image_data=b"card image",
            user_id=TEST_USER_ID,
            license_key=TEST_LICENSE_KEY,
            task="business_card",
        )

        assert result.task == "business_card"
        assert result.structured is not None
        assert result.structured["name"] == "张伟"

    @pytest.mark.asyncio
    async def test_ocr_relay_quota_exceeded(self, relay_service: RelayService, license_store):
        """Test OCR quota exceeded."""
        lic = license_store[TEST_LICENSE_KEY]
        lic.quota_used_ocr = lic.quota_limit_ocr

        from gateway.core.exceptions import OCRQuotaExceededError

        with pytest.raises(OCRQuotaExceededError):
            await relay_service.relay_ocr(
                image_data=b"image",
                user_id=TEST_USER_ID,
                license_key=TEST_LICENSE_KEY,
            )


# ── SSE Format Tests ──


class TestSSEFormat:
    """Tests for SSE event formatting."""

    def test_format_sse_event_token(self):
        """Test formatting a token SSE event."""
        event = format_sse_event("token", {"content": "Hello", "index": 0})
        assert event == 'event: token\ndata: {"content": "Hello", "index": 0}\n\n'

    def test_format_sse_event_done(self):
        """Test formatting a done SSE event."""
        event = format_sse_event("done", {"usage": {"total_tokens": 15}})
        assert event.startswith("event: done\n")
        assert '"total_tokens": 15' in event
        assert event.endswith("\n\n")

    def test_format_sse_event_unicode(self):
        """Test SSE event with Unicode content."""
        event = format_sse_event("token", {"content": "你好"})
        assert "你好" in event
        assert event.startswith("event: token\n")


# ── API Key Pool Integration Tests ──


class TestAPIKeyPoolIntegration:
    """Tests for API key pool integration with relay service."""

    @pytest.mark.asyncio
    async def test_key_health_updated_on_success(
        self, relay_service: RelayService, api_key_pool
    ):
        """Test that key health score increases on success."""
        mock_client = make_mock_client(json_data=make_llm_response("OK", 5, 3))
        relay_service._http_client = mock_client

        # Lower the health score first
        key = api_key_pool.get_key("key-moka-1")
        key.health_score = 0.5

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        # Health should have increased
        assert key.health_score > 0.5

    @pytest.mark.asyncio
    async def test_key_health_decreased_on_5xx(
        self, relay_service: RelayService, api_key_pool
    ):
        """Test that key health score decreases on 5xx error."""
        def handler(request: httpx.Request) -> httpx.Response:
            if "moka.test" in str(request.url):
                return httpx.Response(500, json={"error": "fail"})
            return httpx.Response(200, json=make_llm_response("OK", 5, 3))

        mock_client = make_mock_client(handler)
        relay_service._http_client = mock_client

        key = api_key_pool.get_key("key-moka-1")
        original_score = key.health_score

        request = LLMRelayRequest(
            model="moka-chat",
            messages=[LLMMessage(role="user", content="Hi")],
        )
        await relay_service.relay_llm(request, TEST_USER_ID, TEST_LICENSE_KEY)

        # Moka key health should have decreased
        assert key.health_score < original_score
        assert key.consecutive_failures >= 1

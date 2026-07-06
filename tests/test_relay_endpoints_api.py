"""Tests for promiselink.services.relay_endpoints — HTTP relay channels.

Covers the four relay channels (LLM / ASR / TTS / OCR) and the internal
HTTP helpers (_post_with_auth, _post_multipart_with_auth, _stream_llm)
using httpx.MockTransport to stub upstream gateway responses.

This complements test_relay_endpoints.py (which only tests the pure
LLMProvider-protocol methods without HTTP).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from promiselink.core.exceptions import LLMResponseParseError, LLMTimeoutError
from promiselink.services.relay_client import RelayClient
from promiselink.services.relay_models import (
    _RELAY_PREFIX,
    RelayAuthError,
    RelayError,
    RelayUnavailableError,
)

# ── Helpers ──

_GATEWAY = "http://gateway.test"
_LICENSE_ACTIVATE = "/api/v1/pro/license/activate"


def _token_response() -> dict:
    """Valid license-activation response (UnifiedResponse envelope)."""
    return {
        "data": {
            "tokens": {
                "access_token": "refreshed-token",
                "refresh_token": "refreshed-refresh",
                "expires_in": 900,
            }
        }
    }


def _make_client(handler, *, max_retries=3) -> RelayClient:
    """Build a RelayClient whose HTTP calls go through a MockTransport.

    user_token is pre-set so _ensure_token() doesn't trigger activation
    on the first call. The internal httpx.AsyncClient is pre-created with
    the mock transport so _get_client() returns it directly.
    """
    transport = httpx.MockTransport(handler)
    client = RelayClient(
        gateway_url=_GATEWAY,
        license_key="PL-PRO-test-1234-5678",
        user_token="initial-token",
        max_retries=max_retries,
    )
    client._client = httpx.AsyncClient(transport=transport)
    return client


async def _noop_sleep(_delay):
    """asyncio.sleep replacement that does nothing (avoids real delays in retries)."""
    pass


# ═══════════════════════════════════════════════════════════════
# chat_completion — non-streaming (lines 84-98)
# ═══════════════════════════════════════════════════════════════


class TestChatCompletionNonStreaming:
    """chat_completion with stream=False — exercises _post_with_auth + _parse_llm_response."""

    @pytest.mark.asyncio
    async def test_happy_returns_parsed_content(self):
        """Successful LLM relay returns content/model/usage/billing dict."""

        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == f"{_RELAY_PREFIX}/llm"
            body = json.loads(req.content)
            assert body["provider"] == "moka_ai"
            assert body["messages"] == [{"role": "user", "content": "hi"}]
            assert body["stream"] is False
            return httpx.Response(200, json={
                "data": {
                    "content": "hello back",
                    "model": "moka-1",
                    "usage": {"tokens": 5},
                    "billing": {"cost": 0.01},
                }
            })

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result["content"] == "hello back"
        assert result["model"] == "moka-1"
        assert result["usage"] == {"tokens": 5}
        assert result["billing"] == {"cost": 0.01}
        await client.close()

    @pytest.mark.asyncio
    async def test_happy_passes_model_and_params(self):
        """model/max_tokens/temperature are forwarded in the payload."""

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            assert body["model"] == "custom-model"
            assert body["max_tokens"] == 100
            assert body["temperature"] == 0.3
            return httpx.Response(200, json={"data": {"content": "ok"}})

        client = _make_client(handler)
        await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            model="custom-model",
            max_tokens=100,
            temperature=0.3,
        )
        await client.close()

    @pytest.mark.asyncio
    async def test_happy_openai_choices_format(self):
        """OpenAI-style choices[0].message.content is extracted correctly."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "from choices"}}],
                "model": "gpt-4",
            })

        client = _make_client(handler)
        result = await client.chat_completion(messages=[{"role": "user", "content": "x"}])
        assert result["content"] == "from choices"
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_true_returns_stream_generator(self):
        """stream=True returns a dict with 'stream' key (async generator).

        _stream_llm is an async function that returns an async generator,
        so result["stream"] is a coroutine that must be awaited to get
        the actual async generator.
        """

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b'data: {"token": "x"}\n')

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        assert "stream" in result
        # _stream_llm is an async function returning an async generator;
        # await it to get the generator object.
        stream_gen = await result["stream"]
        assert hasattr(stream_gen, "__aiter__")
        await client.close()


# ═══════════════════════════════════════════════════════════════
# _stream_llm — streaming LLM (lines 112-154)
# ═══════════════════════════════════════════════════════════════


class TestStreamLLM:
    """_stream_llm — SSE streaming with 401 refresh and error handling."""

    @pytest.mark.asyncio
    async def test_happy_yields_token_events(self):
        """Normal SSE stream yields token events for each data: line."""

        sse_body = (
            'data: {"token": "hello"}\n'
            'data: {"token": " world"}\n'
            '\n'
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=sse_body.encode("utf-8"),
                headers={"content-type": "text/event-stream"},
            )

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = []
        async for evt in stream_gen:
            events.append(evt)

        assert len(events) == 2
        assert events[0] == {"event": "token", "data": {"token": "hello"}}
        assert events[1] == {"event": "token", "data": {"token": " world"}}
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_skips_non_data_lines(self):
        """Lines not starting with 'data:' are silently skipped."""

        sse_body = (
            ': comment\n'
            'event: ping\n'
            'data: {"token": "ok"}\n'
        )

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_body.encode("utf-8"))

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        assert len(events) == 1
        assert events[0]["data"] == {"token": "ok"}
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_skips_invalid_json_data(self):
        """data: lines with invalid JSON are skipped (JSONDecodeError caught)."""

        sse_body = 'data: {not valid json}\ndata: {"token": "good"}\n'

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=sse_body.encode("utf-8"))

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        # Only the valid JSON line yields an event
        assert len(events) == 1
        assert events[0]["data"] == {"token": "good"}
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_401_refreshes_then_retries(self):
        """First 401 triggers token refresh attempt; second request succeeds.

        Note: refresh_token() only calls the activation endpoint when the
        token is near expiry. With a pre-set user_token, refresh_token()
        returns early (token still valid). The key behavior is that the
        stream retries once after 401 and succeeds.
        """

        call_count = {"relay": 0, "activate": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                call_count["activate"] += 1
                return httpx.Response(200, json=_token_response())
            # Relay LLM endpoint
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "token expired"})
            return httpx.Response(200, content=b'data: {"token": "after-refresh"}\n')

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        # The relay endpoint is called twice: initial 401 + retry 200
        assert call_count["relay"] == 2
        assert len(events) == 1
        assert events[0]["data"] == {"token": "after-refresh"}
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_401_after_retry_yields_error_event(self):
        """If still 401 after refresh, yields an error event with RELAY_AUTH_REFRESHED."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            # Always return 401
            return httpx.Response(401, json={"detail": "still bad"})

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert events[0]["data"]["code"] == "RELAY_AUTH_REFRESHED"
        # Should have retried exactly twice (initial + 1 retry)
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_4xx_error_yields_error_event(self):
        """Non-401 4xx error yields an error event with RELAY_ERROR code."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "bad request"})

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert events[0]["data"]["code"] == "RELAY_ERROR"
        assert events[0]["data"]["status"] == 422
        await client.close()

    @pytest.mark.asyncio
    async def test_stream_5xx_error_yields_error_event(self):
        """5xx error yields an error event."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, content=b"internal error")

        client = _make_client(handler)
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "x"}],
            stream=True,
        )
        stream_gen = await result["stream"]
        events = [evt async for evt in stream_gen]
        assert len(events) == 1
        assert events[0]["event"] == "error"
        assert events[0]["data"]["code"] == "RELAY_ERROR"
        assert events[0]["data"]["status"] == 500
        await client.close()


# ═══════════════════════════════════════════════════════════════
# ASR relay (lines 202-207, via _post_multipart_with_auth)
# ═══════════════════════════════════════════════════════════════


class TestASRRelay:
    """asr — speech-to-text via multipart upload."""

    @pytest.mark.asyncio
    async def test_happy_returns_transcription(self):
        """Successful ASR returns the data dict with text."""

        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == f"{_RELAY_PREFIX}/asr"
            assert req.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(200, json={
                "data": {
                    "text": "你好世界",
                    "language": "zh",
                    "duration_seconds": 3.5,
                    "billing": {"cost": 0.02},
                }
            })

        client = _make_client(handler)
        result = await client.asr(b"fake-audio-bytes", language="zh", filename="audio.mp3")
        assert result["text"] == "你好世界"
        assert result["language"] == "zh"
        assert result["duration_seconds"] == 3.5
        await client.close()

    @pytest.mark.asyncio
    async def test_happy_flat_response(self):
        """Flat response (no data envelope) is returned directly."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"text": "flat result"})

        client = _make_client(handler)
        result = await client.asr(b"audio")
        assert result["text"] == "flat result"
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_then_success(self):
        """401 on ASR triggers token refresh and retries the multipart POST."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"data": {"text": "after refresh"}})

        client = _make_client(handler)
        result = await client.asr(b"audio")
        assert result["text"] == "after refresh"
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self):
        """403 raises RelayAuthError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "forbidden"})

        client = _make_client(handler)
        with pytest.raises(RelayAuthError, match="403"):
            await client.asr(b"audio")
        await client.close()

    @pytest.mark.asyncio
    async def test_4xx_raises_relay_error(self):
        """4xx (non-401/403) raises RelayError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "invalid audio"})

        client = _make_client(handler)
        with pytest.raises(RelayError, match="422"):
            await client.asr(b"audio")
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_relay_error(self):
        """Timeout on multipart POST raises RelayError with RELAY_TIMEOUT."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client(handler)
        with pytest.raises(RelayError, match="timeout"):
            await client.asr(b"audio")
        await client.close()

    @pytest.mark.asyncio
    async def test_network_error_raises_unavailable(self):
        """Network error on multipart POST raises RelayUnavailableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler)
        with pytest.raises(RelayUnavailableError, match="network error"):
            await client.asr(b"audio")
        await client.close()

    @pytest.mark.asyncio
    async def test_invalid_json_raises_parse_error(self):
        """Non-JSON response body raises RelayError with RELAY_PARSE_ERROR."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json at all")

        client = _make_client(handler)
        with pytest.raises(RelayError, match="Invalid JSON"):
            await client.asr(b"audio")
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_retry_network_error_raises_unavailable(self):
        """If the retry after 401-refresh hits a network error, RelayUnavailableError is raised."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            raise httpx.ConnectError("retry failed")

        client = _make_client(handler)
        with pytest.raises(RelayUnavailableError, match="retry failed"):
            await client.asr(b"audio")
        await client.close()


# ═══════════════════════════════════════════════════════════════
# TTS relay (lines 235-282)
# ═══════════════════════════════════════════════════════════════


class TestTTSRelay:
    """tts — text-to-speech, returns raw audio bytes."""

    @pytest.mark.asyncio
    async def test_happy_returns_audio_bytes(self):
        """Successful TTS returns raw audio bytes."""

        audio = b"FAKE-AUDIO-MP3-DATA"

        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == f"{_RELAY_PREFIX}/tts"
            body = json.loads(req.content)
            assert body["text"] == "你好"
            assert body["voice"] == "zh-female-1"
            assert body["response_format"] == "mp3"
            return httpx.Response(200, content=audio)

        client = _make_client(handler)
        result = await client.tts("你好")
        assert result == audio
        await client.close()

    @pytest.mark.asyncio
    async def test_happy_passes_all_params(self):
        """model/voice/speed/response_format are forwarded in the payload."""

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            assert body["model"] == "custom-tts"
            assert body["voice"] == "zh-male-1"
            assert body["speed"] == 1.5
            assert body["response_format"] == "wav"
            return httpx.Response(200, content=b"audio")

        client = _make_client(handler)
        await client.tts("text", model="custom-tts", voice="zh-male-1", speed=1.5, response_format="wav")
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_relay_error(self):
        """Timeout on TTS raises RelayError with RELAY_TIMEOUT code."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client(handler)
        with pytest.raises(RelayError, match="timeout"):
            await client.tts("text")
        await client.close()

    @pytest.mark.asyncio
    async def test_network_error_raises_unavailable(self):
        """Network error on TTS raises RelayUnavailableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler)
        with pytest.raises(RelayUnavailableError, match="network error"):
            await client.tts("text")
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_then_success(self):
        """401 on TTS triggers refresh and retries the POST."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, content=b"audio-after-refresh")

        client = _make_client(handler)
        result = await client.tts("text")
        assert result == b"audio-after-refresh"
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_4xx_raises_relay_error(self):
        """4xx (non-401) on TTS raises RelayError with RELAY_TTS_ERROR."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"detail": "text too long"})

        client = _make_client(handler)
        with pytest.raises(RelayError, match="TTS relay failed"):
            await client.tts("text")
        await client.close()

    @pytest.mark.asyncio
    async def test_401_after_refresh_still_401_raises_auth(self):
        """If TTS still returns 401 after refresh, the 4xx handler raises RelayError."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Request:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            return httpx.Response(401, json={"detail": "still expired"})

        client = _make_client(handler)
        # After refresh, the retry returns 401, which is >= 400 → RelayError
        with pytest.raises(RelayError):
            await client.tts("text")
        assert call_count["relay"] == 2
        await client.close()


# ═══════════════════════════════════════════════════════════════
# OCR relay (lines 309-314, via _post_multipart_with_auth)
# ═══════════════════════════════════════════════════════════════


class TestOCRRelay:
    """ocr — image text recognition via multipart upload."""

    @pytest.mark.asyncio
    async def test_happy_returns_ocr_result(self):
        """Successful OCR returns the data dict with structured/raw_text."""

        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == f"{_RELAY_PREFIX}/ocr"
            assert req.headers["content-type"].startswith("multipart/form-data")
            return httpx.Response(200, json={
                "data": {
                    "task": "general",
                    "structured": {"name": "张三"},
                    "raw_text": "张三 CEO 智源AI",
                    "billing": {"cost": 0.03},
                }
            })

        client = _make_client(handler)
        result = await client.ocr(b"fake-image-bytes", task="general", filename="card.png")
        assert result["task"] == "general"
        assert result["raw_text"] == "张三 CEO 智源AI"
        assert result["structured"]["name"] == "张三"
        await client.close()

    @pytest.mark.asyncio
    async def test_happy_flat_response(self):
        """Flat response (no data envelope) is returned directly."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"raw_text": "flat"})

        client = _make_client(handler)
        result = await client.ocr(b"image")
        assert result["raw_text"] == "flat"
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_then_success(self):
        """401 on OCR triggers refresh and retries."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"data": {"raw_text": "after refresh"}})

        client = _make_client(handler)
        result = await client.ocr(b"image")
        assert result["raw_text"] == "after refresh"
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self):
        """403 on OCR raises RelayAuthError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "forbidden"})

        client = _make_client(handler)
        with pytest.raises(RelayAuthError):
            await client.ocr(b"image")
        await client.close()


# ═══════════════════════════════════════════════════════════════
# _post_with_auth — retry / error logic (lines 433-518)
# ═══════════════════════════════════════════════════════════════


class TestPostWithAuth:
    """_post_with_auth — retry logic, 401 refresh, error handling."""

    @pytest.mark.asyncio
    async def test_401_refresh_then_success(self):
        """First 401 triggers refresh; second attempt succeeds (attempt 0 → 1)."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"data": {"content": "ok"}})

        client = _make_client(handler, max_retries=3)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            result = await client._post_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/llm", {"key": "val"}
            )
        assert result["data"]["content"] == "ok"
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_401_on_second_attempt_raises_auth_error(self):
        """If 401 persists after refresh, RelayAuthError is raised (not retried again)."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            return httpx.Response(401, json={"detail": "still expired"})

        client = _make_client(handler, max_retries=3)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            with pytest.raises(RelayAuthError, match="auth failed"):
                await client._post_with_auth(
                    f"{_GATEWAY}{_RELAY_PREFIX}/llm", {"key": "val"}
                )
        # First attempt (401→refresh→continue), second attempt (401, attempt=1≠0 → auth error)
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self):
        """403 raises RelayAuthError immediately (no refresh)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "forbidden"})

        client = _make_client(handler, max_retries=3)
        with pytest.raises(RelayAuthError, match="403"):
            await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_429_retries_then_succeeds(self):
        """429 rate limit triggers retry with backoff; succeeds on second attempt."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(429, json={"detail": "rate limited"})
            return httpx.Response(200, json={"ok": True})

        client = _make_client(handler, max_retries=3)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            result = await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        assert result == {"ok": True}
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_429_exhausts_retries_raises_rate_limit(self):
        """Persistent 429 exhausts retries and raises RelayError with RELAY_RATE_LIMIT."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"detail": "rate limited"})

        client = _make_client(handler, max_retries=2)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            with pytest.raises(RelayError, match="rate limit"):
                await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_5xx_retries_then_succeeds(self):
        """5xx server error triggers retry; succeeds on second attempt."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(503, json={"detail": "unavailable"})
            return httpx.Response(200, json={"ok": True})

        client = _make_client(handler, max_retries=3)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            result = await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        assert result == {"ok": True}
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_5xx_exhausts_retries_raises_unavailable(self):
        """Persistent 5xx exhausts retries and raises RelayUnavailableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "internal error"})

        client = _make_client(handler, max_retries=2)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            with pytest.raises(RelayUnavailableError, match="server error"):
                await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_4xx_non_auth_raises_relay_error(self):
        """4xx (not 401/403/429) raises RelayError immediately (no retry)."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "validation failed"})

        client = _make_client(handler, max_retries=3)
        with pytest.raises(RelayError, match="422"):
            await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_retries_then_raises_llm_timeout(self):
        """Persistent timeout exhausts retries and raises LLMTimeoutError."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client(handler, max_retries=2)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            with pytest.raises(LLMTimeoutError):
                await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_then_success(self):
        """Timeout on first attempt, success on retry."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                raise httpx.TimeoutException("timed out")
            return httpx.Response(200, json={"ok": True})

        client = _make_client(handler, max_retries=3)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            result = await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        assert result == {"ok": True}
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_network_error_retries_then_raises_unavailable(self):
        """Persistent network error exhausts retries and raises RelayUnavailableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        client = _make_client(handler, max_retries=2)
        with patch("promiselink.services.relay_endpoints.asyncio.sleep", _noop_sleep):
            with pytest.raises(RelayUnavailableError, match="network error"):
                await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_invalid_json_raises_parse_error(self):
        """200 response with non-JSON body raises RelayError with RELAY_PARSE_ERROR."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json {{{")

        client = _make_client(handler, max_retries=3)
        with pytest.raises(RelayError, match="Invalid JSON"):
            await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_on_final_attempt_raises_auth_no_retries(self):
        """401 on the last attempt (after refresh) raises RelayAuthError ('no retries remaining').

        With max_retries=1, the 401 at attempt=0 triggers refresh+continue,
        but the loop ends with no remaining iteration → line 518.
        """

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            return httpx.Response(401, json={"detail": "expired"})

        client = _make_client(handler, max_retries=1)
        with pytest.raises(RelayAuthError, match="no retries remaining"):
            await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        assert call_count["relay"] == 1
        await client.close()

    @pytest.mark.asyncio
    async def test_safe_error_detail_fallback_text(self):
        """safe_error_detail falls back to raw text when body is not JSON."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(400, content=b"plain text error")

        client = _make_client(handler, max_retries=3)
        with pytest.raises(RelayError) as exc_info:
            await client._post_with_auth(f"{_GATEWAY}{_RELAY_PREFIX}/llm", {})
        # The detail should contain the raw text
        assert "plain text error" in exc_info.value.message
        await client.close()


# ═══════════════════════════════════════════════════════════════
# _post_multipart_with_auth — error logic (lines 545-603)
# ═══════════════════════════════════════════════════════════════


class TestPostMultipartWithAuth:
    """_post_multipart_with_auth — used by ASR/OCR, tests 401 refresh and errors."""

    @pytest.mark.asyncio
    async def test_happy_returns_json(self):
        """Successful multipart POST returns parsed JSON."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"result": "ok"}})

        client = _make_client(handler)
        result = await client._post_multipart_with_auth(
            f"{_GATEWAY}{_RELAY_PREFIX}/asr",
            files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
            data={"model": "whisper-1"},
        )
        assert result["data"]["result"] == "ok"
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_then_success(self):
        """401 triggers refresh and retries the multipart POST once."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            return httpx.Response(200, json={"data": {"ok": True}})

        client = _make_client(handler)
        result = await client._post_multipart_with_auth(
            f"{_GATEWAY}{_RELAY_PREFIX}/asr",
            files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
            data={"model": "whisper-1"},
        )
        assert result["data"]["ok"] is True
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_401_after_refresh_still_401_raises_auth(self):
        """If still 401 after refresh, RelayAuthError is raised."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            return httpx.Response(401, json={"detail": "still expired"})

        client = _make_client(handler)
        with pytest.raises(RelayAuthError, match="401"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        assert call_count["relay"] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_403_raises_auth_error(self):
        """403 raises RelayAuthError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"detail": "forbidden"})

        client = _make_client(handler)
        with pytest.raises(RelayAuthError, match="403"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()

    @pytest.mark.asyncio
    async def test_4xx_raises_relay_error(self):
        """4xx (non-401/403) raises RelayError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(422, json={"detail": "bad"})

        client = _make_client(handler)
        with pytest.raises(RelayError, match="422"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()

    @pytest.mark.asyncio
    async def test_timeout_raises_relay_error(self):
        """Timeout raises RelayError with RELAY_TIMEOUT."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client(handler)
        with pytest.raises(RelayError, match="timeout"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()

    @pytest.mark.asyncio
    async def test_network_error_raises_unavailable(self):
        """Network error raises RelayUnavailableError."""

        def handler(req: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        client = _make_client(handler)
        with pytest.raises(RelayUnavailableError, match="network error"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()

    @pytest.mark.asyncio
    async def test_invalid_json_raises_parse_error(self):
        """Non-JSON 200 response raises RelayError with RELAY_PARSE_ERROR."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json")

        client = _make_client(handler)
        with pytest.raises(RelayError, match="Invalid JSON"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()

    @pytest.mark.asyncio
    async def test_401_refresh_retry_network_error_raises_unavailable(self):
        """If retry after 401 hits a network error, RelayUnavailableError is raised."""

        call_count = {"relay": 0}

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == _LICENSE_ACTIVATE:
                return httpx.Response(200, json=_token_response())
            call_count["relay"] += 1
            if call_count["relay"] == 1:
                return httpx.Response(401, json={"detail": "expired"})
            raise httpx.ConnectError("retry network fail")

        client = _make_client(handler)
        with pytest.raises(RelayUnavailableError, match="retry failed"):
            await client._post_multipart_with_auth(
                f"{_GATEWAY}{_RELAY_PREFIX}/asr",
                files={"audio": ("a.mp3", b"bytes", "application/octet-stream")},
                data={},
            )
        await client.close()


# ═══════════════════════════════════════════════════════════════
# LLMProvider Protocol via real HTTP (call / call_json / generate)
# ═══════════════════════════════════════════════════════════════


class TestLLMProviderViaHTTP:
    """LLMProvider Protocol methods exercising the real HTTP path (chat_completion)."""

    @pytest.mark.asyncio
    async def test_call_returns_content(self):
        """call() returns stripped content from the LLM relay."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"content": "  hello  "}})

        client = _make_client(handler)
        result = await client.call("test prompt", system_prompt="you are bot")
        assert result == "hello"
        await client.close()

    @pytest.mark.asyncio
    async def test_call_empty_content_raises_parse_error(self):
        """call() with empty content raises LLMResponseParseError."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"content": ""}})

        client = _make_client(handler)
        with pytest.raises(LLMResponseParseError, match="empty content"):
            await client.call("prompt")
        await client.close()

    @pytest.mark.asyncio
    async def test_call_json_returns_parsed(self):
        """call_json() extracts JSON from the LLM response."""

        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"content": '{"key": "val"}'}})

        client = _make_client(handler)
        result = await client.call_json("extract json")
        assert result == {"key": "val"}
        await client.close()

    @pytest.mark.asyncio
    async def test_generate_returns_short_text(self):
        """generate() returns content with temperature=0.0."""

        def handler(req: httpx.Request) -> httpx.Response:
            body = json.loads(req.content)
            assert body["temperature"] == 0.0
            assert body["max_tokens"] == 10
            return httpx.Response(200, json={"data": {"content": "short"}})

        client = _make_client(handler)
        result = await client.generate("prompt")
        assert result == "short"
        await client.close()

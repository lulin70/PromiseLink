"""Tests for LLM client module.

Tests cover:
- _extract_json() — three-level JSON extraction strategy
- _parse_response() — OpenAI format response parsing
- Exception mapping: Timeout→LLMTimeoutError, 429→LLMRateLimitError, 402→LLMQuotaExceeded
- Retry logic with exponential backoff
- call() and call_json() methods
- generate() uses low temperature
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from promiselink.config import Settings
from promiselink.core.exceptions import (
    LLMError,
    LLMQuotaExceeded,
    LLMRateLimitError,
    LLMResponseParseError,
    LLMTimeoutError,
)
from promiselink.services.llm_client import LLMClient

# ── Fixtures ──


@pytest.fixture
def settings():
    return Settings(
        llm_api_key="test-key",
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com/v1",
        llm_model="deepseek-v4-flash",
        llm_max_tokens=2000,
        llm_temperature=0.3,
        llm_timeout=30,
        llm_max_retries=3,
    )


@pytest.fixture
def llm_client(settings):
    from promiselink.core.redis import cache_service

    cache_service._memory_cache.clear()
    client = LLMClient(settings)
    yield client
    cache_service._memory_cache.clear()


def _make_openai_response(content: str, usage: dict | None = None) -> dict:
    """Build a minimal OpenAI-compatible response dict."""
    return {
        "choices": [
            {
                "message": {"content": content},
                "index": 0,
                "finish_reason": "stop",
            }
        ],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


def _make_httpx_response(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = json.dumps(json_data)
    else:
        resp.json.side_effect = json.JSONDecodeError("", "", 0)
        resp.text = ""
    return resp


def _make_mock_http_client(post_return=None, post_side_effect=None) -> MagicMock:
    """Build a mock httpx.AsyncClient with is_closed=False.

    This is necessary because _get_client() checks `self._client.is_closed`
    and would create a new real client if the mock's is_closed is truthy.
    """
    mock = MagicMock(spec=httpx.AsyncClient)
    mock.is_closed = False
    if post_side_effect is not None:
        mock.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock.post = AsyncMock(return_value=post_return)
    return mock


# ── _extract_json tests ──


class TestExtractJson:
    """Test LLMClient._extract_json() — three-level JSON extraction strategy."""

    def test_extract_json_direct_parse(self):
        """Strategy 1: direct JSON parse of full text."""
        text = '{"name": "Alice", "company": "Acme"}'
        result = LLMClient._extract_json(text)
        assert result == {"name": "Alice", "company": "Acme"}

    def test_extract_json_code_block(self):
        """Strategy 2: extract from ```json...``` code block."""
        text = 'Here is the result:\n```json\n{"name": "Bob", "company": "Beta"}\n```\nDone.'
        result = LLMClient._extract_json(text)
        assert result == {"name": "Bob", "company": "Beta"}

    def test_extract_json_brace_search(self):
        """Strategy 3: find first { ... } brace-delimited object."""
        text = 'The result is {"name": "Charlie", "company": "Gamma"} and more text.'
        result = LLMClient._extract_json(text)
        assert result == {"name": "Charlie", "company": "Gamma"}

    def test_extract_json_failure_raises_error(self):
        """All three strategies fail → LLMResponseParseError."""
        with pytest.raises(LLMResponseParseError):
            LLMClient._extract_json("no json here at all")

    def test_extract_json_code_block_with_extra_whitespace(self):
        """Strategy 2: code block with extra newlines/whitespace."""
        text = '```\njson\n  {"key": "value"}  \n```'
        result = LLMClient._extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_nested_braces(self):
        """Strategy 3: nested braces should still parse correctly."""
        text = 'Result: {"outer": {"inner": 1}, "x": 2}'
        result = LLMClient._extract_json(text)
        assert result == {"outer": {"inner": 1}, "x": 2}

    def test_extract_json_returns_dict_only(self):
        """If the top-level JSON is a list (not dict), it should fall through."""
        text = "[1, 2, 3]"
        with pytest.raises(LLMResponseParseError):
            LLMClient._extract_json(text)


# ── _parse_response tests ──


class TestParseResponse:
    """Test LLMClient._parse_response() — OpenAI format response parsing."""

    def test_parse_response_success(self):
        data = _make_openai_response("Hello world")
        result = LLMClient._parse_response(data)
        assert result == "Hello world"

    def test_parse_response_strips_whitespace(self):
        data = _make_openai_response("  Hello world  ")
        result = LLMClient._parse_response(data)
        assert result == "Hello world"

    def test_parse_response_null_content(self):
        """null content → LLMResponseParseError."""
        data = _make_openai_response(None)
        with pytest.raises(LLMResponseParseError, match="null content"):
            LLMClient._parse_response(data)

    def test_parse_response_missing_choices(self):
        """Missing 'choices' key → LLMResponseParseError."""
        with pytest.raises(LLMResponseParseError, match="Unexpected response structure"):
            LLMClient._parse_response({})

    def test_parse_response_empty_choices(self):
        """Empty choices list → LLMResponseParseError."""
        with pytest.raises(LLMResponseParseError):
            LLMClient._parse_response({"choices": []})

    def test_parse_response_missing_message(self):
        """Missing 'message' in choice → LLMResponseParseError."""
        with pytest.raises(LLMResponseParseError):
            LLMClient._parse_response({"choices": [{}]})


# ── _http_call exception mapping tests ──


class TestHttpExceptionMapping:
    """Test that _http_call maps HTTP errors to correct exception types."""

    async def test_timeout_raises_llm_timeout_error(self, llm_client):
        """httpx.TimeoutException → LLMTimeoutError."""
        mock_client = _make_mock_http_client(post_side_effect=httpx.TimeoutException("timeout"))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMTimeoutError) as exc_info:
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        assert exc_info.value.details["provider"] == "deepseek"
        assert exc_info.value.details["timeout"] == 30

    async def test_rate_limit_raises_llm_rate_limit_error(self, llm_client):
        """HTTP 429 → LLMRateLimitError."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(429))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMRateLimitError) as exc_info:
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        assert exc_info.value.code == "LLM_RATE_LIMIT"

    async def test_quota_exceeded_raises_error(self, llm_client):
        """HTTP 402 → LLMQuotaExceeded."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(402))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMQuotaExceeded) as exc_info:
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        assert exc_info.value.code == "LLM_QUOTA_EXCEEDED"

    async def test_forbidden_raises_quota_exceeded(self, llm_client):
        """HTTP 403 → LLMQuotaExceeded (same as 402)."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(403))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMQuotaExceeded):
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )

    async def test_other_http_error_raises_llm_error(self, llm_client):
        """HTTP 500 → LLMError."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(500))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMError, match="HTTP 500"):
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )

    async def test_http_error_generic(self, llm_client):
        """httpx.HTTPError (non-timeout) → LLMError."""
        mock_client = _make_mock_http_client(post_side_effect=httpx.HTTPError("connection reset"))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMError, match="LLM HTTP error"):
            await llm_client._http_call(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )


# ── call() and call_json() tests ──


class TestCallMethods:
    """Test call() and call_json() methods."""

    async def test_call_success(self, llm_client):
        """call() returns parsed text from successful LLM response."""
        response_data = _make_openai_response("Hello from LLM")
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        result = await llm_client.call("Say hello")
        assert result == "Hello from LLM"

    async def test_call_json_success(self, llm_client):
        """call_json() returns parsed JSON dict from LLM response."""
        json_content = '{"name": "Alice", "company": "Acme"}'
        response_data = _make_openai_response(json_content)
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        result = await llm_client.call_json("Extract person info")
        assert result == {"name": "Alice", "company": "Acme"}

    async def test_call_json_parse_failure(self, llm_client):
        """call_json() raises LLMResponseParseError when JSON extraction fails."""
        response_data = _make_openai_response("This is just plain text, no JSON")
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMResponseParseError):
            await llm_client.call_json("Extract person info")

    async def test_call_uses_default_params(self, llm_client):
        """call() uses default max_tokens and temperature when not overridden."""
        response_data = _make_openai_response("ok")
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        await llm_client.call("test")

        # Verify the payload sent to the API
        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["max_tokens"] == 2000
        assert payload["temperature"] == 0.3

    async def test_call_overrides_params(self, llm_client):
        """call() uses provided max_tokens and temperature overrides."""
        response_data = _make_openai_response("ok")
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        await llm_client.call("test", max_tokens=500, temperature=0.7)

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["max_tokens"] == 500
        assert payload["temperature"] == 0.7


# ── Retry logic tests ──


class TestRetryLogic:
    """Test exponential backoff retry logic."""

    async def test_retry_on_timeout(self, llm_client):
        """Timeout triggers retries; after max_retries, LLMTimeoutError is raised."""
        mock_client = _make_mock_http_client(post_side_effect=httpx.TimeoutException("timeout"))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMTimeoutError):
                await llm_client._call_with_retry(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=100,
                    temperature=0.3,
                )
            # Should have attempted max_retries (3) times
            assert mock_client.post.call_count == 3
            # Sleep called between retries (not after last): 2 calls
            assert mock_sleep.call_count == 2
            # Exponential backoff: 2^0=1s, 2^1=2s for timeout
            mock_sleep.assert_any_call(1)
            mock_sleep.assert_any_call(2)

    async def test_retry_on_rate_limit(self, llm_client):
        """429 triggers retries with exponential backoff; after max_retries, LLMRateLimitError."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(429))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            with pytest.raises(LLMRateLimitError):
                await llm_client._call_with_retry(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=100,
                    temperature=0.3,
                )
            assert mock_client.post.call_count == 3
            assert mock_sleep.call_count == 2
            # Rate limit backoff: 2^(0+1)=2s, 2^(1+1)=4s
            mock_sleep.assert_any_call(2)
            mock_sleep.assert_any_call(4)

    async def test_no_retry_on_quota_exceeded(self, llm_client):
        """LLMQuotaExceeded is not retryable — raised immediately."""
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(402))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMQuotaExceeded):
            await llm_client._call_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        # Should only attempt once — no retry
        assert mock_client.post.call_count == 1

    async def test_retry_succeeds_on_second_attempt(self, llm_client):
        """Retry succeeds on the second attempt after initial timeout."""
        response_data = _make_openai_response("Success on retry")
        mock_client = _make_mock_http_client()

        # First call times out, second succeeds
        mock_client.post = AsyncMock(
            side_effect=[
                httpx.TimeoutException("timeout"),
                _make_httpx_response(200, json_data=response_data),
            ]
        )
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
            result = await llm_client._call_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        assert result == "Success on retry"
        assert mock_client.post.call_count == 2


class TestEmptyContentRetry:
    """2026-08-16 fix: reasoning models can exhaust max_tokens on
    reasoning_content, leaving content="". Must retry with a doubled
    token budget instead of caching/returning the empty response."""

    @staticmethod
    def _reasoning_response(finish_reason: str = "length") -> dict:
        """Build a response where reasoning consumed the entire budget."""
        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "thinking... (truncated)",
                    },
                    "index": 0,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 4000,
                "total_tokens": 5000,
            },
        }

    async def test_parse_response_empty_content_raises(self, llm_client):
        """Empty content raises LLMEmptyContentError (not silent '')."""
        from promiselink.core.exceptions import LLMEmptyContentError

        with pytest.raises(LLMEmptyContentError):
            llm_client._parse_response(self._reasoning_response())

    async def test_empty_content_retries_with_doubled_max_tokens(self, llm_client):
        """First attempt (4000 tokens) returns empty content; retry must
        double the budget and succeed once content is produced."""
        from promiselink.core.exceptions import LLMEmptyContentError

        empty = _make_httpx_response(200, json_data=self._reasoning_response())
        ok = _make_httpx_response(200, json_data=_make_openai_response('{"persons": []}'))
        mock_client = _make_mock_http_client()
        mock_client.post = AsyncMock(side_effect=[empty, ok])
        llm_client._get_client = AsyncMock(return_value=mock_client)

        result = await llm_client._call_with_retry(
            messages=[{"role": "user", "content": "extract"}],
            max_tokens=4000,
            temperature=0.3,
        )
        assert result == '{"persons": []}'
        assert mock_client.post.call_count == 2
        # Second call must carry doubled max_tokens
        second_payload = mock_client.post.call_args_list[1].kwargs.get("json") or mock_client.post.call_args_list[1][
            1
        ].get("json")
        assert second_payload["max_tokens"] == 8000

    async def test_empty_content_all_attempts_fail_raises(self, llm_client):
        """If every retry still returns empty content, raise after max_retries."""
        from promiselink.core.exceptions import LLMEmptyContentError

        mock_client = _make_mock_http_client(
            post_return=_make_httpx_response(200, json_data=self._reasoning_response())
        )
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with pytest.raises(LLMEmptyContentError):
            await llm_client._call_with_retry(
                messages=[{"role": "user", "content": "extract"}],
                max_tokens=4000,
                temperature=0.3,
            )
        assert mock_client.post.call_count == 3  # llm_max_retries from fixture

    async def test_empty_content_never_cached(self, llm_client):
        """Empty responses must not poison the LLM response cache."""
        from promiselink.core.redis import cache_service

        response_data = self._reasoning_response()
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        from promiselink.core.exceptions import LLMEmptyContentError

        with pytest.raises(LLMEmptyContentError):
            await llm_client._call_with_retry(
                messages=[{"role": "user", "content": "extract"}],
                max_tokens=4000,
                temperature=0.3,
            )
        # Memory cache must contain no entry for this prompt
        assert not cache_service._memory_cache

    async def test_poisoned_cache_entry_is_purged(self, llm_client):
        """A pre-fix cached empty entry is deleted and treated as a miss."""
        from promiselink.core.redis import cache_service

        messages = [{"role": "user", "content": "extract"}]
        messages_str = json.dumps(messages, sort_keys=True)
        cache_key = await cache_service.llm_cache_key(messages_str, llm_client.model)
        # Simulate poisoned entry written by the old code path
        await cache_service.set(cache_key, {"content": "", "usage": {}}, ttl=86400)

        ok = _make_httpx_response(
            200, json_data=_make_openai_response("real answer")
        )
        mock_client = _make_mock_http_client(post_return=ok)
        llm_client._get_client = AsyncMock(return_value=mock_client)

        result = await llm_client._call_with_retry(
            messages=messages, max_tokens=100, temperature=0.3
        )
        assert result == "real answer"
        assert mock_client.post.call_count == 1  # cache was treated as miss


class TestTieredRetry:
    """Tiered retry (Pipeline_Reliability_2026-08-16 §4): flash for early
    attempts, escalate to fallback model (e.g. deepseek-v4-pro) from
    fallback_after_attempts onward with a larger timeout."""

    @pytest.fixture
    def tiered_client(self, settings):
        settings.llm_fallback_model = "deepseek-v4-pro"
        settings.llm_fallback_after_attempts = 3
        settings.llm_fallback_timeout = 120
        from promiselink.core.redis import cache_service

        cache_service._memory_cache.clear()
        client = LLMClient(settings)
        yield client
        cache_service._memory_cache.clear()

    async def test_escalates_model_on_third_attempt(self, tiered_client):
        """Attempts 1-2 use primary model; attempt 3+ switch to fallback."""
        responses = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _make_httpx_response(200, json_data=_make_openai_response("ok")),
        ]
        mock_client = _make_mock_http_client()
        mock_client.post = AsyncMock(side_effect=responses)
        tiered_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
            result = await tiered_client._call_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        assert result == "ok"
        models_used = [
            (c.kwargs.get("json") or c[1].get("json"))["model"]
            for c in mock_client.post.call_args_list
        ]
        assert models_used == [
            "deepseek-v4-flash",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
        ]

    async def test_fallback_uses_fallback_timeout(self, tiered_client):
        """Fallback attempts carry the larger fallback timeout."""
        responses = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _make_httpx_response(200, json_data=_make_openai_response("ok")),
        ]
        mock_client = _make_mock_http_client()
        mock_client.post = AsyncMock(side_effect=responses)
        tiered_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
            await tiered_client._call_with_retry(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=100,
                temperature=0.3,
            )
        timeouts = [
            c.kwargs.get("timeout") for c in mock_client.post.call_args_list
        ]
        # Primary attempts use client default (60 via Settings fixture=30);
        # fallback attempt uses fallback_timeout=120
        assert timeouts[2] is not None and timeouts[2].read == 120

    async def test_no_escalation_when_fallback_not_configured(self, llm_client):
        """Without a fallback model, all attempts stay on the primary model."""
        # Force-disable fallback: the developer .env may configure
        # LLM_FALLBACK_MODEL globally, which must not leak into this test.
        llm_client.fallback_model = ""
        assert llm_client.fallback_model == ""
        responses = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
        ]
        mock_client = _make_mock_http_client()
        mock_client.post = AsyncMock(side_effect=responses)
        llm_client._get_client = AsyncMock(return_value=mock_client)

        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(LLMTimeoutError):
                await llm_client._call_with_retry(
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=100,
                    temperature=0.3,
                )
        models_used = [
            (c.kwargs.get("json") or c[1].get("json"))["model"]
            for c in mock_client.post.call_args_list
        ]
        assert models_used == ["deepseek-v4-flash"] * 3

    async def test_fallback_success_cached_under_primary_key(self, tiered_client):
        """A fallback success is cached under the primary-model key, so the
        next identical prompt hits cache without re-escalating."""
        from promiselink.core.redis import cache_service

        responses = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _make_httpx_response(200, json_data=_make_openai_response("cached-ok")),
        ]
        mock_client = _make_mock_http_client()
        mock_client.post = AsyncMock(side_effect=responses)
        tiered_client._get_client = AsyncMock(return_value=mock_client)

        messages = [{"role": "user", "content": "unique-prompt-x"}]
        with patch("promiselink.services.llm_client.asyncio.sleep", new_callable=AsyncMock):
            r1 = await tiered_client._call_with_retry(
                messages=messages, max_tokens=100, temperature=0.3
            )
            r2 = await tiered_client._call_with_retry(
                messages=messages, max_tokens=100, temperature=0.3
            )
        assert r1 == r2 == "cached-ok"
        assert mock_client.post.call_count == 3  # second call: pure cache hit


# ── generate() tests ──


class TestGenerate:
    """Test generate() method uses low temperature."""

    async def test_generate_uses_low_temperature(self, llm_client):
        """generate() always uses temperature=0.0 for deterministic output."""
        response_data = _make_openai_response("0.95")
        mock_client = _make_mock_http_client(post_return=_make_httpx_response(200, json_data=response_data))
        llm_client._get_client = AsyncMock(return_value=mock_client)

        result = await llm_client.generate("Rate confidence", max_tokens=10)
        assert result == "0.95"

        call_args = mock_client.post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["temperature"] == 0.0
        assert payload["max_tokens"] == 10


# ── Client lifecycle tests ──


class TestClientLifecycle:
    """Test client initialization and cleanup."""

    def test_init_stores_config(self, settings, llm_client):
        assert llm_client.api_key == "test-key"
        assert llm_client.base_url == "https://api.deepseek.com/v1"
        assert llm_client.model == "deepseek-v4-flash"
        assert llm_client.default_max_tokens == 2000
        assert llm_client.default_temperature == 0.3
        assert llm_client.timeout == 30
        assert llm_client.max_retries == 3

    def test_base_url_strips_trailing_slash(self):
        settings = Settings(
            llm_api_key="k",
            llm_base_url="https://api.example.com/v1/",
        )
        client = LLMClient(settings)
        assert client.base_url == "https://api.example.com/v1"

    async def test_close_is_noop(self, llm_client):
        """close() is a no-op with shared client — does not close or clear _client."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.is_closed = False
        llm_client._client = mock_client

        await llm_client.close()
        # close() is now a no-op: should NOT call aclose or clear _client
        mock_client.aclose.assert_not_awaited()
        assert llm_client._client is mock_client

    async def test_close_idempotent(self, llm_client):
        """close() is safe to call multiple times — it's a no-op."""
        await llm_client.close()  # Should not raise
        await llm_client.close()  # Still should not raise

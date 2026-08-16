"""LLM client module for PromiseLink.

Uses DeepSeek API (OpenAI-compatible interface) via httpx async calls.
Supports retry with exponential backoff, timeout, and graceful degradation.
"""

import asyncio
import json
import time
from typing import Any, cast

import httpx

from promiselink.config import Settings
from promiselink.core.exceptions import (
    LLMEmptyContentError,
    LLMError,
    LLMQuotaExceeded,
    LLMRateLimitError,
    LLMResponseParseError,
    LLMTimeoutError,
)
from promiselink.core.logging import get_logger
from promiselink.core.text_utils import extract_json_from_text, sanitize_llm_input

logger = get_logger("promiselink.llm_client")

# ── Shared httpx client for connection reuse ──
_shared_client: httpx.AsyncClient | None = None


async def get_shared_client() -> httpx.AsyncClient:
    """Get or create the module-level shared httpx.AsyncClient.

    Reuses a single connection pool across all LLMClient instances,
    reducing TCP handshake overhead and improving throughput.

    Returns:
        The shared httpx.AsyncClient instance.
    """
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.AsyncClient(timeout=120.0)
        logger.debug("shared_httpx_client_created")
    return _shared_client


async def close_shared_client() -> None:
    """Close the shared httpx client. Call on app shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        await _shared_client.aclose()
        _shared_client = None
        logger.info("shared_httpx_client_closed")


class LLMClient:
    """Async LLM client for DeepSeek (OpenAI-compatible) API calls.

    Features:
        - Exponential backoff retry (manual, no tenacity)
        - Configurable timeout
        - Structured logging per call
        - JSON response extraction with fallback strategies
    """

    def __init__(self, config: Settings) -> None:
        """Initialize with settings.

        Args:
            config: Application settings containing LLM configuration.
        """
        self.config = config
        self.api_key: str = config.llm_api_key
        self.base_url: str = config.llm_base_url.rstrip("/")
        self.model: str = config.llm_model
        self.default_max_tokens: int = config.llm_max_tokens
        self.default_temperature: float = config.llm_temperature
        self.timeout: int = config.llm_timeout
        self.max_retries: int = config.llm_max_retries
        self.provider: str = config.llm_provider
        # Tiered retry config (Pipeline_Reliability_2026-08-16 §4)
        self.fallback_model: str = config.llm_fallback_model
        self.fallback_after_attempts: int = config.llm_fallback_after_attempts
        self.fallback_timeout: int = config.llm_fallback_timeout

        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get the shared httpx async client for connection reuse.

        Returns:
            The shared httpx.AsyncClient instance with auth headers set per-request.
        """
        return await get_shared_client()

    async def _http_call(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        model: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Execute the HTTP call to the LLM API.

        Args:
            messages: Chat messages in OpenAI format.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.
            model: Override model for this call (tiered retry escalation).
            timeout: Override request timeout in seconds for this call.

        Returns:
            Parsed JSON response from the API.

        Raises:
            LLMTimeoutError: On request timeout.
            LLMRateLimitError: On HTTP 429.
            LLMQuotaExceeded: On HTTP 402/403.
            LLMError: On other HTTP errors.
        """
        effective_model = model or self.model
        effective_timeout = timeout or self.timeout
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            client = await self._get_client()
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(effective_timeout, connect=10.0),
            )
        except httpx.TimeoutException:
            raise LLMTimeoutError(provider=self.provider, timeout=effective_timeout)
        except httpx.HTTPError as exc:
            error_detail = str(exc) or f"{type(exc).__name__} (no detail)"
            raise LLMError(
                message=f"LLM HTTP error: {error_detail}",
                code="LLM_HTTP_ERROR",
                details={"provider": self.provider, "error_type": type(exc).__name__, "error": error_detail},
            )

        # Map HTTP status codes to exceptions
        if response.status_code == 429:
            raise LLMRateLimitError(provider=self.provider)
        if response.status_code in (402, 403):
            raise LLMQuotaExceeded(provider=self.provider)
        if response.status_code >= 400:
            raise LLMError(
                message=f"LLM API error: HTTP {response.status_code}",
                code="LLM_API_ERROR",
                details={
                    "provider": self.provider,
                    "status_code": response.status_code,
                    "body": response.text[:500],
                },
            )

        try:
            result: dict[str, Any] = response.json()
            return result
        except json.JSONDecodeError as exc:
            raise LLMResponseParseError(parse_error=f"Invalid JSON in API response: {exc}")

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> str:
        """Extract text content from the OpenAI-compatible response.

        Args:
            data: Parsed JSON response from the API.

        Returns:
            The generated text content.

        Raises:
            LLMResponseParseError: If response structure is unexpected.
        """
        try:
            message = data["choices"][0]["message"]
            content: str = message["content"]
            if content is None:
                raise LLMResponseParseError(parse_error="LLM returned null content")
            if not content.strip():
                # 2026-08-16 fix: reasoning models (deepseek-v4-flash) can
                # exhaust max_tokens on reasoning_content, leaving content="".
                # Raise a retryable error instead of caching an empty response.
                finish_reason = data["choices"][0].get("finish_reason")
                raise LLMEmptyContentError(finish_reason=finish_reason)
            return content.strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseParseError(parse_error=f"Unexpected response structure: {exc}")

    async def _call_with_retry(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Call LLM with exponential backoff retry logic.

        Retryable errors: LLMTimeoutError, LLMRateLimitError.
        Non-retryable errors are raised immediately.

        Args:
            messages: Chat messages in OpenAI format.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            The generated text content.
        """
        # Check cache
        from promiselink.core.redis import cache_service

        messages_str = json.dumps(messages, sort_keys=True)
        cache_key = await cache_service.llm_cache_key(messages_str, self.model)
        cached = await cache_service.get(cache_key)
        if cached and cached.get("content"):
            logger.debug("llm_cache_hit", key=cache_key)
            return cast(str, cached["content"])
        if cached and not cached.get("content"):
            # 2026-08-16 fix: purged poisoned empty-content cache entries
            # (written by the pre-fix code path) instead of returning them.
            logger.warning("llm_cache_poisoned_empty", key=cache_key)
            await cache_service.delete(cache_key)

        start_time = time.monotonic()
        last_error: Exception | None = None
        current_max_tokens = max_tokens

        for attempt in range(self.max_retries):
            # Tiered retry (Pipeline_Reliability_2026-08-16 §4): escalate to
            # the fallback model from fallback_after_attempts onward.
            use_fallback = bool(
                self.fallback_model
                and attempt + 1 >= self.fallback_after_attempts
            )
            attempt_model = self.fallback_model if use_fallback else None
            attempt_timeout = self.fallback_timeout if use_fallback else None

            try:
                response_data = await self._http_call(
                    messages,
                    current_max_tokens,
                    temperature,
                    model=attempt_model,
                    timeout=attempt_timeout,
                )
                result = self._parse_response(response_data)

                latency_ms = int((time.monotonic() - start_time) * 1000)
                usage = response_data.get("usage", {})
                tokens_used = usage.get("total_tokens", 0)

                logger.info(
                    "llm_call_completed",
                    provider=self.provider,
                    model=attempt_model or self.model,
                    tier="fallback" if use_fallback else "primary",
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    attempt=attempt + 1,
                )

                # Cache the response (never cache empty content — defensive)
                if result.strip():
                    await cache_service.set(cache_key, {"content": result, "usage": usage}, ttl=86400)

                return result

            except LLMTimeoutError:
                last_error = LLMTimeoutError(provider=self.provider, timeout=self.timeout)
                if attempt < self.max_retries - 1:
                    wait = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        "llm_timeout_retrying",
                        provider=self.provider,
                        attempt=attempt + 1,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

            except LLMRateLimitError:
                last_error = LLMRateLimitError(provider=self.provider)
                if attempt < self.max_retries - 1:
                    wait = 2 ** (attempt + 1)  # 2s, 4s, 8s
                    logger.warning(
                        "llm_rate_limited_retrying",
                        provider=self.provider,
                        attempt=attempt + 1,
                        wait_seconds=wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

            except LLMEmptyContentError as exc:
                # 2026-08-16 fix: reasoning model exhausted max_tokens on
                # reasoning_content → empty content. Retry with a doubled
                # token budget so reasoning can finish and content can be
                # produced. Cap at 8192 (DeepSeek hard limit).
                last_error = exc
                if attempt < self.max_retries - 1:
                    current_max_tokens = min(current_max_tokens * 2, 8192)
                    logger.warning(
                        "llm_empty_content_retrying",
                        provider=self.provider,
                        attempt=attempt + 1,
                        max_tokens=current_max_tokens,
                        finish_reason=exc.details.get("finish_reason"),
                    )
                    continue
                raise

            except LLMError as exc:
                # Retry generic LLM errors (e.g., HTTP connection errors)
                # but NOT quota errors which are permanent
                if isinstance(exc, LLMQuotaExceeded):
                    raise
                last_error = exc
                if attempt < self.max_retries - 1:
                    wait = 2**attempt  # 1s, 2s, 4s
                    logger.warning(
                        "llm_error_retrying",
                        provider=self.provider,
                        attempt=attempt + 1,
                        wait_seconds=wait,
                        error=str(exc)[:100],
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        # Should not reach here, but just in case
        raise last_error  # type: ignore[misc]

    async def call(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Call LLM with a simple text prompt.

        Args:
            prompt: The user prompt text.
            max_tokens: Override default max tokens. Uses config default if None.
            temperature: Override default temperature. Uses config default if None.

        Returns:
            The generated text response.
        """
        prompt = sanitize_llm_input(prompt)
        messages = [{"role": "user", "content": prompt}]
        return await self._call_with_retry(
            messages=messages,
            max_tokens=max_tokens or self.default_max_tokens,
            temperature=temperature if temperature is not None else self.default_temperature,
        )

    async def call_json(
        self,
        prompt: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Call LLM and parse response as JSON.

        Handles responses wrapped in ```json...``` code blocks and
        extracts the first JSON object from freeform text.

        Args:
            prompt: The user prompt text.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            Parsed JSON object from the LLM response.

        Raises:
            LLMResponseParseError: If JSON cannot be extracted from the response.
        """
        text = await self.call(prompt, max_tokens=max_tokens, temperature=temperature)
        return self._extract_json(text)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Extract a JSON object from LLM response text.

        Delegates to the shared ``extract_json_from_text`` utility which
        tries three strategies in order:
            1. Direct JSON parse of the full text.
            2. Extract from ```json...``` code block.
            3. Find the first ``{`` ... ``}`` brace-delimited object.

        Args:
            text: Raw LLM response text.

        Returns:
            Parsed JSON dict.

        Raises:
            LLMResponseParseError: If no valid JSON can be extracted.
        """
        try:
            return extract_json_from_text(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseParseError(parse_error=str(exc))

    async def generate(self, prompt: str, max_tokens: int = 10) -> str:
        """Short generation for simple tasks (e.g., confidence score).

        Uses low temperature (0.0) for deterministic output.

        Args:
            prompt: The user prompt text.
            max_tokens: Maximum tokens, defaults to 10 for short outputs.

        Returns:
            The generated short text response.
        """
        prompt = sanitize_llm_input(prompt)
        messages = [{"role": "user", "content": prompt}]
        return await self._call_with_retry(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
        )

    async def close(self) -> None:
        """Close the httpx async client.

        Note: With shared client, this is a no-op. Use close_shared_client()
        at app shutdown instead.
        """
        pass

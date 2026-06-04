"""LLM client module for EventLink.

Uses Moka AI API (OpenAI-compatible interface) via httpx async calls.
Supports retry with exponential backoff, timeout, and graceful degradation.
"""

import asyncio
import json
import re
import time
from typing import Any

import httpx

from eventlink.config import Settings
from eventlink.core.exceptions import (
    LLMError,
    LLMQuotaExceeded,
    LLMRateLimitError,
    LLMResponseParseError,
    LLMTimeoutError,
)
from eventlink.core.logging import get_logger

logger = get_logger("eventlink.llm_client")


class LLMClient:
    """Async LLM client for Moka AI (OpenAI-compatible) API calls.

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

        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create the httpx async client (lazy initialization).

        Returns:
            The httpx.AsyncClient instance.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _http_call(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Execute the HTTP call to the LLM API.

        Args:
            messages: Chat messages in OpenAI format.
            max_tokens: Maximum tokens to generate.
            temperature: Sampling temperature.

        Returns:
            Parsed JSON response from the API.

        Raises:
            LLMTimeoutError: On request timeout.
            LLMRateLimitError: On HTTP 429.
            LLMQuotaExceeded: On HTTP 402/403.
            LLMError: On other HTTP errors.
        """
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            client = self._get_client()
            response = await client.post(url, json=payload)
        except httpx.TimeoutException:
            raise LLMTimeoutError(provider=self.provider, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise LLMError(
                message=f"LLM HTTP error: {exc}",
                code="LLM_HTTP_ERROR",
                details={"provider": self.provider, "error": str(exc)},
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
            raise LLMResponseParseError(
                parse_error=f"Invalid JSON in API response: {exc}"
            )

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
            content: str = data["choices"][0]["message"]["content"]
            if content is None:
                raise LLMResponseParseError(parse_error="LLM returned null content")
            return content.strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseParseError(
                parse_error=f"Unexpected response structure: {exc}"
            )

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
        from eventlink.core.redis import cache_service
        messages_str = json.dumps(messages, sort_keys=True)
        cache_key = await cache_service.llm_cache_key(messages_str, self.model)
        cached = await cache_service.get(cache_key)
        if cached:
            logger.debug("llm_cache_hit", key=cache_key)
            return cached["content"]

        start_time = time.monotonic()
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response_data = await self._http_call(messages, max_tokens, temperature)
                result = self._parse_response(response_data)

                latency_ms = int((time.monotonic() - start_time) * 1000)
                usage = response_data.get("usage", {})
                tokens_used = usage.get("total_tokens", 0)

                logger.info(
                    "llm_call_completed",
                    provider=self.provider,
                    model=self.model,
                    tokens_used=tokens_used,
                    latency_ms=latency_ms,
                    attempt=attempt + 1,
                )

                # Cache the response
                await cache_service.set(cache_key, {"content": result, "usage": usage}, ttl=86400)

                return result

            except LLMTimeoutError:
                last_error = LLMTimeoutError(provider=self.provider, timeout=self.timeout)
                if attempt < self.max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
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

        Tries three strategies in order:
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
        # Strategy 1: Direct parse
        try:
            result = json.loads(text)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

        # Strategy 2: Extract from ```json...``` code block
        json_block_pattern = re.compile(r"```json\s*\n?(.*?)\n?\s*```", re.DOTALL)
        match = json_block_pattern.search(text)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find first { ... } brace-delimited object
        brace_pattern = re.compile(r"\{.*\}", re.DOTALL)
        match = brace_pattern.search(text)
        if match:
            try:
                result = json.loads(match.group(0))
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

        raise LLMResponseParseError(
            parse_error=f"Could not extract JSON from response: {text[:200]}"
        )

    async def generate(self, prompt: str, max_tokens: int = 10) -> str:
        """Short generation for simple tasks (e.g., confidence score).

        Uses low temperature (0.0) for deterministic output.

        Args:
            prompt: The user prompt text.
            max_tokens: Maximum tokens, defaults to 10 for short outputs.

        Returns:
            The generated short text response.
        """
        messages = [{"role": "user", "content": prompt}]
        return await self._call_with_retry(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.0,
        )

    async def close(self) -> None:
        """Close the httpx async client."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

"""LLM Provider Protocol — decoupled interface for LLM API calls.

EventLink uses a Protocol-based interface for LLM interactions.
This decouples business logic from any specific LLM backend.

Architecture:
    EventLink 业务层 (Pipeline/NLU/NLG/EntityExtraction)
         ↕ LLMProvider Protocol (4 methods)
         ↕ Implementation
    LLMClient (Moka AI / OpenAI-compatible)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol interface for LLM API calls.

    All LLM-dependent services should depend on this Protocol
    rather than the concrete LLMClient class, enabling:
    - Mock injection for testing
    - Alternative LLM backend support
    - Type-safe dependency injection
    """

    async def call(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Send a prompt and return the raw text response.

        Args:
            prompt: User prompt text.
            system_prompt: Optional system prompt.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            Raw text response from the LLM.
        """
        ...

    async def call_json(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Send a prompt and parse the response as JSON.

        Args:
            prompt: User prompt text.
            system_prompt: Optional system prompt.
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            Parsed JSON dict from the LLM response.

        Raises:
            LLMResponseParseError: If response cannot be parsed as JSON.
        """
        ...

    async def generate(self, prompt: str, max_tokens: int = 10) -> str:
        """Generate a short text response (convenience method).

        Args:
            prompt: User prompt text.
            max_tokens: Maximum tokens to generate (default: 10).

        Returns:
            Generated text.
        """
        ...

    async def close(self) -> None:
        """Close the underlying HTTP client and release resources."""
        ...

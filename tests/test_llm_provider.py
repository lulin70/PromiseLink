"""Tests for promiselink.services.llm_provider — Protocol contract validation."""

from __future__ import annotations

from typing import Any

import pytest

from promiselink.services.llm_provider import LLMProvider


class _FullProvider:
    """完整实现 LLMProvider Protocol (4 方法)."""

    async def call(
        self, prompt: str, *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return f"response to: {prompt}"

    async def call_json(
        self, prompt: str, *,
        system_prompt: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        return {"prompt": prompt}

    async def generate(self, prompt: str, max_tokens: int = 10) -> str:
        return prompt[:max_tokens]

    async def close(self) -> None:
        pass


class _PartialProvider:
    """只实现 1 个方法 (incomplete)."""

    async def call(self, prompt: str, **kwargs) -> str:
        return prompt


class _Empty:
    """空类,不实现任何方法."""
    pass


class TestLLMProviderProtocol:
    """验证 LLMProvider Protocol 契约 (runtime_checkable)."""

    def test_happy_full_provider_satisfies_protocol(self):
        """完整实现 4 方法的类应通过 isinstance 检查."""
        provider = _FullProvider()
        assert isinstance(provider, LLMProvider)

    def test_boundary_partial_provider_does_not_satisfy(self):
        """只实现 1 方法的类不应通过 isinstance 检查."""
        partial = _PartialProvider()
        assert not isinstance(partial, LLMProvider)

    def test_boundary_empty_class_does_not_satisfy(self):
        """空类不应通过 isinstance 检查."""
        empty = _Empty()
        assert not isinstance(empty, LLMProvider)

    @pytest.mark.asyncio
    async def test_happy_full_provider_methods_callable(self):
        """Protocol 通过后,4 个方法应可正常调用."""
        provider = _FullProvider()

        # call
        result = await provider.call("hello")
        assert "hello" in result

        # call_json
        result_json = await provider.call_json("hello")
        assert isinstance(result_json, dict)
        assert result_json["prompt"] == "hello"

        # generate
        gen = await provider.generate("hello world", max_tokens=5)
        assert gen == "hello"

        # close (no return)
        await provider.close()

    def test_boundary_protocol_attributes(self):
        """Protocol 应暴露 4 个方法名."""
        assert LLMProvider._is_protocol is True
        assert LLMProvider._is_runtime_protocol is True
        expected_methods = {"call", "call_json", "generate", "close"}
        protocol_attrs = {
            attr for attr in dir(LLMProvider)
            if not attr.startswith("_") and callable(getattr(LLMProvider, attr, None))
        }
        assert expected_methods.issubset(protocol_attrs)

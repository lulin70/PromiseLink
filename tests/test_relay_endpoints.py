"""Tests for promiselink.services.relay_endpoints.

Tests RelayEndpointsMixin: _parse_llm_response static method, the
LLMProvider Protocol methods (call / call_json / generate), and
HTTP helpers behavior. Uses a minimal host class to avoid the full
RelayClient HTTP stack.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from promiselink.core.exceptions import LLMResponseParseError
from promiselink.services.relay_endpoints import RelayEndpointsMixin

# ── Extended host class for X-AI-Call header tests ──


class _MockRelayClientWithHTTP(RelayEndpointsMixin):
    """Extended host class that captures HTTP requests for header inspection.

    Implements _get_client/_auth_headers/_ensure_token so we can verify
    that _post_with_auth/_post_multipart_with_auth/_stream_llm attach
    the X-AI-Call: true header for gateway billing attribution.
    """

    def __init__(self) -> None:
        self.gateway_url = "http://test-gateway.example.com"
        self.timeout = 10
        self.max_retries = 1

        # Capture all HTTP calls
        self.captured_posts: list[dict] = []
        self.captured_streams: list[dict] = []

        # Build a mock httpx.AsyncClient that records calls
        self._mock_client = MagicMock()
        self._mock_client.is_closed = False

        async def _post_side_effect(url, **kwargs):
            self.captured_posts.append({"url": url, **kwargs})
            resp = MagicMock()
            resp.status_code = 200
            resp.json = lambda: {"data": {"content": "ok"}}
            resp.aread = AsyncMock(return_value=b"{}")
            resp.text = "{}"
            return resp

        def _stream_side_effect(method, url, **kwargs):
            self.captured_streams.append({"method": method, "url": url, **kwargs})

            class _Ctx:
                async def __aenter__(self_inner):
                    resp = MagicMock()
                    resp.status_code = 200
                    resp.aiter_lines = self._aiter_lines
                    return resp

                async def __aexit__(self_inner, *args):
                    return False

            return _Ctx()

        def _aiter_lines():
            async def _gen():
                if False:
                    yield ""  # pragma: no cover - empty generator
            return _gen()

        self._aiter_lines = _aiter_lines
        self._mock_client.post = MagicMock(side_effect=_post_side_effect)
        self._mock_client.stream = MagicMock(side_effect=_stream_side_effect)

    async def _get_client(self):
        return self._mock_client

    def _auth_headers(self) -> dict:
        return {"Authorization": "Bearer fake-jwt"}

    async def _ensure_token(self) -> str:
        return "fake-jwt"

    async def refresh_token(self) -> str:
        return "fake-jwt-refreshed"


# ── Test host class ──


class _MockRelayClient(RelayEndpointsMixin):
    """Minimal host class providing the dependencies RelayEndpointsMixin needs.

    Allows controlling chat_completion return value without HTTP.
    """

    def __init__(
        self,
        *,
        chat_result: dict | None = None,
        chat_exception: Exception | None = None,
    ) -> None:
        self.gateway_url = "http://test-gateway.example.com"
        self.timeout = 10
        self.max_retries = 3
        self._chat_result = chat_result or {}
        self._chat_exception = chat_exception
        self.last_chat_kwargs: dict | None = None

    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str = "default",
        *,
        stream: bool = False,
        max_tokens: int = 2000,
        temperature: float = 0.7,
    ) -> dict:
        self.last_chat_kwargs = {
            "model": model,
            "stream": stream,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        self.last_messages = messages
        if self._chat_exception:
            raise self._chat_exception
        return self._chat_result


# ═══════════════════════════════════════════════════════════════
# _parse_llm_response — 静态方法 (纯函数)
# ═══════════════════════════════════════════════════════════════


class TestParseLLMResponse:
    """_parse_llm_response 静态方法 — 网关响应解析."""

    def test_happy_data_envelope_extracts_content(self):
        """UnifiedResponse envelope (data.content) 应正确提取."""
        data = {
            "data": {
                "content": "hello world",
                "model": "moka-1",
                "usage": {"tokens": 10},
                "billing": {"cost": 0.01},
            }
        }
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == "hello world"
        assert result["model"] == "moka-1"
        assert result["usage"] == {"tokens": 10}
        assert result["billing"] == {"cost": 0.01}

    def test_happy_flat_dict_extracts_content(self):
        """扁平 dict {content, model, ...} 应正确提取."""
        data = {
            "content": "flat response",
            "model": "gpt-4",
            "usage": {},
            "billing": {},
        }
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == "flat response"
        assert result["model"] == "gpt-4"

    def test_happy_openai_choices_format(self):
        """OpenAI choices 格式应提取 choices[0].message.content."""
        data = {
            "choices": [
                {"message": {"content": "from choices"}}
            ],
            "model": "openai-compatible",
        }
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == "from choices"

    def test_boundary_empty_content_returns_empty_string(self):
        """无 content 字段且无 choices 时 content 应为空字符串."""
        data = {"model": "x"}
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == ""

    def test_boundary_empty_choices_returns_empty_string(self):
        """空 choices 列表应返回空 content."""
        data = {"choices": []}
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == ""

    def test_boundary_data_not_dict_uses_top_level(self):
        """data 字段非 dict 时应回退到顶层."""
        data = {
            "data": "not a dict",
            "content": "fallback content",
        }
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["content"] == "fallback content"

    def test_boundary_no_model_returns_empty_string(self):
        """无 model 字段时 model 应为空字符串."""
        data = {"content": "x"}
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["model"] == ""

    def test_boundary_no_usage_returns_empty_dict(self):
        """无 usage 字段时 usage 应为空 dict."""
        data = {"content": "x"}
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["usage"] == {}

    def test_boundary_no_billing_returns_empty_dict(self):
        """无 billing 字段时 billing 应为空 dict."""
        data = {"content": "x"}
        result = RelayEndpointsMixin._parse_llm_response(data)
        assert result["billing"] == {}


# ═══════════════════════════════════════════════════════════════
# call — LLMProvider Protocol
# ═══════════════════════════════════════════════════════════════


class TestCallMethod:
    """call 方法 — LLMProvider Protocol 实现."""

    @pytest.mark.asyncio
    async def test_happy_returns_content_stripped(self):
        """call 应返回 strip 后的 content."""
        client = _MockRelayClient(chat_result={
            "content": "  hello world  ",
            "model": "m",
            "usage": {},
            "billing": {},
        })
        result = await client.call("test prompt")
        assert result == "hello world"

    @pytest.mark.asyncio
    async def test_happy_passes_system_prompt_as_system_message(self):
        """system_prompt 应被加入 messages 列表作为 system 角色."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.call("user prompt", system_prompt="you are an assistant")
        assert client.last_messages[0] == {
            "role": "system", "content": "you are an assistant"
        }
        assert client.last_messages[1] == {
            "role": "user", "content": "user prompt"
        }

    @pytest.mark.asyncio
    async def test_boundary_no_system_prompt_only_user_message(self):
        """无 system_prompt 时 messages 应只包含 user 消息."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.call("just user")
        assert len(client.last_messages) == 1
        assert client.last_messages[0] == {"role": "user", "content": "just user"}

    @pytest.mark.asyncio
    async def test_happy_passes_max_tokens_and_temperature(self):
        """max_tokens 和 temperature 应被传递给 chat_completion."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.call("p", max_tokens=500, temperature=0.5)
        assert client.last_chat_kwargs["max_tokens"] == 500
        assert client.last_chat_kwargs["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_boundary_default_max_tokens_is_2000(self):
        """无 max_tokens 时默认 2000."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.call("p")
        assert client.last_chat_kwargs["max_tokens"] == 2000

    @pytest.mark.asyncio
    async def test_boundary_default_temperature_is_0_7(self):
        """无 temperature 时默认 0.7."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.call("p")
        assert client.last_chat_kwargs["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_boundary_empty_content_raises_parse_error(self):
        """空 content 应抛 LLMResponseParseError."""
        client = _MockRelayClient(chat_result={"content": ""})
        with pytest.raises(LLMResponseParseError, match="empty content"):
            await client.call("p")


# ═══════════════════════════════════════════════════════════════
# call_json — LLMProvider Protocol
# ═══════════════════════════════════════════════════════════════


class TestCallJsonMethod:
    """call_json 方法 — JSON 响应解析."""

    @pytest.mark.asyncio
    async def test_happy_returns_parsed_json(self):
        """有效 JSON 响应应返回解析后的 dict."""
        json_str = '{"name": "张三", "company": "智源AI"}'
        client = _MockRelayClient(chat_result={"content": json_str})
        result = await client.call_json("extract person info")
        assert result == {"name": "张三", "company": "智源AI"}

    @pytest.mark.asyncio
    async def test_happy_extracts_json_from_markdown_code_block(self):
        """应能从 markdown code block 中提取 JSON."""
        content = '```json\n{"key": "value"}\n```'
        client = _MockRelayClient(chat_result={"content": content})
        result = await client.call_json("p")
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_boundary_invalid_json_raises_parse_error(self):
        """无效 JSON 应抛 LLMResponseParseError."""
        client = _MockRelayClient(chat_result={"content": "not json at all"})
        with pytest.raises(LLMResponseParseError):
            await client.call_json("p")

    @pytest.mark.asyncio
    async def test_boundary_partial_json_raises_parse_error(self):
        """部分 JSON 应抛 LLMResponseParseError."""
        client = _MockRelayClient(chat_result={"content": '{"name": "张三"'})
        with pytest.raises(LLMResponseParseError):
            await client.call_json("p")


# ═══════════════════════════════════════════════════════════════
# generate — LLMProvider Protocol
# ═══════════════════════════════════════════════════════════════


class TestGenerateMethod:
    """generate 方法 — 短文本生成."""

    @pytest.mark.asyncio
    async def test_happy_returns_content(self):
        """generate 应返回 LLM 内容."""
        client = _MockRelayClient(chat_result={"content": "short text"})
        result = await client.generate("prompt", max_tokens=50)
        assert result == "short text"

    @pytest.mark.asyncio
    async def test_happy_uses_temperature_zero_for_determinism(self):
        """generate 应使用 temperature=0.0 (文档化的确定性输出)."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.generate("p", max_tokens=10)
        assert client.last_chat_kwargs["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_happy_passes_max_tokens(self):
        """max_tokens 应被传递给 chat_completion."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.generate("p", max_tokens=25)
        assert client.last_chat_kwargs["max_tokens"] == 25

    @pytest.mark.asyncio
    async def test_boundary_default_max_tokens_is_10(self):
        """无 max_tokens 时默认 10 (文档化的短输出默认值)."""
        client = _MockRelayClient(chat_result={"content": "x"})
        await client.generate("p")
        assert client.last_chat_kwargs["max_tokens"] == 10


# ═══════════════════════════════════════════════════════════════
# RelayEndpointsMixin — 类结构验证
# ═══════════════════════════════════════════════════════════════


class TestRelayEndpointsMixinStructure:
    """RelayEndpointsMixin 类结构验证."""

    def test_class_defines_required_attributes(self):
        """Mixin 应声明 host class 提供的属性 (类型注解)."""
        annotations = RelayEndpointsMixin.__annotations__
        assert "gateway_url" in annotations
        assert "timeout" in annotations
        assert "max_retries" in annotations
        assert "_get_client" in annotations
        assert "_auth_headers" in annotations
        assert "_ensure_token" in annotations
        assert "refresh_token" in annotations

    def test_class_has_llm_provider_methods(self):
        """Mixin 应实现 LLMProvider Protocol 的 4 个方法."""
        assert hasattr(RelayEndpointsMixin, "call")
        assert hasattr(RelayEndpointsMixin, "call_json")
        assert hasattr(RelayEndpointsMixin, "generate")
        assert hasattr(RelayEndpointsMixin, "close") or hasattr(RelayEndpointsMixin, "chat_completion")

    def test_class_has_relay_channel_methods(self):
        """Mixin 应实现 4 个 relay 渠道方法."""
        assert hasattr(RelayEndpointsMixin, "chat_completion")
        assert hasattr(RelayEndpointsMixin, "asr")
        assert hasattr(RelayEndpointsMixin, "tts")
        assert hasattr(RelayEndpointsMixin, "ocr")

    def test_class_has_internal_http_helpers(self):
        """Mixin 应实现内部 HTTP 辅助方法."""
        assert hasattr(RelayEndpointsMixin, "_post_with_auth")
        assert hasattr(RelayEndpointsMixin, "_post_multipart_with_auth")
        assert hasattr(RelayEndpointsMixin, "_stream_llm")
        assert hasattr(RelayEndpointsMixin, "_parse_llm_response")


# ═══════════════════════════════════════════════════════════════
# X-AI-Call header — 网关计费归属区分
# ═══════════════════════════════════════════════════════════════


class TestXAICallHeader:
    """验证所有发往网关的 HTTP 请求都携带 X-AI-Call: true 标头。

    网关用此标头区分"基础版发起的 AI 调用"vs"小程序发起的 AI 调用"，
    用于计费归属。基础版 relay_endpoints.py 在 6 处 HTTP 请求位置添加此标头。
    """

    @pytest.mark.asyncio
    async def test_post_with_auth_includes_x_ai_call_header(self):
        """_post_with_auth 应携带 X-AI-Call: true."""
        client = _MockRelayClientWithHTTP()
        await client._post_with_auth(
            "http://gateway/api/v1/pro/relay/llm",
            {"messages": [{"role": "user", "content": "hi"}]},
        )
        assert len(client.captured_posts) == 1
        headers = client.captured_posts[0]["headers"]
        assert headers.get("X-AI-Call") == "true"

    @pytest.mark.asyncio
    async def test_post_with_auth_preserves_auth_header(self):
        """_post_with_auth 同时应保留 Authorization 标头."""
        client = _MockRelayClientWithHTTP()
        await client._post_with_auth("http://gateway/x", {})
        headers = client.captured_posts[0]["headers"]
        assert headers.get("Authorization") == "Bearer fake-jwt"
        assert headers.get("X-AI-Call") == "true"

    @pytest.mark.asyncio
    async def test_post_multipart_with_auth_includes_x_ai_call_header(self):
        """_post_multipart_with_auth 应携带 X-AI-Call: true."""
        client = _MockRelayClientWithHTTP()
        files = {"audio": ("test.wav", b"fake-audio", "audio/wav")}
        data = {"model": "whisper"}
        await client._post_multipart_with_auth(
            "http://gateway/api/v1/pro/relay/asr",
            files=files,
            data=data,
        )
        assert len(client.captured_posts) == 1
        headers = client.captured_posts[0]["headers"]
        assert headers.get("X-AI-Call") == "true"

    @pytest.mark.asyncio
    async def test_stream_llm_includes_x_ai_call_header(self):
        """_stream_llm 应携带 X-AI-Call: true."""
        client = _MockRelayClientWithHTTP()
        gen = await client._stream_llm(
            "http://gateway/api/v1/pro/relay/llm",
            {"stream": True, "messages": []},
        )
        # Drain the generator to trigger the stream call
        async for _ in gen:  # noqa: F841
            pass
        assert len(client.captured_streams) == 1
        headers = client.captured_streams[0]["headers"]
        assert headers.get("X-AI-Call") == "true"

    @pytest.mark.asyncio
    async def test_chat_completion_via_post_includes_x_ai_call_header(self):
        """chat_completion (non-stream) 应经 _post_with_auth 携带 X-AI-Call."""
        client = _MockRelayClientWithHTTP()
        await client.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            model="moka/claude",
            stream=False,
        )
        assert len(client.captured_posts) == 1
        headers = client.captured_posts[0]["headers"]
        assert headers.get("X-AI-Call") == "true"

    @pytest.mark.asyncio
    async def test_chat_completion_stream_via_stream_llm_includes_x_ai_call_header(self):
        """chat_completion (stream) 应经 _stream_llm 携带 X-AI-Call."""
        client = _MockRelayClientWithHTTP()
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "hi"}],
            model="moka/claude",
            stream=True,
        )
        # chat_completion(stream=True) returns {"stream": <coroutine>}
        # The coroutine must be awaited to get the async generator.
        stream_coro = result["stream"]
        async_gen = await stream_coro
        async for _ in async_gen:  # noqa: F841
            pass
        assert len(client.captured_streams) >= 1
        headers = client.captured_streams[0]["headers"]
        assert headers.get("X-AI-Call") == "true"

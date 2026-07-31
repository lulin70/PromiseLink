"""Tests for title_generator — LLM tag stripping and title generation.

Covers the BUG discovered on 2026-07-31:
  Event title contained ``<think>`` tag leaked from LLM reasoning process.

Root cause: rsxermu666 Claude model returns ``<think>...</think>`` reasoning
blocks before the actual answer. title_generator.py did not strip these
tags, so they were stored in events.title (and truncated mid-tag, leaving
unclosed ``<think>`` in the title).

This test file verifies:
  1. ``_strip_llm_tags`` removes <think>...</think> blocks (closed)
  2. ``_strip_llm_tags`` removes unclosed <think>... (truncated)
  3. ``_strip_llm_tags`` removes <RichMediaReference>...</RichMediaReference>
  4. ``_strip_llm_tags`` leaves normal text unchanged
  5. ``generate_event_title`` produces clean title when LLM returns think tags
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from promiselink.services.title_generator import _strip_llm_tags, generate_event_title


# ═══════════════════════════════════════════════════════════════════
# _strip_llm_tags — pure function tests
# ═══════════════════════════════════════════════════════════════════


class TestStripLlmTags:
    """Verify _strip_llm_tags removes LLM reasoning tags correctly."""

    def test_strip_closed_think_block(self) -> None:
        """Closed <think>...</think> block is removed completely."""
        text = "<think>\n用户要求提取标题\n</think>\n投资对接会 - 盛恒资本李总"
        assert _strip_llm_tags(text) == "投资对接会 - 盛恒资本李总"

    def test_strip_unclosed_think_block(self) -> None:
        """Unclosed <think>... (truncated by max_tokens) is removed.

        This is the exact BUG scenario from 2026-07-31: LLM returned
        ``<think>\n用户要求我从交流记录中提取一个简洁的事件标题，格式为「活动类型 - 关键人物/...``
        (truncated at 50 chars, no closing tag).
        """
        text = "<think>\n用户要求我从交流记录中提取一个简洁的事件标题，格式为「活动类型 - 关键人物/..."
        assert _strip_llm_tags(text) == ""

    def test_strip_orphan_closing_think_tag(self) -> None:
        """Orphan </think> (after partial stripping) is removed."""
        text = "</think>\n下午茶交流 - 智谱AI张总"
        assert _strip_llm_tags(text) == "下午茶交流 - 智谱AI张总"

    def test_strip_closed_rich_media_reference(self) -> None:
        """<RichMediaReference>...</RichMediaReference> is removed."""
        text = "<RichMediaReference>msg_12345.jpg</RichMediaReference>名片扫描 - 王总"
        assert _strip_llm_tags(text) == "名片扫描 - 王总"

    def test_strip_unclosed_rich_media_reference(self) -> None:
        """Unclosed <RichMediaReference>... is removed."""
        text = "<RichMediaReference>msg_12345.jpg"
        assert _strip_llm_tags(text) == ""

    def test_strip_orphan_closing_rich_media_reference(self) -> None:
        """Orphan </RichMediaReference> is removed."""
        text = "</RichMediaReference>名片扫描 - 王总"
        assert _strip_llm_tags(text) == "名片扫描 - 王总"

    def test_normal_text_unchanged(self) -> None:
        """Normal title text without any tags is unchanged."""
        text = "投资对接会 - 盛恒资本李总"
        assert _strip_llm_tags(text) == "投资对接会 - 盛恒资本李总"

    def test_empty_string(self) -> None:
        """Empty string input returns empty string."""
        assert _strip_llm_tags("") == ""

    def test_multiple_think_blocks(self) -> None:
        """Multiple <think>...</think> blocks are all removed."""
        text = "<think>block1</think>标题1<think>block2</think>标题2"
        assert _strip_llm_tags(text) == "标题1标题2"

    def test_multiline_think_block(self) -> None:
        """Multi-line <think> block is removed (DOTALL flag)."""
        text = "<think>\nline1\nline2\nline3\n</think>\n实际标题"
        assert _strip_llm_tags(text) == "实际标题"


# ═══════════════════════════════════════════════════════════════════
# generate_event_title — integration with mock LLM
# ═══════════════════════════════════════════════════════════════════


class TestGenerateEventTitle:
    """Verify generate_event_title produces clean titles from LLM responses."""

    @pytest.mark.asyncio
    async def test_clean_title_from_normal_llm_response(self) -> None:
        """Normal LLM response (no tags) produces clean title."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="投资对接会 - 盛恒资本李总")

        title = await generate_event_title(llm_client, "今天和盛恒资本李总讨论投资合作")

        assert title == "投资对接会 - 盛恒资本李总"
        assert "<think>" not in title
        assert "<RichMediaReference>" not in title

    @pytest.mark.asyncio
    async def test_clean_title_from_llm_with_think_tag(self) -> None:
        """LLM response with <think>...</think> produces clean title.

        Regression test for 2026-07-31 BUG: rsxermu666 Claude returned
        reasoning block before the actual title.
        """
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value="<think>\n用户要求提取标题\n</think>\n投资对接会 - 盛恒资本李总"
        )

        title = await generate_event_title(llm_client, "今天和盛恒资本李总讨论投资合作")

        assert title == "投资对接会 - 盛恒资本李总"
        assert "<think>" not in title
        assert "</think>" not in title

    @pytest.mark.asyncio
    async def test_clean_title_from_truncated_think_tag(self) -> None:
        """LLM response with truncated <think>... (no closing tag) returns None.

        This is the exact 2026-07-31 BUG scenario: LLM returned only the
        reasoning block (truncated at max_tokens), no actual title.
        Expected behavior: return None (no title generated).
        """
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value="<think>\n用户要求我从交流记录中提取一个简洁的事件标题，格式为「活动类型 - 关键人物/..."
        )

        title = await generate_event_title(llm_client, "今天和许总开会讨论Q3合作方案")

        # After stripping <think> block, title is empty → return None
        assert title is None

    @pytest.mark.asyncio
    async def test_clean_title_from_llm_with_rich_media_reference(self) -> None:
        """LLM response with <RichMediaReference> tag produces clean title."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(
            return_value="<RichMediaReference>msg_123.jpg</RichMediaReference>名片扫描 - 王总"
        )

        title = await generate_event_title(llm_client, "今天和王总交换名片，王总是ABC公司的CEO")

        assert title == "名片扫描 - 王总"
        assert "<RichMediaReference>" not in title

    @pytest.mark.asyncio
    async def test_short_raw_text_returns_none(self) -> None:
        """Raw text shorter than 10 chars returns None (no LLM call)."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(return_value="should not be called")

        title = await generate_event_title(llm_client, "短文本")

        assert title is None
        llm_client.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_raw_text_returns_none(self) -> None:
        """Empty raw text returns None."""
        llm_client = AsyncMock()
        title = await generate_event_title(llm_client, "")
        assert title is None

    @pytest.mark.asyncio
    async def test_title_truncated_to_50_chars(self) -> None:
        """Title longer than 50 chars is truncated with '...' suffix."""
        llm_client = AsyncMock()
        # 100-char title to ensure truncation triggers (50 char limit)
        long_title = "今天和一位非常重要的人物开会讨论一个非常重要且复杂的合作方案以及后续落地实施细节与多方资源整合及战略规划" * 2
        assert len(long_title) > 50
        llm_client.generate = AsyncMock(return_value=long_title)

        title = await generate_event_title(llm_client, "今天和一个非常重要的人开会讨论非常重要的事情" * 5)

        assert len(title) == 50
        assert title.endswith("...")
        # Truncated title should be a prefix of the original (minus last 3 chars for "...")
        assert title[:-3] == long_title[:47]

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self) -> None:
        """LLM call failure returns None (resilience)."""
        llm_client = AsyncMock()
        llm_client.generate = AsyncMock(side_effect=Exception("LLM unavailable"))

        title = await generate_event_title(llm_client, "今天和张总开会讨论Q3合作方案")

        assert title is None

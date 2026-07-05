"""Tests for promiselink.services.nudge_generator.

Tests generate_gentle_nudge with mocked LLMClient (no external calls).
Covers: LLM success path, LLM failure fallback, empty response fallback,
entity name lookup, overdue_days calculation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.nudge_generator import (
    TEMPLATE_GENTLE_NUDGE,
    generate_gentle_nudge,
)

# ── Helpers ──


async def _make_event(session, user_id: str) -> str:
    eid = str(uuid.uuid4())
    session.add(Event(
        id=eid, user_id=user_id, event_type="meeting",
        source="test", title="placeholder", raw_text="x", status="completed",
    ))
    await session.flush()
    return eid


def _make_todo(
    user_id: str,
    *,
    related_entity_id: str | None = None,
    due_date: datetime | None = None,
    description: str = "提供技术方案",
    title: str = "their promise todo",
) -> Todo:
    return Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title=title,
        description=description,
        status="pending",
        action_type="their_promise",
        fulfillment_status="pending",
        related_entity_id=related_entity_id,
        due_date=due_date,
    )


def _make_entity(user_id: str, name: str, *, source_event_id: str) -> Entity:
    return Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        status="confirmed",
        source_event_id=source_event_id,
    )


# ═══════════════════════════════════════════════════════════════
# generate_gentle_nudge — LLM 成功路径
# ═══════════════════════════════════════════════════════════════


class TestGenerateGentleNudgeSuccess:
    """generate_gentle_nudge LLM 成功路径."""

    @pytest.mark.asyncio
    async def test_happy_llm_returns_message_with_branding(self, db_session):
        """LLM 返回有效消息时应附加 PromiseLink 品牌标识."""
        user_id = "user-success"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "张总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id))
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="张总，之前的技术方案进展如何？")
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "张总" in result
        assert "PromiseLink" in result
        mock_llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_happy_llm_message_truncated_at_120_chars(self, db_session):
        """LLM 返回过长消息时应截断到 120 字符 (+ 品牌标识)."""
        user_id = "user-trunc"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "李总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id))
        db_session.add(todo)
        await db_session.flush()

        long_message = "这是一段非常长的催促消息" * 30  # > 120 chars
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value=long_message)
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        # Message body capped at 120 + " — via PromiseLink" suffix
        assert result.endswith(" — via PromiseLink")
        body = result.replace(" — via PromiseLink", "")
        assert len(body) <= 120


# ═══════════════════════════════════════════════════════════════
# generate_gentle_nudge — LLM 失败/回退路径
# ═══════════════════════════════════════════════════════════════


class TestGenerateGentleNudgeFallback:
    """generate_gentle_nudge LLM 失败时的回退模板."""

    @pytest.mark.asyncio
    async def test_boundary_llm_raises_exception_returns_fallback(self, db_session):
        """LLM 抛异常时应返回回退模板 (不抛异常)."""
        user_id = "user-fallback-exc"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "王总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id))
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("LLM API timeout"))
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "王总" in result
        assert "技术方案" in result  # from todo.description
        assert "PromiseLink" in result

    @pytest.mark.asyncio
    async def test_boundary_llm_returns_empty_returns_fallback(self, db_session):
        """LLM 返回空字符串或太短消息时应返回回退模板."""
        user_id = "user-fallback-empty"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "赵总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id))
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="ok")  # <5 chars
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "赵总" in result
        assert "PromiseLink" in result

    @pytest.mark.asyncio
    async def test_boundary_llm_returns_whitespace_returns_fallback(self, db_session):
        """LLM 返回纯空白时应返回回退模板."""
        user_id = "user-fallback-ws"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "钱总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id))
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="   \n  ")
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "钱总" in result
        assert "PromiseLink" in result


# ═══════════════════════════════════════════════════════════════
# generate_gentle_nudge — 实体名称查找
# ═══════════════════════════════════════════════════════════════


class TestGenerateGentleNudgeEntityLookup:
    """generate_gentle_nudge 实体名称查找行为."""

    @pytest.mark.asyncio
    async def test_boundary_no_related_entity_id_uses_default_name(self, db_session):
        """todo.related_entity_id 为 None 时应使用默认名称 '对方'."""
        user_id = "user-no-entity"
        todo = _make_todo(user_id, related_entity_id=None)
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("force fallback"))
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "对方" in result

    @pytest.mark.asyncio
    async def test_boundary_non_existent_entity_uses_default_name(self, db_session):
        """related_entity_id 指向不存在的实体时应使用 '对方'."""
        user_id = "user-missing-entity"
        todo = _make_todo(user_id, related_entity_id=str(uuid.uuid4()))
        db_session.add(todo)
        await db_session.flush()

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("force fallback"))
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            result = await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "对方" in result


# ═══════════════════════════════════════════════════════════════
# generate_gentle_nudge — overdue_days 计算
# ═══════════════════════════════════════════════════════════════


class TestGenerateGentleNudgeOverdueDays:
    """generate_gentle_nudge overdue_days 计算与 prompt 拼装."""

    @pytest.mark.asyncio
    async def test_happy_overdue_days_passed_to_prompt(self, db_session):
        """overdue_days 应被计算并传给 LLM prompt."""
        user_id = "user-overdue"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "孙总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        # Due date 10 days ago
        due_date = datetime.now(UTC) - timedelta(days=10)
        todo = _make_todo(user_id, related_entity_id=str(entity.id), due_date=due_date)
        db_session.add(todo)
        await db_session.flush()

        captured_prompt = []

        async def _capture_prompt(prompt, max_tokens=100):
            captured_prompt.append(prompt)
            return "好的催促消息"

        mock_llm = MagicMock()
        mock_llm.generate = _capture_prompt
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert len(captured_prompt) == 1
        # overdue_days should be approximately 10 (may be 9-11 depending on timezone)
        assert "距今已过:" in captured_prompt[0]
        # Extract the days value from prompt
        for line in captured_prompt[0].split("\n"):
            if "距今已过" in line:
                days_str = line.split(":")[-1].strip().replace("天", "")
                days = int(days_str)
                assert 9 <= days <= 11  # tolerate timezone drift
                break

    @pytest.mark.asyncio
    async def test_boundary_no_due_date_yields_zero_overdue(self, db_session):
        """无 due_date 时 overdue_days 应为 0."""
        user_id = "user-no-due"
        eid = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "周总", source_event_id=eid)
        db_session.add(entity)
        await db_session.flush()

        todo = _make_todo(user_id, related_entity_id=str(entity.id), due_date=None)
        db_session.add(todo)
        await db_session.flush()

        captured_prompt = []

        async def _capture(prompt, max_tokens=100):
            captured_prompt.append(prompt)
            return "催促消息"

        mock_llm = MagicMock()
        mock_llm.generate = _capture
        with patch("promiselink.services.nudge_generator.LLMClient", return_value=mock_llm):
            await generate_gentle_nudge(db_session, todo, config=MagicMock())

        assert "距今已过: 0天" in captured_prompt[0]


# ═══════════════════════════════════════════════════════════════
# TEMPLATE_GENTLE_NUDGE 常量
# ═══════════════════════════════════════════════════════════════


class TestTemplateGentleNudge:
    """TEMPLATE_GENTLE_NUDGE 模板常量."""

    def test_template_contains_required_placeholders(self):
        """模板应包含所有 4 个占位符."""
        assert "{entity_name}" in TEMPLATE_GENTLE_NUDGE
        assert "{promise_description}" in TEMPLATE_GENTLE_NUDGE
        assert "{promise_due_date}" in TEMPLATE_GENTLE_NUDGE
        assert "{overdue_days}" in TEMPLATE_GENTLE_NUDGE

    def test_template_format_works(self):
        """模板应能正确 format."""
        result = TEMPLATE_GENTLE_NUDGE.format(
            entity_name="张总",
            promise_description="提供技术方案",
            promise_due_date="2026-01-01",
            overdue_days=10,
        )
        assert "张总" in result
        assert "提供技术方案" in result
        assert "2026-01-01" in result
        assert "10" in result

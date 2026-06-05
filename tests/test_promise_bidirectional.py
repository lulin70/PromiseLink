"""Tests for PromiseBidirectionalHandler — F-45 bidirectional promise analysis.

Covers:
1. Rule-based keyword matching for all 6 action types
2. Todo type to action type mapping
3. LLM fallback for ambiguous cases
4. Evidence quote extraction from event text
5. Entity mapping to promisor/beneficiary
6. Confirmation status defaults (AUTO_SET for rules, PENDING for LLM)
7. Unclear handling when analysis fails
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.promise_bidirectional import (
    ActionType,
    ConfirmationStatus,
    PromiseAnalysis,
    PromiseBidirectionalHandler,
)


# Helper functions to create test objects


def make_todo(
    todo_type: str = "promise",
    title: str = "测试待办",
    description: str | None = None,
    related_entity_id: uuid.UUID | None = None,
) -> Todo:
    """Create a test Todo object."""
    return Todo(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        todo_type=todo_type,
        title=title,
        description=description,
        related_entity_id=related_entity_id,
        source_event_id=uuid.uuid4(),
    )


def make_event(
    raw_text: str = "测试事件原始文本",
    event_type: str = "meeting",
) -> Event:
    """Create a test Event object."""
    return Event(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        event_type=event_type,
        source="test",
        title="测试事件",
        raw_text=raw_text,
    )


def make_entity(
    name: str = "张三",
    entity_type: str = "person",
) -> Entity:
    """Create a test Entity object."""
    return Entity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        entity_type=entity_type,
        name=name,
        canonical_name=name,
        source_event_id=uuid.uuid4(),
    )


def make_mock_llm_client(return_value: dict | None = None):
    """Create a mock LLMClient with async call_json method.

    Args:
        return_value: Optional dict to return from call_json. If None, returns default unclear response.
    """
    mock_client = MagicMock()
    mock_client.call_json = AsyncMock(
        return_value=return_value or {
            "action_type": "unclear",
            "promisor": None,
            "beneficiary": None,
            "evidence_quote": None,
            "confidence": 0.5,
        }
    )
    return mock_client


# Test cases


class TestMyPromiseKeywordMatching:
    """Test 1: my_promise action type from keyword matching."""

    @pytest.mark.asyncio
    async def test_my_promise_keyword答应(self):
        """Match '我答应' pattern → MY_PROMISE with high confidence."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="我答应张总周五前发报价单")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MY_PROMISE
        assert result.confidence >= 0.90
        assert result.confirmation_status == ConfirmationStatus.AUTO_SET

    @pytest.mark.asyncio
    async def test_my_promise_keyword承诺(self):
        """Match '我承诺' pattern → MY_PROMISE."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="我承诺下周完成方案设计")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MY_PROMISE
        assert result.is_my_promise is True

    @pytest.mark.asyncio
    async def test_my_promise_keyword说好(self):
        """Match '我说好' pattern → MY_PROMISE."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="我说好会支持这个项目")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MY_PROMISE


class TestTheirPromiseKeywordMatching:
    """Test 2: their_promise action type from keyword matching."""

    @pytest.mark.asyncio
    async def test_their_promise_keyword说(self):
        """Match '他说要' pattern → THEIR_PROMISE."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="李总说周三给我资料")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.THEIR_PROMISE
        assert result.confidence >= 0.88
        assert result.is_my_promise is False

    @pytest.mark.asyncio
    async def test_their_promise_keyword答应(self):
        """Match '他答应' pattern → THEIR_PROMISE."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="王总答应参加我们的技术评审")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.THEIR_PROMISE


class TestMyFollowupMatching:
    """Test 3: my_followup action type from keyword and type mapping."""

    @pytest.mark.asyncio
    async def test_my_followup_keyword跟进(self):
        """Match '跟进一下' pattern → MY_FOLLOWUP."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="需要跟进一下陈总的项目进展")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MY_FOLLOWUP
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_my_followup_care_type_mapping(self):
        """Test 6: care todo_type → MY_FOLLOWUP mapping."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(todo_type="care", title="关心张总的身体健康状况")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MY_FOLLOWUP
        assert result.is_my_promise is True


class TestMutualActionMatching:
    """Test 4: mutual_action action type from keyword and type mapping."""

    @pytest.mark.asyncio
    async def test_mutual_action_keyword一起(self):
        """Match '一起' pattern → MUTUAL_ACTION."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="和王总一起讨论合作方案")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MUTUAL_ACTION
        assert result.confidence >= 0.83

    @pytest.mark.asyncio
    async def test_mutual_action_cooperation_signal_mapping(self):
        """Test 7: cooperation_signal todo_type → MUTUAL_ACTION mapping."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(
            todo_type="cooperation_signal",
            title="发现与李总公司的协同发展机遇",
        )

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.MUTUAL_ACTION


class TestSystemReminderMatching:
    """Test 5: system_reminder action type."""

    @pytest.mark.asyncio
    async def test_system_reminder_keyword(self):
        """Match '系统提醒' pattern → SYSTEM_REMINDER."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="系统提醒：合同即将到期")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.SYSTEM_REMINDER
        assert result.confidence >= 0.94  # Highest confidence pattern

    @pytest.mark.asyncio
    async def test_system_reminder_risk_type_mapping(self):
        """risk todo_type → SYSTEM_REMINDER mapping."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(
            todo_type="risk",
            title="识别到项目延期风险",
        )

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.SYSTEM_REMINDER


class TestLLMFallback:
    """Test 8: LLM fallback when rules don't match or have low confidence."""

    @pytest.mark.asyncio
    async def test_llm_fallback_for_ambiguous_todo(self):
        """When no rule matches, should call LLM for analysis."""
        mock_client = make_mock_llm_client()
        mock_client.call_json.return_value = {
            "action_type": "my_promise",
            "promisor": None,
            "beneficiary": "张三",
            "evidence_quote": "我会处理这件事",
            "confidence": 0.75,
        }

        handler = PromiseBidirectionalHandler(mock_client)
        todo = make_todo(title="这个事情需要安排一下")  # No clear keywords

        result = await handler.analyze_todo(todo)

        # Should have called LLM
        mock_client.call_json.assert_called_once()
        # LLM results should be PENDING confirmation
        assert result.confirmation_status == ConfirmationStatus.PENDING
        assert result.action_type == ActionType.MY_PROMISE

    @pytest.mark.asyncio
    async def test_llm_fallback_on_low_confidence_rule(self):
        """When no rule matches at all, should use LLM fallback."""
        mock_client = make_mock_llm_client()
        mock_client.call_json.return_value = {
            "action_type": "their_promise",
            "promisor": "李总",
            "beneficiary": None,
            "evidence_quote": None,
            "confidence": 0.85,
        }

        handler = PromiseBidirectionalHandler(mock_client)
        # followup type has no mapping and title has no keywords → no rule match
        todo = make_todo(todo_type="followup", title="某个完全模糊的任务描述")

        result = await handler.analyze_todo(todo)

        # Should fall back to LLM due to no rule match
        mock_client.call_json.assert_called_once()
        assert result.confirmation_status == ConfirmationStatus.PENDING


class TestEvidenceExtraction:
    """Test 9: Evidence quote extraction from event.raw_text."""

    @pytest.mark.asyncio
    async def test_evidence_extraction_from_event(self):
        """Should extract relevant sentence from event raw_text."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        event = make_event(
            raw_text="今天和张总开会讨论了项目进度。"
            "我答应在周五前提交最终版方案。"
            "张总表示会配合提供所需数据。"
        )
        # Use title with keyword to trigger rule-based matching (not LLM)
        todo = make_todo(title="我答应周五前提交方案")

        result = await handler.analyze_todo(todo, event=event)

        assert result.evidence_quote is not None
        assert "提交" in result.evidence_quote or "周五" in result.evidence_quote

    @pytest.mark.asyncio
    async def test_no_evidence_when_no_event(self):
        """Should return None evidence_quote when no event provided."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="测试待办")

        result = await handler.analyze_todo(todo, event=None)

        # Rule-based match, but no event to extract evidence from
        assert result.evidence_quote is None


class TestEntityMapping:
    """Test 10: Entity mapping to promisor_id/beneficiary_id."""

    @pytest.mark.asyncio
    async def test_entity_mapping_my_promise(self):
        """For my_promise: beneficiary should be the related entity."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        entity_zhang = make_entity(name="张三")
        todo = make_todo(
            title="我答应张总提交报告",
            related_entity_id=entity_zhang.id,
        )

        result = await handler.analyze_todo(todo, entities=[entity_zhang])

        assert result.beneficiary_entity_id == entity_zhang.id
        assert result.promisor_entity_id is None  # User (implicit)

    @pytest.mark.asyncio
    async def test_entity_mapping_their_promise(self):
        """For their_promise: promisor should be the related entity."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        entity_li = make_entity(name="李总")
        todo = make_todo(
            title="李总说周三给资料",
            related_entity_id=entity_li.id,
        )

        result = await handler.analyze_todo(todo, entities=[entity_li])

        assert result.promisor_entity_id == entity_li.id
        assert result.beneficiary_entity_id is None  # User (implicit)

    @pytest.mark.asyncio
    async def test_entity_mapping_mutual_action(self):
        """For mutual_action: both promisor and beneficiary should be set."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        entity_wang = make_entity(name="王总")
        entity_zhao = make_entity(name="赵总")
        todo = make_todo(
            title="和王总、赵总协同完成项目",
            related_entity_id=entity_wang.id,
        )

        result = await handler.analyze_todo(
            todo, entities=[entity_wang, entity_zhao]
        )

        assert result.promisor_entity_id is not None
        assert result.beneficiary_entity_id is not None


class TestConfirmationStatusDefaults:
    """Test 11: Confirmation status defaults based on analysis method."""

    @pytest.mark.asyncio
    async def test_auto_set_for_rule_based(self):
        """Rule-based analysis should set AUTO_SET confirmation."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())
        todo = make_todo(title="我承诺完成任务")

        result = await handler.analyze_todo(todo)

        assert result.confirmation_status == ConfirmationStatus.AUTO_SET

    @pytest.mark.asyncio
    async def test_pending_for_llm_based(self):
        """LLM-based analysis should set PENDING confirmation."""
        mock_client = make_mock_llm_client()
        mock_client.call_json.return_value = {
            "action_type": "my_followup",
            "promisor": None,
            "beneficiary": "陈总",
            "evidence_quote": None,
            "confidence": 0.70,
        }

        handler = PromiseBidirectionalHandler(mock_client)
        todo = make_todo(title="模糊的待办事项")

        result = await handler.analyze_todo(todo)

        assert result.confirmation_status == ConfirmationStatus.PENDING


class TestUnclearHandling:
    """Test 12: Unclear handling when analysis cannot determine action type."""

    @pytest.mark.asyncio
    async def test_unclear_on_llm_failure(self):
        """Should return UNCLEAR when LLM call fails."""
        mock_client = make_mock_llm_client()
        mock_client.call_json.side_effect = Exception("LLM service unavailable")

        handler = PromiseBidirectionalHandler(mock_client)
        todo = make_todo(title="完全无法判断的待办")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.UNCLEAR
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_unclear_on_invalid_action_type_from_llm(self):
        """Should return UNCLEAR when LLM returns invalid action_type."""
        mock_client = make_mock_llm_client()
        mock_client.call_json.return_value = {
            "action_type": "invalid_type",  # Not a valid ActionType
            "promisor": None,
            "beneficiary": None,
            "evidence_quote": None,
            "confidence": 0.6,
        }

        handler = PromiseBidirectionalHandler(mock_client)
        todo = make_todo(title="待分析的待办")

        result = await handler.analyze_todo(todo)

        assert result.action_type == ActionType.UNCLEAR


class TestIsMyPromiseFlag:
    """Additional test: Verify is_my_promise flag behavior."""

    @pytest.mark.asyncio
    async def test_is_my_promise_true_for_my_actions(self):
        """is_my_promise should be True for MY_PROMISE and MY_FOLLOWUP."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        todo_my = make_todo(title="我答应完成工作")
        result_my = await handler.analyze_todo(todo_my)
        assert result_my.is_my_promise is True

        todo_followup = make_todo(title="跟进一下客户反馈")
        result_followup = await handler.analyze_todo(todo_followup)
        assert result_followup.is_my_promise is True

    @pytest.mark.asyncio
    async def test_is_my_promise_false_for_other_actions(self):
        """is_my_promise should be False for non-my actions."""
        handler = PromiseBidirectionalHandler(make_mock_llm_client())

        todo_their = make_todo(title="他说会处理这个问题")
        result_their = await handler.analyze_todo(todo_their)
        assert result_their.is_my_promise is False

        todo_system = make_todo(title="系统提醒：任务到期")
        result_system = await handler.analyze_todo(todo_system)
        assert result_system.is_my_promise is False

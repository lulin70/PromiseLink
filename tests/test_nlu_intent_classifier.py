"""Tests for F-50 NLUIntentClassifier — rule-based + LLM fallback intent classification."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from promiselink.services.nlu_intent_classifier import (
    NLUIntentClassifier,
    NLUResult,
    VoiceIntent,
)
from promiselink.services.llm_client import LLMClient


# ── Helpers ──


def _make_llm_client(json_return=None) -> MagicMock:
    """Create a mock LLMClient with configurable call_json response."""
    mock = MagicMock(spec=LLMClient)
    mock.call_json = AsyncMock(return_value=json_return)
    return mock


def _make_classifier(mock_llm: MagicMock | None = None) -> NLUIntentClassifier:
    """Create a classifier instance. If no mock provided, creates one that should not be called."""
    if mock_llm is None:
        mock_llm = _make_llm_client()
    return NLUIntentClassifier(llm_client=mock_llm)


# ── Test 1: 日程查询意图识别 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_query_today():
    """'今天有什么会' → schedule_query with high confidence (rule match)."""
    classifier = _make_classifier()
    result = await classifier.classify("今天有什么会")

    assert result.intent == VoiceIntent.SCHEDULE_QUERY
    assert result.confidence >= 0.85
    assert "date" in result.slots or "今天" in result.evidence.lower() or "schedule" in result.evidence.lower()


@pytest.mark.asyncio
async def test_schedule_query_tomorrow():
    """'明天安排' → schedule_query via rule matching."""
    classifier = _make_classifier()
    result = await classifier.classify("明天安排")

    assert result.intent == VoiceIntent.SCHEDULE_QUERY
    assert result.confidence >= 0.85
    assert result.method == "rule"


@pytest.mark.asyncio
async def test_schedule_query_meeting_keyword():
    """'下午有会议吗' → schedule_query via '会议' keyword."""
    classifier = _make_classifier()
    result = await classifier.classify("下午有会议吗")

    assert result.intent == VoiceIntent.SCHEDULE_QUERY
    assert result.confidence >= 0.85


# ── Test 2: 承诺追踪意图识别 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_promise_tracker_promise():
    """'我答应谁什么还没做' → promise_tracker."""
    classifier = _make_classifier()
    result = await classifier.classify("我答应张总什么还没做")

    assert result.intent == VoiceIntent.PROMISE_TRACKER
    assert result.confidence >= 0.85
    # Should extract person name
    assert result.slots.get("person") == "张总"


@pytest.mark.asyncio
async def test_promise_tracker_todo():
    """'待办事项有哪些' → promise_tracker via '待办' keyword."""
    classifier = _make_classifier()
    result = await classifier.classify("待办事项有哪些")

    assert result.intent == VoiceIntent.PROMISE_TRACKER
    assert result.confidence >= 0.85


# ── Test 3: 关系状态意图识别 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_relationship_status_progress():
    """'张总到哪步了' → relationship_status."""
    classifier = _make_classifier()
    result = await classifier.classify("张总到哪步了")

    assert result.intent == VoiceIntent.RELATIONSHIP_STATUS
    assert result.confidence >= 0.85
    assert result.slots.get("person") == "张总"


@pytest.mark.asyncio
async def test_relationship_status_how():
    """'李总最近怎么样' → relationship_status."""
    classifier = _make_classifier()
    result = await classifier.classify("李总最近怎么样")

    assert result.intent == VoiceIntent.RELATIONSHIP_STATUS
    assert result.slots.get("person") == "李总"


# ── Test 4: 行动建议意图识别 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_action_suggestion_what_to_do():
    """'我该联系谁' → action_suggestion."""
    classifier = _make_classifier()
    result = await classifier.classify("我该联系谁")

    assert result.intent == VoiceIntent.ACTION_SUGGESTION
    assert result.confidence >= 0.85


@pytest.mark.asyncio
async def test_action_suggestion_next_step():
    """'下一步该怎么推进' → action_suggestion."""
    classifier = _make_classifier()
    result = await classifier.classify("下一步该怎么推进")

    assert result.intent == VoiceIntent.ACTION_SUGGESTION


# ── Test 5: 创建提醒意图识别 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_todo_create_reminder():
    """'帮我记一下周五见王总' → todo_create with slots."""
    classifier = _make_classifier()
    result = await classifier.classify("帮我记一下周五见王总")

    assert result.intent == VoiceIntent.TODO_CREATE
    assert result.confidence >= 0.85
    assert result.slots.get("content") is not None
    assert result.slots.get("person") == "王总"
    assert "due_date" in result.slots


@pytest.mark.asyncio
async def test_todo_create_alert():
    """'提醒我明天开会' → todo_create."""
    classifier = _make_classifier()
    result = await classifier.classify("提醒我明天开会")

    assert result.intent == VoiceIntent.TODO_CREATE
    assert result.slots.get("content") is not None


# ── Test 6: 退出意图识别 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_exit_goodbye():
    """'再见' → exit."""
    classifier = _make_classifier()
    result = await classifier.classify("再见")

    assert result.intent == VoiceIntent.EXIT
    assert result.confidence >= 0.90


@pytest.mark.asyncio
async def test_exit_no_need():
    """'不用了' → exit."""
    classifier = _make_classifier()
    result = await classifier.classify("不用了")

    assert result.intent == VoiceIntent.EXIT


# ── Test 7: 规则高置信度时不调用 LLM (mock 验证) ───────────────


@pytest.mark.asyncio
async def test_high_confidence_rule_does_not_call_llm():
    """When rule matches with confidence >= 0.85, LLM must NOT be called."""
    mock_llm = _make_llm_client()
    classifier = _make_classifier(mock_llm)

    result = await classifier.classify("今天有什么会")

    assert result.intent == VoiceIntent.SCHEDULE_QUERY
    assert result.method == "rule"
    mock_llm.call_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_exit_high_confidence_no_llm():
    """Exit intent has confidence 0.95, should not trigger LLM."""
    mock_llm = _make_llm_client()
    classifier = _make_classifier(mock_llm)

    result = await classifier.classify("再见")

    assert result.intent == VoiceIntent.EXIT
    mock_llm.call_json.assert_not_awaited()


# ── Test 8: 规则不命中时 fallback 到 LLM ─────────────────────────


@pytest.mark.asyncio
async def test_no_rule_match_falls_back_to_llm():
    """Query with no keyword match falls back to LLM classification."""
    llm_response = {
        "intent": "schedule_query",
        "confidence": 0.88,
        "slots": {"date": "2026-06-05"},
        "evidence": "User seems to ask about schedule",
    }
    mock_llm = _make_llm_client(json_return=llm_response)
    classifier = _make_classifier(mock_llm)

    result = await classifier.classify("我想知道一些事情")

    assert result.method == "llm"
    assert result.intent == VoiceIntent.SCHEDULE_QUERY
    assert result.confidence == 0.88
    mock_llm.call_json.assert_awaited_once()


# ── Test 9: slot 提取 — 日期 ──────────────────────────────────────


def test_slot_extract_date_tomorrow():
    """'明天' slot extraction returns correct ISO date."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C
    today = date.today()
    expected = (today + timedelta(days=1)).isoformat()

    slots = C._extract_slots("明天有什么安排", VoiceIntent.SCHEDULE_QUERY)
    assert slots["date"] == expected


def test_slot_extract_date_day_after_tomorrow():
    """'后天' slot extraction returns correct ISO date."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C
    today = date.today()
    expected = (today + timedelta(days=2)).isoformat()

    slots = C._extract_slots("后天有会吗", VoiceIntent.SCHEDULE_QUERY)
    assert slots["date"] == expected


def test_slot_extract_date_range_this_week():
    """'本周' slot extraction returns correct date range."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C
    today = date.today()

    slots = C._extract_slots("本周的日程", VoiceIntent.SCHEDULE_QUERY)
    assert "date_range" in slots
    assert slots["date_range"]["start"] == today.isoformat()


def test_slot_extract_date_iso_format():
    """ISO date pattern in text gets extracted as date slot."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C

    slots = C._extract_slots("2026-06-10有什么安排", VoiceIntent.SCHEDULE_QUERY)
    assert slots["date"] == "2026-06-10"


# ── Test 10: slot 提取 — 人名 ──────────────────────────────────────


def test_slot_extract_person_name():
    """Person name '张总' extracted for relationship_status intent."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C

    slots = C._extract_slots("张总到哪步了", VoiceIntent.RELATIONSHIP_STATUS)
    assert slots["person"] == "张总"


def test_slot_extract_person_name_for_promise():
    """Person name extracted for promise_tracker intent too."""
    from promiselink.services.nlu_intent_classifier import NLUIntentClassifier as C

    slots = C._extract_slots("我答应王经理的事", VoiceIntent.PROMISE_TRACKER)
    assert slots["person"] == "王经理"


# ── Test 11: 空输入处理 ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_input_returns_unclear():
    """Empty query text → unclear intent with zero confidence."""
    classifier = _make_classifier()
    result = await classifier.classify("")

    assert result.intent == VoiceIntent.UNCLEAR
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_whitespace_only_input():
    """Whitespace-only input → unclear intent."""
    classifier = _make_classifier()
    result = await classifier.classify("   ")

    assert result.intent == VoiceIntent.UNCLEAR


# ── Test 12: LLM 失败降级 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_failure_degrades_to_unclear():
    """When LLM raises exception, degrades to UNCLEAR with low confidence."""
    mock_llm = _make_llm_client()
    mock_llm.call_json = AsyncMock(side_effect=Exception("LLM service unavailable"))
    classifier = _make_classifier(mock_llm)

    # Use a query that won't match any rule (triggers LLM fallback)
    result = await classifier.classify("这个完全没关键词的东西")

    assert result.intent == VoiceIntent.UNCLEAR
    assert result.confidence <= 0.35
    assert "failed" in result.evidence.lower() or "error" in result.evidence.lower()


# ── Test 13: confidence 钳位 [0, 1] ────────────────────────────────


@pytest.mark.asyncio
async def test_confidence_clamped_to_valid_range():
    """LLM returning out-of-range confidence values gets clamped to [0, 1]."""
    for bad_value, expected in [(-0.5, 0.0), (1.5, 1.0), (999, 1.0), (-100, 0.0)]:
        mock_llm = _make_llm_client(json_return={
            "intent": "schedule_query",
            "confidence": bad_value,
            "slots": {},
            "evidence": "test",
        })
        classifier = _make_classifier(mock_llm)

        result = await classifier.classify("随便说点什么来触发llm")

        assert result.confidence == expected, (
            f"Confidence {bad_value} should be clamped to {expected}, got {result.confidence}"
        )


@pytest.mark.asyncio
async def test_all_rule_results_have_valid_confidence():
    """All rule-based results have confidence in [0, 1]."""
    classifier = _make_classifier()

    test_queries = [
        "今天有什么会",
        "明天安排",
        "后天日程",
        "承诺还没做完",
        "关系进展如何",
        "建议下一步",
        "帮我记个事",
        "再见",
        "不用了",
        "你好",
        "谢谢",
    ]

    for query in test_queries:
        result = await classifier.classify(query)
        assert 0.0 <= result.confidence <= 1.0, (
            f"Invalid confidence {result.confidence} for query '{query}'"
        )


# ── Test 14: chitchat 检测 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_chitchat_hello():
    """'你好' → chitchat intent."""
    classifier = _make_classifier()
    result = await classifier.classify("你好")

    assert result.intent == VoiceIntent.CHITCHAT
    assert result.confidence >= 0.85


@pytest.mark.asyncio
async def test_chitchat_thanks():
    """'谢谢' → chitchat intent."""
    classifier = _make_classifier()
    result = await classifier.classify("谢谢")

    assert result.intent == VoiceIntent.CHITCHAT


@pytest.mark.asyncio
async def test_chitchat_greeting_morning():
    """'早上好' → chitchat intent."""
    classifier = _make_classifier()
    result = await classifier.classify("早上好")

    assert result.intent == VoiceIntent.CHITCHAT


# ── Test 15: LLM 返回无效 intent 时降级 ───────────────────────────


@pytest.mark.asyncio
async def test_llm_invalid_intent_defaults_to_unclear():
    """LLM returning unrecognized intent string defaults to UNCLEAR."""
    mock_llm = _make_llm_client(json_return={
        "intent": "nonexistent_intent_xyz",
        "confidence": 0.9,
        "slots": {},
        "evidence": "bad classification",
    })
    classifier = _make_classifier(mock_llm)

    result = await classifier.classify("需要LLM判断的文本")

    assert result.intent == VoiceIntent.UNCLEAR
    assert "invalid intent" in result.evidence.lower() or "defaulted" in result.evidence.lower()


@pytest.mark.asyncio
async def test_llm_malformed_response_degradation():
    """When LLM response is missing required fields, degrades gracefully."""
    mock_llm = _make_llm_client(json_return={"wrong_key": "value"})
    classifier = _make_classifier(mock_llm)

    result = await classifier.classify("需要LLM判断的文本2")

    # Should not crash; intent defaults to UNCLEAR, confidence clamped
    assert isinstance(result.intent, VoiceIntent)
    assert 0.0 <= result.confidence <= 1.0

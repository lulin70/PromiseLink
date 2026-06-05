"""Tests for F-44 InputScopeClassifier — rule-based + LLM fallback classification."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from eventlink.models.event import Event
from eventlink.services.input_scope_classifier import (
    ClassificationResult,
    InputScope,
    InputScopeClassifier,
)
from eventlink.services.llm_client import LLMClient


# ── Helpers ──


def _make_llm_client(json_return=None) -> MagicMock:
    """Create a mock LLMClient with configurable call_json response."""
    mock = MagicMock(spec=LLMClient)
    mock.call_json = AsyncMock(return_value=json_return)
    return mock


def _make_event(
    event_type: str = "manual",
    source: str = "manual",
    title: str = "Test Event",
    raw_text: str = "Some content",
) -> Event:
    """Create an Event instance for testing (SQLite-compatible string IDs)."""
    return Event(
        id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        event_type=event_type,
        source=source,
        title=title,
        raw_text=raw_text,
        status="pending",
    )


def _make_classifier(mock_llm: MagicMock | None = None) -> InputScopeClassifier:
    """Create a classifier instance. If no mock provided, creates one that should not be called."""
    if mock_llm is None:
        # Create a sentinel mock — if called, tests will fail because it wasn't expected
        mock_llm = _make_llm_client()
    return InputScopeClassifier(llm_client=mock_llm)


# ── Test 1: card_scan 事件 → 正确分类 ─────────────────────────────


@pytest.mark.asyncio
async def test_card_scan_wechat_scan_classifies_correctly():
    """card_save + wechat_scan source → card_scan with high confidence."""
    classifier = _make_classifier()
    event = _make_event(event_type="card_save", source="wechat_scan", title="扫描名片")

    result = await classifier.classify(event)

    assert result.scope == InputScope.CARD_SCAN
    assert result.confidence >= 0.90
    assert result.method == "rule"


@pytest.mark.asyncio
async def test_card_scan_manual_source_classifies_correctly():
    """card_save + manual source → card_scan."""
    classifier = _make_classifier()
    event = _make_event(event_type="card_save", source="manual", title="手动录入名片")

    result = await classifier.classify(event)

    assert result.scope == InputScope.CARD_SCAN
    assert result.confidence == 0.95
    assert result.method == "rule"


# ── Test 2: meeting 事件 → 正确分类 ───────────────────────────────


@pytest.mark.asyncio
async def test_meeting_calendar_source_classifies_correctly():
    """meeting + calendar source → meeting with high confidence."""
    classifier = _make_classifier()
    event = _make_event(event_type="meeting", source="calendar", title="产品评审会")

    result = await classifier.classify(event)

    assert result.scope == InputScope.MEETING
    assert result.confidence == 0.95
    assert result.method == "rule"


# ── Test 3: call 事件 → 正确分类 ──────────────────────────────────


@pytest.mark.asyncio
async def test_call_phone_source_classifies_correctly():
    """call + phone source → call with high confidence."""
    classifier = _make_classifier()
    event = _make_event(event_type="call", source="phone", title="与客户电话沟通")

    result = await classifier.classify(event)

    assert result.scope == InputScope.CALL
    assert result.confidence == 0.95
    assert result.method == "rule"


# ── Test 4: manual + followup 来源 → followup ─────────────────────


@pytest.mark.asyncio
async def test_manual_followup_reminder_source():
    """manual + followup_reminder source → followup."""
    classifier = _make_classifier()
    event = _make_event(
        event_type="manual", source="followup_reminder", title="跟进张三项目"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.FOLLOWUP
    assert result.confidence == 0.90
    assert result.method == "rule"


# ── Test 5: manual + voice 来源 → voice_query ─────────────────────


@pytest.mark.asyncio
async def test_manual_voice_input_source():
    """manual + voice_input source → voice_query."""
    classifier = _make_classifier()
    event = _make_event(
        event_type="manual", source="voice_input", title="语音查询联系人"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.VOICE_QUERY
    assert result.confidence == 0.90
    assert result.method == "rule"


# ── Test 6: 规则高置信度时不调用 LLM (mock 验证) ───────────────


@pytest.mark.asyncio
async def test_high_confidence_rule_does_not_call_llm():
    """When rule matches with confidence >= 0.85, LLM must NOT be called."""
    mock_llm = _make_llm_client()
    classifier = _make_classifier(mock_llm)
    event = _make_event(event_type="card_save", source="wechat_scan", title="扫描名片")

    result = await classifier.classify(event)

    assert result.scope == InputScope.CARD_SCAN
    assert result.method == "rule"
    # LLM should NOT have been called for high-confidence rule match
    mock_llm.call_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_meeting_high_confidence_no_llm():
    """meeting + calendar (confidence 0.95) should not trigger LLM."""
    mock_llm = _make_llm_client()
    classifier = _make_classifier(mock_llm)
    event = _make_event(event_type="meeting", source="calendar", title="周会")

    result = await classifier.classify(event)

    assert result.scope == InputScope.MEETING
    mock_llm.call_json.assert_not_awaited()


# ── Test 7: 规则低置信度时 fallback 到 LLM ─────────────────────


@pytest.mark.asyncio
async def test_low_confidence_rule_falls_back_to_llm():
    """Manual event without specific source (confidence 0.70 < 0.85) falls back to LLM."""
    llm_response = {
        "scope": "followup",
        "confidence": 0.88,
        "evidence": "Title suggests follow-up action",
    }
    mock_llm = _make_llm_client(json_return=llm_response)
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="随便记点什么", raw_text="记得联系李总"
    )

    result = await classifier.classify(event)

    assert result.method == "llm"
    assert result.scope == InputScope.FOLLOWUP
    assert result.confidence == 0.88
    mock_llm.call_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_event_type_falls_back_to_llm():
    """Unrecognized event_type has low confidence (0.50), triggers LLM fallback."""
    llm_response = {
        "scope": "meeting",
        "confidence": 0.82,
        "evidence": "Content describes a meeting",
    }
    mock_llm = _make_llm_client(json_return=llm_response)
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="custom_type", source="api", title="某次活动记录"
    )

    result = await classifier.classify(event)

    assert result.method == "llm"
    mock_llm.call_json.assert_awaited_once()


# ── Test 8: LLM 返回无效 JSON 时的降级处理 ─────────────────────


@pytest.mark.asyncio
async def test_llm_invalid_json_graceful_degradation():
    """When LLM raises exception (invalid JSON), returns UNKNOWN with low confidence."""
    mock_llm = _make_llm_client()
    mock_llm.call_json = AsyncMock(side_effect=Exception("Invalid JSON response"))
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="需要LLM判断的事件"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.UNKNOWN
    assert result.confidence <= 0.35
    assert result.method == "llm"
    assert "failed" in result.evidence.lower() or "error" in result.evidence.lower()


@pytest.mark.asyncio
async def test_llm_malformed_response_degradation():
    """When LLM response is missing required fields, degrades gracefully."""
    mock_llm = _make_llm_client(json_return={"wrong_key": "value"})
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="需要LLM判断的事件"
    )

    result = await classifier.classify(event)

    # Should not crash; scope defaults to UNKNOWN or MANUAL, confidence clamped
    assert isinstance(result.scope, InputScope)
    assert 0.0 <= result.confidence <= 1.0


# ── Test 9: 空 title 事件的默认处理 ─────────────────────────────


@pytest.mark.asyncio
async def test_empty_title_manual_event():
    """Manual event with empty title and generic source → MANUAL with default handling."""
    mock_llm = _make_llm_client(json_return={
        "scope": "manual",
        "confidence": 0.60,
        "evidence": "No clear indicators found",
    })
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="", raw_text=""
    )

    result = await classifier.classify(event)

    # Empty title won't match keywords → low confidence rule → LLM fallback
    assert result.method == "llm"  # Falls back to LLM since rule conf is 0.70 < 0.85


@pytest.mark.asyncio
async def test_empty_title_card_save_still_works():
    """Card save with empty title still classifies by event_type rule."""
    classifier = _make_classifier()
    event = _make_event(
        event_type="card_save", source="wechat_scan", title=""
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.CARD_SCAN
    assert result.method == "rule"


# ── Test 10: confidence 范围校验 (0.0-1.0) ──────────────────────


@pytest.mark.asyncio
async def test_confidence_clamped_to_valid_range():
    """LLM returning out-of-range confidence values gets clamped to [0, 1]."""
    for bad_value, expected in [(-0.5, 0.0), (1.5, 1.0), (999, 1.0), (-100, 0.0)]:
        mock_llm = _make_llm_client(json_return={
            "scope": "manual",
            "confidence": bad_value,
            "evidence": "test",
        })
        classifier = _make_classifier(mock_llm)
        event = _make_event(event_type="manual", source="web", title="test")

        result = await classifier.classify(event)

        assert result.confidence == expected, (
            f"Confidence {bad_value} should be clamped to {expected}, got {result.confidence}"
        )


@pytest.mark.asyncio
async def test_all_rule_results_have_valid_confidence():
    """All rule-based results have confidence in [0, 1]."""
    classifier = _make_classifier()

    test_cases = [
        ("card_save", "wechat_scan", "扫描"),
        ("card_save", "other", "扫描"),
        ("meeting", "calendar", "会议"),
        ("meeting", "other", "会议"),
        ("call", "phone", "通话"),
        ("call", "other", "通话"),
        ("manual", "followup_reminder", "跟进"),
        ("manual", "voice_input", "语音"),
        ("manual", "reflection_note", "复盘"),
        ("manual", "web", "跟进提醒"),   # keyword match
        ("manual", "web", "随便写点"),   # no keyword → default manual
        ("unknown_type", "api", "未知"),  # unknown type
    ]

    for et, src, title in test_cases:
        event = _make_event(event_type=et, source=src, title=title)
        result = await classifier.classify(event)
        assert 0.0 <= result.confidence <= 1.0, (
            f"Invalid confidence {result.confidence} for ({et}, {src}, {title})"
        )


# ── Additional: 关键词匹配测试 ─────────────────────────────────


@pytest.mark.asyncio
async def test_keyword_matching_followup():
    """Title containing '跟进' keyword on manual event → keyword rule matches first, then LLM confirms."""
    llm_response = {
        "scope": "followup",
        "confidence": 0.90,
        "evidence": "LLM confirms follow-up intent",
    }
    mock_llm = _make_llm_client(json_return=llm_response)
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="跟进李总的合作方案"
    )

    result = await classifier.classify(event)

    # Keyword rule gives 0.80 < 0.85 → falls back to LLM → LLM returns followup
    assert result.scope == InputScope.FOLLOWUP
    assert result.method == "llm"


@pytest.mark.asyncio
async def test_keyword_matching_reflection():
    """Title containing '复盘' keyword → keyword rule matches, LLM confirms REFLECTION."""
    llm_response = {
        "scope": "reflection",
        "confidence": 0.92,
        "evidence": "LLM confirms reflection intent",
    }
    mock_llm = _make_llm_client(json_return=llm_response)
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="Q3季度复盘总结"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.REFLECTION


@pytest.mark.asyncio
async def test_reflection_note_source_direct_match():
    """manual + reflection_note source → REFLECTION with high confidence (no LLM)."""
    mock_llm = _make_llm_client()
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="reflection_note", title="本周工作回顾"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.REFLECTION
    assert result.confidence == 0.90
    assert result.method == "rule"
    mock_llm.call_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_invalid_scope_defaults_to_unknown():
    """LLM returning unrecognized scope string defaults to UNKNOWN."""
    mock_llm = _make_llm_client(json_return={
        "scope": "nonexistent_scope",
        "confidence": 0.9,
        "evidence": "bad classification",
    })
    classifier = _make_classifier(mock_llm)
    event = _make_event(
        event_type="manual", source="web", title="需要LLM判断"
    )

    result = await classifier.classify(event)

    assert result.scope == InputScope.UNKNOWN
    assert "invalid scope" in result.evidence.lower() or "defaulted" in result.evidence.lower()

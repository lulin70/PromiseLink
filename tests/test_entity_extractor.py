"""Tests for Entity Extractor — LLM-based entity extraction from event raw text."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.entity_extractor import (
    EntityExtractor,
    ExtractedPerson,
    ExtractionResult,
)
from promiselink.services.entity_resolution import (
    EntityResolutionEngine,
    ResolutionAction,
    ResolutionResult,
)
from promiselink.services.llm_client import LLMClient
from tests.conftest import create_test_event, make_user_id

# ── Mock Data ──

CARD_RESPONSE = {
    "name": "张三",
    "company": "智源AI",
    "title": "CEO",
    "phone": "13812345678",
    "email": "zhangsan@zhiyuan.com",
    "city": "北京",
    "resource": ["AI算法专家"],
    "demand": [],
    "industry": "人工智能",
    "confidence": 0.95,
    "is_ai_inference": True,
    "confidence_level": "inferred",
    "requires_confirmation": True,
}

CONVERSATION_RESPONSE = {
    "persons": [
        {
            "name": "李总",
            "company": "盛恒资本",
            "title": "投资总监",
            "resource": ["投资渠道"],
            "demand": ["AI项目"],
        },
        {
            "name": "王明",
            "company": None,
            "title": None,
            "resource": ["推荐3个AI项目"],
            "demand": [],
        },
    ],
    "events": [{"name": "投资对接会", "time": "下周三", "location": "国贸", "topic": "AI项目路演"}],
    "keywords": ["AI投资", "早期项目"],
    "summary": "李总寻找AI项目，王明推荐了3个项目",
    "is_ai_inference": False,
    "confidence_level": "confirmed",
    "requires_confirmation": False,
}


def _make_llm_client(json_return=None, call_return=None) -> MagicMock:
    """Create a mock LLMClient with configurable responses."""
    mock = MagicMock(spec=LLMClient)
    mock.call_json = AsyncMock(return_value=json_return)
    mock.call = AsyncMock(return_value=call_return)
    return mock


def _make_event(
    event_type: str = "card_save",
    raw_text: str = "张三 CEO 智源AI",
    user_id: str | None = None,
) -> Event:
    """Create an Event instance for testing (SQLite-compatible string IDs)."""
    uid = user_id or make_user_id()
    return Event(
        id=str(uuid.uuid4()),
        user_id=uid,
        event_type=event_type,
        source="test",
        title="Test Event",
        raw_text=raw_text,
        status="pending",
    )


def _make_resolution_engine(
    action: ResolutionAction = ResolutionAction.CREATE,
    target_entity: Entity | None = None,
    confidence: float = 0.0,
) -> MagicMock:
    """Create a mock EntityResolutionEngine."""
    mock = MagicMock(spec=EntityResolutionEngine)
    mock.resolve = AsyncMock(
        return_value=ResolutionResult(
            action=action,
            target_entity=target_entity,
            confidence=confidence,
            matched_step="test",
            matched_fields={},
            explanation="test",
        )
    )
    mock.merge_entity = AsyncMock()
    return mock


async def _create_entity_with_str_id(
    session, user_id: str, data: dict, status: str = "confirmed"
) -> Entity:
    """Helper to create an Entity with string IDs (SQLite-compatible).

    Creates a test Event first to satisfy the source_event_id FK constraint.
    """
    evt = await create_test_event(session, user_id=user_id)
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=data["name"],
        canonical_name=data.get("canonical_name", data["name"]),
        entity_type=data.get("entity_type", "person"),
        properties=data.get("properties", {}),
        aliases=data.get("aliases", []),
        source_event_id=data.get("source_event_id", evt.id),
        confidence=data.get("confidence", 1.0),
        status=status,
    )
    session.add(entity)
    return entity


# ── Tests: _extract_card ──


class TestExtractCard:
    """Test _extract_card (Template 1 — business card extraction)."""

    @pytest.mark.asyncio
    async def test_extract_card_success(self, db_session):
        """Card extraction returns ExtractionResult with single person."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        result = await extractor._extract_card("张三 CEO 智源AI 13812345678")

        assert isinstance(result, ExtractionResult)
        assert len(result.persons) == 1
        person = result.persons[0]
        assert person.name == "张三"
        assert person.company == "智源AI"
        assert person.title == "CEO"
        assert person.phone == "13812345678"
        assert person.email == "zhangsan@zhiyuan.com"
        assert person.city == "北京"
        assert person.resource == ["AI算法专家"]
        assert person.demand == []
        assert person.industry == "人工智能"
        assert person.confidence == 0.95
        assert person.is_ai_inference is True
        assert person.confidence_level == "inferred"
        assert person.requires_confirmation is True

    @pytest.mark.asyncio
    async def test_extract_card_calls_llm_with_sanitized_text(self, db_session):
        """_extract_card should sanitize input before calling LLM."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        # Text with code fences should be sanitized
        await extractor._extract_card("```some text```")

        # Verify call_json was called
        llm.call_json.assert_called_once()
        call_kwargs = llm.call_json.call_args
        prompt = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get("prompt") or call_kwargs[0][0]
        # Code fences should be removed from the prompt
        assert "```" not in prompt or "ocr_text" in prompt


# ── Tests: _extract_conversation ──


class TestExtractConversation:
    """Test _extract_conversation (Template 2 — conversation extraction)."""

    @pytest.mark.asyncio
    async def test_extract_conversation_success(self, db_session):
        """Conversation extraction returns ExtractionResult with multiple persons."""
        llm = _make_llm_client(json_return=CONVERSATION_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        result = await extractor._extract_conversation(
            "李总说他最近在看AI项目，王明推荐了3个", language="zh-CN"
        )

        assert isinstance(result, ExtractionResult)
        assert len(result.persons) == 2
        assert result.persons[0].name == "李总"
        assert result.persons[0].company == "盛恒资本"
        assert result.persons[0].title == "投资总监"
        assert result.persons[0].resource == ["投资渠道"]
        assert result.persons[0].demand == ["AI项目"]
        assert result.persons[1].name == "王明"
        assert result.persons[1].company is None
        assert result.persons[1].title is None
        assert result.keywords == ["AI投资", "早期项目"]
        assert result.summary == "李总寻找AI项目，王明推荐了3个项目"
        assert len(result.events) == 1
        assert result.events[0]["name"] == "投资对接会"
        assert result.is_ai_inference is False
        assert result.confidence_level == "confirmed"
        assert result.requires_confirmation is False


# ── Tests: extract_from_event ──


class TestExtractFromEvent:
    """Test extract_from_event — top-level orchestration."""

    @pytest.mark.asyncio
    async def test_extract_from_event_card_save(self, db_session):
        """card_save event triggers _extract_card path."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        resolution_engine = _make_resolution_engine(action=ResolutionAction.CREATE)
        extractor = EntityExtractor(llm, db_session, resolution_engine)

        event = _make_event(event_type="card_save", raw_text="张三 CEO 智源AI")
        result = await extractor.extract_from_event(event)

        assert len(result.persons) == 1
        assert result.persons[0].name == "张三"

    @pytest.mark.asyncio
    async def test_extract_from_event_meeting(self, db_session):
        """meeting event triggers _extract_conversation path."""
        llm = _make_llm_client(json_return=CONVERSATION_RESPONSE)
        resolution_engine = _make_resolution_engine(action=ResolutionAction.CREATE)
        extractor = EntityExtractor(llm, db_session, resolution_engine)

        event = _make_event(event_type="meeting", raw_text="李总说他最近在看AI项目")
        result = await extractor.extract_from_event(event)

        assert len(result.persons) == 2
        assert result.persons[0].name == "李总"

    @pytest.mark.asyncio
    async def test_extract_from_event_empty_raw_text(self, db_session):
        """Empty raw_text returns empty ExtractionResult."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        event = _make_event(event_type="card_save", raw_text="")
        result = await extractor.extract_from_event(event)

        assert result.persons == []
        llm.call_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_from_event_none_raw_text(self, db_session):
        """None raw_text returns empty ExtractionResult."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        event = _make_event(event_type="card_save", raw_text=None)
        event.raw_text = None
        result = await extractor.extract_from_event(event)

        assert result.persons == []
        llm.call_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_from_event_whitespace_only_raw_text(self, db_session):
        """Whitespace-only raw_text returns empty ExtractionResult."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        event = _make_event(event_type="card_save", raw_text="   \n\t  ")
        result = await extractor.extract_from_event(event)

        assert result.persons == []
        llm.call_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_from_event_unknown_type(self, db_session):
        """Unknown event_type returns empty ExtractionResult without calling LLM."""
        llm = _make_llm_client(json_return=CARD_RESPONSE)
        extractor = EntityExtractor(llm, db_session)

        event = _make_event(event_type="unknown_type", raw_text="some text")
        result = await extractor.extract_from_event(event)

        assert result.persons == []
        llm.call_json.assert_not_called()


# ── Tests: _resolve_and_persist ──


class TestResolveAndPersist:
    """Test _resolve_and_persist — entity resolution + persistence.

    Uses mock session to avoid SQLite UUID binding issues.
    """

    @pytest.mark.asyncio
    async def test_resolve_and_persist_create_new(self, db_session):
        """CREATE action creates a new confirmed entity."""
        llm = _make_llm_client()
        resolution_engine = _make_resolution_engine(action=ResolutionAction.CREATE)

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        extractor = EntityExtractor(llm, mock_session, resolution_engine)

        person = ExtractedPerson(
            name="张三",
            company="智源AI",
            title="CEO",
            confidence=0.9,
            requires_confirmation=False,
        )
        user_id = make_user_id()
        event_id = str(uuid.uuid4())

        entity = await extractor._resolve_and_persist(person, user_id, event_id)

        assert isinstance(entity, Entity)
        assert entity.name == "张三"
        assert entity.status == "confirmed"
        assert entity.user_id == user_id
        assert entity.source_event_id == event_id
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_and_persist_merge_existing(self, db_session):
        """MERGE action merges into existing entity."""
        llm = _make_llm_client()

        user_id = make_user_id()
        existing_entity = await _create_entity_with_str_id(
            db_session,
            user_id,
            {"name": "张三", "properties": {"basic": {"company": "旧公司"}}},
        )
        await db_session.flush()

        merged_entity = existing_entity
        resolution_engine = _make_resolution_engine(
            action=ResolutionAction.MERGE,
            target_entity=existing_entity,
            confidence=0.95,
        )
        resolution_engine.merge_entity = AsyncMock(return_value=merged_entity)

        mock_session = MagicMock()
        extractor = EntityExtractor(llm, mock_session, resolution_engine)

        person = ExtractedPerson(name="张三", company="智源AI", confidence=0.95)
        entity = await extractor._resolve_and_persist(person, user_id, str(uuid.uuid4()))

        resolution_engine.merge_entity.assert_called_once()
        assert entity == merged_entity

    @pytest.mark.asyncio
    async def test_resolve_and_persist_confirm_provisional(self, db_session):
        """CONFIRM action creates a provisional entity."""
        llm = _make_llm_client()

        user_id = make_user_id()
        existing_entity = await _create_entity_with_str_id(
            db_session, user_id, {"name": "张三", "confidence": 0.7}
        )

        resolution_engine = _make_resolution_engine(
            action=ResolutionAction.CONFIRM,
            target_entity=existing_entity,
            confidence=0.75,
        )

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        extractor = EntityExtractor(llm, mock_session, resolution_engine)

        person = ExtractedPerson(name="张三", company="智源AI", confidence=0.75)
        entity = await extractor._resolve_and_persist(person, user_id, str(uuid.uuid4()))

        assert entity.status == "provisional"

    @pytest.mark.asyncio
    async def test_resolve_and_persist_no_engine_creates_confirmed(self, db_session):
        """Without resolution engine, creates confirmed entity when requires_confirmation=False."""
        llm = _make_llm_client()

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        extractor = EntityExtractor(llm, mock_session, resolution_engine=None)

        person = ExtractedPerson(
            name="李四", confidence=0.9, requires_confirmation=False
        )
        user_id = make_user_id()
        event_id = str(uuid.uuid4())

        entity = await extractor._resolve_and_persist(person, user_id, event_id)

        assert entity.status == "confirmed"

    @pytest.mark.asyncio
    async def test_resolve_and_persist_no_engine_provisional_when_requires(self, db_session):
        """Without resolution engine, creates provisional entity when requires_confirmation=True."""
        llm = _make_llm_client()

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        extractor = EntityExtractor(llm, mock_session, resolution_engine=None)

        person = ExtractedPerson(
            name="李四", confidence=0.6, requires_confirmation=True
        )
        user_id = make_user_id()
        event_id = str(uuid.uuid4())

        entity = await extractor._resolve_and_persist(person, user_id, event_id)

        assert entity.status == "provisional"


# ── Tests: sanitize_llm_input ──


class TestSanitizeInput:
    """Test sanitize_llm_input — input sanitization."""

    def test_sanitize_input_truncation(self):
        """Text exceeding max_len is truncated."""
        from promiselink.core.text_utils import sanitize_llm_input
        long_text = "a" * 15000
        result = sanitize_llm_input(long_text, max_len=10000)
        assert len(result) == 10000

    def test_sanitize_input_removes_code_fences(self):
        """Markdown code fences are removed."""
        from promiselink.core.text_utils import sanitize_llm_input
        text = "some text ```python\nprint('hello')\n``` more text"
        result = sanitize_llm_input(text)
        assert "```" not in result
        assert "some text" in result
        assert "more text" in result

    def test_sanitize_input_strips_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        from promiselink.core.text_utils import sanitize_llm_input
        text = "  hello world  "
        result = sanitize_llm_input(text)
        assert result == "hello world"

    def test_sanitize_input_short_text_unchanged(self):
        """Short text within limit is unchanged (except stripping)."""
        from promiselink.core.text_utils import sanitize_llm_input
        text = "hello world"
        result = sanitize_llm_input(text)
        assert result == "hello world"


# ── Tests: _detect_language ──


class TestDetectLanguage:
    """Test _detect_language — language detection heuristic."""

    def test_detect_language_chinese(self):
        """Chinese-dominant text returns zh-CN."""
        text = "这是一个中文的测试文本，包含很多汉字"
        result = EntityExtractor._detect_language(text)
        assert result == "zh-CN"

    def test_detect_language_english(self):
        """English-dominant text returns en-US."""
        text = "This is an English test text with some words"
        result = EntityExtractor._detect_language(text)
        assert result == "en-US"

    def test_detect_language_empty_text(self):
        """Empty text defaults to zh-CN."""
        result = EntityExtractor._detect_language("")
        assert result == "zh-CN"

    def test_detect_language_mixed_mostly_chinese(self):
        """Mixed text with >30% CJK returns zh-CN."""
        text = "今天meeting讨论了project的进展"
        result = EntityExtractor._detect_language(text)
        assert result == "zh-CN"

    def test_detect_language_mixed_mostly_english(self):
        """Mixed text with <30% CJK returns en-US."""
        text = "We discussed the 项目 briefly during the meeting"
        result = EntityExtractor._detect_language(text)
        assert result == "en-US"

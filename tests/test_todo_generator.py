"""Tests for Todo Generator — LLM-based todo generation from events."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from eventlink.core.exceptions import InvalidTodoTypeError
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.llm_client import LLMClient
from eventlink.services.todo_generator import (
    DUE_DATE_OFFSETS,
    PRIORITY_MAP,
    VALID_TODO_TYPES,
    GeneratedTodo,
    TodoGenerator,
)
from tests.conftest import make_user_id

# ── Mock Data ──

PROMISE_RESPONSE = json.dumps({
    "promises": [
        {
            "to_person": "李总",
            "content": "下周一前发送AI项目资料",
            "mentioned_deadline": "下周一",
            "suggested_deadline": "2026-06-09T00:00:00Z",
            "priority": "high",
            "source_text": "我说好下周一前把AI项目的资料发给您",
        }
    ],
    "summary": "1项承诺：给李总发资料",
    "is_ai_inference": False,
    "confidence_level": "confirmed",
    "requires_confirmation": False,
})

CARE_RESPONSE = json.dumps({
    "cares": [
        {
            "person": "李总",
            "topic": "AI项目投资评估",
            "detail": "正在寻找AI赛道优质早期项目",
            "urgency": "high",
            "source_text": "李总说他最近一直在看AI赛道的项目",
        }
    ],
    "summary": "1个关注点：李总关注AI投资",
    "is_ai_inference": False,
    "confidence_level": "confirmed",
    "requires_confirmation": False,
})

TYPED_TODO_RESPONSE = json.dumps({
    "todo_type": "cooperation_signal",
    "description": "李总与用户在AI投资领域有合作可能",
    "priority": "medium",
    "due_date_suggestion": "2026-06-06T00:00:00Z",
    "context": {
        "reason": "双方资源互补",
        "suggested_action": "安排一次深度沟通",
        "related_entities": ["李总"],
    },
    "is_ai_inference": True,
    "confidence_level": "inferred",
    "requires_confirmation": False,
})


def _make_llm_client(call_return: str | None = None) -> MagicMock:
    """Create a mock LLMClient with configurable call response."""
    mock = MagicMock(spec=LLMClient)
    mock.call = AsyncMock(return_value=call_return or "")
    mock.call_json = AsyncMock(return_value={})
    return mock


def _make_event(
    event_type: str = "meeting",
    raw_text: str = "我说好下周一前把AI项目的资料发给您",
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


def _make_entity(
    name: str = "李总",
    company: str = "盛恒资本",
    title: str = "投资总监",
    user_id: str | None = None,
) -> Entity:
    """Create an Entity instance for testing."""
    uid = user_id or make_user_id()
    return Entity(
        id=str(uuid.uuid4()),
        user_id=uid,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=[],
        properties={
            "basic": {
                "company": company,
                "title": title,
            }
        },
        source_event_id=str(uuid.uuid4()),
        confidence=0.9,
        status="confirmed",
    )


def _make_todo_from_generated(
    gen: GeneratedTodo, user_id: str, event_id: str
) -> Todo:
    """Create a Todo from a GeneratedTodo (with string IDs for SQLite)."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=gen.todo_type,
        title=gen.title,
        description=gen.description,
        priority=gen.priority,
        status="pending",
        due_date=gen.due_date,
        source_event_id=event_id,
        properties={
            **(gen.properties or {}),
            "is_ai_inference": gen.is_ai_inference,
            "confidence_level": gen.confidence_level,
            "requires_confirmation": gen.requires_confirmation,
        },
    )


# ── Tests: Constants ──


class TestConstants:
    """Test PRIORITY_MAP, DUE_DATE_OFFSETS, VALID_TODO_TYPES constants."""

    def test_priority_map_values(self):
        """PRIORITY_MAP maps string priorities to int values (1=highest, 5=lowest)."""
        assert PRIORITY_MAP["high"] == 1
        assert PRIORITY_MAP["medium"] == 3
        assert PRIORITY_MAP["low"] == 5

    def test_due_date_offsets_keys_match_valid_types(self):
        """DUE_DATE_OFFSETS keys should be a subset of VALID_TODO_TYPES."""
        for key in DUE_DATE_OFFSETS:
            assert key in VALID_TODO_TYPES

    def test_valid_todo_types_count(self):
        """There should be exactly 6 valid todo types."""
        assert len(VALID_TODO_TYPES) == 6
        assert "promise" in VALID_TODO_TYPES
        assert "help" in VALID_TODO_TYPES
        assert "care" in VALID_TODO_TYPES
        assert "followup" in VALID_TODO_TYPES
        assert "cooperation_signal" in VALID_TODO_TYPES
        assert "risk" in VALID_TODO_TYPES


# ── Tests: _format_persons ──


class TestFormatPersons:
    """Test _format_persons — entity list formatting for LLM prompts."""

    def test_format_persons_with_entities(self):
        """Entities with basic info are formatted correctly."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())

        entities = [_make_entity(name="李总", company="盛恒资本", title="投资总监")]
        result = generator._format_persons(entities)

        assert "李总" in result
        assert "盛恒资本" in result
        assert "投资总监" in result

    def test_format_persons_empty_list(self):
        """Empty entity list returns '无'."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())

        result = generator._format_persons([])
        assert result == "无"

    def test_format_persons_multiple_entities(self):
        """Multiple entities are formatted with one per line."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())

        entities = [
            _make_entity(name="李总", company="盛恒资本", title="投资总监"),
            _make_entity(name="王明", company="技术公司", title="CTO"),
        ]
        result = generator._format_persons(entities)

        lines = result.strip().split("\n")
        assert len(lines) == 2


# ── Tests: sanitize_llm_input ──


class TestSanitizeInput:
    """Test sanitize_llm_input — input sanitization."""

    def test_sanitize_input_truncation(self):
        """Text exceeding max_len is truncated."""
        from eventlink.core.text_utils import sanitize_llm_input
        long_text = "a" * 10000
        result = sanitize_llm_input(long_text, max_len=8000)
        assert len(result) == 8000

    def test_sanitize_input_removes_null_chars(self):
        """Null characters and replacement characters are removed."""
        from eventlink.core.text_utils import sanitize_llm_input
        text = "hello\x00world\ufffdtest"
        result = sanitize_llm_input(text)
        assert "\x00" not in result
        assert "\ufffd" not in result
        assert "hello" in result
        assert "world" in result
        assert "test" in result

    def test_sanitize_input_empty_string(self):
        """Empty string returns empty string."""
        from eventlink.core.text_utils import sanitize_llm_input
        result = sanitize_llm_input("")
        assert result == ""

    def test_sanitize_input_none_like_empty(self):
        """Falsy empty string returns empty string."""
        from eventlink.core.text_utils import sanitize_llm_input
        result = sanitize_llm_input("")
        assert result == ""


# ── Tests: _parse_due_date ──


class TestParseDueDate:
    """Test _parse_due_date — ISO 8601 date parsing."""

    def test_parse_due_date_iso_format(self):
        """Standard ISO 8601 format is parsed correctly."""
        result = TodoGenerator._parse_due_date("2026-06-09T00:00:00+08:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 9

    def test_parse_due_date_with_z_suffix(self):
        """Z suffix (UTC) is handled correctly."""
        result = TodoGenerator._parse_due_date("2026-06-09T00:00:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 9
        assert result.tzinfo is not None

    def test_parse_due_date_invalid_returns_none(self):
        """Invalid date string returns None."""
        result = TodoGenerator._parse_due_date("not-a-date")
        assert result is None

    def test_parse_due_date_none_returns_none(self):
        """None input returns None."""
        result = TodoGenerator._parse_due_date(None)
        assert result is None

    def test_parse_due_date_empty_string_returns_none(self):
        """Empty string returns None."""
        result = TodoGenerator._parse_due_date("")
        assert result is None

    def test_parse_due_date_date_only(self):
        """Date-only format (no time) is parsed correctly."""
        result = TodoGenerator._parse_due_date("2026-06-09")
        assert result is not None
        assert result.year == 2026
        assert result.month == 6
        assert result.day == 9


# ── Tests: _extract_promises ──


class TestExtractPromises:
    """Test _extract_promises (Template 11)."""

    @pytest.mark.asyncio
    async def test_extract_promises_success(self, db_session):
        """Promise extraction returns GeneratedTodo list from LLM response."""
        llm = _make_llm_client(call_return=PROMISE_RESPONSE)
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_promises(
            "我说好下周一前把AI项目的资料发给您", "李总: 投资总监 @ 盛恒资本"
        )

        assert len(result) == 1
        todo = result[0]
        assert todo.todo_type == "promise"
        assert "承诺" in todo.title
        assert "李总" in todo.title
        assert todo.priority == PRIORITY_MAP["high"]
        assert todo.due_date is not None
        assert todo.properties["to_person"] == "李总"
        assert todo.is_ai_inference is False
        assert todo.confidence_level == "confirmed"

    @pytest.mark.asyncio
    async def test_extract_promises_empty_array(self, db_session):
        """Empty promises array returns empty list."""
        empty_response = json.dumps({
            "promises": [],
            "summary": "无承诺",
            "is_ai_inference": False,
            "confidence_level": "confirmed",
            "requires_confirmation": False,
        })
        llm = _make_llm_client(call_return=empty_response)
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_promises("some text", "无")

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_promises_invalid_json(self, db_session):
        """Invalid JSON from LLM returns empty list gracefully."""
        llm = _make_llm_client(call_return="not valid json {{{")
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_promises("some text", "无")

        assert result == []

    @pytest.mark.asyncio
    async def test_extract_promises_no_deadline_uses_default(self, db_session):
        """When suggested_deadline is missing, default offset is used."""
        response = json.dumps({
            "promises": [
                {
                    "to_person": "王总",
                    "content": "发送项目介绍",
                    "mentioned_deadline": None,
                    "suggested_deadline": None,
                    "priority": "medium",
                    "source_text": "我答应发资料",
                }
            ],
            "summary": "1项承诺",
            "is_ai_inference": False,
            "confidence_level": "confirmed",
            "requires_confirmation": False,
        })
        llm = _make_llm_client(call_return=response)
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_promises("some text", "无")

        assert len(result) == 1
        assert result[0].due_date is not None
        # Due date should be approximately 3 days from now
        now = datetime.now(UTC)
        expected = now + timedelta(days=DUE_DATE_OFFSETS["promise"])
        assert abs((result[0].due_date - expected).total_seconds()) < 10


# ── Tests: _extract_cares ──


class TestExtractCares:
    """Test _extract_cares (Template 12)."""

    @pytest.mark.asyncio
    async def test_extract_cares_success(self, db_session):
        """Care extraction returns GeneratedTodo list from LLM response."""
        llm = _make_llm_client(call_return=CARE_RESPONSE)
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_cares(
            "李总说他最近一直在看AI赛道的项目", "李总: 投资总监 @ 盛恒资本"
        )

        assert len(result) == 1
        todo = result[0]
        assert todo.todo_type == "care"
        assert "关注" in todo.title
        assert "李总" in todo.title
        assert todo.priority == PRIORITY_MAP["high"]
        assert todo.properties["person"] == "李总"
        assert todo.properties["topic"] == "AI项目投资评估"

    @pytest.mark.asyncio
    async def test_extract_cares_empty_array(self, db_session):
        """Empty cares array returns empty list."""
        empty_response = json.dumps({
            "cares": [],
            "summary": "无关注点",
            "is_ai_inference": False,
            "confidence_level": "confirmed",
            "requires_confirmation": False,
        })
        llm = _make_llm_client(call_return=empty_response)
        generator = TodoGenerator(llm, db_session)

        result = await generator._extract_cares("some text", "无")

        assert result == []


# ── Tests: _generate_typed_todo ──


class TestGenerateTypedTodo:
    """Test _generate_typed_todo (Template 3)."""

    @pytest.mark.asyncio
    async def test_generate_typed_todo_success(self, db_session):
        """Typed todo generation returns GeneratedTodo from LLM response."""
        llm = _make_llm_client(call_return=TYPED_TODO_RESPONSE)
        generator = TodoGenerator(llm, db_session)

        result = await generator._generate_typed_todo(
            todo_type="cooperation_signal",
            conversation="李总对AI项目很感兴趣",
            persons="李总: 投资总监 @ 盛恒资本",
            user_context="AI领域创业者",
        )

        assert result is not None
        assert result.todo_type == "cooperation_signal"
        assert "合作信号" in result.title
        assert result.priority == PRIORITY_MAP["medium"]
        assert result.due_date is not None

    @pytest.mark.asyncio
    async def test_generate_typed_todo_invalid_type_raises(self, db_session):
        """Invalid todo_type raises InvalidTodoTypeError."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        with pytest.raises(InvalidTodoTypeError):
            await generator._generate_typed_todo(
                todo_type="invalid_type",
                conversation="some text",
                persons="无",
            )

    @pytest.mark.asyncio
    async def test_generate_typed_todo_invalid_json_returns_none(self, db_session):
        """Invalid JSON from LLM returns None gracefully."""
        llm = _make_llm_client(call_return="not json")
        generator = TodoGenerator(llm, db_session)

        result = await generator._generate_typed_todo(
            todo_type="risk",
            conversation="some text",
            persons="无",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_generate_typed_todo_empty_description_returns_none(self, db_session):
        """Empty description in LLM response returns None."""
        empty_desc_response = json.dumps({
            "todo_type": "risk",
            "description": "",
            "priority": "high",
        })
        llm = _make_llm_client(call_return=empty_desc_response)
        generator = TodoGenerator(llm, db_session)

        result = await generator._generate_typed_todo(
            todo_type="risk",
            conversation="some text",
            persons="无",
        )

        assert result is None


# ── Tests: generate_todos (integration) ──


class TestGenerateTodos:
    """Test generate_todos — top-level orchestration with mocked sub-methods.

    Uses mock _persist_todo to avoid SQLite UUID binding issues.
    """

    @pytest.mark.asyncio
    async def test_generate_todos_meeting_event(self, db_session):
        """meeting event: promise + care + cooperation_signal + risk.

        F-46: Deduplication applies per-event cap (max 3) and similarity check,
        so result may be <= 4. High-priority todos are preserved.
        """
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        # Mock sub-methods
        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="兑现承诺: 发送AI项目资料",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="关注: 李总 — AI项目投资评估",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )
        coop_todo = GeneratedTodo(
            todo_type="cooperation_signal",
            title="[合作信号] 双方资源互补",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        risk_todo = GeneratedTodo(
            todo_type="risk",
            title="[风险预警] 竞争风险",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=1),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])
        generator._generate_typed_todo = AsyncMock(
            side_effect=[coop_todo, risk_todo]
        )

        event = _make_event(event_type="meeting", raw_text="讨论AI项目合作")
        entities = [_make_entity(name="李总")]

        # Mock _persist_todo to return proper Todo objects
        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        result = await generator.generate_todos(event, entities)

        # F-46: Deduplication caps at MAX_TODOS_PER_EVENT (3) per event
        assert len(result) >= 3  # At least 3 (per-event cap)
        assert len(result) <= 4  # At most original count
        types = [t.todo_type for t in result]
        # Core high-priority types should be preserved
        assert "promise" in types
        assert "risk" in types

    @pytest.mark.asyncio
    async def test_generate_todos_card_save_event(self, db_session):
        """card_save event: promise + care only (no cooperation_signal/risk)."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="兑现承诺: 发送资料",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="关注: 张总 — 项目需求",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])
        generator._generate_typed_todo = AsyncMock(return_value=None)

        event = _make_event(event_type="card_save", raw_text="张总的名片和对话")
        entities = [_make_entity(name="张总")]

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        result = await generator.generate_todos(event, entities)

        assert len(result) == 2
        types = [t.todo_type for t in result]
        assert "promise" in types
        assert "care" in types
        assert "cooperation_signal" not in types
        assert "risk" not in types
        # _generate_typed_todo should NOT be called for card_save
        generator._generate_typed_todo.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_todos_manual_event(self, db_session):
        """manual event: promise + care + followup."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="兑现承诺: 发送资料",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="关注: 王总 — 技术需求",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )
        followup_todo = GeneratedTodo(
            todo_type="followup",
            title="[跟进事项] 确认王总需求",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])
        generator._generate_typed_todo = AsyncMock(return_value=followup_todo)

        event = _make_event(event_type="manual", raw_text="手动记录的对话")
        entities = [_make_entity(name="王总")]

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        result = await generator.generate_todos(event, entities)

        assert len(result) == 3
        types = [t.todo_type for t in result]
        assert "promise" in types
        assert "care" in types
        assert "followup" in types
        # _generate_typed_todo should be called once for followup
        generator._generate_typed_todo.assert_called_once()
        call_kwargs = generator._generate_typed_todo.call_args
        assert call_kwargs.kwargs.get("todo_type") == "followup" or call_kwargs[1].get("todo_type") == "followup"

    @pytest.mark.asyncio
    async def test_generate_todos_empty_conversation(self, db_session):
        """Empty conversation returns empty list."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        event = _make_event(event_type="meeting", raw_text="")
        entities = [_make_entity(name="李总")]

        result = await generator.generate_todos(event, entities)

        assert result == []

    @pytest.mark.asyncio
    async def test_generate_todos_none_raw_text(self, db_session):
        """None raw_text returns empty list."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        event = _make_event(event_type="meeting", raw_text=None)
        event.raw_text = None
        entities = [_make_entity(name="李总")]

        result = await generator.generate_todos(event, entities)

        assert result == []

    @pytest.mark.asyncio
    async def test_generate_todos_whitespace_only_raw_text(self, db_session):
        """Whitespace-only raw_text returns empty list."""
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        event = _make_event(event_type="meeting", raw_text="   \n\t  ")
        entities = [_make_entity(name="李总")]

        result = await generator.generate_todos(event, entities)

        assert result == []


# ── Tests: _persist_todo ──


class TestPersistTodo:
    """Test _persist_todo — Todo persistence.

    Uses mock session to avoid SQLite UUID binding issues.
    """

    @pytest.mark.asyncio
    async def test_persist_todo_creates_todo_object(self, db_session):
        """_persist_todo creates a Todo with correct fields."""
        llm = _make_llm_client()

        mock_session = MagicMock()
        mock_session.add = MagicMock()
        mock_session.flush = AsyncMock()

        generator = TodoGenerator(llm, mock_session)

        gen = GeneratedTodo(
            todo_type="promise",
            title="兑现承诺: 发送AI项目资料",
            description="我说好下周一前把AI项目的资料发给您",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
            properties={"to_person": "李总"},
            is_ai_inference=False,
            confidence_level="confirmed",
            requires_confirmation=False,
        )
        user_id = make_user_id()
        event_id = str(uuid.uuid4())

        todo = await generator._persist_todo(gen, user_id, event_id)

        assert isinstance(todo, Todo)
        assert todo.todo_type == "promise"
        assert todo.title == "兑现承诺: 发送AI项目资料"
        assert todo.description == "我说好下周一前把AI项目的资料发给您"
        assert todo.priority == 1
        assert todo.status == "pending"
        assert todo.source_event_id == event_id
        assert todo.user_id == user_id
        assert todo.properties["to_person"] == "李总"
        assert todo.properties["is_ai_inference"] is False
        assert todo.properties["confidence_level"] == "confirmed"
        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()

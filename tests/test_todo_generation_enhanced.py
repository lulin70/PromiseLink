"""Enhanced tests for Todo Generation — covering 8 test gaps (G2-01 through G2-08).

Test coverage by gap:
- G2-01: help type todo never generated (4 event types)
- G2-02: _rule_based_fallback keyword matching (5 tests)
- G2-03: _is_duplicate_todo deduplication logic (3 tests)
- G2-04: call event type integration (1 test)
- G2-05: PriorityScorerV2.score_with_context (3 tests)
- G2-06: conversation truncation at 8000 chars (2 tests)
- G2-07: LLM exception handling (3 tests)
- G2-08: TodoDeduplicator integration with generate_todos (2 tests)

Coverage dimensions:
- Happy Path: ~55% (normal flows)
- Error Case: ~18% (exceptions, invalid input)
- Boundary: ~27% (truncation, empty input, exact thresholds)

Iron Rule: Each test follows Arrange-Act-Assert with precise assertions.
"""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.llm_client import LLMClient
from promiselink.services.priority_scorer import PriorityScorerV2
from promiselink.services.todo_deduplicator import TodoDeduplicator
from promiselink.services.todo_generator import GeneratedTodo, TodoGenerator
from tests.conftest import make_user_id


# ── Helpers ──


def _make_llm_client(
    call_return: str | None = None, call_side_effect=None
) -> MagicMock:
    """Create a mock LLMClient with configurable call behavior."""
    mock = MagicMock(spec=LLMClient)
    if call_side_effect is not None:
        mock.call = AsyncMock(side_effect=call_side_effect)
    else:
        mock.call = AsyncMock(return_value=call_return or "")
    mock.call_json = AsyncMock(return_value={})
    return mock


def _make_event(
    event_type: str = "meeting",
    raw_text: str = "test",
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


def _make_entity(name: str = "李总", user_id: str | None = None) -> Entity:
    """Create an Entity instance for testing."""
    uid = user_id or make_user_id()
    return Entity(
        id=str(uuid.uuid4()),
        user_id=uid,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=[],
        properties={"basic": {"company": "盛恒资本", "title": "投资总监"}},
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


async def _add_existing_todo(
    session,
    user_id: str,
    todo_type: str,
    title: str,
    person: str | None = None,
    priority: int = 3,
    status: str = "pending",
) -> Todo:
    """Add an existing Todo to the DB session for deduplication tests."""
    props: dict = {}
    if person:
        if todo_type == "promise":
            props["to_person"] = person
        else:
            props["person"] = person
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title=title,
        priority=priority,
        status=status,
        source_event_id=str(uuid.uuid4()),
        properties=props,
    )
    session.add(todo)
    await session.flush()
    return todo


# ── G2-02: _rule_based_fallback ──


class TestRuleBasedFallback:
    """G2-02: Test _rule_based_fallback — keyword-based todo generation when LLM returns empty.

    When LLM produces nothing, the fallback scans for keywords:
    - '答应/承诺' → promise todo
    - '担心/焦虑' → care todo
    - '待确认/后续' → followup todo
    """

    def test_promise_keyword_generates_promise_todo(self):
        """Text containing '答应' keyword generates a promise todo."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())
        conversation = "我答应李总明天把项目资料发给他"
        persons = "- 李总: 投资总监 @ 盛恒资本"

        # Act
        result = generator._rule_based_fallback(conversation, persons)

        # Assert
        promise_todos = [t for t in result if t.todo_type == "promise"]
        assert len(promise_todos) == 1
        assert "承诺" in promise_todos[0].title
        assert promise_todos[0].priority == 1
        assert promise_todos[0].requires_confirmation is True
        assert promise_todos[0].properties.get("rule_based_fallback") is True

    def test_care_keyword_generates_care_todo(self):
        """Text containing '担心' keyword generates a care todo."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())
        conversation = "李总担心项目进度跟不上"
        persons = "- 李总: 投资总监 @ 盛恒资本"

        # Act
        result = generator._rule_based_fallback(conversation, persons)

        # Assert
        care_todos = [t for t in result if t.todo_type == "care"]
        assert len(care_todos) == 1
        assert "关注" in care_todos[0].title
        assert care_todos[0].priority == 3
        assert care_todos[0].requires_confirmation is True

    def test_followup_keyword_generates_followup_todo(self):
        """Text containing '待确认' keyword generates a followup todo."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())
        conversation = "这个方案待确认后再推进"
        persons = "- 李总: 投资总监 @ 盛恒资本"

        # Act
        result = generator._rule_based_fallback(conversation, persons)

        # Assert
        followup_todos = [t for t in result if t.todo_type == "followup"]
        assert len(followup_todos) == 1
        assert "跟进" in followup_todos[0].title
        assert followup_todos[0].priority == 3
        assert followup_todos[0].requires_confirmation is True

    def test_all_keywords_generate_three_todos(self):
        """Text containing all three keyword types generates promise + care + followup."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())
        conversation = "我答应发资料。李总担心进度。方案待确认。"
        persons = "- 李总: 投资总监 @ 盛恒资本"

        # Act
        result = generator._rule_based_fallback(conversation, persons)

        # Assert
        types = {t.todo_type for t in result}
        assert types == {"promise", "care", "followup"}
        assert len(result) == 3

    def test_no_keywords_returns_empty_list(self):
        """Text without any keywords returns empty list (boundary case)."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, MagicMock())
        conversation = "今天天气不错，我们聊了聊家常"
        persons = "- 李总: 投资总监 @ 盛恒资本"

        # Act
        result = generator._rule_based_fallback(conversation, persons)

        # Assert
        assert result == []


# ── G2-03: _is_duplicate_todo ──


class TestIsDuplicateTodo:
    """G2-03: Test _is_duplicate_todo — deduplication logic.

    Deduplication criteria:
    1. Same user_id + same todo_type + same target person
    2. Title similarity > 0.6 (Jaccard word overlap)
    """

    @pytest.mark.asyncio
    async def test_same_type_same_person_similar_title_is_duplicate(
        self, db_session
    ):
        """Same type + same person + identical title → duplicate (similarity=1.0)."""
        # Arrange
        user_id = make_user_id()
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        await _add_existing_todo(
            db_session,
            user_id,
            "promise",
            title="[承诺] 李总 — 发送资料",
            person="李总",
        )

        gen = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 李总 — 发送资料",
            properties={"to_person": "李总"},
        )

        # Act
        result = await generator._is_duplicate_todo(gen, user_id)

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_different_person_not_duplicate(self, db_session):
        """Same type + same title but different person → not duplicate."""
        # Arrange
        user_id = make_user_id()
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        await _add_existing_todo(
            db_session,
            user_id,
            "promise",
            title="[承诺] 李总 — 发送资料",
            person="李总",
        )

        gen = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 李总 — 发送资料",
            properties={"to_person": "王总"},
        )

        # Act
        result = await generator._is_duplicate_todo(gen, user_id)

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_no_existing_todos_not_duplicate(self, db_session):
        """No existing todos in DB → not duplicate (boundary case)."""
        # Arrange
        user_id = make_user_id()
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        gen = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 李总 — 发送资料",
            properties={"to_person": "李总"},
        )

        # Act
        result = await generator._is_duplicate_todo(gen, user_id)

        # Assert
        assert result is False


# ── G2-01: help type not generated ──


class TestHelpTypeNotGenerated:
    """G2-01: Verify generate_todos never generates 'help' type todos.

    The generate_todos method only produces: promise, care, cooperation_signal,
    risk, followup. The 'help' type is never generated for any event type.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ["meeting", "call", "manual", "card_save"])
    async def test_no_help_todo_for_any_event_type(self, db_session, event_type):
        """generate_todos does not produce 'help' type todos for any event type."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 发送计划书",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="[关注] 投资偏好",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )
        coop_todo = GeneratedTodo(
            todo_type="cooperation_signal",
            title="[合作信号] 资源互补",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        risk_todo = GeneratedTodo(
            todo_type="risk",
            title="[风险预警] 竞争对手",
            priority=5,
            due_date=datetime.now(UTC) + timedelta(days=1),
        )
        followup_todo = GeneratedTodo(
            todo_type="followup",
            title="[跟进事项] 确认需求",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])

        typed_map = {
            "cooperation_signal": coop_todo,
            "risk": risk_todo,
            "followup": followup_todo,
        }

        async def mock_typed_todo(todo_type, **kwargs):
            return typed_map.get(todo_type)

        generator._generate_typed_todo = AsyncMock(side_effect=mock_typed_todo)

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        event = _make_event(event_type=event_type, raw_text="讨论事项")
        entities = [_make_entity(name="李总")]

        # Act
        result = await generator.generate_todos(event, entities)

        # Assert
        result_types = {t.todo_type for t in result}
        assert "help" not in result_types
        # Verify _generate_typed_todo was never called with todo_type="help"
        for call in generator._generate_typed_todo.call_args_list:
            assert call.kwargs.get("todo_type") != "help"


# ── G2-04: call event integration ──


class TestCallEventIntegration:
    """G2-04: call event should generate promise + care + cooperation_signal + risk.

    Call events are treated identically to meeting events (line 196):
    both trigger cooperation_signal and risk generation in addition to
    the always-on promise and care extraction.
    """

    @pytest.mark.asyncio
    async def test_call_event_generates_four_todo_types(self, db_session):
        """call event triggers promise + care + cooperation_signal + risk generation."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 发送项目计划书",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="[关注] 投资偏好分析",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )
        coop_todo = GeneratedTodo(
            todo_type="cooperation_signal",
            title="[合作信号] 资源互补",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        risk_todo = GeneratedTodo(
            todo_type="risk",
            title="[风险预警] 竞争对手",
            priority=5,
            due_date=datetime.now(UTC) + timedelta(days=1),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])

        typed_map = {
            "cooperation_signal": coop_todo,
            "risk": risk_todo,
        }

        async def mock_typed_todo(todo_type, **kwargs):
            return typed_map.get(todo_type)

        generator._generate_typed_todo = AsyncMock(side_effect=mock_typed_todo)

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        event = _make_event(event_type="call", raw_text="电话讨论AI项目合作")
        entities = [_make_entity(name="李总")]

        # Act
        result = await generator.generate_todos(event, entities)

        # Assert
        # _generate_typed_todo must be called for both cooperation_signal and risk
        called_types = [
            call.kwargs.get("todo_type")
            for call in generator._generate_typed_todo.call_args_list
        ]
        assert "cooperation_signal" in called_types
        assert "risk" in called_types
        assert "help" not in called_types
        assert "followup" not in called_types

        # Result should contain promise and care (high priority, survive per-event cap)
        result_types = {t.todo_type for t in result}
        assert "promise" in result_types
        assert "care" in result_types
        assert "help" not in result_types


# ── G2-05: PriorityScorerV2 ──


class TestPriorityScorerV2:
    """G2-05: Test PriorityScorerV2.score_with_context (used by Step07).

    Step07 (step_07_priority.py) uses PriorityScorerV2.score_with_context to
    compute four-dimensional priority scores: urgency + importance + dependency + context.
    Formula: score = 0.3*urgency + 0.35*importance + 0.2*dependency + 0.15*context
    """

    @pytest.mark.asyncio
    async def test_score_with_context_basic_calculation(self, db_session):
        """score_with_context computes correct four-dimensional score."""
        # Arrange
        scorer = PriorityScorerV2()
        # Mock dependency and context analyzers (avoid DB graph queries)
        scorer.dependency_analyzer = MagicMock()
        scorer.dependency_analyzer.compute_dependency_score = AsyncMock(
            return_value=0.5
        )
        scorer.context_matcher = MagicMock()
        scorer.context_matcher.compute_context_score = AsyncMock(return_value=0.5)

        todo = SimpleNamespace(
            todo_type="promise",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=2),
        )

        # Act
        result = await scorer.score_with_context(todo, db_session)

        # Assert
        # urgency = 0.7 (due in 2 days, <= 3 days threshold)
        # importance = 0.9 (promise type)
        # dependency = 0.5 (mocked)
        # context = 0.5 (mocked)
        # score = 0.3*0.7 + 0.35*0.9 + 0.2*0.5 + 0.15*0.5 = 0.70
        # priority_adj = 0.05 * (3-1)/2 = 0.05
        # final = 0.75
        assert result.score == pytest.approx(0.75, abs=0.01)
        assert result.urgency == pytest.approx(0.7, abs=0.01)
        assert result.importance == pytest.approx(0.9, abs=0.01)
        assert result.breakdown["dependency_raw"] == 0.5
        assert result.breakdown["context_raw"] == 0.5

    @pytest.mark.asyncio
    async def test_score_with_context_always_in_valid_range(self, db_session):
        """score_with_context always returns score in [0.0, 1.0] (boundary test)."""
        # Arrange
        scorer = PriorityScorerV2()
        scorer.dependency_analyzer = MagicMock()
        scorer.context_matcher = MagicMock()

        test_cases = [
            (0.0, 0.0),  # minimum dependency + context
            (1.0, 1.0),  # maximum dependency + context
            (0.3, 0.7),
        ]

        for dep_score, ctx_score in test_cases:
            scorer.dependency_analyzer.compute_dependency_score = AsyncMock(
                return_value=dep_score
            )
            scorer.context_matcher.compute_context_score = AsyncMock(
                return_value=ctx_score
            )

            todo = SimpleNamespace(
                todo_type="risk",
                priority=5,
                due_date=datetime.now(UTC) + timedelta(days=30),
            )

            # Act
            result = await scorer.score_with_context(todo, db_session)

            # Assert
            assert 0.0 <= result.score <= 1.0, (
                f"Score {result.score} out of range for dep={dep_score}, ctx={ctx_score}"
            )

    @pytest.mark.asyncio
    async def test_score_with_context_breakdown_contains_all_dimensions(
        self, db_session
    ):
        """score_with_context breakdown includes all four dimensions + weights."""
        # Arrange
        scorer = PriorityScorerV2()
        scorer.dependency_analyzer = MagicMock()
        scorer.dependency_analyzer.compute_dependency_score = AsyncMock(
            return_value=0.3
        )
        scorer.context_matcher = MagicMock()
        scorer.context_matcher.compute_context_score = AsyncMock(return_value=0.4)

        todo = SimpleNamespace(
            todo_type="care",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=5),
        )

        # Act
        result = await scorer.score_with_context(todo, db_session)

        # Assert
        assert "urgency_raw" in result.breakdown
        assert "importance_raw" in result.breakdown
        assert "dependency_raw" in result.breakdown
        assert "context_raw" in result.breakdown
        assert "weights" in result.breakdown
        assert result.breakdown["weights"]["urgency"] == 0.3
        assert result.breakdown["weights"]["importance"] == 0.35
        assert result.breakdown["weights"]["dependency"] == 0.2
        assert result.breakdown["weights"]["context"] == 0.15


# ── G2-06: conversation truncation ──


class TestConversationTruncation:
    """G2-06: Conversation text > 8000 chars is truncated to 8000.

    The generate_todos method truncates raw_text to 8000 chars before
    passing to LLM extraction methods (line 158-164).
    """

    @pytest.mark.asyncio
    async def test_long_conversation_truncated_to_8000(self, db_session):
        """raw_text > 8000 chars is truncated to exactly 8000 before LLM call."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        captured_conversations: list[str] = []

        async def capture_promise(conv, persons, event_date):
            captured_conversations.append(conv)
            return []

        async def capture_care(conv, persons, event_date):
            captured_conversations.append(conv)
            return []

        generator._extract_promises = AsyncMock(side_effect=capture_promise)
        generator._extract_cares = AsyncMock(side_effect=capture_care)

        long_text = "a" * 10000
        event = _make_event(event_type="card_save", raw_text=long_text)
        entities: list[Entity] = []

        # Act
        await generator.generate_todos(event, entities)

        # Assert
        assert len(captured_conversations) == 2
        for conv in captured_conversations:
            assert len(conv) <= 8000, "Conversation not truncated to 8000"
            assert len(conv) == 8000, "Conversation should be exactly 8000 chars"

    @pytest.mark.asyncio
    async def test_conversation_at_boundary_not_truncated(self, db_session):
        """raw_text exactly 8000 chars is not truncated (boundary case)."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        captured_conversations: list[str] = []

        async def capture_promise(conv, persons, event_date):
            captured_conversations.append(conv)
            return []

        async def capture_care(conv, persons, event_date):
            captured_conversations.append(conv)
            return []

        generator._extract_promises = AsyncMock(side_effect=capture_promise)
        generator._extract_cares = AsyncMock(side_effect=capture_care)

        boundary_text = "b" * 8000
        event = _make_event(event_type="card_save", raw_text=boundary_text)
        entities: list[Entity] = []

        # Act
        await generator.generate_todos(event, entities)

        # Assert
        assert len(captured_conversations) == 2
        for conv in captured_conversations:
            assert len(conv) == 8000, "Boundary text should remain at 8000"


# ── G2-07: LLM exception handling ──


class TestLLMExceptionHandling:
    """G2-07: _extract_promises/_extract_cares return empty list when LLM call raises.

    Both methods wrap LLM calls in try/except (line 324-334, 387-397) and
    return [] on any exception, ensuring LLM failures don't crash the pipeline.
    """

    @pytest.mark.asyncio
    async def test_extract_promises_returns_empty_on_llm_exception(
        self, db_session
    ):
        """_extract_promises returns [] when LLM call raises RuntimeError."""
        # Arrange
        llm = _make_llm_client(call_side_effect=RuntimeError("LLM timeout"))
        generator = TodoGenerator(llm, db_session)

        # Act
        result = await generator._extract_promises(
            "some text", "无", "2026-06-14T10:00:00+00:00"
        )

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_cares_returns_empty_on_llm_exception(self, db_session):
        """_extract_cares returns [] when LLM call raises RuntimeError."""
        # Arrange
        llm = _make_llm_client(call_side_effect=RuntimeError("LLM timeout"))
        generator = TodoGenerator(llm, db_session)

        # Act
        result = await generator._extract_cares(
            "some text", "无", "2026-06-14T10:00:00+00:00"
        )

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_generate_typed_todo_returns_none_on_llm_exception(
        self, db_session
    ):
        """_generate_typed_todo returns None when LLM call raises exception."""
        # Arrange
        llm = _make_llm_client(call_side_effect=RuntimeError("LLM error"))
        generator = TodoGenerator(llm, db_session)

        # Act
        result = await generator._generate_typed_todo(
            todo_type="risk",
            conversation="some text",
            persons="无",
        )

        # Assert
        assert result is None


# ── G2-08: TodoDeduplicator integration ──


class TestTodoDeduplicatorIntegration:
    """G2-08: TodoDeduplicator is called at the end of generate_todos (F-46).

    After persisting todos, generate_todos calls TodoDeduplicator.deduplicate
    (line 285-289) which applies:
    1. Per-event cap: max MAX_TODOS_PER_EVENT (3) todos per source_event_id
    2. Similarity dedup: title similarity > 0.6 → remove lower priority
    3. Within-batch dedup: among new todos themselves
    """

    @pytest.mark.asyncio
    async def test_deduplicator_applies_per_event_cap(self, db_session):
        """F-46: TodoDeduplicator caps todos to MAX_TODOS_PER_EVENT (3) per event."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        # Create 4 GeneratedTodos with distinct titles and different priorities
        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 发送项目计划书",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="[关注] 投资偏好分析",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )
        coop_todo = GeneratedTodo(
            todo_type="cooperation_signal",
            title="[合作信号] 资源互补",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        risk_todo = GeneratedTodo(
            todo_type="risk",
            title="[风险预警] 竞争对手",
            priority=5,
            due_date=datetime.now(UTC) + timedelta(days=1),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])

        typed_map = {
            "cooperation_signal": coop_todo,
            "risk": risk_todo,
        }

        async def mock_typed_todo(todo_type, **kwargs):
            return typed_map.get(todo_type)

        generator._generate_typed_todo = AsyncMock(side_effect=mock_typed_todo)

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        event = _make_event(event_type="meeting", raw_text="讨论AI项目合作")
        entities = [_make_entity(name="李总")]

        # Act
        result = await generator.generate_todos(event, entities)

        # Assert
        # Per-event cap: MAX_TODOS_PER_EVENT = 3, so 4 todos → 3 kept
        assert len(result) == 3
        # The lowest priority (priority=5, risk) should be removed by cap
        priorities = [t.priority for t in result]
        assert 5 not in priorities
        assert 1 in priorities
        assert 2 in priorities
        assert 3 in priorities

    @pytest.mark.asyncio
    async def test_deduplicator_called_in_generate_todos(
        self, db_session, monkeypatch
    ):
        """F-46: TodoDeduplicator.deduplicate is invoked at end of generate_todos."""
        # Arrange
        llm = _make_llm_client()
        generator = TodoGenerator(llm, db_session)

        promise_todo = GeneratedTodo(
            todo_type="promise",
            title="[承诺] 发送资料",
            priority=1,
            due_date=datetime.now(UTC) + timedelta(days=3),
        )
        care_todo = GeneratedTodo(
            todo_type="care",
            title="[关注] 项目需求",
            priority=3,
            due_date=datetime.now(UTC) + timedelta(days=7),
        )

        generator._extract_promises = AsyncMock(return_value=[promise_todo])
        generator._extract_cares = AsyncMock(return_value=[care_todo])
        generator._generate_typed_todo = AsyncMock(return_value=None)

        async def mock_persist(gen, user_id, event_id):
            return _make_todo_from_generated(gen, user_id, event_id)

        generator._persist_todo = AsyncMock(side_effect=mock_persist)

        # Patch TodoDeduplicator.deduplicate to track invocation
        dedup_called = False
        original_dedup = TodoDeduplicator.deduplicate

        def tracking_dedup(self, todos, user_id, existing_todos=None):
            nonlocal dedup_called
            dedup_called = True
            return original_dedup(self, todos, user_id, existing_todos)

        monkeypatch.setattr(TodoDeduplicator, "deduplicate", tracking_dedup)

        event = _make_event(event_type="card_save", raw_text="讨论事项")
        entities = [_make_entity(name="李总")]

        # Act
        result = await generator.generate_todos(event, entities)

        # Assert
        assert dedup_called is True
        assert len(result) >= 1

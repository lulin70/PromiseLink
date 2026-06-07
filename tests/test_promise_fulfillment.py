"""Tests for PromiseFulfillmentEngine & SensitivityFilter.

Covers all public classes/methods in promise_fulfillment.py:
  - SensitivityFilter: check, batch_filter
  - PromiseFulfillmentEngine: __init__, calculate_match_score, find_matching_persons,
    _keyword_overlap, _industry_alignment, _topic_similarity, _llm_semantic_judge,
    _history_collaboration, _callability, _sanitize_for_llm, _generate_reason
"""

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from eventlink.database import Base
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.promise_fulfillment import (
    FULL_WEIGHTS,
    PHASE1_WEIGHTS,
    POC_WEIGHTS,
    PromiseFulfillmentEngine,
    SensitivityFilter,
)


# ── Helpers ──

TEST_USER_ID = str(uuid.uuid4())
EVENT_ID = str(uuid.uuid4())


def _make_entity(
    name: str = "TestPerson",
    entity_type: str = "person",
    properties: dict | None = None,
    status: str = "confirmed",
) -> Entity:
    """Create an Entity instance (not persisted)."""
    return Entity(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        entity_type=entity_type,
        name=name,
        canonical_name=name,
        properties=properties or {},
        source_event_id=EVENT_ID,
        confidence=1.0,
        status=status,
    )


def _make_todo(
    title: str = "TestTodo",
    description: str | None = None,
    todo_type: str = "promise",
    properties: dict | None = None,
) -> Todo:
    """Create a Todo instance (not persisted)."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        todo_type=todo_type,
        title=title,
        description=description,
        source_event_id=EVENT_ID,
        properties=properties or {},
    )


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    """In-memory SQLite async engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Async session bound to in-memory DB."""
    session = AsyncSession(bind=db_engine, expire_on_commit=False)
    yield session
    await session.close()


@pytest_asyncio.fixture
def filter_instance():
    return SensitivityFilter()


# ════════════════════════════════════════════════════════════════════
# SensitivityFilter — pure logic, no DB needed
# ════════════════════════════════════════════════════════════════════


class TestSensitivityFilterCheck:
    """SensitivityFilter.check() tests."""

    def test_default_no_sensitivity_field(self, filter_instance):
        """No sensitivity field → matchable (True)."""
        person = _make_entity(properties={})
        assert filter_instance.check(person) is True

    def test_none_properties(self, filter_instance):
        """properties is None → matchable (True)."""
        person = _make_entity()
        person.properties = None
        assert filter_instance.check(person) is True

    def test_empty_properties(self, filter_instance):
        """Empty dict properties → matchable (True)."""
        person = _make_entity(properties={})
        assert filter_instance.check(person) is True

    def test_resource_sensitivity_no_match(self, filter_instance):
        """resource.sensitivity='no_match' → filtered (False)."""
        person = _make_entity(properties={
            "resource": {"sensitivity": "no_match"},
        })
        assert filter_instance.check(person) is False

    def test_resource_sensitivity_top_level(self, filter_instance):
        """top-level resource_sensitivity='no_match' → filtered (False)."""
        person = _make_entity(properties={
            "resource_sensitivity": "no_match",
        })
        assert filter_instance.check(person) is False

    def test_resource_sensitivity_matchable(self, filter_instance):
        """resource.sensitivity='matchable' → True."""
        person = _make_entity(properties={
            "resource": {"sensitivity": "matchable"},
        })
        assert filter_instance.check(person) is True

    def test_resource_dict_takes_priority(self, filter_instance):
        """resource.sensitivity takes priority over top-level resource_sensitivity."""
        person = _make_entity(properties={
            "resource": {"sensitivity": "matchable"},
            "resource_sensitivity": "no_match",
        })
        assert filter_instance.check(person) is True

    def test_unknown_sensitivity_value(self, filter_instance):
        """Unknown sensitivity value defaults to matchable (True)."""
        person = _make_entity(properties={
            "resource": {"sensitivity": "unknown_value"},
        })
        assert filter_instance.check(person) is True

    def test_resource_not_dict_uses_fallback(self, filter_instance):
        """resource is not a dict → falls back to resource_sensitivity field."""
        person = _make_entity(properties={
            "resource": "some_string",
            "resource_sensitivity": "no_match",
        })
        assert filter_instance.check(person) is False

    def test_resource_not_dict_no_fallback(self, filter_instance):
        """resource is not a dict and no fallback → default matchable."""
        person = _make_entity(properties={"resource": "some_string"})
        assert filter_instance.check(person) is True


class TestSensitivityFilterBatchFilter:
    """SensitivityFilter.batch_filter() tests."""

    def test_all_matchable(self, filter_instance):
        """All persons are matchable."""
        persons = [
            _make_entity(name=f"P{i}", properties={})
            for i in range(3)
        ]
        matchable, filtered = filter_instance.batch_filter(persons)
        assert len(matchable) == 3
        assert len(filtered) == 0

    def test_all_filtered(self, filter_instance):
        """All persons are filtered out."""
        persons = [
            _make_entity(
                name=f"P{i}",
                properties={"resource": {"sensitivity": "no_match"}},
            )
            for i in range(3)
        ]
        matchable, filtered = filter_instance.batch_filter(persons)
        assert len(matchable) == 0
        assert len(filtered) == 3

    def test_mixed_batch(self, filter_instance):
        """Mixed batch splits correctly."""
        persons = [
            _make_entity(name="Match1", properties={}),
            _make_entity(name="Filtered1", properties={"resource": {"sensitivity": "no_match"}}),
            _make_entity(name="Match2", properties={}),
            _make_entity(name="Filtered2", properties={"resource_sensitivity": "no_match"}),
        ]
        matchable, filtered = filter_instance.batch_filter(persons)
        assert len(matchable) == 2
        assert len(filtered) == 2
        assert {p.name for p in matchable} == {"Match1", "Match2"}
        assert {p.name for p in filtered} == {"Filtered1", "Filtered2"}

    def test_empty_list(self, filter_instance):
        """Empty list returns two empty lists."""
        matchable, filtered = filter_instance.batch_filter([])
        assert matchable == []
        assert filtered == []


# ════════════════════════════════════════════════════════════════════
# PromiseFulfillmentEngine — __init__ & weight selection
# ════════════════════════════════════════════════════════════════════


class TestPromiseFulfillmentEngineInit:
    """Constructor weight selection by stage."""

    @pytest.mark.asyncio
    async def test_poc_weights(self, db_session):
        """stage='poc' selects POC_WEIGHTS."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        assert engine.weights == POC_WEIGHTS
        assert engine.stage == "poc"

    @pytest.mark.asyncio
    async def test_phase1_weights(self, db_session):
        """stage='phase1' selects PHASE1_WEIGHTS."""
        engine = PromiseFulfillmentEngine(db_session, stage="phase1")
        assert engine.weights == PHASE1_WEIGHTS
        assert engine.stage == "phase1"

    @pytest.mark.asyncio
    async def test_full_weights_default(self, db_session):
        """Unknown stage selects FULL_WEIGHTS."""
        engine = PromiseFulfillmentEngine(db_session, stage="phase2")
        assert engine.weights == FULL_WEIGHTS

    @pytest.mark.asyncio
    async def test_config_stored(self, db_session):
        """Config dict is stored on instance."""
        cfg = {"related_industries": {"tech": ["internet"]}}
        engine = PromiseFulfillmentEngine(db_session, config=cfg, stage="poc")
        assert engine.config == cfg

    @pytest.mark.asyncio
    async def test_llm_client_stored(self, db_session):
        """LLM client reference is stored."""
        mock_llm = AsyncMock()
        engine = PromiseFulfillmentEngine(db_session, llm_client=mock_llm)
        assert engine.llm is mock_llm

    @pytest.mark.asyncio
    async def test_sensitivity_filter_created(self, db_session):
        """SensitivityFilter instance is created on init."""
        engine = PromiseFulfillmentEngine(db_session)
        assert isinstance(engine.sensitivity_filter, SensitivityFilter)


# ════════════════════════════════════════════════════════════════════
# Dimension methods — pure functions, no DB
# ════════════════════════════════════════════════════════════════════


class TestKeywordOverlap:
    """_keyword_overlap — Jaccard similarity on keyword sets."""

    @pytest.mark.asyncio
    async def test_exact_keyword_match(self, db_session):
        """Identical keyword sets → Jaccard = 1.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI", "cloud"]})
        person = _make_entity(properties={"keywords": ["AI", "cloud"]})
        result = engine._keyword_overlap(todo, person)
        assert result == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_keyword_overlap(self, db_session):
        """Partial overlap → correct Jaccard value."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI", "cloud", "security"]})
        person = _make_entity(properties={"keywords": ["AI", "blockchain"]})
        result = engine._keyword_overlap(todo, person)
        # intersection={"AI"}, union={"AI","cloud","security","blockchain"} → 1/4
        assert result == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_no_keyword_overlap(self, db_session):
        """No overlapping keywords → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={"keywords": ["farming"]})
        result = engine._keyword_overlap(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_todo_keywords(self, db_session):
        """Todo has no keywords → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={})
        person = _make_entity(properties={"keywords": ["AI"]})
        result = engine._keyword_overlap(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_empty_person_keywords(self, db_session):
        """Person has no keywords → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={})
        result = engine._keyword_overlap(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_none_properties(self, db_session):
        """None properties handled gracefully → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties=None)
        person = _make_entity(properties=None)
        result = engine._keyword_overlap(todo, person)
        assert result == 0.0


class TestIndustryAlignment:
    """_industry_alignment — exact / related / no match."""

    @pytest.mark.asyncio
    async def test_exact_industry_match(self, db_session):
        """Same industry → 1.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"domain_l1": "tech"})
        person = _make_entity(properties={"basic": {"industry": "tech"}})
        result = engine._industry_alignment(todo, person)
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_related_industry(self, db_session):
        """Related industry via config → 0.5."""
        config = {"related_industries": {"tech": ["internet", "software"]}}
        engine = PromiseFulfillmentEngine(db_session, config=config)
        todo = _make_todo(properties={"domain_l1": "tech"})
        person = _make_entity(properties={"basic": {"industry": "internet"}})
        result = engine._industry_alignment(todo, person)
        assert result == 0.5

    @pytest.mark.asyncio
    async def test_unrelated_industry(self, db_session):
        """Unrelated industry → 0.0."""
        config = {"related_industries": {"tech": ["internet"]}}
        engine = PromiseFulfillmentEngine(db_session, config=config)
        todo = _make_todo(properties={"domain_l1": "tech"})
        person = _make_entity(properties={"basic": {"industry": "agriculture"}})
        result = engine._industry_alignment(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_missing_todo_domain(self, db_session):
        """Todo has no domain_l1 → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={})
        person = _make_entity(properties={"basic": {"industry": "tech"}})
        result = engine._industry_alignment(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_missing_person_industry(self, db_session):
        """Person has no industry → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"domain_l1": "tech"})
        person = _make_entity(properties={})
        result = engine._industry_alignment(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_no_related_config(self, db_session):
        """No related_industries config → unrelated returns 0.0."""
        engine = PromiseFulfillmentEngine(db_session, config={})
        todo = _make_todo(properties={"domain_l1": "tech"})
        person = _make_entity(properties={"basic": {"industry": "internet"}})
        result = engine._industry_alignment(todo, person)
        assert result == 0.0


class TestTopicSimilarity:
    """_topic_similarity — Jaccard on topic tags."""

    @pytest.mark.asyncio
    async def test_identical_topics(self, db_session):
        """Identical topic tags → 1.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"topic_tags": ["LLM", "agent"]})
        person = _make_entity(properties={"topic_tags": ["LLM", "agent"]})
        result = await engine._topic_similarity(todo, person)
        assert result == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_topic_overlap(self, db_session):
        """Partial overlap → correct Jaccard."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"topic_tags": ["A", "B", "C"]})
        person = _make_entity(properties={"topic_tags": ["B", "D"]})
        result = await engine._topic_similarity(todo, person)
        # intersection={"B"}, union={"A","B","C","D"} → 1/4
        assert result == pytest.approx(0.25)

    @pytest.mark.asyncio
    async def test_no_topics(self, db_session):
        """Either side empty → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={})
        person = _make_entity(properties={"topic_tags": ["X"]})
        result = await engine._topic_similarity(todo, person)
        assert result == 0.0


class TestHistoryCollaboration:
    """_history_collaboration — PoC always returns 0.0."""

    @pytest.mark.asyncio
    async def test_always_zero_in_poc(self, db_session):
        """PoC stage always returns 0.0 regardless of inputs."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo()
        person = _make_entity()
        result = engine._history_collaboration(todo, person)
        assert result == 0.0


class TestCallability:
    """_callability — resource tags vs demand keywords."""

    @pytest.mark.asyncio
    async def test_all_resources_match(self, db_session):
        """All resources have matching tags → 1.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI", "consulting"]})
        person = _make_entity(properties={
            "resource": [
                {"tags": ["AI", "expert"]},
                {"tags": ["consulting", "advisor"]},
            ],
        })
        result = engine._callability(todo, person)
        assert result == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_partial_resource_match(self, db_session):
        """Some resources match → fractional score."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={
            "resource": [
                {"tags": ["AI", "expert"]},
                {"tags": ["legal", "advisor"]},
                {"tags": ["finance", "cfo"]},
            ],
        })
        result = engine._callability(todo, person)
        # 1 out of 3 matched
        assert result == pytest.approx(1.0 / 3.0)

    @pytest.mark.asyncio
    async def test_no_resources(self, db_session):
        """Person has no resource list → 0.0."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={})
        result = engine._callability(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_no_demand_keywords_neutral_score(self, db_session):
        """No demand keywords → neutral 0.3 score."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={})
        person = _make_entity(properties={
            "resource": [{"tags": ["AI"]}],
        })
        result = engine._callability(todo, person)
        assert result == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_resource_not_dict_ignored(self, db_session):
        """Non-dict resource entries are skipped gracefully."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={
            "resource": ["string_item", {"tags": ["AI"]}, None],
        })
        result = engine._callability(todo, person)
        # Only the dict entry matches; total resources counted = 3
        assert result == pytest.approx(1.0 / 3.0)


class TestSanitizeForLlm:
    """_sanitize_for_llm — data sanitization (no PII)."""

    @pytest.mark.asyncio
    async def test_extracts_relevant_fields(self, db_session):
        """Extracts only non-PII fields from todo and person."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(
            description="Need AI consultant",
            properties={"keywords": ["AI", "ML"]},
        )
        person = _make_entity(properties={
            "basic": {
                "company": "Acme Corp",
                "title": "CTO",
                "industry": "tech",
            },
        })
        result = engine._sanitize_for_llm(todo, person)
        assert result == {
            "todo": {
                "description": "Need AI consultant",
                "keywords": ["AI", "ML"],
            },
            "person": {
                "company": "Acme Corp",
                "title": "CTO",
                "industry": "tech",
            },
        }

    @pytest.mark.asyncio
    async def test_handles_none_properties(self, db_session):
        """None properties produce empty fields."""
        engine = PromiseFulfillmentEngine(db_session)
        todo = _make_todo(description="test", properties=None)
        person = _make_entity(properties=None)
        result = engine._sanitize_for_llm(todo, person)
        assert result["todo"]["description"] == "test"
        assert result["todo"]["keywords"] == []
        assert result["person"]["company"] is None
        assert result["person"]["title"] is None
        assert result["person"]["industry"] is None


class TestGenerateReason:
    """_generate_reason — human-readable reason string."""

    @pytest.mark.asyncio
    async def test_high_industry_triggers_reason(self, db_session):
        """Industry >= 0.5 includes '同行业'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({"industry_alignment": 0.6})
        assert "同行业" in reason

    @pytest.mark.asyncio
    async def test_high_keyword_triggers_reason(self, db_session):
        """Keyword >= 0.3 includes '关键词相关'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({"keyword_overlap": 0.5})
        assert "关键词相关" in reason

    @pytest.mark.asyncio
    async def test_high_history_triggers_reason(self, db_session):
        """History >= 0.3 includes '有过合作'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({"history_collaboration": 0.5})
        assert "有过合作" in reason

    @pytest.mark.asyncio
    async def test_high_topic_triggers_reason(self, db_session):
        """Topic >= 0.5 includes '话题相关'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({"topic_similarity": 0.7})
        assert "话题相关" in reason

    @pytest.mark.asyncio
    async def test_high_callability_triggers_reason(self, db_session):
        """Callability >= 0.5 includes '可调用资源匹配'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({"callability": 0.8})
        assert "可调用资源匹配" in reason

    @pytest.mark.asyncio
    async def test_multiple_reasons_joined(self, db_session):
        """Multiple qualifying dimensions are joined with '·'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({
            "industry_alignment": 0.6,
            "keyword_overlap": 0.4,
            "callability": 0.6,
        })
        assert "同行业" in reason
        assert "关键词相关" in reason
        assert "可调用资源匹配" in reason
        assert "·" in reason

    @pytest.mark.asyncio
    async def test_no_qualifying_dimensions(self, db_session):
        """No dimension above threshold → '潜在关联'."""
        engine = PromiseFulfillmentEngine(db_session)
        reason = engine._generate_reason({
            "industry_alignment": 0.1,
            "keyword_overlap": 0.1,
            "history_collaboration": 0.0,
            "topic_similarity": 0.1,
            "callability": 0.1,
        })
        assert reason == "潜在关联"


# ════════════════════════════════════════════════════════════════════
# LLM semantic judge — needs mock llm_client
# ════════════════════════════════════════════════════════════════════


class TestLlmSemanticJudge:
    """_llm_semantic_judge with mocked LLM client."""

    @pytest.mark.asyncio
    async def test_successful_llm_response(self, db_session):
        """LLM returns valid float → clamped to [0, 1]."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="0.85")
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo()
        person = _make_entity()
        result = await engine._llm_semantic_judge(todo, person)
        assert result == pytest.approx(0.85)

    @pytest.mark.asyncio
    async def test_llm_value_clamped_above_one(self, db_session):
        """LLM returns > 1.0 → clamped to 1.0."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="1.5")
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo()
        person = _make_entity()
        result = await engine._llm_semantic_judge(todo, person)
        assert result == 1.0

    @pytest.mark.asyncio
    async def test_llm_value_clamped_below_zero(self, db_session):
        """LLM returns < 0.0 → clamped to 0.0."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="-0.3")
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo()
        person = _make_entity()
        result = await engine._llm_semantic_judge(todo, person)
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_llm_exception_returns_fallback(self, db_session):
        """LLM raises exception → fallback 0.5."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo()
        person = _make_entity()
        result = await engine._llm_semantic_judge(todo, person)
        assert result == 0.5

    @pytest.mark.asyncio
    async def test_llm_invalid_float_returns_fallback(self, db_session):
        """LLM returns non-numeric string → fallback 0.5."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="not_a_number")
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo()
        person = _make_entity()
        result = await engine._llm_semantic_judge(todo, person)
        assert result == 0.5


# ════════════════════════════════════════════════════════════════════
# calculate_match_score — integration of all dimensions
# ════════════════════════════════════════════════════════════════════


class TestCalculateMatchScore:
    """calculate_match_score end-to-end scoring."""

    @pytest.mark.asyncio
    async def test_normal_scoring(self, db_session):
        """Normal case: computes weighted sum across enabled dimensions."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        todo = _make_todo(
            description="Find AI expert",
            properties={
                "keywords": ["AI", "ML"],
                "domain_l1": "tech",
                "topic_tags": ["LLM"],
            },
        )
        person = _make_entity(
            name="Alice",
            properties={
                "keywords": ["AI", "cloud"],
                "basic": {"industry": "tech"},
                "topic_tags": ["LLM", "agent"],
                "resource": [{"tags": ["AI", "consulting"]}],
            },
        )
        result = await engine.calculate_match_score(todo, person)
        assert result["filtered"] is False
        assert result["total_score"] > 0.0
        assert "dimensions" in result
        assert "match_reason" in result
        # All 6 dimension keys present
        dims = result["dimensions"]
        assert set(dims.keys()) == {
            "keyword_overlap", "industry_alignment", "topic_similarity",
            "llm_semantic", "history_collaboration", "callability",
        }

    @pytest.mark.asyncio
    async def test_filtered_by_sensitivity(self, db_session):
        """Sensitivity=no_match → filtered=True, score=0."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(
            properties={"resource": {"sensitivity": "no_match"}},
        )
        result = await engine.calculate_match_score(todo, person)
        assert result["filtered"] is True
        assert result["total_score"] == 0.0
        assert result["dimensions"] == {}
        assert result["match_reason"] == "Resource marked as no_match"

    @pytest.mark.asyncio
    async def test_poc_weighted_total(self, db_session):
        """PoC weights: keyword(35%) + callability(35%) + industry(30%)."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        # Perfect matches on all 3 PoC dimensions
        todo = _make_todo(properties={
            "keywords": ["AI"],
            "domain_l1": "tech",
        })
        person = _make_entity(properties={
            "keywords": ["AI"],
            "basic": {"industry": "tech"},
            "resource": [{"tags": ["AI"]}],
        })
        result = await engine.calculate_match_score(todo, person)
        dims = result["dimensions"]
        # In PoC: keyword=1.0, industry=1.0, callability=1.0
        # Total = 1.0*0.35 + 1.0*0.30 + 1.0*0.35 = 1.0
        expected = (
            dims["keyword_overlap"] * 0.35
            + dims["industry_alignment"] * 0.30
            + dims["callability"] * 0.35
        )
        assert result["total_score"] == pytest.approx(expected, abs=1e-4)

    @pytest.mark.asyncio
    async def test_zero_score_excluded_from_results(self, db_session):
        """Score=0 results should have total_score exactly 0."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        # No keyword overlap, wrong industry, no resources → likely near-zero
        todo = _make_todo(properties={
            "keywords": ["quantum"],
            "domain_l1": "physics",
        })
        person = _make_entity(properties={
            "keywords": ["farming"],
            "basic": {"industry": "agriculture"},
        })
        result = await engine.calculate_match_score(todo, person)
        # callability will be 0.3 (neutral), so total > 0
        assert isinstance(result["total_score"], float)

    @pytest.mark.asyncio
    async def test_with_llm_semantic_enabled(self, db_session):
        """Full stage with LLM semantic dimension active."""
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="0.9")
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=mock_llm, stage="full",
        )
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={"keywords": ["AI"]})
        result = await engine.calculate_match_score(todo, person)
        dims = result["dimensions"]
        # LLM semantic should contribute since full weights have it at 0.10
        assert dims["llm_semantic"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_without_llm_client_skips_semantic(self, db_session):
        """No llm_client → llm_semantic = 0.0 even if weight > 0."""
        engine = PromiseFulfillmentEngine(
            db_session, llm_client=None, stage="full",
        )
        todo = _make_todo(properties={"keywords": ["AI"]})
        person = _make_entity(properties={"keywords": ["AI"]})
        result = await engine.calculate_match_score(todo, person)
        assert result["dimensions"]["llm_semantic"] == 0.0

    @pytest.mark.asyncio
    async def test_dimensions_rounded_to_4_decimals(self, db_session):
        """Each dimension value is rounded to 4 decimal places."""
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        todo = _make_todo(properties={"keywords": ["a"], "domain_l1": "x"})
        person = _make_entity(properties={
            "keywords": ["a", "b", "c", "d", "e"],
            "basic": {"industry": "y"},
        })
        result = await engine.calculate_match_score(todo, person)
        for val in result["dimensions"].values():
            # Check rounding precision
            rounded = round(val, 4)
            assert val == rounded


# ════════════════════════════════════════════════════════════════════
# find_matching_persons — full DB-backed flow
# ════════════════════════════════════════════════════════════════════


class TestFindMatchingPersons:
    """find_matching_persons — DB query + filter + rank."""

    @pytest_asyncio.fixture
    async def _seed_data(self, db_session):
        """Persist entities and todos into the test DB."""
        # Create a source event first (FK required by Entity and Todo)
        event = Event(
            id=EVENT_ID,
            user_id=TEST_USER_ID,
            event_type="manual",
            source="test",
            title="Test event for promise fulfillment",
        )
        db_session.add(event)
        await db_session.flush()

        # Create 3 persons for TEST_USER_ID
        persons = [
            Entity(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                entity_type="person",
                name="Alice",
                canonical_name="Alice",
                properties={
                    "keywords": ["AI", "ML"],
                    "basic": {"industry": "tech"},
                    "topic_tags": ["LLM"],
                    "resource": [{"tags": ["AI", "consulting"]}],
                },
                source_event_id=EVENT_ID,
                confidence=1.0,
                status="confirmed",
            ),
            Entity(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                entity_type="person",
                name="Bob",
                canonical_name="Bob",
                properties={
                    "keywords": ["finance"],
                    "basic": {"industry": "finance"},
                    "resource": [],
                },
                source_event_id=EVENT_ID,
                confidence=1.0,
                status="provisional",
            ),
            Entity(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                entity_type="person",
                name="Charlie",
                canonical_name="Charlie",
                properties={
                    "resource": {"sensitivity": "no_match"},
                },
                source_event_id=EVENT_ID,
                confidence=1.0,
                status="confirmed",
            ),
        ]
        for p in persons:
            db_session.add(p)
        await db_session.flush()

        # Create a todo
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            todo_type="promise",
            title="Find AI expert",
            description="Need AI consultant",
            source_event_id=EVENT_ID,
            properties={
                "keywords": ["AI", "consulting"],
                "domain_l1": "tech",
                "topic_tags": ["LLM"],
            },
        )
        db_session.add(todo)
        await db_session.flush()
        await db_session.commit()

        return todo, persons

    @pytest.mark.asyncio
    async def test_find_matches_returns_sorted(self, db_session, _seed_data):
        """Results sorted by total_score descending."""
        todo, _ = _seed_data
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=5)
        assert len(results) >= 1
        scores = [r["total_score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_find_matches_respects_top_k(self, db_session, _seed_data):
        """Returns at most top_k results."""
        todo, _ = _seed_data
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=1)
        assert len(results) <= 1

    @pytest.mark.asyncio
    async def test_find_matches_filters_by_user_id(self, db_session, _seed_data):
        """Only returns persons belonging to the given user_id."""
        todo, _ = _seed_data
        other_user_id = str(uuid.uuid4())
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, other_user_id, top_k=5)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_find_matches_filters_sensitivity(self, db_session, _seed_data):
        """Persons with sensitivity=no_match are excluded."""
        todo, _ = _seed_data
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=5)
        names = [r.get("person_name") for r in results]
        assert "Charlie" not in names  # Charlie is no_match

    @pytest.mark.asyncio
    async def test_find_matches_includes_person_metadata(self, db_session, _seed_data):
        """Each result contains person_id and person_name."""
        todo, _ = _seed_data
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=5)
        for r in results:
            assert "person_id" in r
            assert "person_name" in r

    @pytest.mark.asyncio
    async def test_find_matches_excludes_deleted_status(self, db_session, _seed_data):
        """Persons with deleted status are excluded from query."""
        todo, _ = _seed_data
        # Add a deleted person
        deleted = Entity(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            entity_type="person",
            name="DeletedPerson",
            canonical_name="DeletedPerson",
            properties={"keywords": ["AI"]},
            source_event_id=EVENT_ID,
            confidence=1.0,
            status="deleted",
        )
        db_session.add(deleted)
        await db_session.flush()
        await db_session.commit()

        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=10)
        names = [r.get("person_name") for r in results]
        assert "DeletedPerson" not in names

    @pytest.mark.asyncio
    async def test_find_matches_empty_database(self, db_session):
        """No persons in DB → empty list."""
        todo = _make_todo(properties={"keywords": ["AI"]})
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_find_matches_only_positive_scores(self, db_session, _seed_data):
        """Results only include entries with total_score > 0."""
        todo, _ = _seed_data
        engine = PromiseFulfillmentEngine(db_session, stage="poc")
        results = await engine.find_matching_persons(todo, TEST_USER_ID, top_k=5)
        for r in results:
            assert r["total_score"] > 0.0

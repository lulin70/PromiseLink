"""Tests for F-50 Voice Query API — POST /voice/query endpoint.

Tests cover:
  1. Schedule query (日程查询)
  2. Promise query (承诺追踪)
  3. Relationship query (关系推进查询)
  4. Non-query intents return no data
  5. Validation errors
  6. Query service unit tests
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from eventlink.core.auth import get_current_user_id
from eventlink.database import Base, get_async_session
from eventlink.main import app
from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.models.todo import Todo
from eventlink.services.nlu_intent_classifier import VoiceIntent
from eventlink.services.voice_query_service import (
    execute_query,
    query_promises,
    query_relationship,
    query_schedule,
)


# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"
_TZ_CN = timezone(timedelta(hours=8))


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite async engine for testing."""
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
    """Create an async session bound to the test engine."""
    async_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    yield async_session
    await async_session.close()


@pytest_asyncio.fixture
async def client(db_session):
    """Create an AsyncClient with the test session override."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


def _make_mock_nlu_result(intent_value="schedule_query", confidence=0.92, slots=None, evidence="test"):
    """Create a mock NLUResult object."""
    mock_result = MagicMock()
    mock_result.intent = MagicMock(value=intent_value)
    # Make intent comparable with VoiceIntent enum
    if intent_value == "schedule_query":
        mock_result.intent = VoiceIntent.SCHEDULE_QUERY
    elif intent_value == "promise_tracker":
        mock_result.intent = VoiceIntent.PROMISE_TRACKER
    elif intent_value == "relationship_status":
        mock_result.intent = VoiceIntent.RELATIONSHIP_STATUS
    elif intent_value == "action_suggestion":
        mock_result.intent = VoiceIntent.ACTION_SUGGESTION
    elif intent_value == "todo_create":
        mock_result.intent = VoiceIntent.TODO_CREATE
    elif intent_value == "exit":
        mock_result.intent = VoiceIntent.EXIT
    elif intent_value == "chitchat":
        mock_result.intent = VoiceIntent.CHITCHAT
    elif intent_value == "unclear":
        mock_result.intent = VoiceIntent.UNCLEAR
    mock_result.confidence = confidence
    mock_result.slots = slots or {}
    mock_result.evidence = evidence
    mock_result.method = "rule"
    return mock_result


# ── Test 1: Schedule query (日程查询) ──────────────────────────────


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_schedule(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/query with schedule query returns events data."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="schedule_query",
        confidence=0.92,
        slots={"date": datetime.now(_TZ_CN).date().isoformat()},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "今天有什么安排"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "schedule_query"
    assert data["confidence"] == 0.92
    assert data["response"] is not None
    assert isinstance(data["response"], str)
    assert data["data"] is not None
    assert "events" in data["data"]
    assert "count" in data["data"]


# ── Test 2: Promise query (承诺追踪) ──────────────────────────────


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_promise(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/query with promise query returns todos data."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="promise_tracker",
        confidence=0.90,
        slots={"person": "老王"},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "我答应老王什么事"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "promise_tracker"
    assert data["confidence"] == 0.90
    assert data["response"] is not None
    assert data["data"] is not None
    assert "todos" in data["data"]
    assert "count" in data["data"]


# ── Test 3: Relationship query (关系推进查询) ──────────────────────


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_relationship(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/query with relationship query returns relationships data."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="relationship_status",
        confidence=0.88,
        slots={"person": "张总"},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "我和张总的关系到哪一步了"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "relationship_status"
    assert data["confidence"] == 0.88
    assert data["response"] is not None
    assert data["data"] is not None
    assert "relationships" in data["data"]
    assert "count" in data["data"]


# ── Test 4: Non-query intent returns no data ──────────────────────


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_non_query_intent_no_data(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/query with non-query intent (e.g., exit) returns no data field."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="exit",
        confidence=0.95,
        slots={},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "再见"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "exit"
    assert data["data"] is None


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_todo_create_no_data(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/query with todo_create intent returns no data field."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="todo_create",
        confidence=0.90,
        slots={"content": "周五见王总"},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "提醒我周五见王总"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "todo_create"
    assert data["data"] is None


# ── Test 5: Validation errors ──────────────────────────────────────


async def test_voice_query_empty_text_returns_422(client):
    """Empty text triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": ""},
    )
    assert response.status_code == 422


async def test_voice_query_missing_text_returns_422(client):
    """Missing text field triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"user_id": TEST_USER_ID},
    )
    assert response.status_code == 422


async def test_voice_query_text_too_long_returns_422(client):
    """Text exceeding max length triggers validation error (422)."""
    long_text = "a" * 2001
    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": long_text},
    )
    assert response.status_code == 422


# ── Test 6: user_id from body overrides auth ──────────────────────


@patch("eventlink.api.v1.voice_query.LLMClient")
@patch("eventlink.api.v1.voice_query.NLUIntentClassifier")
async def test_voice_query_user_id_from_body(mock_classifier_cls, mock_llm_cls, client):
    """user_id in request body is used when provided."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="schedule_query",
        confidence=0.92,
        slots={},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    custom_user_id = "00000000-0000-0000-0000-000000000099"
    response = await client.post(
        f"{API_PREFIX}/voice/query",
        json={"text": "今天有什么安排", "user_id": custom_user_id},
    )

    assert response.status_code == 200


# ── Test 7: Query service unit tests ──────────────────────────────


@pytest.mark.asyncio
async def test_query_schedule_returns_events(db_session):
    """query_schedule returns events for the specified date."""
    user_id = TEST_USER_ID
    now = datetime.now(_TZ_CN)
    today = now.date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=_TZ_CN)

    # Create test events
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="和李总开会",
        timestamp=day_start + timedelta(hours=10),
        status="pending",
    )
    db_session.add(event)
    await db_session.commit()

    result = await query_schedule(db_session, user_id, {"date": today.isoformat()})

    assert "events" in result
    assert result["count"] >= 1
    assert result["events"][0]["title"] == "和李总开会"
    assert result["events"][0]["event_type"] == "meeting"


@pytest.mark.asyncio
async def test_query_schedule_filters_by_meeting_call(db_session):
    """query_schedule only returns meeting and call events, not card_save."""
    user_id = TEST_USER_ID
    now = datetime.now(_TZ_CN)
    today = now.date()
    day_start = datetime(today.year, today.month, today.day, tzinfo=_TZ_CN)

    # Add a meeting event
    meeting_event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="会议",
        timestamp=day_start + timedelta(hours=10),
        status="pending",
    )
    # Add a card_save event (should be filtered out)
    card_event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="card_save",
        source="manual",
        title="名片",
        timestamp=day_start + timedelta(hours=11),
        status="pending",
    )
    db_session.add_all([meeting_event, card_event])
    await db_session.commit()

    result = await query_schedule(db_session, user_id, {"date": today.isoformat()})

    assert result["count"] == 1
    assert result["events"][0]["event_type"] == "meeting"


@pytest.mark.asyncio
async def test_query_schedule_no_events(db_session):
    """query_schedule returns empty list when no events exist."""
    user_id = TEST_USER_ID
    today = datetime.now(_TZ_CN).date()

    result = await query_schedule(db_session, user_id, {"date": today.isoformat()})

    assert result["events"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_query_promises_returns_pending_todos(db_session):
    """query_promises returns pending promise/care todos."""
    user_id = TEST_USER_ID

    # Create a source event first (required by FK)
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="测试会议",
        timestamp=datetime.now(_TZ_CN),
        status="completed",
    )
    db_session.add(event)
    await db_session.flush()

    # Create pending promise todo
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title="[承诺] 给老王发资料",
        status="pending",
        priority=2,
        source_event_id=event_id,
    )
    db_session.add(todo)
    await db_session.commit()

    result = await query_promises(db_session, user_id, {})

    assert "todos" in result
    assert result["count"] >= 1
    assert result["todos"][0]["todo_type"] == "promise"
    assert result["todos"][0]["status"] == "pending"


@pytest.mark.asyncio
async def test_query_promises_filters_by_person(db_session):
    """query_promises filters by person name when provided."""
    user_id = TEST_USER_ID

    # Create source event
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="测试",
        timestamp=datetime.now(_TZ_CN),
        status="completed",
    )
    db_session.add(event)
    await db_session.flush()

    # Create promise todo for 老王
    todo1 = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title="[承诺] 给老王发资料",
        status="pending",
        priority=2,
        source_event_id=event_id,
    )
    # Create promise todo for 张总
    todo2 = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title="[承诺] 给张总发报告",
        status="pending",
        priority=2,
        source_event_id=event_id,
    )
    db_session.add_all([todo1, todo2])
    await db_session.commit()

    result = await query_promises(db_session, user_id, {"person": "老王"})

    assert result["count"] >= 1
    assert all("老王" in t["title"] for t in result["todos"])


@pytest.mark.asyncio
async def test_query_promises_excludes_completed(db_session):
    """query_promises excludes completed todos."""
    user_id = TEST_USER_ID

    # Create source event
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="测试",
        timestamp=datetime.now(_TZ_CN),
        status="completed",
    )
    db_session.add(event)
    await db_session.flush()

    # Create completed promise todo
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title="[承诺] 已完成的事",
        status="done",
        priority=2,
        source_event_id=event_id,
    )
    db_session.add(todo)
    await db_session.commit()

    result = await query_promises(db_session, user_id, {})

    assert all(t["status"] not in ("done", "dismissed") for t in result["todos"])


@pytest.mark.asyncio
async def test_query_relationship_returns_briefs(db_session):
    """query_relationship returns relationship briefs with entity info."""
    user_id = TEST_USER_ID

    # Create source event
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="和张总见面",
        timestamp=datetime.now(_TZ_CN),
        status="completed",
    )
    db_session.add(event)
    await db_session.flush()

    # Create entity
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="张总",
        canonical_name="张总",
        source_event_id=event_id,
    )
    db_session.add(entity)
    await db_session.flush()

    # Create relationship brief
    brief = RelationshipBrief(
        id=str(uuid.uuid4()),
        user_id=user_id,
        person_entity_id=entity.id,
        relationship_stage="value_response",
        brief_data={
            "basic_info": {"name": "张总"},
            "strength_score": 75,
            "last_interaction": {"summary": "讨论了合作方案"},
        },
    )
    db_session.add(brief)
    await db_session.commit()

    result = await query_relationship(db_session, user_id, {"person": "张总"})

    assert "relationships" in result
    assert result["count"] >= 1
    assert result["relationships"][0]["relationship_stage"] == "value_response"
    assert result["relationships"][0]["name"] == "张总"


@pytest.mark.asyncio
async def test_query_relationship_no_match(db_session):
    """query_relationship returns empty when no person matches."""
    user_id = TEST_USER_ID

    result = await query_relationship(db_session, user_id, {"person": "不存在的人"})

    assert result["relationships"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_execute_query_dispatches_correctly(db_session):
    """execute_query dispatches to the right query function based on intent."""
    user_id = TEST_USER_ID
    today = datetime.now(_TZ_CN).date()

    # Schedule query
    result = await execute_query(db_session, user_id, VoiceIntent.SCHEDULE_QUERY, {"date": today.isoformat()})
    assert "events" in result

    # Promise query
    result = await execute_query(db_session, user_id, VoiceIntent.PROMISE_TRACKER, {})
    assert "todos" in result

    # Relationship query
    result = await execute_query(db_session, user_id, VoiceIntent.RELATIONSHIP_STATUS, {})
    assert "relationships" in result

    # Non-query intent returns empty
    result = await execute_query(db_session, user_id, VoiceIntent.EXIT, {})
    assert result == {}

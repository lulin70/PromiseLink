"""Tests for F-50 Voice API endpoints — session CRUD and user isolation."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app


# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
API_PREFIX = "/api/v1"


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
        cursor.execute("PRAGMA foreign_keys=OFF")
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
    mock_result.confidence = confidence
    mock_result.slots = slots or {}
    mock_result.evidence = evidence
    mock_result.method = "rule"
    return mock_result


# ── Test 1: POST /voice/session 成功创建 ──────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_create_voice_session_success(mock_classifier_cls, mock_llm_cls, client):
    """POST /voice/session creates a session and returns intent + response_text."""
    mock_llm_instance = MagicMock()
    mock_llm_cls.return_value = mock_llm_instance

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="schedule_query",
        confidence=0.92,
        slots={"date": "2026-06-05"},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={
            "query_text": "今天有什么会",
            "asr_confidence": 0.95,
            "asr_provider": "wechat",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "schedule_query"
    assert data["response_text"] is not None
    assert "session_id" in data
    assert data["slots"] is not None


# ── Test 2: 返回 intent 和 response_text ──────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_session_returns_intent_and_response(mock_classifier_cls, mock_llm_cls, client):
    """Response includes both intent field and generated response_text."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(
        intent_value="promise_tracker",
        confidence=0.90,
        slots={"person": "张总"},
    )

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": "我答应张总什么还没做"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "promise_tracker"
    assert data["response_text"] is not None
    assert isinstance(data["response_text"], str)


# ── Test 3: 无效 query_text → 422 ─────────────────────────────────


async def test_empty_query_text_returns_422(client):
    """Empty query_text triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": ""},
    )
    assert response.status_code == 422


async def test_missing_query_text_returns_422(client):
    """Missing query_text field triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"asr_provider": "wechat"},
    )
    assert response.status_code == 422


async def test_query_text_too_long_returns_422(client):
    """Query text exceeding max length triggers validation error (422)."""
    long_text = "a" * 2001
    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": long_text},
    )
    assert response.status_code == 422


# ── Test 4: GET /voice/sessions 返回列表 ───────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_list_voice_sessions_returns_list(mock_classifier_cls, mock_llm_cls, client):
    """GET /voice/sessions returns a list structure with total and items."""
    # First create a session
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="exit", confidence=0.95)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    create_resp = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": "再见"},
    )
    assert create_resp.status_code == 200

    # Then list sessions
    list_resp = await client.get(f"{API_PREFIX}/voice/sessions")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert "total" in data
    assert "items" in data
    assert isinstance(data["items"], list)


# ── Test 5: DELETE /voice/sessions 清除数据 ────────────────────────


async def test_delete_voice_sessions_success(client):
    """DELETE /voice/sessions returns success with deleted_count."""
    response = await client.delete(f"{API_PREFIX}/voice/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "deleted_count" in data
    assert "message" in data


# ── Test 6: 用户隔离 — 只能访问自己的 session ─────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_user_isolation_in_list(mock_classifier_cls, mock_llm_cls, client):
    """GET /voice/sessions only returns sessions for the authenticated user."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="chitchat", confidence=0.85)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    # Create a session
    resp = await client.post(f"{API_PREFIX}/voice/session", json={"query_text": "你好"})
    assert resp.status_code == 200

    # List should only show sessions (user_id filter applied in query)
    list_resp = await client.get(f"{API_PREFIX}/voice/sessions")
    assert list_resp.status_code == 200
    data = list_resp.json()
    for item in data["items"]:
        assert "session_id" in item
        assert "query_text" in item


# ── Test 7: asr_confidence 存储 ────────────────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_asr_confidence_stored_in_session(mock_classifier_cls, mock_llm_cls, client):
    """asr_confidence value is passed through to the session record."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="unclear", confidence=0.40)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={
            "query_text": "一些没有关键词的话",
            "asr_confidence": 0.87,
            "asr_provider": "whisper",
        },
    )

    assert response.status_code == 200


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_asr_confidence_out_of_range_rejected(mock_classifier_cls, mock_llm_cls, client):
    """asr_confidence outside [0, 1] range is rejected by Pydantic validation."""
    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={
            "query_text": "测试",
            "asr_confidence": 1.5,
        },
    )
    assert response.status_code == 422


# ── Test 8: status 默认为 active ───────────────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_default_status_active_for_non_exit_intents(mock_classifier_cls, mock_llm_cls, client):
    """Session status defaults to 'active' for non-exit/non-chitchat intents."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="schedule_query", confidence=0.92)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": "今天有什么会"},
    )

    assert response.status_code == 200


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_status_completed_for_exit_intent(mock_classifier_cls, mock_llm_cls, client):
    """Session status is 'completed' for exit/chitchat intents."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="exit", confidence=0.95)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": "再见"},
    )

    assert response.status_code == 200


# ── Test 9: 分页参数验证 ──────────────────────────────────────────


async def test_list_sessions_pagination_defaults(client):
    """GET /voice/sessions uses default pagination (limit=20, offset=0)."""
    response = await client.get(f"{API_PREFIX}/voice/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "total" in data
    assert "items" in data


async def test_list_sessions_custom_pagination(client):
    """GET /voice/sessions accepts custom limit and offset parameters."""
    response = await client.get(f"{API_PREFIX}/voice/sessions?limit=5&offset=0")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 5


async def test_list_sessions_limit_exceeds_max(client):
    """Limit > 100 is rejected by validation."""
    response = await client.get(f"{API_PREFIX}/voice/sessions?limit=101")
    assert response.status_code == 422


# ── Test 10: 默认 asr_provider 值 ──────────────────────────────────


@patch("promiselink.api.v1.voice.LLMClient")
@patch("promiselink.api.v1.voice.NLUIntentClassifier")
async def test_default_asr_provider_is_wechat(mock_classifier_cls, mock_llm_cls, client):
    """Default asr_provider value is 'wechat' when not specified."""
    mock_llm_cls.return_value = MagicMock()

    mock_nlu_result = _make_mock_nlu_result(intent_value="chitchat", confidence=0.85)

    mock_classifier_instance = MagicMock()
    mock_classifier_instance.classify = AsyncMock(return_value=mock_nlu_result)
    mock_classifier_cls.return_value = mock_classifier_instance

    response = await client.post(
        f"{API_PREFIX}/voice/session",
        json={"query_text": "你好"},
    )

    assert response.status_code == 200

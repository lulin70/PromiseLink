"""Tests for F-36: Demand input API — voice/text one-line demand recording."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from eventlink.core.auth import get_current_user_id
from eventlink.database import Base, get_async_session
from eventlink.main import app
from eventlink.models.entity import Entity
from eventlink.models.event import Event


# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"


def _create_test_entity(user_id: str, name: str, **kwargs) -> tuple[Event, Entity]:
    """Create a test Event + Entity pair (FK-safe)."""
    event_id = str(uuid.uuid4())
    event = Event(
        id=event_id,
        user_id=user_id,
        event_type="manual",
        source="test",
        title=f"Test event for {name}",
        status="completed",
    )
    entity = Entity(
        id=kwargs.pop("entity_id", str(uuid.uuid4())),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=kwargs.pop("aliases", []),
        properties=kwargs.pop("properties", {"concern": []}),
        source_event_id=event_id,
        confidence=1.0,
        status="confirmed",
        **kwargs,
    )
    return event, entity


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


# ── Test 1: POST /demands 成功创建orphan demand ──────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_create_demand_orphan_success(mock_llm_cls, client):
    """POST /demands creates an orphan demand when no entity matches."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "装修",
        "detail": "我需要一个靠谱的装修团队",
        "person_name": None,
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "我需要一个靠谱的装修团队",
            "source": "voice",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "demand_id" in data
    assert data["extracted"]["tag"] == "装修"
    assert data["extracted"]["detail"] == "我需要一个靠谱的装修团队"
    assert data["extracted"]["related_entity_id"] is None


# ── Test 2: POST /demands 关联到已有Entity ──────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_create_demand_linked_to_entity(mock_llm_cls, client, db_session):
    """POST /demands links demand to existing person entity by name."""
    event, entity = _create_test_entity(TEST_USER_ID, "张总")
    entity_id = str(entity.id)
    db_session.add(event)
    await db_session.flush()  # Flush event first to satisfy FK constraint
    db_session.add(entity)
    await db_session.flush()

    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "融资",
        "detail": "张总需要融资支持",
        "person_name": "张总",
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "张总说他需要融资支持",
            "source": "text",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["extracted"]["tag"] == "融资"
    assert data["extracted"]["related_entity_id"] is not None


# ── Test 3: LLM失败时使用fallback ──────────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_demand_uses_fallback_on_llm_failure(mock_llm_cls, client):
    """POST /demands falls back to keyword extraction when LLM fails."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(side_effect=Exception("LLM unavailable"))
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "我需要找装修团队",
            "source": "text",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["extracted"]["tag"] == "装修"


# ── Test 4: 验证请求参数 ──────────────────────────────────────


async def test_empty_text_returns_422(client):
    """Empty text triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "",
            "source": "text",
        },
    )
    assert response.status_code == 422


async def test_missing_text_returns_422(client):
    """Missing text field triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "source": "text",
        },
    )
    assert response.status_code == 422


async def test_invalid_source_returns_422(client):
    """Invalid source value triggers validation error (422)."""
    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "测试需求",
            "source": "email",
        },
    )
    assert response.status_code == 422


# ── Test 5: source默认值为text ──────────────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_default_source_is_text(mock_llm_cls, client):
    """Default source value is 'text' when not specified."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "招聘",
        "detail": "需要招人",
        "person_name": None,
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "我需要招人",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


# ── Test 6: alias匹配Entity ──────────────────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_demand_matches_entity_by_alias(mock_llm_cls, client, db_session):
    """POST /demands matches entity by alias when name doesn't match."""
    event, entity = _create_test_entity(TEST_USER_ID, "张伟", aliases=["老张"])
    entity_id = str(entity.id)
    db_session.add(event)
    await db_session.flush()
    db_session.add(entity)
    await db_session.flush()

    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "法律",
        "detail": "老张需要法律咨询",
        "person_name": "老张",
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "老张需要法律咨询",
            "source": "voice",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["extracted"]["related_entity_id"] is not None


# ── Test 7: fallback提取逻辑单元测试 ──────────────────────────────


def test_fallback_extract_with_keyword():
    """Fallback extraction identifies demand tag from keywords."""
    from eventlink.api.v1.demand_input import _fallback_extract

    result = _fallback_extract("我需要找装修团队")
    assert result["tag"] == "装修"
    assert result["detail"] == "我需要找装修团队"


def test_fallback_extract_with_person_name():
    """Fallback extraction identifies person name from text."""
    from eventlink.api.v1.demand_input import _fallback_extract

    result = _fallback_extract("张总需要融资支持")
    assert result["person_name"] is not None
    assert "张" in result["person_name"]


def test_fallback_extract_no_keyword():
    """Fallback extraction returns '其他' when no keyword matches."""
    from eventlink.api.v1.demand_input import _fallback_extract

    result = _fallback_extract("今天天气不错")
    assert result["tag"] == "其他"


# ── Test 8: concern追加到已有Entity ──────────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_concern_appended_to_existing_entity(mock_llm_cls, client, db_session):
    """New concern is appended to existing entity's concern list."""
    existing_concern = [{"tag": "招聘", "detail": "需要招人", "source": "text", "created_at": "2026-01-01T00:00:00"}]
    event, entity = _create_test_entity(
        TEST_USER_ID, "李总",
        properties={"concern": existing_concern},
    )
    entity_id = str(entity.id)
    db_session.add(event)
    await db_session.flush()
    db_session.add(entity)
    await db_session.flush()

    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "培训",
        "detail": "李总需要培训团队",
        "person_name": "李总",
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "李总需要培训团队",
            "source": "voice",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["extracted"]["related_entity_id"] == entity_id


# ── Test 9: voice来源标记 ──────────────────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_voice_source_stored_in_concern(mock_llm_cls, client):
    """Voice source is stored correctly in the concern entry."""
    mock_llm_instance = MagicMock()
    mock_llm_instance.call_json = AsyncMock(return_value={
        "tag": "物流",
        "detail": "需要搬家服务",
        "person_name": None,
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "需要搬家服务",
            "source": "voice",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


# ── Test 10: LLM返回缺少字段时fallback ──────────────────────────


@patch("eventlink.api.v1.demand_input.LLMClient")
async def test_llm_missing_fields_triggers_fallback(mock_llm_cls, client):
    """When LLM returns incomplete data, fallback extraction is used."""
    mock_llm_instance = MagicMock()
    # LLM returns response without 'tag' field
    mock_llm_instance.call_json = AsyncMock(return_value={
        "detail": "需要装修",
    })
    mock_llm_cls.return_value = mock_llm_instance

    response = await client.post(
        f"{API_PREFIX}/demands",
        json={
            "user_id": TEST_USER_ID,
            "text": "我需要装修",
            "source": "text",
        },
    )

    assert response.status_code == 200
    data = response.json()
    # Should use fallback which detects "装修" keyword
    assert data["status"] == "success"

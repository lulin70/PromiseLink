"""Tests for Entity Relationship Stage API endpoints (F-G2)."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo


# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provide an async DB session for direct data setup."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, db_engine):
    """Provide an httpx.AsyncClient with DB dependency overridden."""

    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Helpers ──


async def _seed_event(session: AsyncSession, **overrides) -> Event:
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "event_type": "meeting",
        "source": "test",
        "title": "Test Event",
        "raw_text": "Test raw text",
        "status": "completed",
    }
    data.update(overrides)
    event = Event(**data)
    session.add(event)
    await session.flush()
    return event


async def _seed_entity(session: AsyncSession, **overrides) -> Entity:
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await _seed_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "entity_type": "person",
        "name": "Test Person",
        "canonical_name": "Test Person",
        "properties": {"basic": {"company": "Test Corp"}},
        "source_event_id": str(source_event_id),
        "confidence": 0.9,
        "status": "confirmed",
    }
    data.update(overrides)
    entity = Entity(**data)
    session.add(entity)
    await session.flush()
    return entity


async def _seed_todo(session: AsyncSession, **overrides) -> Todo:
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await _seed_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "followup",
        "title": "Follow up",
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


# ════════════════════════════════════════════════════════════════════
# GET /entities/stage-map
# ════════════════════════════════════════════════════════════════════


class TestGetStageMap:
    """Tests for GET /api/v1/entities/stage-map."""

    @pytest.mark.asyncio
    async def test_returns_stage_map(self, client: AsyncClient):
        resp = await client.get(f"{API_PREFIX}/entities/stage-map")
        assert resp.status_code == 200
        data = resp.json()

        assert "stages" in data
        stages = data["stages"]
        assert isinstance(stages, list)
        assert len(stages) >= 1

        # Verify each stage has required fields
        for stage in stages:
            assert "value" in stage
            assert "label" in stage
            assert "color" in stage
            assert "icon" in stage
            assert "description" in stage
            assert "order" in stage

    @pytest.mark.asyncio
    async def test_stage_map_contains_all_seven_stages(
        self, client: AsyncClient
    ):
        resp = await client.get(f"{API_PREFIX}/entities/stage-map")
        assert resp.status_code == 200
        stages = resp.json()["stages"]

        expected_values = [
            "new_connection",
            "understanding_needs",
            "value_response",
            "deep_trust",
            "active_cooperation",
            "long_term_partner",
            "dormant",
        ]
        actual_values = [s["value"] for s in stages]
        for val in expected_values:
            assert val in actual_values, f"Missing stage: {val}"

    @pytest.mark.asyncio
    async def test_stages_are_ordered(self, client: AsyncClient):
        resp = await client.get(f"{API_PREFIX}/entities/stage-map")
        assert resp.status_code == 200
        stages = resp.json()["stages"]

        orders = [s["order"] for s in stages]
        assert orders == sorted(orders)


# ════════════════════════════════════════════════════════════════════
# GET /entities/{entity_id}/stage-info
# ════════════════════════════════════════════════════════════════════


class TestGetStageInfo:
    """Tests for GET /api/v1/entities/{entity_id}/stage-info."""

    @pytest.mark.asyncio
    async def test_returns_stage_info_for_existing_entity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="王五")
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}/stage-info"
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["entity_id"] == entity.id
        assert data["name"] == "王五"
        assert "current_stage" in data
        assert "current_stage_label" in data
        assert "current_stage_color" in data
        assert "current_stage_desc" in data
        assert "stage_order" in data

    @pytest.mark.asyncio
    async def test_default_stage_is_new_connection(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="新联系人")
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}/stage-info"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_stage"] == "new_connection"

    @pytest.mark.asyncio
    async def test_entity_with_custom_stage(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(
            db_session,
            name="深度信任",
            properties={
                "basic": {"company": "Test Corp"},
                "relationship_stage": "deep_trust",
            },
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}/stage-info"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_stage"] == "deep_trust"

    @pytest.mark.asyncio
    async def test_nonexistent_entity_returns_404(
        self, client: AsyncClient
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"{API_PREFIX}/entities/{fake_id}/stage-info"
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_other_users_entity_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        other_user_id = str(uuid.uuid4())
        event = await _seed_event(db_session, user_id=other_user_id)
        entity = await _seed_entity(
            db_session, user_id=other_user_id, source_event_id=event.id
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}/stage-info"
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_suggestion_may_be_present(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="有建议的联系人")
        # Add some interaction data to trigger a suggestion
        await _seed_todo(
            db_session,
            related_entity_id=entity.id,
            todo_type="care",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}/stage-info"
        )
        assert resp.status_code == 200
        data = resp.json()
        # suggestion is optional, but if present must have required fields
        if data.get("suggestion"):
            suggestion = data["suggestion"]
            assert "target_stage" in suggestion
            assert "reason" in suggestion

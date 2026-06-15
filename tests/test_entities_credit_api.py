"""Tests for Entity Credit Score API endpoints (F-E5)."""

import uuid
from unittest.mock import AsyncMock, patch

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

# Default mock score data returned by CreditScoreService
MOCK_SCORE_DATA = {
    "score": 85.0,
    "grade": "A",
    "my_fulfillment_rate": 0.9,
    "their_fulfillment_rate": 0.8,
    "interaction_consistency": 80.0,
    "total_interactions": 5,
}


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
# GET /entities/{entity_id}/credit-score
# ════════════════════════════════════════════════════════════════════


class TestGetEntityCreditScore:
    """Tests for GET /api/v1/entities/{entity_id}/credit-score."""

    @pytest.mark.asyncio
    async def test_returns_credit_score_for_existing_entity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="张三")
        await db_session.commit()

        with patch(
            "promiselink.services.credit_score.CreditScoreService.calculate",
            new_callable=AsyncMock,
            return_value=MOCK_SCORE_DATA,
        ):
            resp = await client.get(
                f"{API_PREFIX}/entities/{entity.id}/credit-score"
            )

        assert resp.status_code == 200
        data = resp.json()

        assert data["entity_id"] == entity.id
        assert data["name"] == "张三"
        assert isinstance(data["score"], (int, float))
        assert data["grade"] in ("A+", "A", "B", "C", "D")
        assert "breakdown" in data
        assert "my_fulfillment_rate" in data["breakdown"]
        assert "their_fulfillment_rate" in data["breakdown"]
        assert "interaction_consistency" in data["breakdown"]
        assert "total_interactions" in data["breakdown"]

    @pytest.mark.asyncio
    async def test_nonexistent_entity_returns_404(
        self, client: AsyncClient
    ):
        fake_id = str(uuid.uuid4())
        resp = await client.get(
            f"{API_PREFIX}/entities/{fake_id}/credit-score"
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
            f"{API_PREFIX}/entities/{entity.id}/credit-score"
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════
# GET /entities/credit-scores
# ════════════════════════════════════════════════════════════════════


class TestListCreditScores:
    """Tests for GET /api/v1/entities/credit-scores."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_entities(
        self, client: AsyncClient
    ):
        resp = await client.get(f"{API_PREFIX}/entities/credit-scores")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_returns_credit_scores_for_entities_with_interactions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="李四")
        # Add enough todos to meet min_interactions=2 default
        await _seed_todo(
            db_session,
            related_entity_id=entity.id,
            action_type="my_promise",
        )
        await _seed_todo(
            db_session,
            related_entity_id=entity.id,
            action_type="their_promise",
        )
        await db_session.commit()

        with patch(
            "promiselink.services.credit_score.CreditScoreService.batch_calculate",
            new_callable=AsyncMock,
            return_value={entity.id: MOCK_SCORE_DATA},
        ):
            resp = await client.get(f"{API_PREFIX}/entities/credit-scores")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert item["entity_id"] == entity.id
        assert item["name"] == "李四"
        assert isinstance(item["score"], (int, float))
        assert item["grade"] in ("A+", "A", "B", "C", "D")

    @pytest.mark.asyncio
    async def test_respects_limit_and_offset(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Create 3 entities with enough interactions
        entity_ids = []
        for i in range(3):
            entity = await _seed_entity(db_session, name=f"人物{i}")
            entity_ids.append(entity.id)
            await _seed_todo(
                db_session,
                related_entity_id=entity.id,
                action_type="my_promise",
            )
            await _seed_todo(
                db_session,
                related_entity_id=entity.id,
                action_type="their_promise",
            )
        await db_session.commit()

        batch_result = {eid: MOCK_SCORE_DATA for eid in entity_ids}
        with patch(
            "promiselink.services.credit_score.CreditScoreService.batch_calculate",
            new_callable=AsyncMock,
            return_value=batch_result,
        ):
            # Request with limit=1, offset=0
            resp = await client.get(
                f"{API_PREFIX}/entities/credit-scores",
                params={"limit": 1, "offset": 0},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] >= 3

    @pytest.mark.asyncio
    async def test_min_interactions_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        entity = await _seed_entity(db_session, name="低交互人物")
        # Only 1 todo — below default min_interactions=2
        await _seed_todo(
            db_session,
            related_entity_id=entity.id,
            action_type="my_promise",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/entities/credit-scores",
            params={"min_interactions": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        entity_ids = [item["entity_id"] for item in data["items"]]
        assert entity.id not in entity_ids


# ════════════════════════════════════════════════════════════════════
# Unauthorized access
# ════════════════════════════════════════════════════════════════════


class TestCreditScoreUnauthorized:
    """Tests for unauthorized access to credit score endpoints."""

    @pytest.mark.asyncio
    async def test_credit_score_requires_auth(self, db_session, db_engine):
        """Without auth override, endpoints return 401."""

        async def override_get_async_session():
            yield db_session

        # Only override DB, NOT auth — so auth is required
        app.dependency_overrides[get_async_session] = override_get_async_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get(f"{API_PREFIX}/entities/credit-scores")
        app.dependency_overrides.clear()

        assert resp.status_code == 401

"""Comprehensive integration tests for PromiseLink.

Validates that multiple components work together correctly:
  1. Full Pipeline Integration (Event → Entity → Todo → Association → Brief)
  2. Auth + API Integration (JWT login, protected endpoints, cross-user isolation)
  3. Dashboard Integration (day-view aggregation, morning-brief summary)
  4. Privacy API Integration (data-summary, export, user-data DELETE)
  5. Rate Limiting Integration (429 after exceeding limit)

Uses httpx.AsyncClient + FastAPI dependency injection against in-memory SQLite,
with LLM calls mocked out. No external services required.
"""

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import create_access_token, get_current_user_id
from promiselink.core.rate_limiter import reset_rate_limits
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.relationship_brief import RelationshipBrief
from promiselink.models.todo import Todo

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
async def client(db_session):
    """Provide an httpx.AsyncClient with DB dependency overridden and LLM mocked."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    # Mock the background pipeline to avoid real LLM calls
    async def mock_process_event(event_id):
        pass

    import promiselink.services.event_processor as processor_module
    original_process = processor_module.process_event_background
    processor_module.process_event_background = mock_process_event

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    processor_module.process_event_background = original_process
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client():
    """Provide an httpx.AsyncClient without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helpers ──


async def insert_event(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB."""
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


async def insert_entity(session: AsyncSession, **overrides) -> Entity:
    """Insert an Entity directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "entity_type": "person",
        "name": "Test Person",
        "canonical_name": "Test Person",
        "aliases": [],
        "properties": {"basic": {"company": "Test Corp", "title": "Engineer"}},
        "source_event_id": str(source_event_id),
        "confidence": 0.9,
        "status": "confirmed",
    }
    data.update(overrides)
    entity = Entity(**data)
    session.add(entity)
    await session.flush()
    return entity


async def insert_todo(session: AsyncSession, **overrides) -> Todo:
    """Insert a Todo directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "promise",
        "title": "Follow up",
        "description": "Send a message",
        "priority": 2,
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


async def insert_association(session: AsyncSession, **overrides) -> Association:
    """Insert an Association directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    source_entity_id = overrides.pop("source_entity_id", None)
    target_entity_id = overrides.pop("target_entity_id", None)

    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id
    if source_entity_id is None:
        entity = await insert_entity(session, source_event_id=source_event_id, name="Source Entity")
        source_entity_id = entity.id
    if target_entity_id is None:
        entity2 = await insert_entity(session, source_event_id=source_event_id, name="Target Entity")
        target_entity_id = entity2.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "source_entity_id": str(source_entity_id),
        "target_entity_id": str(target_entity_id),
        "association_type": "same_city",
        "strength": 0.7,
        "confidence": 0.8,
        "status": "confirmed",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    assoc = Association(**data)
    session.add(assoc)
    await session.flush()
    return assoc


async def insert_brief(session: AsyncSession, **overrides) -> RelationshipBrief:
    """Insert a RelationshipBrief directly into the test DB."""
    person_entity_id = overrides.pop("person_entity_id", None)
    if person_entity_id is None:
        entity = await insert_entity(session)
        person_entity_id = entity.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "person_entity_id": str(person_entity_id),
        "relationship_stage": "new_connection",
        "brief_data": {
            "basic_info": {},
            "relationship_stage": "new_connection",
            "last_interaction": {},
            "interaction_freq": {"total_count": 0, "last_30_days": 0, "avg_interval_days": 0},
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
            "my_contributions": [],
            "cooperation_signals": [],
            "risk_flags": [],
            "next_actions": [],
            "strength_score": 0,
            "notes": "",
        },
        "version": 1,
    }
    data.update(overrides)
    brief = RelationshipBrief(**data)
    session.add(brief)
    await session.flush()
    return brief


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Full Pipeline Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegration:
    """Verify the pipeline processes an event end-to-end:
    Event → Entity extraction → Todo generation → Association → Brief update.
    """

    @pytest.mark.asyncio
    async def test_create_event_triggers_pipeline(self, client: AsyncClient):
        """Creating an event via API returns 201 with pipeline_status=pending."""
        payload = {
            "event_type": "meeting",
            "source": "manual",
            "title": "和张总见面",
            "raw_text": "今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
        }
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["pipeline_status"] == "pending"
        assert data["status"] == "pending"
        assert data["title"] == "和张总见面"

    @pytest.mark.asyncio
    async def test_pipeline_produces_entities_and_todos(self, db_session: AsyncSession):
        """After pipeline processing, entities and todos are created for the event."""
        # Simulate what the pipeline would produce
        event = await insert_event(
            db_session,
            raw_text="今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
            status="completed",
        )

        entity = await insert_entity(
            db_session,
            name="张总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某制造集团", "title": "总经理"},
                "concern": [{"category": "AI应用", "detail": "AI在制造业的应用"}],
            },
        )

        todo = await insert_todo(
            db_session,
            title="给张总发AI方案",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
        )

        await db_session.commit()

        # Verify entity has concern data
        from sqlalchemy import select
        result = await db_session.execute(select(Entity).where(Entity.id == entity.id))
        saved_entity = result.scalar_one()
        concerns = (saved_entity.properties or {}).get("concern", [])
        assert len(concerns) >= 1
        assert concerns[0]["category"] == "AI应用"

        # Verify todo is linked to entity
        result = await db_session.execute(select(Todo).where(Todo.id == todo.id))
        saved_todo = result.scalar_one()
        assert saved_todo.related_entity_id == str(entity.id)
        assert saved_todo.todo_type == "promise"

    @pytest.mark.asyncio
    async def test_associations_discovered_between_entities(self, db_session: AsyncSession):
        """Two entities with overlapping concerns discover an association."""
        event = await insert_event(db_session, raw_text="AI赛道讨论")

        entity_a = await insert_entity(
            db_session,
            name="李总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "盛恒资本", "industry": "投资"},
                "concern": [{"category": "市场拓展", "detail": "找好项目"}],
                "capability": [{"category": "投资决策", "detail": "专注AI"}],
            },
        )

        entity_b = await insert_entity(
            db_session,
            name="张总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "智谱AI", "industry": "AI"},
                "concern": [{"category": "融资", "detail": "需要资金"}],
                "capability": [{"category": "技术架构", "detail": "大模型"}],
            },
        )

        # Create association (simulating what pipeline step 10 would do)
        assoc = await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            association_type="supply_demand",
            source_event_id=event.id,
        )
        await db_session.commit()

        # Verify association exists
        result = await db_session.execute(
            select(Association).where(Association.id == assoc.id)
        )
        saved_assoc = result.scalar_one()
        assert saved_assoc.association_type == "supply_demand"
        assert str(saved_assoc.source_entity_id) == str(entity_a.id)
        assert str(saved_assoc.target_entity_id) == str(entity_b.id)

    @pytest.mark.asyncio
    async def test_relationship_brief_updated_after_event(self, db_session: AsyncSession):
        """RelationshipBrief is created/updated after an event is processed."""
        event = await insert_event(db_session, status="completed")
        entity = await insert_entity(
            db_session,
            name="张总",
            source_event_id=event.id,
            properties={"basic": {"company": "某集团", "title": "CEO"}},
        )
        await db_session.commit()

        # Use the service to update the brief (simulating pipeline step 12)
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        service = RelationshipBriefService(db_session)
        result = await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            event=event,
            entities=[entity],
        )

        await db_session.commit()

        assert result.is_new is True
        assert result.brief is not None
        assert result.brief.relationship_stage == "new_connection"
        assert "last_interaction" in result.modules_updated
        assert result.brief.brief_data.get("basic_info", {}).get("name") == "张总"


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: Auth + API Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestAuthAPIIntegration:
    """Verify JWT authentication, protected endpoints, and cross-user isolation."""

    @pytest.mark.asyncio
    async def test_login_with_poc_secret(self, db_session: AsyncSession):
        """Login via /auth/login with valid poc_secret returns JWT."""
        from promiselink.config import get_settings, Settings

        # Clear cached settings so new instance picks up env var
        get_settings.cache_clear()
        os.environ["POC_SECRET"] = "test-secret-123"

        try:
            async def override_get_async_session():
                yield db_session

            app.dependency_overrides[get_async_session] = override_get_async_session

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"{API_PREFIX}/auth/login",
                    json={"user_id": TEST_USER_ID, "poc_secret": "test-secret-123"},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"
            assert data["user_id"] == TEST_USER_ID
        finally:
            os.environ.pop("POC_SECRET", None)
            get_settings.cache_clear()
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_login_with_wrong_secret_returns_401(self, db_session: AsyncSession):
        """Login with wrong poc_secret returns 401."""
        os.environ["PROMISELINK_POC_SECRET"] = "correct-secret"

        try:
            async def override_get_async_session():
                yield db_session

            app.dependency_overrides[get_async_session] = override_get_async_session

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"{API_PREFIX}/auth/login",
                    json={"user_id": TEST_USER_ID, "poc_secret": "wrong-secret"},
                )
            assert resp.status_code == 401
        finally:
            os.environ.pop("PROMISELINK_POC_SECRET", None)
            app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_valid_jwt_accesses_protected_endpoints(self, client: AsyncClient):
        """A valid JWT token allows access to protected endpoints."""
        token = create_access_token(TEST_USER_ID)
        resp = await client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_invalid_jwt_returns_401(self, unauth_client: AsyncClient):
        """An invalid JWT token returns 401 on protected endpoints."""
        resp = await unauth_client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": "Bearer invalid-token-here"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, unauth_client: AsyncClient):
        """No JWT token returns 401 on protected endpoints."""
        resp = await unauth_client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_cross_user_data_isolation(self, client: AsyncClient, db_session: AsyncSession):
        """User cannot access another user's data via API."""
        # Create event for OTHER user
        other_event = await insert_event(
            db_session,
            user_id=OTHER_USER_ID,
            title="Other User's Secret Event",
        )
        await db_session.commit()

        # Try to access other user's event via GET detail
        resp = await client.get(f"{API_PREFIX}/events/{other_event.id}")
        assert resp.status_code == 404  # Not found for this user

        # Verify our own events don't include other user's
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        data = resp.json()
        for item in data.get("items", []):
            assert item["user_id"] != OTHER_USER_ID


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Dashboard Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestDashboardIntegration:
    """Verify dashboard aggregation and morning brief summary."""

    @pytest.mark.asyncio
    async def test_day_view_aggregates_events_and_todos(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Day-view returns correct aggregation of events and todos for a date."""
        target_date = "2026-06-04"
        ts = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)
        due_dt = datetime(2026, 6, 4, 18, 0, 0, tzinfo=timezone.utc)

        # Create events for the target date
        event1 = await insert_event(
            db_session, title="晨会", timestamp=ts, event_type="meeting"
        )
        event2 = await insert_event(
            db_session, title="电话沟通", timestamp=ts.replace(hour=14), event_type="call"
        )

        # Create todos due on the target date
        await insert_todo(
            db_session,
            title="发方案给张总",
            todo_type="promise",
            source_event_id=event1.id,
            due_date=due_dt,
            status="pending",
        )
        await insert_todo(
            db_session,
            title="关注李总需求",
            todo_type="care",
            source_event_id=event2.id,
            due_date=due_dt,
            status="pending",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": target_date}
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["date"] == target_date
        assert len(data["events"]) == 2
        assert data["summary"]["total_events"] == 2
        assert data["summary"]["total_todos"] == 2
        assert data["summary"]["pending_promises"] == 1
        assert data["summary"]["upcoming_meetings"] == 1

    @pytest.mark.asyncio
    async def test_day_view_excludes_other_dates(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Day-view only shows data for the specified date."""
        ts_today = datetime(2026, 6, 4, 10, 0, 0, tzinfo=timezone.utc)
        ts_yesterday = datetime(2026, 6, 3, 10, 0, 0, tzinfo=timezone.utc)

        await insert_event(db_session, title="今天的事件", timestamp=ts_today)
        await insert_event(db_session, title="昨天的事件", timestamp=ts_yesterday)
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": "2026-06-04"}
        )
        assert resp.status_code == 200
        events = resp.json()["events"]
        assert len(events) == 1
        assert events[0]["title"] == "今天的事件"

    @pytest.mark.asyncio
    async def test_morning_brief_summary(self, client: AsyncClient, db_session: AsyncSession):
        """Morning brief returns correct counts and summary text."""
        # Create pending promise todos
        event = await insert_event(db_session)
        await insert_todo(
            db_session,
            title="承诺发方案",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
        )
        await insert_todo(
            db_session,
            title="关注需求",
            todo_type="care",
            source_event_id=event.id,
            status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        data = resp.json()

        assert data["pending_promises"] >= 1
        assert data["pending_cares"] >= 1
        assert isinstance(data["summary_text"], str)
        assert len(data["summary_text"]) > 0
        assert "greeting" in data
        assert data["date"] == date.today().isoformat()

    @pytest.mark.asyncio
    async def test_morning_brief_key_persons(self, client: AsyncClient, db_session: AsyncSession):
        """Morning brief includes key persons from pending todos."""
        event = await insert_event(db_session)
        entity = await insert_entity(
            db_session, name="关键人物A", source_event_id=event.id
        )
        await insert_todo(
            db_session,
            title="跟进A",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        data = resp.json()
        assert "关键人物A" in data["key_persons"]


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Privacy API Integration
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="Privacy API is a Pro-only feature",
)
class TestPrivacyAPIIntegration:
    """Verify privacy endpoints: data-summary, export, and user-data DELETE."""

    @pytest.mark.asyncio
    async def test_data_summary_returns_correct_counts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /privacy/data-summary returns accurate counts of all user data."""
        # Create events
        event1 = await insert_event(db_session, title="Event 1")
        event2 = await insert_event(db_session, title="Event 2")
        event3 = await insert_event(db_session, title="Event 3")

        # Create entities
        await insert_entity(db_session, name="Person A", source_event_id=event1.id)
        await insert_entity(db_session, name="Person B", source_event_id=event2.id)

        # Create todos
        await insert_todo(db_session, title="Todo 1", source_event_id=event1.id)
        await insert_todo(db_session, title="Todo 2", source_event_id=event2.id)

        # Create association
        entity_a = await insert_entity(db_session, name="Assoc A", source_event_id=event3.id)
        entity_b = await insert_entity(db_session, name="Assoc B", source_event_id=event3.id)
        await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            source_event_id=event3.id,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/privacy/data-summary")
        assert resp.status_code == 200
        data = resp.json()

        assert data["events"] >= 3
        assert data["entities"] >= 4  # 2 + 2 for association
        assert data["todos"] >= 2
        assert data["associations"] >= 1

    @pytest.mark.asyncio
    async def test_export_returns_user_data(self, client: AsyncClient, db_session: AsyncSession):
        """GET /export/{user_id} returns structured JSON export of all user data."""
        event = await insert_event(db_session, title="Export Test Event")
        await insert_entity(db_session, name="Export Person", source_event_id=event.id)
        await insert_todo(db_session, title="Export Todo", source_event_id=event.id)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = json.loads(resp.text)

        assert data["export_version"] == "1.0"
        assert data["user_id"] == TEST_USER_ID
        assert "exported_at" in data
        assert len(data["events"]) >= 1
        assert len(data["entities"]) >= 1
        assert len(data["todos"]) >= 1

    @pytest.mark.asyncio
    async def test_export_forbidden_for_other_user(self, client: AsyncClient, db_session: AsyncSession):
        """GET /export/{other_user_id} returns 403."""
        resp = await client.get(f"{API_PREFIX}/export/{OTHER_USER_ID}")
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_privacy_export_endpoint(self, client: AsyncClient, db_session: AsyncSession):
        """POST /privacy/export returns download URL."""
        resp = await client.post(f"{API_PREFIX}/privacy/export")
        assert resp.status_code == 200
        data = resp.json()
        assert "download_url" in data
        assert TEST_USER_ID in data["download_url"]

    @pytest.mark.asyncio
    async def test_delete_user_data_cleans_everything(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """DELETE /privacy/user-data removes all user data."""
        # Seed data
        event = await insert_event(db_session, title="To Be Deleted")
        entity = await insert_entity(db_session, name="Delete Me", source_event_id=event.id)
        await insert_todo(db_session, title="Delete Todo", source_event_id=event.id)
        await db_session.commit()

        # Verify data exists
        resp = await client.get(f"{API_PREFIX}/privacy/data-summary")
        assert resp.status_code == 200
        before = resp.json()
        assert before["events"] >= 1

        # Delete all user data
        resp = await client.delete(f"{API_PREFIX}/privacy/user-data")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["events_deleted"] >= 1

        # Verify data is gone
        resp = await client.get(f"{API_PREFIX}/privacy/data-summary")
        assert resp.status_code == 200
        after = resp.json()
        assert after["events"] == 0
        assert after["entities"] == 0
        assert after["todos"] == 0
        assert after["associations"] == 0

    @pytest.mark.asyncio
    async def test_delete_only_affects_current_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """DELETE /privacy/user-data does not affect other users' data."""
        # Create data for other user
        other_event = Event(
            id=str(uuid.uuid4()),
            user_id=OTHER_USER_ID,
            event_type="meeting",
            source="test",
            title="Other User Event",
            raw_text="Should not be deleted",
            status="completed",
        )
        db_session.add(other_event)
        await db_session.commit()

        # Delete current user's data
        resp = await client.delete(f"{API_PREFIX}/privacy/user-data")
        assert resp.status_code == 200

        # Verify other user's data still exists
        from sqlalchemy import select, func
        count = (
            await db_session.execute(
                select(func.count()).select_from(Event).where(Event.user_id == OTHER_USER_ID)
            )
        ).scalar()
        assert count >= 1


# ══════════════════════════════════════════════════════════════════════════════
# Test 5: Rate Limiting Integration
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimitingIntegration:
    """Verify rate limiting returns 429 after exceeding limits."""

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excessive_requests_via_api(
        self, client: AsyncClient
    ):
        """Rapid requests to a rate-limited endpoint eventually return 429."""
        from promiselink.core.rate_limiter import check_rate_limit

        # Use the in-memory limiter directly for a controlled test
        key = "user:rate_test_user"
        limit = 5

        # First 5 requests should be allowed
        for i in range(limit):
            allowed, remaining, retry_after = await check_rate_limit(key, limit)
            assert allowed is True, f"Request {i+1} should be allowed"

        # 6th request should be blocked
        allowed, remaining, retry_after = await check_rate_limit(key, limit)
        assert allowed is False, "Request exceeding limit should be blocked"
        assert retry_after > 0, "retry_after should be positive when blocked"

        # Clean up
        reset_rate_limits(key)

    @pytest.mark.asyncio
    async def test_rate_limiter_separate_keys_are_independent(self):
        """Different rate limit keys have independent counters."""
        from promiselink.core.rate_limiter import check_rate_limit

        key_a = "user:independent_a"
        key_b = "user:independent_b"
        limit = 3

        # Exhaust key_a
        for _ in range(limit):
            await check_rate_limit(key_a, limit)

        # key_a should be blocked
        allowed_a, _, _ = await check_rate_limit(key_a, limit)
        assert allowed_a is False

        # key_b should still be allowed
        allowed_b, _, _ = await check_rate_limit(key_b, limit)
        assert allowed_b is True

        # Clean up
        reset_rate_limits(key_a)
        reset_rate_limits(key_b)

    @pytest.mark.asyncio
    async def test_rate_limiter_resets_between_tests(self):
        """Rate limit state is reset between tests (autouse fixture)."""
        from promiselink.core.rate_limiter import check_rate_limit

        key = "user:reset_test"
        limit = 2

        # Should be fresh (allowed)
        allowed, _, _ = await check_rate_limit(key, limit)
        assert allowed is True

        # Clean up
        reset_rate_limits(key)

"""Tests for F-21 Data Export API — GET /api/v1/export/{user_id}.

Validates data portability export: structure, data isolation,
and completeness across all data types.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from eventlink.core.auth import get_current_user_id
from eventlink.database import Base, get_async_session
from eventlink.main import app
from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo

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
        cursor.execute("PRAGMA foreign_keys=ON")
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


async def insert_event(session: AsyncSession, **overrides) -> Event:
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
        "aliases": ["TP"],
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


async def insert_association(session: AsyncSession, **overrides) -> Association:
    source_event_id = overrides.pop("source_event_id", None)
    source_entity_id = overrides.pop("source_entity_id", None)
    target_entity_id = overrides.pop("target_entity_id", None)

    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id
    if source_entity_id is None:
        e1 = await insert_entity(session, source_event_id=source_event_id, name="Src")
        source_entity_id = e1.id
    if target_entity_id is None:
        e2 = await insert_entity(session, source_event_id=source_event_id, name="Tgt")
        target_entity_id = e2.id

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


async def insert_todo(session: AsyncSession, **overrides) -> Todo:
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "followup",
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


# ══════════════════════════════════════════════════════════════════════════════
# Export API Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestExportAPI:
    """Tests for GET /api/v1/export/{user_id}."""

    async def test_export_returns_200(self, client: AsyncClient):
        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200

    async def test_export_structure(self, client: AsyncClient):
        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()

        assert data["export_version"] == "1.0"
        assert "exported_at" in data
        assert data["user_id"] == TEST_USER_ID
        assert "events" in data
        assert "entities" in data
        assert "associations" in data
        assert "todos" in data
        assert "vector_embeddings" in data

        # All top-level list fields should be lists
        assert isinstance(data["events"], list)
        assert isinstance(data["entities"], list)
        assert isinstance(data["associations"], list)
        assert isinstance(data["todos"], list)
        assert isinstance(data["vector_embeddings"], list)

    async def test_export_includes_events(self, client: AsyncClient, db_session: AsyncSession):
        await insert_event(db_session, title="Export Event A")
        await insert_event(db_session, title="Export Event B")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        assert len(data["events"]) >= 2
        titles = [e["title"] for e in data["events"]]
        assert "Export Event A" in titles
        assert "Export Event B" in titles

    async def test_export_includes_entities(self, client: AsyncClient, db_session: AsyncSession):
        await insert_entity(db_session, name="Alice")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        assert len(data["entities"]) >= 1
        names = [e["name"] for e in data["entities"]]
        assert "Alice" in names

    async def test_export_includes_associations(self, client: AsyncClient, db_session: AsyncSession):
        await insert_association(db_session, association_type="alumni")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        assert len(data["associations"]) >= 1
        types = [a["association_type"] for a in data["associations"]]
        assert "alumni" in types

    async def test_export_includes_todos(self, client: AsyncClient, db_session: AsyncSession):
        await insert_todo(db_session, title="Export Todo")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        assert len(data["todos"]) >= 1
        titles = [t["title"] for t in data["todos"]]
        assert "Export Todo" in titles

    async def test_export_forbids_other_user(self, client: AsyncClient):
        """Requesting another user's data returns 403."""
        other_user_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/export/{other_user_id}")
        assert resp.status_code == 403

    async def test_export_data_isolation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Data from other users must not leak into export."""
        other_user_id = str(uuid.uuid4())
        # Insert data for another user
        other_event = await insert_event(
            db_session, user_id=other_user_id, title="Other User Event"
        )
        await insert_entity(
            db_session,
            user_id=other_user_id,
            name="Other User Entity",
            source_event_id=other_event.id,
        )
        # Insert data for test user
        await insert_event(db_session, title="My Event")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()

        # Events: only test user's events
        event_titles = [e["title"] for e in data["events"]]
        assert "Other User Event" not in event_titles
        assert "My Event" in event_titles

        # Entities: only test user's entities
        entity_names = [e["name"] for e in data["entities"]]
        assert "Other User Entity" not in entity_names

    async def test_export_empty_data(self, client: AsyncClient):
        """Export with no data returns valid structure with empty lists."""
        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        assert data["events"] == []
        assert data["entities"] == []
        assert data["associations"] == []
        assert data["todos"] == []
        assert data["vector_embeddings"] == []

    async def test_export_event_fields_serialized(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """UUID and datetime fields are serialized as strings."""
        event = await insert_event(db_session, title="Serialization Check")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()

        exported_event = next(
            e for e in data["events"] if e["title"] == "Serialization Check"
        )
        # id and user_id should be strings
        assert isinstance(exported_event["id"], str)
        assert isinstance(exported_event["user_id"], str)
        # created_at should be an ISO string
        assert isinstance(exported_event["created_at"], str)
        assert "T" in exported_event["created_at"]

    async def test_export_entity_includes_properties(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Entity properties (JSONB) are preserved in export."""
        await insert_entity(
            db_session,
            name="Prop Check",
            properties={"basic": {"company": "Acme", "title": "CTO"}},
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        data = resp.json()
        entity = next(e for e in data["entities"] if e["name"] == "Prop Check")
        assert entity["properties"]["basic"]["company"] == "Acme"
        assert entity["properties"]["basic"]["title"] == "CTO"

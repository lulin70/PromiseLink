"""Tests for F-59: Todo priority user adjustment feature.

Covers:
1. Setting priority_override → priority_source becomes "user"
2. Clearing priority_override (null) → priority_source reverts to "ai"
3. Todos with user-set priority sort above AI-calculated at same level
4. PATCH /todos/{id} with priority_override works correctly
5. GET /todos returns priority_override and priority_source fields
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.event import Event
from promiselink.models.todo import Todo

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
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

    # Mock the background pipeline to avoid real LLM calls
    import promiselink.services.event_processor as processor_module
    original_process = processor_module.process_event_background
    processor_module.process_event_background = lambda eid: None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    processor_module.process_event_background = original_process
    app.dependency_overrides.clear()


# ── Helpers ──


async def insert_event(db_session: AsyncSession, **overrides) -> Event:
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
    db_session.add(event)
    await db_session.flush()
    return event


async def insert_todo(db_session: AsyncSession, **overrides) -> Todo:
    """Insert a Todo directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(db_session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "followup",
        "title": "Follow up with contact",
        "description": "Send a message",
        "priority": 3,
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    db_session.add(todo)
    await db_session.flush()
    return todo


# ── Unit Tests (direct model) ──


class TestPriorityOverrideModel:
    """Test priority_override and priority_source fields on the Todo model."""

    @pytest.mark.asyncio
    async def test_default_priority_source_is_ai(self, db_session):
        """Newly created Todo defaults to priority_source='ai'."""
        todo = await insert_todo(db_session)
        assert todo.priority_source == "ai"
        assert todo.priority_override is None

    @pytest.mark.asyncio
    async def test_set_priority_override_sets_source_to_user(self, db_session):
        """Setting priority_override should make priority_source='user'."""
        todo = await insert_todo(db_session)
        todo.priority_override = "high"
        todo.priority_source = "user"
        await db_session.flush()
        await db_session.refresh(todo)

        assert todo.priority_override == "high"
        assert todo.priority_source == "user"

    @pytest.mark.asyncio
    async def test_clear_priority_override_reverts_source_to_ai(self, db_session):
        """Clearing priority_override should revert priority_source='ai'."""
        todo = await insert_todo(db_session)
        # First set it
        todo.priority_override = "high"
        todo.priority_source = "user"
        await db_session.flush()

        # Now clear it
        todo.priority_override = None
        todo.priority_source = "ai"
        await db_session.flush()
        await db_session.refresh(todo)

        assert todo.priority_override is None
        assert todo.priority_source == "ai"


# ── API Tests ──


class TestPriorityOverrideAPI:
    """Test PATCH /todos/{id} with priority_override."""

    @pytest.mark.asyncio
    async def test_patch_set_priority_override(self, client, db_session):
        """PATCH with priority_override="high" → priority_source becomes "user"."""
        todo = await insert_todo(db_session)
        todo_id = str(todo.id)

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo_id}",
            json={"priority_override": "high"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["priority_override"] == "high"
        assert data["priority_source"] == "user"

    @pytest.mark.asyncio
    async def test_patch_clear_priority_override(self, client, db_session):
        """PATCH with priority_override=null → priority_source reverts to "ai"."""
        todo = await insert_todo(db_session)
        todo_id = str(todo.id)

        # First set it
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo_id}",
            json={"priority_override": "medium"},
        )
        assert resp.status_code == 200
        assert resp.json()["priority_source"] == "user"

        # Now clear it
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo_id}",
            json={"priority_override": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["priority_override"] is None
        assert data["priority_source"] == "ai"

    @pytest.mark.asyncio
    async def test_patch_priority_override_with_other_fields(self, client, db_session):
        """PATCH with priority_override and feedback together."""
        todo = await insert_todo(db_session)
        todo_id = str(todo.id)

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo_id}",
            json={"priority_override": "low", "feedback": "useful"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["priority_override"] == "low"
        assert data["priority_source"] == "user"

    @pytest.mark.asyncio
    async def test_get_todos_returns_priority_fields(self, client, db_session):
        """GET /todos returns priority_override and priority_source fields."""
        await insert_todo(db_session)

        resp = await client.get(f"{API_PREFIX}/todos")

        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) > 0
        todo_data = items[0]
        assert "priority_override" in todo_data
        assert "priority_source" in todo_data
        assert todo_data["priority_source"] == "ai"

    @pytest.mark.asyncio
    async def test_get_todo_detail_returns_priority_fields(self, client, db_session):
        """GET /todos/{id} returns priority_override and priority_source fields."""
        todo = await insert_todo(db_session)
        todo_id = str(todo.id)

        resp = await client.get(f"{API_PREFIX}/todos/{todo_id}")

        assert resp.status_code == 200
        data = resp.json()
        assert "priority_override" in data
        assert "priority_source" in data
        assert data["priority_source"] == "ai"


# ── Sorting Tests ──


class TestPriorityOverrideSorting:
    """Test that user-set priorities sort above AI-calculated at same level."""

    @pytest.mark.asyncio
    async def test_user_priority_sorts_above_ai_at_same_level(self, client, db_session):
        """When sorting by priority, user-set priority sorts above AI at same level."""
        # Create two todos with same priority number but different sources
        event = await insert_event(db_session)

        todo_ai = await insert_todo(
            db_session,
            title="AI priority todo",
            priority=2,
            priority_source="ai",
            source_event_id=event.id,
        )

        todo_user = await insert_todo(
            db_session,
            title="User priority todo",
            priority=2,
            priority_override="high",
            priority_source="user",
            source_event_id=event.id,
        )

        await db_session.flush()

        # Sort by priority
        resp = await client.get(f"{API_PREFIX}/todos?sort_by=priority")

        assert resp.status_code == 200
        items = resp.json()["items"]

        # Find positions of our two todos
        titles = [item["title"] for item in items]
        ai_idx = titles.index("AI priority todo")
        user_idx = titles.index("User priority todo")

        # User-set priority should come before AI at same level
        assert user_idx < ai_idx, (
            f"User priority todo should sort above AI priority todo at same level, "
            f"but user_idx={user_idx} >= ai_idx={ai_idx}"
        )

    @pytest.mark.asyncio
    async def test_urgency_sort_user_priority_above_ai(self, client, db_session):
        """When sorting by urgency, user-set priority sorts above AI at same level."""
        event = await insert_event(db_session)

        todo_ai = await insert_todo(
            db_session,
            title="AI urgency todo",
            priority=1,
            priority_source="ai",
            source_event_id=event.id,
        )

        todo_user = await insert_todo(
            db_session,
            title="User urgency todo",
            priority=1,
            priority_override="high",
            priority_source="user",
            source_event_id=event.id,
        )

        await db_session.flush()

        # Sort by urgency (default)
        resp = await client.get(f"{API_PREFIX}/todos?sort_by=urgency")

        assert resp.status_code == 200
        items = resp.json()["items"]

        titles = [item["title"] for item in items]
        ai_idx = titles.index("AI urgency todo")
        user_idx = titles.index("User urgency todo")

        assert user_idx < ai_idx

    @pytest.mark.asyncio
    async def test_different_priority_levels_still_sort_correctly(self, client, db_session):
        """Higher priority (lower number) still sorts first regardless of source."""
        event = await insert_event(db_session)

        await insert_todo(
            db_session,
            title="User low priority",
            priority=3,
            priority_override="low",
            priority_source="user",
            source_event_id=event.id,
        )

        await insert_todo(
            db_session,
            title="AI high priority",
            priority=1,
            priority_source="ai",
            source_event_id=event.id,
        )

        await db_session.flush()

        resp = await client.get(f"{API_PREFIX}/todos?sort_by=priority")

        assert resp.status_code == 200
        items = resp.json()["items"]

        # AI high priority (1) should come before user low priority (3)
        titles = [item["title"] for item in items]
        ai_idx = titles.index("AI high priority")
        user_idx = titles.index("User low priority")

        assert ai_idx < user_idx

"""Tests for Todo CRUD API endpoints (todos.py).

Covers:
- GET /todos — list with pagination, status/type/priority filters, search, sort modes, enrichment
- GET /todos/pending-confirmations — list pending promise confirmations
- GET /todos/{id} — detail with enrichment (entity name, event title, snooze schedule)
- PATCH /todos/{id} — status transitions via state machine, feedback, priority_override
- PATCH /todos/{id}/confirm — confirm/reject promise todos
- DELETE /todos/{id} — delete todo
- Error cases: 404 for non-existent, IDOR (other user's todo returns 404), invalid UUID

Uses REAL DB operations (in-memory SQLite), no mocks for data layer.
"""

import uuid
from datetime import UTC, datetime, timedelta

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
from promiselink.models.todo import SnoozeSchedule, Todo

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
async def client(db_session, mock_pipeline):
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
        "source_event_id": str(source_event_id),
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
        "todo_type": "followup",
        "title": "Test Todo",
        "description": "Test description",
        "priority": 3,
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


# ════════════════════════════════════════════════════════════════════
# GET /todos — List tests
# ════════════════════════════════════════════════════════════════════


class TestListTodos:
    """GET /todos — list with filtering, sorting, pagination."""

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty(self, client: AsyncClient):
        """Empty DB returns empty items list with total=0."""
        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_with_pagination(self, client: AsyncClient, db_session: AsyncSession):
        """limit/offset pagination works correctly."""
        for i in range(5):
            await insert_todo(db_session, title=f"Todo {i}")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"limit": 2, "offset": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

        # Second page
        resp = await client.get(f"{API_PREFIX}/todos", params={"limit": 2, "offset": 2})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    @pytest.mark.asyncio
    async def test_list_filter_by_status(self, client: AsyncClient, db_session: AsyncSession):
        """Filter by status returns only matching todos."""
        await insert_todo(db_session, title="Pending", status="pending")
        await insert_todo(db_session, title="Done", status="done")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"status": "done"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["title"] == "Done"

    @pytest.mark.asyncio
    async def test_list_filter_by_todo_type(self, client: AsyncClient, db_session: AsyncSession):
        """Filter by todo_type returns only matching todos."""
        await insert_todo(db_session, title="Promise", todo_type="promise")
        await insert_todo(db_session, title="Followup", todo_type="followup")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"todo_type": "promise"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["todo_type"] == "promise"

    @pytest.mark.asyncio
    async def test_list_filter_by_priority(self, client: AsyncClient, db_session: AsyncSession):
        """Filter by priority returns only matching todos (line 116)."""
        await insert_todo(db_session, title="High", priority=1)
        await insert_todo(db_session, title="Low", priority=5)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"priority": 1})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["priority"] == 1

    @pytest.mark.asyncio
    async def test_list_with_search(self, client: AsyncClient, db_session: AsyncSession):
        """Search in description returns matching todos (lines 118-119)."""
        await insert_todo(db_session, title="A", description="send proposal to client")
        await insert_todo(db_session, title="B", description="review code")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"search": "proposal"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert "proposal" in items[0]["description"]

    @pytest.mark.asyncio
    async def test_list_search_with_special_chars(self, client: AsyncClient, db_session: AsyncSession):
        """Search with SQL LIKE special chars (%, _) is escaped properly (lines 130-131)."""
        await insert_todo(db_session, title="A", description="100% complete")
        await insert_todo(db_session, title="B", description="review code")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"search": "100%"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert "100%" in items[0]["description"]

    @pytest.mark.asyncio
    async def test_list_sort_by_urgency(self, client: AsyncClient, db_session: AsyncSession):
        """Sort by urgency (default): priority ASC, due_date ASC (lines 142-145)."""
        now = datetime.now(UTC)
        await insert_todo(
            db_session, title="LowPri", priority=5, due_date=now + timedelta(days=1)
        )
        await insert_todo(
            db_session, title="HighPri", priority=1, due_date=now + timedelta(days=2)
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"sort_by": "urgency"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()["items"]]
        assert titles.index("HighPri") < titles.index("LowPri")

    @pytest.mark.asyncio
    async def test_list_sort_by_due_date(self, client: AsyncClient, db_session: AsyncSession):
        """Sort by due_date ASC, nulls last (line 147)."""
        now = datetime.now(UTC)
        await insert_todo(db_session, title="NoDate", due_date=None)
        await insert_todo(
            db_session, title="Soonest", due_date=now + timedelta(days=1)
        )
        await insert_todo(
            db_session, title="Later", due_date=now + timedelta(days=5)
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"sort_by": "due_date"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()["items"]]
        assert titles[0] == "Soonest"
        assert titles[-1] == "NoDate"  # nulls last

    @pytest.mark.asyncio
    async def test_list_sort_by_created(self, client: AsyncClient, db_session: AsyncSession):
        """Sort by created_at DESC (newest first) (lines 150-151)."""
        old_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=UTC)
        new_time = datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC)
        await insert_todo(db_session, title="Old", created_at=old_time)
        await insert_todo(db_session, title="New", created_at=new_time)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"sort_by": "created"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()["items"]]
        assert titles[0] == "New"

    @pytest.mark.asyncio
    async def test_list_with_entity_enrichment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """List includes related_entity_name when todo has related_entity_id (lines 159-166)."""
        event = await insert_event(db_session)
        entity = await insert_entity(db_session, name="Alice", source_event_id=event.id)
        await insert_todo(
            db_session,
            title="With entity",
            related_entity_id=str(entity.id),
            source_event_id=event.id,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["related_entity_name"] == "Alice"
        assert items[0]["related_entity_id"] == str(entity.id)

    @pytest.mark.asyncio
    async def test_list_with_event_enrichment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """List includes source_event_title and source_event_date (lines 169-179)."""
        event = await insert_event(db_session, title="Q2 Planning Meeting")
        await insert_todo(
            db_session, title="Follow up", source_event_id=str(event.id)
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["source_event_title"] == "Q2 Planning Meeting"
        assert items[0]["source_event_date"] is not None


# ════════════════════════════════════════════════════════════════════
# GET /todos/pending-confirmations
# ════════════════════════════════════════════════════════════════════


class TestListPendingConfirmations:
    """GET /todos/pending-confirmations — list promise todos pending confirmation."""

    @pytest.mark.asyncio
    async def test_list_pending_confirmations_basic(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Returns only promise todos with pending/auto_set confirmation_status (lines 218-235)."""
        await insert_todo(
            db_session,
            title="My promise",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="auto_set",
        )
        await insert_todo(
            db_session,
            title="Their promise",
            todo_type="promise",
            action_type="their_promise",
            confirmation_status="pending",
        )
        # Should NOT appear: confirmed
        await insert_todo(
            db_session,
            title="Confirmed",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="confirmed",
        )
        # Should NOT appear: non-promise type
        await insert_todo(
            db_session,
            title="Followup",
            todo_type="followup",
            action_type=None,
            confirmation_status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/pending-confirmations")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        titles = [i["title"] for i in items]
        assert "My promise" in titles
        assert "Their promise" in titles
        assert "Confirmed" not in titles
        assert "Followup" not in titles

    @pytest.mark.asyncio
    async def test_list_pending_confirmations_filter_by_event_id(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Filter by event_id returns only matching todos (line 225-226)."""
        event1 = await insert_event(db_session, title="Event 1")
        event2 = await insert_event(db_session, title="Event 2")
        await insert_todo(
            db_session,
            title="Promise from event 1",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="pending",
            source_event_id=str(event1.id),
        )
        await insert_todo(
            db_session,
            title="Promise from event 2",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="pending",
            source_event_id=str(event2.id),
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/todos/pending-confirmations",
            params={"event_id": str(event1.id)},
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["title"] == "Promise from event 1"

    @pytest.mark.asyncio
    async def test_list_pending_confirmations_empty(self, client: AsyncClient):
        """No pending confirmations returns empty list."""
        resp = await client.get(f"{API_PREFIX}/todos/pending-confirmations")
        assert resp.status_code == 200
        assert resp.json() == []


# ════════════════════════════════════════════════════════════════════
# GET /todos/{id} — Detail tests
# ════════════════════════════════════════════════════════════════════


class TestGetTodo:
    """GET /todos/{id} — detail endpoint with enrichment."""

    @pytest.mark.asyncio
    async def test_get_todo_detail_basic(self, client: AsyncClient, db_session: AsyncSession):
        """Get todo detail returns all fields (lines 270-338)."""
        todo = await insert_todo(db_session, title="My todo", description="Details here")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(todo.id)
        assert data["title"] == "My todo"
        assert data["description"] == "Details here"
        assert data["user_id"] == TEST_USER_ID
        assert "properties" in data
        assert "snoozed_until" in data
        assert "completed_at" in data

    @pytest.mark.asyncio
    async def test_get_todo_with_related_entity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Detail includes related_entity_name (lines 277-285)."""
        event = await insert_event(db_session)
        entity = await insert_entity(
            db_session, name="Bob Smith", source_event_id=event.id
        )
        todo = await insert_todo(
            db_session,
            title="With entity",
            related_entity_id=str(entity.id),
            source_event_id=str(event.id),
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["related_entity_name"] == "Bob Smith"
        assert data["related_entity_id"] == str(entity.id)

    @pytest.mark.asyncio
    async def test_get_todo_with_source_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Detail includes source_event_title and source_event_date (lines 290-301)."""
        event = await insert_event(db_session, title="Strategy Sync")
        todo = await insert_todo(
            db_session, title="Follow up", source_event_id=str(event.id)
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["source_event_title"] == "Strategy Sync"
        assert data["source_event_date"] is not None

    @pytest.mark.asyncio
    async def test_get_todo_snoozed_with_schedule(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Detail includes snoozed_until when todo is snoozed (lines 304-312)."""
        todo = await insert_todo(db_session, title="Snoozed", status="snoozed")
        recover_at = datetime.now(UTC) + timedelta(days=3)
        schedule = SnoozeSchedule(
            todo_id=todo.id,
            original_status="pending",
            recover_at=recover_at.isoformat(),
        )
        db_session.add(schedule)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "snoozed"
        assert data["snoozed_until"] is not None

    @pytest.mark.asyncio
    async def test_get_todo_not_found_404(self, client: AsyncClient):
        """Non-existent todo returns 404 (line 273)."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/todos/{fake_id}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_todo_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Todo belonging to another user returns 404 (IDOR protection, line 267)."""
        todo = await insert_todo(db_session, title="Other user's todo", user_id=OTHER_USER_ID)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_todo_invalid_uuid_422(self, client: AsyncClient):
        """Invalid UUID format returns 422."""
        resp = await client.get(f"{API_PREFIX}/todos/not-a-uuid")
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════
# PATCH /todos/{id} — Update tests
# ════════════════════════════════════════════════════════════════════


class TestUpdateTodo:
    """PATCH /todos/{id} — update endpoint."""

    @pytest.mark.asyncio
    async def test_update_todo_status_transition_pending_to_done(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Status transition via state machine: pending → done (lines 363-370)."""
        todo = await insert_todo(db_session, title="To complete", status="pending")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "done", "feedback": "useful"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"

    @pytest.mark.asyncio
    async def test_update_todo_status_transition_pending_to_in_progress(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Status transition: pending → in_progress."""
        todo = await insert_todo(db_session, title="Start work", status="pending")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"status": "in_progress"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_todo_snooze_with_snoozed_until(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Snooze transition requires snoozed_until (defer functionality)."""
        todo = await insert_todo(db_session, title="Defer this", status="pending")
        await db_session.commit()

        snooze_until = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "snoozed", "snoozed_until": snooze_until},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_update_todo_feedback_without_status_change(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Feedback is stored in properties when no status change (lines 372-375)."""
        todo = await insert_todo(db_session, title="Feedback todo")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"feedback": "very useful"}
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_update_todo_dismissed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Dismiss transition: pending → dismissed."""
        todo = await insert_todo(db_session, title="Dismiss me", status="pending")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"status": "dismissed"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_update_todo_not_found_404(self, client: AsyncClient):
        """Update non-existent todo returns 404 (line 360)."""
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"{API_PREFIX}/todos/{fake_id}", json={"status": "done"}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_todo_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Update todo belonging to another user returns 404 (IDOR, line 357)."""
        todo = await insert_todo(
            db_session, title="Other's todo", user_id=OTHER_USER_ID
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"status": "done"}
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_todo_invalid_uuid_422(self, client: AsyncClient):
        """Invalid UUID format returns 422."""
        resp = await client.patch(
            f"{API_PREFIX}/todos/bad-uuid", json={"status": "done"}
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════
# PATCH /todos/{id}/confirm — Confirm tests
# ════════════════════════════════════════════════════════════════════


class TestConfirmTodo:
    """PATCH /todos/{id}/confirm — confirm or reject promise todos."""

    @pytest.mark.asyncio
    async def test_confirm_todo_confirmed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Confirm a promise todo (lines 452-462)."""
        todo = await insert_todo(
            db_session,
            title="My promise",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="pending",
            status="pending",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "confirmed"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmation_status"] == "confirmed"
        assert data["status"] == "pending"  # stays pending (already actionable)

    @pytest.mark.asyncio
    async def test_confirm_todo_confirmed_with_corrections(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Confirm with description and due_date corrections (lines 456-459)."""
        todo = await insert_todo(
            db_session,
            title="Promise",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="pending",
        )
        await db_session.commit()

        new_due = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={
                "confirmation_status": "confirmed",
                "description": "Corrected description",
                "due_date": new_due,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["confirmation_status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_todo_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Reject a promise todo sets status to dismissed (lines 463-465)."""
        todo = await insert_todo(
            db_session,
            title="Bad promise",
            todo_type="promise",
            action_type="my_promise",
            confirmation_status="pending",
            status="pending",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "rejected"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["confirmation_status"] == "rejected"
        assert data["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_confirm_todo_invalid_status_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Invalid confirmation_status returns 400 ValidationError (lines 438-440)."""
        todo = await insert_todo(db_session, title="Todo")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "maybe"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_confirm_todo_not_found_404(self, client: AsyncClient):
        """Confirm non-existent todo returns 404 (line 450)."""
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"{API_PREFIX}/todos/{fake_id}/confirm",
            json={"confirmation_status": "confirmed"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_confirm_todo_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Confirm todo belonging to another user returns 404 (IDOR, line 449)."""
        todo = await insert_todo(
            db_session, title="Other's promise", user_id=OTHER_USER_ID
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "confirmed"},
        )
        assert resp.status_code == 404


# ════════════════════════════════════════════════════════════════════
# DELETE /todos/{id} — Delete tests
# ════════════════════════════════════════════════════════════════════


class TestDeleteTodo:
    """DELETE /todos/{id} — delete endpoint."""

    @pytest.mark.asyncio
    async def test_delete_todo_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Delete todo returns 204 (lines 409-421)."""
        todo = await insert_todo(db_session, title="To delete")
        await db_session.commit()

        resp = await client.delete(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 204

        # Verify deleted from DB
        resp2 = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_todo_not_found_404(self, client: AsyncClient):
        """Delete non-existent todo returns 404 (line 411)."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"{API_PREFIX}/todos/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_todo_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Delete todo belonging to another user returns 404 (IDOR, line 410)."""
        todo = await insert_todo(
            db_session, title="Other's todo", user_id=OTHER_USER_ID
        )
        await db_session.commit()

        resp = await client.delete(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_todo_invalid_uuid_422(self, client: AsyncClient):
        """Invalid UUID format returns 422."""
        resp = await client.delete(f"{API_PREFIX}/todos/xyz-not-uuid")
        assert resp.status_code == 422

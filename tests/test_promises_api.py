"""Tests for Promise fulfillment tracking API (promises.py).

Covers endpoints NOT already covered by test_promise_followup_enhanced.py:
- GET /promises — list with search filter, custom view, entity/event enrichment, pagination
- PATCH /promises/{id}/fulfillment — IDOR (other user's todo → 404)
- GET /promises/{id}/nudge-draft — exception fallback path, IDOR
- GET /promises/stats — stats with mixed statuses, IDOR isolation

Focuses on lines not covered by existing tests:
- Line 79: else branch for custom view value
- Lines 85-86: search filter in list_promises
- Lines 102-110: entity name enrichment
- Lines 113-123: event title/date enrichment
- Lines 289-300: nudge-draft exception fallback
- IDOR tests for update_fulfillment and nudge-draft

Uses REAL DB operations (in-memory SQLite), no mocks for data layer.
"""

import uuid
from datetime import UTC, datetime, timedelta
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


async def insert_promise_todo(session: AsyncSession, **overrides) -> Todo:
    """Insert a promise-type Todo directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "promise",
        "title": "Test Promise",
        "description": "Test promise description",
        "priority": 2,
        "status": "pending",
        "source_event_id": str(source_event_id),
        "action_type": "my_promise",
        "fulfillment_status": "pending",
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


# ════════════════════════════════════════════════════════════════════
# GET /promises — List tests (focus on uncovered lines)
# ════════════════════════════════════════════════════════════════════


class TestListPromises:
    """GET /promises — list with search, custom view, enrichment, pagination."""

    @pytest.mark.asyncio
    async def test_list_promises_with_search(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Search filter returns only matching promises (lines 85-86)."""
        await insert_promise_todo(
            db_session, description="send technical proposal", title="Proposal"
        )
        await insert_promise_todo(
            db_session, description="review contract terms", title="Contract"
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises", params={"search": "proposal"}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert "proposal" in items[0]["description"]

    @pytest.mark.asyncio
    async def test_list_promises_search_special_chars(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Search with SQL LIKE special chars is escaped (lines 85-86)."""
        await insert_promise_todo(
            db_session, description="100% delivery guarantee", title="Guarantee"
        )
        await insert_promise_todo(
            db_session, description="unrelated task", title="Other"
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises", params={"search": "100%"}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert "100%" in items[0]["description"]

    @pytest.mark.asyncio
    async def test_list_promises_custom_view_returns_both(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Custom view value (not my-promises/their-promises) returns both types (line 79)."""
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="my promise",
            title="MyP",
        )
        await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="their promise",
            title="TheirP",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "all"}
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        # Both my_promise and their_promise should be returned
        action_types = {i["action_type"] for i in items}
        assert "my_promise" in action_types
        assert "their_promise" in action_types

    @pytest.mark.asyncio
    async def test_list_promises_with_entity_enrichment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """List includes entity_name when todo has related_entity_id (lines 102-110)."""
        event = await insert_event(db_session, title="Meeting with Alice")
        entity = await insert_entity(
            db_session, name="Alice Chen", source_event_id=event.id
        )
        await insert_promise_todo(
            db_session,
            title="My promise to Alice",
            description="Send proposal to Alice",
            related_entity_id=str(entity.id),
            source_event_id=str(event.id),
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["entity_name"] == "Alice Chen"
        assert items[0]["entity_id"] == str(entity.id)

    @pytest.mark.asyncio
    async def test_list_promises_with_event_enrichment(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """List includes source_event_title and source_event_date (lines 113-123)."""
        event = await insert_event(db_session, title="Strategy Sync")
        await insert_promise_todo(
            db_session,
            title="Follow up promise",
            description="Send deck after meeting",
            source_event_id=str(event.id),
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["source_event_title"] == "Strategy Sync"
        assert items[0]["source_event_date"] is not None

    @pytest.mark.asyncio
    async def test_list_promises_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """limit/offset pagination works correctly."""
        for i in range(5):
            await insert_promise_todo(
                db_session,
                title=f"Promise {i}",
                description=f"Description {i}",
                due_date=datetime.now(UTC) + timedelta(days=i),
            )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises", params={"limit": 2, "offset": 0}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_promises_idor_isolation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Promises belonging to other users are NOT visible."""
        await insert_promise_todo(
            db_session,
            user_id=OTHER_USER_ID,
            title="Other user's promise",
            description="Should not be visible",
        )
        await insert_promise_todo(
            db_session,
            title="My promise",
            description="Should be visible",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["description"] == "Should be visible"

    @pytest.mark.asyncio
    async def test_list_promises_empty(self, client: AsyncClient):
        """Empty DB returns empty items list."""
        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_promises_sorted_by_due_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Promises sorted by due_date ASC, nulls last (line 96)."""
        now = datetime.now(UTC)
        await insert_promise_todo(
            db_session,
            title="NoDate",
            description="No due date",
            due_date=None,
        )
        await insert_promise_todo(
            db_session,
            title="Soonest",
            description="Due soon",
            due_date=now + timedelta(days=1),
        )
        await insert_promise_todo(
            db_session,
            title="Later",
            description="Due later",
            due_date=now + timedelta(days=5),
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        descs = [i["description"] for i in resp.json()["items"]]
        assert descs[0] == "Due soon"
        assert descs[-1] == "No due date"


# ════════════════════════════════════════════════════════════════════
# PATCH /promises/{id}/fulfillment — IDOR and error cases
# ════════════════════════════════════════════════════════════════════


class TestUpdateFulfillment:
    """PATCH /promises/{id}/fulfillment — IDOR and error cases."""

    @pytest.mark.asyncio
    async def test_update_fulfillment_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Fulfillment update on other user's todo returns 404 (IDOR, lines 166-169)."""
        todo = await insert_promise_todo(
            db_session,
            user_id=OTHER_USER_ID,
            title="Other's promise",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_update_fulfillment_invalid_status_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Invalid fulfillment_status returns 400 ValidationError (line 163-164)."""
        todo = await insert_promise_todo(db_session, title="My promise")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "invalid_xyz"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_update_fulfillment_not_found_404(self, client: AsyncClient):
        """Fulfillment update on non-existent todo returns 404 (line 168-169)."""
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"{API_PREFIX}/promises/{fake_id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_fulfillment_overdue_sets_overdue_notified_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Marking overdue sets overdue_notified_at (lines 184-185)."""
        todo = await insert_promise_todo(db_session, title="Overdue promise")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "overdue"},
        )
        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "overdue"

    @pytest.mark.asyncio
    async def test_update_fulfillment_their_promise_overdue_logs_manual_mark(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Manual overdue mark on their_promise is allowed and logged (lines 172-179)."""
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            title="Their promise",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "overdue"},
        )
        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "overdue"


# ════════════════════════════════════════════════════════════════════
# GET /promises/{id}/nudge-draft — exception fallback and IDOR
# ════════════════════════════════════════════════════════════════════


class TestNudgeDraft:
    """GET /promises/{id}/nudge-draft — exception fallback and IDOR tests."""

    @pytest.mark.asyncio
    async def test_nudge_draft_exception_returns_fallback(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """When generate_gentle_nudge raises, fallback message is returned (lines 289-300)."""
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            title="Their promise",
            description="对方答应给资料",
        )
        await db_session.commit()

        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new_callable=AsyncMock,
            side_effect=RuntimeError("LLM service unavailable"),
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_fallback"] is True
        assert "不着急" in data["nudge_text"]
        assert data["todo_id"] == str(todo.id)

    @pytest.mark.asyncio
    async def test_nudge_draft_idor_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Nudge draft for other user's todo returns 404 (IDOR, lines 258-261)."""
        todo = await insert_promise_todo(
            db_session,
            user_id=OTHER_USER_ID,
            action_type="their_promise",
            title="Other's promise",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/{todo.id}/nudge-draft")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"

    @pytest.mark.asyncio
    async def test_nudge_draft_my_promise_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Nudge draft for my_promise type returns 400 ValidationError (lines 264-265)."""
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            title="My promise",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/{todo.id}/nudge-draft")
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    @pytest.mark.asyncio
    async def test_nudge_draft_not_found_404(self, client: AsyncClient):
        """Nudge draft for non-existent todo returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/promises/{fake_id}/nudge-draft")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nudge_draft_generated_and_cached(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Generated nudge is cached in properties._nlg_draft (lines 302-311)."""
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            title="Their promise",
            description="对方答应下周给方案",
        )
        await db_session.commit()

        generated_text = "李总，之前提到的方案不知进展如何？ — via PromiseLink"
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new_callable=AsyncMock,
            return_value=generated_text,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        assert resp.status_code == 200
        assert resp.json()["nudge_text"] == generated_text
        assert resp.json()["is_fallback"] is False

        # Second call should hit cache (generate_gentle_nudge not called again)
        mock_gen = AsyncMock(return_value="should_not_be_called")
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new=mock_gen,
        ):
            resp2 = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )
        assert resp2.status_code == 200
        assert resp2.json()["nudge_text"] == generated_text
        mock_gen.assert_not_called()


# ════════════════════════════════════════════════════════════════════
# GET /promises/stats — Stats tests (IDOR isolation)
# ════════════════════════════════════════════════════════════════════


class TestPromiseStats:
    """GET /promises/stats — statistics endpoint."""

    @pytest.mark.asyncio
    async def test_stats_idor_isolation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Other users' promises are NOT counted in stats."""
        # Other user's promises (should NOT be counted)
        await insert_promise_todo(
            db_session,
            user_id=OTHER_USER_ID,
            action_type="my_promise",
            fulfillment_status="fulfilled",
            title="Other's fulfilled",
        )
        # My promises
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            fulfillment_status="pending",
            title="My pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1  # Only my promise
        assert data["my_promises"]["pending"] == 1
        assert data["my_promises"]["fulfilled"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_all_statuses(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Stats correctly counts all fulfillment statuses (lines 209-228)."""
        # my_promise with all 4 statuses
        for status in ["pending", "fulfilled", "overdue", "expired"]:
            await insert_promise_todo(
                db_session,
                action_type="my_promise",
                fulfillment_status=status,
                title=f"My {status}",
            )
        # their_promise with 2 statuses
        for status in ["pending", "fulfilled"]:
            await insert_promise_todo(
                db_session,
                action_type="their_promise",
                fulfillment_status=status,
                title=f"Their {status}",
            )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 6
        assert data["my_promises"] == {
            "pending": 1, "fulfilled": 1, "overdue": 1, "expired": 1
        }
        assert data["their_promises"]["pending"] == 1
        assert data["their_promises"]["fulfilled"] == 1
        # fulfillment_rate = fulfilled / total = 2/6
        assert data["fulfillment_rate"] == round(2 / 6, 3)

    @pytest.mark.asyncio
    async def test_stats_empty_returns_zeros(self, client: AsyncClient):
        """Empty DB returns all-zero stats."""
        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["fulfillment_rate"] == 0.0
        assert data["my_promises"] == {
            "pending": 0, "fulfilled": 0, "overdue": 0, "expired": 0
        }
        assert data["their_promises"] == {
            "pending": 0, "fulfilled": 0, "overdue": 0, "expired": 0
        }

    @pytest.mark.asyncio
    async def test_stats_fulfillment_rate_calculation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """fulfillment_rate = (my_fulfilled + their_fulfilled) / total (lines 224-226)."""
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            fulfillment_status="fulfilled",
            title="My fulfilled 1",
        )
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            fulfillment_status="fulfilled",
            title="My fulfilled 2",
        )
        await insert_promise_todo(
            db_session,
            action_type="their_promise",
            fulfillment_status="fulfilled",
            title="Their fulfilled",
        )
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            fulfillment_status="pending",
            title="My pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 4
        # 3 fulfilled out of 4 total
        assert data["fulfillment_rate"] == round(3 / 4, 3)

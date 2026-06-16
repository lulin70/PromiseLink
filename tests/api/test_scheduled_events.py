"""Comprehensive tests for ScheduledEvent API endpoints.

Covers: CRUD, record conversion, cancel, overdue marking,
cancelled cleanup, boundary conditions, and dashboard integration.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.scheduled_event import ScheduledEvent

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"
FUTURE_DT = (datetime.now(UTC) + timedelta(days=7)).isoformat()
PAST_DT = (datetime.now(UTC) - timedelta(days=1)).isoformat()


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

    # Restore
    processor_module.process_event_background = original_process
    app.dependency_overrides.clear()


# ── Helpers ──


async def create_scheduled_event_via_api(
    client: AsyncClient, **overrides
) -> dict:
    """Create a scheduled event via POST and return the response JSON."""
    payload = {
        "scheduled_at": FUTURE_DT,
        "topic": "Test scheduled event",
        "event_type": "meeting",
    }
    payload.update(overrides)
    resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
    assert resp.status_code == 201, f"Failed to create: {resp.text}"
    return resp.json()


async def insert_scheduled_event(
    session: AsyncSession, **overrides
) -> ScheduledEvent:
    """Insert a ScheduledEvent directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "scheduled_at": datetime.now(UTC) + timedelta(days=7),
        "topic": "Test scheduled event",
        "event_type": "meeting",
        "status": "pending",
    }
    data.update(overrides)
    se = ScheduledEvent(**data)
    session.add(se)
    await session.flush()
    return se


# ══════════════════════════════════════════════════════════════════════════════
# Happy Path Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateScheduledEvent:
    """1. POST /scheduled-events — create a scheduled event."""

    @pytest.mark.asyncio
    async def test_create_returns_201(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "与张总讨论新项目",
            "event_type": "meeting",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["topic"] == "与张总讨论新项目"
        assert data["event_type"] == "meeting"
        assert data["status"] == "pending"
        assert data["user_id"] == TEST_USER_ID
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data

    @pytest.mark.asyncio
    async def test_create_with_participants_and_location(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "项目评审会",
            "event_type": "meeting",
            "participants": [{"name": "李总", "company": "ABC科技"}],
            "location": "望京SOHO",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["participants"] is not None
        assert len(data["participants"]) == 1
        assert data["participants"][0]["name"] == "李总"
        assert data["location"] == "望京SOHO"

    @pytest.mark.asyncio
    async def test_create_with_metadata(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "带元数据的日程",
            "event_type": "call",
            "metadata": {"priority": "high", "project": "PromiseLink"},
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        # FastAPI serializes using alias by default; alias="metadata_" → key is "metadata_"
        assert data["metadata_"]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_create_default_event_type_is_meeting(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "默认类型",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 201
        assert resp.json()["event_type"] == "meeting"


class TestListScheduledEvents:
    """2. GET /scheduled-events — list scheduled events."""

    @pytest.mark.asyncio
    async def test_list_returns_200(self, client: AsyncClient):
        await create_scheduled_event_via_api(client, topic="Event A")
        await create_scheduled_event_via_api(client, topic="Event B")

        resp = await client.get(f"{API_PREFIX}/scheduled-events")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 2

    @pytest.mark.asyncio
    async def test_list_empty_returns_empty_items(self, client: AsyncClient):
        resp = await client.get(f"{API_PREFIX}/scheduled-events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    @pytest.mark.asyncio
    async def test_list_pagination(self, client: AsyncClient):
        for i in range(5):
            await create_scheduled_event_via_api(client, topic=f"Page item {i}")

        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"limit": 2, "offset": 0}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 0


class TestGetScheduledEvent:
    """3. GET /scheduled-events/{id} — get detail."""

    @pytest.mark.asyncio
    async def test_get_detail_returns_200(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client, topic="Detail test")

        resp = await client.get(f"{API_PREFIX}/scheduled-events/{created['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == created["id"]
        assert data["topic"] == "Detail test"
        assert "scheduled_at" in data
        assert "status" in data


class TestUpdateScheduledEvent:
    """4. PATCH /scheduled-events/{id} — update a scheduled event."""

    @pytest.mark.asyncio
    async def test_update_topic_returns_200(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client, topic="Original")

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"topic": "Updated topic"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["topic"] == "Updated topic"

    @pytest.mark.asyncio
    async def test_update_location(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"location": "中关村"},
        )
        assert resp.status_code == 200
        assert resp.json()["location"] == "中关村"

    @pytest.mark.asyncio
    async def test_update_event_type(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client, event_type="meeting")

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"event_type": "call"},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "call"


class TestRecordScheduledEvent:
    """5. POST /scheduled-events/{id}/record — record a scheduled event."""

    @pytest.mark.asyncio
    async def test_record_returns_200(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client, topic="待记录会议")

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "会议讨论了项目进展和下一步计划"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scheduled_event_id"] == created["id"]
        assert "event_id" in data
        assert data["pipeline_status"] == "pending"

    @pytest.mark.asyncio
    async def test_record_with_event_type_override(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(
            client, event_type="meeting"
        )

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "电话沟通内容", "event_type": "call"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data


class TestCancelScheduledEvent:
    """6. POST /scheduled-events/{id}/cancel — cancel a scheduled event."""

    @pytest.mark.asyncio
    async def test_cancel_returns_200(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancel_reason"] is None


class TestDeleteScheduledEvent:
    """7. DELETE /scheduled-events/{id} — delete a scheduled event."""

    @pytest.mark.asyncio
    async def test_delete_returns_204(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.delete(
            f"{API_PREFIX}/scheduled-events/{created['id']}"
        )
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = await client.get(
            f"{API_PREFIX}/scheduled-events/{created['id']}"
        )
        assert get_resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Error Case Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateWithInvalidEventType:
    """8. Create with invalid event_type."""

    @pytest.mark.asyncio
    async def test_invalid_event_type_returns_400(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "Bad type",
            "event_type": "invalid_type",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data


class TestRecordAlreadyRecordedEvent:
    """9. Record an already recorded event."""

    @pytest.mark.asyncio
    async def test_record_recorded_event_returns_409(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        # First record succeeds
        resp1 = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "First recording"},
        )
        assert resp1.status_code == 200

        # Second record should fail
        resp2 = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "Second recording"},
        )
        assert resp2.status_code == 409
        data = resp2.json()
        assert "error" in data


class TestCancelAlreadyCancelledEvent:
    """10. Cancel an already cancelled event."""

    @pytest.mark.asyncio
    async def test_cancel_cancelled_event_returns_409(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        # First cancel succeeds
        resp1 = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={},
        )
        assert resp1.status_code == 200

        # Second cancel should fail
        resp2 = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={},
        )
        assert resp2.status_code == 409


class TestUpdateRecordedEvent:
    """11. Update a recorded event."""

    @pytest.mark.asyncio
    async def test_update_recorded_event_returns_400(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client, topic="Original")

        # Record it first
        await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "Recorded content"},
        )

        # Try to update — should fail
        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"topic": "Should not work"},
        )
        assert resp.status_code == 400


class TestGetNonExistentScheduledEvent:
    """12. Get non-existent scheduled event."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_404(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/scheduled-events/{fake_id}")
        assert resp.status_code == 404


class TestRecordRawTextExceedsLimit:
    """13. Record with raw_text exceeding 500KB."""

    @pytest.mark.asyncio
    async def test_raw_text_over_500kb_returns_400(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        # Generate text > 500KB (512000 bytes)
        big_text = "A" * 512001
        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": big_text},
        )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Boundary Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateWithPastScheduledAt:
    """14. Create with scheduled_at in the past (should auto-mark as overdue)."""

    @pytest.mark.asyncio
    async def test_past_scheduled_at_marks_overdue(self, client: AsyncClient):
        payload = {
            "scheduled_at": PAST_DT,
            "topic": "过期的日程",
            "event_type": "meeting",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "overdue"


class TestUpdateScheduledAtToPast:
    """15. Update scheduled_at to past (should mark overdue)."""

    @pytest.mark.asyncio
    async def test_update_to_past_marks_overdue(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)
        assert created["status"] == "pending"

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"scheduled_at": PAST_DT},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "overdue"


class TestUpdateScheduledAtToFuture:
    """16. Update scheduled_at to future (overdue should revert to pending)."""

    @pytest.mark.asyncio
    async def test_overdue_reverts_to_pending_on_future_update(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Create an overdue event directly in DB
        se = await insert_scheduled_event(
            db_session,
            scheduled_at=datetime.now(UTC) - timedelta(days=1),
            status="overdue",
        )
        await db_session.commit()

        far_future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{se.id}",
            json={"scheduled_at": far_future},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"


class TestCreateWithEmptyTopic:
    """17. Create with empty topic (should fail validation)."""

    @pytest.mark.asyncio
    async def test_empty_topic_returns_422(self, client: AsyncClient):
        payload = {
            "scheduled_at": FUTURE_DT,
            "topic": "",
            "event_type": "meeting",
        }
        resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
        # Pydantic min_length=1 triggers FastAPI 422
        assert resp.status_code == 422


class TestListWithStatusFilter:
    """18. List with status filter."""

    @pytest.mark.asyncio
    async def test_filter_by_pending_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Create one pending and one cancelled
        await create_scheduled_event_via_api(client, topic="Pending one")

        se_cancelled = await insert_scheduled_event(
            db_session, status="cancelled", topic="Cancelled one"
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"status": "pending"}
        )
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["status"] == "pending"

    @pytest.mark.asyncio
    async def test_filter_by_invalid_status_returns_400(self, client: AsyncClient):
        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"status": "invalid_status"}
        )
        assert resp.status_code == 400


class TestCancelWithOptionalReason:
    """19. Cancel with optional reason."""

    @pytest.mark.asyncio
    async def test_cancel_with_reason(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={"cancel_reason": "对方临时有事"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancel_reason"] == "对方临时有事"

    @pytest.mark.asyncio
    async def test_cancel_without_reason(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancel_reason"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestRecordCreatesEventWithSource:
    """20. Record creates Event with source='scheduled_record'."""

    @pytest.mark.asyncio
    async def test_recorded_event_has_scheduled_record_source(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        created = await create_scheduled_event_via_api(
            client, topic="记录来源测试"
        )

        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "测试记录来源"},
        )
        assert record_resp.status_code == 200
        event_id = record_resp.json()["event_id"]

        # Verify the Event in DB has source='scheduled_record'
        from promiselink.models.event import Event
        from sqlalchemy import select

        result = await db_session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one_or_none()
        assert event is not None
        assert event.source == "scheduled_record"
        assert event.title == "记录来源测试"


class TestRecordTriggersPipeline:
    """21. Record triggers pipeline (Event status transitions)."""

    @pytest.mark.asyncio
    async def test_recorded_event_status_is_pending(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        created = await create_scheduled_event_via_api(client)

        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "Pipeline trigger test"},
        )
        assert record_resp.status_code == 200
        data = record_resp.json()
        assert data["pipeline_status"] == "pending"

        # Verify the ScheduledEvent is now recorded
        se_resp = await client.get(
            f"{API_PREFIX}/scheduled-events/{created['id']}"
        )
        assert se_resp.json()["status"] == "recorded"
        assert se_resp.json()["linked_event_id"] is not None
        assert se_resp.json()["recorded_at"] is not None


class TestMarkOverdueScheduledEvents:
    """22. mark_overdue_scheduled_events function."""

    @pytest.mark.asyncio
    async def test_marks_pending_as_overdue(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import mark_overdue_scheduled_events

        # Insert a pending event with past scheduled_at
        await insert_scheduled_event(
            db_session,
            scheduled_at=datetime.now(UTC) - timedelta(hours=2),
            status="pending",
        )
        await db_session.commit()

        count = await mark_overdue_scheduled_events(db_session)
        assert count == 1

        # Verify the event is now overdue
        from sqlalchemy import select

        result = await db_session.execute(
            select(ScheduledEvent).where(
                ScheduledEvent.user_id == TEST_USER_ID
            )
        )
        events = result.scalars().all()
        overdue_events = [e for e in events if e.status == "overdue"]
        assert len(overdue_events) >= 1

    @pytest.mark.asyncio
    async def test_does_not_affect_future_pending(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import mark_overdue_scheduled_events

        # Insert a pending event with future scheduled_at
        await insert_scheduled_event(
            db_session,
            scheduled_at=datetime.now(UTC) + timedelta(days=7),
            status="pending",
        )
        await db_session.commit()

        count = await mark_overdue_scheduled_events(db_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_does_not_affect_recorded_events(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import mark_overdue_scheduled_events

        # Insert a recorded event with past scheduled_at
        await insert_scheduled_event(
            db_session,
            scheduled_at=datetime.now(UTC) - timedelta(hours=2),
            status="recorded",
        )
        await db_session.commit()

        count = await mark_overdue_scheduled_events(db_session)
        assert count == 0


class TestCleanupCancelledScheduledEvents:
    """23. cleanup_cancelled_scheduled_events function."""

    @pytest.mark.asyncio
    async def test_deletes_old_cancelled_events(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import cleanup_cancelled_scheduled_events

        # Insert a cancelled event with updated_at > 30 days ago
        old_cancelled = ScheduledEvent(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            scheduled_at=datetime.now(UTC) - timedelta(days=60),
            topic="Old cancelled",
            event_type="meeting",
            status="cancelled",
            updated_at=datetime.now(UTC) - timedelta(days=31),
        )
        db_session.add(old_cancelled)
        await db_session.commit()

        count = await cleanup_cancelled_scheduled_events(db_session)
        assert count == 1

    @pytest.mark.asyncio
    async def test_does_not_delete_recent_cancelled(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import cleanup_cancelled_scheduled_events

        # Insert a recently cancelled event
        await insert_scheduled_event(
            db_session,
            status="cancelled",
            topic="Recent cancelled",
        )
        await db_session.commit()

        count = await cleanup_cancelled_scheduled_events(db_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_does_not_delete_pending_events(self, db_session: AsyncSession):
        from promiselink.api.v1.scheduled_events import cleanup_cancelled_scheduled_events

        # Insert a very old pending event
        old_pending = ScheduledEvent(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            scheduled_at=datetime.now(UTC) - timedelta(days=60),
            topic="Old pending",
            event_type="meeting",
            status="pending",
            updated_at=datetime.now(UTC) - timedelta(days=31),
        )
        db_session.add(old_pending)
        await db_session.commit()

        count = await cleanup_cancelled_scheduled_events(db_session)
        assert count == 0


class TestDashboardDayViewIncludesScheduledEvents:
    """24. Dashboard day-view includes scheduled_events."""

    @pytest.mark.asyncio
    async def test_day_view_includes_scheduled_events(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        # Create a scheduled event for today (using UTC+8 local time to match dashboard logic)
        _CST = timezone(timedelta(hours=8))
        now_local = datetime.now(_CST)
        # Set scheduled time to 1 hour from now, but ensure it stays within today
        today_scheduled_local = now_local + timedelta(hours=1)
        # If that pushes past midnight, use a time earlier today instead
        if today_scheduled_local.date() != now_local.date():
            today_scheduled_local = now_local.replace(hour=15, minute=0, second=0, microsecond=0)
        # Convert to naive UTC for database storage (dashboard queries in UTC range)
        today_scheduled = today_scheduled_local.astimezone(timezone.utc).replace(tzinfo=None)

        await insert_scheduled_event(
            db_session,
            scheduled_at=today_scheduled,
            topic="今天的日程",
            status="pending",
        )
        await db_session.commit()

        # Get today's day-view
        from datetime import date

        today_str = date.today().isoformat()
        resp = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": today_str}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "scheduled_events" in data
        # The scheduled event should appear (either in today's list or overdue list)
        topics = [se["topic"] for se in data["scheduled_events"]]
        assert "今天的日程" in topics

    @pytest.mark.asyncio
    async def test_day_view_summary_includes_schedule_counts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _CST = timezone(timedelta(hours=8))
        now_local = datetime.now(_CST)
        future_today_local = now_local + timedelta(hours=1)
        # If that pushes past midnight, use a time earlier today instead
        if future_today_local.date() != now_local.date():
            future_today_local = now_local.replace(hour=15, minute=0, second=0, microsecond=0)
        # Convert to naive UTC for database storage
        future_today = future_today_local.astimezone(timezone.utc).replace(tzinfo=None)

        await insert_scheduled_event(
            db_session,
            scheduled_at=future_today,
            topic="Pending schedule",
            status="pending",
        )
        await db_session.commit()

        from datetime import date

        today_str = date.today().isoformat()
        resp = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": today_str}
        )
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert "pending_schedules" in summary
        assert "overdue_schedules" in summary


# ══════════════════════════════════════════════════════════════════════════════
# Additional Edge Case Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestDeleteNonPendingEvent:
    """Delete a recorded/cancelled event should fail."""

    @pytest.mark.asyncio
    async def test_delete_recorded_event_returns_400(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        # Record it first
        await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "Some content"},
        )

        # Try to delete
        resp = await client.delete(
            f"{API_PREFIX}/scheduled-events/{created['id']}"
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_delete_cancelled_event_returns_400(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        # Cancel it first
        await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={},
        )

        # Try to delete
        resp = await client.delete(
            f"{API_PREFIX}/scheduled-events/{created['id']}"
        )
        assert resp.status_code == 400


class TestUpdateInvalidEventType:
    """Update with invalid event_type should fail."""

    @pytest.mark.asyncio
    async def test_update_invalid_event_type_returns_400(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(client)

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{created['id']}",
            json={"event_type": "nonexistent"},
        )
        assert resp.status_code == 400


class TestRecordOverdueEvent:
    """Recording an overdue event should succeed."""

    @pytest.mark.asyncio
    async def test_record_overdue_event_succeeds(self, client: AsyncClient):
        # Create with past scheduled_at → status=overdue
        created = await create_scheduled_event_via_api(
            client, scheduled_at=PAST_DT
        )
        assert created["status"] == "overdue"

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "补录内容"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data


class TestCancelOverdueEvent:
    """Cancelling an overdue event should succeed."""

    @pytest.mark.asyncio
    async def test_cancel_overdue_event_succeeds(self, client: AsyncClient):
        created = await create_scheduled_event_via_api(
            client, scheduled_at=PAST_DT
        )
        assert created["status"] == "overdue"

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/cancel",
            json={"cancel_reason": "已过期取消"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"


class TestRecordEventMetadata:
    """Record should store scheduled_event_id in Event metadata."""

    @pytest.mark.asyncio
    async def test_event_metadata_contains_scheduled_info(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        created = await create_scheduled_event_via_api(
            client, topic="元数据测试", location="会议室A"
        )

        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{created['id']}/record",
            json={"raw_text": "元数据内容"},
        )
        assert record_resp.status_code == 200
        event_id = record_resp.json()["event_id"]

        from promiselink.models.event import Event
        from sqlalchemy import select

        result = await db_session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one_or_none()
        assert event is not None
        assert event.metadata_ is not None
        assert event.metadata_.get("scheduled_event_id") == created["id"]
        assert event.metadata_.get("location") == "会议室A"

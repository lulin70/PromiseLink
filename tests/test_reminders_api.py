"""Comprehensive tests for /api/v1/reminders endpoints (F-69 Smart Follow-up Reminders).

Covers:
  - GET  /reminders/daily         — fatigue/quiet-hours filtering, classification, sorting
  - POST /reminders/{todo_id}/action — completed/snoozed/dismissed + ReminderLog update
  - POST /reminders/batch-action   — batch operations (partial failure, DB state)
  - GET  /reminders/preferences    — default vs custom preferences
  - PATCH /reminders/preferences   — update + validation + create-on-absence
  - Unit tests for _is_quiet_hours and _classify_reminder_type helpers

Note: some batch-action edge cases (IDOR, invalid action, snooze-without-hours,
empty/>50 ids) are also covered in test_reminder_batch_privacy.py. The batch
tests here focus on DB-state verification and partial-failure scenarios to
avoid pure duplication while still ensuring full line coverage.
"""

import uuid
from datetime import UTC, datetime, time, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.api.v1 import reminders as reminders_module
from promiselink.api.v1.reminders import _classify_reminder_type, _is_quiet_hours
from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.event import Event
from promiselink.models.reminder import ReminderLog, ReminderPreference
from promiselink.models.todo import Todo

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000002"
API_PREFIX = "/api/v1"


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
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
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session):
    """Authenticated client for TEST_USER_ID with DB dependency overridden."""

    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Helpers ──


async def insert_event(
    session: AsyncSession, user_id: str = TEST_USER_ID, **overrides
) -> Event:
    data = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "event_type": "meeting",
        "source": "manual",
        "title": "Test Event",
        "raw_text": "Test raw text",
        "status": "completed",
    }
    data.update(overrides)
    event = Event(**data)
    session.add(event)
    await session.flush()
    return event


async def insert_todo(
    session: AsyncSession,
    *,
    user_id: str = TEST_USER_ID,
    title: str = "Test todo",
    todo_type: str = "followup",
    status: str = "pending",
    priority: int = 2,
    dynamic_score: float | None = None,
    due_date: datetime | None = None,
    properties: dict | None = None,
    source_event_id: str | None = None,
    reminder_at: datetime | None = None,
) -> Todo:
    if source_event_id is None:
        event = await insert_event(session, user_id=user_id)
        source_event_id = str(event.id)
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=source_event_id,
        title=title,
        todo_type=todo_type,
        status=status,
        priority=priority,
        dynamic_score=dynamic_score,
        due_date=due_date,
        properties=properties,
        reminder_at=reminder_at,
    )
    session.add(todo)
    await session.flush()
    return todo


async def insert_reminder_log(
    session: AsyncSession,
    *,
    user_id: str = TEST_USER_ID,
    todo_id: str,
    reminder_type: str = "followup",
    sent_at: datetime | None = None,
    action_taken: str | None = None,
) -> ReminderLog:
    log = ReminderLog(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_id=todo_id,
        reminder_type=reminder_type,
        sent_at=sent_at or datetime.now(UTC),
        action_taken=action_taken,
    )
    session.add(log)
    await session.flush()
    return log


async def insert_preference(
    session: AsyncSession,
    *,
    user_id: str = TEST_USER_ID,
    preferred_times: list[str] | None = None,
    fatigue_threshold: int = 5,
    quiet_hours_start: time = time(22, 0),
    quiet_hours_end: time = time(8, 0),
) -> ReminderPreference:
    pref = ReminderPreference(
        user_id=user_id,
        preferred_times=preferred_times or ["09:00", "20:00"],
        fatigue_threshold=fatigue_threshold,
        quiet_hours_start=quiet_hours_start,
        quiet_hours_end=quiet_hours_end,
    )
    session.add(pref)
    await session.flush()
    return pref


class _FakeDateTime:
    """Stand-in for ``datetime`` in the reminders module to control 'now'.

    Only ``now(tz=...)`` is invoked by the module; the return value is a real
    datetime so subsequent ``.time()`` / ``.replace()`` calls work normally.
    """

    _fixed: datetime = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed.astimezone(tz)
        return cls._fixed


# ════════════════════════════════════════════════════════════════════
# GET /reminders/daily
# ════════════════════════════════════════════════════════════════════


class TestGetDailyReminders:
    """GET /reminders/daily — fatigue, quiet-hours, sorting, classification."""

    @pytest.mark.asyncio
    async def test_empty_todos_returns_empty(self, client, db_session):
        """No todos → empty items, total_pending=0, fatigue_remaining=5 (default)."""
        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["items"] == []
        assert body["total_pending"] == 0
        assert body["fatigue_remaining"] == 5  # default threshold, no logs

    @pytest.mark.asyncio
    async def test_returns_items_sorted_by_dynamic_score(self, client, db_session):
        """Items returned sorted by dynamic_score descending."""
        await insert_todo(db_session, title="low", dynamic_score=0.3)
        await insert_todo(db_session, title="high", dynamic_score=0.9)
        await insert_todo(db_session, title="mid", dynamic_score=0.6)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_pending"] == 3
        scores = [item["dynamic_score"] for item in body["items"]]
        assert scores == [0.9, 0.6, 0.3]

    @pytest.mark.asyncio
    async def test_fatigue_limiting_with_preference(self, client, db_session):
        """fatigue_threshold=2, 3 todos → only 2 returned; fatigue_remaining=0."""
        await insert_preference(db_session, fatigue_threshold=2)
        for i in range(3):
            await insert_todo(db_session, title=f"t{i}", dynamic_score=0.5 + i * 0.01)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_pending"] == 3
        assert len(body["items"]) == 2  # limited by fatigue_threshold
        assert body["fatigue_remaining"] == 0  # 2 - 2

    @pytest.mark.asyncio
    async def test_fatigue_from_sent_logs(self, client, db_session):
        """Default threshold=5, 3 logs sent today → fatigue_remaining=2, 3 todos → 2 items."""
        todo = await insert_todo(db_session, title="t1", dynamic_score=0.9)
        await insert_todo(db_session, title="t2", dynamic_score=0.8)
        await insert_todo(db_session, title="t3", dynamic_score=0.7)

        # Seed 3 reminder logs sent today (count towards fatigue)
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        for _ in range(3):
            await insert_reminder_log(
                db_session, todo_id=str(todo.id), sent_at=today_start + timedelta(hours=1)
            )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_pending"] == 3
        assert len(body["items"]) == 2  # 5 - 3 = 2 remaining

    @pytest.mark.asyncio
    async def test_quiet_hours_active(self, client, db_session):
        """Mock now=23:30 → within 22:00-08:00 → is_quiet_hours=true."""
        await insert_todo(db_session, title="t1", dynamic_score=0.5)
        await db_session.commit()

        _FakeDateTime._fixed = datetime(2026, 7, 5, 23, 30, 0, tzinfo=UTC)
        with patch.object(reminders_module, "datetime", _FakeDateTime):
            resp = await client.get(f"{API_PREFIX}/reminders/daily")

        assert resp.status_code == 200, resp.text
        assert resp.json()["is_quiet_hours"] is True

    @pytest.mark.asyncio
    async def test_quiet_hours_inactive(self, client, db_session):
        """Mock now=14:00 → outside 22:00-08:00 → is_quiet_hours=false."""
        await insert_todo(db_session, title="t1", dynamic_score=0.5)
        await db_session.commit()

        _FakeDateTime._fixed = datetime(2026, 7, 5, 14, 0, 0, tzinfo=UTC)
        with patch.object(reminders_module, "datetime", _FakeDateTime):
            resp = await client.get(f"{API_PREFIX}/reminders/daily")

        assert resp.status_code == 200, resp.text
        assert resp.json()["is_quiet_hours"] is False

    @pytest.mark.asyncio
    async def test_custom_preferences_used(self, client, db_session):
        """Custom quiet hours (12:00-14:00) with now=13:00 → is_quiet_hours=true."""
        await insert_preference(
            db_session,
            fatigue_threshold=3,
            quiet_hours_start=time(12, 0),
            quiet_hours_end=time(14, 0),
        )
        await insert_todo(db_session, title="t1", dynamic_score=0.5)
        await db_session.commit()

        _FakeDateTime._fixed = datetime(2026, 7, 5, 13, 0, 0, tzinfo=UTC)
        with patch.object(reminders_module, "datetime", _FakeDateTime):
            resp = await client.get(f"{API_PREFIX}/reminders/daily")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["is_quiet_hours"] is True
        assert body["fatigue_remaining"] == 2  # 3 - 1 item returned

    @pytest.mark.asyncio
    async def test_default_preferences_when_no_row(self, client, db_session):
        """No ReminderPreference row → default fatigue_threshold=5."""
        await insert_todo(db_session, title="t1", dynamic_score=0.5)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # 1 todo returned, fatigue 5-0=5, then 5-1=4 remaining
        assert len(body["items"]) == 1
        assert body["fatigue_remaining"] == 4

    @pytest.mark.asyncio
    async def test_classify_reminder_types_via_endpoint(self, client, db_session):
        """Verify _classify_reminder_type returns correct type for each todo_type."""
        # Use a high fatigue_threshold so all 6 todos are returned
        await insert_preference(db_session, fatigue_threshold=10)
        # promise overdue → promise_due
        await insert_todo(
            db_session,
            title="overdue_promise",
            todo_type="promise",
            due_date=datetime(2020, 1, 1, tzinfo=UTC),
            dynamic_score=0.99,
        )
        # followup → followup
        await insert_todo(
            db_session,
            title="followup_todo",
            todo_type="followup",
            dynamic_score=0.95,
        )
        # care → stage_suggestion
        await insert_todo(
            db_session,
            title="care_todo",
            todo_type="care",
            dynamic_score=0.90,
        )
        # cooperation_signal → stage_suggestion
        await insert_todo(
            db_session,
            title="coop_todo",
            todo_type="cooperation_signal",
            dynamic_score=0.85,
        )
        # risk → followup
        await insert_todo(
            db_session,
            title="risk_todo",
            todo_type="risk",
            dynamic_score=0.80,
        )
        # dormant_contact hint (on a followup todo — hint takes precedence)
        await insert_todo(
            db_session,
            title="dormant_todo",
            todo_type="followup",
            properties={"reminder_hint": "dormant_contact"},
            dynamic_score=0.75,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200, resp.text
        items = resp.json()["items"]
        by_title = {item["title"]: item["reminder_type"] for item in items}
        assert by_title["overdue_promise"] == "promise_due"
        assert by_title["followup_todo"] == "followup"
        assert by_title["care_todo"] == "stage_suggestion"
        assert by_title["coop_todo"] == "stage_suggestion"
        assert by_title["risk_todo"] == "followup"
        assert by_title["dormant_todo"] == "dormant_contact"

    @pytest.mark.asyncio
    async def test_logs_created_for_returned_items(self, client, db_session):
        """GET /daily creates ReminderLog entries for each returned item."""
        await insert_todo(db_session, title="t1", dynamic_score=0.9)
        await insert_todo(db_session, title="t2", dynamic_score=0.8)
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/daily")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

        # Verify 2 ReminderLog entries were created
        result = await db_session.execute(
            select(ReminderLog).where(ReminderLog.user_id == TEST_USER_ID)
        )
        logs = result.scalars().all()
        assert len(logs) == 2


# ════════════════════════════════════════════════════════════════════
# POST /reminders/{todo_id}/action
# ════════════════════════════════════════════════════════════════════


class TestTakeReminderAction:
    """POST /reminders/{todo_id}/action — single todo action + log update."""

    @pytest.mark.asyncio
    async def test_action_completed(self, client, db_session):
        """action=completed → todo.status=done, completed_at set."""
        todo = await insert_todo(db_session, title="t1", status="pending")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["new_status"] == "done"
        assert body["action"] == "completed"

        # Verify DB state
        await db_session.refresh(todo)
        assert todo.status == "done"
        assert todo.completed_at is not None

    @pytest.mark.asyncio
    async def test_action_snoozed_with_hours(self, client, db_session):
        """action=snoozed with snooze_hours → status=snoozed, reminder_at updated."""
        todo = await insert_todo(db_session, title="t1", status="pending")
        await db_session.commit()
        original_reminder_at = todo.reminder_at

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "snoozed", "snooze_hours": 12},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["new_status"] == "snoozed"

        await db_session.refresh(todo)
        assert todo.status == "snoozed"
        assert todo.reminder_at is not None
        assert todo.reminder_at != original_reminder_at

    @pytest.mark.asyncio
    async def test_action_snoozed_without_hours(self, client, db_session):
        """action=snoozed WITHOUT snooze_hours → 400 ValidationError."""
        todo = await insert_todo(db_session, title="t1")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "snoozed"},
        )
        assert resp.status_code == 400
        assert "snooze_hours" in resp.text

    @pytest.mark.asyncio
    async def test_action_dismissed(self, client, db_session):
        """action=dismissed → todo.status=dismissed."""
        todo = await insert_todo(db_session, title="t1", status="pending")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "dismissed"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_status"] == "dismissed"

        await db_session.refresh(todo)
        assert todo.status == "dismissed"

    @pytest.mark.asyncio
    async def test_invalid_action(self, client, db_session):
        """Invalid action → 400 ValidationError."""
        todo = await insert_todo(db_session, title="t1")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "delete"},
        )
        assert resp.status_code == 400
        assert "Invalid action" in resp.text

    @pytest.mark.asyncio
    async def test_nonexistent_todo(self, client, db_session):
        """Non-existent todo → 404 NotFoundError."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"{API_PREFIX}/reminders/{fake_id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 404
        assert "not found" in resp.text.lower()

    @pytest.mark.asyncio
    async def test_idor_other_user_todo(self, client, db_session):
        """Other user's todo → 404 (IDOR protection, not 403 to hide existence)."""
        other_todo = await insert_todo(db_session, user_id=OTHER_USER_ID, title="secret")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{other_todo.id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reminder_log_updated(self, client, db_session):
        """Action updates ReminderLog: action_taken + response_latency_seconds set."""
        todo = await insert_todo(db_session, title="t1")
        # Seed a reminder log sent 60 seconds ago
        sent_at = datetime.now(UTC) - timedelta(seconds=60)
        log = await insert_reminder_log(
            db_session, todo_id=str(todo.id), sent_at=sent_at
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 200, resp.text

        # Verify log updated
        await db_session.refresh(log)
        assert log.action_taken == "completed"
        assert log.response_latency_seconds is not None
        assert log.response_latency_seconds >= 60

    @pytest.mark.asyncio
    async def test_reminder_log_naive_sent_at(self, client, db_session):
        """Naive sent_at (no tzinfo) does not crash — tests the timezone fix (line 284)."""
        todo = await insert_todo(db_session, title="t1")
        # Explicitly naive datetime — SQLite stores/returns it naive
        naive_sent_at = datetime(2026, 7, 5, 10, 0, 0)
        log = await insert_reminder_log(
            db_session, todo_id=str(todo.id), sent_at=naive_sent_at
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 200, resp.text

        await db_session.refresh(log)
        assert log.action_taken == "completed"
        assert log.response_latency_seconds is not None

    @pytest.mark.asyncio
    async def test_action_without_existing_log(self, client, db_session):
        """Action succeeds even when no prior ReminderLog exists (log update skipped)."""
        todo = await insert_todo(db_session, title="t1")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            json={"action": "completed"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["new_status"] == "done"


# ════════════════════════════════════════════════════════════════════
# POST /reminders/batch-action
# ════════════════════════════════════════════════════════════════════


class TestBatchReminderAction:
    """POST /reminders/batch-action — batch ops with DB-state verification.

    Edge cases (IDOR, invalid action, snooze-without-hours, empty/>50 ids)
    are also covered in test_reminder_batch_privacy.py. Tests here focus on
    partial-failure and DB-state verification for full line coverage.
    """

    @pytest.mark.asyncio
    async def test_batch_all_success_with_db_state(self, client, db_session):
        """2 todos completed → success=2, failed=[]; completed_at set in DB."""
        t1 = await insert_todo(db_session, title="t1", status="pending")
        t2 = await insert_todo(db_session, title="t2", status="pending")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(t1.id), str(t2.id)], "action": "completed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["success"]) == 2
        assert len(body["failed"]) == 0
        for item in body["success"]:
            assert item["new_status"] == "done"

        # Verify DB state
        await db_session.refresh(t1)
        await db_session.refresh(t2)
        assert t1.status == "done"
        assert t1.completed_at is not None
        assert t2.status == "done"
        assert t2.completed_at is not None

    @pytest.mark.asyncio
    async def test_batch_partial_failure(self, client, db_session):
        """2 valid + 1 invalid (other user) → success=2, failed=1."""
        own1 = await insert_todo(db_session, title="own1")
        own2 = await insert_todo(db_session, title="own2")
        other = await insert_todo(db_session, user_id=OTHER_USER_ID, title="other")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={
                "todo_ids": [str(own1.id), str(own2.id), str(other.id)],
                "action": "completed",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["success"]) == 2
        assert len(body["failed"]) == 1
        assert body["failed"][0]["todo_id"] == str(other.id)
        assert "forbidden" in body["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_snooze_updates_reminder_at(self, client, db_session):
        """Snooze batch sets snoozed status and updates reminder_at in DB."""
        t1 = await insert_todo(db_session, title="t1", reminder_at=datetime(2020, 1, 1, tzinfo=UTC))
        await db_session.commit()
        old_reminder_at = t1.reminder_at

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(t1.id)], "action": "snoozed", "snooze_hours": 6},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"][0]["new_status"] == "snoozed"

        await db_session.refresh(t1)
        assert t1.status == "snoozed"
        assert t1.reminder_at != old_reminder_at

    @pytest.mark.asyncio
    async def test_batch_dismiss_success(self, client, db_session):
        """Batch dismiss sets dismissed status."""
        t1 = await insert_todo(db_session, title="t1")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(t1.id)], "action": "dismissed"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"][0]["new_status"] == "dismissed"

        await db_session.refresh(t1)
        assert t1.status == "dismissed"

    @pytest.mark.asyncio
    async def test_batch_empty_ids_rejected(self, client, db_session):
        """Empty todo_ids → 422 (min_length=1)."""
        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [], "action": "completed"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_over_fifty_ids_rejected(self, client, db_session):
        """>50 todo_ids → 422 (max_length=50)."""
        ids = [str(uuid.uuid4()) for _ in range(51)]
        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": ids, "action": "completed"},
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════
# GET /reminders/preferences
# ════════════════════════════════════════════════════════════════════


class TestGetPreferences:
    """GET /reminders/preferences — default vs custom preferences."""

    @pytest.mark.asyncio
    async def test_no_preference_returns_defaults(self, client, db_session):
        """No ReminderPreference row → returns defaults (09:00/20:00, 5, 22:00-08:00)."""
        resp = await client.get(f"{API_PREFIX}/reminders/preferences")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == TEST_USER_ID
        assert body["preferred_times"] == ["09:00", "20:00"]
        assert body["fatigue_threshold"] == 5
        assert body["quiet_hours_start"] == "22:00"
        assert body["quiet_hours_end"] == "08:00"

    @pytest.mark.asyncio
    async def test_with_preference_returns_custom(self, client, db_session):
        """With preference row → returns custom values."""
        await insert_preference(
            db_session,
            preferred_times=["08:00", "12:00", "18:00"],
            fatigue_threshold=10,
            quiet_hours_start=time(23, 0),
            quiet_hours_end=time(7, 0),
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/reminders/preferences")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["preferred_times"] == ["08:00", "12:00", "18:00"]
        assert body["fatigue_threshold"] == 10
        assert body["quiet_hours_start"] == "23:00"
        assert body["quiet_hours_end"] == "07:00"


# ════════════════════════════════════════════════════════════════════
# PATCH /reminders/preferences
# ════════════════════════════════════════════════════════════════════


class TestUpdatePreferences:
    """PATCH /reminders/preferences — update + validation + create-on-absence."""

    @pytest.mark.asyncio
    async def test_update_fatigue_threshold(self, client, db_session):
        """Update fatigue_threshold → returns updated value."""
        await insert_preference(db_session, fatigue_threshold=5)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"fatigue_threshold": 10},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["fatigue_threshold"] == 10

    @pytest.mark.asyncio
    async def test_update_quiet_hours(self, client, db_session):
        """Update quiet_hours → returns updated times."""
        await insert_preference(db_session)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"quiet_hours_start": "23:30", "quiet_hours_end": "06:30"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["quiet_hours_start"] == "23:30"
        assert body["quiet_hours_end"] == "06:30"

    @pytest.mark.asyncio
    async def test_update_preferred_times(self, client, db_session):
        """Update preferred_times → returns updated list."""
        await insert_preference(db_session)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"preferred_times": ["07:00", "11:00", "15:00", "19:00"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["preferred_times"] == ["07:00", "11:00", "15:00", "19:00"]

    @pytest.mark.asyncio
    async def test_fatigue_threshold_zero_rejected(self, client, db_session):
        """fatigue_threshold=0 → 422 (ge=1)."""
        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"fatigue_threshold": 0},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_fatigue_threshold_over_twenty_rejected(self, client, db_session):
        """fatigue_threshold=21 → 422 (le=20)."""
        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"fatigue_threshold": 21},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_invalid_quiet_hours_start_format(self, client, db_session):
        """Invalid quiet_hours_start format → 400 ValidationError."""
        await insert_preference(db_session)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"quiet_hours_start": "25:99"},
        )
        assert resp.status_code == 400
        assert "quiet_hours_start" in resp.text

    @pytest.mark.asyncio
    async def test_invalid_quiet_hours_end_format(self, client, db_session):
        """Invalid quiet_hours_end format → 400 ValidationError."""
        await insert_preference(db_session)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"quiet_hours_end": "not-a-time"},
        )
        assert resp.status_code == 400
        assert "quiet_hours_end" in resp.text

    @pytest.mark.asyncio
    async def test_creates_preference_when_none_exists(self, client, db_session):
        """PATCH with no existing preference row → creates with defaults then updates."""
        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={"fatigue_threshold": 8},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["fatigue_threshold"] == 8
        # Defaults preserved for unset fields
        assert body["preferred_times"] == ["09:00", "20:00"]
        assert body["quiet_hours_start"] == "22:00"
        assert body["quiet_hours_end"] == "08:00"

    @pytest.mark.asyncio
    async def test_update_all_fields_at_once(self, client, db_session):
        """Update all fields in a single request."""
        await insert_preference(db_session)
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            json={
                "preferred_times": ["06:00", "12:00"],
                "fatigue_threshold": 15,
                "quiet_hours_start": "23:00",
                "quiet_hours_end": "07:00",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["preferred_times"] == ["06:00", "12:00"]
        assert body["fatigue_threshold"] == 15
        assert body["quiet_hours_start"] == "23:00"
        assert body["quiet_hours_end"] == "07:00"


# ════════════════════════════════════════════════════════════════════
# Unit tests: _is_quiet_hours helper (lines 97-104)
# ════════════════════════════════════════════════════════════════════


class TestIsQuietHours:
    """Unit tests for _is_quiet_hours covering all branches."""

    def test_crosses_midnight_in_range_late_evening(self):
        """22:00-08:00, now=23:00 → True (>= 22:00)."""
        assert _is_quiet_hours(time(22, 0), time(8, 0), time(23, 0)) is True

    def test_crosses_midnight_in_range_early_morning(self):
        """22:00-08:00, now=03:00 → True (< 08:00)."""
        assert _is_quiet_hours(time(22, 0), time(8, 0), time(3, 0)) is True

    def test_crosses_midnight_not_in_range(self):
        """22:00-08:00, now=14:00 → False."""
        assert _is_quiet_hours(time(22, 0), time(8, 0), time(14, 0)) is False

    def test_crosses_midnight_at_start_boundary(self):
        """22:00-08:00, now=22:00 → True (inclusive start)."""
        assert _is_quiet_hours(time(22, 0), time(8, 0), time(22, 0)) is True

    def test_crosses_midnight_at_end_boundary(self):
        """22:00-08:00, now=08:00 → False (exclusive end)."""
        assert _is_quiet_hours(time(22, 0), time(8, 0), time(8, 0)) is False

    def test_same_day_in_range(self):
        """12:00-14:00, now=13:00 → True."""
        assert _is_quiet_hours(time(12, 0), time(14, 0), time(13, 0)) is True

    def test_same_day_not_in_range(self):
        """12:00-14:00, now=15:00 → False."""
        assert _is_quiet_hours(time(12, 0), time(14, 0), time(15, 0)) is False

    def test_same_day_at_start_boundary(self):
        """12:00-14:00, now=12:00 → True (inclusive start)."""
        assert _is_quiet_hours(time(12, 0), time(14, 0), time(12, 0)) is True

    def test_same_day_at_end_boundary(self):
        """12:00-14:00, now=14:00 → False (exclusive end)."""
        assert _is_quiet_hours(time(12, 0), time(14, 0), time(14, 0)) is False

    def test_defaults_to_real_now(self):
        """When now=None, uses real datetime.now() — just verify it returns a bool."""
        result = _is_quiet_hours(time(22, 0), time(8, 0))
        assert isinstance(result, bool)


# ════════════════════════════════════════════════════════════════════
# Unit tests: _classify_reminder_type helper (lines 107-129)
# ════════════════════════════════════════════════════════════════════


class TestClassifyReminderType:
    """Unit tests for _classify_reminder_type covering all branches."""

    def test_promise_overdue(self):
        """promise with past due_date → promise_due."""
        todo = Todo(todo_type="promise", due_date=datetime(2020, 1, 1, tzinfo=UTC))
        assert _classify_reminder_type(todo) == "promise_due"

    def test_promise_not_yet_due(self):
        """promise with future due_date → falls through to default followup."""
        todo = Todo(todo_type="promise", due_date=datetime(2099, 1, 1, tzinfo=UTC))
        assert _classify_reminder_type(todo) == "followup"

    def test_promise_naive_due_date(self):
        """promise with naive past due_date → promise_due (tzinfo added)."""
        todo = Todo(todo_type="promise", due_date=datetime(2020, 1, 1))
        assert _classify_reminder_type(todo) == "promise_due"

    def test_promise_no_due_date(self):
        """promise with no due_date → default followup."""
        todo = Todo(todo_type="promise", due_date=None)
        assert _classify_reminder_type(todo) == "followup"

    def test_followup_type(self):
        """followup → followup (early return)."""
        todo = Todo(todo_type="followup")
        assert _classify_reminder_type(todo) == "followup"

    def test_care_type(self):
        """care → stage_suggestion (type_map)."""
        todo = Todo(todo_type="care")
        assert _classify_reminder_type(todo) == "stage_suggestion"

    def test_cooperation_signal_type(self):
        """cooperation_signal → stage_suggestion (type_map)."""
        todo = Todo(todo_type="cooperation_signal")
        assert _classify_reminder_type(todo) == "stage_suggestion"

    def test_risk_type(self):
        """risk → followup (type_map)."""
        todo = Todo(todo_type="risk")
        assert _classify_reminder_type(todo) == "followup"

    def test_help_type(self):
        """help → followup (type_map)."""
        todo = Todo(todo_type="help")
        assert _classify_reminder_type(todo) == "followup"

    def test_dormant_contact_hint(self):
        """properties.reminder_hint=dormant_contact → dormant_contact."""
        todo = Todo(todo_type="followup", properties={"reminder_hint": "dormant_contact"})
        assert _classify_reminder_type(todo) == "dormant_contact"

    def test_stage_suggestion_hint(self):
        """properties.reminder_hint=stage_suggestion → stage_suggestion."""
        todo = Todo(todo_type="followup", properties={"reminder_hint": "stage_suggestion"})
        assert _classify_reminder_type(todo) == "stage_suggestion"

    def test_empty_properties(self):
        """Empty properties dict → type_map default."""
        todo = Todo(todo_type="care", properties={})
        assert _classify_reminder_type(todo) == "stage_suggestion"

    def test_none_properties(self):
        """None properties → type_map default."""
        todo = Todo(todo_type="risk", properties=None)
        assert _classify_reminder_type(todo) == "followup"

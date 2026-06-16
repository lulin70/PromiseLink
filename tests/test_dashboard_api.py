"""Unit tests for Dashboard API (day-view / range-view endpoints)."""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

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
TARGET_DATE = "2026-06-04"  # Fixed test target date (Thursday)


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


# ── Helper: seed test data ──


async def _seed_event(
    session: AsyncSession,
    title: str,
    event_type: str = "meeting",
    days_offset: int = 0,
    hour: int = 10,
    status: str = "completed",
    input_scope: str | None = None,
) -> Event:
    """Create a test Event record anchored to TARGET_DATE."""
    target = date(2026, 6, 4) + timedelta(days=days_offset)
    ts = datetime(target.year, target.month, target.day, hour, 0, 0, tzinfo=timezone.utc)
    evt = Event(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        event_type=event_type,
        source="test",
        title=title,
        timestamp=ts,
        status=status,
        input_scope=input_scope,
    )
    session.add(evt)
    await session.flush()
    return evt


async def _seed_todo(
    session: AsyncSession,
    title: str,
    todo_type: str = "promise",
    days_offset: int = 0,
    status: str = "pending",
    action_type: str | None = None,
    related_entity_id: uuid.UUID | None = None,
    source_event: Event | None = None,
) -> Todo:
    """Create a test Todo record anchored to TARGET_DATE."""
    target = date(2026, 6, 4) + timedelta(days=days_offset)
    due_dt = datetime(target.year, target.month, target.day, 18, 0, 0, tzinfo=timezone.utc)
    # Use provided event or create a dummy one for FK compliance
    evt_id = str(source_event.id) if source_event else str(uuid.uuid4())
    td = Todo(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        todo_type=todo_type,
        title=title,
        due_date=due_dt,
        status=status,
        action_type=action_type,
        source_event_id=evt_id,
        related_entity_id=str(related_entity_id) if related_entity_id else None,
    )
    session.add(td)
    await session.flush()
    return td


async def _seed_person_entity(
    session: AsyncSession, name: str, source_event: Event
) -> Entity:
    """Create a test person entity linked to a real event (FK safe)."""
    ent = Entity(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        entity_type="person",
        name=name,
        canonical_name=name,
        source_event_id=str(source_event.id),
    )
    session.add(ent)
    await session.flush()
    return ent


# ════════════════════════════════════════════════════════════════════
# Day View Tests
# ════════════════════════════════════════════════════════════════════


class TestDayViewNoParams:
    """Test 1: GET /day-view without parameters returns data for '今天'."""

    @pytest.mark.asyncio
    async def test_day_view_no_params_returns_today(self, client: AsyncClient, db_session: AsyncSession):
        # Seed an event for the date that parse_natural_date(None) resolves to.
        # We patch date.today() so "今天" == our fixed test date.
        fixed_today = date(2026, 6, 4)
        evt = await _seed_event(db_session, "今天的会议", days_offset=0)

        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = fixed_today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            response = await client.get(f"{API_PREFIX}/dashboard/day-view")
        assert response.status_code == 200
        data = response.json()

        assert data["date"] == TARGET_DATE
        assert len(data["events"]) >= 1
        assert data["events"][0]["title"] == "今天的会议"


class TestDayViewTomorrow:
    """Test 2: GET /day-view?date=明天 returns tomorrow's data."""

    @pytest.mark.asyncio
    async def test_day_view_tomorrow(self, client: AsyncClient, db_session: AsyncSession):
        ref = date(2026, 6, 4)
        await _seed_event(db_session, "今天的事", days_offset=0)
        await _seed_event(db_session, "明天的事", days_offset=1)

        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = ref
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            response = await client.get(f"{API_PREFIX}/dashboard/day-view", params={"date": "明天"})
        assert response.status_code == 200
        data = response.json()

        assert data["date"] == "2026-06-05"
        assert len(data["events"]) == 1
        assert data["events"][0]["title"] == "明天的事"
        assert "明天" in data["date_label"]
        assert "周五" in data["date_label"]


class TestDayViewEventsSortedByTime:
    """Test 3: Events are sorted by time ascending."""

    @pytest.mark.asyncio
    async def test_events_sorted_by_time(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "早会", days_offset=0, hour=9)
        await _seed_event(db_session, "午会", days_offset=0, hour=12)
        await _seed_event(db_session, "晚会", days_offset=0, hour=18)

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        events = response.json()["events"]

        times = [e["time"] for e in events]
        assert times == sorted(times)


class TestDayViewTodosOverdueFlag:
    """Test 4: Todos include is_overdue flag correctly."""

    @pytest.mark.asyncio
    async def test_todos_is_overdue_flag(self, client: AsyncClient, db_session: AsyncSession):
        # Seed a todo due on TARGET_DATE but mark it as overdue by patching today forward
        await _seed_todo(db_session, "过期待办", days_offset=0, status="pending")

        with patch("promiselink.api.v1.dashboard_day_view.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 10)  # Well past due
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            response = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
            )
        assert response.status_code == 200
        todos = response.json()["todos"]
        overdue_todos = [t for t in todos if t["is_overdue"]]
        assert len(overdue_todos) >= 1
        assert overdue_todos[0]["title"] == "过期待办"

    @pytest.mark.asyncio
    async def test_done_todo_not_overdue(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_todo(db_session, "已完成", days_offset=-5, status="done")

        with patch("promiselink.api.v1.dashboard_day_view.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 10)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            response = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": "2026-05-30"}
            )
        assert response.status_code == 200
        todos = response.json()["todos"]
        done_todos = [t for t in todos if t["title"] == "已完成"]
        if done_todos:
            assert not done_todos[0]["is_overdue"]


class TestDayViewSummaryStats:
    """Test 5: Summary statistics are correct."""

    @pytest.mark.asyncio
    async def test_summary_counts_correct(self, client: AsyncClient, db_session: AsyncSession):
        # Seed 2 events for TARGET_DATE
        await _seed_event(db_session, "会议A", event_type="meeting", days_offset=0)
        await _seed_event(db_session, "电话B", event_type="call", days_offset=0)

        # Seed 3 todos for TARGET_DATE (2 pending promises + 1 help)
        await _seed_todo(db_session, "承诺1", todo_type="promise", days_offset=0, status="pending")
        await _seed_todo(db_session, "承诺2", todo_type="promise", days_offset=0, status="pending")
        await _seed_todo(db_session, "帮忙事", todo_type="help", days_offset=0, status="pending")

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        summary = response.json()["summary"]

        assert summary["total_events"] == 2
        assert summary["total_todos"] == 3
        assert summary["pending_promises"] == 2
        assert summary["upcoming_meetings"] == 1


class TestDayViewAdjacentDates:
    """Test 6: Adjacent dates (previous/next day) are correct."""

    @pytest.mark.asyncio
    async def test_adjacent_dates_correct(self, client: AsyncClient):
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        adj = response.json()["adjacent_dates"]

        assert adj["previous_day"] == "2026-06-03"
        assert adj["next_day"] == "2026-06-05"

    @pytest.mark.asyncio
    async def test_adjacent_dates_for_specific_date(self, client: AsyncClient):
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": "2026-07-01"}
        )
        assert response.status_code == 200
        adj = response.json()["adjacent_dates"]

        assert adj["previous_day"] == "2026-06-30"
        assert adj["next_day"] == "2026-07-02"


class TestDayViewEmptyData:
    """Test 7: No data returns empty lists (not 404)."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty_lists(self, client: AsyncClient):
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": "2099-01-01"}
        )
        assert response.status_code == 200
        data = response.json()

        assert data["events"] == []
        assert data["todos"] == []
        assert data["summary"]["total_events"] == 0
        assert data["summary"]["total_todos"] == 0


class TestDayViewEventInputScope:
    """Test 8: input_scope field appears in event item."""

    @pytest.mark.asyncio
    async def test_input_scope_in_event_item(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(
            db_session, "重要会议", event_type="meeting", days_offset=0, input_scope="meeting"
        )

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        events = response.json()["events"]
        assert len(events) >= 1
        assert events[0]["input_scope"] == "meeting"


class TestDayViewTodoActionType:
    """Test 9: action_type field appears in todo item."""

    @pytest.mark.asyncio
    async def test_action_type_in_todo_item(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_todo(
            db_session, "我的承诺", todo_type="promise", days_offset=0, action_type="my_promise"
        )

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        todos = response.json()["todos"]
        assert len(todos) >= 1
        assert todos[0]["action_type"] == "my_promise"


class TestRangeViewThisWeek:
    """Test 10: GET /range-view with 本周 range text."""

    @pytest.mark.asyncio
    async def test_range_view_this_week(self, client: AsyncClient, db_session: AsyncSession):
        # Seed events across multiple days this week (TARGET_DATE is Thursday)
        await _seed_event(db_session, "周一事件", days_offset=-3)  # Monday
        await _seed_event(db_session, "周四事件", days_offset=0)   # Thursday
        await _seed_event(db_session, "周五事件", days_offset=1)   # Friday

        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 4)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            response = await client.get(
                f"{API_PREFIX}/dashboard/range-view", params={"range_text": "本周"}
            )
        assert response.status_code == 200
        data = response.json()

        assert data["range_start"] == "2026-06-01"  # Monday
        assert data["range_end"] == "2026-06-07"     # Sunday
        assert data["total_events"] == 3
        assert "本周" in data["label"]


class TestDayViewEntitiesInEvents:
    """Bonus test: Events include related person entities."""

    @pytest.mark.asyncio
    async def test_entities_in_event_item(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "和张总开会", days_offset=0)
        await _seed_person_entity(db_session, "张三", source_event=evt)

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        events = response.json()["events"]
        meeting_events = [e for e in events if e["title"] == "和张总开会"]
        assert len(meeting_events) == 1
        assert "张三" in meeting_events[0]["entities"]


class TestDayViewTodoCountInEvent:
    """Bonus test: Events show todo_count."""

    @pytest.mark.asyncio
    async def test_todo_count_in_event_item(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "有多个待办的事件", days_offset=0)
        # Create todos linked to this event
        await _seed_todo(
            db_session, "待办1", todo_type="promise", days_offset=0, source_event=evt
        )
        await _seed_todo(
            db_session, "待办2", todo_type="help", days_offset=0, source_event=evt
        )

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        events = response.json()["events"]
        target = [e for e in events if e["title"] == "有多个待办的事件"]
        assert len(target) == 1
        assert target[0]["todo_count"] == 2


class TestDayViewRelatedPersonInTodo:
    """Bonus test: Todos show related person name when linked to entity."""

    @pytest.mark.asyncio
    async def test_related_person_in_todo_item(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "dummy event for FK", days_offset=0)
        person = await _seed_person_entity(db_session, "李四", source_event=evt)
        await _seed_todo(
            db_session,
            "给李四发邮件",
            todo_type="care",
            days_offset=0,
            related_entity_id=person.id,
            source_event=evt,
        )

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        todos = response.json()["todos"]
        email_todos = [t for t in todos if t["title"] == "给李四发邮件"]
        assert len(email_todos) == 1
        assert email_todos[0]["related_person"] == "李四"


class TestRangeViewWithStartEndDates:
    """Bonus test: Range view with explicit start/end dates."""

    @pytest.mark.asyncio
    async def test_range_view_start_end_dates(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "第一天", days_offset=0)
        await _seed_event(db_session, "第三天", days_offset=2)

        response = await client.get(
            f"{API_PREFIX}/dashboard/range-view",
            params={"start_date": "2026-06-04", "end_date": "2026-06-06"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["range_start"] == "2026-06-04"
        assert data["range_end"] == "2026-06-06"
        assert data["total_events"] == 2


class TestDayViewISODateParam:
    """Bonus: ISO date parameter works correctly."""

    @pytest.mark.asyncio
    async def test_iso_date_param(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "ISO日期事件", days_offset=2)

        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": "2026-06-06"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-06-06"
        assert len(data["events"]) == 1
        assert data["events"][0]["title"] == "ISO日期事件"

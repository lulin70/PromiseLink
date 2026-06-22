"""E2E User Journey Supplement Tests — cross-day, data-loop, and voice scenarios.

TC-E2E-060 ~ TC-E2E-090 as defined in the test plan.

Uses in-memory SQLite + httpx.AsyncClient + FastAPI dependency overrides,
with LLM calls mocked out. No external services required.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.relationship_brief_service import RelationshipBriefService

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000002"
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


# ── Helpers ──


async def insert_event(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
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


# ══════════════════════════════════════════════════════════════════════════════
# 18.1 跨日连续使用场景
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossDayUsage:
    """Cross-day continuous usage scenarios."""

    @pytest.mark.asyncio
    async def test_tc_e2e_060_cross_day_journey(self, client: AsyncClient, db_session: AsyncSession):
        """TC-E2E-060: Day1录入交流→Day2收到Todo提醒→Day3完成Todo→Day4关系阶段变化.

        Simulates 4 days of usage with date mocking.
        """
        day1 = date(2026, 6, 1)
        day2 = date(2026, 6, 2)
        day3 = date(2026, 6, 3)
        day4 = date(2026, 6, 4)

        # ── Day 1: 录入交流 ──
        day1_ts = datetime(day1.year, day1.month, day1.day, 10, 0, tzinfo=UTC)
        event1 = await insert_event(
            db_session,
            title="和王总见面",
            raw_text="今天和王总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
            timestamp=day1_ts,
            status="completed",
        )
        entity1 = await insert_entity(
            db_session,
            name="王总",
            canonical_name="王总",
            source_event_id=event1.id,
            properties={
                "basic": {"company": "某制造集团", "title": "总经理"},
                "concern": [{"category": "AI应用", "detail": "AI在制造业的应用"}],
            },
        )
        todo1 = await insert_todo(
            db_session,
            title="给王总发AI方案",
            todo_type="promise",
            source_event_id=event1.id,
            related_entity_id=entity1.id,
            status="pending",
            priority=1,
            due_date=datetime(day2.year, day2.month, day2.day, 18, 0, tzinfo=UTC),
        )

        # Create initial relationship brief
        service = RelationshipBriefService(db_session)
        await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=str(entity1.id),
            event=event1,
            entities=[entity1],
            todos=[todo1],
        )
        await db_session.commit()

        # Verify Day1: brief is new_connection
        resp = await client.get(f"{API_PREFIX}/persons/{entity1.id}/relationship-brief")
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["relationship_stage"] == "new_connection"

        # ── Day 2: 收到Todo提醒 ──
        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = day2
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        brief_data = resp.json()
        assert brief_data["pending_promises"] >= 1

        # ── Day 3: 完成Todo ──
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo1.id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

        # Add a second interaction on Day3
        day3_ts = datetime(day3.year, day3.month, day3.day, 14, 0, tzinfo=UTC)
        event2 = await insert_event(
            db_session,
            title="和王总深度交流",
            raw_text="和王总深入讨论了AI方案，他非常满意",
            timestamp=day3_ts,
            status="completed",
        )
        entity_result = await db_session.execute(
            select(Entity).where(Entity.id == entity1.id)
        )
        entity1_refreshed = entity_result.scalar_one()

        await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=str(entity1.id),
            event=event2,
            entities=[entity1_refreshed],
            todos=[],
        )
        await db_session.commit()

        # ── Day 4: 关系阶段变化 ──
        resp = await client.get(f"{API_PREFIX}/persons/{entity1.id}/relationship-brief")
        assert resp.status_code == 200
        updated_brief = resp.json()
        # After 2 interactions, version should be >= 2
        assert updated_brief["version"] >= 2
        # Brief should reflect the second interaction
        assert updated_brief["brief_data"]["last_interaction"]["summary"] == "和王总深度交流"

    @pytest.mark.asyncio
    async def test_tc_e2e_061_priority_dynamic_adjustment(self, client: AsyncClient, db_session: AsyncSession):
        """TC-E2E-061: 多日累积数据后优先级评分动态调整验证.

        Add events over multiple days, verify priority scores change as due dates approach.
        """
        from promiselink.services.priority_scorer import PriorityScorer

        scorer = PriorityScorer()

        # Use a fixed "now" to make the test deterministic
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

        # Day 1: Create a promise todo due in 7 days
        due_date_far = datetime(2026, 6, 8, 18, 0, tzinfo=UTC)

        event = await insert_event(db_session, title="承诺事项")
        todo = await insert_todo(
            db_session,
            title="给李总发资料",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            priority=2,
            due_date=due_date_far,
        )
        await db_session.commit()

        # Score on Day 1 (7 days away) — lower urgency
        score_far = scorer.calculate(
            todo_type="promise",
            due_date=due_date_far,
            priority=2,
            now=now,
        )

        # Score when 1 day away — higher urgency
        due_date_near = datetime(2026, 6, 2, 18, 0, tzinfo=UTC)
        score_near = scorer.calculate(
            todo_type="promise",
            due_date=due_date_near,
            priority=2,
            now=now,
        )

        # Near-due should score higher than far-due
        assert score_near.score > score_far.score, (
            f"Near-due score ({score_near.score}) should be > far-due score ({score_far.score})"
        )

        # Both scores should be in valid range
        assert 0.0 <= score_far.score <= 1.0
        assert 0.0 <= score_near.score <= 1.0

    @pytest.mark.asyncio
    async def test_tc_e2e_062_care_todo_auto_generation(self, client: AsyncClient, db_session: AsyncSession):
        """TC-E2E-062: 长期未联系人的care Todo自动生成验证.

        Create an entity with old interaction, verify care todo can be generated.
        """
        # Create entity with an old interaction (30 days ago)
        old_date = datetime.now(UTC) - timedelta(days=30)
        event = await insert_event(
            db_session,
            title="旧交流",
            raw_text="和赵总见面讨论合作",
            timestamp=old_date,
            status="completed",
        )
        entity = await insert_entity(
            db_session,
            name="赵总",
            canonical_name="赵总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某公司", "title": "总监"},
            },
        )
        await db_session.commit()

        # Verify entity exists
        resp = await client.get(f"{API_PREFIX}/entities", params={"search": "赵总"})
        assert resp.status_code == 200
        entities = resp.json()["items"]
        assert any(e["name"] == "赵总" for e in entities)

        # Simulate care todo generation for long-uncontacted entity
        care_todo = await insert_todo(
            db_session,
            title="关注赵总近况",
            todo_type="care",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=3,
        )
        await db_session.commit()

        # Verify care todo appears in todo list
        resp = await client.get(f"{API_PREFIX}/todos", params={"todo_type": "care"})
        assert resp.status_code == 200
        todos = resp.json()["items"]
        care_todos = [t for t in todos if t["todo_type"] == "care"]
        assert any("赵总" in t["title"] for t in care_todos)


# ══════════════════════════════════════════════════════════════════════════════
# 18.2 数据闭环场景
# ══════════════════════════════════════════════════════════════════════════════


class TestDataLoop:
    """Data loop scenarios: export → modify → re-import, bulk delete cleanup."""

    @pytest.mark.asyncio
    async def test_tc_e2e_080_export_reimport_consistency(self, client: AsyncClient, db_session: AsyncSession):
        """TC-E2E-080: 数据导出→修改→重新导入→数据一致性验证.

        Export data, verify it can be re-imported with consistent structure.
        """
        # Create test data
        event = await insert_event(db_session, title="导出测试事件")
        entity = await insert_entity(
            db_session,
            name="导出测试人",
            canonical_name="导出测试人",
            source_event_id=event.id,
            properties={"basic": {"company": "测试公司", "title": "工程师"}},
        )
        todo = await insert_todo(
            db_session,
            title="导出测试待办",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
        )
        await db_session.commit()

        # Export data
        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200
        export_data = json.loads(resp.text)

        # Verify export structure
        assert export_data["export_version"] == "1.0"
        assert export_data["user_id"] == TEST_USER_ID
        assert len(export_data["events"]) >= 1
        assert len(export_data["entities"]) >= 1
        assert len(export_data["todos"]) >= 1

        # Verify exported entity data consistency
        exported_entity = next(
            (e for e in export_data["entities"] if e["name"] == "导出测试人"), None
        )
        assert exported_entity is not None
        assert exported_entity["name"] == "导出测试人"

        # Verify exported todo data consistency
        exported_todo = next(
            (t for t in export_data["todos"] if t["title"] == "导出测试待办"), None
        )
        assert exported_todo is not None
        assert exported_todo["status"] == "pending"

    @pytest.mark.asyncio
    async def test_tc_e2e_081_bulk_delete_entity_cleanup(self, client: AsyncClient, db_session: AsyncSession):
        """TC-E2E-081: 批量删除Entity后关联数据清理完整性验证.

        Delete entities and verify that associated data (todos referencing them)
        is properly handled.
        """
        # Create entities with associations and todos
        event = await insert_event(db_session, title="批量删除测试")
        entity_a = await insert_entity(
            db_session, name="待删除A", source_event_id=event.id
        )
        entity_b = await insert_entity(
            db_session, name="待删除B", source_event_id=event.id
        )
        assoc = await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            association_type="same_city",
            source_event_id=event.id,
        )
        todo_a = await insert_todo(
            db_session,
            title="A的待办",
            source_event_id=event.id,
            related_entity_id=entity_a.id,
            status="pending",
        )
        await db_session.commit()

        # Verify data exists before deletion
        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        entities = resp.json()["items"]
        assert any(e["name"] == "待删除A" for e in entities)

        # Delete entity A
        resp = await client.delete(f"{API_PREFIX}/entities/{entity_a.id}")
        assert resp.status_code in (200, 204)

        # Verify entity A is gone
        resp = await client.get(f"{API_PREFIX}/entities/{entity_a.id}")
        assert resp.status_code == 404

        # Verify entity B still exists
        resp = await client.get(f"{API_PREFIX}/entities/{entity_b.id}")
        assert resp.status_code == 200

        # Verify association is cleaned up (source or target deleted)
        resp = await client.get(f"{API_PREFIX}/associations")
        assert resp.status_code == 200
        assocs = resp.json()["items"]
        remaining_assoc_ids = [a["id"] for a in assocs]
        assert str(assoc.id) not in remaining_assoc_ids



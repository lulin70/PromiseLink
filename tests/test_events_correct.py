"""Tests for POST /api/v1/events/{id}/correct — event correction (纠偏) endpoint.

Validates the three correction types:
- 人脉纠偏: select_existing / create_new / ignore
- 待办纠偏: edit / delete / add
- 承诺纠偏: confirm / ignore / modify

Also tests the extended GET /events/{id} response with related_entities
and related_associations.
"""

import uuid

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

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


async def setup_completed_event_with_data(session: AsyncSession) -> dict:
    """Create a completed event with entities, todos, promises, and associations.

    Returns a dict of IDs for use in tests.
    """
    event_id = str(uuid.uuid4())

    # Create event
    event = Event(
        id=event_id,
        user_id=TEST_USER_ID,
        event_type="meeting",
        source="test",
        title="与李总讨论合作",
        raw_text="今天和李总讨论了合作方案",
        status="completed",
    )
    session.add(event)
    await session.flush()

    # Create extracted entity (person "李总")
    entity1_id = str(uuid.uuid4())
    entity1 = Entity(
        id=entity1_id,
        user_id=TEST_USER_ID,
        entity_type="person",
        name="李总",
        canonical_name="李总",
        source_event_id=event_id,
        properties={"basic": {"company": "未知", "title": "总经理"}},
        confidence=0.8,
        status="confirmed",
    )
    session.add(entity1)

    # Create another extracted entity (person "张总")
    entity2_id = str(uuid.uuid4())
    entity2 = Entity(
        id=entity2_id,
        user_id=TEST_USER_ID,
        entity_type="person",
        name="张总",
        canonical_name="张总",
        source_event_id=event_id,
        properties={"basic": {"company": "ABC公司", "title": "CEO"}},
        confidence=0.9,
        status="confirmed",
    )
    session.add(entity2)
    await session.flush()

    # Create an existing entity in the library (for select_existing test)
    existing_entity_id = str(uuid.uuid4())
    existing_event_id = str(uuid.uuid4())
    existing_event = Event(
        id=existing_event_id,
        user_id=TEST_USER_ID,
        event_type="meeting",
        source="test",
        title="历史会议",
        raw_text="历史记录",
        status="completed",
    )
    session.add(existing_event)
    await session.flush()
    existing_entity = Entity(
        id=existing_entity_id,
        user_id=TEST_USER_ID,
        entity_type="person",
        name="李总",
        canonical_name="李建国",
        source_event_id=existing_event_id,
        properties={"basic": {"company": "建国集团", "title": "董事长"}},
        confidence=1.0,
        status="confirmed",
    )
    session.add(existing_entity)

    # Create a todo (followup)
    todo_id = str(uuid.uuid4())
    todo = Todo(
        id=todo_id,
        user_id=TEST_USER_ID,
        todo_type="followup",
        title="跟进合作方案",
        description="下周前发送方案文档",
        priority=2,
        status="pending",
        source_event_id=event_id,
        related_entity_id=entity1_id,
    )
    session.add(todo)

    # Create a promise (my_promise)
    promise_id = str(uuid.uuid4())
    promise = Todo(
        id=promise_id,
        user_id=TEST_USER_ID,
        todo_type="promise",
        title="我答应提供技术方案",
        description="我会在周五前提供技术方案",
        priority=1,
        status="pending",
        source_event_id=event_id,
        action_type="my_promise",
        confirmation_status="pending",
        related_entity_id=entity1_id,
    )
    session.add(promise)

    # Create a their_promise
    their_promise_id = str(uuid.uuid4())
    their_promise = Todo(
        id=their_promise_id,
        user_id=TEST_USER_ID,
        todo_type="promise",
        title="李总承诺介绍客户",
        description="李总说会介绍一个客户给我",
        priority=2,
        status="pending",
        source_event_id=event_id,
        action_type="their_promise",
        confirmation_status="auto_set",
        related_entity_id=entity1_id,
    )
    session.add(their_promise)

    # Create an association
    assoc_id = str(uuid.uuid4())
    assoc = Association(
        id=assoc_id,
        user_id=TEST_USER_ID,
        source_entity_id=entity1_id,
        target_entity_id=entity2_id,
        association_type="co_occurrence",
        strength=0.7,
        source_event_id=event_id,
    )
    session.add(assoc)

    await session.commit()

    return {
        "event_id": event_id,
        "entity1_id": entity1_id,
        "entity2_id": entity2_id,
        "existing_entity_id": existing_entity_id,
        "todo_id": todo_id,
        "promise_id": promise_id,
        "their_promise_id": their_promise_id,
        "assoc_id": assoc_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# GET /events/{id} — Extended detail with related_entities and related_associations
# ══════════════════════════════════════════════════════════════════════════════


class TestEventDetailExtended:
    """Tests for extended GET /events/{id} with related_entities/associations."""

    async def test_get_event_returns_related_entities(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.get(f"{API_PREFIX}/events/{ids['event_id']}")
        assert resp.status_code == 200
        data = resp.json()

        assert "related_entities" in data
        assert len(data["related_entities"]) == 2
        ent = data["related_entities"][0]
        assert "name" in ent
        assert "company" in ent
        assert "title" in ent
        assert "entity_type" in ent

    async def test_get_event_returns_related_associations(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.get(f"{API_PREFIX}/events/{ids['event_id']}")
        data = resp.json()

        assert "related_associations" in data
        assert len(data["related_associations"]) == 1
        assoc = data["related_associations"][0]
        assert assoc["association_type"] == "co_occurrence"
        assert "source_entity_name" in assoc
        assert "target_entity_name" in assoc

    async def test_get_event_returns_related_todos_with_details(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.get(f"{API_PREFIX}/events/{ids['event_id']}")
        data = resp.json()

        assert "related_todos" in data
        assert len(data["related_todos"]) == 3
        todo = next(t for t in data["related_todos"] if t["id"] == ids["todo_id"])
        assert todo["title"] == "跟进合作方案"
        assert todo["priority"] == 2
        assert todo["description"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# POST /events/{id}/correct — Entity Correction (人脉纠偏)
# ══════════════════════════════════════════════════════════════════════════════


class TestEntityCorrection:
    """Tests for 人脉纠偏 (entity correction)."""

    async def test_select_existing_entity(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [{
                "extracted_entity_id": ids["entity1_id"],
                "action": "select_existing",
                "selected_entity_id": ids["existing_entity_id"],
            }],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_updated"] == 1

        # Verify entity was marked as merged
        from sqlalchemy import select
        result = await db_session.execute(
            select(Entity).where(Entity.id == ids["entity1_id"])
        )
        entity = result.scalar_one()
        assert entity.status == "merged"

    async def test_create_new_entity(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [{
                "extracted_entity_id": ids["entity1_id"],
                "action": "create_new",
                "new_name": "李建国",
                "new_company": "建国集团",
                "new_title": "董事长",
            }],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_created"] == 1

        # Verify entity was updated
        from sqlalchemy import select
        result = await db_session.execute(
            select(Entity).where(Entity.id == ids["entity1_id"])
        )
        entity = result.scalar_one()
        assert entity.name == "李建国"
        assert entity.canonical_name == "李建国"
        assert entity.properties["basic"]["company"] == "建国集团"
        assert entity.properties["basic"]["title"] == "董事长"
        assert entity.status == "confirmed"

    async def test_ignore_entity(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [{
                "extracted_entity_id": ids["entity1_id"],
                "action": "ignore",
            }],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_ignored"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Entity).where(Entity.id == ids["entity1_id"])
        )
        entity = result.scalar_one()
        assert entity.status == "deleted"


# ══════════════════════════════════════════════════════════════════════════════
# POST /events/{id}/correct — Todo Correction (待办纠偏)
# ══════════════════════════════════════════════════════════════════════════════


class TestTodoCorrection:
    """Tests for 待办纠偏 (todo correction)."""

    async def test_edit_todo(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [{
                "id": ids["todo_id"],
                "title": "跟进合作方案(已修改)",
                "description": "修改后的描述",
                "priority": 1,
                "action": "edit",
            }],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["todos_updated"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.id == ids["todo_id"])
        )
        todo = result.scalar_one()
        assert todo.title == "跟进合作方案(已修改)"
        assert todo.priority == 1

    async def test_delete_todo(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [{
                "id": ids["todo_id"],
                "title": "跟进合作方案",
                "priority": 2,
                "action": "delete",
            }],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["todos_deleted"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.id == ids["todo_id"])
        )
        assert result.scalar_one_or_none() is None

    async def test_add_new_todo(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [{
                "title": "新待办：发送邮件",
                "description": "给李总发送确认邮件",
                "priority": 3,
                "action": "add",
            }],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["todos_created"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.title == "新待办：发送邮件")
        )
        todo = result.scalar_one()
        assert todo.source_event_id == ids["event_id"]
        assert todo.status == "pending"


# ══════════════════════════════════════════════════════════════════════════════
# POST /events/{id}/correct — Promise Correction (承诺纠偏)
# ══════════════════════════════════════════════════════════════════════════════


class TestPromiseCorrection:
    """Tests for 承诺纠偏 (promise correction)."""

    async def test_confirm_promise(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [],
            "corrected_promises": [{
                "id": ids["promise_id"],
                "action": "confirm",
            }],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_confirmed"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.id == ids["promise_id"])
        )
        promise = result.scalar_one()
        assert promise.confirmation_status == "confirmed"

    async def test_ignore_promise(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [],
            "corrected_promises": [{
                "id": ids["promise_id"],
                "action": "ignore",
            }],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_ignored"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.id == ids["promise_id"])
        )
        promise = result.scalar_one()
        assert promise.confirmation_status == "rejected"
        assert promise.status == "dismissed"

    async def test_modify_promise(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [],
            "corrected_promises": [{
                "id": ids["their_promise_id"],
                "content": "李总承诺下周介绍客户",
                "promise_type": "their_promise",
                "action": "modify",
            }],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_modified"] == 1

        from sqlalchemy import select
        result = await db_session.execute(
            select(Todo).where(Todo.id == ids["their_promise_id"])
        )
        promise = result.scalar_one()
        assert promise.description == "李总承诺下周介绍客户"
        assert promise.confirmation_status == "confirmed"


# ══════════════════════════════════════════════════════════════════════════════
# POST /events/{id}/correct — Combined & Edge Cases
# ══════════════════════════════════════════════════════════════════════════════


class TestCorrectCombined:
    """Tests for combined corrections and edge cases."""

    async def test_combined_corrections(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [{
                "extracted_entity_id": ids["entity1_id"],
                "action": "create_new",
                "new_name": "李建国",
            }],
            "corrected_todos": [
                {"id": ids["todo_id"], "title": "修改后待办", "priority": 1, "action": "edit"},
                {"title": "新增待办", "priority": 3, "action": "add"},
            ],
            "corrected_promises": [
                {"id": ids["promise_id"], "action": "confirm"},
                {"id": ids["their_promise_id"], "action": "ignore"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_created"] == 1
        assert data["todos_updated"] == 1
        assert data["todos_created"] == 1
        assert data["promises_confirmed"] == 1
        assert data["promises_ignored"] == 1

    async def test_empty_corrections(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_updated"] == 0
        assert data["todos_created"] == 0

    async def test_nonexistent_event_returns_404(self, client: AsyncClient):
        fake_id = str(uuid.uuid4())
        resp = await client.post(f"{API_PREFIX}/events/{fake_id}/correct", json={
            "corrected_entities": [],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 404

    async def test_nonexistent_entity_skipped(self, client: AsyncClient, db_session: AsyncSession):
        ids = await setup_completed_event_with_data(db_session)

        resp = await client.post(f"{API_PREFIX}/events/{ids['event_id']}/correct", json={
            "corrected_entities": [{
                "extracted_entity_id": str(uuid.uuid4()),
                "action": "ignore",
            }],
            "corrected_todos": [],
            "corrected_promises": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_ignored"] == 0

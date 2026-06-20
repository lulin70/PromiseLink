"""Tests for POST /api/v1/events/{id}/correct — PRD §5.18 v5.6 新增功能.

Covers two new correction capabilities added in v5.6:
- 承诺添加 (promise add, action='add'): 手动补录承诺
- 关系纠偏 (association correction): modify / delete 关系

Also validates the new response fields:
- promises_created
- associations_updated

Follows the same fixture pattern as tests/test_events_correct.py.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

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

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"


# ── Fixtures (mirror tests/test_events_correct.py) ──


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


async def setup_event_with_entities_and_association(session: AsyncSession) -> dict:
    """Create a completed event with two entities and one association.

    Provides the minimum data needed for v5.6 tests:
    - 1 event (status=completed)
    - 2 entities (persons, status=confirmed)
    - 1 association (co_occurrence, strength=0.7)
    - 1 existing promise (my_promise, confirmation_status=pending)
    """
    event_id = str(uuid.uuid4())

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

    await session.commit()

    return {
        "event_id": event_id,
        "entity1_id": entity1_id,
        "entity2_id": entity2_id,
        "assoc_id": assoc_id,
        "promise_id": promise_id,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 承诺添加 (Promise Add, action='add') — PRD §5.18 v5.6
# ══════════════════════════════════════════════════════════════════════════════


class TestPromiseAdd:
    """Tests for 承诺添加 (promise add, action='add')."""

    async def test_promise_add_creates_new_promise(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: add 动作创建新承诺.

        Scenario: 提交承诺纠偏 action='add'
        Expected: promises_created=1, 数据库新增一条 todo_type='promise' 记录
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": "我承诺下周三前发送报价单",
                        "promise_type": "my_promise",
                        "promisor_id": None,
                        "beneficiary_id": ids["entity1_id"],
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

        result = await db_session.execute(
            select(Todo).where(Todo.todo_type == "promise", Todo.title == "我承诺下周三前发送报价单")
        )
        new_promise = result.scalar_one()
        assert new_promise.action_type == "my_promise"
        assert new_promise.source_event_id == ids["event_id"]
        assert new_promise.beneficiary_id == ids["entity1_id"]

    async def test_promise_add_without_content_skipped(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: add 动作无 content 时跳过.

        Scenario: 提交承诺纠偏 action='add' 但 content 为空
        Expected: promises_created=0, 数据库无新增
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": None,
                        "promise_type": "my_promise",
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 0

    async def test_promise_add_with_due_date(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: add 动作带截止时间.

        Scenario: 提交承诺纠偏 action='add' 带 due_date
        Expected: promises_created=1, 新承诺 due_date 正确写入
        """
        ids = await setup_event_with_entities_and_association(db_session)
        due = (datetime.now(UTC) + timedelta(days=7)).isoformat()

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": "我承诺7天内交付原型",
                        "promise_type": "my_promise",
                        "beneficiary_id": ids["entity1_id"],
                        "due_date": due,
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

        result = await db_session.execute(
            select(Todo).where(Todo.title == "我承诺7天内交付原型")
        )
        new_promise = result.scalar_one()
        assert new_promise.due_date is not None

    async def test_promise_add_my_promise_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: add 动作 my_promise 类型.

        Scenario: 提交承诺纠偏 action='add', promise_type='my_promise'
        Expected: promises_created=1, 新承诺 action_type='my_promise'
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": "我会负责跟进客户",
                        "promise_type": "my_promise",
                        "beneficiary_id": ids["entity1_id"],
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

        result = await db_session.execute(
            select(Todo).where(Todo.title == "我会负责跟进客户")
        )
        new_promise = result.scalar_one()
        assert new_promise.action_type == "my_promise"

    async def test_promise_add_their_promise_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: add 动作 their_promise 类型.

        Scenario: 提交承诺纠偏 action='add', promise_type='their_promise'
        Expected: promises_created=1, 新承诺 action_type='their_promise'
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": "李总承诺介绍客户",
                        "promise_type": "their_promise",
                        "promisor_id": ids["entity1_id"],
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

        result = await db_session.execute(
            select(Todo).where(Todo.title == "李总承诺介绍客户")
        )
        new_promise = result.scalar_one()
        assert new_promise.action_type == "their_promise"
        assert new_promise.promisor_id == ids["entity1_id"]

    async def test_promise_add_confirmation_status(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 新承诺 confirmation_status='confirmed'.

        Scenario: 提交承诺纠偏 action='add'
        Expected: promises_created=1, 新承诺 confirmation_status='confirmed'
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [
                    {
                        "content": "手动补录的承诺",
                        "promise_type": "my_promise",
                        "beneficiary_id": ids["entity1_id"],
                        "action": "add",
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

        result = await db_session.execute(
            select(Todo).where(Todo.title == "手动补录的承诺")
        )
        new_promise = result.scalar_one()
        assert new_promise.confirmation_status == "confirmed"
        assert new_promise.todo_type == "promise"


# ══════════════════════════════════════════════════════════════════════════════
# 关系纠偏 (Association Correction) — PRD §5.18 v5.6
# ══════════════════════════════════════════════════════════════════════════════


class TestAssociationCorrection:
    """Tests for 关系纠偏 (association correction)."""

    async def test_association_modify_updates_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: modify 动作更新关系类型.

        Scenario: 提交关系纠偏 action='modify', relationship_type='alumni'
        Expected: associations_updated=1, 关系类型更新为 alumni
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [
                    {
                        "source_entity_id": ids["entity1_id"],
                        "target_entity_id": ids["entity2_id"],
                        "relationship_type": "alumni",
                        "action": "modify",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["associations_updated"] == 1

        result = await db_session.execute(
            select(Association).where(Association.id == ids["assoc_id"])
        )
        assoc = result.scalar_one()
        assert assoc.association_type == "alumni"

    async def test_association_modify_updates_strength(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: modify 动作更新关系强度.

        Scenario: 提交关系纠偏 action='modify', strength=0.95
        Expected: associations_updated=1, 关系强度更新为 0.95
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [
                    {
                        "source_entity_id": ids["entity1_id"],
                        "target_entity_id": ids["entity2_id"],
                        "strength": 0.95,
                        "action": "modify",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["associations_updated"] == 1

        result = await db_session.execute(
            select(Association).where(Association.id == ids["assoc_id"])
        )
        assoc = result.scalar_one()
        assert assoc.strength == 0.95

    async def test_association_delete_removes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: delete 动作删除关系.

        Scenario: 提交关系纠偏 action='delete'
        Expected: associations_updated=1, 关系被删除
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [
                    {
                        "source_entity_id": ids["entity1_id"],
                        "target_entity_id": ids["entity2_id"],
                        "action": "delete",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["associations_updated"] == 1

        result = await db_session.execute(
            select(Association).where(Association.id == ids["assoc_id"])
        )
        assert result.scalar_one_or_none() is None

    async def test_association_nonexistent_skipped(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 不存在的关系跳过.

        Scenario: 提交关系纠偏，但 source/target 实体不存在关系
        Expected: associations_updated=0, 不报错
        """
        ids = await setup_event_with_entities_and_association(db_session)

        # 用两个不相关的实体 ID（虽然存在，但无 association 连接）
        fake_source = str(uuid.uuid4())
        fake_target = str(uuid.uuid4())

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [
                    {
                        "source_entity_id": fake_source,
                        "target_entity_id": fake_target,
                        "relationship_type": "alumni",
                        "action": "modify",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["associations_updated"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 综合测试 (Combined) — PRD §5.18 v5.6
# ══════════════════════════════════════════════════════════════════════════════


class TestCorrectionV56Combined:
    """Tests for combined v5.6 corrections."""

    async def test_correction_with_all_five_types(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 五类纠偏同时提交（人脉+关系+待办+承诺确认+承诺添加）.

        Scenario: 单次请求提交全部五类纠偏
        Expected: 各类计数器正确，响应包含 promises_created 和 associations_updated
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": ids["entity1_id"],
                        "action": "create_new",
                        "new_name": "李建国",
                        "new_company": "建国集团",
                        "new_title": "董事长",
                    }
                ],
                "corrected_todos": [
                    {
                        "title": "新待办：发送邮件",
                        "priority": 3,
                        "action": "add",
                    }
                ],
                "corrected_promises": [
                    {
                        "id": ids["promise_id"],
                        "action": "confirm",
                    },
                    {
                        "content": "手动补录的新承诺",
                        "promise_type": "my_promise",
                        "beneficiary_id": ids["entity1_id"],
                        "action": "add",
                    },
                ],
                "corrected_associations": [
                    {
                        "source_entity_id": ids["entity1_id"],
                        "target_entity_id": ids["entity2_id"],
                        "relationship_type": "alumni",
                        "strength": 0.9,
                        "action": "modify",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # 人脉
        assert data["entities_created"] == 1
        # 待办
        assert data["todos_created"] == 1
        # 承诺确认
        assert data["promises_confirmed"] == 1
        # 承诺添加（v5.6 新增）
        assert data["promises_created"] == 1
        # 关系纠偏（v5.6 新增）
        assert data["associations_updated"] == 1

    async def test_correction_response_has_new_fields(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 响应包含 promises_created 和 associations_updated 字段.

        Scenario: 提交纠偏请求
        Expected: 响应 JSON 包含 promises_created 和 associations_updated 字段
        """
        ids = await setup_event_with_entities_and_association(db_session)

        resp = await client.post(
            f"{API_PREFIX}/events/{ids['event_id']}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # v5.6 新增字段必须存在
        assert "promises_created" in data
        assert "associations_updated" in data
        # 空请求时这两个字段应为 0
        assert data["promises_created"] == 0
        assert data["associations_updated"] == 0

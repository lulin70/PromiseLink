"""Tests for 1.3 batch reminder action + 1.1 privacy delete (Batch 2).

Covers:
  - POST /api/v1/reminders/batch-action: 成功批量完成/推迟/忽略
  - POST /api/v1/reminders/batch-action: action 枚举白名单（拒绝非法值）
  - POST /api/v1/reminders/batch-action: IDOR 防护（拒绝非归属 todo_id）
  - POST /api/v1/reminders/batch-action: snooze 必须带 snooze_hours
  - DELETE /api/v1/privacy/user-data: 二次确认短语
  - DELETE /api/v1/privacy/user-data: 多租户隔离（只删自己的数据）
  - DELETE /api/v1/privacy/user-data: 级联清理依赖表
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

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
from promiselink.models.reminder import ReminderLog, ReminderPreference
from promiselink.models.todo import Todo
import promiselink.services.event_processor as processor_module

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000201"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000202"
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
    """Authenticated client for TEST_USER_ID."""

    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    async def mock_process_event(event_id):
        pass

    original_process = processor_module.process_event_background
    processor_module.process_event_background = mock_process_event  # type: ignore[assignment]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    processor_module.process_event_background = original_process  # type: ignore[assignment]
    app.dependency_overrides.clear()


# ── Helpers ──


async def insert_event(session: AsyncSession, user_id: str = TEST_USER_ID, **overrides) -> Event:
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
    source_event_id: str | None = None,
    due_date: datetime | None = None,
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
        description="test description",
        due_date=due_date,
    )
    session.add(todo)
    await session.flush()
    return todo


# ──────────────────────────────────────────────────────────────────
# 1.3 batch-action tests
# ──────────────────────────────────────────────────────────────────


class TestBatchReminderAction:
    """1.3 提醒页批量操作 — 安全 + 功能验证。"""

    @pytest.mark.asyncio
    async def test_batch_complete_success(self, client, db_session):
        """Verify: 批量完成 3 条 todo 全部成功。"""
        todos = [await insert_todo(db_session, title=f"t{i}") for i in range(3)]
        await db_session.commit()
        todo_ids = [str(t.id) for t in todos]

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": todo_ids, "action": "completed"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["success"]) == 3
        assert len(body["failed"]) == 0
        for item in body["success"]:
            assert item["new_status"] == "done"

    @pytest.mark.asyncio
    async def test_batch_invalid_action_rejected(self, client, db_session):
        """Verify: action 枚举白名单拒绝非法值（422 ValidationError）。"""
        todo = await insert_todo(db_session)
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(todo.id)], "action": "delete"},
        )
        assert resp.status_code == 400
        assert "Invalid action" in resp.text

    @pytest.mark.asyncio
    async def test_batch_idor_protection(self, client, db_session):
        """Verify: IDOR 防护 — 其他用户的 todo_id 进入 failed 列表。"""
        own_todo = await insert_todo(db_session, user_id=TEST_USER_ID, title="own")
        other_todo = await insert_todo(db_session, user_id=OTHER_USER_ID, title="other")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={
                "todo_ids": [str(own_todo.id), str(other_todo.id)],
                "action": "dismissed",
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["success"]) == 1
        assert body["success"][0]["todo_id"] == str(own_todo.id)
        assert len(body["failed"]) == 1
        assert body["failed"][0]["todo_id"] == str(other_todo.id)
        assert "forbidden" in body["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_batch_snooze_requires_hours(self, client, db_session):
        """Verify: action=snoozed 必须带 snooze_hours。"""
        todo = await insert_todo(db_session)
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(todo.id)], "action": "snoozed"},
        )
        assert resp.status_code == 400
        assert "snooze_hours" in resp.text

    @pytest.mark.asyncio
    async def test_batch_snooze_success(self, client, db_session):
        """Verify: 批量推迟设置 snoozed 状态。"""
        todo = await insert_todo(db_session)
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [str(todo.id)], "action": "snoozed", "snooze_hours": 12},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"][0]["new_status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_batch_max_fifty_ids(self, client, db_session):
        """Verify: 单次最多 50 条（防止滥用）。"""
        # Pydantic min_length=1 max_length=50; 51 个应被 422 拒绝
        ids = [str(uuid.uuid4()) for _ in range(51)]
        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": ids, "action": "completed"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_batch_empty_ids_rejected(self, client, db_session):
        """Verify: todo_ids 不能为空。"""
        resp = await client.post(
            f"{API_PREFIX}/reminders/batch-action",
            json={"todo_ids": [], "action": "completed"},
        )
        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────
# 1.1 privacy delete tests
# ──────────────────────────────────────────────────────────────────


class TestPrivacyDelete:
    """1.1 设置页隐私数据删除 — 安全 + 级联验证。"""

    @pytest.mark.asyncio
    async def test_delete_confirm_phrase_required(self, client, db_session):
        """Verify: 二次确认短语必须为 'DELETE'。"""
        resp = await client.request(
            "DELETE",
            f"{API_PREFIX}/privacy/user-data",
            json={"confirm": "delete"},
        )
        assert resp.status_code == 400
        assert "DELETE" in resp.text

    @pytest.mark.asyncio
    async def test_delete_success_cascade(self, client, db_session):
        """Verify: 删除成功 + 级联清理依赖表。"""
        event = await insert_event(db_session)
        entity1 = Entity(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            entity_type="person",
            name="Test1",
            canonical_name="Test1",
            aliases=[],
            properties={},
            source_event_id=str(event.id),
            confidence=0.9,
            status="confirmed",
        )
        entity2 = Entity(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            entity_type="person",
            name="Test2",
            canonical_name="Test2",
            aliases=[],
            properties={},
            source_event_id=str(event.id),
            confidence=0.9,
            status="confirmed",
        )
        db_session.add_all([entity1, entity2])
        todo = await insert_todo(db_session, source_event_id=str(event.id))
        db_session.add(
            Association(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                source_entity_id=str(entity1.id),
                target_entity_id=str(entity2.id),
                association_type="ex_colleague",
                strength=0.5,
            )
        )
        db_session.add(
            ReminderLog(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                todo_id=str(todo.id),
                reminder_type="followup",
                sent_at=datetime.now(UTC),
            )
        )
        await db_session.commit()

        resp = await client.request(
            "DELETE",
            f"{API_PREFIX}/privacy/user-data",
            json={"confirm": "DELETE"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deleted"]["todos"] >= 1
        assert body["deleted"]["events"] >= 1
        assert body["deleted"]["entities"] >= 1
        assert body["deleted"]["associations"] >= 1
        assert body["deleted"]["reminder_logs"] >= 1
        assert body["audit_id"]
        assert body["deleted_at"]

    @pytest.mark.asyncio
    async def test_delete_multi_tenant_isolation(self, client, db_session):
        """Verify: 多租户隔离 — 只删当前用户数据，其他用户数据保留。"""
        # Both users have data
        await insert_todo(db_session, user_id=TEST_USER_ID, title="mine")
        await insert_todo(db_session, user_id=OTHER_USER_ID, title="theirs")
        await db_session.commit()

        resp = await client.request(
            "DELETE",
            f"{API_PREFIX}/privacy/user-data",
            json={"confirm": "DELETE"},
        )
        assert resp.status_code == 200, resp.text

        # Verify other user's data still exists
        result = await db_session.execute(
            select(Todo).where(Todo.user_id == OTHER_USER_ID)
        )
        remaining = result.scalars().all()
        assert len(remaining) == 1
        assert remaining[0].title == "theirs"

    @pytest.mark.asyncio
    async def test_data_summary_endpoint(self, client, db_session):
        """Verify: /privacy/data-summary 返回数据概览。"""
        await insert_todo(db_session, title="t1")
        await insert_todo(db_session, title="t2")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/privacy/data-summary")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["user_id"] == TEST_USER_ID
        assert body["counts"]["todos"] >= 2

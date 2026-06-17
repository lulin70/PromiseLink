#!/usr/bin/env python3
"""PromiseLink E2E 用户旅程扩展测试 — 覆盖真实用户使用场景.

8 大场景:
  1. 新用户首次使用完整流程 (注册→空状态→录入→查看解析结果)
  2. 多事件记录和管理 (3种类型→列表→删除→级联清理)
  3. 人脉关系管理 (列表→搜索→详情→编辑→删除)
  4. 承诺确认和履约 (待确认→确认→完成→忽略)
  5. 日程预定和录入 (创建→列表→录入→取消→过期)
  6. 仪表盘和数据展示 (日视图→晨报→关怀提醒→逾期)
  7. 数据导出 (格式→完整性)
  8. 边界和错误场景 (空状态→无效输入→权限验证)

使用 in-memory SQLite + httpx.AsyncClient + FastAPI 依赖覆盖,
LLM 调用被 mock, 无需外部服务, 测试可独立运行.

运行方式:
  cd /Users/lin/trae_projects/PromiseLink && \\
  python3 -m pytest scripts/e2e/e2e_user_journey_extended.py -v --tb=short
"""

import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Ensure src is on path (for running outside tests/ directory)
project_root = Path(__file__).parent.parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from promiselink.core.auth import get_current_user_id  # noqa: E402
from promiselink.database import Base, get_async_session  # noqa: E402
from promiselink.main import app  # noqa: E402
from promiselink.models.association import Association  # noqa: E402
from promiselink.models.entity import Entity  # noqa: E402
from promiselink.models.event import Event  # noqa: E402
from promiselink.models.todo import Todo  # noqa: E402

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000010"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000020"
API_PREFIX = "/api/v1"


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset in-memory rate limiter state before each test."""
    from promiselink.core.rate_limiter import reset_rate_limits

    reset_rate_limits()
    yield
    reset_rate_limits()


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


# ══════════════════════════════════════════════════════════════════════════════
# Helpers — 直接插入测试数据到 DB
# ══════════════════════════════════════════════════════════════════════════════


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
        entity = await insert_entity(
            session, source_event_id=source_event_id, name="Source Entity"
        )
        source_entity_id = entity.id
    if target_entity_id is None:
        entity2 = await insert_entity(
            session, source_event_id=source_event_id, name="Target Entity"
        )
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
# 场景 1: 新用户首次使用完整流程
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario1NewUserFirstUse:
    """新用户首次使用完整流程: 登录→空状态→录入→查看解析结果."""

    @pytest.mark.asyncio
    async def test_empty_state_before_first_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """1.1 新用户登录后看到空状态: 0 事件, 0 实体, 0 待办."""
        # 验证事件列表为空
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

        # 验证实体列表为空
        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

        # 验证待办列表为空
        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

        # 验证承诺列表为空
        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_first_event_creation_and_view(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """1.2 新用户记录第一次交流并查看事件详情."""
        # 创建第一个事件
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "manual",
                "title": "和张总的第一次见面",
                "raw_text": "今天和张总见面聊了合作, 张总承诺下周提供技术方案.",
            },
        )
        assert resp.status_code == 201
        event_data = resp.json()
        event_id = event_data["id"]
        assert event_data["event_type"] == "meeting"
        assert event_data["title"] == "和张总的第一次见面"
        assert event_data["status"] == "pending"
        assert event_data["pipeline_status"] == "pending"

        # 查询事件列表, 应有 1 条
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["id"] == event_id

        # 查看事件详情
        resp = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == event_id
        assert detail["title"] == "和张总的第一次见面"
        assert "raw_text" in detail
        assert detail["raw_text"] == "今天和张总见面聊了合作, 张总承诺下周提供技术方案."

    @pytest.mark.asyncio
    async def test_first_entity_and_todo_view(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """1.3 新用户查看首次交流后生成的人脉和待办."""
        # 直接插入测试数据 (mock pipeline 不实际处理)
        event = await insert_event(
            db_session,
            title="和王总见面",
            raw_text="今天和王总见面, 我答应下周发他一份方案.",
        )
        entity = await insert_entity(
            db_session,
            name="王总",
            canonical_name="王总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某集团", "title": "总经理"},
                "concern": [{"category": "合作", "detail": "需要方案"}],
            },
        )
        todo = await insert_todo(
            db_session,
            title="给王总发方案",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=1,
            action_type="my_promise",
        )
        await db_session.commit()

        # 查看人脉列表
        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "王总"

        # 查看待办列表
        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "给王总发方案"
        assert data["items"][0]["todo_type"] == "promise"

        # 查看承诺列表
        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["description"] == "Send a message" or \
               data["items"][0]["todo_id"] == str(todo.id)


# ══════════════════════════════════════════════════════════════════════════════
# 场景 2: 多事件记录和管理
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario2MultiEventManagement:
    """多事件记录和管理: 3种类型→列表→删除→级联清理."""

    @pytest.mark.asyncio
    async def test_create_three_different_event_types(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """2.1 连续记录 3 个不同类型事件 (会议/通话/微信转发)."""
        event_types = [
            ("meeting", "项目讨论会议", "和张总讨论了新项目合作方案"),
            ("call", "电话跟进", "给李总打电话跟进项目进度"),
            ("wechat_forward", "微信消息", "收到王总转发的合作机会"),
        ]

        created_ids = []
        for event_type, title, raw_text in event_types:
            resp = await client.post(
                f"{API_PREFIX}/events",
                json={
                    "event_type": event_type,
                    "source": "manual",
                    "title": title,
                    "raw_text": raw_text,
                },
            )
            assert resp.status_code == 201
            created_ids.append(resp.json()["id"])

        # 验证事件列表有 3 条
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

        # 验证事件类型分布
        types_in_list = {e["event_type"] for e in data["items"]}
        assert types_in_list == {"meeting", "call", "wechat_forward"}

    @pytest.mark.asyncio
    async def test_event_list_filtering_by_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """2.2 按事件类型过滤事件列表."""
        # 创建 3 种类型事件
        for event_type, title in [
            ("meeting", "会议1"),
            ("call", "通话1"),
            ("meeting", "会议2"),
        ]:
            resp = await client.post(
                f"{API_PREFIX}/events",
                json={
                    "event_type": event_type,
                    "source": "manual",
                    "title": title,
                    "raw_text": f"{title}内容",
                },
            )
            assert resp.status_code == 201

        # 过滤 meeting 类型
        resp = await client.get(
            f"{API_PREFIX}/events", params={"event_type": "meeting"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(e["event_type"] == "meeting" for e in data["items"])

        # 过滤 call 类型
        resp = await client.get(
            f"{API_PREFIX}/events", params={"event_type": "call"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["event_type"] == "call"

    @pytest.mark.asyncio
    async def test_delete_event_cascades_cleanup(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """2.3 删除事件后关联数据 (实体/待办/关联) 被清理."""
        # 创建事件 + 实体 + 待办
        event = await insert_event(
            db_session,
            title="待删除事件",
            raw_text="测试删除事件后的级联清理",
        )
        entity = await insert_entity(
            db_session,
            name="待清理人脉",
            source_event_id=event.id,
        )
        await insert_todo(
            db_session,
            title="待清理待办",
            source_event_id=event.id,
            related_entity_id=entity.id,
        )
        await db_session.commit()

        event_id = str(event.id)
        entity_id = str(entity.id)

        # 删除事件
        resp = await client.delete(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 204

        # 验证事件已删除
        resp = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 404

        # 验证关联实体已清理 (delete_event_cascade 删除 source_event_id 匹配的实体)
        resp = await client.get(f"{API_PREFIX}/entities/{entity_id}")
        assert resp.status_code == 404

        # 验证事件列表为空
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 场景 3: 人脉关系管理
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario3EntityManagement:
    """人脉关系管理: 列表→搜索→详情→编辑→删除."""

    @pytest.mark.asyncio
    async def test_entity_list_and_search(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """3.1 查看人脉列表并按名称搜索."""
        # 创建多个人脉
        event = await insert_event(db_session, title="人脉测试事件")
        await insert_entity(
            db_session,
            name="张三",
            canonical_name="张三",
            source_event_id=event.id,
            properties={"basic": {"company": "阿里", "title": "总监"}},
        )
        await insert_entity(
            db_session,
            name="李四",
            canonical_name="李四",
            source_event_id=event.id,
            properties={"basic": {"company": "腾讯", "title": "经理"}},
        )
        await insert_entity(
            db_session,
            name="王五",
            canonical_name="王五",
            source_event_id=event.id,
            properties={"basic": {"company": "百度", "title": "工程师"}},
        )
        await db_session.commit()

        # 查看全部人脉
        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

        # 搜索 "张"
        resp = await client.get(
            f"{API_PREFIX}/entities", params={"search": "张"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "张三"

        # 搜索 "李四"
        resp = await client.get(
            f"{API_PREFIX}/entities", params={"search": "李四"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "李四"

    @pytest.mark.asyncio
    async def test_entity_detail_and_history(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """3.2 查看人脉详情和互动历史."""
        event = await insert_event(
            db_session,
            title="与赵六的会议",
            raw_text="和赵六讨论了AI合作机会",
        )
        entity = await insert_entity(
            db_session,
            name="赵六",
            canonical_name="赵六",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某AI公司", "title": "CTO", "city": "北京"},
                "concern": [{"category": "AI应用", "detail": "寻找AI落地场景"}],
            },
        )
        await insert_todo(
            db_session,
            title="给赵六发AI案例",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
        )
        await db_session.commit()

        # 查看实体详情
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["name"] == "赵六"
        assert detail["canonical_name"] == "赵六"
        assert detail["entity_type"] == "person"

        # 查看实体历史
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert history["entity"]["name"] == "赵六"
        assert len(history["events"]) >= 1
        assert len(history["todos"]) >= 1
        assert history["events"][0]["title"] == "与赵六的会议"

    @pytest.mark.asyncio
    async def test_entity_update(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """3.3 编辑人脉信息 (名称/别名/属性)."""
        event = await insert_event(db_session, title="编辑测试")
        entity = await insert_entity(
            db_session,
            name="原名称",
            canonical_name="原名称",
            source_event_id=event.id,
        )
        await db_session.commit()

        # 更新名称和别名
        resp = await client.patch(
            f"{API_PREFIX}/entities/{entity.id}",
            json={
                "name": "新名称",
                "aliases": ["小新", "NewName"],
                "properties": {
                    "basic": {"company": "新公司", "title": "新职位"}
                },
                "status": "confirmed",
            },
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "新名称"
        assert "小新" in updated["aliases"]
        assert "NewName" in updated["aliases"]
        assert updated["status"] == "confirmed"

        # 验证更新持久化
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["name"] == "新名称"

    @pytest.mark.asyncio
    async def test_entity_delete_removes_associations(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """3.4 删除人脉后关联关系被清理."""
        event = await insert_event(db_session, title="删除人脉测试")
        entity_a = await insert_entity(
            db_session, name="人脉A", source_event_id=event.id
        )
        entity_b = await insert_entity(
            db_session, name="人脉B", source_event_id=event.id
        )
        assoc = await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            source_event_id=event.id,
        )
        await db_session.commit()

        assoc_id = str(assoc.id)

        # 删除人脉 A
        resp = await client.delete(f"{API_PREFIX}/entities/{entity_a.id}")
        assert resp.status_code == 204

        # 验证人脉 A 已删除
        resp = await client.get(f"{API_PREFIX}/entities/{entity_a.id}")
        assert resp.status_code == 404

        # 验证人脉 B 仍存在
        resp = await client.get(f"{API_PREFIX}/entities/{entity_b.id}")
        assert resp.status_code == 200

        # 验证关联关系已清理
        resp = await client.get(f"{API_PREFIX}/associations")
        assert resp.status_code == 200
        remaining_ids = [a["id"] for a in resp.json()["items"]]
        assert assoc_id not in remaining_ids


# ══════════════════════════════════════════════════════════════════════════════
# 场景 4: 承诺确认和履约
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario4PromiseFulfillment:
    """承诺确认和履约: 待确认→确认→完成→忽略."""

    @pytest.mark.asyncio
    async def test_pending_confirmations_list(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """4.1 查看待确认承诺列表."""
        event = await insert_event(db_session, title="承诺测试事件")
        # 创建待确认的承诺 (my_promise)
        await insert_todo(
            db_session,
            title="我承诺发方案",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="pending",
            description="我答应下周发技术方案",
        )
        # 创建待确认的承诺 (their_promise)
        await insert_todo(
            db_session,
            title="对方承诺提供资料",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            action_type="their_promise",
            confirmation_status="auto_set",
            description="对方说会发资料",
        )
        await db_session.commit()

        # 查看待确认承诺
        resp = await client.get(f"{API_PREFIX}/todos/pending-confirmations")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2
        # 验证都是 promise 类型且待确认
        for item in items:
            assert item["todo_type"] == "promise"
            assert item["confirmation_status"] in ("pending", "auto_set")
            assert item["action_type"] in ("my_promise", "their_promise")

    @pytest.mark.asyncio
    async def test_confirm_promise(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """4.2 确认承诺 (confirmed) 并验证状态变化."""
        event = await insert_event(db_session, title="确认承诺测试")
        todo = await insert_todo(
            db_session,
            title="待确认承诺",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="pending",
            description="原描述",
        )
        await db_session.commit()

        # 确认承诺, 同时修正描述和截止日期
        new_due = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={
                "confirmation_status": "confirmed",
                "description": "确认后的描述",
                "due_date": new_due,
            },
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["confirmation_status"] == "confirmed"
        assert result["status"] == "pending"  # confirmed 后仍为 pending (可执行)

        # 验证数据库状态
        resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["description"] == "确认后的描述"

    @pytest.mark.asyncio
    async def test_reject_promise_dismisses_it(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """4.3 忽略 (reject) 不需要的承诺, 验证状态变为 dismissed."""
        event = await insert_event(db_session, title="忽略承诺测试")
        todo = await insert_todo(
            db_session,
            title="不需要的承诺",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="pending",
        )
        await db_session.commit()

        # 拒绝承诺
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "rejected"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["confirmation_status"] == "rejected"
        assert result["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_mark_promise_fulfilled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """4.4 标记承诺已履约 (fulfilled)."""
        event = await insert_event(db_session, title="履约测试")
        todo = await insert_todo(
            db_session,
            title="已兑现承诺",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="confirmed",
            fulfillment_status="pending",
        )
        await db_session.commit()

        # 标记为已履约
        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["fulfillment_status"] == "fulfilled"

        # 验证承诺统计中 fulfilled 计数增加
        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["my_promises"]["fulfilled"] == 1
        assert stats["fulfillment_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_promise_stats_dual_view(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """4.5 承诺统计双视图 (我的承诺 vs 对方承诺)."""
        event = await insert_event(db_session, title="双视图统计")
        # 我的承诺 - pending
        await insert_todo(
            db_session,
            title="我的待兑现承诺",
            todo_type="promise",
            source_event_id=event.id,
            action_type="my_promise",
            fulfillment_status="pending",
        )
        # 我的承诺 - fulfilled
        await insert_todo(
            db_session,
            title="我的已兑现承诺",
            todo_type="promise",
            source_event_id=event.id,
            action_type="my_promise",
            fulfillment_status="fulfilled",
        )
        # 对方承诺 - pending
        await insert_todo(
            db_session,
            title="对方待兑现承诺",
            todo_type="promise",
            source_event_id=event.id,
            action_type="their_promise",
            fulfillment_status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total"] == 3
        assert stats["my_promises"]["pending"] == 1
        assert stats["my_promises"]["fulfilled"] == 1
        assert stats["their_promises"]["pending"] == 1
        # 兑现率 = 1/3
        assert abs(stats["fulfillment_rate"] - 1 / 3) < 0.001


# ══════════════════════════════════════════════════════════════════════════════
# 场景 5: 日程预定和录入
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario5ScheduledEvents:
    """日程预定和录入: 创建→列表→录入→取消→过期."""

    @pytest.mark.asyncio
    async def test_create_scheduled_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """5.1 创建预定日程 (未来时间 → pending 状态)."""
        future_time = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "下周与张总的合作会议",
                "participants": [
                    {"name": "张总", "company": "某集团"}
                ],
                "location": "望京SOHO",
                "event_type": "meeting",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["topic"] == "下周与张总的合作会议"
        assert data["status"] == "pending"
        assert data["event_type"] == "meeting"
        assert data["location"] == "望京SOHO"
        assert len(data["participants"]) == 1
        assert data["participants"][0]["name"] == "张总"

    @pytest.mark.asyncio
    async def test_list_scheduled_events_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """5.2 查看预定日程列表并按状态过滤."""
        # 创建 2 个 pending + 1 个 cancelled
        future1 = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        future2 = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        future3 = (datetime.now(UTC) + timedelta(days=7)).isoformat()

        r1 = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={"scheduled_at": future1, "topic": "会议1", "event_type": "meeting"},
        )
        assert r1.status_code == 201
        r2 = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={"scheduled_at": future2, "topic": "会议2", "event_type": "call"},
        )
        assert r2.status_code == 201
        r3 = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={"scheduled_at": future3, "topic": "会议3", "event_type": "meeting"},
        )
        assert r3.status_code == 201

        # 取消第三个
        cancel_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{r3.json()['id']}/cancel",
            json={"cancel_reason": "时间冲突"},
        )
        assert cancel_resp.status_code == 200

        # 查看全部
        resp = await client.get(f"{API_PREFIX}/scheduled-events")
        assert resp.status_code == 200
        assert resp.json()["total"] == 3

        # 过滤 pending
        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"status": "pending"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert all(item["status"] == "pending" for item in data["items"])

        # 过滤 cancelled
        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"status": "cancelled"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["status"] == "cancelled"
        assert data["items"][0]["cancel_reason"] == "时间冲突"

    @pytest.mark.asyncio
    async def test_record_scheduled_event_creates_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """5.3 录入预定日程 (转为事件, 触发 pipeline)."""
        future_time = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        # 创建预定日程
        create_resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "产品演示会议",
                "event_type": "meeting",
                "participants": [{"name": "李总"}],
            },
        )
        assert create_resp.status_code == 201
        se_id = create_resp.json()["id"]

        # 录入实际内容
        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/record",
            json={
                "raw_text": "和李总进行了产品演示, 李总对功能很满意, 承诺下周签约.",
            },
        )
        assert record_resp.status_code == 200
        record_data = record_resp.json()
        assert record_data["scheduled_event_id"] == se_id
        assert record_data["pipeline_status"] == "pending"
        event_id = record_data["event_id"]

        # 验证预定日程状态变为 recorded
        resp = await client.get(f"{API_PREFIX}/scheduled-events/{se_id}")
        assert resp.status_code == 200
        se_detail = resp.json()
        assert se_detail["status"] == "recorded"
        assert se_detail["linked_event_id"] == event_id

        # 验证事件已创建
        resp = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 200
        event_detail = resp.json()
        assert event_detail["title"] == "产品演示会议"
        assert event_detail["source"] == "scheduled_record"

    @pytest.mark.asyncio
    async def test_cancel_scheduled_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """5.4 取消预定日程 (带取消原因)."""
        future_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        create_resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "待取消会议",
                "event_type": "meeting",
            },
        )
        assert create_resp.status_code == 201
        se_id = create_resp.json()["id"]

        # 取消
        cancel_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/cancel",
            json={"cancel_reason": "客户临时有事"},
        )
        assert cancel_resp.status_code == 200
        cancelled = cancel_resp.json()
        assert cancelled["status"] == "cancelled"
        assert cancelled["cancel_reason"] == "客户临时有事"

    @pytest.mark.asyncio
    async def test_overdue_scheduled_event_marked(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """5.5 过期预定日程被标记为 overdue."""
        # 创建一个过去时间的预定日程 (应自动标记为 overdue)
        past_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": past_time,
                "topic": "已过期的会议",
                "event_type": "meeting",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # 过去时间应被标记为 overdue
        assert data["status"] == "overdue"

        # 验证在列表中能通过 overdue 过滤找到
        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", params={"status": "overdue"}
        )
        assert resp.status_code == 200
        overdue_list = resp.json()
        assert overdue_list["total"] >= 1
        assert any(item["topic"] == "已过期的会议" for item in overdue_list["items"])


# ══════════════════════════════════════════════════════════════════════════════
# 场景 6: 仪表盘和数据展示
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario6Dashboard:
    """仪表盘和数据展示: 日视图→晨报→关怀提醒→逾期."""

    @pytest.mark.asyncio
    async def test_day_view_with_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """6.1 日视图展示今日事件和待办."""
        # 创建今日事件
        today = datetime.now(UTC)
        event = await insert_event(
            db_session,
            title="今日会议",
            raw_text="今天的会议内容",
            timestamp=today,
            status="completed",
        )
        entity = await insert_entity(
            db_session,
            name="今日人脉",
            source_event_id=event.id,
        )
        await insert_todo(
            db_session,
            title="今日待办",
            todo_type="followup",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            due_date=today,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/day-view")
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert "date_label" in data
        assert "summary" in data
        assert "events" in data
        assert "todos" in data
        assert "adjacent_dates" in data
        # summary 字段存在且为非负数
        assert data["summary"]["total_events"] >= 0
        assert data["summary"]["total_todos"] >= 0
        # 相邻日期格式为 ISO
        assert "previous_day" in data["adjacent_dates"]
        assert "next_day" in data["adjacent_dates"]

    @pytest.mark.asyncio
    async def test_morning_brief_structure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """6.2 晨报结构正确, 包含问候语和统计."""
        event = await insert_event(db_session, title="晨报测试")
        await insert_todo(
            db_session,
            title="待处理承诺",
            todo_type="promise",
            source_event_id=event.id,
            status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert "greeting" in data
        assert data["greeting"] in ("早上好", "下午好", "晚上好")
        assert "pending_promises" in data
        assert "pending_cares" in data
        assert "overdue_todos" in data
        assert "today_events" in data
        assert "today_todos" in data
        assert "key_persons" in data
        assert "summary_text" in data
        # 至少有 1 个待处理承诺
        assert data["pending_promises"] >= 1

    @pytest.mark.asyncio
    async def test_care_reminders_with_concerns(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """6.3 关怀提醒展示含个人关怀点的联系人."""
        event = await insert_event(db_session, title="关怀测试")
        await insert_entity(
            db_session,
            name="需要关怀的人",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某公司", "title": "总监"},
                "concern": [
                    {"category": "家庭", "detail": "孩子今年高考"}
                ],
            },
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "personal_items" in data
        assert "business_items" in data
        assert "summary_text" in data
        # 应识别到个人关怀点 (孩子高考 → family_milestone)
        personal_names = [p["name"] for p in data["personal_items"]]
        assert "需要关怀的人" in personal_names

    @pytest.mark.asyncio
    async def test_relationship_health_summary(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """6.4 关系健康度展示统计和分级."""
        event = await insert_event(db_session, title="健康度测试")
        await insert_entity(
            db_session,
            name="健康人脉1",
            source_event_id=event.id,
        )
        await insert_entity(
            db_session,
            name="健康人脉2",
            source_event_id=event.id,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/relationship-health")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_entities" in data
        assert "healthy_count" in data
        assert "attention_count" in data
        assert "at_risk_count" in data
        assert "items" in data
        assert "summary_text" in data
        assert data["total_entities"] == 2
        # 健康度分级总和应等于总数
        assert (
            data["healthy_count"] + data["attention_count"] + data["at_risk_count"]
            == data["total_entities"]
        )


# ══════════════════════════════════════════════════════════════════════════════
# 场景 7: 数据导出
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario7DataExport:
    """数据导出: 格式→完整性."""

    @pytest.mark.asyncio
    async def test_export_format_structure(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """7.1 导出数据格式正确, 包含所有必需字段."""
        event = await insert_event(db_session, title="导出格式测试")
        await insert_entity(
            db_session,
            name="导出人脉",
            source_event_id=event.id,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()

        # 验证导出格式
        assert data["export_version"] == "1.0"
        assert "exported_at" in data
        assert data["user_id"] == TEST_USER_ID
        assert "events" in data
        assert "entities" in data
        assert "associations" in data
        assert "todos" in data
        assert "vector_embeddings" in data

    @pytest.mark.asyncio
    async def test_export_data_integrity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """7.2 导出数据完整性: 事件/实体/待办/关联全部包含."""
        # 创建完整数据集
        event = await insert_event(
            db_session,
            title="完整性测试事件",
            raw_text="测试导出数据完整性",
        )
        entity_a = await insert_entity(
            db_session,
            name="完整性人脉A",
            canonical_name="完整性人脉A",
            source_event_id=event.id,
            properties={"basic": {"company": "完整性公司", "title": "完整性职位"}},
        )
        entity_b = await insert_entity(
            db_session,
            name="完整性人脉B",
            source_event_id=event.id,
        )
        await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            source_event_id=event.id,
            association_type="co_occurrence",
        )
        await insert_todo(
            db_session,
            title="完整性待办",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity_a.id,
            status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()

        # 验证事件完整性
        assert len(data["events"]) == 1
        exported_event = data["events"][0]
        assert exported_event["title"] == "完整性测试事件"
        assert exported_event["raw_text"] == "测试导出数据完整性"
        assert exported_event["user_id"] == TEST_USER_ID

        # 验证实体完整性
        assert len(data["entities"]) == 2
        entity_names = {e["name"] for e in data["entities"]}
        assert "完整性人脉A" in entity_names
        assert "完整性人脉B" in entity_names

        # 验证关联完整性
        assert len(data["associations"]) == 1
        assert data["associations"][0]["association_type"] == "co_occurrence"

        # 验证待办完整性
        assert len(data["todos"]) == 1
        assert data["todos"][0]["title"] == "完整性待办"
        assert data["todos"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_export_forbidden_for_other_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """7.3 不能导出其他用户的数据 (权限隔离)."""
        resp = await client.get(f"{API_PREFIX}/export/{OTHER_USER_ID}")
        assert resp.status_code == 403
        data = resp.json()
        assert "error" in data


# ══════════════════════════════════════════════════════════════════════════════
# 场景 8: 边界和错误场景
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario8BoundaryAndError:
    """边界和错误场景: 空状态→无效输入→权限验证."""

    @pytest.mark.asyncio
    async def test_empty_dashboard_shows_zero_state(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.1 空数据状态下仪表盘展示零值, 不报错."""
        resp = await client.get(f"{API_PREFIX}/dashboard/day-view")
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["total_events"] == 0
        assert data["summary"]["total_todos"] == 0
        assert data["summary"]["overdue_todos"] == 0
        assert data["summary"]["pending_promises"] == 0
        assert data["events"] == []
        assert data["todos"] == []

        # 晨报也为空状态
        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["pending_promises"] == 0
        assert brief["overdue_todos"] == 0
        assert brief["today_events"] == 0
        assert brief["key_persons"] == []

    @pytest.mark.asyncio
    async def test_invalid_event_type_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.2 无效事件类型被拒绝 (400 错误)."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "invalid_type",
                "source": "manual",
                "raw_text": "测试无效事件类型",
            },
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_missing_required_fields_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.3 缺少必填字段被拒绝 (422 错误)."""
        # 缺少 event_type
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={"source": "manual", "raw_text": "缺少 event_type"},
        )
        assert resp.status_code == 422

        # 缺少 source
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={"event_type": "meeting", "raw_text": "缺少 source"},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_oversized_raw_text_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.4 超大 raw_text (超过 500KB) 被拒绝."""
        # 构造 600KB 的文本
        oversized_text = "A" * (600 * 1024)
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "manual",
                "raw_text": oversized_text,
            },
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_event_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.5 获取不存在的事件返回 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/events/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_entity_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.6 获取不存在的人脉返回 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/entities/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_todo_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.7 删除不存在的待办返回 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.delete(f"{API_PREFIX}/todos/{fake_id}")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_invalid_todo_status_transition_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.8 无效待办状态转换被拒绝."""
        event = await insert_event(db_session, title="状态转换测试")
        todo = await insert_todo(
            db_session,
            title="状态转换待办",
            source_event_id=event.id,
            status="pending",
        )
        await db_session.commit()

        # 尝试转换为无效状态
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "invalid_status"},
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_invalid_confirmation_status_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.9 无效确认状态被拒绝."""
        event = await insert_event(db_session, title="确认状态测试")
        todo = await insert_todo(
            db_session,
            title="确认状态待办",
            source_event_id=event.id,
            action_type="my_promise",
            confirmation_status="pending",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "invalid_status"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_fulfillment_status_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.10 无效履约状态被拒绝."""
        event = await insert_event(db_session, title="履约状态测试")
        todo = await insert_todo(
            db_session,
            title="履约状态待办",
            source_event_id=event.id,
            action_type="my_promise",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "invalid_status"},
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_scheduled_event_invalid_type_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.11 预定日程无效事件类型被拒绝."""
        future_time = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "无效类型测试",
                "event_type": "invalid_type",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_cancel_recorded_scheduled_event_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.12 取消已录入的预定日程返回冲突错误 (409)."""
        future_time = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        # 创建并录入
        create_resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "已录入会议",
                "event_type": "meeting",
            },
        )
        assert create_resp.status_code == 201
        se_id = create_resp.json()["id"]

        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/record",
            json={"raw_text": "会议内容"},
        )
        assert record_resp.status_code == 200

        # 尝试取消已录入的预定日程 → 应失败
        cancel_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/cancel",
            json={"cancel_reason": "尝试取消"},
        )
        assert cancel_resp.status_code == 409

    @pytest.mark.asyncio
    async def test_record_cancelled_scheduled_event_conflict(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.13 录入已取消的预定日程返回冲突错误 (409)."""
        future_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        create_resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            json={
                "scheduled_at": future_time,
                "topic": "已取消会议",
                "event_type": "meeting",
            },
        )
        assert create_resp.status_code == 201
        se_id = create_resp.json()["id"]

        # 先取消
        cancel_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/cancel",
            json={"cancel_reason": "时间冲突"},
        )
        assert cancel_resp.status_code == 200

        # 尝试录入已取消的预定日程 → 应失败
        record_resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/record",
            json={"raw_text": "尝试录入"},
        )
        assert record_resp.status_code == 409

    @pytest.mark.asyncio
    async def test_health_check_no_auth_required(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """8.14 健康检查端点不需要认证."""
        # 临时清除依赖覆盖来测试无认证场景
        saved = app.dependency_overrides.copy()
        app.dependency_overrides.clear()

        try:
            resp = await client.get(f"{API_PREFIX}/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "healthy"
            assert "version" in data
            assert "edition" in data
        finally:
            app.dependency_overrides.update(saved)

    @pytest.mark.asyncio
    async def test_data_isolation_between_users(
        self, client: AsyncSession, db_session: AsyncSession
    ):
        """8.15 用户数据隔离: 切换用户后看不到其他用户数据."""
        # 用 TEST_USER_ID 创建数据
        event = await insert_event(
            db_session,
            title="用户A的事件",
            raw_text="用户A的私有数据",
        )
        await db_session.commit()

        # 切换到其他用户
        saved = app.dependency_overrides[get_current_user_id]
        app.dependency_overrides[get_current_user_id] = lambda: OTHER_USER_ID

        try:
            # 其他用户看不到 TEST_USER 的事件
            resp = await client.get(f"{API_PREFIX}/events")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total"] == 0
            assert data["items"] == []

            # 其他用户看不到 TEST_USER 的实体
            resp = await client.get(f"{API_PREFIX}/entities")
            assert resp.status_code == 200
            assert resp.json()["total"] == 0

            # 其他用户访问 TEST_USER 的事件详情 → 404
            resp = await client.get(f"{API_PREFIX}/events/{event.id}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides[get_current_user_id] = saved

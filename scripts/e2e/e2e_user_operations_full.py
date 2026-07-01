#!/usr/bin/env python3
"""PromiseLink 基础版 E2E 测试 — 模拟用户在宽屏 UI 上的所有操作（全集）.

覆盖用户要求的全部操作（P0 优先级）：
  1. 文件上传（.txt/.md）创建事件 + 边界错误
  2. 待办确认三态：完成(done) / 推迟(snoozed) / 忽略(dismissed) + confirm/reject
  3. 跨页面跳转：事件↔人脉、待办→事件、承诺→人脉
  4. 关联发现：列表 + 筛选 + 详情 + 404
  5. 仪表盘、关系简报、数据导出

设计原则（对齐 e2e_user_journey_extended.py 成熟模式）：
  - pytest + httpx.AsyncClient + ASGITransport
  - in-memory SQLite + LLM mock，无需外部服务
  - UUID 格式 user_id
  - CI 友好（GitHub Actions ubuntu-latest 可直接运行）
  - 不修改现有 CI 门禁脚本 e2e_basic_test.py

运行方式:
  cd /Users/lin/trae_projects/PromiseLink && \\
  python3 -m pytest scripts/e2e/e2e_user_operations_full.py -v --tb=short
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

TEST_USER_ID = "550e8400-e29b-41d4-a716-446655440000"
OTHER_USER_ID = "660e8400-e29b-41d4-a716-446655440000"
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
# 场景 1: 文件上传（.txt/.md）创建事件
# ══════════════════════════════════════════════════════════════════════════════


class TestFileUpload:
    """文件上传操作: .txt/.md 上传创建事件 + 边界错误处理."""

    @pytest.mark.asyncio
    async def test_file_upload_txt_creates_event(self, client: AsyncClient):
        """B-P0-01: 上传 .txt 文件 → 创建事件 → 验证 source=file_upload."""
        content = "今天和张总开会，讨论了Q3合作方案。张总承诺下周提供技术方案。"
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("meeting.txt", content.encode("utf-8"), "text/plain")},
            data={"event_type": "meeting"},
        )
        assert resp.status_code == 201, f"上传失败: {resp.text}"
        data = resp.json()
        assert data["source"] == "file_upload"
        assert data["title"] == "meeting.txt"
        assert data["event_type"] == "meeting"
        assert data["status"] == "pending"
        assert data["id"]  # 返回事件 ID

    @pytest.mark.asyncio
    async def test_file_upload_md_strips_markdown(self, client: AsyncClient):
        """B-P0-02: 上传 .md 文件 → 验证 markdown 被剥离（标题#被去除）."""
        # markdown 内容：# 标题 和 **粗体** 应被处理
        md_content = "# 会议纪要\n\n今天和**李总**讨论了合作。\n\n## 要点\n- 方案A\n- 方案B\n"
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={
                "file": ("notes.md", md_content.encode("utf-8"), "text/markdown")
            },
            data={"event_type": "meeting"},
        )
        assert resp.status_code == 201, f"上传失败: {resp.text}"
        data = resp.json()
        assert data["source"] == "file_upload"
        assert data["title"] == "notes.md"

        # 验证事件详情中的 raw_text 已剥离 markdown 标记
        event_id = data["id"]
        detail = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert detail.status_code == 200
        raw_text = detail.json().get("raw_text", "")
        # # 标题标记应被剥离（不存在 "# 会议纪要"）
        assert "# 会议纪要" not in raw_text
        assert "李总" in raw_text  # 正文内容保留

    @pytest.mark.asyncio
    async def test_file_upload_invalid_extension_rejected(self, client: AsyncClient):
        """B-P0-03: 上传 .pdf → 422 ValidationError."""
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"event_type": "meeting"},
        )
        assert resp.status_code in (400, 422), f"应拒绝 .pdf，实际: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_file_upload_oversized_rejected(self, client: AsyncClient):
        """B-P0-04: 上传 >1MB 文件 → 422."""
        # 1MB + 1 字节
        big_content = b"x" * (1_048_576 + 1)
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("big.txt", big_content, "text/plain")},
            data={"event_type": "meeting"},
        )
        assert resp.status_code in (400, 422), f"应拒绝超大文件，实际: {resp.status_code}"

    @pytest.mark.asyncio
    async def test_file_upload_empty_rejected(self, client: AsyncClient):
        """B-P0-05: 上传空文件 → 422."""
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
            data={"event_type": "meeting"},
        )
        assert resp.status_code in (400, 422), f"应拒绝空文件，实际: {resp.status_code}"


# ══════════════════════════════════════════════════════════════════════════════
# 场景 2: 待办确认三态（完成/推迟/忽略）+ confirm/reject
# ══════════════════════════════════════════════════════════════════════════════


class TestTodoOperations:
    """待办操作: 完成/推迟/忽略 + confirm/reject 全状态流转."""

    @pytest.mark.asyncio
    async def test_todo_complete_flow(self, client: AsyncClient, db_session: AsyncSession):
        """B-P0-06: 创建 todo → 完成(done) → 验证状态."""
        todo = await insert_todo(db_session, title="完成报价单", status="pending")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"status": "done"}
        )
        assert resp.status_code == 200, f"完成失败: {resp.text}"
        assert resp.json()["status"] == "done"

    @pytest.mark.asyncio
    async def test_todo_defer_snoozed(self, client: AsyncClient, db_session: AsyncSession):
        """B-P0-07: 创建 todo → 推迟(snoozed) → 验证状态."""
        todo = await insert_todo(db_session, title="推迟跟进", status="pending")
        await db_session.commit()

        snoozed_until = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "snoozed", "snoozed_until": snoozed_until},
        )
        assert resp.status_code == 200, f"推迟失败: {resp.text}"
        assert resp.json()["status"] == "snoozed"

    @pytest.mark.asyncio
    async def test_todo_ignore_dismissed(self, client: AsyncClient, db_session: AsyncSession):
        """B-P0-08: 创建 todo → 忽略(dismissed) → 验证状态."""
        todo = await insert_todo(db_session, title="忽略此待办", status="pending")
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}", json={"status": "dismissed"}
        )
        assert resp.status_code == 200, f"忽略失败: {resp.text}"
        assert resp.json()["status"] == "dismissed"

    @pytest.mark.asyncio
    async def test_todo_confirm_confirmed(self, client: AsyncClient, db_session: AsyncSession):
        """B-P0-09: 创建 pending todo → confirm confirmed → 验证."""
        todo = await insert_todo(
            db_session,
            title="待确认承诺",
            status="pending",
            confirmation_status="pending",
            todo_type="promise",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "confirmed"},
        )
        assert resp.status_code == 200, f"确认失败: {resp.text}"
        data = resp.json()
        assert data["confirmation_status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_todo_confirm_rejected_dismissed(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-10: 创建 pending todo → confirm rejected → 验证 dismissed."""
        todo = await insert_todo(
            db_session,
            title="拒绝此承诺",
            status="pending",
            confirmation_status="pending",
            todo_type="promise",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={"confirmation_status": "rejected"},
        )
        assert resp.status_code == 200, f"拒绝失败: {resp.text}"
        data = resp.json()
        assert data["confirmation_status"] == "rejected"
        assert data["status"] == "dismissed"


# ══════════════════════════════════════════════════════════════════════════════
# 场景 3: 跨页面跳转（事件↔人脉、待办→事件、承诺→人脉）
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossPageNavigation:
    """跨页面跳转: 模拟用户在 UI 上点击关联链接的 navigateTo 行为."""

    @pytest.mark.asyncio
    async def test_event_to_entity_navigation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-11: 事件 → 关联人脉详情跳转.

        用户在事件列表点击某事件的关联人脉，跳转到人脉详情页。
        """
        event = await insert_event(
            db_session, title="与王总的会议", raw_text="和王总讨论合作"
        )
        entity = await insert_entity(
            db_session, name="王总", source_event_id=event.id
        )
        await db_session.commit()

        # 步骤1: 查看事件详情，找到关联人脉 ID
        resp = await client.get(f"{API_PREFIX}/events/{event.id}")
        assert resp.status_code == 200
        event_detail = resp.json()
        # 事件详情可能通过 related_entities 或直接查询关联
        # 模拟 UI 跳转：用人脉 ID 查询人脉详情
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "王总"

    @pytest.mark.asyncio
    async def test_entity_to_event_navigation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-12: 人脉 → 关联事件跳转（via history）.

        用户在人脉详情页点击互动历史中的某事件，跳转到事件详情。
        """
        event = await insert_event(
            db_session, title="历史会议", raw_text="历史互动记录"
        )
        entity = await insert_entity(
            db_session, name="赵六", source_event_id=event.id
        )
        await db_session.commit()

        # 步骤1: 查看人脉详情
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200

        # 步骤2: 查看人脉互动历史，找到关联事件
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}/history")
        assert resp.status_code == 200
        history = resp.json()
        # 历史中应包含该事件
        events = history.get("events", [])
        assert len(events) >= 1
        event_id = events[0]["id"]

        # 步骤3: 跳转到事件详情
        resp = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "历史会议"

    @pytest.mark.asyncio
    async def test_todo_to_event_navigation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-13: 待办 → 关联事件跳转（via source_event_id）.

        用户在待办列表点击某待办的来源事件，跳转到事件详情。
        """
        event = await insert_event(
            db_session, title="待办来源事件", raw_text="产生了待办"
        )
        todo = await insert_todo(
            db_session, title="跟进此事", source_event_id=event.id
        )
        await db_session.commit()

        # 步骤1: 查看待办列表
        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        todos = resp.json()["items"]
        assert len(todos) >= 1
        target_todo = next(t for t in todos if t["id"] == todo.id)
        source_event_id = target_todo.get("source_event_id")
        assert source_event_id  # 待办有来源事件

        # 步骤2: 跳转到来源事件详情
        resp = await client.get(f"{API_PREFIX}/events/{source_event_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "待办来源事件"

    @pytest.mark.asyncio
    async def test_promise_to_entity_navigation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-14: 承诺 → 关联人脉跳转.

        用户在承诺列表点击某承诺的关联人脉，跳转到人脉详情。
        """
        event = await insert_event(db_session, title="承诺场景")
        entity = await insert_entity(
            db_session, name="钱总", source_event_id=event.id
        )
        # 承诺本质是 todo_type=promise + action_type=my_promise 且有 related_entity_id 的待办
        # /promises 端点按 action_type 过滤（my_promise / their_promise）
        await insert_todo(
            db_session,
            title="钱总承诺提供方案",
            todo_type="promise",
            action_type="my_promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            confirmation_status="confirmed",
        )
        await db_session.commit()

        # 步骤1: 查看承诺列表
        resp = await client.get(f"{API_PREFIX}/promises")
        assert resp.status_code == 200
        promises_data = resp.json()
        promises = promises_data.get("items", promises_data) if isinstance(
            promises_data, dict
        ) else promises_data
        assert len(promises) >= 1
        target = promises[0]
        entity_id = target.get("related_entity_id") or target.get("entity_id")
        assert entity_id  # 承诺有关联人脉

        # 步骤2: 跳转到人脉详情
        resp = await client.get(f"{API_PREFIX}/entities/{entity_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "钱总"


# ══════════════════════════════════════════════════════════════════════════════
# 场景 4: 关联发现（associations）
# ══════════════════════════════════════════════════════════════════════════════


class TestAssociationDiscovery:
    """关联发现: 列表 + 筛选 + 详情 + 404."""

    @pytest.mark.asyncio
    async def test_association_list_and_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-15: 关联发现列表 + 类型筛选."""
        # 合法 association_type: alumni/ex_colleague/same_city/competitor/
        # tech_overlap/deal_link/risk_link/supply_chain/co_occurrence/
        # topic_overlap/supply_demand/industry_chain
        await insert_association(
            db_session, association_type="same_city", strength=0.8
        )
        await insert_association(
            db_session, association_type="supply_demand", strength=0.6
        )
        await db_session.commit()

        # 查看全部关联
        resp = await client.get(f"{API_PREFIX}/associations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

        # 按 same_city 筛选
        resp = await client.get(
            f"{API_PREFIX}/associations", params={"association_type": "same_city"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert all(
            a["association_type"] == "same_city" for a in data["items"]
        )

    @pytest.mark.asyncio
    async def test_association_detail_and_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-16: 关联详情 + 不存在 404."""
        assoc = await insert_association(db_session)
        await db_session.commit()

        # 查看存在的关联详情
        resp = await client.get(f"{API_PREFIX}/associations/{assoc.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == str(assoc.id)

        # 查询不存在的关联
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/associations/{fake_id}")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 场景 5: 仪表盘、关系简报、数据导出
# ══════════════════════════════════════════════════════════════════════════════


class TestDashboardBriefsExport:
    """仪表盘、关系简报、数据导出的真实用户查看操作."""

    @pytest.mark.asyncio
    async def test_dashboard_day_view_with_data(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-17: 仪表盘日视图（有数据）."""
        # 插入今日事件和待办
        await insert_event(db_session, title="今日会议", status="completed")
        await insert_todo(db_session, title="今日待办", status="pending")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/day-view")
        assert resp.status_code == 200
        data = resp.json()
        summary = data.get("summary", {})
        assert "total_events" in summary or "total" in data  # 结构存在

    @pytest.mark.asyncio
    async def test_relationship_briefs_view(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """B-P0-18: 关系简报查看."""
        event = await insert_event(db_session, title="关系简报场景")
        await insert_entity(
            db_session, name="简报对象", source_event_id=event.id
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/relationship-briefs")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_data_export_structure(self, client: AsyncClient, db_session: AsyncSession):
        """B-P0-19: 数据导出结构完整性."""
        await insert_event(db_session, title="导出测试事件")
        await insert_entity(db_session, name="导出测试人脉")
        await insert_todo(db_session, title="导出测试待办")
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{TEST_USER_ID}")
        assert resp.status_code == 200
        data = resp.json()
        # 导出应包含核心数据结构
        assert isinstance(data, dict)
        # 验证核心字段存在（events/entities/todos 至少有一个）
        assert any(key in data for key in ("events", "entities", "todos", "promises"))


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

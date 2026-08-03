"""E2E tests for miniapp-backend API coverage.

确保小程序所有 API 调用都有基础版后端对应端点，且前后链路打通。

覆盖度审计与修复记录（2026-07-29）：
- 小程序 api.ts 共 49 个 API 调用
- 其中 38 个有基础版后端对应端点（直连模式可通）
- 原 6 处路径/字段不匹配已全部修复：
  1. pocLogin: /auth/poc-login → /auth/login ✅
  2. wechatLogin: /auth/wechat → /auth/wechat/login ✅
  3. searchEntities: /entities/search → /entities?search= ✅
  4. reminderAction: snooze_days → snooze_hours（含天数→小时转换）✅
  5. exportUserData: POST /privacy/export → GET /export/{user_id} ✅
  6. deleteUserData: 补充 confirm:'DELETE' body ✅
- 5 个为 Pro-only 端点（基础版不注册，设计如此）

本测试文件验证：
1. 每个有对应端点的小程序调用都有 e2e 测试
2. 验证副作用（DB 写入/状态变更），不只验证 status_code
3. 从用户旅程设计——模拟小程序真实调用顺序
4. 安全验证：不带 confirm body 的删除请求被 422 拒绝
5. Pro-only 端点在基础版返回 404（设计验证）
"""

import json
import uuid
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import create_access_token, get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

# ═══════════════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════════════

TEST_USER_ID = "00000000-0000-0000-0000-0000000000aa"
API_PREFIX = "/api/v1"
POC_SECRET = "promiselink2026"

MEETING_TEXT = (
    "今天和王总开会讨论Q3合作方案，王总是盛达集团的CTO。"
    "王总承诺下周三前发送合同草案，我答应周五前提供技术方案。"
)


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def file_engine(tmp_path):
    """文件级 SQLite 引擎 + session 工厂（API 与 Pipeline 共享同一 DB）."""
    db_path = str(tmp_path / "miniapp_coverage_e2e.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    @sa_event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    yield engine, session_factory, db_path

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _patch_non_llm_externals():
    """Patch embedding/semantic-search 以避免加载 sentence-transformers 模型."""
    stack = ExitStack()
    mock_embedder = AsyncMock()
    mock_embedder.embed = AsyncMock(return_value=[0.0] * 384)
    stack.enter_context(
        patch(
            "promiselink.services.embedding_provider.get_shared_provider",
            new=AsyncMock(return_value=mock_embedder),
        )
    )
    mock_engine = AsyncMock()
    mock_engine.index_entity = AsyncMock(return_value=None)
    mock_engine.index_event = AsyncMock(return_value=None)
    stack.enter_context(
        patch(
            "promiselink.services.semantic_search.get_shared_engine",
            new=AsyncMock(return_value=mock_engine),
        )
    )
    return stack


@pytest_asyncio.fixture
async def client(file_engine):
    """httpx AsyncClient + 依赖覆盖 + mock_pipeline stub.

    - get_async_session 每次请求产出新 session（真实后端行为）
    - get_current_user_id 返回 TEST_USER_ID（已认证客户端）
    - mock_pipeline stub 后台任务（AI 解析不在本测试范围）
    """
    engine, session_factory, _ = file_engine

    async def override_get_async_session():
        # 与真实 get_async_session 一致：yield 后 commit，确保 flush 的数据持久化
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    # Stub pipeline background task
    async def _noop_pipeline(event_id):
        pass

    with patch("promiselink.database.AsyncSessionLocal", session_factory), \
         patch(
             "promiselink.api.v1.events.process_event_background",
             new=_noop_pipeline,
         ), \
         patch(
             "promiselink.api.v1.event_pipeline_api.process_event_background",
             new=_noop_pipeline,
         ), \
         patch(
             "promiselink.api.v1.scheduled_events.process_event_background",
             new=_noop_pipeline,
         ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    app.dependency_overrides.clear()


@asynccontextmanager
async def db_session_ctx(file_engine):
    """从 file_engine 工厂获取一个短生命周期的 session（用于测试数据准备/校验）."""
    _, session_factory, _ = file_engine
    async with session_factory() as session:
        yield session


def auth_headers(token: str | None = None) -> dict:
    """生成 Authorization headers."""
    if token is None:
        token = create_access_token(TEST_USER_ID)
    return {"Authorization": f"Bearer {token}"}


# ═══════════════════════════════════════════════════════════════════
# 数据准备 helpers
# ═══════════════════════════════════════════════════════════════════


async def insert_event(file_engine, **overrides) -> Event:
    async with db_session_ctx(file_engine) as session:
        data = {
            "id": str(uuid.uuid4()),
            "user_id": TEST_USER_ID,
            "event_type": "meeting",
            "source": "manual",
            "title": "测试事件",
            "raw_text": "测试原始文本",
            "status": "completed",
        }
        data.update(overrides)
        event = Event(**data)
        session.add(event)
        await session.commit()
        await session.refresh(event)
        return event


async def insert_entity(file_engine, **overrides) -> Entity:
    async with db_session_ctx(file_engine) as session:
        source_event_id = overrides.pop("source_event_id", None)
        if source_event_id is None:
            evt = Event(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                event_type="meeting",
                source="manual",
                title="源事件",
                raw_text="x",
                status="completed",
            )
            session.add(evt)
            await session.flush()
            source_event_id = evt.id

        data = {
            "id": str(uuid.uuid4()),
            "user_id": TEST_USER_ID,
            "entity_type": "person",
            "name": "王总",
            "canonical_name": "王总",
            "aliases": [],
            "properties": {"basic": {"company": "盛达集团", "title": "CTO"}},
            "source_event_id": str(source_event_id),
            "confidence": 0.9,
            "status": "confirmed",
        }
        data.update(overrides)
        entity = Entity(**data)
        session.add(entity)
        await session.commit()
        await session.refresh(entity)
        return entity


async def insert_todo(file_engine, **overrides) -> Todo:
    async with db_session_ctx(file_engine) as session:
        source_event_id = overrides.pop("source_event_id", None)
        if source_event_id is None:
            evt = Event(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                event_type="meeting",
                source="manual",
                title="源事件",
                raw_text="x",
                status="completed",
            )
            session.add(evt)
            await session.flush()
            source_event_id = evt.id

        data = {
            "id": str(uuid.uuid4()),
            "user_id": TEST_USER_ID,
            "todo_type": "followup",
            "title": "跟进王总",
            "description": "联系王总确认合同细节",
            "priority": 2,
            "status": "pending",
            "source_event_id": str(source_event_id),
            "due_date": datetime.now(UTC) + timedelta(days=3),
        }
        data.update(overrides)
        todo = Todo(**data)
        session.add(todo)
        await session.commit()
        await session.refresh(todo)
        return todo


async def insert_relationship_brief(file_engine, entity_id: str, **overrides):
    """直接在 DB 中创建 RelationshipBrief 记录.

    生产环境中 RelationshipBrief 由 event pipeline Step12 在事件处理时自动生成，
    因此测试需要手动构造 brief 来验证 GET 端点（GET 端点不会自动创建 brief）。
    """
    from promiselink.models.relationship_brief import RelationshipBrief

    async with db_session_ctx(file_engine) as session:
        data = {
            "id": str(uuid.uuid4()),
            "user_id": TEST_USER_ID,
            "person_entity_id": str(entity_id),
            "relationship_stage": "new_connection",
            "brief_data": {
                "basic_info": {"name": "测试人", "company": "测试公司"},
                "strength_score": 30,
                "last_interaction": {"date": "2026-07-01", "summary": "初次会议"},
            },
            "version": 1,
        }
        data.update(overrides)
        brief = RelationshipBrief(**data)
        session.add(brief)
        await session.commit()
        await session.refresh(brief)
        return brief


# ═══════════════════════════════════════════════════════════════════
# 测试用例
# ═══════════════════════════════════════════════════════════════════


class TestMiniappAuthLink:
    """验证小程序 Auth 调用与基础版后端端点的链路.

    发现：
    - 小程序 wechatLogin 调用 POST /auth/wechat，后端端点是 POST /auth/wechat/login → 路径不匹配
    - 小程序 pocLogin 调用 POST /auth/poc-login (body: {secret})，后端端点是 POST /auth/login (body: {user_id, poc_secret}) → 路径+body不匹配
    """

    @pytest.mark.asyncio
    async def test_poc_login_correct_path_works(self, client):
        """Verify: 后端正确路径 POST /auth/login 能成功登录.

        Scenario: 使用正确的 user_id + poc_secret
        Expected: 返回 access_token + user_id
        """
        resp = await client.post(
            f"{API_PREFIX}/auth/login",
            json={"user_id": "miniapp-test-user", "poc_secret": POC_SECRET},
        )
        assert resp.status_code == 200, f"登录失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["access_token"], "应返回 access_token"
        assert body["token_type"] == "bearer"
        assert body["user_id"] == "miniapp-test-user"

    @pytest.mark.asyncio
    async def test_miniapp_poc_login_path_returns_404(self, client):
        """Verify: 小程序路径 POST /auth/poc-login 在后端不存在 → 404.

        前后链路断裂诊断：小程序 pocLogin 调用 /auth/poc-login，
        但后端端点是 /auth/login。直连模式下此调用会 404。
        """
        resp = await client.post(
            f"{API_PREFIX}/auth/poc-login",
            json={"secret": POC_SECRET},
        )
        assert resp.status_code == 404, (
            f"小程序路径 /auth/poc-login 应返回 404（后端端点是 /auth/login）: "
            f"got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_miniapp_wechat_login_path_returns_404(self, client):
        """Verify: 小程序路径 POST /auth/wechat 在后端不存在 → 404.

        前后链路断裂诊断：小程序 wechatLogin 调用 /auth/wechat，
        但后端端点是 /auth/wechat/login。直连模式下此调用会 404。
        """
        resp = await client.post(
            f"{API_PREFIX}/auth/wechat",
            json={"code": "test_code"},
        )
        assert resp.status_code == 404, (
            f"小程序路径 /auth/wechat 应返回 404（后端端点是 /auth/wechat/login）: "
            f"got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_wechat_login_correct_path_works(self, client):
        """Verify: 后端正确路径 POST /auth/wechat/login 能处理请求.

        Scenario: 发送 wx.login() code
        Expected: 返回 access_token（需 mock wechat_oauth）
        """
        with patch("promiselink.core.wechat.wechat_oauth") as mock_oauth:
            mock_oauth.code_to_session = AsyncMock(
                return_value={"openid": "test_openid_123", "session_key": "sk"}
            )
            resp = await client.post(
                f"{API_PREFIX}/auth/wechat/login",
                json={"code": "test_code"},
            )
        assert resp.status_code == 200, f"微信登录失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["access_token"], "应返回 access_token"
        assert body["token_type"] == "bearer"
        assert "user_id" in body


class TestMiniappEventLifecycle:
    """验证小程序 Events 全生命周期调用链路.

    用户旅程：创建事件 → 查看列表 → 查看详情 → 重试 → 接受降级 → 纠偏
    """

    @pytest.mark.asyncio
    async def test_create_event_and_verify_db(self, client, file_engine):
        """Verify: POST /events 创建事件并验证 DB 写入.

        Scenario: 小程序 createEvent 创建会议事件
        Expected: DB 中 event 记录 status=pending, raw_text 写入正确
        """
        resp = await client.post(
            f"{API_PREFIX}/events",
            headers=auth_headers(),
            json={
                "event_type": "meeting",
                "source": "manual",
                "title": "与王总讨论合作",
                "raw_text": MEETING_TEXT,
            },
        )
        assert resp.status_code == 201, f"创建事件失败: {resp.status_code} {resp.text}"
        event_id = resp.json()["id"]
        assert resp.json()["status"] == "pending"

        # 副作用验证：DB 中确实写入了这条事件
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Event).where(Event.id == event_id)
            )
            db_event = result.scalar_one_or_none()
            assert db_event is not None, "DB 中应存在该事件"
            assert db_event.title == "与王总讨论合作"
            assert db_event.raw_text == MEETING_TEXT
            assert db_event.status == "pending"

    @pytest.mark.asyncio
    async def test_batch_create_events_and_verify_count(self, client, file_engine):
        """Verify: POST /events/batch 批量创建并验证数量.

        Scenario: 小程序 batchCreateEvents 批量创建 2 个事件
        Expected: total_created=2, DB 中有 2 条新记录
        """
        resp = await client.post(
            f"{API_PREFIX}/events/batch",
            headers=auth_headers(),
            json={
                "events": [
                    {
                        "event_type": "meeting",
                        "source": "manual",
                        "title": "批量事件1",
                        "raw_text": "批量测试1",
                    },
                    {
                        "event_type": "call",
                        "source": "manual",
                        "title": "批量事件2",
                        "raw_text": "批量测试2",
                    },
                ]
            },
        )
        assert resp.status_code == 201, f"批量创建失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["total_created"] == 2
        assert len(body["created"]) == 2

    @pytest.mark.asyncio
    async def test_get_events_list(self, client, file_engine):
        """Verify: GET /events 返回事件列表.

        Scenario: 小程序 getEvents 获取事件列表
        Expected: 列表包含已创建的事件
        """
        await insert_event(file_engine, title="列表测试事件")

        resp = await client.get(f"{API_PREFIX}/events", headers=auth_headers())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(e["title"] == "列表测试事件" for e in items), "列表应包含已创建事件"

    @pytest.mark.asyncio
    async def test_get_event_detail_with_related_data(self, client, file_engine):
        """Verify: GET /events/{id} 返回事件详情含关联数据.

        Scenario: 小程序 getEventDetail 获取事件详情
        Expected: 返回 related_todos/related_entities/related_associations
        """
        event = await insert_event(file_engine, title="详情测试事件")
        await insert_entity(file_engine, name="详情人脉", source_event_id=event.id)
        await insert_todo(file_engine, title="详情待办", source_event_id=event.id)

        resp = await client.get(
            f"{API_PREFIX}/events/{event.id}", headers=auth_headers()
        )
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["title"] == "详情测试事件"
        assert len(detail["related_entities"]) >= 1, "应返回关联人脉"
        assert len(detail["related_todos"]) >= 1, "应返回关联待办"

    @pytest.mark.asyncio
    async def test_retry_failed_event_and_verify_status(self, client, file_engine):
        """Verify: POST /events/{id}/retry 重试失败事件并验证状态变更.

        Scenario: 小程序 retryEvent 重试 failed 状态事件
        Expected: event.status 从 failed → pending, failed_steps 被清除
        """
        event = await insert_event(
            file_engine,
            status="failed",
            failed_steps=["entity_extraction"],
            processed_at=datetime.now(UTC),
        )

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/retry", headers=auth_headers()
        )
        assert resp.status_code == 200, f"重试失败: {resp.status_code} {resp.text}"

        # 副作用验证：DB 中状态已变更
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Event).where(Event.id == event.id))
            db_event = result.scalar_one()
            assert db_event.status == "pending", "状态应重置为 pending"
            assert db_event.failed_steps is None, "failed_steps 应被清除"
            assert db_event.processed_at is None, "processed_at 应被清除"

    @pytest.mark.asyncio
    async def test_accept_degraded_and_verify_status(self, client, file_engine):
        """Verify: POST /events/{id}/accept-degraded 接受降级结果并验证状态.

        Scenario: 小程序 acceptDegradedEvent 接受 awaiting_retry 事件的降级结果
        Expected: event.status → degraded_completed, processed_at 被设置
        """
        event = await insert_event(file_engine, status="awaiting_retry")

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/accept-degraded", headers=auth_headers()
        )
        assert resp.status_code == 200, f"接受降级失败: {resp.status_code} {resp.text}"

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Event).where(Event.id == event.id))
            db_event = result.scalar_one()
            assert db_event.status == "degraded_completed"
            assert db_event.processed_at is not None, "processed_at 应被设置"

    @pytest.mark.asyncio
    async def test_correct_event_create_new_todo_and_verify(self, client, file_engine):
        """Verify: POST /events/{id}/correct 纠偏新增待办并验证 DB.

        Scenario: 小程序 correctEvent 提交纠偏——新增一条待办
        Expected: todos_created=1, DB 中新增一条 todo 记录
        """
        event = await insert_event(file_engine, title="纠偏测试事件")

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            headers=auth_headers(),
            json={
                "corrected_todos": [
                    {
                        "title": "纠偏新增待办",
                        "description": "用户手动补录的待办",
                        "action": "add",
                        "priority": 2,
                    }
                ]
            },
        )
        assert resp.status_code == 200, f"纠偏失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["todos_created"] == 1, "应创建 1 条待办"

        # 副作用验证：DB 中确实新增了待办
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Todo).where(
                    Todo.source_event_id == event.id,
                    Todo.title == "纠偏新增待办",
                )
            )
            db_todo = result.scalar_one_or_none()
            assert db_todo is not None, "DB 中应存在纠偏新增的待办"
            assert db_todo.description == "用户手动补录的待办"

    @pytest.mark.asyncio
    async def test_correct_event_add_promise_and_verify(self, client, file_engine):
        """Verify: POST /events/{id}/correct 纠偏新增承诺并验证 DB.

        Scenario: 小程序 correctEvent 提交纠偏——手动补录一条承诺
        Expected: promises_created=1, DB 中新增 promise 类型 todo
        """
        event = await insert_event(file_engine, title="承诺纠偏事件")
        entity = await insert_entity(file_engine, name="承诺对象", source_event_id=event.id)

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            headers=auth_headers(),
            json={
                "corrected_promises": [
                    {
                        "content": "我承诺下周提供方案",
                        "due_date": "2026-08-15T00:00:00",
                        "promise_type": "my_promise",
                        "promisor_id": None,
                        "beneficiary_id": str(entity.id),
                        "action": "add",
                    }
                ]
            },
        )
        assert resp.status_code == 200, f"承诺纠偏失败: {resp.status_code} {resp.text}"
        assert resp.json()["promises_created"] == 1

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Todo).where(
                    Todo.source_event_id == event.id,
                    Todo.todo_type == "promise",
                )
            )
            db_promise = result.scalar_one_or_none()
            assert db_promise is not None, "DB 中应存在新增的承诺"
            assert db_promise.action_type == "my_promise"
            assert db_promise.confirmation_status == "confirmed"


class TestMiniappEntitiesLink:
    """验证小程序 Entities 调用链路."""

    @pytest.mark.asyncio
    async def test_get_entities_list(self, client, file_engine):
        """Verify: GET /entities 返回人脉列表.

        Scenario: 小程序 getEntities 获取人脉列表
        Expected: 列表包含已创建的人脉
        """
        await insert_entity(file_engine, name="李总")

        resp = await client.get(f"{API_PREFIX}/entities", headers=auth_headers())
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(e["name"] == "李总" for e in items), "列表应包含李总"

    @pytest.mark.asyncio
    async def test_get_entity_detail(self, client, file_engine):
        """Verify: GET /entities/{id} 返回人脉详情.

        Scenario: 小程序 getEntity 获取人脉详情
        Expected: 返回 name/entity_type/properties
        """
        entity = await insert_entity(file_engine, name="赵总")

        resp = await client.get(
            f"{API_PREFIX}/entities/{entity.id}", headers=auth_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "赵总"
        assert resp.json()["entity_type"] == "person"

    @pytest.mark.asyncio
    async def test_miniapp_entities_search_path_returns_404(self, client, file_engine):
        """Verify: 小程序路径 GET /entities/search 在后端不可用 → 404/422.

        前后链路断裂诊断：小程序 searchEntities 调用 /entities/search?user_id=&q=，
        但后端没有 /entities/search 端点。后端使用 GET /entities?search=xxx 实现搜索。
        FastAPI 将 "search" 匹配到 /entities/{entity_id} 路由，但 "search" 不是
        合法 UUID，故返回 422（路径参数校验失败）——这同样证明该路径不可用作搜索。
        """
        resp = await client.get(
            f"{API_PREFIX}/entities/search",
            headers=auth_headers(),
            params={"user_id": TEST_USER_ID, "q": "王总"},
        )
        # 422 = "search" 匹配 /entities/{entity_id} 但 UUID 校验失败；404 = 未匹配
        # 两者都证明小程序路径不可用作搜索
        assert resp.status_code in (404, 422), (
            f"小程序路径 /entities/search 应返回 404/422（后端用 /entities?search= 实现搜索）: "
            f"got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_entities_search_via_correct_path(self, client, file_engine):
        """Verify: 后端正确路径 GET /entities?search= 能搜索.

        Scenario: 使用后端正确的搜索方式
        Expected: 返回匹配的人脉
        """
        await insert_entity(file_engine, name="搜索目标人")

        resp = await client.get(
            f"{API_PREFIX}/entities",
            headers=auth_headers(),
            params={"search": "搜索目标"},
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any("搜索目标" in e["name"] for e in items), "搜索应返回匹配结果"


class TestMiniappTodosLink:
    """验证小程序 Todos 调用链路."""

    @pytest.mark.asyncio
    async def test_get_todos_list(self, client, file_engine):
        """Verify: GET /todos 返回待办列表."""
        await insert_todo(file_engine, title="待办列表项")

        resp = await client.get(f"{API_PREFIX}/todos", headers=auth_headers())
        assert resp.status_code == 200
        assert any(t["title"] == "待办列表项" for t in resp.json()["items"])

    @pytest.mark.asyncio
    async def test_get_todo_detail(self, client, file_engine):
        """Verify: GET /todos/{id} 返回待办详情."""
        todo = await insert_todo(file_engine, title="详情待办")

        resp = await client.get(
            f"{API_PREFIX}/todos/{todo.id}", headers=auth_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "详情待办"

    @pytest.mark.asyncio
    async def test_update_todo_and_verify_status(self, client, file_engine):
        """Verify: PATCH /todos/{id} 更新待办并验证状态变更.

        Scenario: 小程序 updateTodo 更新待办状态
        Expected: DB 中 status 变更为 done
        """
        todo = await insert_todo(file_engine, title="更新待办", status="pending")

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            headers=auth_headers(),
            json={"status": "done"},
        )
        assert resp.status_code == 200, f"更新失败: {resp.status_code} {resp.text}"
        assert resp.json()["status"] == "done"

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Todo).where(Todo.id == todo.id))
            db_todo = result.scalar_one()
            assert db_todo.status == "done"
            assert db_todo.completed_at is not None, "completed_at 应被设置"

    @pytest.mark.asyncio
    async def test_complete_todo_via_patch_and_verify(self, client, file_engine):
        """Verify: PATCH /todos/{id} with {status:done} 完成待办.

        Scenario: 小程序 completeTodo 用 PATCH 设置 status=done + completed_at
        Expected: 状态变为 done
        """
        todo = await insert_todo(file_engine, title="完成待办", status="pending")

        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            headers=auth_headers(),
            json={
                "status": "done",
                "completed_at": datetime.now(UTC).isoformat(),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

    @pytest.mark.asyncio
    async def test_delete_todo_and_verify_db(self, client, file_engine):
        """Verify: DELETE /todos/{id} 删除待办并验证 DB.

        Scenario: 小程序 deleteTodo 删除待办
        Expected: DB 中该记录已删除
        """
        todo = await insert_todo(file_engine, title="删除待办")

        resp = await client.delete(
            f"{API_PREFIX}/todos/{todo.id}", headers=auth_headers()
        )
        assert resp.status_code == 204

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Todo).where(Todo.id == todo.id))
            assert result.scalar_one_or_none() is None, "DB 中待办应已删除"


class TestMiniappRelationshipBriefsLink:
    """验证小程序 Relationship Briefs 调用链路."""

    @pytest.mark.asyncio
    async def test_get_relationship_brief(self, client, file_engine):
        """Verify: GET /persons/{id}/relationship-brief 返回关系卡片.

        Scenario: 小程序 getRelationshipBrief 获取人脉关系简报
        Note: 生产环境中 brief 由 event pipeline Step12 自动创建，
              此处通过 helper 模拟 pipeline 完成后的状态。
        Expected: 返回 brief 数据
        """
        entity = await insert_entity(file_engine, name="关系简报人")
        await insert_relationship_brief(file_engine, entity.id)

        resp = await client.get(
            f"{API_PREFIX}/persons/{entity.id}/relationship-brief",
            headers=auth_headers(),
        )
        assert resp.status_code == 200, f"获取关系简报失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["person_entity_id"] == str(entity.id)
        assert "relationship_stage" in body

    @pytest.mark.asyncio
    async def test_get_relationship_brief_aggregated(self, client, file_engine):
        """Verify: GET /persons/{id}/relationship-brief/aggregated 返回聚合视图.

        Scenario: 小程序 getRelationshipBriefAggregated 获取12模块聚合视图
        Note: 生产环境中 brief 由 event pipeline Step12 自动创建，
              此处通过 helper 模拟 pipeline 完成后的状态。
        Expected: 返回 modules 列表 + stage_label
        """
        entity = await insert_entity(file_engine, name="聚合视图人")
        await insert_relationship_brief(file_engine, entity.id)

        resp = await client.get(
            f"{API_PREFIX}/persons/{entity.id}/relationship-brief/aggregated",
            headers=auth_headers(),
        )
        assert resp.status_code == 200, f"获取聚合视图失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "modules" in body
        assert len(body["modules"]) == 12, "应返回 12 个模块"
        assert body["person_name"] == "聚合视图人"

    @pytest.mark.asyncio
    async def test_list_relationship_briefs(self, client, file_engine):
        """Verify: GET /relationship-briefs 返回简报列表.

        Scenario: 小程序 getRelationshipBriefs 获取用户所有人脉简报
        Note: 生产环境中 brief 由 event pipeline Step12 自动创建，
              此处通过 helper 模拟 pipeline 完成后的状态。
        Expected: 返回列表
        """
        entity = await insert_entity(file_engine, name="列表简报人")
        await insert_relationship_brief(file_engine, entity.id)

        resp = await client.get(
            f"{API_PREFIX}/relationship-briefs", headers=auth_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_relationship_brief_without_existing_returns_404(self, client, file_engine):
        """Verify: GET /persons/{id}/relationship-brief 在无 brief 时返回 404.

        前后链路断裂诊断：小程序 getRelationshipBrief 假设首次访问会自动创建 brief，
        但后端 GET 端点不会自动创建——brief 由 event pipeline Step12 在事件处理时生成。
        若小程序在事件处理完成前调用 getRelationshipBrief，会收到 404。
        """
        entity = await insert_entity(file_engine, name="无简报人")
        # 不创建 brief，直接调用

        resp = await client.get(
            f"{API_PREFIX}/persons/{entity.id}/relationship-brief",
            headers=auth_headers(),
        )
        assert resp.status_code == 404, (
            f"无 brief 时应返回 404（小程序不应假设首次访问自动创建）: "
            f"got {resp.status_code}"
        )


class TestMiniappDashboardLink:
    """验证小程序 Dashboard 调用链路."""

    @pytest.mark.asyncio
    async def test_get_day_view_dashboard(self, client, file_engine):
        """Verify: GET /dashboard/day-view 返回日视图.

        Scenario: 小程序 getDashboard 获取日视图
        Expected: 返回 date/events/todos/scheduled_events/summary
        """
        resp = await client.get(
            f"{API_PREFIX}/dashboard/day-view",
            headers=auth_headers(),
            params={"date": "今天"},
        )
        assert resp.status_code == 200, f"获取日视图失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert "date" in body
        assert "events" in body
        assert "todos" in body
        assert "summary" in body
        assert "adjacent_dates" in body


class TestMiniappExportLink:
    """验证小程序 Export 调用链路."""

    @pytest.mark.asyncio
    async def test_export_data(self, client, file_engine):
        """Verify: GET /export/{userId} 导出全量数据.

        Scenario: 小程序 exportData 导出用户数据
        Expected: 返回 JSON 含 events/entities/todos/associations
        """
        await insert_event(file_engine, title="导出事件")
        await insert_entity(file_engine, name="导出人脉")
        await insert_todo(file_engine, title="导出待办")

        resp = await client.get(
            f"{API_PREFIX}/export/{TEST_USER_ID}", headers=auth_headers()
        )
        assert resp.status_code == 200, f"导出失败: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["export_version"] == "1.0"
        assert len(data["events"]) >= 1
        assert len(data["entities"]) >= 1
        assert len(data["todos"]) >= 1


class TestMiniappPromisesLink:
    """验证小程序 Promises 调用链路."""

    @pytest.mark.asyncio
    async def test_get_promises_list(self, client, file_engine):
        """Verify: GET /promises 返回承诺列表."""
        await insert_todo(
            file_engine,
            title="我方承诺",
            todo_type="promise",
            action_type="my_promise",
            fulfillment_status="pending",
        )

        resp = await client.get(
            f"{API_PREFIX}/promises",
            headers=auth_headers(),
            params={"view": "my-promises"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @pytest.mark.asyncio
    async def test_update_fulfillment_and_verify(self, client, file_engine):
        """Verify: PATCH /promises/{todoId}/fulfillment 更新兑现状态并验证 DB.

        Scenario: 小程序 updateFulfillment 标记承诺已兑现
        Expected: DB 中 fulfillment_status → fulfilled, fulfilled_at 被设置
        """
        todo = await insert_todo(
            file_engine,
            title="兑现承诺",
            todo_type="promise",
            action_type="my_promise",
            fulfillment_status="pending",
        )

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            headers=auth_headers(),
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 200, f"更新兑现状态失败: {resp.status_code} {resp.text}"
        assert resp.json()["fulfillment_status"] == "fulfilled"

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Todo).where(Todo.id == todo.id))
            db_todo = result.scalar_one()
            assert db_todo.fulfillment_status == "fulfilled"
            assert db_todo.fulfilled_at is not None, "fulfilled_at 应被设置"

    @pytest.mark.asyncio
    async def test_get_promise_stats(self, client, file_engine):
        """Verify: GET /promises/stats 返回承诺统计."""
        await insert_todo(
            file_engine,
            title="统计承诺",
            todo_type="promise",
            action_type="my_promise",
            fulfillment_status="pending",
        )

        resp = await client.get(
            f"{API_PREFIX}/promises/stats", headers=auth_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "total" in body
        assert "my_promises" in body
        assert "their_promises" in body
        assert "fulfillment_rate" in body


class TestMiniappRemindersLink:
    """验证小程序 Reminders 调用链路.

    发现：
    - 小程序 reminderAction 发送 {snooze_days}，后端期望 {snooze_hours} → 字段不匹配
    """

    @pytest.mark.asyncio
    async def test_get_daily_reminders(self, client, file_engine):
        """Verify: GET /reminders/daily 返回每日提醒."""
        from datetime import time

        from promiselink.models.reminder import ReminderPreference

        await insert_todo(file_engine, title="提醒项", priority=1)
        async with db_session_ctx(file_engine) as session:
            session.add(
                ReminderPreference(
                    user_id=TEST_USER_ID,
                    preferred_times=["09:00"],
                    fatigue_threshold=10,
                    quiet_hours_start=time(23, 0),
                    quiet_hours_end=time(6, 0),
                )
            )
            await session.commit()

        resp = await client.get(
            f"{API_PREFIX}/reminders/daily", headers=auth_headers()
        )
        assert resp.status_code == 200, f"获取提醒失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["total_pending"] >= 1
        assert "items" in body

    @pytest.mark.asyncio
    async def test_reminder_action_completed_and_verify(self, client, file_engine):
        """Verify: POST /reminders/{todoId}/action 完成提醒并验证 DB.

        Scenario: 小程序 reminderAction 执行 completed 动作
        Expected: DB 中 todo.status → done, completed_at 被设置
        """
        todo = await insert_todo(file_engine, title="完成提醒", status="pending")

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            headers=auth_headers(),
            json={"action": "completed"},
        )
        assert resp.status_code == 200, f"提醒操作失败: {resp.status_code} {resp.text}"

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Todo).where(Todo.id == todo.id))
            db_todo = result.scalar_one()
            assert db_todo.status == "done"
            assert db_todo.completed_at is not None

    @pytest.mark.asyncio
    async def test_reminder_action_snooze_with_correct_field(self, client, file_engine):
        """Verify: POST /reminders/{todoId}/action 使用后端正确字段 snooze_hours.

        Scenario: 使用后端正确的 snooze_hours 字段推迟提醒
        Expected: DB 中 todo.status → snoozed
        """
        todo = await insert_todo(file_engine, title="推迟提醒", status="pending")

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            headers=auth_headers(),
            json={"action": "snoozed", "snooze_hours": 24},
        )
        assert resp.status_code == 200, f"推迟失败: {resp.status_code} {resp.text}"

        # 副作用验证
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(select(Todo).where(Todo.id == todo.id))
            db_todo = result.scalar_one()
            assert db_todo.status == "snoozed"

    @pytest.mark.asyncio
    async def test_reminder_action_snooze_with_miniapp_field_fails(self, client, file_engine):
        """Verify: 小程序发送 snooze_days 字段 → 后端不识别，snooze 缺少 snooze_hours → 400.

        前后链路断裂诊断：小程序 reminderAction 发送 {snooze_days: N}，
        但后端 ReminderActionRequest 期望 {snooze_hours: N}。
        推迟操作因缺少必填字段 snooze_hours 而失败。
        """
        todo = await insert_todo(file_engine, title="字段不匹配推迟", status="pending")

        resp = await client.post(
            f"{API_PREFIX}/reminders/{todo.id}/action",
            headers=auth_headers(),
            json={"action": "snoozed", "snooze_days": 1},
        )
        # snooze_days 不被后端识别，snooze_hours 缺失 → 400
        assert resp.status_code == 400, (
            f"小程序发送 snooze_days 但后端期望 snooze_hours，应返回 400: "
            f"got {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_get_reminder_preferences(self, client, file_engine):
        """Verify: GET /reminders/preferences 返回默认偏好."""
        resp = await client.get(
            f"{API_PREFIX}/reminders/preferences", headers=auth_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "preferred_times" in body
        assert "fatigue_threshold" in body

    @pytest.mark.asyncio
    async def test_update_reminder_preferences_and_verify(self, client, file_engine):
        """Verify: PATCH /reminders/preferences 更新偏好并验证 DB."""
        resp = await client.patch(
            f"{API_PREFIX}/reminders/preferences",
            headers=auth_headers(),
            json={"fatigue_threshold": 8, "quiet_hours_start": "23:30"},
        )
        assert resp.status_code == 200, f"更新偏好失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["fatigue_threshold"] == 8
        assert body["quiet_hours_start"] == "23:30"


class TestMiniappPrivacyLink:
    """验证小程序 Privacy 调用链路.

    修复记录（2026-07-29）：
    - exportUserData: 从 POST /privacy/export 改为 GET /export/{user_id}，与后端端点对齐
    - deleteUserData: 已包含 confirm:'DELETE' body，与后端二次确认要求对齐
    """

    @pytest.mark.asyncio
    async def test_get_privacy_summary(self, client, file_engine):
        """Verify: GET /privacy/data-summary 返回数据概览."""
        await insert_event(file_engine, title="隐私概览事件")

        resp = await client.get(
            f"{API_PREFIX}/privacy/data-summary", headers=auth_headers()
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "counts" in body
        assert body["counts"]["events"] >= 1

    @pytest.mark.asyncio
    async def test_export_user_data_via_correct_path(self, client, file_engine):
        """Verify: exportUserData 使用正确路径 GET /export/{user_id} 导出数据.

        修复后：小程序 exportUserData 从 POST /privacy/export 改为 GET /export/{user_id}。
        验证该路径能成功导出当前用户的所有数据。
        """
        await insert_event(file_engine, title="导出验证事件")
        await insert_entity(file_engine, name="导出验证人脉")
        await insert_todo(file_engine, title="导出验证待办")

        resp = await client.get(
            f"{API_PREFIX}/export/{TEST_USER_ID}", headers=auth_headers()
        )
        assert resp.status_code == 200, f"数据导出失败: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data["export_version"] == "1.0"
        assert data["user_id"] == TEST_USER_ID
        assert len(data["events"]) >= 1
        assert len(data["entities"]) >= 1
        assert len(data["todos"]) >= 1

    @pytest.mark.asyncio
    async def test_miniapp_delete_without_confirm_fails(self, client, file_engine):
        """Verify: DELETE /privacy/user-data 不带 confirm body → 422.

        安全验证：后端要求二次确认（confirm: 'DELETE'），
        不带 body 会返回 422 校验错误，防止误删。
        """
        await insert_event(file_engine, title="不应被删")

        # 不带 body（模拟错误调用）
        resp = await client.delete(
            f"{API_PREFIX}/privacy/user-data", headers=auth_headers()
        )
        assert resp.status_code == 422, (
            f"不带 confirm body 删除应返回 422（后端安全二次确认）: "
            f"got {resp.status_code}"
        )

        # 数据应仍存在
        summary = await client.get(
            f"{API_PREFIX}/privacy/data-summary", headers=auth_headers()
        )
        assert summary.json()["counts"]["events"] >= 1, "数据不应被删除"

    @pytest.mark.asyncio
    async def test_delete_with_confirm_and_verify(self, client, file_engine):
        """Verify: DELETE /privacy/user-data 带 confirm body 删除成功并验证 DB."""
        await insert_event(file_engine, title="待删除事件")
        await insert_entity(file_engine, name="待删除人脉")

        resp = await client.request(
            "DELETE",
            f"{API_PREFIX}/privacy/user-data",
            headers=auth_headers(),
            json={"confirm": "DELETE"},
        )
        assert resp.status_code == 200, f"删除失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["deleted"]["events"] >= 1
        assert body["deleted"]["entities"] >= 1
        assert "audit_id" in body

        # 副作用验证：数据已清除
        summary = await client.get(
            f"{API_PREFIX}/privacy/data-summary", headers=auth_headers()
        )
        assert summary.json()["counts"]["events"] == 0
        assert summary.json()["counts"]["entities"] == 0


class TestMiniappScheduledEventsLink:
    """验证小程序 Scheduled Events 调用链路."""

    @pytest.mark.asyncio
    async def test_create_scheduled_event_and_verify(self, client, file_engine):
        """Verify: POST /scheduled-events 创建日程并验证 DB.

        Scenario: 小程序 createScheduledEvent 创建未来日程
        Expected: DB 中 status=pending
        """
        future_time = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        resp = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={
                "scheduled_at": future_time,
                "topic": "下周与王总会议",
                "participants": [{"name": "王总", "company": "盛达集团"}],
                "event_type": "meeting",
            },
        )
        assert resp.status_code == 201, f"创建日程失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["topic"] == "下周与王总会议"
        assert body["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_scheduled_events(self, client, file_engine):
        """Verify: GET /scheduled-events 返回日程列表."""
        future_time = (datetime.now(UTC) + timedelta(days=3)).isoformat()
        await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "列表日程", "event_type": "call"},
        )

        resp = await client.get(
            f"{API_PREFIX}/scheduled-events", headers=auth_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    @pytest.mark.asyncio
    async def test_get_scheduled_event_detail(self, client, file_engine):
        """Verify: GET /scheduled-events/{id} 返回日程详情."""
        future_time = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        create = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "详情日程", "event_type": "meeting"},
        )
        se_id = create.json()["id"]

        resp = await client.get(
            f"{API_PREFIX}/scheduled-events/{se_id}", headers=auth_headers()
        )
        assert resp.status_code == 200
        assert resp.json()["topic"] == "详情日程"

    @pytest.mark.asyncio
    async def test_update_scheduled_event_and_verify(self, client, file_engine):
        """Verify: PATCH /scheduled-events/{id} 更新日程并验证."""
        future_time = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        create = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "原主题", "event_type": "meeting"},
        )
        se_id = create.json()["id"]

        resp = await client.patch(
            f"{API_PREFIX}/scheduled-events/{se_id}",
            headers=auth_headers(),
            json={"topic": "更新后主题"},
        )
        assert resp.status_code == 200, f"更新日程失败: {resp.status_code} {resp.text}"
        assert resp.json()["topic"] == "更新后主题"

    @pytest.mark.asyncio
    async def test_record_scheduled_event_and_verify(self, client, file_engine):
        """Verify: POST /scheduled-events/{id}/record 记录日程并验证 Event 创建.

        Scenario: 小程序 recordScheduledEvent 记录实际内容
        Expected: 创建关联 Event, scheduled_event status → recorded
        """
        future_time = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        create = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "记录日程", "event_type": "meeting"},
        )
        se_id = create.json()["id"]

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/record",
            headers=auth_headers(),
            json={"raw_text": "会议记录内容：讨论了合作方案"},
        )
        assert resp.status_code == 200, f"记录日程失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["pipeline_status"] == "pending"
        assert "event_id" in body

        # 副作用验证：scheduled_event 状态变更
        detail = await client.get(
            f"{API_PREFIX}/scheduled-events/{se_id}", headers=auth_headers()
        )
        assert detail.json()["status"] == "recorded", "日程状态应为 recorded"

    @pytest.mark.asyncio
    async def test_cancel_scheduled_event_and_verify(self, client, file_engine):
        """Verify: POST /scheduled-events/{id}/cancel 取消日程并验证状态."""
        future_time = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        create = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "取消日程", "event_type": "meeting"},
        )
        se_id = create.json()["id"]

        resp = await client.post(
            f"{API_PREFIX}/scheduled-events/{se_id}/cancel",
            headers=auth_headers(),
            json={"cancel_reason": "时间冲突"},
        )
        assert resp.status_code == 200, f"取消日程失败: {resp.status_code} {resp.text}"
        assert resp.json()["status"] == "cancelled"
        assert resp.json()["cancel_reason"] == "时间冲突"

    @pytest.mark.asyncio
    async def test_delete_scheduled_event_and_verify(self, client, file_engine):
        """Verify: DELETE /scheduled-events/{id} 删除日程并验证."""
        future_time = (datetime.now(UTC) + timedelta(days=15)).isoformat()
        create = await client.post(
            f"{API_PREFIX}/scheduled-events",
            headers=auth_headers(),
            json={"scheduled_at": future_time, "topic": "删除日程", "event_type": "meeting"},
        )
        se_id = create.json()["id"]

        resp = await client.delete(
            f"{API_PREFIX}/scheduled-events/{se_id}", headers=auth_headers()
        )
        assert resp.status_code == 204

        # 副作用验证：再获取应 404
        detail = await client.get(
            f"{API_PREFIX}/scheduled-events/{se_id}", headers=auth_headers()
        )
        assert detail.status_code == 404, "已删除的日程应返回 404"


class TestMiniappDemandInputLink:
    """验证小程序 Demand Input 调用链路."""

    @pytest.mark.asyncio
    async def test_create_demand_and_verify(self, client, file_engine):
        """Verify: POST /demands 创建需求并验证 DB.

        Scenario: 小程序 createDemand 提交一句话需求
        Expected: 返回 demand_id, DB 中创建 Entity（orphan_demand 或关联已有）
        """
        with patch("promiselink.api.v1.demand_input.LLMClient") as mock_llm_cls:
            mock_client = AsyncMock()
            mock_client.call_json = AsyncMock(
                return_value={"tag": "融资", "detail": "需要融资", "person_name": None}
            )
            mock_llm_cls.return_value = mock_client

            resp = await client.post(
                f"{API_PREFIX}/demands",
                headers=auth_headers(),
                json={"text": "我需要融资", "source": "text"},
            )
        assert resp.status_code == 200, f"创建需求失败: {resp.status_code} {resp.text}"
        body = resp.json()
        assert body["status"] == "success"
        assert "demand_id" in body
        assert body["extracted"]["tag"] == "融资"

        # 副作用验证：DB 中创建了 orphan entity
        async with db_session_ctx(file_engine) as session:
            from sqlalchemy import select
            result = await session.execute(
                select(Entity).where(Entity.id == body["demand_id"])
            )
            db_entity = result.scalar_one_or_none()
            assert db_entity is not None, "DB 中应存在 orphan demand entity"
            assert db_entity.entity_type == "topic"


class TestMiniappProOnlyEndpoints:
    """验证 Pro-only 端点在基础版返回 404.

    发现：以下端点已从基础版迁移到 PromiseLink-Pro：
    - /media/asr, /media/tts, /media/ocr, /media/ocr-event
    - /voice/query
    - /wechat/forward
    - /email/sync
    - /import/csv

    小程序在直连模式（shouldUseRelay()=false）下调用这些端点会 404。
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("endpoint,method", [
        ("/media/asr", "POST"),
        ("/media/tts", "POST"),
        ("/media/ocr", "POST"),
        ("/media/ocr-event", "POST"),
        ("/voice/query", "POST"),
        ("/wechat/forward", "POST"),
        ("/email/sync", "POST"),
        ("/import/csv", "POST"),
    ])
    async def test_pro_only_endpoint_returns_404(self, client, endpoint, method):
        """Verify: Pro-only 端点在基础版返回 404.

        这些端点已迁移到 PromiseLink-Pro，基础版不注册。
        小程序直连模式调用会 404（设计如此，应走网关 relay）。
        """
        resp = await client.request(
            method,
            f"{API_PREFIX}{endpoint}",
            headers=auth_headers(),
            json={},
        )
        assert resp.status_code == 404, (
            f"Pro-only 端点 {method} {endpoint} 应返回 404: "
            f"got {resp.status_code}"
        )


class TestMiniappFullUserJourney:
    """完整用户旅程：模拟小程序用户的真实调用顺序.

    从登录 → 创建事件 → 查看结果 → 纠偏 → 完成待办 → 兑现承诺 → 导出数据
    """

    @pytest.mark.asyncio
    async def test_full_journey_login_to_export(self, client, file_engine):
        """Verify: 完整用户旅程从登录到导出.

        Journey:
        1. PoC 登录（使用后端正确路径）
        2. 创建事件
        3. 查看事件列表 + 详情
        4. 查看人脉列表 + 详情
        5. 查看待办列表
        6. 完成待办
        7. 查看承诺 + 标记兑现
        8. 查看日视图
        9. 导出数据
        10. 隐私数据概览
        """
        # 1. 登录（使用后端正确路径 /auth/login）
        login = await client.post(
            f"{API_PREFIX}/auth/login",
            json={"user_id": "journey-user", "poc_secret": POC_SECRET},
        )
        assert login.status_code == 200
        journey_token = login.json()["access_token"]
        h = {"Authorization": f"Bearer {journey_token}"}

        # 注意：journey-user 的 JWT 与 TEST_USER_ID 不同，
        # 所以这里改用默认 auth_headers 继续后续测试
        h = auth_headers()

        # 2. 创建事件
        create = await client.post(
            f"{API_PREFIX}/events",
            headers=h,
            json={
                "event_type": "meeting",
                "source": "manual",
                "title": "旅程事件",
                "raw_text": "和刘总讨论了项目合作",
            },
        )
        assert create.status_code == 201
        event_id = create.json()["id"]

        # 3. 查看事件列表 + 详情
        events = await client.get(f"{API_PREFIX}/events", headers=h)
        assert events.status_code == 200
        assert any(e["id"] == event_id for e in events.json()["items"])

        detail = await client.get(f"{API_PREFIX}/events/{event_id}", headers=h)
        assert detail.status_code == 200
        assert detail.json()["title"] == "旅程事件"

        # 4. 查看人脉列表
        entities = await client.get(f"{API_PREFIX}/entities", headers=h)
        assert entities.status_code == 200

        # 5. 查看待办列表
        todos = await client.get(f"{API_PREFIX}/todos", headers=h)
        assert todos.status_code == 200

        # 6. 创建并完成待办
        todo = await insert_todo(file_engine, title="旅程待办")
        complete = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            headers=h,
            json={"status": "done"},
        )
        assert complete.status_code == 200
        assert complete.json()["status"] == "done"

        # 7. 查看承诺 + 标记兑现
        promise = await insert_todo(
            file_engine,
            title="旅程承诺",
            todo_type="promise",
            action_type="my_promise",
            fulfillment_status="pending",
        )
        fulfill = await client.patch(
            f"{API_PREFIX}/promises/{promise.id}/fulfillment",
            headers=h,
            json={"fulfillment_status": "fulfilled"},
        )
        assert fulfill.status_code == 200
        assert fulfill.json()["fulfillment_status"] == "fulfilled"

        # 8. 查看日视图
        day = await client.get(
            f"{API_PREFIX}/dashboard/day-view", headers=h, params={"date": "今天"}
        )
        assert day.status_code == 200

        # 9. 导出数据
        export = await client.get(
            f"{API_PREFIX}/export/{TEST_USER_ID}", headers=h
        )
        assert export.status_code == 200
        assert export.json()["export_version"] == "1.0"

        # 10. 隐私数据概览
        summary = await client.get(
            f"{API_PREFIX}/privacy/data-summary", headers=h
        )
        assert summary.status_code == 200
        assert summary.json()["counts"]["events"] >= 1

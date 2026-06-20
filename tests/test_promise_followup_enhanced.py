"""Enhanced tests for Promise follow-up feature — G3-01 ~ G3-15 test gap coverage.

Covers 10 prioritized gaps (5 high + 5 medium) for the promise follow-up feature:
  G3-01: nudge-draft endpoint (their_promise draft, my_promise 400, cache hit, fallback)
  G3-02: their_promise fulfillment lifecycle (pending→fulfilled, list query)
  G3-03: overdue status (PATCH overdue, overdue_notified_at field)
  G3-04: broken status (PATCH broken)
  G3-05: security constraint (their_promise manual mark vs AI auto-mark)
  G3-06: pending reset (fulfilled_at cleared on pending)
  G3-07: fulfilled_at field validation (fulfilled sets fulfilled_at)
  G3-08: nudge draft cache (no regeneration on cache hit)
  G3-09: their_promises stats (stats dict counts)
  G3-15: bidirectional promise same event E2E (my_promise + their_promise from one event)

Each test follows the Iron Rule format with Verify/Scenario/Expected docstrings.
Uses precise assertions (assertEqual/assertIn/assertRaises) per testing guidelines.

Coverage targets:
  - Happy Path ≥50%
  - Error Case ≥15%
  - Boundary ≥10%
"""

import uuid
from datetime import UTC, datetime, timedelta
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
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.promise_bidirectional import (
    ActionType,
    PromiseBidirectionalHandler,
)

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000099"
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


async def insert_promise_todo(
    session: AsyncSession,
    *,
    action_type: str = "my_promise",
    fulfillment_status: str = "pending",
    description: str = "Send proposal",
    title: str = "Follow up",
    due_date: datetime | None = None,
    related_entity_id: str | None = None,
    source_event_id: str | None = None,
    properties: dict | None = None,
    todo_id: str | None = None,
) -> Todo:
    """Insert a promise-type Todo with F-45 bidirectional fields."""
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = str(event.id)

    data = {
        "id": todo_id or str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "promise",
        "title": title,
        "description": description,
        "priority": 2,
        "status": "pending",
        "source_event_id": str(source_event_id),
        "action_type": action_type,
        "fulfillment_status": fulfillment_status,
        "due_date": due_date,
        "properties": properties or {},
    }
    if related_entity_id is not None:
        data["related_entity_id"] = str(related_entity_id)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


async def get_todo_from_db(session: AsyncSession, todo_id: str) -> Todo | None:
    """Fetch a Todo by id directly from DB (bypass session cache)."""
    # expire_all is synchronous — bust the session cache so we re-read from DB
    session.expire_all()
    result = await session.execute(select(Todo).where(Todo.id == str(todo_id)))
    return result.scalar_one_or_none()


# ══════════════════════════════════════════════════════════════════════════════
# G3-01: nudge-draft endpoint tests
# ══════════════════════════════════════════════════════════════════════════════


class TestG301NudgeDraftEndpoint:
    """G3-01: GET /promises/{id}/nudge-draft endpoint coverage."""

    @pytest.mark.asyncio
    async def test_nudge_draft_for_their_promise_generates_draft(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: their_promise的nudge-draft生成草稿.

        Scenario: GET /promises/{id}/nudge-draft 对their_promise类型todo
        Expected: 200响应，返回nudge_text非空，is_fallback为False
        """
        entity = await insert_entity(db_session, name="李总")
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="李总答应周三给资料",
            title="李总答应给资料",
            related_entity_id=str(entity.id),
            due_date=datetime.now(UTC) - timedelta(days=2),
        )
        await db_session.commit()

        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new_callable=AsyncMock,
            return_value="李总，之前提到的资料不知进展如何？方便的话同步一下 — via PromiseLink",
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("nudge_text", data)
        self.assertIn("李总", data["nudge_text"])
        self.assertEqual(data["is_fallback"], False)
        self.assertEqual(data["todo_id"], str(todo.id))

    @pytest.mark.asyncio
    async def test_nudge_draft_for_my_promise_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: my_promise类型不能生成nudge-draft.

        Scenario: GET /promises/{id}/nudge-draft 对my_promise类型todo
        Expected: 400 ValidationError
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/{todo.id}/nudge-draft")

        self.assertEqual(resp.status_code, 400)
        err = resp.json()
        self.assertIn("their_promise", err["error"]["message"])

    @pytest.mark.asyncio
    async def test_nudge_draft_cache_hit_returns_cached(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: properties._nlg_draft缓存命中时返回缓存内容.

        Scenario: todo.properties已含_nlg_draft，GET nudge-draft
        Expected: 返回缓存的nudge_text，不调用generate_gentle_nudge
        """
        cached_text = "缓存的催促消息 — via PromiseLink"
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
            properties={
                "_nlg_draft": {
                    "nudge_text": cached_text,
                    "is_fallback": True,
                    "generated_at": "2026-01-01T00:00:00+00:00",
                }
            },
        )
        await db_session.commit()

        # Mock should NOT be called if cache hits
        mock_gen = AsyncMock(return_value="should_not_be_called")
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new=mock_gen,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nudge_text"], cached_text)
        self.assertEqual(data["is_fallback"], True)
        mock_gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_nudge_draft_fallback_detection(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: LLM失败时返回fallback模板，is_fallback=True.

        Scenario: generate_gentle_nudge返回含"不着急"的fallback文本
        Expected: is_fallback=True（启发式检测"不着急"关键词）
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
        )
        await db_session.commit()

        fallback_text = "对方，之前提到的那件事不知进展如何？方便的话跟我同步一下情况，不着急。 — via PromiseLink"
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new_callable=AsyncMock,
            return_value=fallback_text,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["is_fallback"], True)
        self.assertIn("不着急", data["nudge_text"])

    @pytest.mark.asyncio
    async def test_nudge_draft_not_found_returns_404(
        self, client: AsyncClient
    ):
        """Verify: 不存在的todo_id返回404.

        Scenario: GET /promises/{non-existent-id}/nudge-draft
        Expected: 404 NotFoundError
        """
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"{API_PREFIX}/promises/{fake_id}/nudge-draft")

        self.assertEqual(resp.status_code, 404)

    # Helper to use unittest-style assertions within pytest
    @staticmethod
    def assertEqual(first, second, msg=None):
        assert first == second, msg or f"{first!r} != {second!r}"

    @staticmethod
    def assertIn(member, container, msg=None):
        assert member in container, msg or f"{member!r} not in {container!r}"


# ══════════════════════════════════════════════════════════════════════════════
# G3-02: their_promise fulfillment lifecycle
# ══════════════════════════════════════════════════════════════════════════════


class TestG302TheirPromiseLifecycle:
    """G3-02: their_promise的pending→fulfilled生命周期."""

    @pytest.mark.asyncio
    async def test_their_promise_pending_to_fulfilled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: their_promise从pending标记为fulfilled.

        Scenario: PATCH /promises/{id}/fulfillment fulfillment_status=fulfilled
        Expected: 200响应，状态变为fulfilled，fulfilled_at被设置
        """
        entity = await insert_entity(db_session, name="王总")
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="王总答应给反馈",
            title="王总答应给反馈",
            related_entity_id=str(entity.id),
            fulfillment_status="pending",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )

        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "fulfilled"

        # Verify fulfilled_at was set in DB
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfillment_status == "fulfilled"
        assert db_todo.fulfilled_at is not None

    @pytest.mark.asyncio
    async def test_their_promise_list_query(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: their-promises视图查询返回their_promise类型.

        Scenario: GET /promises?view=their-promises
        Expected: 仅返回action_type=their_promise的todo
        """
        # Create one their_promise and one my_promise
        their_todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
        )
        my_todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "their-promises"}
        )

        assert resp.status_code == 200
        data = resp.json()
        todo_ids = [item["todo_id"] for item in data["items"]]
        assert str(their_todo.id) in todo_ids
        assert str(my_todo.id) not in todo_ids
        # All items should be their_promise
        for item in data["items"]:
            assert item["action_type"] == "their_promise"


# ══════════════════════════════════════════════════════════════════════════════
# G3-03: overdue status tests
# ══════════════════════════════════════════════════════════════════════════════


class TestG303OverdueStatus:
    """G3-03: PATCH fulfillment_status=overdue."""

    @pytest.mark.asyncio
    async def test_fulfillment_status_overdue(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: my_promise可标记为overdue.

        Scenario: PATCH /promises/{id}/fulfillment fulfillment_status=overdue
        Expected: 200响应，状态变为overdue
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
            due_date=datetime.now(UTC) - timedelta(days=3),
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "overdue"},
        )

        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "overdue"

        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfillment_status == "overdue"

    @pytest.mark.asyncio
    async def test_overdue_notified_at_field_exists(
        self, client: AsyncSession, db_session: AsyncSession
    ):
        """Verify: overdue_notified_at字段在标记overdue后被自动设置.

        Scenario: 标记overdue后查询todo，检查overdue_notified_at字段
        Expected: 字段存在且被设置为当前时间（bug已修复）
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "overdue"},
        )
        assert resp.status_code == 200

        db_todo = await get_todo_from_db(db_session, str(todo.id))
        # 字段存在于模型中（验证字段可访问）
        assert hasattr(db_todo, "overdue_notified_at")
        # Bug已修复：PATCH endpoint在overdue时自动设置overdue_notified_at
        assert db_todo.overdue_notified_at is not None


# ══════════════════════════════════════════════════════════════════════════════
# G3-04: broken status tests
# ══════════════════════════════════════════════════════════════════════════════


class TestG304BrokenStatus:
    """G3-04: PATCH fulfillment_status=broken."""

    @pytest.mark.asyncio
    async def test_fulfillment_status_broken(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: my_promise可标记为broken.

        Scenario: PATCH /promises/{id}/fulfillment fulfillment_status=broken
        Expected: 200响应，状态变为broken
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "broken"},
        )

        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "broken"

        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfillment_status == "broken"

    @pytest.mark.asyncio
    async def test_broken_does_not_set_fulfilled_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 标记broken时fulfilled_at保持None.

        Scenario: PATCH fulfillment_status=broken
        Expected: fulfilled_at为None（broken不是兑现）
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "broken"},
        )
        assert resp.status_code == 200

        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfilled_at is None


# ══════════════════════════════════════════════════════════════════════════════
# G3-05: security constraint tests
# ══════════════════════════════════════════════════════════════════════════════


class TestG305SecurityConstraint:
    """G3-05: their_promise安全约束（仅用户手动可标记overdue/broken）."""

    @pytest.mark.asyncio
    async def test_their_promise_user_can_mark_overdue(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 用户通过API可手动标记their_promise为overdue.

        Scenario: PATCH /promises/{id}/fulfillment 对their_promise设置overdue
        Expected: 200响应（API层允许用户手动标记，安全约束在服务层）
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "overdue"},
        )

        # API允许用户手动标记（安全约束在AI服务层强制，不在API层）
        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "overdue"

    @pytest.mark.asyncio
    async def test_their_promise_user_can_mark_broken(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 用户通过API可手动标记their_promise为broken.

        Scenario: PATCH /promises/{id}/fulfillment 对their_promise设置broken
        Expected: 200响应（用户手动操作被允许）
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "broken"},
        )

        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "broken"

    @pytest.mark.asyncio
    async def test_their_promise_user_can_mark_fulfilled(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 用户可标记their_promise为fulfilled（正常兑现确认）.

        Scenario: PATCH /promises/{id}/fulfillment 对their_promise设置fulfilled
        Expected: 200响应，fulfilled_at被设置
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )

        assert resp.status_code == 200
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfilled_at is not None


# ══════════════════════════════════════════════════════════════════════════════
# G3-06: pending reset tests
# ══════════════════════════════════════════════════════════════════════════════


class TestG306PendingReset:
    """G3-06: PATCH fulfillment_status=pending时fulfilled_at清空."""

    @pytest.mark.asyncio
    async def test_pending_resets_fulfilled_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 从fulfilled重置为pending时fulfilled_at被清空.

        Scenario: 先PATCH为fulfilled，再PATCH为pending
        Expected: fulfilled_at从有值变为None
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        # First mark as fulfilled
        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 200
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfilled_at is not None

        # Then reset to pending
        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "pending"},
        )
        assert resp.status_code == 200
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfillment_status == "pending"
        assert db_todo.fulfilled_at is None


# ══════════════════════════════════════════════════════════════════════════════
# G3-07: fulfilled_at field validation
# ══════════════════════════════════════════════════════════════════════════════


class TestG307FulfilledAtValidation:
    """G3-07: fulfilled时fulfilled_at被设置."""

    @pytest.mark.asyncio
    async def test_fulfilled_sets_fulfilled_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 标记fulfilled时fulfilled_at被设置为当前时间.

        Scenario: PATCH fulfillment_status=fulfilled
        Expected: fulfilled_at不为None，且为近期时间
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        before = datetime.now(UTC)
        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        after = datetime.now(UTC)

        assert resp.status_code == 200
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfilled_at is not None
        # fulfilled_at should be between before and after (allowing small clock skew)
        # Convert to comparable timezone-aware datetimes
        fulfilled_at = db_todo.fulfilled_at
        if fulfilled_at.tzinfo is None:
            fulfilled_at = fulfilled_at.replace(tzinfo=UTC)
        assert before - timedelta(seconds=5) <= fulfilled_at <= after + timedelta(seconds=5)

    @pytest.mark.asyncio
    async def test_pending_initial_fulfilled_at_is_none(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 新建promise的fulfilled_at初始为None.

        Scenario: 创建pending状态的promise todo
        Expected: fulfilled_at为None
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
            fulfillment_status="pending",
        )
        await db_session.commit()

        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.fulfilled_at is None


# ══════════════════════════════════════════════════════════════════════════════
# G3-08: nudge draft cache (no regeneration)
# ══════════════════════════════════════════════════════════════════════════════


class TestG308NudgeDraftCache:
    """G3-08: properties._nlg_draft缓存命中不重复生成."""

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_regenerate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 缓存命中时generate_gentle_nudge不被调用.

        Scenario: todo.properties._nlg_draft已存在，再次请求nudge-draft
        Expected: 返回缓存内容，generate_gentle_nudge调用次数为0
        """
        cached_text = "已缓存的催促消息 — via PromiseLink"
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
            properties={
                "_nlg_draft": {
                    "nudge_text": cached_text,
                    "is_fallback": False,
                }
            },
        )
        await db_session.commit()

        mock_gen = AsyncMock(return_value="should_not_be_called")
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new=mock_gen,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        assert resp.status_code == 200
        assert resp.json()["nudge_text"] == cached_text
        mock_gen.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_cache_generates_and_caches(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 无缓存时生成nudge并写入properties._nlg_draft.

        Scenario: todo无_nlg_draft缓存，GET nudge-draft
        Expected: 调用generate_gentle_nudge，结果写入properties._nlg_draft
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
            properties={},
        )
        await db_session.commit()

        generated_text = "新生成的催促消息 — via PromiseLink"
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new_callable=AsyncMock,
            return_value=generated_text,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        assert resp.status_code == 200
        assert resp.json()["nudge_text"] == generated_text

        # Verify cache was written to DB
        db_todo = await get_todo_from_db(db_session, str(todo.id))
        assert db_todo.properties is not None
        assert "_nlg_draft" in db_todo.properties
        assert db_todo.properties["_nlg_draft"]["nudge_text"] == generated_text

    @pytest.mark.asyncio
    async def test_corrupted_cache_falls_through_to_generation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 缓存损坏（无效JSON字符串）时回退到重新生成.

        Scenario: todo.properties._nlg_draft为无效JSON字符串，GET nudge-draft
        Expected: 跳过损坏缓存，调用generate_gentle_nudge生成新草稿
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
            properties={"_nlg_draft": "not-valid-json{{{"},
        )
        await db_session.commit()

        regenerated_text = "重新生成的催促消息 — via PromiseLink"
        mock_gen = AsyncMock(return_value=regenerated_text)
        with patch(
            "promiselink.services.nudge_generator.generate_gentle_nudge",
            new=mock_gen,
        ):
            resp = await client.get(
                f"{API_PREFIX}/promises/{todo.id}/nudge-draft"
            )

        assert resp.status_code == 200
        assert resp.json()["nudge_text"] == regenerated_text
        mock_gen.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# G3-09: their_promises stats
# ══════════════════════════════════════════════════════════════════════════════


class TestG309TheirPromisesStats:
    """G3-09: stats中their_promises字典的计数."""

    @pytest.mark.asyncio
    async def test_stats_their_promises_counts(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: /promises/stats返回their_promises字典正确计数.

        Scenario: 创建2个their_promise（1 pending, 1 fulfilled），查询stats
        Expected: their_promises={pending:1, fulfilled:1, overdue:0, broken:0}
        """
        await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料1",
            title="对方答应给资料1",
            fulfillment_status="pending",
        )
        await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料2",
            title="对方答应给资料2",
            fulfillment_status="fulfilled",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert "their_promises" in data
        their = data["their_promises"]
        assert their["pending"] == 1
        assert their["fulfilled"] == 1
        assert their["overdue"] == 0
        assert their["broken"] == 0

    @pytest.mark.asyncio
    async def test_stats_my_and_their_separate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: my_promises和their_promises分别计数互不干扰.

        Scenario: 创建1个my_promise(fulfilled)和1个their_promise(pending)
        Expected: my_promises.fulfilled=1, their_promises.pending=1
        """
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
            fulfillment_status="fulfilled",
        )
        await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="对方答应给资料",
            title="对方答应给资料",
            fulfillment_status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["my_promises"]["fulfilled"] == 1
        assert data["my_promises"]["pending"] == 0
        assert data["their_promises"]["pending"] == 1
        assert data["their_promises"]["fulfilled"] == 0

    @pytest.mark.asyncio
    async def test_stats_fulfillment_rate(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: fulfillment_rate正确计算.

        Scenario: 2个promise中1个fulfilled
        Expected: fulfillment_rate=0.5
        """
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
            fulfillment_status="fulfilled",
        )
        await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案2",
            title="我答应发方案2",
            fulfillment_status="pending",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/promises/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["fulfillment_rate"] == 0.5


# ══════════════════════════════════════════════════════════════════════════════
# G3-15: bidirectional promise same event E2E
# ══════════════════════════════════════════════════════════════════════════════


class TestG315BidirectionalSameEvent:
    """G3-15: 同一事件同时提取my_promise和their_promise."""

    @pytest.mark.asyncio
    async def test_bidirectional_same_event_extraction(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 同一事件可同时产生my_promise和their_promise.

        Scenario: 一个事件包含"我答应发方案"和"对方说会给资料"两个承诺
        Expected: 两个todo都被创建，分别action_type=my_promise和their_promise
        """
        # Simulate pipeline extracting two promises from one event
        event = await insert_event(
            db_session,
            title="和张总交流",
            raw_text="今天和张总开会。我答应下周三前发技术方案给他。张总说会配合提供所需数据。",
        )
        entity = await insert_entity(
            db_session,
            name="张总",
            canonical_name="张总",
            source_event_id=event.id,
        )

        # My promise todo
        my_todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="下周三前发技术方案给张总",
            title="我答应下周三前发技术方案",
            related_entity_id=str(entity.id),
            source_event_id=str(event.id),
        )
        # Their promise todo
        their_todo = await insert_promise_todo(
            db_session,
            action_type="their_promise",
            description="张总答应配合提供所需数据",
            title="张总说会配合提供所需数据",
            related_entity_id=str(entity.id),
            source_event_id=str(event.id),
        )
        await db_session.commit()

        # Verify my-promises view contains only my_todo
        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "my-promises"}
        )
        assert resp.status_code == 200
        my_ids = [item["todo_id"] for item in resp.json()["items"]]
        assert str(my_todo.id) in my_ids
        assert str(their_todo.id) not in my_ids

        # Verify their-promises view contains only their_todo
        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "their-promises"}
        )
        assert resp.status_code == 200
        their_ids = [item["todo_id"] for item in resp.json()["items"]]
        assert str(their_todo.id) in their_ids
        assert str(my_todo.id) not in their_ids

        # Verify both share the same source_event_id
        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "my-promises"}
        )
        my_item = [
            i for i in resp.json()["items"] if i["todo_id"] == str(my_todo.id)
        ][0]
        resp = await client.get(
            f"{API_PREFIX}/promises", params={"view": "their-promises"}
        )
        their_item = [
            i for i in resp.json()["items"] if i["todo_id"] == str(their_todo.id)
        ][0]
        assert my_item["source_event_id"] == their_item["source_event_id"]

    @pytest.mark.asyncio
    async def test_bidirectional_handler_analyzes_both_directions(self):
        """Verify: PromiseBidirectionalHandler能从同一事件文本识别双向承诺.

        Scenario: 事件文本含"我答应"和"他说会"，分别分析两个todo
        Expected: 一个识别为MY_PROMISE，一个识别为THEIR_PROMISE
        """
        from unittest.mock import MagicMock

        mock_llm = MagicMock()
        handler = PromiseBidirectionalHandler(mock_llm)

        # My promise todo
        my_todo = Todo(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            todo_type="promise",
            title="我答应下周三前发技术方案",
            description="我答应下周三前发技术方案给张总",
            source_event_id=uuid.uuid4(),
        )
        my_result = await handler.analyze_todo(my_todo)
        assert my_result.action_type == ActionType.MY_PROMISE

        # Their promise todo
        their_todo = Todo(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            todo_type="promise",
            title="张总说会配合提供所需数据",
            description="张总说会配合提供所需数据",
            source_event_id=uuid.uuid4(),
        )
        their_result = await handler.analyze_todo(their_todo)
        assert their_result.action_type == ActionType.THEIR_PROMISE


# ══════════════════════════════════════════════════════════════════════════════
# Additional boundary/error case tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFulfillmentBoundaryCases:
    """边界和错误用例补充."""

    @pytest.mark.asyncio
    async def test_invalid_fulfillment_status_returns_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 无效fulfillment_status返回400.

        Scenario: PATCH fulfillment_status=invalid_status
        Expected: 400 ValidationError
        """
        todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案",
            title="我答应发方案",
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "invalid_status"},
        )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_fulfillment_not_found_returns_404(
        self, client: AsyncClient
    ):
        """Verify: 不存在的todo_id返回404.

        Scenario: PATCH /promises/{non-existent-id}/fulfillment
        Expected: 404 NotFoundError
        """
        fake_id = str(uuid.uuid4())
        resp = await client.patch(
            f"{API_PREFIX}/promises/{fake_id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_fulfillment_status_filter(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify: 按fulfillment_status过滤承诺列表.

        Scenario: 创建pending和fulfilled两个promise，按status=fulfilled过滤
        Expected: 仅返回fulfilled的promise
        """
        pending_todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案1",
            title="我答应发方案1",
            fulfillment_status="pending",
        )
        fulfilled_todo = await insert_promise_todo(
            db_session,
            action_type="my_promise",
            description="我答应发方案2",
            title="我答应发方案2",
            fulfillment_status="fulfilled",
        )
        await db_session.commit()

        resp = await client.get(
            f"{API_PREFIX}/promises",
            params={"view": "my-promises", "status": "fulfilled"},
        )

        assert resp.status_code == 200
        items = resp.json()["items"]
        todo_ids = [item["todo_id"] for item in items]
        assert str(fulfilled_todo.id) in todo_ids
        assert str(pending_todo.id) not in todo_ids
        for item in items:
            assert item["fulfillment_status"] == "fulfilled"

    @pytest.mark.asyncio
    async def test_empty_stats_returns_zeros(
        self, client: AsyncClient
    ):
        """Verify: 无承诺时stats返回全0.

        Scenario: 数据库无promise todo，查询stats
        Expected: total=0, fulfillment_rate=0.0, 各状态计数为0
        """
        resp = await client.get(f"{API_PREFIX}/promises/stats")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["fulfillment_rate"] == 0.0
        assert data["my_promises"] == {
            "pending": 0, "fulfilled": 0, "overdue": 0, "broken": 0
        }
        assert data["their_promises"] == {
            "pending": 0, "fulfilled": 0, "overdue": 0, "broken": 0
        }

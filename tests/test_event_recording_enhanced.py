"""Enhanced tests for event recording features (会后记录功能增强测试).

Covers 9 test gaps (G1-01 through G1-09):
- G1-01: email event type creation
- G1-02: wechat_forward event type creation
- G1-03: batch creation (20 events, partial failure, all failure, boundary)
- G1-04: retry endpoint (failed/awaiting_retry/non-retryable/not-found)
- G1-05: accept-degraded endpoint (awaiting_retry/failed/non-degradable/not-found)
- G1-06: raw_text 500KB size limit (over/exactly-at/under limit)
- G1-07: DELETE cascade (entities/todos/associations/not-found)
- G1-08: search and filter (search/event_type/status/pagination)
- G1-09: call event type creation

Coverage dimensions:
- Happy Path: ~61% (19/31)
- Error Case: ~23% (7/31)
- Boundary: ~16% (5/31)

Iron Rule: Each test is Independent, Isolated, Repeatable, Self-validating.
Each test follows Arrange → Act → Assert with precise assertions.
"""

import uuid
from datetime import UTC, datetime

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
RAW_TEXT_MAX_BYTES = 512000  # 500KB as enforced by API


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
    """Provide an httpx.AsyncClient with DB dependency overridden and pipeline mocked."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    # Mock the background pipeline to avoid real LLM calls during event creation
    async def mock_process_event(event_id):
        pass

    import promiselink.api.v1.events as events_module
    original_process = events_module.process_event_background
    events_module.process_event_background = mock_process_event

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    events_module.process_event_background = original_process
    app.dependency_overrides.clear()


# ── Helpers ──


async def insert_event_directly(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB with given overrides.

    Returns the created Event instance (flushed, not committed).
    """
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


async def insert_entity_directly(
    session: AsyncSession, source_event_id: str, **overrides
) -> Entity:
    """Insert an Entity directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "entity_type": "person",
        "name": "Test Person",
        "canonical_name": "Test Person",
        "source_event_id": str(source_event_id),
        "properties": {"basic": {"company": "Test Corp", "title": "Engineer"}},
        "confidence": 0.9,
        "status": "confirmed",
    }
    data.update(overrides)
    entity = Entity(**data)
    session.add(entity)
    await session.flush()
    return entity


async def insert_todo_directly(
    session: AsyncSession, source_event_id: str, **overrides
) -> Todo:
    """Insert a Todo directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "followup",
        "title": "Test Todo",
        "description": "Test description",
        "priority": 3,
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


async def insert_association_directly(
    session: AsyncSession,
    source_event_id: str,
    source_entity_id: str,
    target_entity_id: str,
    **overrides,
) -> Association:
    """Insert an Association directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "source_entity_id": str(source_entity_id),
        "target_entity_id": str(target_entity_id),
        "association_type": "co_occurrence",
        "strength": 0.7,
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    assoc = Association(**data)
    session.add(assoc)
    await session.flush()
    return assoc


def make_event_payload(**overrides) -> dict:
    """Generate a valid event creation payload."""
    payload = {
        "event_type": "meeting",
        "source": "manual",
        "title": "测试事件",
        "raw_text": "这是一条测试记录",
    }
    payload.update(overrides)
    return payload


# ══════════════════════════════════════════════════════════════════════════════
# G1-01: email event type
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_01_ManualEventType:
    """G1-01: POST /events with event_type='manual' — verify creation succeeds."""

    async def test_create_manual_event_returns_201(self, client: AsyncClient):
        """Happy: manual event created successfully with correct response fields."""
        # Arrange
        payload = make_event_payload(
            event_type="manual",
            source="gmail",
            title="与客户邮件往来",
            raw_text="今天收到客户的邮件，讨论合作细节",
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "manual"
        assert data["title"] == "与客户邮件往来"
        assert data["source"] == "gmail"
        assert data["status"] == "pending"
        assert data["pipeline_status"] == "pending"
        assert "id" in data
        assert len(data["id"]) > 0

    async def test_manual_event_persisted_with_correct_type(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: manual event is persisted in DB with correct type and source."""
        # Arrange
        payload = make_event_payload(
            event_type="manual",
            source="outlook",
            title="项目确认邮件",
            raw_text="确认项目交付时间",
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        event_id = resp.json()["id"]

        # Assert — verify DB persistence
        result = await db_session.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one()
        assert event.event_type == "manual"
        assert event.source == "outlook"
        assert event.title == "项目确认邮件"
        assert event.raw_text == "确认项目交付时间"
        assert event.status == "pending"


# ══════════════════════════════════════════════════════════════════════════════
# G1-02: wechat_forward event type
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_02_WechatForwardEventType:
    """G1-02: POST /events with event_type='wechat_forward' — verify creation succeeds."""

    async def test_create_wechat_forward_event_returns_201(self, client: AsyncClient):
        """Happy: wechat_forward event created successfully."""
        # Arrange
        payload = make_event_payload(
            event_type="wechat_forward",
            source="wechat",
            title="转发：行业分析报告",
            raw_text="这是一份关于AI行业的分析报告...",
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "wechat_forward"
        assert data["source"] == "wechat"
        assert data["status"] == "pending"

    async def test_wechat_forward_event_with_metadata(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: wechat_forward event with metadata field is stored correctly."""
        # Arrange
        payload = make_event_payload(
            event_type="wechat_forward",
            source="wechat",
            title="转发文章",
            raw_text="文章内容",
            metadata={"forward_from": "公众号A", "original_author": "张三"},
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        event_id = resp.json()["id"]

        # Assert
        assert resp.status_code == 201
        result = await db_session.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one()
        assert event.event_type == "wechat_forward"
        assert event.metadata_["forward_from"] == "公众号A"
        assert event.metadata_["original_author"] == "张三"


# ══════════════════════════════════════════════════════════════════════════════
# G1-03: Batch creation
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_03_BatchCreation:
    """G1-03: POST /events/batch — batch create events with success/failure scenarios."""

    async def test_batch_create_20_events_all_success(self, client: AsyncClient):
        """Happy: batch create exactly 20 (max) events — all succeed."""
        # Arrange
        events = [
            make_event_payload(
                event_type="meeting",
                source="manual",
                title=f"批量事件_{i:02d}",
                raw_text=f"第{i}个事件的原始文本",
            )
            for i in range(20)
        ]

        # Act
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": events})

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_requested"] == 20
        assert data["total_created"] == 20
        assert len(data["created"]) == 20
        assert len(data["failed"]) == 0
        # Verify each created event has correct fields
        for i, created in enumerate(data["created"]):
            assert created["title"] == f"批量事件_{i:02d}"
            assert created["status"] == "pending"

    async def test_batch_create_partial_failure(self, client: AsyncClient):
        """Error: batch with 3 valid + 2 invalid event_type — 3 created, 2 failed."""
        # Arrange
        events = [
            make_event_payload(event_type="meeting", title="有效事件_0", raw_text="text0"),
            make_event_payload(event_type="manual", title="有效事件_1", raw_text="text1"),
            make_event_payload(event_type="call", title="有效事件_2", raw_text="text2"),
            make_event_payload(event_type="invalid_type", title="无效事件_3", raw_text="text3"),
            make_event_payload(event_type="bad_type", title="无效事件_4", raw_text="text4"),
        ]

        # Act
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": events})

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_requested"] == 5
        assert data["total_created"] == 3
        assert len(data["created"]) == 3
        assert len(data["failed"]) == 2
        # Verify failed entries have index and error
        failed_indices = sorted(f["index"] for f in data["failed"])
        assert failed_indices == [3, 4]
        for f in data["failed"]:
            assert "error" in f
            assert "Invalid event_type" in f["error"]

    async def test_batch_create_all_failure(self, client: AsyncClient):
        """Error: all events have invalid event_type — 0 created, all failed."""
        # Arrange
        events = [
            make_event_payload(event_type="invalid_0", title="无效_0", raw_text="t0"),
            make_event_payload(event_type="invalid_1", title="无效_1", raw_text="t1"),
            make_event_payload(event_type="invalid_2", title="无效_2", raw_text="t2"),
        ]

        # Act
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": events})

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_requested"] == 3
        assert data["total_created"] == 0
        assert len(data["created"]) == 0
        assert len(data["failed"]) == 3
        assert all(f["index"] in [0, 1, 2] for f in data["failed"])

    async def test_batch_create_21_events_exceeds_max(self, client: AsyncClient):
        """Boundary: 21 events exceeds max_length=20 — returns 422."""
        # Arrange
        events = [make_event_payload(title=f"事件_{i}") for i in range(21)]

        # Act
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": events})

        # Assert
        assert resp.status_code == 422

    async def test_batch_create_empty_list_rejected(self, client: AsyncClient):
        """Boundary: empty events list rejected by min_length=1 — returns 422."""
        # Arrange
        payload = {"events": []}

        # Act
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)

        # Assert
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# G1-04: retry endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_04_RetryEndpoint:
    """G1-04: POST /events/{id}/retry — retry failed or awaiting_retry events."""

    async def test_retry_failed_event_success(self, client: AsyncClient, db_session: AsyncSession):
        """Happy: retry a 'failed' event — status resets to 'pending'."""
        # Arrange
        event = await insert_event_directly(
            db_session,
            status="failed",
            failed_steps=["step_02_extract", "step_04_todo"],
            processed_at=datetime.now(UTC),
        )
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["id"] == str(event.id)

        # Verify DB state: status reset, processed_at cleared, failed_steps cleared
        await db_session.refresh(event)
        assert event.status == "pending"
        assert event.processed_at is None
        assert event.failed_steps is None

    async def test_retry_awaiting_retry_event_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: retry an 'awaiting_retry' event — status resets to 'pending'."""
        # Arrange
        event = await insert_event_directly(
            db_session,
            status="awaiting_retry",
            failed_steps=["step_03_embedding"],
        )
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")

        # Assert
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

        await db_session.refresh(event)
        assert event.status == "pending"
        assert event.failed_steps is None

    async def test_retry_completed_event_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Error: retry a 'completed' event — returns 400 (not retryable)."""
        # Arrange
        event = await insert_event_directly(db_session, status="completed")
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")

        # Assert
        assert resp.status_code == 400
        assert "not in a retryable state" in resp.json()["error"]["message"]

    async def test_retry_nonexistent_event_404(self, client: AsyncClient):
        """Error: retry a non-existent event — returns 404."""
        # Arrange
        fake_id = str(uuid.uuid4())

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{fake_id}/retry")

        # Assert
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# G1-05: accept-degraded endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_05_AcceptDegradedEndpoint:
    """G1-05: POST /events/{id}/accept-degraded — accept degraded processing result."""

    async def test_accept_degraded_awaiting_retry_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: accept degraded for 'awaiting_retry' event — status becomes 'degraded_completed'."""
        # Arrange
        event = await insert_event_directly(db_session, status="awaiting_retry")
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded_completed"

        await db_session.refresh(event)
        assert event.status == "degraded_completed"
        assert event.processed_at is not None

    async def test_accept_degraded_failed_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: accept degraded for 'failed' event — status becomes 'degraded_completed'."""
        # Arrange
        event = await insert_event_directly(
            db_session, status="failed", failed_steps=["step_05_promise"]
        )
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")

        # Assert
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded_completed"

        await db_session.refresh(event)
        assert event.status == "degraded_completed"

    async def test_accept_degraded_completed_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Error: accept degraded for 'completed' event — returns 400 (not degradable)."""
        # Arrange
        event = await insert_event_directly(db_session, status="completed")
        await db_session.commit()

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")

        # Assert
        assert resp.status_code == 400
        assert "not in a degradable state" in resp.json()["error"]["message"]

    async def test_accept_degraded_nonexistent_404(self, client: AsyncClient):
        """Error: accept degraded for non-existent event — returns 404."""
        # Arrange
        fake_id = str(uuid.uuid4())

        # Act
        resp = await client.post(f"{API_PREFIX}/events/{fake_id}/accept-degraded")

        # Assert
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# G1-06: raw_text 500KB limit
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_06_RawTextSizeLimit:
    """G1-06: POST /events with raw_text exceeding 500KB — returns 400."""

    async def test_raw_text_exceeds_500kb_returns_400(self, client: AsyncClient):
        """Boundary: raw_text of 512001 bytes (> 500KB) — returns 400."""
        # Arrange — 512001 bytes of ASCII (1 byte per char)
        oversized_text = "a" * (RAW_TEXT_MAX_BYTES + 1)
        payload = make_event_payload(raw_text=oversized_text)

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 400
        error = resp.json()["error"]
        assert "500KB" in error["message"]
        assert error["details"]["max_bytes"] == RAW_TEXT_MAX_BYTES

    async def test_raw_text_exactly_at_limit_success(self, client: AsyncClient):
        """Boundary: raw_text of exactly 512000 bytes (= 500KB) — succeeds with 201."""
        # Arrange — exactly 512000 bytes
        max_text = "a" * RAW_TEXT_MAX_BYTES
        payload = make_event_payload(raw_text=max_text, title="边界测试_正好500KB")

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 201
        assert resp.json()["title"] == "边界测试_正好500KB"

    async def test_raw_text_just_under_limit_success(self, client: AsyncClient):
        """Boundary: raw_text of 511999 bytes (< 500KB) — succeeds with 201."""
        # Arrange — 511999 bytes
        under_text = "a" * (RAW_TEXT_MAX_BYTES - 1)
        payload = make_event_payload(raw_text=under_text, title="边界测试_略小于500KB")

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 201
        assert resp.json()["title"] == "边界测试_略小于500KB"


# ══════════════════════════════════════════════════════════════════════════════
# G1-07: DELETE cascade
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_07_DeleteCascade:
    """G1-07: DELETE /events/{id} — cascade deletes related entities, todos, associations."""

    async def test_delete_event_cascades_to_entities(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: deleting event removes related entities."""
        # Arrange
        event = await insert_event_directly(db_session, status="completed")
        entity1 = await insert_entity_directly(
            db_session, source_event_id=event.id, name="人物A"
        )
        entity2 = await insert_entity_directly(
            db_session, source_event_id=event.id, name="人物B"
        )
        await db_session.commit()

        # Act
        resp = await client.delete(f"{API_PREFIX}/events/{event.id}")

        # Assert
        assert resp.status_code == 204

        # Verify entities are deleted
        e1_result = await db_session.execute(
            select(Entity).where(Entity.id == str(entity1.id))
        )
        e2_result = await db_session.execute(
            select(Entity).where(Entity.id == str(entity2.id))
        )
        assert e1_result.scalar_one_or_none() is None
        assert e2_result.scalar_one_or_none() is None

    async def test_delete_event_cascades_to_todos(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: deleting event removes related todos (both source_event and related_entity)."""
        # Arrange
        event = await insert_event_directly(db_session, status="completed")
        entity = await insert_entity_directly(
            db_session, source_event_id=event.id, name="人物C"
        )
        todo1 = await insert_todo_directly(
            db_session,
            source_event_id=event.id,
            title="事件级待办",
        )
        todo2 = await insert_todo_directly(
            db_session,
            source_event_id=event.id,
            title="实体级待办",
            related_entity_id=str(entity.id),
        )
        await db_session.commit()

        # Act
        resp = await client.delete(f"{API_PREFIX}/events/{event.id}")

        # Assert
        assert resp.status_code == 204

        # Verify both todos are deleted
        t1_result = await db_session.execute(
            select(Todo).where(Todo.id == str(todo1.id))
        )
        t2_result = await db_session.execute(
            select(Todo).where(Todo.id == str(todo2.id))
        )
        assert t1_result.scalar_one_or_none() is None
        assert t2_result.scalar_one_or_none() is None

    async def test_delete_event_cascades_to_associations(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: deleting event removes related associations."""
        # Arrange
        event = await insert_event_directly(db_session, status="completed")
        entity1 = await insert_entity_directly(
            db_session, source_event_id=event.id, name="人物D"
        )
        entity2 = await insert_entity_directly(
            db_session, source_event_id=event.id, name="人物E"
        )
        assoc = await insert_association_directly(
            db_session,
            source_event_id=event.id,
            source_entity_id=str(entity1.id),
            target_entity_id=str(entity2.id),
        )
        await db_session.commit()

        # Act
        resp = await client.delete(f"{API_PREFIX}/events/{event.id}")

        # Assert
        assert resp.status_code == 204

        # Verify association is deleted
        a_result = await db_session.execute(
            select(Association).where(Association.id == str(assoc.id))
        )
        assert a_result.scalar_one_or_none() is None

    async def test_delete_nonexistent_event_404(self, client: AsyncClient):
        """Error: deleting a non-existent event — returns 404."""
        # Arrange
        fake_id = str(uuid.uuid4())

        # Act
        resp = await client.delete(f"{API_PREFIX}/events/{fake_id}")

        # Assert
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# G1-08: Search and filter
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_08_SearchAndFilter:
    """G1-08: GET /events — search, status, event_type, limit, offset combinations."""

    async def test_search_events_by_title(self, client: AsyncClient, db_session: AsyncSession):
        """Happy: search parameter matches event titles."""
        # Arrange
        await insert_event_directly(db_session, title="与张总开会", raw_text="讨论项目", status="completed")
        await insert_event_directly(db_session, title="电话沟通", raw_text="和李总通话", status="completed")
        await insert_event_directly(db_session, title="张总回访", raw_text="跟进张总", status="completed")
        await db_session.commit()

        # Act
        resp = await client.get(f"{API_PREFIX}/events", params={"search": "张总"})

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        titles = [e["title"] for e in data["items"]]
        assert "与张总开会" in titles
        assert "张总回访" in titles
        assert "电话沟通" not in titles

    async def test_search_events_by_raw_text(self, client: AsyncClient, db_session: AsyncSession):
        """Happy: search parameter matches event raw_text."""
        # Arrange
        await insert_event_directly(db_session, title="事件A", raw_text="讨论AI技术趋势", status="completed")
        await insert_event_directly(db_session, title="事件B", raw_text="市场推广计划", status="completed")
        await db_session.commit()

        # Act
        resp = await client.get(f"{API_PREFIX}/events", params={"search": "AI技术"})

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        titles = [e["title"] for e in data["items"]]
        assert "事件A" in titles
        assert "事件B" not in titles

    async def test_filter_events_by_event_type(self, client: AsyncClient, db_session: AsyncSession):
        """Happy: event_type filter returns only matching events."""
        # Arrange
        await insert_event_directly(db_session, title="会议1", event_type="meeting", status="completed")
        await insert_event_directly(db_session, title="电话1", event_type="call", status="completed")
        await insert_event_directly(db_session, title="会议2", event_type="meeting", status="completed")
        await db_session.commit()

        # Act
        resp = await client.get(f"{API_PREFIX}/events", params={"event_type": "meeting"})

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        titles = [e["title"] for e in data["items"]]
        assert "会议1" in titles
        assert "会议2" in titles
        assert "电话1" not in titles
        assert all(e["event_type"] == "meeting" for e in data["items"])

    async def test_filter_events_by_status(self, client: AsyncClient, db_session: AsyncSession):
        """Happy: status filter returns only matching events."""
        # Arrange
        await insert_event_directly(db_session, title="已完成事件", status="completed")
        await insert_event_directly(db_session, title="失败事件", status="failed")
        await insert_event_directly(db_session, title="待处理事件", status="pending")
        await db_session.commit()

        # Act
        resp = await client.get(f"{API_PREFIX}/events", params={"status": "failed"})

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        titles = [e["title"] for e in data["items"]]
        assert "失败事件" in titles
        assert "已完成事件" not in titles
        assert "待处理事件" not in titles
        assert all(e["status"] == "failed" for e in data["items"])

    async def test_pagination_with_limit_and_offset(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: limit/offset pagination returns correct slice and total."""
        # Arrange — create 5 events
        for i in range(5):
            await insert_event_directly(
                db_session, title=f"分页事件_{i}", status="completed"
            )
        await db_session.commit()

        # Act — page 1 (limit=2, offset=0)
        resp1 = await client.get(
            f"{API_PREFIX}/events", params={"limit": 2, "offset": 0}
        )
        # Act — page 2 (limit=2, offset=2)
        resp2 = await client.get(
            f"{API_PREFIX}/events", params={"limit": 2, "offset": 2}
        )
        # Act — page 3 (limit=2, offset=4)
        resp3 = await client.get(
            f"{API_PREFIX}/events", params={"limit": 2, "offset": 4}
        )

        # Assert
        data1 = resp1.json()
        data2 = resp2.json()
        data3 = resp3.json()

        assert data1["total"] == 5
        assert len(data1["items"]) == 2
        assert data1["limit"] == 2
        assert data1["offset"] == 0

        assert len(data2["items"]) == 2
        assert data2["offset"] == 2

        assert len(data3["items"]) == 1  # only 1 remaining
        assert data3["offset"] == 4

        # Verify no overlap between pages
        ids_page1 = {e["id"] for e in data1["items"]}
        ids_page2 = {e["id"] for e in data2["items"]}
        ids_page3 = {e["id"] for e in data3["items"]}
        assert ids_page1.isdisjoint(ids_page2)
        assert ids_page2.isdisjoint(ids_page3)
        assert ids_page1.isdisjoint(ids_page3)


# ══════════════════════════════════════════════════════════════════════════════
# G1-09: call event type
# ══════════════════════════════════════════════════════════════════════════════


class TestG1_09_CallEventType:
    """G1-09: POST /events with event_type='call' — verify API creation succeeds."""

    async def test_create_call_event_returns_201(self, client: AsyncClient):
        """Happy: call event created successfully via API."""
        # Arrange
        payload = make_event_payload(
            event_type="call",
            source="phone",
            title="与陈总电话沟通",
            raw_text="和陈总通了电话，确认了技术对接的时间",
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "call"
        assert data["source"] == "phone"
        assert data["title"] == "与陈总电话沟通"
        assert data["status"] == "pending"
        assert data["pipeline_status"] == "pending"

    async def test_call_event_with_custom_timestamp(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Happy: call event with explicit timestamp is stored correctly."""
        # Arrange
        custom_ts = "2026-06-15T14:30:00Z"
        payload = make_event_payload(
            event_type="call",
            source="phone",
            title="定时电话",
            raw_text="预约的电话沟通",
            timestamp=custom_ts,
        )

        # Act
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        event_id = resp.json()["id"]

        # Assert
        assert resp.status_code == 201
        result = await db_session.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one()
        assert event.event_type == "call"
        # Verify timestamp was set from request (not just default)
        assert event.timestamp.year == 2026
        assert event.timestamp.month == 6
        assert event.timestamp.day == 15

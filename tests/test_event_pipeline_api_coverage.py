"""Tests for promiselink.api.v1.event_pipeline_api — pipeline endpoints.

Covers the four pipeline endpoints mounted on pipeline_router:
  POST /api/v1/events/batch                  — batch create events
  POST /api/v1/events/{event_id}/retry       — retry failed event
  POST /api/v1/events/{event_id}/accept-degraded — accept degraded result
  POST /api/v1/events/{event_id}/correct     — apply user corrections (纠偏)

Uses httpx.AsyncClient + ASGITransport with real in-memory SQLite DB.
The process_event_background stub is patched in BOTH events and
event_pipeline_api modules (the latter imports the function by value).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.api.v1 import event_pipeline_api as pipeline_module
from promiselink.api.v1 import events as events_module
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


@pytest.fixture(autouse=True)
def _mock_pipeline(monkeypatch):
    """Stub process_event_background in both events and event_pipeline_api modules.

    event_pipeline_api imports the function by value, so we must patch it
    in its own namespace (the conftest mock_pipeline only patches events).
    """
    async def _noop(event_id):
        pass

    monkeypatch.setattr(events_module, "process_event_background", _noop)
    monkeypatch.setattr(pipeline_module, "process_event_background", _noop)
    yield


# ── Helpers ──


async def _seed_event(
    session: AsyncSession,
    *,
    status: str = "completed",
    event_type: str = "meeting",
    title: str = "Test Event",
    raw_text: str = "test raw text",
    user_id: str = TEST_USER_ID,
) -> Event:
    """Create a test Event record directly in the DB."""
    evt = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type=event_type,
        source="test",
        title=title,
        raw_text=raw_text,
        status=status,
    )
    session.add(evt)
    await session.flush()
    return evt


async def _seed_entity(
    session: AsyncSession,
    *,
    name: str = "张三",
    source_event_id: str | None = None,
    status: str = "confirmed",
    user_id: str = TEST_USER_ID,
    company: str | None = None,
    title: str | None = None,
) -> Entity:
    """Create a test Entity record.

    source_event_id is required (NOT NULL in the Entity model). If not
    provided, a throwaway event is created to satisfy the constraint.
    """
    if source_event_id is None:
        # Entity.source_event_id is NOT NULL — create a throwaway event
        evt = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="manual",
            source="seed",
            title="seed event",
            status="completed",
        )
        session.add(evt)
        await session.flush()
        source_event_id = str(evt.id)

    props = {}
    if company or title:
        props = {"basic": {}}
        if company:
            props["basic"]["company"] = company
        if title:
            props["basic"]["title"] = title

    ent = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=[],
        properties=props if props else None,
        source_event_id=source_event_id,
        confidence=0.95,
        status=status,
    )
    session.add(ent)
    await session.flush()
    return ent


async def _seed_todo(
    session: AsyncSession,
    *,
    title: str = "Test Todo",
    todo_type: str = "care",
    status: str = "pending",
    source_event_id: str | None = None,
    related_entity_id: str | None = None,
    user_id: str = TEST_USER_ID,
    confirmation_status: str | None = None,
    action_type: str | None = None,
    description: str = "test description",
) -> Todo:
    """Create a test Todo record."""
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title=title,
        description=description,
        priority=3,
        status=status,
        source_event_id=source_event_id,
        related_entity_id=related_entity_id,
        properties={},
        confirmation_status=confirmation_status,
        action_type=action_type,
    )
    session.add(todo)
    await session.flush()
    return todo


async def _seed_association(
    session: AsyncSession,
    *,
    source_entity_id: str,
    target_entity_id: str,
    association_type: str = "co_occurrence",
    strength: float = 0.5,
    user_id: str = TEST_USER_ID,
    source_event_id: str | None = None,
) -> Association:
    """Create a test Association record."""
    assoc = Association(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        association_type=association_type,
        strength=strength,
        source_event_id=source_event_id,
        confidence=1.0,
        status="confirmed",
    )
    session.add(assoc)
    await session.flush()
    return assoc


# ═══════════════════════════════════════════════════════════════
# batch_create_events — POST /events/batch (lines 72-164)
# ═══════════════════════════════════════════════════════════════


class TestBatchCreateEvents:
    """POST /api/v1/events/batch — batch event creation."""

    @pytest.mark.asyncio
    async def test_happy_creates_multiple_events(self, client, db_session):
        """Two valid events are created, both returned with pipeline_status=pending."""
        payload = {
            "events": [
                {
                    "event_type": "meeting",
                    "source": "manual",
                    "title": "上午会议",
                    "raw_text": "和李总讨论合作",
                },
                {
                    "event_type": "call",
                    "source": "manual",
                    "title": "下午电话",
                    "raw_text": "和陈宇鑫电话沟通",
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_requested"] == 2
        assert data["total_created"] == 2
        assert len(data["created"]) == 2
        assert len(data["failed"]) == 0
        assert data["created"][0]["pipeline_status"] == "pending"
        assert data["created"][0]["entity_count"] == 0
        assert data["created"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_invalid_event_type_goes_to_failed(self, client, db_session):
        """Invalid event_type is rejected and added to the failed list."""
        payload = {
            "events": [
                {
                    "event_type": "invalid_type",
                    "source": "manual",
                    "title": "Bad",
                    "raw_text": "x",
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_created"] == 0
        assert len(data["failed"]) == 1
        assert data["failed"][0]["index"] == 0
        assert "Invalid event_type" in data["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_oversized_raw_text_goes_to_failed(self, client, db_session):
        """raw_text exceeding 500KB is added to the failed list."""
        big_text = "x" * (512000 + 1)
        payload = {
            "events": [
                {
                    "event_type": "meeting",
                    "source": "manual",
                    "title": "Big",
                    "raw_text": big_text,
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_created"] == 0
        assert len(data["failed"]) == 1
        assert "500KB" in data["failed"][0]["error"]

    @pytest.mark.asyncio
    async def test_mixed_valid_and_invalid(self, client, db_session):
        """One valid + one invalid → 1 created, 1 failed."""
        payload = {
            "events": [
                {
                    "event_type": "meeting",
                    "source": "manual",
                    "title": "Good",
                    "raw_text": "valid",
                },
                {
                    "event_type": "bad_type",
                    "source": "manual",
                    "title": "Bad",
                    "raw_text": "invalid",
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["total_requested"] == 2
        assert data["total_created"] == 1
        assert len(data["created"]) == 1
        assert len(data["failed"]) == 1
        assert data["failed"][0]["index"] == 1

    @pytest.mark.asyncio
    async def test_empty_events_list_rejected(self, client, db_session):
        """Empty events list is rejected by pydantic (min_length=1)."""
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": []})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_too_many_events_rejected(self, client, db_session):
        """More than 20 events is rejected by pydantic (max_length=20)."""
        events = [
            {"event_type": "meeting", "source": "s", "title": "t", "raw_text": "r"}
            for _ in range(21)
        ]
        resp = await client.post(f"{API_PREFIX}/events/batch", json={"events": events})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_event_with_timestamp(self, client, db_session):
        """Custom timestamp is stored on the created event."""
        ts = "2026-06-15T14:30:00Z"
        payload = {
            "events": [
                {
                    "event_type": "call",
                    "source": "manual",
                    "title": "Timed",
                    "timestamp": ts,
                    "raw_text": "x",
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        created = resp.json()["created"][0]
        assert "2026-06-15" in created["timestamp"]

    @pytest.mark.asyncio
    async def test_event_with_metadata(self, client, db_session):
        """metadata field is stored on the created event."""
        payload = {
            "events": [
                {
                    "event_type": "card_save",
                    "source": "iamhere",
                    "title": "Card",
                    "raw_text": "x",
                    "metadata": {"scan_quality": "high"},
                },
            ]
        }
        resp = await client.post(f"{API_PREFIX}/events/batch", json=payload)
        assert resp.status_code == 201
        assert resp.json()["total_created"] == 1


# ═══════════════════════════════════════════════════════════════
# retry_event — POST /events/{event_id}/retry (lines 167-208)
# ═══════════════════════════════════════════════════════════════


class TestRetryEvent:
    """POST /api/v1/events/{event_id}/retry — retry failed/awaiting_retry events."""

    @pytest.mark.asyncio
    async def test_happy_retries_failed_event(self, client, db_session):
        """Failed event is reset to pending and pipeline is re-triggered."""
        event = await _seed_event(db_session, status="failed", title="Failed Event")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(event.id)
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_happy_retries_awaiting_retry_event(self, client, db_session):
        """awaiting_retry event is reset to pending."""
        event = await _seed_event(db_session, status="awaiting_retry")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client, db_session):
        """Non-existent event_id returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(f"{API_PREFIX}/events/{fake_id}/retry")
        assert resp.status_code == 404
        assert "not found" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_completed_event_not_retryable(self, client, db_session):
        """Completed event cannot be retried → 400."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 400
        assert "retryable" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_pending_event_not_retryable(self, client, db_session):
        """Pending event cannot be retried → 400."""
        event = await _seed_event(db_session, status="pending")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_degraded_completed_not_retryable(self, client, db_session):
        """degraded_completed event cannot be retried → 400."""
        event = await _seed_event(db_session, status="degraded_completed")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_retry_resets_failed_steps(self, client, db_session):
        """failed_steps is cleared after retry."""
        event = await _seed_event(db_session, status="failed")
        event.failed_steps = ["step01_verify_event", "step04_todo_generation"]
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/retry")
        assert resp.status_code == 200

        # Verify failed_steps was cleared
        await db_session.refresh(event)
        assert event.failed_steps is None


# ═══════════════════════════════════════════════════════════════
# accept_degraded_event — POST /events/{event_id}/accept-degraded (lines 211-245)
# ═══════════════════════════════════════════════════════════════


class TestAcceptDegradedEvent:
    """POST /api/v1/events/{event_id}/accept-degraded — accept degraded result."""

    @pytest.mark.asyncio
    async def test_happy_accepts_awaiting_retry(self, client, db_session):
        """awaiting_retry event is marked degraded_completed."""
        event = await _seed_event(db_session, status="awaiting_retry")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded_completed"

    @pytest.mark.asyncio
    async def test_happy_accepts_failed(self, client, db_session):
        """failed event is marked degraded_completed."""
        event = await _seed_event(db_session, status="failed")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded_completed"

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self, client, db_session):
        """Non-existent event_id returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(f"{API_PREFIX}/events/{fake_id}/accept-degraded")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_completed_not_degradable(self, client, db_session):
        """Completed event cannot be degraded → 400."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")
        assert resp.status_code == 400
        assert "degradable" in resp.json()["error"]["message"].lower()

    @pytest.mark.asyncio
    async def test_pending_not_degradable(self, client, db_session):
        """Pending event cannot be degraded → 400."""
        event = await _seed_event(db_session, status="pending")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_accept_sets_processed_at(self, client, db_session):
        """processed_at is set when accepting degraded."""
        event = await _seed_event(db_session, status="awaiting_retry")
        await db_session.commit()

        resp = await client.post(f"{API_PREFIX}/events/{event.id}/accept-degraded")
        assert resp.status_code == 200
        await db_session.refresh(event)
        assert event.processed_at is not None
        assert event.status == "degraded_completed"


# ═══════════════════════════════════════════════════════════════
# correct_event — POST /events/{event_id}/correct (lines 322-553)
# ═══════════════════════════════════════════════════════════════


class TestCorrectEventNotFound:
    """correct_event — error cases."""

    @pytest.mark.asyncio
    async def test_event_not_found_returns_404(self, client, db_session):
        """Non-existent event_id returns 404."""
        fake_id = str(uuid.uuid4())
        resp = await client.post(
            f"{API_PREFIX}/events/{fake_id}/correct",
            json={"corrected_entities": []},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_empty_corrections_returns_zeros(self, client, db_session):
        """Empty correction lists return a response with all counters at 0."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [],
                "corrected_todos": [],
                "corrected_promises": [],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_id"] == str(event.id)
        assert data["entities_updated"] == 0
        assert data["entities_created"] == 0
        assert data["todos_created"] == 0
        assert data["promises_created"] == 0
        assert data["associations_updated"] == 0


class TestCorrectEventEntities:
    """correct_event — entity corrections (人脉纠偏)."""

    @pytest.mark.asyncio
    async def test_select_existing_merges_entity_and_repoints_todos(self, client, db_session):
        """select_existing marks extracted entity as merged and re-points todos."""
        event = await _seed_event(db_session, status="completed")
        extracted = await _seed_entity(db_session, name="张三", source_event_id=str(event.id), status="confirmed")
        target = await _seed_entity(db_session, name="张三丰", status="confirmed")
        todo = await _seed_todo(
            db_session,
            title="follow up",
            source_event_id=str(event.id),
            related_entity_id=str(extracted.id),
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": str(extracted.id),
                        "action": "select_existing",
                        "selected_entity_id": str(target.id),
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_updated"] == 1

        # Verify DB state
        await db_session.refresh(extracted)
        await db_session.refresh(todo)
        assert extracted.status == "merged"
        assert str(todo.related_entity_id) == str(target.id)

    @pytest.mark.asyncio
    async def test_create_new_updates_entity_info(self, client, db_session):
        """create_new updates the extracted entity's name/company/title."""
        event = await _seed_event(db_session, status="completed")
        extracted = await _seed_entity(
            db_session, name="旧名", source_event_id=str(event.id),
            status="confirmed", company="旧公司", title="旧职位",
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": str(extracted.id),
                        "action": "create_new",
                        "new_name": "新名",
                        "new_company": "新公司",
                        "new_title": "新职位",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_created"] == 1

        await db_session.refresh(extracted)
        assert extracted.name == "新名"
        assert extracted.canonical_name == "新名"
        assert extracted.status == "confirmed"
        assert extracted.properties["basic"]["company"] == "新公司"
        assert extracted.properties["basic"]["title"] == "新职位"

    @pytest.mark.asyncio
    async def test_ignore_marks_entity_deleted(self, client, db_session):
        """ignore action marks the extracted entity as deleted."""
        event = await _seed_event(db_session, status="completed")
        extracted = await _seed_entity(db_session, name="忽略", source_event_id=str(event.id), status="confirmed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": str(extracted.id),
                        "action": "ignore",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["entities_ignored"] == 1

        await db_session.refresh(extracted)
        assert extracted.status == "deleted"

    @pytest.mark.asyncio
    async def test_nonexistent_extracted_entity_is_skipped(self, client, db_session):
        """If extracted_entity_id doesn't exist, the correction is skipped (continue)."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()
        fake_entity_id = str(uuid.uuid4())

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": fake_entity_id,
                        "action": "ignore",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_ignored"] == 0


class TestCorrectEventTodos:
    """correct_event — todo corrections (待办纠偏)."""

    @pytest.mark.asyncio
    async def test_add_creates_new_todo(self, client, db_session):
        """add action creates a new followup todo."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_todos": [
                    {
                        "action": "add",
                        "title": "新待办",
                        "description": "跟进客户",
                        "priority": 2,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["todos_created"] == 1

    @pytest.mark.asyncio
    async def test_delete_removes_todo(self, client, db_session):
        """delete action removes an existing todo."""
        event = await _seed_event(db_session, status="completed")
        todo = await _seed_todo(db_session, title="待删除", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_todos": [
                    {
                        "id": str(todo.id),
                        "action": "delete",
                        "title": "待删除",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["todos_deleted"] == 1

    @pytest.mark.asyncio
    async def test_edit_updates_todo_fields(self, client, db_session):
        """edit action updates title/description/priority of an existing todo."""
        event = await _seed_event(db_session, status="completed")
        todo = await _seed_todo(db_session, title="原标题", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_todos": [
                    {
                        "id": str(todo.id),
                        "action": "edit",
                        "title": "新标题",
                        "description": "新描述",
                        "priority": 1,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["todos_updated"] == 1

        await db_session.refresh(todo)
        assert todo.title == "新标题"
        assert todo.description == "新描述"
        assert todo.priority == 1

    @pytest.mark.asyncio
    async def test_delete_nonexistent_todo_skipped(self, client, db_session):
        """delete with non-existent todo ID is skipped."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_todos": [
                    {
                        "id": str(uuid.uuid4()),
                        "action": "delete",
                        "title": "x",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["todos_deleted"] == 0


class TestCorrectEventPromises:
    """correct_event — promise corrections (承诺纠偏)."""

    @pytest.mark.asyncio
    async def test_add_promise_with_promisor_and_beneficiary(self, client, db_session):
        """add action creates a new promise todo with explicit promisor/beneficiary."""
        event = await _seed_event(db_session, status="completed")
        entity = await _seed_entity(db_session, name="李四", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "action": "add",
                        "content": "我承诺下周交付方案",
                        "promise_type": "my_promise",
                        "promisor_id": str(entity.id),
                        "beneficiary_id": str(entity.id),
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1

    @pytest.mark.asyncio
    async def test_add_promise_infers_counterparty_from_event_entities(self, client, db_session):
        """add promise without promisor_id/beneficiary_id infers from event entities."""
        event = await _seed_event(db_session, status="completed")
        entity = await _seed_entity(db_session, name="王五", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "action": "add",
                        "content": "对方承诺下周回复",
                        "promise_type": "their_promise",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["promises_created"] == 1
        # their_promise: promisor inferred as counterparty (first related entity)
        # beneficiary not set (would be current user implicitly)

    @pytest.mark.asyncio
    async def test_add_my_promise_infers_beneficiary(self, client, db_session):
        """my_promise without beneficiary_id infers counterparty from event entities."""
        event = await _seed_event(db_session, status="completed")
        entity = await _seed_entity(db_session, name="赵六", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "action": "add",
                        "content": "我承诺下周联系",
                        "promise_type": "my_promise",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_created"] == 1

    @pytest.mark.asyncio
    async def test_add_promise_without_content_skipped(self, client, db_session):
        """add promise with no content is skipped (continue)."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "action": "add",
                        "content": "",
                        "promise_type": "my_promise",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_created"] == 0

    @pytest.mark.asyncio
    async def test_confirm_promise(self, client, db_session):
        """confirm action sets confirmation_status=confirmed."""
        event = await _seed_event(db_session, status="completed")
        promise = await _seed_todo(
            db_session, title="承诺", todo_type="promise",
            source_event_id=str(event.id), confirmation_status="pending",
            action_type="my_promise",
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "id": str(promise.id),
                        "action": "confirm",
                        "content": None,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_confirmed"] == 1

        await db_session.refresh(promise)
        assert promise.confirmation_status == "confirmed"

    @pytest.mark.asyncio
    async def test_ignore_promise_rejects_it(self, client, db_session):
        """ignore action sets confirmation_status=rejected and status=dismissed."""
        event = await _seed_event(db_session, status="completed")
        promise = await _seed_todo(
            db_session, title="承诺", todo_type="promise",
            source_event_id=str(event.id), confirmation_status="pending",
            action_type="my_promise",
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "id": str(promise.id),
                        "action": "ignore",
                        "content": None,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_ignored"] == 1

        await db_session.refresh(promise)
        assert promise.confirmation_status == "rejected"
        assert promise.status == "dismissed"

    @pytest.mark.asyncio
    async def test_modify_promise_updates_fields(self, client, db_session):
        """modify action updates content/due_date/promise_type and confirms."""
        event = await _seed_event(db_session, status="completed")
        promise = await _seed_todo(
            db_session, title="承诺", todo_type="promise",
            source_event_id=str(event.id), confirmation_status="pending",
            action_type="my_promise", description="旧内容",
        )
        await db_session.commit()

        due = "2026-07-20T12:00:00Z"
        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "id": str(promise.id),
                        "action": "modify",
                        "content": "修改后的内容",
                        "due_date": due,
                        "promise_type": "their_promise",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_modified"] == 1

        await db_session.refresh(promise)
        assert promise.description == "修改后的内容"
        assert promise.action_type == "their_promise"
        assert promise.confirmation_status == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_nonexistent_promise_skipped(self, client, db_session):
        """confirm with non-existent promise ID is skipped."""
        event = await _seed_event(db_session, status="completed")
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_promises": [
                    {
                        "id": str(uuid.uuid4()),
                        "action": "confirm",
                        "content": None,
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["promises_confirmed"] == 0


class TestCorrectEventAssociations:
    """correct_event — association corrections (关系纠偏)."""

    @pytest.mark.asyncio
    async def test_modify_association(self, client, db_session):
        """modify action updates association_type and strength."""
        event = await _seed_event(db_session, status="completed")
        ent1 = await _seed_entity(db_session, name="甲", source_event_id=str(event.id))
        ent2 = await _seed_entity(db_session, name="乙", source_event_id=str(event.id))
        assoc = await _seed_association(
            db_session,
            source_entity_id=str(ent1.id),
            target_entity_id=str(ent2.id),
            association_type="co_occurrence",
            strength=0.3,
            source_event_id=str(event.id),
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_associations": [
                    {
                        "source_entity_id": str(ent1.id),
                        "target_entity_id": str(ent2.id),
                        "relationship_type": "alumni",
                        "strength": 0.9,
                        "action": "modify",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["associations_updated"] == 1

        await db_session.refresh(assoc)
        assert assoc.association_type == "alumni"
        assert assoc.strength == 0.9

    @pytest.mark.asyncio
    async def test_delete_association(self, client, db_session):
        """delete action removes the association."""
        event = await _seed_event(db_session, status="completed")
        ent1 = await _seed_entity(db_session, name="丙", source_event_id=str(event.id))
        ent2 = await _seed_entity(db_session, name="丁", source_event_id=str(event.id))
        assoc = await _seed_association(
            db_session,
            source_entity_id=str(ent1.id),
            target_entity_id=str(ent2.id),
            source_event_id=str(event.id),
        )
        await db_session.commit()
        assoc_id = str(assoc.id)

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_associations": [
                    {
                        "source_entity_id": str(ent1.id),
                        "target_entity_id": str(ent2.id),
                        "action": "delete",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["associations_updated"] == 1

        # Verify the association was deleted
        from sqlalchemy import select
        result = await db_session.execute(
            select(Association).where(Association.id == assoc_id)
        )
        assert result.scalar_one_or_none() is None

    @pytest.mark.asyncio
    async def test_nonexistent_association_skipped(self, client, db_session):
        """If the association doesn't exist, the correction is skipped."""
        event = await _seed_event(db_session, status="completed")
        ent1 = await _seed_entity(db_session, name="戊", source_event_id=str(event.id))
        ent2 = await _seed_entity(db_session, name="己", source_event_id=str(event.id))
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_associations": [
                    {
                        "source_entity_id": str(ent1.id),
                        "target_entity_id": str(ent2.id),
                        "action": "modify",
                        "relationship_type": "alumni",
                    }
                ],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["associations_updated"] == 0


class TestCorrectEventCombined:
    """correct_event — combined corrections across all four categories."""

    @pytest.mark.asyncio
    async def test_combined_corrections_all_categories(self, client, db_session):
        """All four correction categories in a single request."""
        event = await _seed_event(db_session, status="completed")
        ent = await _seed_entity(db_session, name="张三", source_event_id=str(event.id), status="confirmed")
        todo = await _seed_todo(db_session, title="待办", source_event_id=str(event.id))
        promise = await _seed_todo(
            db_session, title="承诺", todo_type="promise",
            source_event_id=str(event.id), confirmation_status="pending",
        )
        await db_session.commit()

        resp = await client.post(
            f"{API_PREFIX}/events/{event.id}/correct",
            json={
                "corrected_entities": [
                    {
                        "extracted_entity_id": str(ent.id),
                        "action": "ignore",
                    }
                ],
                "corrected_todos": [
                    {
                        "action": "add",
                        "title": "新待办",
                        "priority": 3,
                    }
                ],
                "corrected_promises": [
                    {
                        "id": str(promise.id),
                        "action": "confirm",
                        "content": None,
                    }
                ],
                "corrected_associations": [],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["entities_ignored"] == 1
        assert data["todos_created"] == 1
        assert data["promises_confirmed"] == 1

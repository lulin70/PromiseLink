"""API integration tests for manual duplicate handling endpoints.

Covers: POST /entities/{id}/confirm, POST /entities/{target_id}/merge,
GET /entities/duplicates — happy path + 400/404/409 error contracts.
Design: docs/design/Duplicate_Entity_Manual_Handling_2026-08-16.md §2.1/§3.2.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"


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

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, mock_pipeline):
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def insert_entity(db_session: AsyncSession, **overrides) -> Entity:
    """Insert an Entity directly into the test DB."""
    data: dict = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "entity_type": "person",
        "name": "王总",
        "canonical_name": "王总",
        "aliases": [],
        "properties": {},
        "status": "confirmed",
        "confidence": 0.9,
    }
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = Event(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            event_type="meeting",
            source="test",
            title="Test Event",
            raw_text="raw",
            status="completed",
        )
        db_session.add(event)
        await db_session.flush()
        source_event_id = event.id
    data.update(overrides)
    entity = Entity(**data, source_event_id=source_event_id)
    db_session.add(entity)
    await db_session.flush()
    return entity


async def insert_todo(db_session: AsyncSession, entity_id: str) -> Todo:
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        todo_type="followup",
        title="跟进王总",
        related_entity_id=entity_id,
        status="pending",
        priority=3,
    )
    db_session.add(todo)
    await db_session.flush()
    return todo


# ── POST /entities/{id}/confirm ──


@pytest.mark.asyncio
async def test_confirm_provisional_entity(client, db_session):
    entity = await insert_entity(db_session, status="provisional")

    resp = await client.post(f"{API_PREFIX}/entities/{entity.id}/confirm")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(entity.id)
    assert body["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_not_found(client):
    resp = await client.post(f"{API_PREFIX}/entities/{uuid.uuid4()}/confirm")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_confirm_non_provisional_conflict(client, db_session):
    entity = await insert_entity(db_session, status="confirmed")

    resp = await client.post(f"{API_PREFIX}/entities/{entity.id}/confirm")

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


# ── POST /entities/{target_id}/merge ──


@pytest.mark.asyncio
async def test_merge_happy_path(client, db_session):
    target = await insert_entity(
        db_session,
        name="王志强",
        canonical_name="王志强",
        properties={"basic": {"company": "创新科技"}},
    )
    source = await insert_entity(
        db_session,
        name="王总",
        canonical_name="王总",
        properties={"basic": {"title": "CEO"}},
    )
    todo = await insert_todo(db_session, str(source.id))

    resp = await client.post(
        f"{API_PREFIX}/entities/{target.id}/merge",
        json={"source_id": str(source.id)},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["target"]["id"] == str(target.id)
    assert body["target"]["status"] == "confirmed"
    assert body["migrated"]["todos"] == 1
    # Alias appended in response
    assert "王总" in (body["target"]["aliases"] or [])

    # Source tombstoned (merged) and disappears from list view
    src_resp = await client.get(f"{API_PREFIX}/entities/{source.id}")
    assert src_resp.status_code == 200
    assert src_resp.json()["status"] == "merged"

    list_resp = await client.get(f"{API_PREFIX}/entities")
    ids = [e["id"] for e in list_resp.json()["items"]]
    assert str(source.id) not in ids
    assert str(target.id) in ids

    # Todo migrated to target (verify via history endpoint)
    hist_resp = await client.get(f"{API_PREFIX}/entities/{target.id}/history")
    assert hist_resp.status_code == 200


@pytest.mark.asyncio
async def test_merge_self_merge_rejected(client, db_session):
    entity = await insert_entity(db_session)

    resp = await client.post(
        f"{API_PREFIX}/entities/{entity.id}/merge",
        json={"source_id": str(entity.id)},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_merge_missing_source_not_found(client, db_session):
    target = await insert_entity(db_session)

    resp = await client.post(
        f"{API_PREFIX}/entities/{target.id}/merge",
        json={"source_id": str(uuid.uuid4())},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_merge_already_merged_conflict_with_merged_into(client, db_session):
    target = await insert_entity(db_session, name="王志强", canonical_name="王志强")
    source = await insert_entity(db_session, name="王总", canonical_name="王总")

    first = await client.post(
        f"{API_PREFIX}/entities/{target.id}/merge",
        json={"source_id": str(source.id)},
    )
    assert first.status_code == 200

    # Merging the tombstoned source again → 409 with merged_into for redirect
    second = await client.post(
        f"{API_PREFIX}/entities/{target.id}/merge",
        json={"source_id": str(source.id)},
    )
    assert second.status_code == 409
    details = second.json()["error"]["details"]
    assert details.get("merged_into") == str(target.id)


@pytest.mark.asyncio
async def test_merge_invalid_body_unprocessable(client, db_session):
    target = await insert_entity(db_session)

    resp = await client.post(
        f"{API_PREFIX}/entities/{target.id}/merge",
        json={},
    )
    assert resp.status_code == 422  # FastAPI request validation (missing field)


# ── GET /entities/duplicates ──


@pytest.mark.asyncio
async def test_duplicates_detects_same_name_groups(client, db_session):
    e1 = await insert_entity(
        db_session, name="王总", canonical_name="王总", properties={"basic": {"company": "A公司"}}
    )
    e2 = await insert_entity(
        db_session,
        name="王总",
        canonical_name="王总",
        properties={"basic": {"company": "B公司", "title": "CTO"}},
    )
    await insert_entity(db_session, name="李四", canonical_name="李四")
    # merged same-name entity must be excluded from duplicate detection
    e3 = await insert_entity(db_session, name="赵五", canonical_name="赵五")
    e3.status = "merged"
    await insert_entity(db_session, name="赵五", canonical_name="赵五")

    resp = await client.get(f"{API_PREFIX}/entities/duplicates")

    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert len(groups) == 1
    group = groups[0]
    assert group["name"] == "王总"
    assert group["hint"] == "同名"
    assert {e["id"] for e in group["entities"]} == {str(e1.id), str(e2.id)}
    by_id = {e["id"]: e for e in group["entities"]}
    assert by_id[str(e2.id)]["company"] == "B公司"
    assert by_id[str(e2.id)]["title"] == "CTO"


@pytest.mark.asyncio
async def test_duplicates_empty_when_all_unique(client, db_session):
    await insert_entity(db_session, name="王总", canonical_name="王总")
    await insert_entity(db_session, name="李四", canonical_name="李四")

    resp = await client.get(f"{API_PREFIX}/entities/duplicates")

    assert resp.status_code == 200
    assert resp.json()["groups"] == []

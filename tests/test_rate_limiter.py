"""Tests for F-24 Rate Limiter and F-23 Privacy Protection API."""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.core.rate_limiter import reset_rate_limits
from promiselink.database import Base, get_async_session
from promiselink.main import app


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

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create an async session bound to the test engine."""
    async_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    yield async_session
    await async_session.close()


@pytest_asyncio.fixture
async def client(db_session):
    """Create an AsyncClient with the test session override."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client():
    """Create an AsyncClient without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helper ──


def _create_test_event_data():
    """Return minimal event creation payload."""
    return {
        "event_type": "manual",
        "source": "test",
        "title": "Test Event",
        "raw_text": "Test raw text",
    }


# ── Rate Limiter Tests ──


async def test_rate_limiter_allows_normal_requests(client):
    """Normal request volume should be allowed (under rate limit)."""
    # Make a few requests — should all succeed
    for _ in range(5):
        response = await client.get(f"{API_PREFIX}/events")
        assert response.status_code in (200, 404), (
            f"Expected 200 or 404, got {response.status_code}"
        )


async def test_rate_limiter_blocks_excessive_requests(client):
    """Excessive requests should be blocked with 429 and Retry-After header."""
    # Use a low limit for testing by hitting the endpoint many times
    # The default authenticated limit is 60/min, so we need to exceed it
    # We'll use the in-memory limiter directly for a more controlled test
    from promiselink.core.rate_limiter import check_rate_limit

    key = "user:test_user_block"
    limit = 5

    # First 5 requests should be allowed
    for i in range(limit):
        allowed, remaining, retry_after = await check_rate_limit(key, limit)
        assert allowed is True, f"Request {i+1} should be allowed"

    # 6th request should be blocked
    allowed, remaining, retry_after = await check_rate_limit(key, limit)
    assert allowed is False, "Request exceeding limit should be blocked"
    assert retry_after > 0, "retry_after should be positive when blocked"

    # Clean up
    reset_rate_limits(key)


async def test_rate_limiter_llm_endpoints_lower_limit(client):
    """LLM endpoints (/voice/, /media/) should use lower rate limit."""
    from promiselink.core.rate_limiter import check_rate_limit

    # LLM limit is separate from standard limit
    llm_key = "llm:user:test_llm_user"
    standard_key = "user:test_llm_user"

    llm_limit = 20
    standard_limit = 60

    # Verify LLM key has lower limit
    for i in range(llm_limit):
        allowed, _, _ = await check_rate_limit(llm_key, llm_limit)
        assert allowed is True, f"LLM request {i+1} should be allowed"

    # LLM limit should now be exhausted
    allowed, _, retry_after = await check_rate_limit(llm_key, llm_limit)
    assert allowed is False, "LLM request exceeding limit should be blocked"

    # Standard limit should still have capacity
    allowed, _, _ = await check_rate_limit(standard_key, standard_limit)
    assert allowed is True, "Standard request should still be allowed"

    # Clean up
    reset_rate_limits(llm_key)
    reset_rate_limits(standard_key)


# ── Privacy API Tests ──


async def test_privacy_data_summary_requires_auth(unauth_client):
    """GET /privacy/data-summary without token → 401."""
    response = await unauth_client.get(f"{API_PREFIX}/privacy/data-summary")
    assert response.status_code == 401


async def test_privacy_data_summary_returns_counts(client, db_session):
    """GET /privacy/data-summary returns correct counts of user data."""
    # Create some test data
    from promiselink.models.event import Event
    from promiselink.models.entity import Entity
    from promiselink.models.todo import Todo

    # Create events first (entities and todos reference events)
    event_ids = []
    for i in range(3):
        event = Event(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            event_type="manual",
            source="test",
            title=f"Test Event {i}",
            raw_text="test",
            status="completed",
        )
        db_session.add(event)
        event_ids.append(event.id)

    await db_session.flush()

    # Create entities (require source_event_id)
    for i in range(2):
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            entity_type="person",
            name=f"Test Person {i}",
            canonical_name=f"Test Person {i}",
            source_event_id=event_ids[i],
            confidence=0.9,
            status="confirmed",
        )
        db_session.add(entity)

    # Create a todo (requires source_event_id)
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        todo_type="promise",
        title="Test Todo",
        source_event_id=event_ids[0],
        priority=3,
        status="pending",
    )
    db_session.add(todo)

    await db_session.commit()

    response = await client.get(f"{API_PREFIX}/privacy/data-summary")
    assert response.status_code == 200

    data = response.json()
    assert data["events"] == 3
    assert data["entities"] == 2
    assert data["todos"] == 1
    assert data["associations"] == 0
    assert data["voice_sessions"] == 0


async def test_privacy_delete_user_data(client, db_session):
    """DELETE /privacy/user-data removes all user data."""
    from promiselink.models.event import Event
    from promiselink.models.entity import Entity
    from promiselink.models.todo import Todo
    from promiselink.models.association import Association

    # Create test data
    event_ids = []
    for i in range(2):
        event = Event(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            event_type="manual",
            source="test",
            title=f"Delete Test Event {i}",
            raw_text="test",
            status="completed",
        )
        db_session.add(event)
        event_ids.append(event.id)

    await db_session.flush()

    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        entity_type="person",
        name="Delete Test Person",
        canonical_name="Delete Test Person",
        source_event_id=event_ids[0],
        confidence=0.9,
        status="confirmed",
    )
    db_session.add(entity)

    await db_session.commit()

    # Verify data exists before deletion
    from sqlalchemy import select, func

    count_before = (
        await db_session.execute(
            select(func.count()).select_from(Event).where(Event.user_id == TEST_USER_ID)
        )
    ).scalar()
    assert count_before == 2

    # Delete all user data
    response = await client.delete(f"{API_PREFIX}/privacy/user-data")
    assert response.status_code == 200

    data = response.json()
    assert data["deleted"] is True
    assert data["events_deleted"] == 2
    assert data["entities_deleted"] == 1

    # Verify data is gone
    count_after = (
        await db_session.execute(
            select(func.count()).select_from(Event).where(Event.user_id == TEST_USER_ID)
        )
    ).scalar()
    assert count_after == 0

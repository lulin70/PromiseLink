"""Performance baseline tests for PromiseLink API.

Establishes response time baselines for:
  A. API response times (8 endpoints)
  B. Database query performance (4 scenarios)
  C. Concurrency performance (3 scenarios)
  D. Memory and resource usage (2 scenarios)

Uses pytest + httpx AsyncClient with in-memory SQLite.
Each test runs 3 iterations and reports the average.
Thresholds are based on local SQLite baselines — do NOT loosen to pass.
"""

import asyncio
import gc
import os
import time
import tracemalloc
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Force IS_SQLITE=True BEFORE importing models
os.environ.setdefault("DATABASE_URL", "sqlite://")

from promiselink.core.auth import get_current_user_id, get_optional_user_id  # noqa: E402
from promiselink.database import Base, get_async_session  # noqa: E402
from promiselink.main import app  # noqa: E402
from promiselink.models.association import Association  # noqa: E402
from promiselink.models.entity import Entity  # noqa: E402
from promiselink.models.event import Event  # noqa: E402
from promiselink.models.todo import Todo  # noqa: E402

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000010"
API_PREFIX = "/api/v1"
ITERATIONS = 3  # Run each test 3 times and take average


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite async engine with StaticPool.

    StaticPool ensures all sessions share the same in-memory database,
    which is required for concurrent request tests.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
async def session_factory(db_engine):
    """Provide a session factory for creating per-request sessions."""
    return async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest_asyncio.fixture
async def db_session(session_factory):
    """Provide an async DB session for direct data setup."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, mock_pipeline):
    """httpx.AsyncClient with shared DB session and mocked pipeline.

    Use this for sequential request tests. The same DB session is reused
    across all requests within a test.
    """
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_optional_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def concurrent_client(session_factory, mock_pipeline):
    """httpx.AsyncClient that creates a new DB session per request.

    Use this for concurrency tests. Each request gets its own session
    from the factory, but all sessions share the same in-memory database.
    """
    async def override_get_async_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID
    app.dependency_overrides[get_optional_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


async def insert_event(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "event_type": "meeting",
        "source": "manual",
        "title": "Test Event",
        "raw_text": "Test raw text content",
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
        "description": "Send a message to follow up",
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


async def seed_events(session: AsyncSession, count: int) -> list[Event]:
    """Bulk insert events for testing. Returns list of created events."""
    events = []
    for i in range(count):
        event = Event(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            event_type="meeting",
            source="perf_test",
            title=f"Performance Test Event {i}",
            raw_text=f"Raw text content for performance test event number {i}",
            status="completed",
        )
        events.append(event)
    session.add_all(events)
    await session.commit()
    return events


async def seed_entities(session: AsyncSession, count: int) -> tuple[str, list[str]]:
    """Bulk insert entities for testing. Returns (shared_event_id, entity_ids)."""
    event = Event(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        event_type="manual",
        source="perf_test",
        title="Seed Event",
        raw_text="Seed raw text",
        status="completed",
    )
    session.add(event)
    await session.flush()

    entity_ids = []
    for i in range(count):
        eid = str(uuid.uuid4())
        entity = Entity(
            id=eid,
            user_id=TEST_USER_ID,
            entity_type="person",
            name=f"测试人脉{i:04d}",
            canonical_name=f"测试人脉{i:04d}",
            aliases=[],
            properties={
                "basic": {
                    "company": f"公司{i % 20}",
                    "title": f"职位{i % 5}",
                    "city": f"城市{i % 8}",
                }
            },
            source_event_id=event.id,
            confidence=0.9,
            status="confirmed",
        )
        session.add(entity)
        entity_ids.append(eid)

    await session.commit()
    return str(event.id), entity_ids


def avg_ms(times: list[float]) -> float:
    """Convert list of seconds to average milliseconds."""
    return sum(times) / len(times) * 1000


# ══════════════════════════════════════════════════════════════════════════════
# A. API Response Time Baseline
# ══════════════════════════════════════════════════════════════════════════════


class TestAPIResponseBaseline:
    """A. API response time baseline tests.

    Each endpoint is called 3 times; the average must be under threshold.
    """

    async def test_health_baseline(self, client: AsyncClient):
        """GET /api/v1/health → < 50ms (unauthenticated, no DB)."""
        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/health")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 50, f"GET /health avg {avg:.1f}ms exceeds 50ms threshold"

    async def test_dashboard_day_view_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/dashboard/day-view → < 200ms."""
        # Seed some events for today
        await seed_events(db_session, 10)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/dashboard/day-view")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 200, (
            f"GET /dashboard/day-view avg {avg:.1f}ms exceeds 200ms threshold"
        )

    async def test_entities_list_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/entities → < 300ms."""
        await seed_entities(db_session, 50)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/entities?limit=50")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 300, f"GET /entities avg {avg:.1f}ms exceeds 300ms threshold"

    async def test_events_list_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/events → < 300ms."""
        await seed_events(db_session, 50)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/events?limit=50")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 300, f"GET /events avg {avg:.1f}ms exceeds 300ms threshold"

    async def test_promises_list_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/promises → < 300ms."""
        # Seed promise-type todos
        for i in range(20):
            await insert_todo(
                db_session,
                todo_type="promise",
                action_type="my_promise",
                title=f"Promise {i}",
                description=f"Description for promise {i}",
                fulfillment_status="pending",
            )
        await db_session.commit()

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/promises")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 300, f"GET /promises avg {avg:.1f}ms exceeds 300ms threshold"

    async def test_todos_list_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/todos → < 300ms."""
        for i in range(20):
            await insert_todo(
                db_session,
                title=f"Todo {i}",
                description=f"Description for todo {i}",
            )
        await db_session.commit()

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/todos?limit=50")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 300, f"GET /todos avg {avg:.1f}ms exceeds 300ms threshold"

    async def test_create_event_baseline(self, client: AsyncClient):
        """POST /api/v1/events → < 500ms (pipeline mocked)."""
        payload = {
            "event_type": "meeting",
            "source": "perf_test",
            "title": "Performance Test Event",
            "raw_text": "This is a test event for performance baseline measurement.",
        }

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.post(f"{API_PREFIX}/events", json=payload)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 201
        avg = avg_ms(times)
        assert avg < 500, f"POST /events avg {avg:.1f}ms exceeds 500ms threshold"

    async def test_entity_detail_baseline(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """GET /api/v1/entities/{id} → < 150ms."""
        _, entity_ids = await seed_entities(db_session, 5)
        entity_id = entity_ids[0]

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/entities/{entity_id}")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
        avg = avg_ms(times)
        assert avg < 150, (
            f"GET /entities/{{id}} avg {avg:.1f}ms exceeds 150ms threshold"
        )


# ══════════════════════════════════════════════════════════════════════════════
# B. Database Query Performance
# ══════════════════════════════════════════════════════════════════════════════


class TestDatabaseQueryPerformance:
    """B. Database query performance tests."""

    async def test_batch_insert_100_events(self, db_session: AsyncSession):
        """Batch insert 100 events → < 5s."""
        times = []
        for _ in range(ITERATIONS):
            # Clean up previous iteration's data
            await db_session.execute(Event.__table__.delete().where(
                Event.user_id == TEST_USER_ID
            ))
            await db_session.commit()

            start = time.perf_counter()
            await seed_events(db_session, 100)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        avg = avg_ms(times)
        assert avg < 5000, (
            f"Batch insert 100 events avg {avg:.1f}ms exceeds 5000ms threshold"
        )

    async def test_query_100_events(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Query list of 100 events → < 500ms."""
        await seed_events(db_session, 100)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/events?limit=100")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["items"]) == 100

        avg = avg_ms(times)
        assert avg < 500, (
            f"Query 100 events avg {avg:.1f}ms exceeds 500ms threshold"
        )

    async def test_search_1000_entities(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Search 1000 entities → < 1s."""
        await seed_entities(db_session, 1000)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/entities?search=测试人脉05")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200

        avg = avg_ms(times)
        assert avg < 1000, (
            f"Search 1000 entities avg {avg:.1f}ms exceeds 1000ms threshold"
        )

    async def test_join_query(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Join query (events + entities + promises) → < 300ms.

        Uses GET /api/v1/entities/{id}/history which joins entity, events,
        todos, and associations.
        """
        # Set up related data: event → entity → todo + association
        event = await insert_event(db_session, title="Join Query Test Event")
        entity = await insert_entity(
            db_session,
            source_event_id=event.id,
            name="Join Query Person",
        )
        await insert_todo(
            db_session,
            source_event_id=event.id,
            todo_type="promise",
            action_type="my_promise",
            title="Join Query Promise",
            related_entity_id=entity.id,
        )
        # Create a second entity for association
        entity2 = await insert_entity(
            db_session,
            source_event_id=event.id,
            name="Join Query Person 2",
        )
        await insert_association(
            db_session,
            source_event_id=event.id,
            source_entity_id=entity.id,
            target_entity_id=entity2.id,
            association_type="same_city",
        )
        await db_session.commit()

        entity_id = str(entity.id)

        times = []
        for _ in range(ITERATIONS):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/entities/{entity_id}/history")
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert resp.status_code == 200

        avg = avg_ms(times)
        assert avg < 300, (
            f"Join query (entity history) avg {avg:.1f}ms exceeds 300ms threshold"
        )


# ══════════════════════════════════════════════════════════════════════════════
# C. Concurrency Performance
# ══════════════════════════════════════════════════════════════════════════════


class TestConcurrencyPerformance:
    """C. Concurrency performance tests.

    All concurrent requests must individually complete within threshold.
    Uses concurrent_client which creates a new DB session per request.
    """

    async def test_concurrent_health(self, concurrent_client: AsyncClient):
        """10 concurrent GET /api/v1/health → all < 100ms."""
        concurrency = 10
        threshold_ms = 100

        async def single_request():
            start = time.perf_counter()
            resp = await concurrent_client.get(f"{API_PREFIX}/health")
            elapsed = time.perf_counter() - start
            assert resp.status_code == 200
            return elapsed

        results = await asyncio.gather(
            *[single_request() for _ in range(concurrency)]
        )

        max_ms = max(results) * 1000
        all_times_ms = [r * 1000 for r in results]
        assert max_ms < threshold_ms, (
            f"10 concurrent /health: max {max_ms:.1f}ms exceeds {threshold_ms}ms. "
            f"All times: {[f'{t:.1f}ms' for t in all_times_ms]}"
        )

    async def test_concurrent_post_events(
        self, concurrent_client: AsyncClient
    ):
        """5 concurrent POST /api/v1/events → all < 1s."""
        concurrency = 5
        threshold_ms = 1000

        async def single_request(idx: int):
            payload = {
                "event_type": "meeting",
                "source": "perf_test",
                "title": f"Concurrent Event {idx}",
                "raw_text": f"Concurrent test event number {idx}",
            }
            start = time.perf_counter()
            resp = await concurrent_client.post(
                f"{API_PREFIX}/events", json=payload
            )
            elapsed = time.perf_counter() - start
            assert resp.status_code == 201
            return elapsed

        results = await asyncio.gather(
            *[single_request(i) for i in range(concurrency)]
        )

        max_ms = max(results) * 1000
        all_times_ms = [r * 1000 for r in results]
        assert max_ms < threshold_ms, (
            f"5 concurrent POST /events: max {max_ms:.1f}ms exceeds {threshold_ms}ms. "
            f"All times: {[f'{t:.1f}ms' for t in all_times_ms]}"
        )

    async def test_concurrent_get_entities(
        self, concurrent_client: AsyncClient, session_factory
    ):
        """10 concurrent GET /api/v1/entities → all < 500ms."""
        # Seed data before concurrent requests
        async with session_factory() as session:
            await seed_entities(session, 50)

        concurrency = 10
        threshold_ms = 500

        async def single_request():
            start = time.perf_counter()
            resp = await concurrent_client.get(f"{API_PREFIX}/entities?limit=50")
            elapsed = time.perf_counter() - start
            assert resp.status_code == 200
            return elapsed

        results = await asyncio.gather(
            *[single_request() for _ in range(concurrency)]
        )

        max_ms = max(results) * 1000
        all_times_ms = [r * 1000 for r in results]
        assert max_ms < threshold_ms, (
            f"10 concurrent GET /entities: max {max_ms:.1f}ms exceeds {threshold_ms}ms. "
            f"All times: {[f'{t:.1f}ms' for t in all_times_ms]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# D. Memory and Resource
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryAndResource:
    """D. Memory and resource usage tests."""

    async def test_memory_growth_50_events(self, client: AsyncClient):
        """Memory growth after creating 50 events → < 50MB.

        Uses tracemalloc to measure Python-level allocation growth.
        """
        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        payload = {
            "event_type": "meeting",
            "source": "perf_test",
            "title": "Memory Test Event",
            "raw_text": "Memory test event content for baseline measurement.",
        }

        for i in range(50):
            payload["title"] = f"Memory Test Event {i}"
            resp = await client.post(f"{API_PREFIX}/events", json=payload)
            assert resp.status_code == 201

        gc.collect()
        snapshot_after = tracemalloc.take_snapshot()

        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth_bytes = sum(
            stat.size_diff for stat in stats if stat.size_diff > 0
        )
        tracemalloc.stop()

        growth_mb = total_growth_bytes / (1024 * 1024)
        assert growth_mb < 50, (
            f"Memory growth after 50 events: {growth_mb:.1f}MB exceeds 50MB threshold"
        )

    async def test_large_response_size(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Response size for 100 events list → < 500KB."""
        await seed_events(db_session, 100)

        resp = await client.get(f"{API_PREFIX}/events?limit=100")
        assert resp.status_code == 200

        response_size_bytes = len(resp.content)
        response_size_kb = response_size_bytes / 1024

        assert response_size_kb < 500, (
            f"Response size for 100 events: {response_size_kb:.1f}KB exceeds 500KB threshold"
        )

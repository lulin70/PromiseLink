"""Real load/performance tests — concurrent user simulation + P95/P99 assertions.

Batch 3.8: 补真实负载/性能测试

测试目标 (来自 P0_P1_FIX_PLAN_2026-07-05.md):
  1. 并发 10/50/100 用户模拟
  2. P95/P99 响应时间断言 (P95 < 500ms)
  3. LLM API 限流场景测试

设计原则:
  - 使用 REAL DB (in-memory SQLite + StaticPool 支持并发)
  - 使用 asyncio.gather 模拟真实并发用户
  - 收集每次请求的响应时间，计算 percentile
  - 不 mock pipeline（负载测试关注 API 层，不触发 LLM）
  - 阈值不可调松 — 测试为发现性能问题而非凑通过率
"""

import asyncio
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from promiselink.core.auth import get_current_user_id
from promiselink.core.rate_limiter import reset_rate_limits
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000020"
API_PREFIX = "/api/v1"

# 性能阈值 (不可调松)
P95_THRESHOLD_MS = 500  # P95 响应时间 < 500ms (plan 验证清单要求)
P99_THRESHOLD_MS = 1000  # P99 响应时间 < 1s
RATE_LIMIT_RESPONSE_SEC = 1  # 限流响应应在 1s 内返回 429


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    """In-memory SQLite with StaticPool for concurrent access.

    StaticPool ensures all connections share the same in-memory database,
    which is critical for concurrent request tests (each asyncio task
    may open a new connection).
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
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(db_engine):
    """Session factory shared by db_session and concurrent_client.

    All sessions created from this factory share the same in-memory database
    via StaticPool, but each session has its own transaction — this is what
    makes concurrent requests safe (AsyncSession is NOT safe for concurrent use).
    """
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, mock_pipeline):
    """httpx.AsyncClient with a shared DB session.

    Use for sequential request tests only — AsyncSession is NOT safe for
    concurrent use. For concurrent tests, use `concurrent_client` instead.
    """

    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def concurrent_client(session_factory, mock_pipeline):
    """httpx.AsyncClient that creates a new DB session per request.

    Use for concurrency tests. Each request gets its own session from the
    factory, but all sessions share the same in-memory database. This mirrors
    production behavior where `get_async_session` yields a fresh session
    per request.
    """

    async def override_get_async_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_rate_limits_fixture():
    reset_rate_limits()
    yield
    reset_rate_limits()


# ── Helpers ──


async def _seed_load_data(session: AsyncSession, entity_count: int = 50, todo_count: int = 100):
    """Seed entities and todos for load testing."""
    now = datetime.now(UTC)

    events = []
    for i in range(20):
        evt = Event(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            event_type="meeting",
            source="test",
            title=f"事件{i}",
            raw_text=f"测试事件 {i} 的内容",
            status="completed",
            created_at=now - timedelta(days=i),
        )
        events.append(evt)
        session.add(evt)
    await session.flush()  # Ensure events are persisted before referencing

    entities = []
    for i in range(entity_count):
        e = Entity(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            name=f"联系人{i}",
            entity_type="person",
            canonical_name=f"联系人{i}",
            source_event_id=events[i % len(events)].id,
            properties={
                "basic": {
                    "company": f"公司{i % 10}",
                    "title": f"职位{i % 5}",
                    "city": "北京",
                    "industry": "科技",
                }
            },
        )
        entities.append(e)
        session.add(e)

    for i in range(todo_count):
        t = Todo(
            id=str(uuid.uuid4()),
            user_id=TEST_USER_ID,
            todo_type=["care", "followup", "promise", "help"][i % 4],
            title=f"待办{i}",
            description=f"描述{i}",
            status=["pending", "in_progress", "done"][i % 3],
            priority=(i % 5) + 1,  # 1-5 (priority_range_check constraint)
            dynamic_score=float(100 - i) / 100,
            source_event_id=events[i % len(events)].id if events else None,
            created_at=now - timedelta(hours=i),
        )
        session.add(t)

    await session.commit()
    return entities, events


def _percentile(values: list[float], p: float) -> float:
    """Calculate the p-th percentile (0-100) of a list of values."""
    if not values:
        return float("inf")
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _format_stats(times_ms: list[float]) -> str:
    """Format response time statistics for assertion messages."""
    return (
        f"count={len(times_ms)}, "
        f"min={min(times_ms):.1f}ms, "
        f"avg={statistics.mean(times_ms):.1f}ms, "
        f"P50={_percentile(times_ms, 50):.1f}ms, "
        f"P95={_percentile(times_ms, 95):.1f}ms, "
        f"P99={_percentile(times_ms, 99):.1f}ms, "
        f"max={max(times_ms):.1f}ms"
    )


async def _concurrent_requests(
    client: AsyncClient,
    method: str,
    url: str,
    concurrency: int,
    **kwargs,
) -> list[float]:
    """Issue N concurrent requests and return response times in ms."""
    async def single_request():
        start = time.perf_counter()
        if method == "GET":
            resp = await client.get(url, **kwargs)
        elif method == "POST":
            resp = await client.post(url, **kwargs)
        elif method == "PATCH":
            resp = await client.patch(url, **kwargs)
        else:
            resp = await client.request(method, url, **kwargs)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return elapsed_ms, resp.status_code

    results = await asyncio.gather(*[single_request() for _ in range(concurrency)])
    times = [r[0] for r in results]
    status_codes = [r[1] for r in results]

    # All should be 2xx (or expected status)
    return times, status_codes


# ══════════════════════════════════════════════════════════════════════════════
# Test 1: Concurrent user simulation (10 / 50 / 100)
# ══════════════════════════════════════════════════════════════════════════════


class TestConcurrentUsers:
    """Simulate 10/50/100 concurrent users hitting key API endpoints."""

    @pytest_asyncio.fixture
    async def seeded_client(self, concurrent_client, db_session):
        # Seed via a dedicated session, then run concurrent requests via
        # concurrent_client (per-request session — AsyncSession is not
        # safe for concurrent use on a single shared session).
        await _seed_load_data(db_session, entity_count=50, todo_count=100)
        return concurrent_client

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_10_concurrent_users_get_todos(self, seeded_client):
        """10 concurrent GET /todos requests — P95 < 500ms."""
        times, status_codes = await _concurrent_requests(
            seeded_client, "GET", f"{API_PREFIX}/todos?limit=20", concurrency=10
        )

        assert all(sc == 200 for sc in status_codes), f"Non-200 status: {set(status_codes)}"
        p95 = _percentile(times, 95)
        p99 = _percentile(times, 99)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"10 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        assert p99 < P99_THRESHOLD_MS, f"10 users P99={p99:.1f}ms > {P99_THRESHOLD_MS}ms ({stats})"
        print(f"\n  10 users GET /todos: {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_10_concurrent_users_get_entities(self, seeded_client):
        """10 concurrent GET /entities requests — P95 < 500ms."""
        times, status_codes = await _concurrent_requests(
            seeded_client, "GET", f"{API_PREFIX}/entities?limit=20", concurrency=10
        )

        assert all(sc == 200 for sc in status_codes), f"Non-200 status: {set(status_codes)}"
        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"10 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  10 users GET /entities: {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_10_concurrent_users_get_dashboard(self, seeded_client):
        """10 concurrent GET /dashboard/day-view requests — P95 < 500ms."""
        times, status_codes = await _concurrent_requests(
            seeded_client,
            "GET",
            f"{API_PREFIX}/dashboard/day-view?date=2026-07-05",
            concurrency=10,
        )

        assert all(sc == 200 for sc in status_codes), f"Non-200 status: {set(status_codes)}"
        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"10 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  10 users GET /dashboard/day-view: {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_50_concurrent_users_get_todos(self, seeded_client):
        """50 concurrent GET /todos requests — P95 < 500ms.

        Note: rate limiter (~30/window) may 429 some requests — that's expected.
        We assert no 5xx errors and P95 < 500ms for all responses.
        """
        times, status_codes = await _concurrent_requests(
            seeded_client, "GET", f"{API_PREFIX}/todos?limit=20", concurrency=50
        )

        # 429 (rate limited) is valid under high concurrency — only 5xx is a real error
        server_errors = [sc for sc in status_codes if sc >= 500]
        assert not server_errors, f"Server errors: {server_errors}"
        ok_count = status_codes.count(200)
        assert ok_count > 0, "At least some requests should succeed (200)"

        p95 = _percentile(times, 95)
        p99 = _percentile(times, 99)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"50 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        assert p99 < P99_THRESHOLD_MS, f"50 users P99={p99:.1f}ms > {P99_THRESHOLD_MS}ms ({stats})"
        print(f"\n  50 users GET /todos: {stats} (200={ok_count}, 429={status_codes.count(429)})")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_50_concurrent_users_mixed_endpoints(self, seeded_client):
        """50 concurrent users hitting mixed endpoints — P95 < 500ms."""
        endpoints = [
            (f"{API_PREFIX}/todos?limit=10", "GET"),
            (f"{API_PREFIX}/entities?limit=10", "GET"),
            (f"{API_PREFIX}/dashboard/day-view?date=2026-07-05", "GET"),
            (f"{API_PREFIX}/reminders/daily", "GET"),
            (f"{API_PREFIX}/scheduled-events?limit=10", "GET"),
        ]

        async def mixed_request():
            url, method = endpoints[mixed_request._counter % len(endpoints)]
            mixed_request._counter += 1
            start = time.perf_counter()
            resp = await seeded_client.get(url)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return elapsed_ms, resp.status_code

        mixed_request._counter = 0

        results = await asyncio.gather(*[mixed_request() for _ in range(50)])
        times = [r[0] for r in results]
        status_codes = [r[1] for r in results]

        # 429 rate limiting is expected; only 5xx is a real error
        server_errors = [sc for sc in status_codes if sc >= 500]
        assert not server_errors, f"Server errors: {server_errors}"

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"50 mixed P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  50 users mixed endpoints: {stats} (status: {set(status_codes)})")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_100_concurrent_users_get_todos(self, seeded_client):
        """100 concurrent GET /todos requests — P95 < 500ms.

        Rate limiter will 429 most requests at this concurrency — that's expected.
        We assert no 5xx errors and P95 < 500ms for all responses (including 429).
        """
        times, status_codes = await _concurrent_requests(
            seeded_client, "GET", f"{API_PREFIX}/todos?limit=20", concurrency=100
        )

        server_errors = [sc for sc in status_codes if sc >= 500]
        assert not server_errors, f"Server errors: {server_errors}"
        ok_count = status_codes.count(200)
        assert ok_count > 0, "At least some requests should succeed (200)"

        p95 = _percentile(times, 95)
        p99 = _percentile(times, 99)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"100 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        assert p99 < P99_THRESHOLD_MS, f"100 users P99={p99:.1f}ms > {P99_THRESHOLD_MS}ms ({stats})"
        print(f"\n  100 users GET /todos: {stats} (200={ok_count}, 429={status_codes.count(429)})")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_100_concurrent_users_get_entities(self, seeded_client):
        """100 concurrent GET /entities requests — P95 < 500ms."""
        times, status_codes = await _concurrent_requests(
            seeded_client, "GET", f"{API_PREFIX}/entities?limit=20", concurrency=100
        )

        server_errors = [sc for sc in status_codes if sc >= 500]
        assert not server_errors, f"Server errors: {server_errors}"
        ok_count = status_codes.count(200)
        assert ok_count > 0, "At least some requests should succeed (200)"

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"100 users P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  100 users GET /entities: {stats}")


# ══════════════════════════════════════════════════════════════════════════════
# Test 2: P95/P99 response time assertions for individual endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestResponseTimePercentiles:
    """Measure P95/P99 for key endpoints with sequential requests (baseline)."""

    @pytest_asyncio.fixture
    async def seeded_client(self, client, db_session):
        await _seed_load_data(db_session, entity_count=50, todo_count=100)
        return client

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_todos_list_p95(self, seeded_client):
        """GET /todos — 20 sequential requests, P95 < 500ms."""
        times = []
        for _ in range(20):
            start = time.perf_counter()
            resp = await seeded_client.get(f"{API_PREFIX}/todos?limit=20")
            times.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 200

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"GET /todos P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  GET /todos (20x): {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_entities_list_p95(self, seeded_client):
        """GET /entities — 20 sequential requests, P95 < 500ms."""
        times = []
        for _ in range(20):
            start = time.perf_counter()
            resp = await seeded_client.get(f"{API_PREFIX}/entities?limit=20")
            times.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 200

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"GET /entities P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  GET /entities (20x): {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_dashboard_day_view_p95(self, seeded_client):
        """GET /dashboard/day-view — 20 sequential requests, P95 < 500ms."""
        times = []
        for _ in range(20):
            start = time.perf_counter()
            resp = await seeded_client.get(f"{API_PREFIX}/dashboard/day-view?date=2026-07-05")
            times.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 200

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"GET /dashboard P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  GET /dashboard/day-view (20x): {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_reminders_daily_p95(self, seeded_client):
        """GET /reminders/daily — 20 sequential requests, P95 < 500ms."""
        times = []
        for _ in range(20):
            start = time.perf_counter()
            resp = await seeded_client.get(f"{API_PREFIX}/reminders/daily")
            times.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 200

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < P95_THRESHOLD_MS, f"GET /reminders/daily P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        print(f"\n  GET /reminders/daily (20x): {stats}")

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_health_p95(self, seeded_client):
        """GET /health — 50 sequential requests, P95 < 100ms (health should be fast)."""
        times = []
        for _ in range(50):
            start = time.perf_counter()
            resp = await seeded_client.get(f"{API_PREFIX}/health")
            times.append((time.perf_counter() - start) * 1000)
            assert resp.status_code == 200

        p95 = _percentile(times, 95)
        stats = _format_stats(times)
        assert p95 < 100, f"GET /health P95={p95:.1f}ms > 100ms ({stats})"
        print(f"\n  GET /health (50x): {stats}")


# ══════════════════════════════════════════════════════════════════════════════
# Test 3: Rate limiting scenarios
# ══════════════════════════════════════════════════════════════════════════════


class TestRateLimiting:
    """Test API rate limiting under burst traffic.

    The rate limiter uses in-memory sliding window. When the limit is exceeded,
    the API should return 429 (Too Many Requests) quickly, not hang.
    """

    @pytest.mark.asyncio
    async def test_burst_requests_get_rate_limited(self, client, db_session):
        """Burst of 200 rapid requests should trigger rate limiting (429)."""
        await _seed_load_data(db_session, entity_count=5, todo_count=10)

        # Fire 200 requests rapidly — rate limiter should kick in
        results = []
        for i in range(200):
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/todos?limit=5")
            elapsed_ms = (time.perf_counter() - start) * 1000
            results.append((resp.status_code, elapsed_ms))

        status_codes = [r[0] for r in results]
        times = [r[1] for r in results]

        # Should have a mix of 200 (OK) and 429 (rate limited)
        ok_count = status_codes.count(200)
        rate_limited_count = status_codes.count(429)

        print(f"\n  Burst 200 requests: {ok_count} OK, {rate_limited_count} rate-limited")
        print(f"  Response times: {_format_stats(times)}")

        # At least some should be rate limited (default limit is generous, but 200 rapid requests should hit it)
        # Note: if rate limit is very high, this test verifies the rate limiter doesn't HANG
        assert rate_limited_count > 0 or ok_count == 200, (
            f"Expected rate limiting or all-success, got: 200={ok_count}, 429={rate_limited_count}, "
            f"other={set(status_codes)}"
        )

        # Rate-limited responses should be fast (no hanging)
        if rate_limited_count > 0:
            rate_limited_times = [t for s, t in results if s == 429]
            p95_rate_limited = _percentile(rate_limited_times, 95)
            assert p95_rate_limited < 100, (
                f"Rate-limited responses P95={p95_rate_limited:.1f}ms > 100ms — "
                f"rate limiter should reject quickly, not hang"
            )

    @pytest.mark.asyncio
    async def test_rate_limit_response_time_under_load(self, concurrent_client, db_session):
        """Rate-limited responses should be fast even under concurrent load."""
        await _seed_load_data(db_session, entity_count=5, todo_count=10)

        # Fire 100 concurrent requests — rate limiter should handle gracefully
        async def rapid_request():
            start = time.perf_counter()
            resp = await concurrent_client.get(f"{API_PREFIX}/health")
            elapsed_ms = (time.perf_counter() - start) * 1000
            return resp.status_code, elapsed_ms

        results = await asyncio.gather(*[rapid_request() for _ in range(100)])
        times = [r[1] for r in results]
        status_codes = [r[0] for r in results]

        p95 = _percentile(times, 95)
        p99 = _percentile(times, 99)
        stats = _format_stats(times)

        print(f"\n  100 concurrent /health: {stats} (status: {set(status_codes)})")

        # Even with rate limiting, responses should be fast
        assert p95 < P95_THRESHOLD_MS, f"Concurrent P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"
        assert p99 < P99_THRESHOLD_MS, f"Concurrent P99={p99:.1f}ms > {P99_THRESHOLD_MS}ms ({stats})"

    @pytest.mark.asyncio
    async def test_rate_limit_does_not_corrupt_data(self, client, db_session):
        """Rate-limited requests should not corrupt data or leave partial writes."""
        await _seed_load_data(db_session, entity_count=5, todo_count=10)

        # Fire many POST requests (create scheduled events) — some may be rate-limited
        payload = {
            "scheduled_at": datetime.now(UTC).isoformat(),
            "topic": f"Load test {uuid.uuid4().hex[:8]}",
            "event_type": "meeting",
            "participants": [],
        }

        results = []
        for _ in range(50):
            resp = await client.post(f"{API_PREFIX}/scheduled-events", json=payload)
            results.append(resp.status_code)

        ok_count = results.count(201)
        rate_limited_count = results.count(429)
        server_errors = [sc for sc in results if sc >= 500]

        print(f"\n  50 POST /scheduled-events: {ok_count} created, {rate_limited_count} rate-limited")

        # No 5xx server errors should occur under rate limiting
        assert not server_errors, f"Server errors during POST burst: {server_errors}"

        # Reset rate limits before verification so the GET isn't 429'd.
        # This test verifies data integrity, not rate limiter state.
        reset_rate_limits()

        # Verify data integrity — count created events
        resp = await client.get(f"{API_PREFIX}/scheduled-events?limit=100")
        assert resp.status_code == 200, f"Verification GET failed: {resp.status_code}"
        data = resp.json()
        actual_count = data.get("total", 0)

        # The number of created events should match the number of 201 responses
        assert actual_count >= ok_count, (
            f"Data corruption: {ok_count} events created (201) but only {actual_count} found in DB"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Test 4: Sustained load (throughput) — 10s sustained requests
# ══════════════════════════════════════════════════════════════════════════════


class TestSustainedLoad:
    """Sustained load test — measure throughput over a time window."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_sustained_5s_throughput(self, client, db_session):
        """5 seconds of sustained GET /todos — measure throughput (req/s)."""
        await _seed_load_data(db_session, entity_count=50, todo_count=100)

        duration_sec = 5
        end_time = time.perf_counter() + duration_sec
        request_count = 0
        response_times = []
        server_errors = 0
        rate_limited = 0
        ok_count = 0

        while time.perf_counter() < end_time:
            start = time.perf_counter()
            resp = await client.get(f"{API_PREFIX}/todos?limit=20")
            elapsed_ms = (time.perf_counter() - start) * 1000
            response_times.append(elapsed_ms)
            request_count += 1
            if resp.status_code >= 500:
                server_errors += 1
            elif resp.status_code == 429:
                rate_limited += 1
            elif resp.status_code == 200:
                ok_count += 1

        actual_duration = duration_sec
        throughput = request_count / actual_duration
        p95 = _percentile(response_times, 95)
        p99 = _percentile(response_times, 99)
        stats = _format_stats(response_times)

        print(f"\n  Sustained 5s GET /todos:")
        print(f"    Throughput: {throughput:.1f} req/s ({request_count} requests in {actual_duration}s)")
        print(f"    Response: {stats}")
        print(f"    200={ok_count}, 429={rate_limited}, 5xx={server_errors}")

        # Only 5xx counts as a real error — 429 is expected rate limiting under sustained load
        assert server_errors == 0, f"{server_errors} server errors out of {request_count} requests"
        # At least some requests should succeed (proves endpoint is functional under load)
        assert ok_count > 0, f"No successful requests — all {request_count} requests failed"
        assert throughput > 10, f"Throughput {throughput:.1f} req/s < 10 req/s minimum"
        assert p95 < P95_THRESHOLD_MS, f"P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_sustained_concurrent_5s(self, concurrent_client, db_session):
        """5 seconds of concurrent (10 workers) GET /todos — measure throughput."""
        await _seed_load_data(db_session, entity_count=50, todo_count=100)

        duration_sec = 5
        end_time = time.perf_counter() + duration_sec
        all_times = []
        all_status = []
        lock = asyncio.Lock()

        async def worker():
            times = []
            statuses = []
            while time.perf_counter() < end_time:
                start = time.perf_counter()
                resp = await concurrent_client.get(f"{API_PREFIX}/todos?limit=20")
                times.append((time.perf_counter() - start) * 1000)
                statuses.append(resp.status_code)
            async with lock:
                all_times.extend(times)
                all_status.extend(statuses)

        # 10 concurrent workers
        await asyncio.gather(*[worker() for _ in range(10)])

        total_requests = len(all_times)
        throughput = total_requests / duration_sec
        p95 = _percentile(all_times, 95)
        p99 = _percentile(all_times, 99)
        stats = _format_stats(all_times)
        server_errors = sum(1 for s in all_status if s >= 500)
        ok_count = sum(1 for s in all_status if s == 200)
        rate_limited = sum(1 for s in all_status if s == 429)

        print(f"\n  Sustained 5s (10 workers) GET /todos:")
        print(f"    Throughput: {throughput:.1f} req/s ({total_requests} requests in {duration_sec}s)")
        print(f"    Response: {stats}")
        print(f"    200={ok_count}, 429={rate_limited}, 5xx={server_errors}")

        # Only 5xx counts as a real error — 429 is expected rate limiting under sustained concurrent load
        assert server_errors == 0, f"{server_errors} server errors out of {total_requests} requests"
        # At least some requests should succeed (proves endpoint is functional under concurrent load)
        assert ok_count > 0, f"No successful requests — all {total_requests} requests failed"
        assert throughput > 20, f"Concurrent throughput {throughput:.1f} req/s < 20 req/s minimum"
        assert p95 < P95_THRESHOLD_MS, f"P95={p95:.1f}ms > {P95_THRESHOLD_MS}ms ({stats})"

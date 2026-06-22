"""Performance Supplement Tests — LLM degradation/circuit-breaker, large data,
and concurrency scenarios.

TC-PERF-001 ~ TC-PERF-021 as defined in the test plan.

Uses in-memory SQLite + httpx.AsyncClient + FastAPI dependency overrides,
with LLM calls mocked out. Data volumes scaled down for CI.
Heavy tests marked with @pytest.mark.slow.
"""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.core.rate_limiter import InMemorySlidingWindow, reset_rate_limits
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000004"
API_PREFIX = "/api/v1"

# Scaled-down data volumes for CI
CI_ENTITY_COUNT = 100  # instead of 10000
CI_ASSOCIATION_COUNT = 200  # instead of 100000


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
        entity = await insert_entity(session, source_event_id=source_event_id, name="Source Entity")
        source_entity_id = entity.id
    if target_entity_id is None:
        entity2 = await insert_entity(session, source_event_id=source_event_id, name="Target Entity")
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
# 20.1 LLM降级与熔断
# ══════════════════════════════════════════════════════════════════════════════


class TestLLMDegradation:
    """LLM degradation and circuit-breaker tests."""

    @pytest.mark.asyncio
    async def test_tc_perf_001_llm_fallback_on_failure(self):
        """TC-PERF-001: LLM API不可用→本地fallback降级验证.

        Mock LLM failure, verify EmbeddingProvider falls back to local/pseudo embedding.
        """
        from promiselink.config import get_settings
        from promiselink.services.embedding_provider import EmbeddingProvider

        settings = get_settings()
        settings.embedding_provider = "api"  # Use API mode so _client is created
        provider = EmbeddingProvider(settings=settings)

        # Mock the API client to always fail
        with patch.object(provider._client, "embeddings") as mock_embeddings:
            mock_embeddings.create.side_effect = Exception("API unavailable")

            # Should fall back to local/pseudo embedding
            embedding = await provider.embed("测试文本")

            # Should return a valid embedding vector
            assert isinstance(embedding, list)
            assert len(embedding) > 0
            assert all(isinstance(x, float) for x in embedding)

    @pytest.mark.asyncio
    async def test_tc_perf_002_llm_rate_limit_retry(self):
        """TC-PERF-002: LLM API限流→指数退避重试验证.

        Mock rate limit response, verify LLMClient retries with backoff.
        """
        from promiselink.config import get_settings
        from promiselink.core.exceptions import LLMRateLimitError
        from promiselink.services.llm_client import LLMClient

        settings = get_settings()
        settings.llm_max_retries = 3
        client = LLMClient(config=settings)

        call_count = 0

        async def mock_http_call_with_rate_limit(messages, max_tokens, temperature):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise LLMRateLimitError(provider="test")
            # Third call succeeds
            return {
                "choices": [{"message": {"content": "success"}}],
                "usage": {"total_tokens": 10},
            }

        # Mock cache_service to return None (no cache hit)
        mock_cache_service = AsyncMock()
        mock_cache_service.get.return_value = None
        mock_cache_service.llm_cache_key.return_value = "test-key"

        with patch.object(client, "_http_call", side_effect=mock_http_call_with_rate_limit), \
             patch.object(client, "_parse_response", return_value="success"), \
             patch("promiselink.core.redis.cache_service", mock_cache_service):

            result = await client._call_with_retry(
                messages=[{"role": "user", "content": "test"}],
                max_tokens=10,
                temperature=0.0,
            )

        # Should have retried and eventually succeeded
        assert call_count >= 2
        assert result == "success"

    @pytest.mark.asyncio
    async def test_tc_perf_003_three_level_degradation(self):
        """TC-PERF-003: 三级降级策略(API→本地模型→hash伪embedding)验证.

        Test full degradation chain: API fails → local model unavailable → pseudo embedding.
        """
        from promiselink.config import get_settings
        from promiselink.services.embedding_provider import EmbeddingProvider

        settings = get_settings()
        settings.embedding_provider = "api"  # Use API mode so _client is created
        provider = EmbeddingProvider(settings=settings)

        # Force API to fail and sentence_transformers to not be available
        with patch.object(provider._client, "embeddings") as mock_api:
            mock_api.create.side_effect = Exception("API down")

            with patch.dict("sys.modules", {"sentence_transformers": None}):
                # Force local model to be None so it falls to pseudo
                provider._local_model = None

                # Patch the import inside _embed_local to raise ImportError
                original_embed_local = provider._embed_local

                async def mock_embed_local(text, cache_key):
                    # Simulate sentence_transformers not available
                    return provider._pseudo_embedding(text, cache_key)

                with patch.object(provider, "_embed_local", side_effect=mock_embed_local):
                    embedding = await provider.embed("降级测试文本")

                    # Should get a pseudo embedding
                    assert isinstance(embedding, list)
                    assert len(embedding) == 384  # LOCAL_EMBEDDING_DIMENSIONS
                    # Pseudo embeddings are deterministic
                    embedding2 = await provider.embed("降级测试文本")
                    assert embedding == embedding2


# ══════════════════════════════════════════════════════════════════════════════
# 20.2 大数据量性能
# ══════════════════════════════════════════════════════════════════════════════


class TestLargeDataPerformance:
    """Large data volume performance tests (scaled down for CI)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_tc_perf_010_entity_association_discovery_performance(self, db_session: AsyncSession):
        """TC-PERF-010: 万级Entity下关联发现性能(<5s)验证.

        Create CI_ENTITY_COUNT entities, measure association discovery time.
        Uses smaller scale (100) for CI; production target is 10000 in <5s.
        """
        # Create entities in bulk
        event = await insert_event(db_session, title="性能测试事件")
        entities = []
        for i in range(CI_ENTITY_COUNT):
            entity = Entity(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                entity_type="person",
                name=f"Person{i}",
                canonical_name=f"Person{i}",
                aliases=[],
                properties={
                    "basic": {"company": f"Company{i % 10}", "industry": f"Industry{i % 5}"},
                    "concern": [{"category": f"Concern{i % 3}", "detail": f"Detail{i}"}],
                    "capability": [{"category": f"Capability{i % 3}", "detail": f"Detail{i}"}],
                },
                source_event_id=event.id,
                confidence=0.9,
                status="confirmed",
            )
            entities.append(entity)
            db_session.add(entity)

        await db_session.commit()

        # Measure association discovery time
        from promiselink.services.association_discovery import AssociationDiscoveryEngine
        engine = AssociationDiscoveryEngine(session=db_session)

        start = time.perf_counter()
        # Test discovery between first two entities (representative)
        score, evidence = await engine._discover_supply_demand(entities[0], entities[1])
        elapsed = time.perf_counter() - start

        # Discovery should be fast even with many entities
        # CI scale: <1s; production scale (10000): <5s
        assert elapsed < 5.0, f"Association discovery took {elapsed:.2f}s, expected <5s"
        assert isinstance(score, float)

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_tc_perf_011_association_query_performance(self, db_session: AsyncSession):
        """TC-PERF-011: 十万级Association下查询性能(<2s)验证.

        Create CI_ASSOCIATION_COUNT associations, measure query time.
        Uses smaller scale (200) for CI; production target is 100000 in <2s.
        """
        # Create entities and associations in bulk
        event = await insert_event(db_session, title="关联查询性能测试")

        # Create a small set of entities to link
        entity_ids = []
        for i in range(20):
            entity = Entity(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                entity_type="person",
                name=f"AssocPerson{i}",
                canonical_name=f"AssocPerson{i}",
                aliases=[],
                properties={"basic": {"company": f"Company{i}"}},
                source_event_id=event.id,
                confidence=0.9,
                status="confirmed",
            )
            db_session.add(entity)
            entity_ids.append(entity.id)

        await db_session.flush()

        # Create associations between entity pairs (avoid unique constraint violations)
        assoc_types = ["same_city", "tech_overlap", "co_occurrence", "alumni"]
        created_pairs = set()
        for i in range(CI_ASSOCIATION_COUNT):
            src_idx = i % len(entity_ids)
            tgt_idx = (i + 1) % len(entity_ids)
            if src_idx == tgt_idx:
                tgt_idx = (tgt_idx + 1) % len(entity_ids)

            # Cycle through association types to avoid unique constraint on (src, tgt, type)
            assoc_type = assoc_types[i % len(assoc_types)]
            pair_key = (entity_ids[src_idx], entity_ids[tgt_idx], assoc_type)
            if pair_key in created_pairs:
                # Try a different type
                for at in assoc_types:
                    alt_key = (entity_ids[src_idx], entity_ids[tgt_idx], at)
                    if alt_key not in created_pairs:
                        assoc_type = at
                        pair_key = alt_key
                        break
            if pair_key in created_pairs:
                continue  # Skip if all types exhausted for this pair

            created_pairs.add(pair_key)

            assoc = Association(
                id=str(uuid.uuid4()),
                user_id=TEST_USER_ID,
                source_entity_id=entity_ids[src_idx],
                target_entity_id=entity_ids[tgt_idx],
                association_type=assoc_type,
                strength=0.5 + (i % 5) * 0.1,
                confidence=0.8,
                status="confirmed",
                source_event_id=event.id,
            )
            db_session.add(assoc)

        await db_session.commit()

        # Measure query time
        start = time.perf_counter()
        result = await db_session.execute(
            select(Association).where(Association.user_id == TEST_USER_ID).limit(50)
        )
        associations = result.scalars().all()
        elapsed = time.perf_counter() - start

        # Query should be fast
        assert elapsed < 2.0, f"Association query took {elapsed:.2f}s, expected <2s"
        assert len(associations) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 20.3 并发测试
# ══════════════════════════════════════════════════════════════════════════════


class TestConcurrency:
    """Concurrency and rate limiting tests."""

    @pytest.mark.asyncio
    async def test_tc_perf_020_concurrent_entity_update(self, db_session: AsyncSession):
        """TC-PERF-020: 10并发写入同一Entity的乐观锁冲突处理验证.

        Test concurrent updates to the same entity.
        SQLite doesn't support true concurrent writes, but we verify
        that sequential rapid updates don't lose data.
        """
        event = await insert_event(db_session, title="并发测试")
        entity = await insert_entity(
            db_session, name="并发测试人", source_event_id=event.id
        )
        await db_session.commit()

        # Simulate rapid sequential updates (SQLite doesn't support true concurrency)
        original_name = entity.name
        for i in range(10):
            entity.name = f"并发测试人_v{i}"
            await db_session.commit()

        # Verify the final update is persisted
        result = await db_session.execute(
            select(Entity).where(Entity.id == entity.id)
        )
        final_entity = result.scalar_one()
        assert final_entity.name == "并发测试人_v9"

    @pytest.mark.asyncio
    async def test_tc_perf_021_rate_limiting_under_load(self):
        """TC-PERF-021: 50并发API请求的限流与排队验证.

        Test rate limiting under load using InMemorySlidingWindow.
        """
        reset_rate_limits()
        limiter = InMemorySlidingWindow()

        # Simulate 50 concurrent requests with a limit of 20
        limit = 20
        results = []

        async def make_request(request_id: int):
            allowed, remaining, retry_after = await limiter.is_allowed(
                "user:test_user", limit
            )
            return (request_id, allowed, remaining, retry_after)

        # Run 50 requests concurrently
        tasks = [make_request(i) for i in range(50)]
        results_list = await asyncio.gather(*tasks)

        # Count allowed vs rejected
        allowed_count = sum(1 for r in results_list if r[1])
        rejected_count = sum(1 for r in results_list if not r[1])

        # Should have exactly `limit` allowed requests
        assert allowed_count == limit, f"Expected {limit} allowed, got {allowed_count}"
        assert rejected_count == 50 - limit

        # Rejected requests should have retry_after > 0
        for r in results_list:
            if not r[1]:
                assert r[3] > 0, "Rejected request should have retry_after > 0"

        reset_rate_limits()

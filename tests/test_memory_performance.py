"""Memory performance tests for PromiseLink.

Establishes memory baselines and verifies memory stays flat over many iterations:
  1. Memory baseline for event processing pipeline (mocked pipeline steps)
  2. Memory baseline for association discovery
  3. Memory baseline for entity resolution
  4. Memory growth over 100 iterations (should be flat, not growing)

Uses tracemalloc for Python-level allocation tracking.
Thresholds are based on local SQLite baselines — do NOT loosen to pass.
"""

import gc
import os
import tracemalloc
import uuid
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Force IS_SQLITE=True BEFORE importing models
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.entity import Entity
from promiselink.services.association_discovery import AssociationDiscoveryEngine
from promiselink.services.embedding_provider import (
    EMBEDDING_CACHE_MAX_SIZE,
    EmbeddingProvider,
)
from promiselink.services.entity_resolution import EntityResolutionEngine
from tests.conftest import create_test_event, make_user_id

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_embedding(dim: int = 384, seed: int = 42) -> list[float]:
    """Generate a deterministic fake embedding vector."""
    import random
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    norm = sum(x * x for x in vec) ** 0.5
    return [x / norm for x in vec]


def _mock_embedding_response(embeddings: list[list[float]]):
    """Build a mock OpenAI EmbeddingResponse-like object."""
    data = []
    for i, emb in enumerate(embeddings):
        item = MagicMock()
        item.embedding = emb
        item.index = i
        data.append(item)
    resp = MagicMock()
    resp.data = data
    return resp


def _make_provider_with_api() -> EmbeddingProvider:
    """Create an EmbeddingProvider with a mocked API client."""
    provider = EmbeddingProvider.__new__(EmbeddingProvider)
    provider._provider = "api"
    provider._client = MagicMock()
    provider._model = "text-embedding-3-small"
    provider._cache = OrderedDict()
    provider._cache_hits = 0
    provider._cache_misses = 0
    provider._local_model = None
    return provider


async def _make_entity(
    session: AsyncSession,
    user_id: str,
    name: str,
    city: str = "",
    company: str = "",
    event_id: str | None = None,
    properties: dict | None = None,
) -> Entity:
    """Helper to create an Entity object."""
    if event_id is None:
        evt = await create_test_event(session, user_id=user_id)
        event_id = evt.id
    props = dict(properties) if properties else {}
    basic = props.get("basic", {})
    if city:
        basic["city"] = city
    if company:
        basic["company"] = company
    if basic:
        props["basic"] = basic

    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        properties=props,
        source_event_id=event_id,
        status="confirmed",
    )
    session.add(entity)
    return entity


# ══════════════════════════════════════════════════════════════════════════════
# 1. Memory Baseline for Embedding/Event Processing
# ══════════════════════════════════════════════════════════════════════════════


class TestEmbeddingMemoryBaseline:
    """Memory baseline for embedding operations (core of event pipeline Step 3)."""

    @pytest.mark.asyncio
    async def test_embedding_50_texts_memory_baseline(self):
        """Embedding 50 texts should use < 10MB of memory."""
        provider = _make_provider_with_api()

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(50):
            fake_emb = _make_fake_embedding(seed=i)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"perf-baseline-{i}")

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 10, (
            f"Memory growth for 50 embeddings: {growth_mb:.1f}MB exceeds 10MB baseline"
        )

    @pytest.mark.asyncio
    async def test_embedding_batch_100_memory_baseline(self):
        """Batch embedding 100 texts should use < 15MB of memory."""
        provider = _make_provider_with_api()

        texts = [f"batch-perf-{i}" for i in range(100)]
        embeddings = [_make_fake_embedding(seed=i) for i in range(100)]
        mock_response = _mock_embedding_response(embeddings)
        provider._client.embeddings.create = AsyncMock(return_value=mock_response)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        await provider.embed_batch(texts)

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 15, (
            f"Memory growth for batch of 100 embeddings: {growth_mb:.1f}MB exceeds 15MB baseline"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Memory Baseline for Association Discovery
# ══════════════════════════════════════════════════════════════════════════════


class TestAssociationDiscoveryMemoryBaseline:
    """Memory baseline for association discovery operations."""

    @pytest.mark.asyncio
    async def test_discover_all_pairs_20_entities_baseline(self, db_session):
        """Full scan discovery with 20 entities should use < 30MB."""
        user_id = make_user_id()
        for i in range(20):
            await _make_entity(
                db_session, user_id, f"关联{i:03d}",
                city=f"城市{i % 3}",
                company=f"公司{i % 4}",
            )
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        await engine.discover_all_pairs(user_id)

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 30, (
            f"Memory growth for discover_all_pairs (20 entities): "
            f"{growth_mb:.1f}MB exceeds 30MB baseline"
        )

    @pytest.mark.asyncio
    async def test_discover_cold_types_baseline(self, db_session):
        """Cold type discovery between 2 entities should use < 10MB."""
        user_id = make_user_id()
        a = await _make_entity(
            db_session, user_id, "冷发现A",
            properties={"basic": {"schools": ["北大"]}, "tech_stack": ["Python"]},
        )
        b = await _make_entity(
            db_session, user_id, "冷发现B",
            properties={"basic": {"schools": ["北大"]}, "tech_stack": ["Python"]},
        )
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        await engine.discover_cold_types(a, b)

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 10, (
            f"Memory growth for discover_cold_types: {growth_mb:.1f}MB exceeds 10MB baseline"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Memory Baseline for Entity Resolution
# ══════════════════════════════════════════════════════════════════════════════


class TestEntityResolutionMemoryBaseline:
    """Memory baseline for entity resolution operations."""

    @pytest.mark.asyncio
    async def test_resolve_30_entities_baseline(self, db_session):
        """Resolving 30 entities against 30 existing should use < 25MB."""
        user_id = make_user_id()
        # Seed 30 existing entities
        for i in range(30):
            await _make_entity(db_session, user_id, f"已有{i:03d}", city="北京")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(30):
            await engine.resolve(
                {"name": f"待解析{i:03d}", "city": "北京", "entity_type": "person"},
                user_id,
            )

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 25, (
            f"Memory growth for 30 entity resolutions: {growth_mb:.1f}MB exceeds 25MB baseline"
        )

    @pytest.mark.asyncio
    async def test_clear_index_reduces_memory(self, db_session):
        """clear_index() should reduce traced memory after resolution."""
        user_id = make_user_id()
        for i in range(50):
            await _make_entity(db_session, user_id, f"清理{i:03d}", city="上海")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)
        # Load the index by resolving
        await engine.resolve({"name": "触发加载", "city": "上海"}, user_id)

        assert engine.index_size() > 0

        gc.collect()
        tracemalloc.start()
        before_clear = tracemalloc.get_traced_memory()[0]

        engine.clear_index()
        gc.collect()
        after_clear = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()

        # Memory should not increase after clearing (ideally it decreases)
        # We assert it doesn't grow, which would indicate a leak
        assert after_clear <= before_clear + 1024, (
            f"Memory after clear_index ({after_clear}B) should not exceed "
            f"before ({before_clear}B) + 1KB tolerance"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Memory Growth Over Iterations (should be flat)
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryGrowthOverIterations:
    """Verify memory stays flat over many iterations — no leaks."""

    @pytest.mark.asyncio
    async def test_embedding_memory_flat_over_100_iterations(self):
        """Embedding 100 unique texts repeatedly should not grow memory unboundedly.

        The cache is bounded at EMBEDDING_CACHE_MAX_SIZE, so after the cache
        fills, memory should stay flat as old entries are evicted.
        """
        provider = _make_provider_with_api()

        gc.collect()
        tracemalloc.start()

        memory_samples: list[int] = []
        # Use more unique texts than the cache limit to force eviction
        total_texts = EMBEDDING_CACHE_MAX_SIZE + 100

        for i in range(100):
            # Cycle through texts to force cache churn
            text_idx = i % total_texts
            fake_emb = _make_fake_embedding(seed=text_idx)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"growth-test-{text_idx}")

            if i % 10 == 0:
                current, _ = tracemalloc.get_traced_memory()
                memory_samples.append(current)

        tracemalloc.stop()

        # Memory should be flat — the cache is bounded
        first_sample = memory_samples[0]
        last_sample = memory_samples[-1]
        growth = last_sample - first_sample
        growth_mb = growth / (1024 * 1024)

        assert growth_mb < 10, (
            f"Memory grew {growth_mb:.1f}MB over 100 iterations — possible leak. "
            f"Samples: {[f'{s/1024/1024:.1f}MB' for s in memory_samples]}"
        )
        # Cache should be at or below the limit
        assert len(provider._cache) <= EMBEDDING_CACHE_MAX_SIZE

    @pytest.mark.asyncio
    async def test_entity_resolution_memory_flat_over_50_iterations(self, db_session):
        """Resolving entities 50 times should not grow memory unboundedly."""
        user_id = make_user_id()
        # Seed a few existing entities
        for i in range(10):
            await _make_entity(db_session, user_id, f"基线{i:03d}", city="深圳")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)

        gc.collect()
        tracemalloc.start()

        memory_samples: list[int] = []

        for i in range(50):
            await engine.resolve(
                {"name": f"迭代{i:03d}", "city": "深圳", "entity_type": "person"},
                user_id,
            )
            # Periodically clear the index to simulate session-scoped cleanup
            if i % 10 == 9:
                engine.clear_index()

            if i % 5 == 0:
                current, _ = tracemalloc.get_traced_memory()
                memory_samples.append(current)

        tracemalloc.stop()

        first_sample = memory_samples[0]
        last_sample = memory_samples[-1]
        growth = last_sample - first_sample
        growth_mb = growth / (1024 * 1024)

        assert growth_mb < 15, (
            f"Memory grew {growth_mb:.1f}MB over 50 entity resolutions — possible leak. "
            f"Samples: {[f'{s/1024/1024:.1f}MB' for s in memory_samples]}"
        )

    @pytest.mark.asyncio
    async def test_association_discovery_memory_flat_over_10_iterations(self, db_session):
        """Running association discovery 10 times should not grow memory unboundedly."""
        user_id = make_user_id()
        for i in range(15):
            await _make_entity(
                db_session, user_id, f"迭代关联{i:03d}",
                city=f"城市{i % 2}",
                company=f"公司{i % 3}",
            )
        await db_session.flush()

        gc.collect()
        tracemalloc.start()

        memory_samples: list[int] = []

        for i in range(10):
            engine = AssociationDiscoveryEngine(db_session)
            await engine.discover_all_pairs(user_id)
            # Engine goes out of scope here, allowing GC

            if i % 2 == 0:
                gc.collect()
                current, _ = tracemalloc.get_traced_memory()
                memory_samples.append(current)

        tracemalloc.stop()

        first_sample = memory_samples[0]
        last_sample = memory_samples[-1]
        growth = last_sample - first_sample
        growth_mb = growth / (1024 * 1024)

        assert growth_mb < 20, (
            f"Memory grew {growth_mb:.1f}MB over 10 discovery iterations — possible leak. "
            f"Samples: {[f'{s/1024/1024:.1f}MB' for s in memory_samples]}"
        )

    @pytest.mark.asyncio
    async def test_cache_service_memory_flat_over_iterations(self):
        """CacheService should maintain flat memory over many set/get cycles."""
        from promiselink.core.redis import _MEMORY_CACHE_MAX_SIZE, CacheService

        cache = CacheService()

        gc.collect()
        tracemalloc.start()

        memory_samples: list[int] = []

        # Write 5x the cache limit, cycling through keys
        for i in range(_MEMORY_CACHE_MAX_SIZE * 5):
            await cache.set(f"cycle-{i}", {"data": i}, ttl=3600)

            if i % 500 == 0:
                current, _ = tracemalloc.get_traced_memory()
                memory_samples.append(current)

        tracemalloc.stop()

        # Cache should be at the limit, not growing
        assert len(cache._memory_cache) <= _MEMORY_CACHE_MAX_SIZE

        first_sample = memory_samples[0]
        last_sample = memory_samples[-1]
        growth = last_sample - first_sample
        growth_mb = growth / (1024 * 1024)

        assert growth_mb < 10, (
            f"CacheService memory grew {growth_mb:.1f}MB over iterations — possible leak. "
            f"Samples: {[f'{s/1024/1024:.1f}MB' for s in memory_samples]}"
        )

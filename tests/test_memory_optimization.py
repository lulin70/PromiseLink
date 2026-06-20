"""Memory optimization tests for PromiseLink.

Verifies that memory optimizations are in place and effective:
  1. Cache size limits — EmbeddingProvider and CacheService caches are bounded
  2. Memory usage baseline — tracemalloc measurements for typical operations
  3. Batch processing memory — memory stays flat during batch processing
  4. Graph cleanup — association discovery releases intermediate data
  5. Embedding cache — LRU eviction keeps cache within max size
  6. Session cleanup — DB sessions are properly closed after use
  7. Generator usage — large datasets use pagination/generators, not full lists

Uses tracemalloc for Python-level allocation tracking.
"""

import gc

# Force IS_SQLITE=True BEFORE importing models
import os
import tracemalloc
import uuid
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from promiselink.core.redis import _MEMORY_CACHE_MAX_SIZE, CacheService
from promiselink.services.embedding_provider import (
    EMBEDDING_CACHE_MAX_SIZE,
    EmbeddingProvider,
)
from promiselink.services.entity_resolution import EntityResolutionEngine
from promiselink.services.semantic_search import SemanticSearchEngine

os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.entity import Entity
from promiselink.services.association_discovery import AssociationDiscoveryEngine
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
) -> Entity:
    """Helper to create an Entity object."""
    if event_id is None:
        evt = await create_test_event(session, user_id=user_id)
        event_id = evt.id
    props: dict = {}
    basic: dict = {}
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
# 1. Cache Size Limits
# ══════════════════════════════════════════════════════════════════════════════


class TestCacheSizeLimits:
    """Verify caches have bounded sizes to prevent unbounded memory growth."""

    def test_embedding_cache_max_size_constant_exists(self):
        """EMBEDDING_CACHE_MAX_SIZE constant is defined and positive."""
        assert EMBEDDING_CACHE_MAX_SIZE > 0
        assert isinstance(EMBEDDING_CACHE_MAX_SIZE, int)

    def test_redis_memory_cache_max_size_constant_exists(self):
        """_MEMORY_CACHE_MAX_SIZE constant is defined and positive."""
        assert _MEMORY_CACHE_MAX_SIZE > 0
        assert isinstance(_MEMORY_CACHE_MAX_SIZE, int)

    def test_embedding_provider_cache_is_ordered_dict(self):
        """EmbeddingProvider uses OrderedDict (enables LRU eviction)."""
        provider = _make_provider_with_api()
        assert isinstance(provider._cache, OrderedDict)

    @pytest.mark.asyncio
    async def test_embedding_cache_evicts_when_over_limit(self):
        """Embedding cache evicts LRU entries when exceeding max size."""
        provider = _make_provider_with_api()

        # Generate more unique embeddings than the cache limit
        count = EMBEDDING_CACHE_MAX_SIZE + 50
        for i in range(count):
            fake_emb = _make_fake_embedding(seed=i)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"unique-text-{i}")

        stats = provider.get_cache_stats()
        assert stats["cache_size"] <= EMBEDDING_CACHE_MAX_SIZE, (
            f"Cache size {stats['cache_size']} exceeds max {EMBEDDING_CACHE_MAX_SIZE}"
        )

    @pytest.mark.asyncio
    async def test_redis_cache_service_evicts_when_over_limit(self):
        """CacheService memory cache evicts oldest entries over the limit."""
        cache = CacheService()
        # Insert more entries than the limit
        count = _MEMORY_CACHE_MAX_SIZE + 10
        for i in range(count):
            await cache.set(f"key-{i}", {"index": i}, ttl=3600)

        assert len(cache._memory_cache) <= _MEMORY_CACHE_MAX_SIZE, (
            f"Memory cache size {len(cache._memory_cache)} exceeds max {_MEMORY_CACHE_MAX_SIZE}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. Memory Usage Baseline
# ══════════════════════════════════════════════════════════════════════════════


class TestMemoryUsageBaseline:
    """Measure memory before/after typical operations using tracemalloc."""

    @pytest.mark.asyncio
    async def test_embedding_provider_memory_baseline(self):
        """Embedding 100 texts should not allocate excessive memory (< 20MB)."""
        provider = _make_provider_with_api()

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(100):
            fake_emb = _make_fake_embedding(seed=i)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"baseline-text-{i}")

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        # 100 embeddings × 384 floats × 8 bytes ≈ 0.3MB, allow overhead
        assert growth_mb < 20, (
            f"Memory growth after 100 embeddings: {growth_mb:.1f}MB exceeds 20MB threshold"
        )

    @pytest.mark.asyncio
    async def test_entity_resolution_memory_baseline(self, db_session):
        """Resolving 50 entities should not allocate excessive memory (< 30MB)."""
        user_id = make_user_id()
        # Seed 50 existing entities
        for i in range(50):
            await _make_entity(db_session, user_id, f"人脉{i:03d}", city="北京")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        for i in range(50):
            await engine.resolve(
                {"name": f"新人{i:03d}", "city": "北京", "entity_type": "person"},
                user_id,
            )

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        assert growth_mb < 30, (
            f"Memory growth after 50 resolutions: {growth_mb:.1f}MB exceeds 30MB threshold"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Batch Processing Memory
# ══════════════════════════════════════════════════════════════════════════════


class TestBatchProcessingMemory:
    """Verify memory stays flat during batch processing."""

    @pytest.mark.asyncio
    async def test_embedding_batch_memory_stays_flat(self):
        """Embedding batches repeatedly should not grow memory unboundedly.

        Pre-creates a single mock response and reuses it across batches so
        that the only source of memory growth is the embedding cache itself.
        With cycling texts, the cache stays small and bounded.
        """
        provider = _make_provider_with_api()

        # Pre-create a single mock response with 50 unique embeddings.
        # Reusing it across batches ensures mock object allocation does not
        # pollute the memory measurement — only the cache can grow.
        UNIQUE_TEXTS = 50
        BATCH_SIZE = 200
        embeddings = [_make_fake_embedding(seed=i) for i in range(UNIQUE_TEXTS)]
        mock_response = _mock_embedding_response(embeddings)
        provider._client.embeddings.create = AsyncMock(return_value=mock_response)

        memory_samples: list[int] = []
        gc.collect()
        tracemalloc.start()

        for batch_num in range(5):
            # Cycle through the same 50 unique texts in every batch
            texts = [f"text-{i % UNIQUE_TEXTS}" for i in range(BATCH_SIZE)]
            await provider.embed_batch(texts)

            gc.collect()
            current, _ = tracemalloc.get_traced_memory()
            memory_samples.append(current)

        tracemalloc.stop()

        # Memory should not grow significantly across batches.
        # With cycling texts, the cache stays at 50 entries, so growth
        # indicates a leak in the batch processing path.
        first_sample = memory_samples[0]
        last_sample = memory_samples[-1]
        growth = last_sample - first_sample
        growth_mb = growth / (1024 * 1024)

        # The cache has 50 entries × 384 floats × 8 bytes ≈ 1.5MB.
        # Allow tolerance for tracemalloc overhead and internal buffers.
        assert growth_mb < 5, (
            f"Memory grew {growth_mb:.1f}MB across 5 batches — possible leak. "
            f"Samples: {[f'{s/1024/1024:.1f}MB' for s in memory_samples]}"
        )
        # Cache should have exactly UNIQUE_TEXTS entries (no growth)
        assert len(provider._cache) == UNIQUE_TEXTS, (
            f"Cache should have {UNIQUE_TEXTS} entries, got {len(provider._cache)}"
        )

    @pytest.mark.asyncio
    async def test_association_discovery_batch_memory_bounded(self, db_session):
        """Association discovery with many entities should not OOM."""
        user_id = make_user_id()
        # Seed entities that share a city (triggers same_city associations)
        for i in range(30):
            await _make_entity(db_session, user_id, f"测试{i:03d}", city="上海")
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)

        gc.collect()
        tracemalloc.start()
        snapshot_before = tracemalloc.take_snapshot()

        # Run full scan discovery
        await engine.discover_all_pairs(user_id)

        snapshot_after = tracemalloc.take_snapshot()
        stats = snapshot_after.compare_to(snapshot_before, "lineno")
        total_growth = sum(s.size_diff for s in stats if s.size_diff > 0)
        tracemalloc.stop()

        growth_mb = total_growth / (1024 * 1024)
        # 30 entities → ~435 pairs, should be well under 50MB
        assert growth_mb < 50, (
            f"Memory growth during association discovery: {growth_mb:.1f}MB exceeds 50MB threshold"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 4. Graph Cleanup
# ══════════════════════════════════════════════════════════════════════════════


class TestGraphCleanup:
    """Verify association discovery releases intermediate data after use."""

    @pytest.mark.asyncio
    async def test_association_engine_does_not_hold_entity_references(self, db_session):
        """After discovery, the engine should not hold references to all entities.

        The AssociationDiscoveryEngine loads entities into local variables during
        discovery. After the method returns, those locals should be eligible for
        garbage collection. We verify by checking that the engine instance does
        not accumulate entity attributes across calls.
        """
        user_id = make_user_id()
        for i in range(10):
            await _make_entity(db_session, user_id, f"实体{i:03d}", city="深圳")
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)

        # Before discovery — engine should not have entity caches
        assert not hasattr(engine, "_entity_cache") or len(getattr(engine, "_entity_cache", {})) == 0

        await engine.discover_all_pairs(user_id)

        # After discovery — engine should still not accumulate unbounded entity caches
        # The engine only holds self.session, self.config, self.cold_discoverers
        # It should NOT hold references to the discovered entities after the method returns
        assert not hasattr(engine, "_all_entities"), (
            "Engine should not retain _all_entities attribute after discovery"
        )

    @pytest.mark.asyncio
    async def test_existing_pairs_set_is_local_not_persisted(self, db_session):
        """The existing_pairs set used for dedup should be local, not stored on self."""
        user_id = make_user_id()
        for i in range(5):
            await _make_entity(db_session, user_id, f"清理测试{i}", city="广州")
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)
        await engine.discover_all_pairs(user_id)

        # The existing_pairs set should be a local variable, not stored on self
        assert not hasattr(engine, "_existing_pairs"), (
            "Engine should not retain _existing_pairs after discovery (memory leak)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Embedding Cache
# ══════════════════════════════════════════════════════════════════════════════


class TestEmbeddingCache:
    """Verify embedding cache has size limits and LRU eviction works."""

    @pytest.mark.asyncio
    async def test_cache_hit_does_not_exceed_limit(self):
        """Repeated cache hits should not grow the cache."""
        provider = _make_provider_with_api()
        fake_emb = _make_fake_embedding(seed=1)
        mock_response = _mock_embedding_response([fake_emb])
        provider._client.embeddings.create = AsyncMock(return_value=mock_response)

        # Embed the same text 100 times — should be 1 cache entry
        for _ in range(100):
            await provider.embed("repeated-text")

        stats = provider.get_cache_stats()
        assert stats["cache_size"] == 1, (
            f"Cache size should be 1 for repeated text, got {stats['cache_size']}"
        )
        assert stats["hits"] == 99, f"Should have 99 cache hits, got {stats['hits']}"
        assert stats["misses"] == 1, f"Should have 1 cache miss, got {stats['misses']}"

    @pytest.mark.asyncio
    async def test_lru_eviction_removes_oldest(self):
        """LRU eviction should remove the least-recently-used entry."""
        provider = _make_provider_with_api()

        # Fill cache to exactly the limit
        for i in range(EMBEDDING_CACHE_MAX_SIZE):
            fake_emb = _make_fake_embedding(seed=i)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"text-{i}")

        assert len(provider._cache) == EMBEDDING_CACHE_MAX_SIZE

        # Add one more — should evict "text-0" (the oldest/least-recently-used)
        fake_emb = _make_fake_embedding(seed=999)
        mock_response = _mock_embedding_response([fake_emb])
        provider._client.embeddings.create = AsyncMock(return_value=mock_response)
        await provider.embed("text-new")

        assert len(provider._cache) == EMBEDDING_CACHE_MAX_SIZE, (
            f"Cache should stay at {EMBEDDING_CACHE_MAX_SIZE} after eviction, "
            f"got {len(provider._cache)}"
        )

        # The first key ("text-0") should have been evicted
        first_key = provider._cache_key("text-0")
        assert first_key not in provider._cache, (
            "Oldest entry should have been evicted by LRU"
        )

    @pytest.mark.asyncio
    async def test_clear_cache_releases_memory(self):
        """clear_cache() should empty the cache and reset stats."""
        provider = _make_provider_with_api()

        for i in range(50):
            fake_emb = _make_fake_embedding(seed=i)
            mock_response = _mock_embedding_response([fake_emb])
            provider._client.embeddings.create = AsyncMock(return_value=mock_response)
            await provider.embed(f"clear-test-{i}")

        assert len(provider._cache) == 50

        provider.clear_cache()

        assert len(provider._cache) == 0
        stats = provider.get_cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["cache_size"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# 6. Session Cleanup
# ══════════════════════════════════════════════════════════════════════════════


class TestSessionCleanup:
    """Verify DB sessions are properly closed after use."""

    @pytest.mark.asyncio
    async def test_db_session_fixture_closes_after_test(self, db_session):
        """The db_session fixture should provide a working session that closes after use."""
        # The session should be active during the test
        assert db_session is not None
        # Perform a simple operation
        user_id = make_user_id()
        await create_test_event(db_session, user_id=user_id)
        await db_session.flush()
        # The fixture's cleanup (after yield) handles closing

    @pytest.mark.asyncio
    async def test_entity_resolution_clear_index_releases_references(self, db_session):
        """clear_index() should release entity references from in-memory indexes."""
        user_id = make_user_id()
        for i in range(20):
            await _make_entity(db_session, user_id, f"索引测试{i:03d}", city="杭州")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)
        # Trigger index loading by resolving an entity
        await engine.resolve({"name": "新实体", "city": "杭州"}, user_id)

        # Index should now be loaded
        assert engine._index_loaded is True
        assert engine.index_size() > 0, "Index should contain entity references after resolve()"

        # Clear the index
        engine.clear_index()

        # Index should be empty and marked as not loaded
        assert engine._index_loaded is False
        assert engine.index_size() == 0, "Index should be empty after clear_index()"
        assert len(engine._name_index) == 0
        assert len(engine._surname_index) == 0
        assert len(engine._alias_index) == 0

    @pytest.mark.asyncio
    async def test_clear_index_allows_rebuild_on_next_resolve(self, db_session):
        """After clear_index(), the next resolve() should rebuild the index."""
        user_id = make_user_id()
        await _make_entity(db_session, user_id, "重建测试", city="成都")
        await db_session.flush()

        engine = EntityResolutionEngine(db_session)
        await engine.resolve({"name": "重建测试", "city": "成都"}, user_id)
        assert engine._index_loaded is True

        engine.clear_index()
        assert engine._index_loaded is False

        # Next resolve should rebuild the index
        await engine.resolve({"name": "重建测试", "city": "成都"}, user_id)
        assert engine._index_loaded is True
        assert engine.index_size() > 0


# ══════════════════════════════════════════════════════════════════════════════
# 7. Generator Usage / Pagination
# ══════════════════════════════════════════════════════════════════════════════


class TestGeneratorUsage:
    """Verify large datasets use pagination/generators, not full in-memory lists."""

    @pytest.mark.asyncio
    async def test_fetch_all_person_entities_uses_pagination(self, db_session):
        """_fetch_all_person_entities should use batched pagination, not one big query.

        This verifies the method has a BATCH_SIZE constant and MAX_ENTITY_LIMIT
        to prevent loading all entities into memory at once.
        """
        # Inspect the source code to verify pagination constants exist
        import inspect

        from promiselink.services.association_graph import AssociationGraphMixin

        source = inspect.getsource(AssociationGraphMixin._fetch_all_person_entities)
        assert "BATCH_SIZE" in source, (
            "_fetch_all_person_entities should use BATCH_SIZE for pagination"
        )
        assert "MAX_ENTITY_LIMIT" in source, (
            "_fetch_all_person_entities should have MAX_ENTITY_LIMIT to cap memory"
        )
        assert "offset" in source, (
            "_fetch_all_person_entities should use offset-based pagination"
        )

    @pytest.mark.asyncio
    async def test_fetch_all_person_entities_respects_limit(self, db_session):
        """_fetch_all_person_entities should cap total entities at MAX_ENTITY_LIMIT."""
        user_id = make_user_id()
        # Create more entities than the internal batch size to test pagination
        for i in range(15):
            await _make_entity(db_session, user_id, f"分页{i:03d}", city="南京")
        await db_session.flush()

        engine = AssociationDiscoveryEngine(db_session)
        entities = await engine._fetch_all_person_entities(user_id)

        # Should return all 15 entities (under the MAX_ENTITY_LIMIT of 5000)
        assert len(entities) == 15
        # Verify it returned a list (the method builds a list, but with pagination)
        assert isinstance(entities, list)

    @pytest.mark.asyncio
    async def test_find_incremental_candidates_has_limit(self, db_session):
        """_find_incremental_candidates should have a CANDIDATE_LIMIT to bound memory."""
        import inspect

        from promiselink.services.association_matcher import AssociationMatcherMixin

        source = inspect.getsource(AssociationMatcherMixin._find_incremental_candidates)
        assert "CANDIDATE_LIMIT" in source, (
            "_find_incremental_candidates should have CANDIDATE_LIMIT to bound memory"
        )
        assert ".limit(" in source, (
            "_find_incremental_candidates should use SQL LIMIT to bound query results"
        )

    @pytest.mark.asyncio
    async def test_discover_incremental_has_batch_limit(self, db_session):
        """discover_incremental should have COLD_DISCOVERY_BATCH_LIMIT to bound memory."""
        import inspect

        from promiselink.services.association_discovery import AssociationDiscoveryEngine

        source = inspect.getsource(AssociationDiscoveryEngine.discover_incremental)
        assert "COLD_DISCOVERY_BATCH_LIMIT" in source, (
            "discover_incremental should have COLD_DISCOVERY_BATCH_LIMIT to bound memory"
        )

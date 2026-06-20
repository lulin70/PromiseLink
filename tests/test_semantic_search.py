"""Tests for EmbeddingProvider and SemanticSearchEngine (F-57).

All API calls are mocked — no real network access required.
"""

import sqlite3
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from promiselink.services.embedding_provider import (
    DEFAULT_EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
)
from promiselink.services.semantic_search import SemanticSearchEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_embedding(dim: int = EMBEDDING_DIMENSIONS, seed: int = 42) -> list[float]:
    """Generate a deterministic fake embedding vector."""
    import random
    rng = random.Random(seed)
    vec = [rng.gauss(0, 1) for _ in range(dim)]
    # Normalise to unit length so cosine similarity behaves nicely
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


# ---------------------------------------------------------------------------
# EmbeddingProvider tests
# ---------------------------------------------------------------------------

class TestEmbeddingProvider:
    """Tests for EmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_embed_returns_correct_dimensions(self):
        """embed() should return a 768-dim vector."""
        fake_emb = _make_fake_embedding()
        mock_response = _mock_embedding_response([fake_emb])

        with patch("promiselink.services.embedding_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = EmbeddingProvider.__new__(EmbeddingProvider)
            provider._provider = "api"
            provider._client = mock_client
            provider._model = DEFAULT_EMBEDDING_MODEL
            provider._cache = OrderedDict()
            provider._cache_hits = 0
            provider._cache_misses = 0
            provider._local_model = None

            result = await provider.embed("hello world")

            assert len(result) == EMBEDDING_DIMENSIONS
            assert result == fake_emb
            mock_client.embeddings.create.assert_awaited_once_with(
                model=DEFAULT_EMBEDDING_MODEL,
                input="hello world",
            )

    @pytest.mark.asyncio
    async def test_embed_cache_hit(self):
        """Second call with same text should hit cache (no API call)."""
        fake_emb = _make_fake_embedding()
        mock_response = _mock_embedding_response([fake_emb])

        with patch("promiselink.services.embedding_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = EmbeddingProvider.__new__(EmbeddingProvider)
            provider._provider = "api"
            provider._client = mock_client
            provider._model = DEFAULT_EMBEDDING_MODEL
            provider._cache = OrderedDict()
            provider._cache_hits = 0
            provider._cache_misses = 0
            provider._local_model = None

            # First call — cache miss
            r1 = await provider.embed("hello")
            assert provider._cache_misses == 1
            assert provider._cache_hits == 0

            # Second call — cache hit
            r2 = await provider.embed("hello")
            assert provider._cache_hits == 1
            assert r1 == r2

            # API called only once
            assert mock_client.embeddings.create.await_count == 1

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """embed_batch() should return embeddings for all input texts."""
        texts = ["alpha", "beta", "gamma"]
        fake_embs = [_make_fake_embedding(seed=i) for i in range(3)]
        mock_response = _mock_embedding_response(fake_embs)

        with patch("promiselink.services.embedding_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings = MagicMock()
            mock_client.embeddings.create = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            provider = EmbeddingProvider.__new__(EmbeddingProvider)
            provider._provider = "api"
            provider._client = mock_client
            provider._model = DEFAULT_EMBEDDING_MODEL
            provider._cache = OrderedDict()
            provider._cache_hits = 0
            provider._cache_misses = 0
            provider._local_model = None

            results = await provider.embed_batch(texts)

            assert len(results) == 3
            for i, r in enumerate(results):
                assert len(r) == EMBEDDING_DIMENSIONS
                assert r == fake_embs[i]

    @pytest.mark.asyncio
    async def test_embed_batch_uses_cache(self):
        """embed_batch() should use cached embeddings for previously seen texts."""
        # Pre-populate cache with "alpha"
        fake_emb_alpha = _make_fake_embedding(seed=0)
        fake_emb_beta = _make_fake_embedding(seed=1)

        with patch("promiselink.services.embedding_provider.AsyncOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.embeddings = MagicMock()
            # Only "beta" is uncached, so API returns 1 embedding
            mock_client.embeddings.create = AsyncMock(
                return_value=_mock_embedding_response([fake_emb_beta])
            )
            mock_client_cls.return_value = mock_client

            provider = EmbeddingProvider.__new__(EmbeddingProvider)
            provider._provider = "api"
            provider._client = mock_client
            provider._model = DEFAULT_EMBEDDING_MODEL
            provider._cache_hits = 0
            provider._cache_misses = 0
            provider._local_model = None

            # Pre-populate cache
            import hashlib
            key_alpha = hashlib.sha256(b"alpha").hexdigest()
            provider._cache = OrderedDict([(key_alpha, fake_emb_alpha)])

            results = await provider.embed_batch(["alpha", "beta"])

            assert len(results) == 2
            assert results[0] == fake_emb_alpha  # from cache
            assert results[1] == fake_emb_beta    # from API
            # API called once (only for uncached "beta")
            assert mock_client.embeddings.create.await_count == 1

    def test_get_cache_stats(self):
        """get_cache_stats() should return correct statistics."""
        provider = EmbeddingProvider.__new__(EmbeddingProvider)
        provider._cache_hits = 7
        provider._cache_misses = 3
        provider._cache = {"a": [1.0], "b": [2.0]}

        stats = provider.get_cache_stats()
        assert stats["hits"] == 7
        assert stats["misses"] == 3
        assert stats["hit_rate"] == 0.7
        assert stats["cache_size"] == 2

    def test_clear_cache(self):
        """clear_cache() should reset cache and stats."""
        provider = EmbeddingProvider.__new__(EmbeddingProvider)
        provider._cache = {"a": [1.0]}
        provider._cache_hits = 5
        provider._cache_misses = 2

        provider.clear_cache()
        assert provider._cache == {}
        assert provider._cache_hits == 0
        assert provider._cache_misses == 0


# ---------------------------------------------------------------------------
# SemanticSearchEngine tests
# ---------------------------------------------------------------------------

class TestSemanticSearchEngine:
    """Tests for SemanticSearchEngine (using Python fallback, no sqlite-vec)."""

    @pytest.fixture
    def provider(self):
        """Create an EmbeddingProvider with mocked client."""
        provider = EmbeddingProvider.__new__(EmbeddingProvider)
        provider._provider = "api"
        provider._client = MagicMock()
        provider._model = DEFAULT_EMBEDDING_MODEL
        provider._cache = OrderedDict()
        provider._cache_hits = 0
        provider._cache_misses = 0
        provider._local_model = None
        return provider

    @pytest.fixture
    def engine(self, provider, tmp_path):
        """Create a SemanticSearchEngine with a temp database."""
        db_path = str(tmp_path / "test_vec.db")
        # Patch sqlite_vec import to force Python fallback
        with patch.dict("sys.modules", {"sqlite_vec": None}):
            engine = SemanticSearchEngine(provider, db_path=db_path)
        return engine

    @pytest.mark.asyncio
    async def test_index_entity(self, engine, provider):
        """index_entity() should store an embedding in the database."""
        fake_emb = _make_fake_embedding(seed=1)
        provider.embed = AsyncMock(return_value=fake_emb)

        await engine.index_entity("ent-1", "张三 CEO 智源AI", "user-1")

        # Verify stored in DB
        conn = sqlite3.connect(engine.db_path)
        row = conn.execute(
            "SELECT target_type, target_id, user_id, source_text FROM vector_embeddings"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "entity"
        assert row[1] == "ent-1"
        assert row[2] == "user-1"
        assert row[3] == "张三 CEO 智源AI"

    @pytest.mark.asyncio
    async def test_index_event(self, engine, provider):
        """index_event() should store an embedding in the database."""
        fake_emb = _make_fake_embedding(seed=2)
        provider.embed = AsyncMock(return_value=fake_emb)

        await engine.index_event("evt-1", "与张三讨论AI合作", "user-1")

        conn = sqlite3.connect(engine.db_path)
        row = conn.execute(
            "SELECT target_type, target_id, user_id, source_text FROM vector_embeddings"
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "event"
        assert row[1] == "evt-1"
        assert row[2] == "user-1"
        assert row[3] == "与张三讨论AI合作"

    @pytest.mark.asyncio
    async def test_search_returns_results(self, engine, provider):
        """search() should return ranked results by cosine similarity."""
        # Index two entities with different embeddings
        emb_a = _make_fake_embedding(seed=10)
        emb_b = _make_fake_embedding(seed=20)

        # Mock embed to return different embeddings for different texts
        embeddings_map = {
            "AI research": emb_a,
            "cooking recipe": emb_b,
            "artificial intelligence": emb_a,  # similar to "AI research"
        }

        async def mock_embed(text: str) -> list[float]:
            return embeddings_map.get(text, _make_fake_embedding(seed=99))

        provider.embed = AsyncMock(side_effect=mock_embed)

        await engine.index_entity("ent-1", "AI research", "user-1")
        await engine.index_entity("ent-2", "cooking recipe", "user-1")

        # Search for something similar to ent-1
        results = await engine.search("artificial intelligence", "user-1", top_k=5)

        assert len(results) == 2
        # ent-1 should rank higher (same embedding as query)
        assert results[0].target_id == "ent-1"
        assert results[0].target_type == "entity"
        assert results[0].score > results[1].score

    @pytest.mark.asyncio
    async def test_search_user_isolation(self, engine, provider):
        """search() should only return results for the specified user."""
        emb = _make_fake_embedding(seed=30)
        provider.embed = AsyncMock(return_value=emb)

        await engine.index_entity("ent-1", "text", "user-1")
        await engine.index_entity("ent-2", "text", "user-2")

        results = await engine.search("text", "user-1", top_k=10)
        assert len(results) == 1
        assert results[0].target_id == "ent-1"

    def test_cosine_similarity_identical_vectors(self):
        """Cosine similarity of identical vectors should be 1.0."""
        vec = [1.0, 0.0, 0.0]
        assert SemanticSearchEngine._cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal_vectors(self):
        """Cosine similarity of orthogonal vectors should be 0.0."""
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        assert SemanticSearchEngine._cosine_similarity(a, b) == pytest.approx(0.0)

    def test_cosine_similarity_opposite_vectors(self):
        """Cosine similarity of opposite vectors should be -1.0."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert SemanticSearchEngine._cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_cosine_similarity_zero_vector(self):
        """Cosine similarity with zero vector should be 0.0."""
        a = [1.0, 2.0]
        b = [0.0, 0.0]
        assert SemanticSearchEngine._cosine_similarity(a, b) == 0.0

    @pytest.mark.asyncio
    async def test_get_stats(self, engine, provider):
        """get_stats() should return correct indexing statistics."""
        emb = _make_fake_embedding(seed=40)
        provider.embed = AsyncMock(return_value=emb)

        await engine.index_entity("ent-1", "text1", "user-1")
        await engine.index_event("evt-1", "text2", "user-1")
        await engine.index_entity("ent-2", "text3", "user-2")

        # Total stats
        stats = await engine.get_stats()
        assert stats["total_embeddings"] == 3
        assert stats["vec_available"] is False
        assert stats["dimensions"] == EMBEDDING_DIMENSIONS

        # User-scoped stats
        stats_user1 = await engine.get_stats(user_id="user-1")
        assert stats_user1["total_embeddings"] == 2

        stats_user2 = await engine.get_stats(user_id="user-2")
        assert stats_user2["total_embeddings"] == 1

    @pytest.mark.asyncio
    async def test_index_upsert(self, engine, provider):
        """Re-indexing the same target should update, not duplicate."""
        emb1 = _make_fake_embedding(seed=50)
        emb2 = _make_fake_embedding(seed=51)
        provider.embed = AsyncMock(side_effect=[emb1, emb2])

        await engine.index_entity("ent-1", "first text", "user-1")
        await engine.index_entity("ent-1", "updated text", "user-1")

        stats = await engine.get_stats(user_id="user-1")
        assert stats["total_embeddings"] == 1

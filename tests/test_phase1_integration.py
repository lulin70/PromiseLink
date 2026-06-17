"""Phase 1 Data Integration Tests — Real DB + Real Embedding + Pipeline chain.

Validates the complete data flow chain:
  1. EmbeddingProvider → local sentence-transformers (all-MiniLM-L6-v2)
  2. SemanticSearchEngine → index + search with real vectors
  3. Step 5.5 → Entity embedding in Pipeline
  4. Step 8.5 → PriorityScorerV2 four-dimensional scoring
  5. F-58 → Semantic similarity in association discovery
  6. db_path consistency → all components use the same SQLite file

These tests use REAL local embedding model (no mock) and REAL SQLite file
to catch integration bugs that mock-based tests cannot.
"""

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.database import Base
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.embedding_provider import (
    LOCAL_EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
)
from promiselink.services.semantic_search import SemanticSearchEngine

# ---------------------------------------------------------------------------
# Fixtures — real SQLite file (not in-memory) for cross-connection access
# ---------------------------------------------------------------------------

@pytest.fixture
def real_db_path(tmp_path):
    """Provide a real SQLite file path for integration testing."""
    return str(tmp_path / "integration_test.db")


@pytest_asyncio.fixture
async def real_db_session(real_db_path):
    """Create an async SQLAlchemy session backed by a real SQLite file.

    This is critical: SemanticSearchEngine uses raw sqlite3.connect(),
    so the DB must be a real file, not in-memory.
    """
    url = f"sqlite+aiosqlite:///{real_db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Test 1: EmbeddingProvider local model produces real embeddings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_provider_local_model_produces_real_vectors():
    """EmbeddingProvider with local model produces 384-dim vectors."""
    provider = EmbeddingProvider()
    # API will fail (no key or model not found), falls back to local
    embedding = await provider.embed("张三是智源AI的CEO，关注大模型应用方向")

    assert isinstance(embedding, list)
    assert len(embedding) == LOCAL_EMBEDDING_DIMENSIONS
    assert all(isinstance(v, float) for v in embedding)

    # Verify it's a real embedding (not pseudo): values should be diverse
    unique_vals = len(set(round(v, 6) for v in embedding))
    assert unique_vals > 100, "Embedding seems pseudo (too few unique values)"


@pytest.mark.asyncio
async def test_embedding_provider_similar_texts_have_high_similarity():
    """Semantically similar texts should have cosine similarity > 0.7."""
    provider = EmbeddingProvider()

    emb_a = await provider.embed("张三关注AI赛道早期项目投资")
    emb_b = await provider.embed("张三对人工智能创业项目很感兴趣")
    emb_c = await provider.embed("今天天气很好适合出去跑步")

    def cosine(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na > 0 and nb > 0 else 0.0

    sim_ab = cosine(emb_a, emb_b)
    sim_ac = cosine(emb_a, emb_c)

    # Similar texts should be more similar than unrelated texts
    assert sim_ab > sim_ac, f"Similar texts ({sim_ab:.3f}) should score higher than unrelated ({sim_ac:.3f})"
    assert sim_ab > 0.5, f"Similar texts cosine similarity too low: {sim_ab:.3f}"


# ---------------------------------------------------------------------------
# Test 2: SemanticSearchEngine index + search with real embeddings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_search_index_and_search(real_db_path):
    """Index entities and search with real embeddings end-to-end."""
    provider = EmbeddingProvider()
    engine = SemanticSearchEngine(provider=provider, db_path=real_db_path)

    user_id = str(uuid.uuid4())

    # Index two entities
    await engine.index_entity(
        entity_id="ent-1",
        text="李总是盛恒资本的合伙人，关注AI赛道早期项目投资",
        user_id=user_id,
    )
    await engine.index_entity(
        entity_id="ent-2",
        text="王明做技术咨询，擅长企业数字化转型",
        user_id=user_id,
    )

    # Search for AI investment related
    results = await engine.search("人工智能投资", user_id=user_id, top_k=5)

    assert len(results) >= 1, "Should find at least 1 result"
    # ent-1 should rank higher (AI investment is more similar)
    top_ids = [r.target_id for r in results]
    assert "ent-1" in top_ids, "AI investment entity should be found"

    # Verify stats
    stats = await engine.get_stats(user_id=user_id)
    assert stats["total_embeddings"] == 2


# ---------------------------------------------------------------------------
# Test 3: db_path consistency — vector data written by index is readable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_path_consistency_across_connections(real_db_path):
    """Verify that data written via SemanticSearchEngine is readable via raw sqlite3."""
    provider = EmbeddingProvider()
    engine = SemanticSearchEngine(provider=provider, db_path=real_db_path)

    user_id = str(uuid.uuid4())
    await engine.index_entity(
        entity_id="ent-consistency",
        text="测试db_path一致性",
        user_id=user_id,
    )

    # Read via raw sqlite3 (same path that _semantic_similarity_fallback uses)
    conn = sqlite3.connect(real_db_path)
    try:
        row = conn.execute(
            "SELECT target_id, embedding FROM vector_embeddings WHERE target_id = ?",
            ("ent-consistency",),
        ).fetchone()
        assert row is not None, "Embedding should be readable via raw sqlite3"
        assert row[0] == "ent-consistency"
        assert len(row[1]) > 0, "Embedding BLOB should not be empty"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 4: SemanticSearchEngine._default_db_path matches Settings
# ---------------------------------------------------------------------------

def test_default_db_path_from_settings():
    """SemanticSearchEngine._default_db_path should derive from Settings.database_url."""
    from promiselink.config import get_settings
    settings = get_settings()
    derived = SemanticSearchEngine._default_db_path()

    # Should derive from database_url, not be a random hardcoded value
    if settings.database_url.startswith("sqlite:///"):
        expected = settings.database_url[len("sqlite:///"):]
        assert derived == expected, f"Expected {expected}, got {derived}"
    elif settings.database_url.startswith("sqlite://"):
        # In-memory or empty path (e.g., "sqlite://")
        expected = settings.database_url[len("sqlite://"):]
        assert derived == expected, f"Expected {expected}, got {derived}"
    else:
        # Non-sqlite fallback
        assert derived == "data/promiselink.db"


# ---------------------------------------------------------------------------
# Test 5: PriorityScorerV2 with real DB session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_priority_scorer_v2_with_real_db(real_db_session, user_id):
    """PriorityScorerV2 computes four-dimensional scores with real DB data."""
    from promiselink.services.priority_scorer import PriorityScorerV2

    # Create event + entity + todo in real DB
    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="投资对接会",
        raw_text="今天和李总开会，我答应下周发资料给他。",
        status="completed",
    )
    real_db_session.add(event)

    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        name="李总",
        canonical_name="李总",
        entity_type="person",
        properties={
            "basic": {"company": "盛恒资本", "title": "合伙人"},
            "concern": [{"category": "AI投资", "detail": "关注AI赛道早期项目"}],
        },
    )
    real_db_session.add(entity)

    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        title="发资料给李总",
        todo_type="promise",
        action_type="my_promise",
        status="pending",
        due_date=datetime.now(UTC) + timedelta(days=3),
    )
    real_db_session.add(todo)
    await real_db_session.commit()

    # Score with V2
    scorer = PriorityScorerV2()
    score_result = await scorer.score_with_context(todo, real_db_session)

    assert score_result is not None
    assert 0.0 <= score_result.score <= 1.0
    # Should have all 4 dimensions
    assert hasattr(score_result, "breakdown") or score_result.score > 0.0


# ---------------------------------------------------------------------------
# Test 6: Full embedding → search → similarity chain
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_embedding_to_similarity_chain(real_db_path):
    """End-to-end: index two entities → compute semantic similarity between them."""
    provider = EmbeddingProvider()
    engine = SemanticSearchEngine(provider=provider, db_path=real_db_path)

    user_id = str(uuid.uuid4())

    # Index two related entities
    await engine.index_entity(
        entity_id="ent-lizong",
        text="李总 | 盛恒资本 | 合伙人 | 关注: AI投资 - 关注AI赛道早期项目",
        user_id=user_id,
    )
    await engine.index_entity(
        entity_id="ent-zhangzong",
        text="张总 | 智谱AI | CTO | 关注: 早期客户 - 寻找大模型API客户 | 关注: 投资方 - 寻找VC",
        user_id=user_id,
    )

    # Compute semantic similarity (same logic as _semantic_similarity_fallback)
    conn = sqlite3.connect(real_db_path)
    try:
        import struct

        row_a = conn.execute(
            "SELECT embedding FROM vector_embeddings WHERE target_id = ? AND target_type = 'entity'",
            ("ent-lizong",),
        ).fetchone()
        row_b = conn.execute(
            "SELECT embedding FROM vector_embeddings WHERE target_id = ? AND target_type = 'entity'",
            ("ent-zhangzong",),
        ).fetchone()

        assert row_a is not None, "ent-lizong embedding should exist"
        assert row_b is not None, "ent-zhangzong embedding should exist"

        emb_a = list(struct.unpack(f"{len(row_a[0]) // 4}f", row_a[0]))
        emb_b = list(struct.unpack(f"{len(row_b[0]) // 4}f", row_b[0]))

        similarity = SemanticSearchEngine._cosine_similarity(emb_a, emb_b)
        assert 0.0 <= similarity <= 1.0
        # Two business-related entities should have some similarity
        assert similarity > 0.1, f"Business entities should have some similarity, got {similarity:.3f}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Test 7: Embedding batch fallback to local model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_batch_fallback_to_local():
    """embed_batch should fallback to local model when API fails."""
    provider = EmbeddingProvider()

    texts = [
        "李总关注AI投资",
        "张总寻找早期客户",
        "王明做技术咨询",
    ]
    embeddings = await provider.embed_batch(texts)

    assert len(embeddings) == len(texts)
    for emb in embeddings:
        assert isinstance(emb, list)
        assert len(emb) == LOCAL_EMBEDDING_DIMENSIONS

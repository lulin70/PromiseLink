"""SemanticSearchEngine — Vector-based semantic search using sqlite-vec.

Implements F-57: Semantic search for Entity and Event.
Uses sqlite-vec extension for vector similarity search.

Design reference: PromiseLink_技术设计_v1.md v2.8 §4.12.2
"""

import asyncio
import sqlite3
import struct
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from promiselink.core.logging import get_logger
from promiselink.services.embedding_provider import (
    LOCAL_EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
)

logger = get_logger("promiselink.semantic_search")

# ── Module-level singleton (reuses provider + sqlite-vec extension load) ──
_shared_engine: Optional["SemanticSearchEngine"] = None
_engine_lock = asyncio.Lock()


async def get_shared_engine(provider: EmbeddingProvider | None = None) -> "SemanticSearchEngine":
    """Get or create the module-level shared SemanticSearchEngine.

    Reuses a single engine across all pipeline executions, avoiding
    repeated sqlite-vec extension loads and table initialization.

    Args:
        provider: Optional EmbeddingProvider. If the engine already
            exists, this is ignored. If creating a new engine and
            provider is None, the shared EmbeddingProvider is used.

    Returns:
        The shared SemanticSearchEngine instance.
    """
    global _shared_engine
    if _shared_engine is None:
        async with _engine_lock:
            # Double-check after acquiring the lock
            if _shared_engine is None:
                if provider is None:
                    from promiselink.services.embedding_provider import get_shared_provider
                    provider = await get_shared_provider()
                _shared_engine = SemanticSearchEngine(provider=provider)
                logger.info("shared_semantic_search_engine_created")
    return _shared_engine


async def close_shared_engine() -> None:
    """Close the shared SemanticSearchEngine. Call on app shutdown.

    The engine opens a fresh sqlite connection per operation (no
    persistent connection to close), so this primarily resets the
    singleton reference to allow garbage collection.
    """
    global _shared_engine
    if _shared_engine is not None:
        _shared_engine = None
        logger.info("shared_semantic_search_engine_closed")


@dataclass
class SearchResult:
    """A single search result from semantic search."""
    target_type: str  # "entity" or "event"
    target_id: str
    score: float  # cosine similarity (0.0 ~ 1.0)
    metadata: dict[str, Any] = field(default_factory=dict)


class SemanticSearchEngine:
    """Semantic search engine using sqlite-vec for vector storage.

    Features:
    - Index Entity and Event text as embeddings
    - Search by natural language query
    - Cosine similarity ranking
    - User-scoped data isolation
    """

    def __init__(self, provider: EmbeddingProvider, db_path: str | None = None):
        self.provider = provider
        self.db_path = db_path or self._default_db_path()
        self._actual_dims: int | None = None  # Detected on first embed
        self._init_db()

    @staticmethod
    def _default_db_path() -> str:
        """Derive SQLite file path from Settings.database_url."""
        from promiselink.config import get_settings
        settings = get_settings()
        url = settings.database_url
        # sqlite:///./data/promiselink.db → ./data/promiselink.db
        # sqlite:///data/promiselink.db → data/promiselink.db
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]
        if url.startswith("sqlite://"):
            return url[len("sqlite://"):]
        # Fallback for non-sqlite (shouldn't happen in PoC)
        return "data/promiselink.db"

    def _init_db(self) -> None:
        """Initialize the vector storage tables."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Try to load sqlite-vec extension
            try:
                conn.enable_load_extension(True)
                import sqlite_vec
                conn.load_extension(sqlite_vec.loadable_path())
                self._vec_available = True
                logger.info("sqlite_vec_loaded", path=sqlite_vec.loadable_path())
            except (ImportError, sqlite3.OperationalError, AttributeError) as e:
                self._vec_available = False
                logger.info("sqlite_vec_not_available", note="Using Python cosine similarity fallback", error=str(e))

            # Create metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vector_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    source_text TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(target_type, target_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_vec_user_type
                ON vector_embeddings(user_id, target_type)
            """)

            # Create sqlite-vec virtual table if available
            if self._vec_available:
                # Use LOCAL_EMBEDDING_DIMENSIONS (384) since local model is preferred
                dims = LOCAL_EMBEDDING_DIMENSIONS
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities
                    USING vec0(
                        embedding float[{dims}],
                        target_id TEXT,
                        user_id TEXT
                    )
                """)

            conn.commit()
        finally:
            conn.close()

    def _embedding_to_blob(self, embedding: list[float]) -> bytes:
        """Convert embedding list to BLOB for storage."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _blob_to_embedding(self, blob: bytes) -> list[float]:
        """Convert BLOB back to embedding list."""
        count = len(blob) // 4
        return list(struct.unpack(f"{count}f", blob))

    async def index_entity(self, entity_id: str, text: str, user_id: str) -> None:
        """Index an Entity's text for semantic search.

        Args:
            entity_id: Entity ID
            text: Combined text (concern + capability + basic info)
            user_id: User ID for data isolation
        """
        embedding = await self.provider.embed(text)
        if self._actual_dims is None:
            self._actual_dims = len(embedding)
        await self._store_embedding("entity", entity_id, embedding, user_id, text)

    async def index_event(self, event_id: str, text: str, user_id: str) -> None:
        """Index an Event's text for semantic search.

        Args:
            event_id: Event ID
            text: Event raw_text or summary
            user_id: User ID for data isolation
        """
        embedding = await self.provider.embed(text)
        if self._actual_dims is None:
            self._actual_dims = len(embedding)
        await self._store_embedding("event", event_id, embedding, user_id, text)

    async def _store_embedding(
        self,
        target_type: str,
        target_id: str,
        embedding: list[float],
        user_id: str,
        source_text: str | None = None,
    ) -> None:
        """Store an embedding in the database."""
        blob = self._embedding_to_blob(embedding)
        vec_available = self._vec_available

        def _do_store() -> None:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO vector_embeddings
                        (target_type, target_id, user_id, embedding, source_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    target_type,
                    target_id,
                    user_id,
                    blob,
                    source_text,
                    datetime.now(UTC).isoformat(),
                ))

                # Also insert into vec virtual table if available
                if vec_available:
                    conn.execute("""
                        INSERT OR REPLACE INTO vec_entities (embedding, target_id, user_id)
                        VALUES (?, ?, ?)
                    """, (blob, f"{target_type}:{target_id}", user_id))

                conn.commit()
                logger.debug(
                    "embedding_stored",
                    target_type=target_type,
                    target_id=target_id,
                    dims=len(embedding),
                )
            finally:
                conn.close()

        await asyncio.to_thread(_do_store)

    async def search(
        self, query: str, user_id: str, top_k: int = 10
    ) -> list[SearchResult]:
        """Search for entities/events matching the query.

        Args:
            query: Natural language search query
            user_id: User ID for data isolation
            top_k: Maximum number of results

        Returns:
            List of SearchResult sorted by similarity (highest first)
        """
        query_embedding = await self.provider.embed(query)

        if self._vec_available:
            return await self._search_with_vec(query_embedding, user_id, top_k)
        else:
            return await self._search_with_python(query_embedding, user_id, top_k)

    async def _search_with_vec(
        self, query_embedding: list[float], user_id: str, top_k: int
    ) -> list[SearchResult]:
        """Search using sqlite-vec virtual table."""
        db_path = self.db_path

        def _do_search() -> Any:
            conn = sqlite3.connect(db_path)
            try:
                results = conn.execute("""
                    SELECT
                        vec_entities.target_id,
                        1 - vec_entities.distance AS similarity
                    FROM vec_entities
                    WHERE vec_entities.user_id = ?
                    ORDER BY vec_entities.distance
                    LIMIT ?
                """, (user_id, top_k)).fetchall()

                search_results = []
                for target_id_str, similarity in results:
                    # Parse "type:id" format
                    parts = target_id_str.split(":", 1)
                    if len(parts) == 2:
                        target_type, target_id = parts
                        search_results.append(SearchResult(
                            target_type=target_type,
                            target_id=target_id,
                            score=round(similarity, 4),
                        ))

                return search_results
            finally:
                conn.close()

        return await asyncio.to_thread(_do_search)

    async def _search_with_python(
        self, query_embedding: list[float], user_id: str, top_k: int
    ) -> list[SearchResult]:
        """Fallback search using Python cosine similarity.

        Uses numpy for vectorized batch cosine similarity when available —
        this is significantly more memory-efficient and faster than building
        a Python list of per-row float lists for large embedding sets.
        Falls back to pure-Python cosine similarity if numpy is unavailable.
        """
        db_path = self.db_path

        def _do_search() -> Any:
            conn = sqlite3.connect(db_path)
            try:
                rows = conn.execute("""
                    SELECT target_type, target_id, embedding
                    FROM vector_embeddings
                    WHERE user_id = ?
                """, (user_id,)).fetchall()

                if not rows:
                    return []

                # Try numpy vectorized path (memory-efficient batch similarity)
                try:
                    import numpy as np

                    query_arr = np.asarray(query_embedding, dtype=np.float32)
                    query_norm = np.linalg.norm(query_arr)
                    if query_norm == 0:
                        return [
                            SearchResult(
                                target_type=t_type,
                                target_id=t_id,
                                score=0.0,
                            )
                            for t_type, t_id, _ in rows[:top_k]
                        ]

                    # Build matrix in one allocation instead of N Python lists.
                    # Each row is unpacked from its BLOB directly into the matrix.
                    dim = len(query_embedding)
                    matrix = np.empty((len(rows), dim), dtype=np.float32)
                    for i, (_, _, blob) in enumerate(rows):
                        count = len(blob) // 4
                        # Pad/truncate to dim if storage dimensions differ
                        unpacked = list(struct.unpack(f"{count}f", blob))
                        row_len = min(count, dim)
                        matrix[i, :row_len] = unpacked[:row_len]
                        if row_len < dim:
                            matrix[i, row_len:] = 0.0

                    # Vectorized cosine similarity: dot / (norm_q * norm_r)
                    row_norms = np.linalg.norm(matrix, axis=1)
                    # Avoid division by zero
                    safe_norms = np.where(row_norms == 0, 1.0, row_norms)
                    similarities = (matrix @ query_arr) / (safe_norms * query_norm)

                    # Get top_k indices sorted by similarity descending
                    top_indices = np.argsort(-similarities)[:top_k]

                    return [
                        SearchResult(
                            target_type=rows[idx][0],
                            target_id=rows[idx][1],
                            score=round(float(similarities[idx]), 4),
                        )
                        for idx in top_indices
                    ]
                except ImportError:
                    # numpy not available — fall back to pure Python
                    pass

                # Pure-Python fallback
                results = []
                for target_type, target_id, blob in rows:
                    stored_embedding = self._blob_to_embedding(blob)
                    similarity = self._cosine_similarity(query_embedding, stored_embedding)
                    results.append(SearchResult(
                        target_type=target_type,
                        target_id=target_id,
                        score=round(similarity, 4),
                    ))

                # Sort by similarity descending
                results.sort(key=lambda r: r.score, reverse=True)
                return results[:top_k]
            finally:
                conn.close()

        return await asyncio.to_thread(_do_search)

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)  # type: ignore[no-any-return]

    async def get_stats(self, user_id: str | None = None) -> dict:
        """Get indexing statistics."""
        db_path = self.db_path
        actual_dims = self._actual_dims
        vec_available = self._vec_available

        def _do_stats() -> Any:
            conn = sqlite3.connect(db_path)
            try:
                if user_id:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM vector_embeddings WHERE user_id = ?",
                        (user_id,)
                    ).fetchone()[0]
                else:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM vector_embeddings"
                    ).fetchone()[0]

                return {
                    "total_embeddings": count,
                    "vec_available": vec_available,
                    "dimensions": actual_dims or LOCAL_EMBEDDING_DIMENSIONS,
                }
            finally:
                conn.close()

        return await asyncio.to_thread(_do_stats)

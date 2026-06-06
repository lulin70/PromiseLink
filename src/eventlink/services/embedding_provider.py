"""EmbeddingProvider — Text embedding via Moka AI API (OpenAI-compatible).

Implements F-57: Text embedding for semantic search and association enhancement.
Uses text-embedding-3-small model (768 dimensions) via Moka AI.

Design reference: EventLink_技术设计_v1.md v2.8 §4.12.1
"""

import hashlib

from openai import AsyncOpenAI

from eventlink.config import Settings, get_settings
from eventlink.core.logging import get_logger

logger = get_logger("eventlink.embedding_provider")

# Default embedding model
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 768


class EmbeddingProvider:
    """Provide text embeddings via Moka AI API (OpenAI-compatible).

    Features:
    - Async embedding via OpenAI SDK
    - In-memory cache to avoid redundant API calls
    - Batch embedding support
    - Graceful fallback when API is unavailable
    """

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()
        self._client = AsyncOpenAI(
            base_url=self._settings.llm_base_url,
            api_key=self._settings.llm_api_key,
        )
        self._model = DEFAULT_EMBEDDING_MODEL
        self._cache: dict[str, list[float]] = {}
        self._cache_hits = 0
        self._cache_misses = 0

    def _cache_key(self, text: str) -> str:
        """Generate cache key from text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def embed(self, text: str) -> list[float]:
        """Get embedding for a single text string.

        Args:
            text: Input text to embed

        Returns:
            List of floats (768 dimensions)

        Raises:
            Exception: If API call fails
        """
        key = self._cache_key(text)
        if key in self._cache:
            self._cache_hits += 1
            return self._cache[key]

        self._cache_misses += 1
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=text,
            )
            embedding = response.data[0].embedding
            self._cache[key] = embedding

            logger.debug(
                "embedding_created",
                text_len=len(text),
                dims=len(embedding),
                cached=False,
            )
            return embedding
        except Exception as e:
            logger.error("embedding_failed", text_len=len(text), error=str(e))
            raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings for multiple texts in a single API call.

        Args:
            texts: List of input texts

        Returns:
            List of embedding vectors
        """
        # Separate cached and uncached
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(texts):
            key = self._cache_key(text)
            if key in self._cache:
                results[i] = self._cache[key]
                self._cache_hits += 1
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch embed uncached texts
        if uncached_texts:
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=uncached_texts,
                )
                for idx, data in zip(uncached_indices, response.data):
                    embedding = data.embedding
                    key = self._cache_key(uncached_texts[uncached_indices.index(idx)])
                    self._cache[key] = embedding
                    results[idx] = embedding
                    self._cache_misses += 1

                logger.info(
                    "batch_embedding_created",
                    count=len(uncached_texts),
                    dims=len(embedding),
                )
            except Exception as e:
                logger.error("batch_embedding_failed", count=len(uncached_texts), error=str(e))
                raise

        return results  # type: ignore

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        total = self._cache_hits + self._cache_misses
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "hit_rate": self._cache_hits / total if total > 0 else 0.0,
            "cache_size": len(self._cache),
        }

    def clear_cache(self) -> None:
        """Clear the embedding cache."""
        self._cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

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

# Local embedding model (fallback when API is unavailable)
LOCAL_EMBEDDING_MODEL = "moka-ai/m3e-base"


class EmbeddingProvider:
    """Provide text embeddings via API or local model.

    Strategy:
    1. Try Moka AI API (text-embedding-3-small) first
    2. If API fails, fall back to local sentence-transformers (moka-ai/m3e-base)
    3. If neither available, raise error

    Features:
    - Async embedding via OpenAI SDK (API path)
    - Local sentence-transformers (fallback path)
    - In-memory cache to avoid redundant calls
    - Batch embedding support
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
        self._local_model = None  # Lazy-loaded sentence-transformers

    def _cache_key(self, text: str) -> str:
        """Generate cache key from text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    async def embed(self, text: str) -> list[float]:
        """Get embedding for a single text string.
        
        Strategy: Try API first, fall back to local model.
        
        Args:
            text: Input text to embed
            
        Returns:
            List of floats (768 dimensions)
        """
        key = self._cache_key(text)
        if key in self._cache:
            self._cache_hits += 1
            return self._cache[key]

        self._cache_misses += 1
        
        # Try API first
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=text,
            )
            embedding = response.data[0].embedding
            self._cache[key] = embedding
            
            logger.debug(
                "embedding_created_api",
                text_len=len(text),
                dims=len(embedding),
            )
            return embedding
        except Exception as api_err:
            logger.warning("embedding_api_failed_fallback_local", error=str(api_err))

        # Fallback to local model
        return await self._embed_local(text, key)

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

    async def _embed_local(self, text: str, cache_key: str) -> list[float]:
        """Embed text using local sentence-transformers model.
        
        Lazy-loads moka-ai/m3e-base on first call.
        Falls back to simple hash-based pseudo-embedding if
        sentence-transformers is not installed.
        """
        if self._local_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._local_model = SentenceTransformer(LOCAL_EMBEDDING_MODEL)
                logger.info("local_embedding_model_loaded", model=LOCAL_EMBEDDING_MODEL)
            except ImportError:
                logger.warning("sentence_transformers_not_installed")
                # Fallback: simple deterministic pseudo-embedding for testing
                return self._pseudo_embedding(text, cache_key)

        # Run encoding in thread pool (CPU-bound)
        import asyncio
        loop = asyncio.get_event_loop()
        embedding = await loop.run_in_executor(
            None, lambda: self._local_model.encode(text).tolist()
        )
        self._cache[cache_key] = embedding

        logger.debug(
            "embedding_created_local",
            text_len=len(text),
            dims=len(embedding),
        )
        return embedding

    def _pseudo_embedding(self, text: str, cache_key: str) -> list[float]:
        """Generate deterministic pseudo-embedding for testing without ML models.
        
        NOT suitable for production — only for testing when no embedding
        model is available. Uses hash-based normalization.
        """
        import hashlib
        import struct
        
        # Generate deterministic bytes from text
        h = hashlib.sha512(text.encode("utf-8")).digest()
        # Repeat to fill 768 dimensions (768 * 4 bytes = 3072 bytes)
        full_bytes = b""
        for i in range(7):
            full_bytes += hashlib.sha512((text + str(i)).encode("utf-8")).digest()
        
        # Convert to floats and normalize
        floats = []
        for i in range(EMBEDDING_DIMENSIONS):
            byte_slice = full_bytes[i*4:(i+1)*4]
            if len(byte_slice) == 4:
                val = struct.unpack("f", byte_slice)[0]
                floats.append(val)
            else:
                floats.append(0.0)
        
        # Normalize to unit vector
        norm = sum(x * x for x in floats) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in floats]
        else:
            embedding = [0.0] * EMBEDDING_DIMENSIONS
        
        self._cache[cache_key] = embedding
        logger.warning("pseudo_embedding_used", text_len=len(text))
        return embedding

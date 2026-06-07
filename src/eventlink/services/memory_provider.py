"""Memory Provider Protocol — decoupled interface for raw data storage.

EventLink uses a Protocol-based interface to store and retrieve raw event data.
This decouples the business logic from any specific storage backend.

Three providers are available:
- CarryMemProvider: Uses CarryMem service (SQLite + semantic search)
- FileStoreProvider: Stores raw data as local files (zero external dependency)
- NullMemoryProvider: No-op provider for testing and graceful degradation

Architecture:
    EventLink 业务层 (归一/关联/匹配/Todo/推送)
         ↕ MemoryProvider Protocol (5 methods)
         ↕ Implementation
    CarryMemProvider / FileStoreProvider / NullMemoryProvider
"""

from __future__ import annotations

import json
import os
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from eventlink.core.logging import get_logger

logger = get_logger("eventlink.memory")


# ── Data Classes ──


@dataclass
class MemoryEntry:
    """A stored raw data entry with metadata."""

    entry_id: str
    event_id: str
    raw_text: str
    stored_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    entity_ids: list[str] = field(default_factory=list)
    summary: str = ""
    file_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "event_id": self.event_id,
            "stored_at": self.stored_at.isoformat(),
            "metadata": self.metadata,
            "entity_ids": self.entity_ids,
            "summary": self.summary,
            "file_path": self.file_path,
        }


@dataclass
class SearchResult:
    """A search result from the memory provider."""

    entry_id: str
    event_id: str
    score: float
    summary: str
    raw_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Protocol Definition ──


@runtime_checkable
class MemoryProvider(Protocol):
    """Protocol interface for raw data storage and retrieval.

    EventLink calls these 5 methods to store/retrieve raw event data.
    The implementation is decoupled from business logic.

    Methods:
        store_raw: Store raw event data after pipeline processing
        search: Semantic/full-text search across stored data
        get_by_entity: Retrieve all entries related to an entity
        delete: Delete stored data for an event
        health_check: Check if the provider is available
    """

    async def store_raw(
        self,
        event_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        entity_ids: list[str] | None = None,
        summary: str = "",
    ) -> MemoryEntry:
        """Store raw event data after pipeline processing.

        Args:
            event_id: The source event ID.
            raw_text: The original raw text from the event.
            metadata: Optional metadata (event_type, source, etc.).
            entity_ids: IDs of entities extracted from this event.
            summary: LLM-generated summary of the event.

        Returns:
            MemoryEntry with the stored entry's metadata.
        """
        ...

    async def search(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search across stored raw data.

        Args:
            query: Search query text.
            top_k: Maximum number of results.
            user_id: Optional user ID for scoping.
            filters: Optional filters (event_type, entity_id, date_range).

        Returns:
            List of SearchResult sorted by relevance.
        """
        ...

    async def get_by_entity(
        self,
        entity_id: str,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        """Retrieve all entries related to a specific entity.

        Args:
            entity_id: The entity ID to look up.
            limit: Maximum number of entries to return.

        Returns:
            List of MemoryEntry objects.
        """
        ...

    async def delete(self, event_id: str) -> bool:
        """Delete stored data for an event.

        Args:
            event_id: The event ID whose data should be deleted.

        Returns:
            True if data was found and deleted, False otherwise.
        """
        ...

    async def health_check(self) -> bool:
        """Check if the provider is available.

        Returns:
            True if the provider is healthy and ready.
        """
        ...


# ── NullMemoryProvider — no-op for testing and graceful degradation ──


class NullMemoryProvider:
    """No-op memory provider for testing and graceful degradation.

    All methods succeed silently without storing any data.
    Use this when CarryMem is unavailable or for testing.
    """

    async def store_raw(
        self,
        event_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        entity_ids: list[str] | None = None,
        summary: str = "",
    ) -> MemoryEntry:
        logger.debug("null_memory_store_skipped", event_id=event_id)
        return MemoryEntry(
            entry_id=str(uuid.uuid4()),
            event_id=event_id,
            raw_text=raw_text,
            stored_at=datetime.now(UTC),
            metadata=metadata or {},
            entity_ids=entity_ids or [],
            summary=summary,
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        logger.debug("null_memory_search_skipped", query=query[:50])
        return []

    async def get_by_entity(
        self,
        entity_id: str,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        logger.debug("null_memory_get_by_entity_skipped", entity_id=entity_id)
        return []

    async def delete(self, event_id: str) -> bool:
        logger.debug("null_memory_delete_skipped", event_id=event_id)
        return False

    async def health_check(self) -> bool:
        return True  # Always healthy — it does nothing


# ── FileStoreProvider — local file system storage ──


class FileStoreProvider:
    """File-based memory provider for PoC with zero external dependencies.

    Stores raw data as JSON files in a local directory.
    Supports full-text search via simple string matching.
    No semantic search capability — use CarryMemProvider for that.

    Directory structure:
        {base_dir}/
          entries/
            {event_id}.json    — raw data + metadata
          index/
            entity_index.json  — entity_id → [event_ids]
    """

    def __init__(self, base_dir: str | Path = "./data/memory"):
        self.base_dir = Path(base_dir)
        self.entries_dir = self.base_dir / "entries"
        self.index_dir = self.base_dir / "index"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        self.entries_dir.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, event_id: str) -> Path:
        return self.entries_dir / f"{event_id}.json"

    def _entity_index_path(self) -> Path:
        return self.index_dir / "entity_index.json"

    def _load_entity_index(self) -> dict[str, list[str]]:
        path = self._entity_index_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_entity_index(self, index: dict[str, list[str]]) -> None:
        path = self._entity_index_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    async def store_raw(
        self,
        event_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        entity_ids: list[str] | None = None,
        summary: str = "",
    ) -> MemoryEntry:
        entry_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        entry = MemoryEntry(
            entry_id=entry_id,
            event_id=event_id,
            raw_text=raw_text,
            stored_at=now,
            metadata=metadata or {},
            entity_ids=entity_ids or [],
            summary=summary,
            file_path=str(self._entry_path(event_id)),
        )

        # Write entry file
        data = entry.to_dict()
        data["raw_text"] = raw_text
        with open(self._entry_path(event_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Update entity index
        if entity_ids:
            index = self._load_entity_index()
            for eid in entity_ids:
                if eid not in index:
                    index[eid] = []
                if event_id not in index[eid]:
                    index[eid].append(event_id)
            self._save_entity_index(index)

        logger.info(
            "file_memory_stored",
            event_id=event_id,
            entry_id=entry_id,
            entity_count=len(entity_ids or []),
        )
        return entry

    async def search(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Simple full-text search via string matching.

        For PoC only — no semantic search. Use CarryMemProvider for production.
        """
        results: list[SearchResult] = []
        query_lower = query.lower()

        for entry_file in self.entries_dir.glob("*.json"):
            with open(entry_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            raw_text = data.get("raw_text", "")
            summary = data.get("summary", "")

            # Simple relevance: count query term occurrences
            text = f"{raw_text} {summary}".lower()
            score = text.count(query_lower)

            # Apply filters
            if filters:
                event_type = filters.get("event_type")
                if event_type and data.get("metadata", {}).get("event_type") != event_type:
                    continue

            if score > 0:
                results.append(
                    SearchResult(
                        entry_id=data["entry_id"],
                        event_id=data["event_id"],
                        score=float(score),
                        summary=summary,
                        metadata=data.get("metadata", {}),
                    )
                )

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    async def get_by_entity(
        self,
        entity_id: str,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        index = self._load_entity_index()
        event_ids = index.get(entity_id, [])[:limit]

        entries: list[MemoryEntry] = []
        for eid in event_ids:
            path = self._entry_path(eid)
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entries.append(
                    MemoryEntry(
                        entry_id=data["entry_id"],
                        event_id=data["event_id"],
                        raw_text=data.get("raw_text", ""),
                        stored_at=datetime.fromisoformat(data["stored_at"]),
                        metadata=data.get("metadata", {}),
                        entity_ids=data.get("entity_ids", []),
                        summary=data.get("summary", ""),
                        file_path=data.get("file_path"),
                    )
                )
        return entries

    async def delete(self, event_id: str) -> bool:
        path = self._entry_path(event_id)
        if not path.exists():
            return False

        # Load entry to get entity_ids for index cleanup
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entity_ids = data.get("entity_ids", [])
        os.remove(path)

        # Update entity index
        if entity_ids:
            index = self._load_entity_index()
            for eid in entity_ids:
                if eid in index and event_id in index[eid]:
                    index[eid].remove(event_id)
                    if not index[eid]:
                        del index[eid]
            self._save_entity_index(index)

        logger.info("file_memory_deleted", event_id=event_id)
        return True

    async def health_check(self) -> bool:
        try:
            return self.entries_dir.exists() and self.entries_dir.is_dir()
        except Exception:
            return False


# ── CarryMemProvider — CarryMem service integration ──


class CarryMemProvider:
    """CarryMem-backed memory provider for semantic search and rule-based filtering.

    Uses CarryMem's Protocol 5 methods internally.
    Delegates storage to CarryMem SQLite, search to CarryMem's semantic engine.
    Rule engine supports: avoid, always, prefer, remind.

    Requires:
        - CarryMem service running at carrymem_api_url
        - carrymem_api_key configured
    """

    def __init__(
        self,
        api_url: str = "http://localhost:8100",
        api_key: str = "",
    ):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._client = None

    async def _get_client(self):
        """Lazy-initialize httpx client."""
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def store_raw(
        self,
        event_id: str,
        raw_text: str,
        metadata: dict[str, Any] | None = None,
        entity_ids: list[str] | None = None,
        summary: str = "",
    ) -> MemoryEntry:
        client = await self._get_client()
        entry_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        payload = {
            "entry_id": entry_id,
            "event_id": event_id,
            "raw_text": raw_text,
            "metadata": metadata or {},
            "entity_ids": entity_ids or [],
            "summary": summary,
            "stored_at": now.isoformat(),
        }

        try:
            response = await client.post("/api/v1/notes", json=payload)
            response.raise_for_status()
        except Exception as e:
            logger.warning(
                "carrymem_store_failed",
                event_id=event_id,
                error=str(e),
            )
            # Graceful degradation: return entry even if CarryMem fails
            return MemoryEntry(
                entry_id=entry_id,
                event_id=event_id,
                raw_text=raw_text,
                stored_at=now,
                metadata=metadata or {},
                entity_ids=entity_ids or [],
                summary=summary,
            )

        logger.info("carrymem_stored", event_id=event_id, entry_id=entry_id)
        return MemoryEntry(
            entry_id=entry_id,
            event_id=event_id,
            raw_text=raw_text,
            stored_at=now,
            metadata=metadata or {},
            entity_ids=entity_ids or [],
            summary=summary,
        )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        user_id: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        client = await self._get_client()

        try:
            payload = {"query": query, "top_k": top_k}
            if user_id:
                payload["user_id"] = user_id
            if filters:
                payload["filters"] = filters

            response = await client.post("/api/v1/search", json=payload)
            response.raise_for_status()

            data = response.json()
            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        entry_id=item.get("entry_id", ""),
                        event_id=item.get("event_id", ""),
                        score=item.get("score", 0.0),
                        summary=item.get("summary", ""),
                        raw_text=item.get("raw_text"),
                        metadata=item.get("metadata", {}),
                    )
                )
            return results
        except Exception as e:
            logger.warning("carrymem_search_failed", query=query[:50], error=str(e))
            return []

    async def get_by_entity(
        self,
        entity_id: str,
        limit: int = 20,
    ) -> list[MemoryEntry]:
        client = await self._get_client()

        try:
            response = await client.get(
                f"/api/v1/notes",
                params={"entity_id": entity_id, "limit": limit},
            )
            response.raise_for_status()

            data = response.json()
            entries = []
            for item in data.get("notes", []):
                entries.append(
                    MemoryEntry(
                        entry_id=item.get("entry_id", ""),
                        event_id=item.get("event_id", ""),
                        raw_text=item.get("raw_text", ""),
                        stored_at=datetime.fromisoformat(
                            item.get("stored_at", datetime.now(UTC).isoformat())
                        ),
                        metadata=item.get("metadata", {}),
                        entity_ids=item.get("entity_ids", []),
                        summary=item.get("summary", ""),
                    )
                )
            return entries
        except Exception as e:
            logger.warning(
                "carrymem_get_by_entity_failed",
                entity_id=entity_id,
                error=str(e),
            )
            return []

    async def delete(self, event_id: str) -> bool:
        client = await self._get_client()

        try:
            response = await client.delete(f"/api/v1/notes/{event_id}")
            if response.status_code == 404:
                return False
            response.raise_for_status()
            logger.info("carrymem_deleted", event_id=event_id)
            return True
        except Exception as e:
            logger.warning("carrymem_delete_failed", event_id=event_id, error=str(e))
            return False

    async def health_check(self) -> bool:
        client = await self._get_client()

        try:
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        """Close the httpx client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# ── Provider Factory ──


def create_memory_provider(
    provider_type: str = "null",
    **kwargs: Any,
) -> MemoryProvider:
    """Factory function to create a memory provider.

    Args:
        provider_type: One of "null", "file", "carrymem".
        **kwargs: Provider-specific configuration.

    Returns:
        A MemoryProvider instance.

    Raises:
        ValueError: If provider_type is not recognized.
    """
    if provider_type == "null":
        return NullMemoryProvider()
    elif provider_type == "file":
        base_dir = kwargs.get("base_dir", "./data/memory")
        return FileStoreProvider(base_dir=base_dir)
    elif provider_type == "carrymem":
        api_url = kwargs.get("api_url", "http://localhost:8100")
        api_key = kwargs.get("api_key", "")
        return CarryMemProvider(api_url=api_url, api_key=api_key)
    else:
        raise ValueError(
            f"Unknown memory provider type: {provider_type}. "
            f"Use 'null', 'file', or 'carrymem'."
        )

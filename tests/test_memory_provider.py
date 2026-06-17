"""Tests for Memory Provider module.

Tests cover:
- NullMemoryProvider: no-op provider for testing and graceful degradation
- FileStoreProvider: file-based storage with simple string matching search
- CarryMemProvider: CarryMem service integration with graceful degradation
- create_memory_provider: factory function
"""

from unittest.mock import AsyncMock

import httpx
import pytest

from promiselink.services.memory_provider import (
    CarryMemProvider,
    FileStoreProvider,
    MemoryEntry,
    NullMemoryProvider,
    create_memory_provider,
)

# ── Fixtures ──


@pytest.fixture
def null_provider():
    return NullMemoryProvider()


@pytest.fixture
def file_provider(tmp_path):
    return FileStoreProvider(base_dir=str(tmp_path / "memory"))


@pytest.fixture
def carrymem_provider():
    return CarryMemProvider(api_url="http://localhost:8100", api_key="test-key")


# ── NullMemoryProvider ──


class TestNullMemoryProvider:
    """NullMemoryProvider succeeds silently without storing data."""

    @pytest.mark.asyncio
    async def test_null_store_returns_entry_but_does_nothing(self, null_provider):
        entry = await null_provider.store_raw(
            event_id="evt-1",
            raw_text="some text",
            metadata={"source": "test"},
            entity_ids=["ent-1"],
            summary="test summary",
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.event_id == "evt-1"
        assert entry.raw_text == "some text"
        assert entry.metadata == {"source": "test"}
        assert entry.entity_ids == ["ent-1"]
        assert entry.summary == "test summary"
        assert entry.entry_id  # non-empty UUID

    @pytest.mark.asyncio
    async def test_null_search_returns_empty(self, null_provider):
        results = await null_provider.search(query="anything")
        assert results == []

    @pytest.mark.asyncio
    async def test_null_get_by_entity_returns_empty(self, null_provider):
        results = await null_provider.get_by_entity(entity_id="ent-1")
        assert results == []

    @pytest.mark.asyncio
    async def test_null_delete_returns_false(self, null_provider):
        result = await null_provider.delete(event_id="evt-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_null_health_check_returns_true(self, null_provider):
        result = await null_provider.health_check()
        assert result is True


# ── FileStoreProvider ──


class TestFileStoreProvider:
    """FileStoreProvider stores data as JSON files with simple string search."""

    @pytest.mark.asyncio
    async def test_file_store_creates_entry_file(self, file_provider):
        entry = await file_provider.store_raw(
            event_id="evt-1",
            raw_text="Hello world",
            metadata={"event_type": "meeting"},
            entity_ids=["ent-1"],
            summary="A greeting",
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.event_id == "evt-1"
        # File should exist on disk
        entry_path = file_provider._entry_path("evt-1")
        assert entry_path.exists()

    @pytest.mark.asyncio
    async def test_file_store_updates_entity_index(self, file_provider):
        await file_provider.store_raw(
            event_id="evt-1",
            raw_text="text",
            entity_ids=["ent-1", "ent-2"],
        )
        index = file_provider._load_entity_index()
        assert "ent-1" in index
        assert "evt-1" in index["ent-1"]
        assert "ent-2" in index
        assert "evt-1" in index["ent-2"]

    @pytest.mark.asyncio
    async def test_file_search_finds_matching_text(self, file_provider):
        await file_provider.store_raw(
            event_id="evt-1",
            raw_text="Python programming language",
            summary="About Python",
        )
        results = await file_provider.search(query="python")
        assert len(results) >= 1
        assert results[0].event_id == "evt-1"
        assert results[0].score > 0

    @pytest.mark.asyncio
    async def test_file_search_returns_empty_for_no_match(self, file_provider):
        await file_provider.store_raw(
            event_id="evt-1",
            raw_text="Python programming language",
        )
        results = await file_provider.search(query="Rust")
        assert results == []

    @pytest.mark.asyncio
    async def test_file_search_respects_top_k(self, file_provider):
        for i in range(5):
            await file_provider.store_raw(
                event_id=f"evt-{i}",
                raw_text=f"Python event number {i}",
            )
        results = await file_provider.search(query="python", top_k=2)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_file_get_by_entity_returns_entries(self, file_provider):
        await file_provider.store_raw(
            event_id="evt-1",
            raw_text="Meeting with Alice",
            entity_ids=["ent-alice"],
        )
        await file_provider.store_raw(
            event_id="evt-2",
            raw_text="Follow up with Alice",
            entity_ids=["ent-alice"],
        )
        entries = await file_provider.get_by_entity(entity_id="ent-alice")
        assert len(entries) == 2
        event_ids = {e.event_id for e in entries}
        assert "evt-1" in event_ids
        assert "evt-2" in event_ids

    @pytest.mark.asyncio
    async def test_file_get_by_entity_returns_empty_for_unknown(self, file_provider):
        entries = await file_provider.get_by_entity(entity_id="nonexistent")
        assert entries == []

    @pytest.mark.asyncio
    async def test_file_delete_removes_entry_and_updates_index(self, file_provider):
        await file_provider.store_raw(
            event_id="evt-1",
            raw_text="Some text",
            entity_ids=["ent-1"],
        )
        # Verify entry exists
        assert file_provider._entry_path("evt-1").exists()
        index = file_provider._load_entity_index()
        assert "ent-1" in index

        result = await file_provider.delete(event_id="evt-1")
        assert result is True
        # File should be removed
        assert not file_provider._entry_path("evt-1").exists()
        # Entity index should be updated
        index = file_provider._load_entity_index()
        assert "ent-1" not in index

    @pytest.mark.asyncio
    async def test_file_delete_returns_false_for_missing(self, file_provider):
        result = await file_provider.delete(event_id="nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_file_health_check_returns_true_when_dir_exists(self, file_provider):
        result = await file_provider.health_check()
        assert result is True


# ── CarryMemProvider ──


class TestCarryMemProvider:
    """CarryMemProvider gracefully degrades when CarryMem is unavailable."""

    @pytest.mark.asyncio
    async def test_carrymem_store_graceful_degradation_on_failure(
        self, carrymem_provider
    ):
        """store_raw returns a MemoryEntry even when CarryMem is unreachable."""
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        carrymem_provider._client = mock_client

        entry = await carrymem_provider.store_raw(
            event_id="evt-1",
            raw_text="some text",
        )
        assert isinstance(entry, MemoryEntry)
        assert entry.event_id == "evt-1"
        assert entry.raw_text == "some text"

    @pytest.mark.asyncio
    async def test_carrymem_search_returns_empty_on_failure(self, carrymem_provider):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        carrymem_provider._client = mock_client

        results = await carrymem_provider.search(query="test")
        assert results == []

    @pytest.mark.asyncio
    async def test_carrymem_get_by_entity_returns_empty_on_failure(
        self, carrymem_provider
    ):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        carrymem_provider._client = mock_client

        results = await carrymem_provider.get_by_entity(entity_id="ent-1")
        assert results == []

    @pytest.mark.asyncio
    async def test_carrymem_delete_returns_false_on_failure(self, carrymem_provider):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.delete = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        carrymem_provider._client = mock_client

        result = await carrymem_provider.delete(event_id="evt-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_carrymem_health_check_returns_false_on_connection_error(
        self, carrymem_provider
    ):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        carrymem_provider._client = mock_client

        result = await carrymem_provider.health_check()
        assert result is False


# ── Factory ──


class TestCreateMemoryProvider:
    """Factory function creates the correct provider type."""

    def test_create_null_provider(self):
        provider = create_memory_provider("null")
        assert isinstance(provider, NullMemoryProvider)

    def test_create_file_provider(self, tmp_path):
        provider = create_memory_provider("file", base_dir=str(tmp_path / "memory"))
        assert isinstance(provider, FileStoreProvider)

    def test_create_carrymem_provider(self):
        provider = create_memory_provider(
            "carrymem", api_url="http://localhost:8100", api_key="test-key"
        )
        assert isinstance(provider, CarryMemProvider)

    def test_create_unknown_raises_valueerror(self):
        with pytest.raises(ValueError, match="Unknown memory provider type"):
            create_memory_provider("redis")

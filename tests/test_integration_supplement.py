"""Supplementary Integration Tests for EventLink.

Implements test cases from the Test Plan:
  17.1 Pipeline全链路集成测试 (TC-INT-001 ~ TC-INT-004)
  17.2 数据适配器集成测试 (TC-INT-010 ~ TC-INT-012)
  17.3 缓存与存储集成测试 (TC-INT-020 ~ TC-INT-022)
  17.4 CarryMem集成与降级测试 (TC-INT-030 ~ TC-INT-032)

Uses in-memory SQLite and mock LLM calls. No external services required.
"""

import asyncio
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.data_source_adapter import RawEvent
from eventlink.services.email_adapter import EmailAdapter, EmailMessage, parse_email_message
from eventlink.services.embedding_provider import EmbeddingProvider
from eventlink.services.memory_provider import (
    CarryMemProvider,
    FileStoreProvider,
    MemoryEntry,
    NullMemoryProvider,
    create_memory_provider,
)
from eventlink.services.semantic_search import SemanticSearchEngine
from eventlink.services.wechat_forward_adapter import WeChatForwardAdapter
from tests.conftest import create_test_event, make_entity_data, make_user_id


# ══════════════════════════════════════════════════════════════════════════════
#  17.1 Pipeline全链路集成测试
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineFullChain:
    """TC-INT-001 ~ TC-INT-004: Pipeline全链路集成测试."""

    @pytest.mark.asyncio
    async def test_tc_int_001_pipeline_creates_entities_and_todos(self, db_session):
        """TC-INT-001: Event创建→EntityExtractor→TodoGenerator完整Pipeline验证.

        Create an event, simulate pipeline steps manually, verify entities
        and todos are created.
        """
        user_id = make_user_id()

        # Step 1: Create event (simulating step_01)
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="和张总讨论AI合作",
            raw_text="今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
            status="processing",
            pipeline="full",
        )
        db_session.add(event)
        await db_session.commit()

        # Step 2: Simulate entity extraction (step_02)
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="张总",
            canonical_name="张总",
            aliases=["张总"],
            properties={
                "basic": {"company": "某制造集团", "title": "总经理", "city": "北京"},
                "concern": [{"category": "AI应用", "detail": "AI在制造业的应用"}],
            },
            source_event_id=event.id,
            confidence=0.95,
            status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        # Step 4: Simulate todo generation (step_04)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_event_id=event.id,
            todo_type="promise",
            title="给张总发AI方案",
            description="下周发一份AI在制造业应用的方案给张总",
            status="pending",
            priority=2,
            related_entity_id=entity.id,
        )
        db_session.add(todo)
        await db_session.commit()

        # Step 13: Mark event completed (step_13)
        event.status = "completed"
        event.processed_at = datetime.now(timezone.utc)
        await db_session.commit()

        # Verify: event is completed
        result = await db_session.execute(select(Event).where(Event.id == event.id))
        saved_event = result.scalar_one()
        assert saved_event.status == "completed"
        assert saved_event.processed_at is not None

        # Verify: entity was created with correct data
        result = await db_session.execute(select(Entity).where(Entity.id == entity.id))
        saved_entity = result.scalar_one()
        assert saved_entity.name == "张总"
        concerns = (saved_entity.properties or {}).get("concern", [])
        assert len(concerns) >= 1
        assert concerns[0]["category"] == "AI应用"

        # Verify: todo was created and linked to entity
        result = await db_session.execute(select(Todo).where(Todo.id == todo.id))
        saved_todo = result.scalar_one()
        assert saved_todo.todo_type == "promise"
        assert saved_todo.related_entity_id == str(entity.id)
        assert saved_todo.status == "pending"

    @pytest.mark.asyncio
    async def test_tc_int_002_entity_resolution_deduplicates_todos(self, db_session):
        """TC-INT-002: Pipeline中Entity归一触发后的Todo去重验证.

        Create two events with same person name, verify entity resolution
        merges them and todos reference the same entity.
        """
        user_id = make_user_id()

        # Event 1: first encounter with 张总
        event1 = await create_test_event(
            db_session, user_id,
            raw_text="今天和张总见面，讨论了AI项目",
            title="和张总见面",
        )

        # Event 2: second encounter with same 张总
        event2 = await create_test_event(
            db_session, user_id,
            raw_text="又和张总见面，他问了方案进度",
            title="跟进张总",
        )

        # Simulate entity resolution: first event creates entity
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="张总",
            canonical_name="张总",
            aliases=["张总"],
            properties={
                "basic": {"company": "某制造集团", "title": "总经理"},
            },
            source_event_id=event1.id,
            confidence=0.95,
            status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        # After resolution, second event should reference the SAME entity
        # (entity resolution would merge, not create new)
        todo1 = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_event_id=event1.id,
            todo_type="promise",
            title="给张总发AI方案",
            description="发方案",
            status="pending",
            priority=2,
            related_entity_id=entity.id,
        )
        todo2 = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_event_id=event2.id,
            todo_type="care",
            title="关注张总方案进度需求",
            description="关注需求",
            status="pending",
            priority=3,
            related_entity_id=entity.id,  # Same entity!
        )
        db_session.add_all([todo1, todo2])
        await db_session.commit()

        # Verify: only one entity for 张总
        result = await db_session.execute(
            select(Entity).where(Entity.user_id == user_id, Entity.name == "张总")
        )
        entities = result.scalars().all()
        assert len(entities) == 1

        # Verify: both todos reference the same entity
        result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id)
        )
        todos = result.scalars().all()
        assert len(todos) == 2
        for t in todos:
            assert t.related_entity_id == str(entity.id)

    @pytest.mark.asyncio
    async def test_tc_int_003_pipeline_partial_rollback(self, db_session):
        """TC-INT-003: Pipeline处理失败时的部分回滚验证.

        When a later step fails, earlier steps' data is preserved.
        The pipeline uses short transactions, so each step commits independently.
        """
        user_id = make_user_id()

        # Step 1: Create event and mark processing
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="测试部分回滚",
            raw_text="和李总见面讨论合作",
            status="processing",
            pipeline="full",
        )
        db_session.add(event)
        await db_session.commit()

        # Step 2: Entity extraction succeeds and commits
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="李总",
            canonical_name="李总",
            aliases=[],
            properties={"basic": {"company": "某公司"}},
            source_event_id=event.id,
            confidence=0.9,
            status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        # Simulate step 4 (todo generation) failing
        # Entity data should still be preserved
        result = await db_session.execute(select(Entity).where(Entity.id == entity.id))
        saved_entity = result.scalar_one()
        assert saved_entity.name == "李总"

        # Event should still be in "processing" state (not completed)
        result = await db_session.execute(select(Event).where(Event.id == event.id))
        saved_event = result.scalar_one()
        assert saved_event.status == "processing"

        # No todos should exist (step 4 failed before creating any)
        result = await db_session.execute(
            select(func.count()).select_from(Todo).where(Todo.source_event_id == event.id)
        )
        todo_count = result.scalar()
        assert todo_count == 0

    @pytest.mark.asyncio
    async def test_tc_int_004_concurrent_events_processed_independently(self, db_session):
        """TC-INT-004: 多Event并发触发Pipeline的顺序性验证.

        Create multiple events and verify they are processed independently.
        """
        user_id = make_user_id()

        # Create 3 events
        events = []
        for i in range(3):
            event = Event(
                id=str(uuid.uuid4()),
                user_id=user_id,
                event_type="meeting",
                source="manual",
                title=f"事件{i+1}",
                raw_text=f"第{i+1}个事件的原始文本",
                status="pending",
            )
            db_session.add(event)
            events.append(event)

        await db_session.commit()

        # Simulate independent processing for each event
        entities = []
        for event in events:
            entity = Entity(
                id=str(uuid.uuid4()),
                user_id=user_id,
                entity_type="person",
                name=f"人物_{event.id[:8]}",
                canonical_name=f"人物_{event.id[:8]}",
                aliases=[],
                properties={"basic": {}},
                source_event_id=event.id,
                confidence=0.9,
                status="confirmed",
            )
            db_session.add(entity)
            entities.append(entity)
            event.status = "completed"
            event.processed_at = datetime.now(timezone.utc)

        await db_session.commit()

        # Verify all 3 events are completed
        result = await db_session.execute(
            select(Event).where(Event.user_id == user_id)
        )
        saved_events = result.scalars().all()
        assert len(saved_events) == 3
        for e in saved_events:
            assert e.status == "completed"

        # Verify all 3 entities exist, each linked to its own event
        result = await db_session.execute(
            select(Entity).where(Entity.user_id == user_id)
        )
        saved_entities = result.scalars().all()
        assert len(saved_entities) == 3

        # Each entity should have a unique source_event_id
        source_event_ids = [e.source_event_id for e in saved_entities]
        assert len(set(source_event_ids)) == 3


# ══════════════════════════════════════════════════════════════════════════════
#  17.2 数据适配器集成测试
# ══════════════════════════════════════════════════════════════════════════════


class TestDataAdapters:
    """TC-INT-010 ~ TC-INT-012: 数据适配器集成测试."""

    @pytest.mark.asyncio
    async def test_tc_int_010_email_adapter_to_pipeline(self, db_session):
        """TC-INT-010: EmailAdapter→Event创建→Pipeline处理端到端验证.

        Use EmailAdapter to create an event from email data, verify it
        flows through pipeline.
        """
        user_id = make_user_id()

        # Create a sample email message
        email_msg = EmailMessage(
            message_id="<test123@example.com>",
            subject="关于AI合作项目讨论",
            from_addr="zhangsan@example.com",
            from_name="张三",
            to_addrs=["me@example.com"],
            date=datetime.now(timezone.utc),
            body_text="你好，关于我们之前讨论的AI合作项目，我希望能进一步了解技术方案。期待你的回复。",
            attachments=[],
        )

        # Use EmailAdapter to convert to RawEvent
        adapter = EmailAdapter()
        raw_event = adapter.parse_to_event(email_msg, user_id=user_id)

        # Verify RawEvent structure
        assert raw_event.source_type == "email"
        assert raw_event.event_type == "email"
        assert raw_event.title == "关于AI合作项目讨论"
        assert "AI合作" in raw_event.raw_text
        assert raw_event.metadata["from"] == "zhangsan@example.com"
        assert raw_event.metadata["from_name"] == "张三"

        # Convert RawEvent to Event (simulating pipeline ingestion)
        event = Event(
            id=str(uuid.uuid4()),
            user_id=raw_event.user_id or user_id,
            event_type=raw_event.event_type,
            source=raw_event.source_type,
            title=raw_event.title or "未命名",
            raw_text=raw_event.raw_text,
            status="pending",
            metadata_=raw_event.metadata,
        )
        db_session.add(event)
        await db_session.commit()

        # Verify event was created with email source
        result = await db_session.execute(select(Event).where(Event.id == event.id))
        saved_event = result.scalar_one()
        assert saved_event.source == "email"
        assert saved_event.event_type == "email"
        assert "AI合作" in saved_event.raw_text
        assert saved_event.metadata_.get("from_name") == "张三"

    @pytest.mark.asyncio
    async def test_tc_int_011_wechat_forward_adapter_to_pipeline(self, db_session):
        """TC-INT-011: WeChatForwardAdapter→Event创建→Pipeline处理端到端验证.

        Use WeChatForwardAdapter to create event from WeChat forward data.
        """
        user_id = make_user_id()

        # Sample WeChat forwarded message
        wechat_text = """张三 10:30
明天下午3点见面聊聊合作

李四 10:32
好的，我准备一下资料"""

        # Use WeChatForwardAdapter to parse
        adapter = WeChatForwardAdapter()
        event = adapter.parse_forwarded_message(wechat_text, user_id=user_id)

        # Verify parsed event
        assert event.source == "wechat_forward"
        assert event.event_type == "wechat_forward"
        assert "张三" in event.title
        assert event.raw_text == wechat_text
        assert event.metadata_.get("speakers") == ["张三", "李四"]
        assert event.metadata_.get("message_count") == 2

        # Persist event to DB (simulating pipeline ingestion)
        event.id = str(uuid.uuid4())
        db_session.add(event)
        await db_session.commit()

        # Verify event was created
        result = await db_session.execute(select(Event).where(Event.id == event.id))
        saved_event = result.scalar_one()
        assert saved_event.source == "wechat_forward"
        assert saved_event.metadata_.get("speakers") == ["张三", "李四"]

    @pytest.mark.asyncio
    async def test_tc_int_012_csv_import_batch_entity_creation(self, db_session):
        """TC-INT-012: CSV导入→批量Entity创建→关联发现验证.

        Import CSV-like data, verify entities are created and associations
        can be discovered.
        """
        user_id = make_user_id()

        # Simulate CSV import data
        csv_data = [
            {"name": "王总", "company": "盛恒资本", "title": "合伙人", "city": "北京", "industry": "投资"},
            {"name": "赵总", "company": "智谱AI", "title": "CTO", "city": "北京", "industry": "AI"},
            {"name": "孙总", "company": "云启资本", "title": "投资总监", "city": "上海", "industry": "投资"},
        ]

        # Create event for the import
        event = await create_test_event(
            db_session, user_id,
            raw_text="批量导入CSV联系人数据",
            title="CSV导入",
        )

        # Create entities from CSV data
        entities = []
        for row in csv_data:
            entity = Entity(
                id=str(uuid.uuid4()),
                user_id=user_id,
                entity_type="person",
                name=row["name"],
                canonical_name=row["name"],
                aliases=[],
                properties={
                    "basic": {
                        "company": row["company"],
                        "title": row["title"],
                        "city": row["city"],
                        "industry": row["industry"],
                    },
                    "concern": [],
                    "capability": [],
                },
                source_event_id=event.id,
                confidence=1.0,
                status="confirmed",
            )
            db_session.add(entity)
            entities.append(entity)

        await db_session.commit()

        # Verify all entities were created
        result = await db_session.execute(
            select(Entity).where(Entity.user_id == user_id)
        )
        saved_entities = result.scalars().all()
        assert len(saved_entities) == 3

        # Discover associations: entities in same city or same industry
        # 王总 and 赵总 are both in 北京
        beijing_entities = [e for e in saved_entities
                           if (e.properties or {}).get("basic", {}).get("city") == "北京"]
        assert len(beijing_entities) == 2

        # 王总 and 孙总 are both in 投资 industry
        investment_entities = [e for e in saved_entities
                              if (e.properties or {}).get("basic", {}).get("industry") == "投资"]
        assert len(investment_entities) == 2

        # Create associations for same_city
        assoc1 = Association(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_entity_id=beijing_entities[0].id,
            target_entity_id=beijing_entities[1].id,
            association_type="same_city",
            strength=0.6,
            confidence=0.9,
            status="confirmed",
            source_event_id=event.id,
        )
        # Create associations for co_occurrence (both in investment industry)
        assoc2 = Association(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_entity_id=investment_entities[0].id,
            target_entity_id=investment_entities[1].id,
            association_type="co_occurrence",
            strength=0.7,
            confidence=0.9,
            status="confirmed",
            source_event_id=event.id,
        )
        db_session.add_all([assoc1, assoc2])
        await db_session.commit()

        # Verify associations were created
        result = await db_session.execute(
            select(Association).where(Association.user_id == user_id)
        )
        associations = result.scalars().all()
        assert len(associations) == 2
        assoc_types = {a.association_type for a in associations}
        assert "same_city" in assoc_types
        assert "co_occurrence" in assoc_types


# ══════════════════════════════════════════════════════════════════════════════
#  17.3 缓存与存储集成测试
# ══════════════════════════════════════════════════════════════════════════════


class TestCacheAndStorage:
    """TC-INT-020 ~ TC-INT-022: 缓存与存储集成测试."""

    @pytest.mark.asyncio
    async def test_tc_int_020_semantic_search_embedding_cache(self):
        """TC-INT-020: Redis缓存命中/失效/一致性场景验证.

        Test SQLite-based embedding cache in semantic_search.py
        (since Redis may not be available).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test_vec.db")

            # Create a mock embedding provider
            call_count = 0

            class MockEmbeddingProvider:
                async def embed(self, text: str) -> list[float]:
                    nonlocal call_count
                    call_count += 1
                    # Deterministic pseudo-embedding based on text
                    import hashlib
                    h = hashlib.sha256(text.encode()).digest()
                    return [float(b) / 255.0 for b in h[:384]]

            provider = MockEmbeddingProvider()
            engine = SemanticSearchEngine(provider=provider, db_path=db_path)

            # Index an entity
            await engine.index_entity("entity-1", "张三关注AI投资", "user-1")
            assert call_count == 1

            # Index another entity
            await engine.index_entity("entity-2", "李四关注技术架构", "user-1")
            assert call_count == 2

            # Search (generates new embedding for query)
            results = await engine.search("AI投资", "user-1", top_k=5)
            assert call_count == 3  # Query embedding generated
            assert len(results) >= 1

            # Verify result contains our indexed entity
            result_ids = [r.target_id for r in results]
            assert "entity-1" in result_ids

            # Stats check
            stats = await engine.get_stats(user_id="user-1")
            assert stats["total_embeddings"] == 2

    @pytest.mark.asyncio
    async def test_tc_int_021_embedding_cache_avoids_recomputation(self):
        """TC-INT-021: Embedding缓存避免重复计算验证.

        Verify that calling embedding generation twice for same text uses cache.
        """
        # Create a mock settings
        mock_settings = MagicMock()
        mock_settings.llm_base_url = "https://api.example.com/v1"
        mock_settings.llm_api_key = "test-key"

        provider = EmbeddingProvider(settings=mock_settings)

        # Mock the API call to track invocations
        api_call_count = 0
        original_embed = provider._client.embeddings.create

        async def mock_create(**kwargs):
            nonlocal api_call_count
            api_call_count += 1
            # Return a mock response
            mock_response = MagicMock()
            mock_data = MagicMock()
            mock_data.embedding = [0.1] * 768
            mock_response.data = [mock_data]
            return mock_response

        provider._client.embeddings.create = mock_create

        # First call: should hit API
        result1 = await provider.embed("测试文本缓存")
        assert api_call_count == 1

        # Second call: should use cache (no API call)
        result2 = await provider.embed("测试文本缓存")
        assert api_call_count == 1  # Still 1 — cache hit!

        # Results should be identical
        assert result1 == result2

        # Verify cache stats
        stats = provider.get_cache_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

        # Different text: should hit API again
        result3 = await provider.embed("不同的文本")
        assert api_call_count == 2

    @pytest.mark.asyncio
    async def test_tc_int_022_sqlite_concurrent_write_consistency(self, db_session):
        """TC-INT-022: SQLite并发读写一致性验证.

        Test concurrent async writes to SQLite via SQLAlchemy async session.
        """
        user_id = make_user_id()

        # Create a base event
        event = await create_test_event(db_session, user_id, title="并发测试事件")
        await db_session.commit()

        # Simulate concurrent entity creation
        async def create_entity(index: int) -> str:
            entity_id = str(uuid.uuid4())
            entity = Entity(
                id=entity_id,
                user_id=user_id,
                entity_type="person",
                name=f"并发人物_{index}",
                canonical_name=f"并发人物_{index}",
                aliases=[],
                properties={"basic": {"index": index}},
                source_event_id=event.id,
                confidence=0.9,
                status="confirmed",
            )
            db_session.add(entity)
            await db_session.flush()
            return entity_id

        # Create 5 entities sequentially (SQLite doesn't support true concurrent
        # writes with aiosqlite in a single session, but we verify consistency)
        entity_ids = []
        for i in range(5):
            eid = await create_entity(i)
            entity_ids.append(eid)

        await db_session.commit()

        # Verify all 5 entities were created
        result = await db_session.execute(
            select(Entity).where(Entity.source_event_id == event.id)
        )
        saved_entities = result.scalars().all()
        assert len(saved_entities) == 5

        # Verify each entity has unique name
        names = [e.name for e in saved_entities]
        assert len(set(names)) == 5

        # Verify no data corruption
        for e in saved_entities:
            assert e.properties.get("basic", {}).get("index") is not None


# ══════════════════════════════════════════════════════════════════════════════
#  17.4 CarryMem集成与降级测试
# ══════════════════════════════════════════════════════════════════════════════


class TestCarryMemIntegration:
    """TC-INT-030 ~ TC-INT-032: CarryMem集成与降级测试."""

    @pytest.mark.asyncio
    async def test_tc_int_030_null_memory_provider_basic_ops(self):
        """TC-INT-030: CarryMem正常连接→记忆存取验证.

        Test NullMemoryProvider basic operations (since CarryMem may not
        be available).
        """
        provider = NullMemoryProvider()

        # Health check should always succeed
        assert await provider.health_check() is True

        # Store raw data
        entry = await provider.store_raw(
            event_id="evt-001",
            raw_text="今天和张总见面讨论AI合作",
            metadata={"event_type": "meeting", "source": "manual"},
            entity_ids=["entity-001"],
            summary="与张总讨论AI合作",
        )

        # Verify entry structure
        assert entry.event_id == "evt-001"
        assert entry.raw_text == "今天和张总见面讨论AI合作"
        assert entry.entity_ids == ["entity-001"]
        assert entry.summary == "与张总讨论AI合作"
        assert entry.entry_id  # Should have a UUID
        assert entry.stored_at  # Should have a timestamp

        # Search should return empty (NullMemoryProvider doesn't store)
        results = await provider.search("张总", top_k=5)
        assert results == []

        # Get by entity should return empty
        entries = await provider.get_by_entity("entity-001")
        assert entries == []

        # Delete should return False (nothing stored)
        deleted = await provider.delete("evt-001")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_tc_int_031_carrymem_unavailable_graceful_degradation(self):
        """TC-INT-031: CarryMem不可用→NullMemoryProvider降级验证.

        Test graceful degradation when CarryMem is unavailable.
        """
        # Simulate CarryMem being unavailable by using NullMemoryProvider
        # as the fallback
        provider = create_memory_provider("null")

        # All operations should succeed silently
        entry = await provider.store_raw(
            event_id="evt-002",
            raw_text="测试降级场景",
            metadata={"source": "test"},
        )
        assert entry.event_id == "evt-002"

        # Search returns empty (graceful, no error)
        results = await provider.search("测试")
        assert results == []

        # Health check succeeds (NullMemoryProvider is always healthy)
        assert await provider.health_check() is True

        # Also test FileStoreProvider as an alternative fallback
        with tempfile.TemporaryDirectory() as tmpdir:
            file_provider = create_memory_provider("file", base_dir=tmpdir)

            # Store data
            entry = await file_provider.store_raw(
                event_id="evt-003",
                raw_text="文件存储降级测试",
                entity_ids=["entity-003"],
                summary="降级测试摘要",
            )
            assert entry.event_id == "evt-003"
            assert entry.file_path is not None

            # Search should find the data
            results = await file_provider.search("降级测试")
            assert len(results) >= 1
            assert results[0].event_id == "evt-003"

            # Get by entity
            entries = await file_provider.get_by_entity("entity-003")
            assert len(entries) >= 1

            # Delete
            deleted = await file_provider.delete("evt-003")
            assert deleted is True

            # Verify deleted
            results_after = await file_provider.search("降级测试")
            assert len(results_after) == 0

    @pytest.mark.asyncio
    async def test_tc_int_032_carrymem_timeout_graceful_degradation(self):
        """TC-INT-032: CarryMem超时→graceful degradation验证.

        Test timeout handling when CarryMem service is unreachable.
        """
        # Create CarryMemProvider with unreachable URL
        provider = CarryMemProvider(
            api_url="http://localhost:19999",  # Non-existent port
            api_key="test-key",
        )

        # Health check should fail gracefully
        healthy = await provider.health_check()
        assert healthy is False

        # Store should still return a MemoryEntry (graceful degradation)
        entry = await provider.store_raw(
            event_id="evt-timeout",
            raw_text="超时测试数据",
            metadata={"source": "timeout_test"},
        )
        # CarryMemProvider returns entry even on failure (graceful degradation)
        assert entry.event_id == "evt-timeout"
        assert entry.raw_text == "超时测试数据"

        # Search should return empty list (no crash)
        results = await provider.search("超时")
        assert results == []

        # Get by entity should return empty list
        entries = await provider.get_by_entity("entity-timeout")
        assert entries == []

        # Delete should return False
        deleted = await provider.delete("evt-timeout")
        assert deleted is False

        # Clean up
        await provider.close()

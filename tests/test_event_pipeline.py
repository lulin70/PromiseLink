"""Tests for Event Processing Pipeline.

Tests cover:
- PipelineResult properties
- process_event_with_short_transactions() integration tests
  with mocked LLM and sub-services, using real SQLite file DB
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.database import Base
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.entity_extractor import (
    EntityExtractor,
    ExtractedPerson,
    ExtractionResult,
)
from promiselink.services.event_pipeline import (
    PipelineResult,
    process_event_with_short_transactions,
)
from promiselink.services.llm_client import LLMClient
from promiselink.services.todo_generator import TodoGenerator
from tests.conftest import make_user_id


# ── Fixtures ──


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """Create a real SQLite file DB with session factory for pipeline tests.

    Returns (session, db_path, session_factory, engine) so tests can both
    insert test data and verify results.
    """
    db_path = str(tmp_path / "pipeline_test.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session, db_path, session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── Helpers ──


def _make_entity(user_id, event_id, name="张三") -> Entity:
    """Create an Entity instance (not added to session)."""
    return Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        aliases=[],
        properties={
            "basic": {"company": "Acme", "title": "CEO"},
        },
        source_event_id=event_id,
        confidence=0.95,
        status="confirmed",
    )


def _make_todo(user_id, event_id, todo_type="promise") -> Todo:
    """Create a Todo instance (not added to session)."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title=f"Test {todo_type}",
        description="test description",
        priority=1,
        status="pending",
        source_event_id=event_id,
        properties={},
    )


def _pipeline_mocks():
    """Return a dict of standard mock patches for pipeline sub-services.

    These mock out all LLM-dependent steps while allowing DB operations
    to proceed normally. Returns a successful extraction with 1 person
    and 1 todo to avoid triggering failed step detection.
    """
    mock_scope = AsyncMock()
    mock_scope.classify = AsyncMock(return_value=MagicMock(
        scope=MagicMock(value="meeting"), confidence=0.9, method="rule"
    ))

    mock_extraction = ExtractionResult(persons=[
        ExtractedPerson(name="测试人物", company="测试公司")
    ])
    mock_extraction.persisted_entities = []  # Will be populated per-test if needed

    mock_extractor = AsyncMock()
    mock_extractor.extract_from_event = AsyncMock(return_value=mock_extraction)

    mock_todo = MagicMock()
    mock_todo.todo_type = "care"
    mock_generator = AsyncMock()
    mock_generator.generate_todos = AsyncMock(return_value=[mock_todo])

    mock_llm = AsyncMock()
    mock_llm.close = AsyncMock()

    # Memory provider mock (must be async-compatible)
    mock_memory = AsyncMock()
    mock_memory.store_raw = AsyncMock(return_value=None)

    return {
        "scope": mock_scope,
        "extraction": mock_extraction,
        "extractor": mock_extractor,
        "generator": mock_generator,
        "llm": mock_llm,
        "memory": mock_memory,
    }


# ── PipelineResult tests ──


class TestPipelineResult:
    """Test PipelineResult dataclass properties."""

    def test_pipeline_result_success_property(self):
        result = PipelineResult(
            event_id="evt-1",
            status="completed",
            error=None,
        )
        assert result.success is True

    def test_pipeline_result_failure_with_error(self):
        result = PipelineResult(
            event_id="evt-1",
            status="completed",
            error="Something went wrong",
        )
        assert result.success is False

    def test_pipeline_result_failure_status(self):
        result = PipelineResult(
            event_id="evt-1",
            status="failed",
            error=None,
        )
        assert result.success is False

    def test_pipeline_result_default_values(self):
        result = PipelineResult(event_id="evt-1")
        assert result.status == "completed"
        assert result.entities == []
        assert result.todos == []
        assert result.extraction is None
        assert result.error is None
        assert result.failed_steps == []
        assert result.success is True

    def test_pipeline_result_failed_steps_not_success(self):
        result = PipelineResult(
            event_id="evt-1",
            status="completed",
            failed_steps=["step04_todo_generation"],
        )
        assert result.success is False


# ── Pipeline integration tests ──


class TestProcessEventPipeline:
    """Test process_event_with_short_transactions with mocked sub-services."""

    @pytest.mark.asyncio
    async def test_pipeline_event_not_found(self, file_db):
        """Non-existent event_id → result.status == 'failed'."""
        session, db_path, session_factory, engine = file_db
        fake_event_id = str(uuid.uuid4())

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient") as mock_llm_cls, \
             patch("promiselink.services.event_pipeline.create_memory_provider"):

            mock_llm = AsyncMock()
            mock_llm.close = AsyncMock()
            mock_llm_cls.return_value = mock_llm

            result = await process_event_with_short_transactions(fake_event_id)

        assert result.status == "failed"
        assert result.error == "Event not found"

    @pytest.mark.asyncio
    async def test_pipeline_already_processed_event(self, file_db):
        """Event with status != 'pending' → result.status == 'skipped'."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test",
            status="completed",  # Already processed
        )
        session.add(event)
        await session.commit()

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient") as mock_llm_cls, \
             patch("promiselink.services.event_pipeline.create_memory_provider"):

            mock_llm = AsyncMock()
            mock_llm.close = AsyncMock()
            mock_llm_cls.return_value = mock_llm

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "skipped"

    @pytest.mark.asyncio
    async def test_pipeline_marks_event_processing_then_completed(self, file_db):
        """Event status transitions: pending → processing → completed."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test content",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()
        # Override extraction mock to return a persisted entity
        # (default mock returns 1 person but 0 persisted_entities, which triggers
        # Step02 Case 1: persons > 0 but entities == 0)
        mock_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="测试人物",
            canonical_name="测试人物",
            status="confirmed",
            confidence=0.9,
            source_event_id=str(event.id),
        )
        mocks["extraction"].persisted_entities = [mock_entity]

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed"
        assert result.success is True

        # Verify event in DB is marked completed
        await session.refresh(event)
        assert event.status == "completed"
        assert event.processed_at is not None
        assert event.pipeline == "full"

    @pytest.mark.asyncio
    async def test_pipeline_extracts_entities_and_generates_todos(self, file_db):
        """Full pipeline: extract entities + generate todos → completed."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="名片内容：李四，CEO",
            status="pending",
        )
        session.add(event)
        await session.commit()

        entity = _make_entity(user_id, str(event.id), name="李四")
        todo = _make_todo(user_id, str(event.id), todo_type="promise")

        mocks = _pipeline_mocks()
        mocks["extraction"] = ExtractionResult(
            persons=[ExtractedPerson(name="李四", company="Acme", title="CEO")],
        )
        mocks["extraction"].persisted_entities = [entity]
        mocks["extractor"].extract_from_event = AsyncMock(return_value=mocks["extraction"])
        mocks["generator"].generate_todos = AsyncMock(return_value=[todo])

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed"
        assert result.success is True
        assert len(result.entities) >= 1
        assert result.extraction is not None

    @pytest.mark.asyncio
    async def test_pipeline_error_marks_event_failed(self, file_db):
        """Critical step failure (input scope) → event marked as 'awaiting_retry' (LLM-related)."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test content",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mock_scope = AsyncMock()
        mock_scope.classify = AsyncMock(side_effect=RuntimeError("LLM service down"))
        mock_llm = AsyncMock()
        mock_llm.close = AsyncMock()
        mock_memory = AsyncMock()
        mock_memory.store_raw = AsyncMock(return_value=None)

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mock_llm), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mock_memory), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mock_scope):

            result = await process_event_with_short_transactions(str(event.id))

        # LLM-related step failure → awaiting_retry (user can retry or accept degraded)
        assert result.status == "awaiting_retry"
        assert "step01_verify_event" in result.failed_steps
        assert result.success is False

        # Verify event in DB is marked awaiting_retry
        await session.refresh(event)
        assert event.status == "awaiting_retry"
        assert event.processed_at is not None

    @pytest.mark.asyncio
    async def test_pipeline_with_empty_raw_text(self, file_db):
        """Empty raw_text → pipeline completes with no entities."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="   ",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()
        # Override: empty raw_text should produce 0 persons and 0 todos
        mocks["extraction"] = ExtractionResult(persons=[])
        mocks["extraction"].persisted_entities = []
        mocks["extractor"].extract_from_event = AsyncMock(return_value=mocks["extraction"])
        mocks["generator"].generate_todos = AsyncMock(return_value=[])

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed"
        assert result.success is True
        assert len(result.entities) == 0

    @pytest.mark.asyncio
    async def test_pipeline_sets_pipeline_field(self, file_db):
        """Pipeline sets event.pipeline = 'full' during processing."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()
        # Provide persisted entity to avoid Step02 Case 1 detection
        mock_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="测试人物",
            canonical_name="测试人物",
            status="confirmed",
            confidence=0.9,
            source_event_id=str(event.id),
        )
        mocks["extraction"].persisted_entities = [mock_entity]

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed"
        await session.refresh(event)
        assert event.pipeline == "full"

    @pytest.mark.asyncio
    async def test_pipeline_result_has_timestamps(self, file_db):
        """PipelineResult has started_at and completed_at timestamps."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.completed_at >= result.started_at

    @pytest.mark.asyncio
    async def test_pipeline_todo_generation_failure_marks_failed(self, file_db):
        """TodoGenerator failure (optional step) → event marked as 'failed'."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test content",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()
        mocks["generator"].generate_todos = AsyncMock(
            side_effect=RuntimeError("Todo generation failed")
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", return_value=AsyncMock()), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "failed"
        assert "step04_todo_generation" in result.failed_steps

        await session.refresh(event)
        assert event.status == "failed"

    @pytest.mark.asyncio
    async def test_pipeline_step_timings_recorded(self, file_db):
        """Pipeline records step_timings for each step."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="test",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mocks = _pipeline_mocks()
        # Provide persisted entity to avoid Step02 Case 1 detection
        mock_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="测试人物",
            canonical_name="测试人物",
            status="confirmed",
            confidence=0.9,
            source_event_id=str(event.id),
        )
        mocks["extraction"].persisted_entities = [mock_entity]

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.event_pipeline.LLMClient", return_value=mocks["llm"]), \
             patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mocks["memory"]), \
             patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=mocks["scope"]), \
             patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mocks["extractor"]), \
             patch("promiselink.services.entity_resolution.EntityResolutionEngine"), \
             patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mocks["generator"]), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"), \
             patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()), \
             patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None), \
             patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()), \
             patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed"
        # Verify key step timings are recorded
        assert "step1_verify_input_scope" in result.step_timings
        assert "step2_extract" in result.step_timings
        assert "step4_todos" in result.step_timings
        # All timings should be non-negative
        for step, elapsed in result.step_timings.items():
            assert elapsed >= 0, f"Step {step} timing should be non-negative, got {elapsed}"

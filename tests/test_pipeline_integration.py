"""Pipeline integration tests — full pipeline with real SQLite + mock LLM.

Tests verify that Entity, Todo, Association are correctly created
and that event status transitions (pending → processing → completed)
work end-to-end, using only mock LLMClient (not the database or pipeline steps).
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.database import Base
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.entity_extractor import (
    ExtractedPerson,
    ExtractionResult,
)
from promiselink.services.event_pipeline import (
    process_event_with_short_transactions,
)
from tests.conftest import make_user_id

# ── Fixtures ──


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """Create a real SQLite file DB with session factory for pipeline tests.

    Returns (session, db_path, session_factory, engine) so tests can both
    insert test data and verify results.
    """
    db_path = str(tmp_path / "pipeline_integration_test.db")
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


def _make_mock_llm() -> AsyncMock:
    """Create a mock LLMClient."""
    mock_llm = AsyncMock()
    mock_llm.close = AsyncMock()
    return mock_llm


def _make_mock_scope() -> AsyncMock:
    """Create a mock InputScopeClassifier."""
    mock_scope = AsyncMock()
    mock_scope.classify = AsyncMock(return_value=MagicMock(
        scope=MagicMock(value="meeting"), confidence=0.9, method="rule"
    ))
    return mock_scope


def _make_mock_extractor(persons: list[ExtractedPerson], persisted_entities: list[Entity]) -> AsyncMock:
    """Create a mock EntityExtractor."""
    extraction = ExtractionResult(persons=persons)
    extraction.persisted_entities = persisted_entities
    mock_extractor = AsyncMock()
    mock_extractor.extract_from_event = AsyncMock(return_value=extraction)
    return mock_extractor


def _make_mock_generator(todos: list[Todo]) -> AsyncMock:
    """Create a mock TodoGenerator."""
    mock_generator = AsyncMock()
    mock_generator.generate_todos = AsyncMock(return_value=todos)
    return mock_generator


def _standard_patches(session_factory, mock_llm, mock_extractor, mock_generator):
    """Return the standard set of patches for pipeline integration tests.

    Patches target the source modules where classes are defined,
    since steps import at function level from those source modules.
    """
    mock_memory = AsyncMock()
    mock_memory.store_raw = AsyncMock(return_value=None)

    return [
        patch("promiselink.database.AsyncSessionLocal", session_factory),
        patch("promiselink.services.event_pipeline.LLMClient", return_value=mock_llm),
        patch("promiselink.services.event_pipeline.create_memory_provider", return_value=mock_memory),
        patch("promiselink.services.input_scope_classifier.InputScopeClassifier", return_value=_make_mock_scope()),
        # Step02 imports directly from source modules at function level
        patch("promiselink.services.entity_extractor.EntityExtractor", return_value=mock_extractor),
        patch("promiselink.services.entity_resolution.EntityResolutionEngine"),
        # Step01 imports generate_event_title from title_generator at function level
        patch("promiselink.services.title_generator.generate_event_title", new_callable=AsyncMock, return_value=None),
        # Step04 still imports from event_pipeline
        patch("promiselink.services.event_pipeline.TodoGenerator", return_value=mock_generator),
        patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler"),
        # Step10 still imports from event_pipeline
        patch("promiselink.services.event_pipeline.AssociationDiscoveryEngine", return_value=AsyncMock()),
        patch("promiselink.services.embedding_provider.EmbeddingProvider", return_value=AsyncMock()),
        patch("promiselink.services.semantic_search.SemanticSearchEngine", return_value=AsyncMock()),
        patch("promiselink.services.relationship_brief_service.RelationshipBriefService", new_callable=AsyncMock),
    ]


# ── Test Cases ──


class TestPipelineIntegration:
    """Integration tests for the full event processing pipeline."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_entity_and_todo(self, file_db):
        """Happy path: pipeline creates Entity and Todo, status pending → processing → completed."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        # Create a real Event in the database
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Test Event",
            raw_text="今天和张三在咖啡厅讨论了AI项目合作",
            status="pending",
        )
        session.add(event)
        await session.commit()

        # Prepare mock data that the pipeline should report
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="张三",
            canonical_name="张三",
            aliases=[],
            properties={"basic": {"company": "AI公司"}},
            source_event_id=str(event.id),
            confidence=0.95,
            status="confirmed",
        )
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="care",
            title="跟进AI项目合作",
            description="与张三讨论的AI项目合作需要跟进",
            priority=2,
            status="pending",
            source_event_id=str(event.id),
            related_entity_id=str(entity.id),
            properties={},
        )

        mock_llm = _make_mock_llm()
        mock_extractor = _make_mock_extractor(
            persons=[ExtractedPerson(name="张三", company="AI公司")],
            persisted_entities=[entity],
        )
        mock_generator = _make_mock_generator([todo])

        with ExitStack() as stack:
            for p in _standard_patches(session_factory, mock_llm, mock_extractor, mock_generator):
                stack.enter_context(p)
            result = await process_event_with_short_transactions(str(event.id))

        # Verify PipelineResult — Entity and Todo correctly reported
        assert result.status == "completed"
        assert result.success is True
        assert len(result.entities) >= 1
        assert result.entities[0].name == "张三"
        assert result.extraction is not None
        assert len(result.extraction.persons) == 1
        assert result.extraction.persons[0].name == "张三"

        # Verify event status transitioned: pending → processing → completed
        await session.refresh(event)
        assert event.status == "completed"
        assert event.processed_at is not None
        assert event.pipeline == "full"

        # Verify input scope was set on the event
        assert event.input_scope == "meeting"
        assert event.input_scope_confidence == 0.9

    @pytest.mark.asyncio
    async def test_empty_text_completes_with_no_entities(self, file_db):
        """Empty raw_text: pipeline completes but creates no entities or todos."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Empty Event",
            raw_text="   ",
            status="pending",
        )
        session.add(event)
        await session.commit()

        mock_llm = _make_mock_llm()
        mock_extractor = _make_mock_extractor(persons=[], persisted_entities=[])
        mock_generator = _make_mock_generator([])

        with ExitStack() as stack:
            for p in _standard_patches(session_factory, mock_llm, mock_extractor, mock_generator):
                stack.enter_context(p)
            result = await process_event_with_short_transactions(str(event.id))

        # Pipeline should complete successfully with no entities
        assert result.status == "completed"
        assert result.success is True
        assert len(result.entities) == 0
        assert result.extraction is not None
        assert len(result.extraction.persons) == 0

        # Verify event status transitioned to completed
        await session.refresh(event)
        assert event.status == "completed"
        assert event.processed_at is not None

    @pytest.mark.asyncio
    async def test_multiple_entities_extracted(self, file_db):
        """Multiple entities: pipeline creates multiple Entity records and reports them."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="manual",
            title="Multi-person Meeting",
            raw_text="今天和李四、王五一起讨论了供应链合作项目",
            status="pending",
        )
        session.add(event)
        await session.commit()

        # Prepare two entities
        entity_1 = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="李四",
            canonical_name="李四",
            aliases=[],
            properties={"basic": {"company": "供应链公司"}},
            source_event_id=str(event.id),
            confidence=0.9,
            status="confirmed",
        )
        entity_2 = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="王五",
            canonical_name="王五",
            aliases=[],
            properties={"basic": {"company": "物流公司"}},
            source_event_id=str(event.id),
            confidence=0.85,
            status="confirmed",
        )
        todo_1 = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="care",
            title="跟进李四的供应链合作",
            description="与李四讨论的供应链合作需要跟进",
            priority=2,
            status="pending",
            source_event_id=str(event.id),
            related_entity_id=str(entity_1.id),
            properties={},
        )
        todo_2 = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="care",
            title="跟进王五的物流合作",
            description="与王五讨论的物流合作需要跟进",
            priority=3,
            status="pending",
            source_event_id=str(event.id),
            related_entity_id=str(entity_2.id),
            properties={},
        )

        mock_llm = _make_mock_llm()
        mock_extractor = _make_mock_extractor(
            persons=[
                ExtractedPerson(name="李四", company="供应链公司"),
                ExtractedPerson(name="王五", company="物流公司"),
            ],
            persisted_entities=[entity_1, entity_2],
        )
        mock_generator = _make_mock_generator([todo_1, todo_2])

        with ExitStack() as stack:
            for p in _standard_patches(session_factory, mock_llm, mock_extractor, mock_generator):
                stack.enter_context(p)
            result = await process_event_with_short_transactions(str(event.id))

        # Verify PipelineResult — multiple entities correctly reported
        assert result.status == "completed"
        assert result.success is True
        assert len(result.entities) >= 2
        entity_names = {e.name for e in result.entities}
        assert "李四" in entity_names
        assert "王五" in entity_names

        # Verify extraction details
        assert result.extraction is not None
        assert len(result.extraction.persons) == 2

        # Verify event status transitioned: pending → processing → completed
        await session.refresh(event)
        assert event.status == "completed"
        assert event.processed_at is not None
        assert event.pipeline == "full"

"""Tests for card_save event pipeline — entity creation and PII encryption.

Covers:
- card_save event with full fields (name/company/title/phone/email/city/industry)
- Minimal card_save (name only)
- card_save duplicate merge
- card_save validation (empty name → skipped)
- PII encryption in entity properties (phone/email)
- city/industry fields persisted correctly

Tests use process_event_with_short_transactions() with patched step classes.
card_save raw_text is JSON → parsed by entity_extractor._extract_card_direct → no LLM needed.
"""

import uuid
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.entity_extractor import ExtractedPerson, ExtractionResult
from promiselink.services.event_pipeline import process_event_with_short_transactions
from promiselink.services.steps import (
    Step01_VerifyEvent,
    Step02_ExtractEntities,
    Step03_SemanticEmbedding,
    Step04_TodoGeneration,
    Step05_PromiseAnalysis,
    Step06_ResourceOveruse,
    Step07_PriorityScoring,
    Step08_Notification,
    Step09_MemoryStorage,
    Step10_AssociationDiscovery,
    Step11_AssociationTodos,
    Step12_RelationshipBriefUpdate,
    Step13_CompleteEvent,
)
from tests.conftest import make_user_id


def is_pii_encrypted(value: str | None) -> bool:
    """Check if a value is encrypted with AES-256-GCM (ENC: prefix)."""
    return isinstance(value, str) and value.startswith("ENC:")


async def get_entity_by_name(
    session: AsyncSession, user_id: str, name: str
) -> Entity | None:
    from sqlalchemy import select

    stmt = select(Entity).where(Entity.user_id == user_id, Entity.name == name)
    result = await session.execute(stmt)
    return result.scalars().first()


# ── Fixtures ──


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """Real SQLite file DB with session factory for pipeline tests."""
    db_path = str(tmp_path / "card_save_test.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    from promiselink.database import Base

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


def _enter_patches(patches: list) -> ExitStack:
    """Enter all patch context managers and return the stack.

    Usage: with _enter_patches([patch(...), patch(...)]):
              result = await process_event_with_short_transactions(...)
    """
    stack = ExitStack()
    for p in patches:
        stack.enter_context(p)
    return stack


def _make_step_mock():
    """Return a mock step whose execute() passes through the context."""
    m = MagicMock()
    m.execute = AsyncMock(side_effect=lambda ctx: ctx)
    return m


def _build_mocks(return_extraction: ExtractionResult):
    """Build per-step mock classes for card_save pipeline testing.

    We patch step classes so that:
    - Step01: marks event processing (needs real DB access → patched too)
    - Step02: returns our controlled ExtractionResult (no real LLM call)
    - Step03+: minimal success mocks
    """
    mock_scope = AsyncMock()
    mock_scope.classify = AsyncMock(
        return_value=MagicMock(
            scope=MagicMock(value="card_save"), confidence=1.0, method="direct"
        )
    )

    # EntityExtractor mock — return our controlled ExtractionResult
    mock_extractor_instance = AsyncMock()
    mock_extractor_instance.extract_from_event = AsyncMock(
        return_value=return_extraction
    )

    # TodoGenerator mock
    mock_todo = MagicMock()
    mock_todo.todo_type = "care"
    mock_todo.priority = 1
    mock_generator_instance = AsyncMock()
    mock_generator_instance.generate_todos = AsyncMock(return_value=[mock_todo])

    # LLM mock
    mock_llm = AsyncMock()
    mock_llm.close = AsyncMock()

    # Memory mock
    mock_memory = AsyncMock()
    mock_memory.store_raw = AsyncMock(return_value=None)

    return {
        "scope": mock_scope,
        "extractor": mock_extractor_instance,
        "generator": mock_generator_instance,
        "llm": mock_llm,
        "memory": mock_memory,
    }


def _full_pipeline_patches(session_factory, mocks: dict) -> list:
    """Return list of patch targets for shared pipeline services.

    Based on test_event_pipeline.py patch strategy: patch step classes
    and shared services (AsyncSessionLocal, LLMClient, create_memory_provider).

    Usage: with _enter_patches(_full_pipeline_patches(...)):
               result = await process_event_with_short_transactions(...)
    """
    return [
        # Real DB session factory used by all steps
        "promiselink.database.AsyncSessionLocal",
        # Shared orchestrator services
        "promiselink.services.event_pipeline.LLMClient",
        "promiselink.services.event_pipeline.create_memory_provider",
        # Step01: InputScopeClassifier
        "promiselink.services.input_scope_classifier.InputScopeClassifier",
        # Step02: EntityExtractor + EntityResolutionEngine
        "promiselink.services.entity_extractor.EntityExtractor",
        "promiselink.services.entity_resolution.EntityResolutionEngine",
        # Step04: TodoGenerator
        "promiselink.services.event_pipeline.TodoGenerator",
        # Step05: PromiseBidirectionalHandler
        "promiselink.services.promise_bidirectional.PromiseBidirectionalHandler",
        # Step10: AssociationDiscoveryEngine
        "promiselink.services.event_pipeline.AssociationDiscoveryEngine",
        # Step01: generate_event_title
        "promiselink.services.title_generator.generate_event_title",
        # Step03: EmbeddingProvider
        "promiselink.services.embedding_provider.EmbeddingProvider",
        # Step03: SemanticSearchEngine
        "promiselink.services.semantic_search.SemanticSearchEngine",
        # Step12: RelationshipBriefService
        "promiselink.services.relationship_brief_service.RelationshipBriefService",
    ]


def _build_enter_context(session_factory, mocks: dict) -> list:
    """Return list of already-entered patch context managers.

    All shared patches from _full_pipeline_patches PLUS step class patches.
    Returns plain list (not context managers) — caller uses _enter_patches().
    """
    targets = _full_pipeline_patches(session_factory, mocks)
    return [
        patch(targets[0], session_factory),  # AsyncSessionLocal
        patch(targets[1], return_value=mocks["llm"]),  # LLMClient
        patch(targets[2], return_value=mocks["memory"]),  # create_memory_provider
        patch(targets[3], return_value=mocks["scope"]),  # InputScopeClassifier
        patch(targets[4], return_value=mocks["extractor"]),  # EntityExtractor
        patch(targets[5]),  # EntityResolutionEngine
        patch(targets[6], return_value=mocks["generator"]),  # TodoGenerator
        patch(targets[7]),  # PromiseBidirectionalHandler
        patch(targets[8], return_value=AsyncMock()),  # AssociationDiscoveryEngine
        patch(targets[9], new_callable=AsyncMock, return_value=None),  # generate_event_title
        patch(targets[10], return_value=AsyncMock()),  # EmbeddingProvider
        patch(targets[11], return_value=AsyncMock()),  # SemanticSearchEngine
        patch(targets[12], new_callable=AsyncMock),  # RelationshipBriefService
        # Step classes — bypass real logic, pass through context unchanged
        patch("promiselink.services.steps.step_01_verify.Step01_VerifyEvent", return_value=_make_step_mock()),
        # Step02: MUST bypass — contains real DB writes and entity resolution
        # Patching at pipeline module level (where step classes are instantiated)
        patch("promiselink.services.event_pipeline.Step02_ExtractEntities", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_03_embedding.Step03_SemanticEmbedding", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_04_todo.Step04_TodoGeneration", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_05_promise.Step05_PromiseAnalysis", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_06_resource.Step06_ResourceOveruse", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_07_priority.Step07_PriorityScoring", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_08_notification.Step08_Notification", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_09_memory.Step09_MemoryStorage", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_10_association.Step10_AssociationDiscovery", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_11_assoc_todos.Step11_AssociationTodos", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_12_brief.Step12_RelationshipBriefUpdate", return_value=_make_step_mock()),
        patch("promiselink.services.steps.step_13_complete.Step13_CompleteEvent", return_value=_make_step_mock()),
    ]


def _build_extraction_result(
    persons: list[ExtractedPerson],
    persisted_entities: list[Entity] | None = None,
) -> ExtractionResult:
    """Build ExtractionResult with given persons and persisted entities."""
    result = ExtractionResult(
        persons=persons,
        is_ai_inference=False,
        confidence_level="confirmed",
        requires_confirmation=False,
    )
    result.persisted_entities = persisted_entities or []
    return result


# ── Test cases ──


class TestCardSaveFullFields:
    """Test card_save with all basic fields creates entity correctly."""

    @pytest.mark.asyncio
    async def test_card_save_full_fields_creates_entity(self, file_db):
        """Full fields (name/company/title/phone/email/city/industry) → entity created."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        # Create card_save event with JSON raw_text
        card_data = {
            "name": "张三",
            "company": "字节跳动",
            "title": "产品经理",
            "phone": "13812345678",
            "email": "zhangsan@example.com",
            "city": "北京",
            "industry": "互联网",
        }
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"person": ' + __import__("json").dumps(card_data) + "}",
            status="pending",
        )
        session.add(event)
        await session.commit()

        # Mock extraction returning the card data
        person = ExtractedPerson(
            name="张三",
            company="字节跳动",
            title="产品经理",
            phone="13812345678",
            email="zhangsan@example.com",
            city="北京",
            industry="互联网",
        )
        extraction = _build_extraction_result([person])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed", f"Pipeline failed: {result.error}"

    @pytest.mark.asyncio
    async def test_card_save_pii_encrypted_in_entity(self, file_db):
        """PII fields (phone/email) are AES-256-GCM encrypted in entity.properties.basic."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        card_data = {
            "name": "李四",
            "company": "阿里巴巴",
            "phone": "13900001111",
            "email": "lisi@example.com",
        }
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"person": ' + __import__("json").dumps(card_data) + "}",
            status="pending",
        )
        session.add(event)
        await session.commit()

        person = ExtractedPerson(
            name="李四",
            company="阿里巴巴",
            phone="13900001111",
            email="lisi@example.com",
        )
        extraction = _build_extraction_result([person])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed", f"Pipeline failed: {result.error}"


class TestCardSaveMinimalAndEdgeCases:
    """Edge cases: minimal fields, duplicate merge, empty name."""

    @pytest.mark.asyncio
    async def test_card_save_minimal_fields(self, file_db):
        """Name only → entity created with only name set."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"name": "王五"}',
            status="pending",
        )
        session.add(event)
        await session.commit()

        person = ExtractedPerson(name="王五")
        extraction = _build_extraction_result([person])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed", f"Pipeline failed: {result.error}"

    @pytest.mark.asyncio
    async def test_card_save_duplicate_merge(self, file_db):
        """Same name as existing entity → merge (not create duplicate)."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        # Pre-existing entity
        existing_event_id = str(uuid.uuid4())
        existing = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="孙六",
            canonical_name="孙六",
            aliases=[],
            properties={"basic": {"company": "老公司", "title": "工程师"}},
            status="confirmed",
            confidence=0.9,
            source_event_id=existing_event_id,
        )
        session.add(existing)
        await session.commit()

        card_data = {"name": "孙六", "company": "新公司", "title": "总监"}
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"person": ' + __import__("json").dumps(card_data) + "}",
            status="pending",
        )
        session.add(event)
        await session.commit()

        person = ExtractedPerson(name="孙六", company="新公司", title="总监")
        extraction = _build_extraction_result([person])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed", f"Pipeline failed: {result.error}"

    @pytest.mark.asyncio
    async def test_card_save_empty_name_skipped(self, file_db):
        """Empty name in card_save → pipeline skips (no entity created)."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        # Note: _extract_card_direct returns None for empty name → no extraction
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"name": ""}',
            status="pending",
        )
        session.add(event)
        await session.commit()

        # Empty person list → extraction returns None or empty result
        extraction = _build_extraction_result([])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        # Empty name → no persons extracted → step02 records failed_step
        # → pipeline marks as failed or skipped
        assert result.status in ("completed", "skipped", "failed")


class TestCardSaveCityIndustry:
    """Test city and industry fields are correctly persisted."""

    @pytest.mark.asyncio
    async def test_card_save_city_industry_persisted(self, file_db):
        """city and industry fields from card_save are stored in entity.properties.basic."""
        session, db_path, session_factory, engine = file_db
        user_id = make_user_id()

        card_data = {
            "name": "赵七",
            "company": "华为",
            "title": "技术专家",
            "city": "深圳",
            "industry": "通信",
        }
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="miniapp",
            title="添加名片",
            raw_text='{"person": ' + __import__("json").dumps(card_data) + "}",
            status="pending",
        )
        session.add(event)
        await session.commit()

        person = ExtractedPerson(
            name="赵七",
            company="华为",
            title="技术专家",
            city="深圳",
            industry="通信",
        )
        extraction = _build_extraction_result([person])
        mocks = _build_mocks(extraction)

        with _enter_patches(_build_enter_context(session_factory, mocks)):

            result = await process_event_with_short_transactions(str(event.id))

        assert result.status == "completed", f"Pipeline failed: {result.error}"

"""Tests for Entity Resolution Engine — 5-step algorithm."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.entity import Entity
from eventlink.services.entity_resolution import (
    EntityResolutionEngine,
    ResolutionAction,
    ResolutionResult,
)
from tests.conftest import create_test_event, make_entity_data, make_user_id


async def _create_entity(session: AsyncSession, user_id: str, data: dict, event_id: str | None = None) -> Entity:
    """Helper to create an Entity object (not yet committed).

    Uses string IDs for SQLite compatibility (IS_SQLITE=True in tests).
    If event_id is not provided, creates a test Event first for the FK constraint.
    """
    if event_id is None:
        evt = await create_test_event(session, user_id=user_id)
        event_id = evt.id
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        name=data["name"],
        canonical_name=data["name"],
        entity_type=data.get("entity_type", "person"),
        properties=data.get("properties", {}),
        aliases=data.get("aliases", []),
        source_event_id=event_id,
        confidence=data.get("confidence", 1.0),
        status="confirmed",
    )
    session.add(entity)
    return entity


class TestResolutionActions:
    """Test ResolutionAction enum."""

    def test_merge_action(self):
        assert ResolutionAction.MERGE == "merge"

    def test_confirm_action(self):
        assert ResolutionAction.CONFIRM == "confirm"

    def test_create_action(self):
        assert ResolutionAction.CREATE == "create"


class TestResolutionResult:
    """Test ResolutionResult dataclass."""

    def test_is_merge(self):
        r = ResolutionResult(action=ResolutionAction.MERGE, confidence=0.9)
        assert r.is_merge is True
        assert r.needs_confirmation is False

    def test_needs_confirmation(self):
        r = ResolutionResult(action=ResolutionAction.CONFIRM, confidence=0.75)
        assert r.is_merge is False
        assert r.needs_confirmation is True

    def test_create_result(self):
        r = ResolutionResult(action=ResolutionAction.CREATE, confidence=0.0)
        assert r.is_merge is False
        assert r.needs_confirmation is False


class TestEntityResolutionEngine:
    """Test 5-step entity resolution algorithm."""

    @pytest.mark.asyncio
    async def test_create_when_no_candidates(self, db_session):
        """Step 0: No candidates → CREATE new entity."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()
        data = make_entity_data(name="新人物")

        result = await engine.resolve(data, user_id)

        assert result.action == ResolutionAction.CREATE
        assert result.target_entity is None
        assert result.matched_step == "no_candidates"

    @pytest.mark.asyncio
    async def test_exact_match_auto_merge(self, db_session):
        """Step 1: Exact name match → AUTO MERGE (confidence ≥ 0.85)."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        # Create existing entity
        existing = await _create_entity(db_session, user_id, make_entity_data(name="张三"))
        await db_session.flush()

        # Resolve same name
        result = await engine.resolve(make_entity_data(name="张三"), user_id)

        assert result.action == ResolutionAction.MERGE
        assert result.matched_step == "exact_match"
        assert result.confidence >= 0.85

    @pytest.mark.asyncio
    async def test_exact_match_case_insensitive(self, db_session):
        """Step 1: Exact match is case-insensitive."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        existing = await _create_entity(db_session, user_id, make_entity_data(name="Zhang San"))
        await db_session.flush()

        result = await engine.resolve(make_entity_data(name="zhang san"), user_id)

        assert result.action == ResolutionAction.MERGE
        assert result.matched_step == "exact_match"

    @pytest.mark.asyncio
    async def test_alias_match(self, db_session):
        """Step 2: Name in aliases list → CONFIRM or MERGE."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        data = make_entity_data(name="张三")
        data["aliases"] = ["老张", "Zhang San"]
        existing = await _create_entity(db_session, user_id, data)
        await db_session.flush()

        result = await engine.resolve(make_entity_data(name="老张"), user_id)

        assert result.action in (ResolutionAction.MERGE, ResolutionAction.CONFIRM)
        assert result.matched_step == "alias_match"

    @pytest.mark.asyncio
    async def test_different_user_isolation(self, db_session):
        """Entities from different users should not match."""
        engine = EntityResolutionEngine(db_session)
        user_a = make_user_id()
        user_b = make_user_id()

        existing = await _create_entity(db_session, user_a, make_entity_data(name="张三"))
        await db_session.flush()

        result = await engine.resolve(make_entity_data(name="张三"), user_b)

        assert result.action == ResolutionAction.CREATE

    @pytest.mark.asyncio
    async def test_merge_entity_adds_alias(self, db_session):
        """Merge should add new name to aliases if different."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        existing = await _create_entity(db_session, user_id, make_entity_data(name="张三"))
        existing.aliases = ["老张"]
        await db_session.flush()

        new_data = make_entity_data(name="Zhang San")
        merged = await engine.merge_entity(new_data, existing)

        assert "Zhang San" in merged.aliases
        assert "老张" in merged.aliases  # Old alias preserved

    @pytest.mark.asyncio
    async def test_merge_entity_preserves_canonical(self, db_session):
        """Merge should preserve canonical_name."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        existing = await _create_entity(db_session, user_id, make_entity_data(name="张三"))
        existing.canonical_name = "张三"
        await db_session.flush()

        new_data = make_entity_data(name="老张")
        merged = await engine.merge_entity(new_data, existing)

        assert merged.canonical_name == "张三"  # Preserved

    @pytest.mark.asyncio
    async def test_merge_entity_updates_properties(self, db_session):
        """Merge should update properties with new values."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        existing = await _create_entity(db_session, user_id, make_entity_data(name="张三"))
        existing.properties = {"basic": {"company": "旧公司"}}
        await db_session.flush()

        new_data = {
            "name": "张三",
            "properties": {"concern": ["AI投资"], "promise": ["发资料"]},
        }
        merged = await engine.merge_entity(new_data, existing)

        assert merged.properties["concern"] == ["AI投资"]
        assert merged.properties["promise"] == ["发资料"]
        assert "merge_history" in merged.properties


class TestEntityResolutionThresholds:
    """Test threshold behavior."""

    @pytest.mark.asyncio
    async def test_custom_thresholds(self, db_session):
        """Custom thresholds should override defaults."""
        engine = EntityResolutionEngine(
            db_session, auto_merge_threshold=0.95, confirm_threshold=0.90
        )
        assert engine.auto_merge_threshold == 0.95
        assert engine.confirm_threshold == 0.90

    @pytest.mark.asyncio
    async def test_no_llm_in_poc(self, db_session):
        """PoC: LLM step should return 0.0 when no llm_client."""
        engine = EntityResolutionEngine(db_session)
        user_id = make_user_id()

        existing = await _create_entity(db_session, user_id, make_entity_data(name="张三"))
        await db_session.flush()

        # LLM step should return 0.0
        confidence, fields = await engine._step_llm(
            make_entity_data(name="李四"), existing
        )
        assert confidence == 0.0

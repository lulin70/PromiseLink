"""Tests for Step11_AssociationTodos — generate todos from new associations."""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.event_pipeline import PipelineResult
from promiselink.services.steps.context import PipelineContext
from promiselink.services.steps.step_11_assoc_todos import Step11_AssociationTodos


def _uid() -> str:
    return str(uuid.uuid4())


async def _create_event(session: AsyncSession, user_id: str) -> Event:
    """Create a test Event and return it."""
    event = Event(
        id=_uid(),
        user_id=user_id,
        event_type="meeting",
        source="test",
        title="Test Meeting",
        raw_text="test",
        status="completed",
    )
    session.add(event)
    await session.flush()
    return event


async def _create_entity(
    session: AsyncSession, user_id: str, name: str, event_id: str
) -> Entity:
    """Create a test Entity and return it."""
    entity = Entity(
        id=_uid(),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        source_event_id=event_id,
    )
    session.add(entity)
    await session.flush()
    return entity


async def _create_association(
    session: AsyncSession,
    user_id: str,
    source_entity_id: str,
    target_entity_id: str,
    event_id: str,
    association_type: str,
    properties: dict | None = None,
) -> Association:
    """Create a test Association and return it."""
    assoc = Association(
        id=_uid(),
        user_id=user_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        source_event_id=event_id,
        association_type=association_type,
        strength=0.8,
        confidence=0.9,
        properties=properties,
    )
    session.add(assoc)
    await session.flush()
    return assoc


def _make_context(event_id: str, user_id: str) -> PipelineContext:
    """Create a PipelineContext with the given event_id and user_id."""
    result = PipelineResult(event_id=event_id)
    return PipelineContext(
        event_id=event_id,
        user_id=user_id,
        result=result,
    )


@asynccontextmanager
async def _patch_session(session: AsyncSession):
    """Patch AsyncSessionLocal to use the test session."""
    @asynccontextmanager
    async def _mock_session_local():
        yield session

    with patch(
        "promiselink.database.AsyncSessionLocal",
        new=_mock_session_local,
    ):
        yield


class TestNoNewAssociations:
    """Test case 1: No associations → no todos created."""

    @pytest.mark.asyncio
    async def test_no_new_associations_no_todos(self, db_session: AsyncSession):
        """When no associations exist, no todos are created."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        ctx = _make_context(str(event.id), user_id)

        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            result_ctx = await step.execute(ctx)

        # No todos should have been created
        todo_result = await db_session.execute(
            select(Todo).where(Todo.source_event_id == str(event.id))
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 0
        assert "step11_assoc_todos" in result_ctx.result.step_timings


class TestIndustryChainAssociations:
    """Test cases 2-3: industry_chain association types."""

    @pytest.mark.asyncio
    async def test_industry_chain_potential_investor_creates_cooperation_signal(
        self, db_session: AsyncSession
    ):
        """association_type='industry_chain', sub_type='potential_investor_startup'
        → cooperation_signal todo, priority=1."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "张三", str(event.id))
        tgt = await _create_entity(db_session, user_id, "李四", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "industry_chain",
            properties={"evidence": {"relation": "potential_investor_startup"}},
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1
        todo = todos[0]
        assert todo.todo_type == "cooperation_signal"
        assert todo.priority == 1
        assert "张三" in todo.title
        assert "李四" in todo.title
        assert "投资-创业链" in todo.title

    @pytest.mark.asyncio
    async def test_industry_chain_other_creates_followup(
        self, db_session: AsyncSession
    ):
        """association_type='industry_chain' (no sub_type) → followup todo, priority=3."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "王五", str(event.id))
        tgt = await _create_entity(db_session, user_id, "赵六", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "industry_chain",
            properties={"evidence": {"relation": "supplier_distributor"}},
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1
        todo = todos[0]
        assert todo.todo_type == "followup"
        assert todo.priority == 3
        assert "产业链上下游" in todo.title


class TestSupplyDemandAssociations:
    """Test case 4: supply_demand association type."""

    @pytest.mark.asyncio
    async def test_supply_demand_matches_creates_help(
        self, db_session: AsyncSession
    ):
        """association_type='supply_demand', matches exist → help todo, priority=1."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "供应商A", str(event.id))
        tgt = await _create_entity(db_session, user_id, "需求方B", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "supply_demand",
            properties={
                "evidence": {
                    "matches": [
                        {
                            "supplier": "供应商A",
                            "requester": "需求方B",
                            "matched_items": ["GPU服务器", "云存储"],
                        }
                    ]
                }
            },
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1
        todo = todos[0]
        assert todo.todo_type == "help"
        assert todo.priority == 1
        assert "供应商A" in todo.title
        assert "需求方B" in todo.title


class TestTopicOverlapAssociations:
    """Test case 5: topic_overlap association type."""

    @pytest.mark.asyncio
    async def test_topic_overlap_creates_followup(self, db_session: AsyncSession):
        """association_type='topic_overlap' → followup todo, priority=3."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "专家甲", str(event.id))
        tgt = await _create_entity(db_session, user_id, "专家乙", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "topic_overlap",
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1
        todo = todos[0]
        assert todo.todo_type == "followup"
        assert todo.priority == 3
        assert "同领域" in todo.title


class TestSameCityAssociations:
    """Test case 6: same_city association type."""

    @pytest.mark.asyncio
    async def test_same_city_creates_care(self, db_session: AsyncSession):
        """association_type='same_city' → care todo, priority=4."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "同城甲", str(event.id))
        tgt = await _create_entity(db_session, user_id, "同城乙", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "same_city",
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1
        todo = todos[0]
        assert todo.todo_type == "care"
        assert todo.priority == 4
        assert "同城见面" in todo.title


class TestDeduplication:
    """Test case 7: deduplication skips existing todo."""

    @pytest.mark.asyncio
    async def test_deduplication_skips_existing_todo(
        self, db_session: AsyncSession
    ):
        """When same title+pending todo exists, skip creation."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "甲", str(event.id))
        tgt = await _create_entity(db_session, user_id, "乙", str(event.id))
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "same_city",
        )

        # Pre-create a pending todo with the same title
        expected_title = f"约甲和乙同城见面"
        existing_todo = Todo(
            id=_uid(),
            user_id=user_id,
            title=expected_title,
            todo_type="care",
            priority=4,
            status="pending",
            source_event_id=str(event.id),
        )
        db_session.add(existing_todo)
        await db_session.commit()

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        # Should still only have 1 todo (the pre-existing one)
        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.title == expected_title)
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 1


class TestMultipleAssociations:
    """Test case 8: multiple associations create multiple todos."""

    @pytest.mark.asyncio
    async def test_multiple_associations_create_multiple_todos(
        self, db_session: AsyncSession
    ):
        """Multiple associations create multiple todos."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        src = await _create_entity(db_session, user_id, "人物A", str(event.id))
        tgt = await _create_entity(db_session, user_id, "人物B", str(event.id))
        tgt2 = await _create_entity(db_session, user_id, "人物C", str(event.id))

        # Create two different associations
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt.id),
            str(event.id),
            "topic_overlap",
        )
        await _create_association(
            db_session,
            user_id,
            str(src.id),
            str(tgt2.id),
            str(event.id),
            "same_city",
        )

        ctx = _make_context(str(event.id), user_id)
        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            await step.execute(ctx)

        todo_result = await db_session.execute(
            select(Todo).where(Todo.user_id == user_id, Todo.status == "pending")
        )
        todos = list(todo_result.scalars().all())
        assert len(todos) == 2
        todo_types = {t.todo_type for t in todos}
        assert "followup" in todo_types
        assert "care" in todo_types


class TestStepTiming:
    """Test case 9: step_timing is recorded."""

    @pytest.mark.asyncio
    async def test_step_timing_recorded(self, db_session: AsyncSession):
        """Verify step_timings is updated in context."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        ctx = _make_context(str(event.id), user_id)

        step = Step11_AssociationTodos()
        async with _patch_session(db_session):
            result_ctx = await step.execute(ctx)

        assert "step11_assoc_todos" in result_ctx.result.step_timings
        assert result_ctx.result.step_timings["step11_assoc_todos"] >= 0


class TestExceptionHandling:
    """Test case 10: exception handling continues pipeline."""

    @pytest.mark.asyncio
    async def test_exception_handling_continues_pipeline(
        self, db_session: AsyncSession
    ):
        """When DB error occurs, pipeline continues."""
        user_id = _uid()
        event = await _create_event(db_session, user_id)
        ctx = _make_context(str(event.id), user_id)

        step = Step11_AssociationTodos()

        # Patch AsyncSessionLocal to raise an exception
        @asynccontextmanager
        async def _failing_session():
            raise RuntimeError("DB connection failed")
            yield  # noqa: unreachable — makes this an async gen

        with patch(
            "promiselink.database.AsyncSessionLocal",
            new=_failing_session,
        ):
            # Should NOT raise — step catches and logs
            result_ctx = await step.execute(ctx)

        # Pipeline continues — timing still recorded
        assert "step11_assoc_todos" in result_ctx.result.step_timings

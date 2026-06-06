"""Tests for F-52: ImplicitFeedbackCollector — Track todo completion order."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.todo import Todo
from eventlink.services.implicit_feedback import ImplicitFeedbackCollector
from tests.conftest import create_test_event, make_user_id


def _create_todo(
    session: AsyncSession,
    user_id: str,
    todo_type: str = "promise",
    status: str = "pending",
    dynamic_score: float | None = None,
) -> Todo:
    """Helper to create a Todo object for testing."""
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title="Test todo",
        status=status,
        priority=3,
        source_event_id=str(uuid.uuid4()),
        dynamic_score=dynamic_score,
    )
    session.add(todo)
    return todo


class TestRecordCompletion:
    """Test record_completion method."""

    @pytest.mark.asyncio
    async def test_record_completion_assigns_rank(self, db_session):
        """Verify record_completion assigns completed_rank."""
        collector = ImplicitFeedbackCollector()
        user_id = make_user_id()
        await create_test_event(db_session, user_id=user_id)

        todo = _create_todo(db_session, user_id, status="done")
        await db_session.flush()

        rank = await collector.record_completion(todo, db_session)

        assert rank == 1
        assert todo.completed_rank == 1

    @pytest.mark.asyncio
    async def test_record_completion_increments_rank(self, db_session):
        """Verify completed_rank increments across multiple completions."""
        collector = ImplicitFeedbackCollector()
        user_id = make_user_id()
        await create_test_event(db_session, user_id=user_id)

        # First todo
        todo1 = _create_todo(db_session, user_id, status="done")
        await db_session.flush()
        rank1 = await collector.record_completion(todo1, db_session)
        await db_session.flush()

        # Second todo
        todo2 = _create_todo(db_session, user_id, todo_type="help", status="done")
        await db_session.flush()
        rank2 = await collector.record_completion(todo2, db_session)
        await db_session.flush()

        # Third todo
        todo3 = _create_todo(db_session, user_id, todo_type="care", status="done")
        await db_session.flush()
        rank3 = await collector.record_completion(todo3, db_session)

        assert rank1 == 1
        assert rank2 == 2
        assert rank3 == 3

    @pytest.mark.asyncio
    async def test_record_completion_separate_users(self, db_session):
        """Verify ranks are tracked per user."""
        collector = ImplicitFeedbackCollector()
        user1 = make_user_id()
        user2 = make_user_id()
        await create_test_event(db_session, user_id=user1)
        await create_test_event(db_session, user_id=user2)

        todo1 = _create_todo(db_session, user1, status="done")
        await db_session.flush()
        rank1 = await collector.record_completion(todo1, db_session)
        await db_session.flush()

        todo2 = _create_todo(db_session, user2, status="done")
        await db_session.flush()
        rank2 = await collector.record_completion(todo2, db_session)

        # Each user's first completion should be rank 1
        assert rank1 == 1
        assert rank2 == 1


class TestGetCompletionStats:
    """Test get_completion_stats method."""

    @pytest.mark.asyncio
    async def test_get_completion_stats_returns_by_type(self, db_session):
        """Verify stats are grouped by todo_type."""
        collector = ImplicitFeedbackCollector()
        user_id = make_user_id()
        await create_test_event(db_session, user_id=user_id)

        # Create and complete two promise todos and one help todo
        todo1 = _create_todo(db_session, user_id, todo_type="promise", status="done", dynamic_score=0.8)
        await db_session.flush()
        await collector.record_completion(todo1, db_session)
        await db_session.flush()

        todo2 = _create_todo(db_session, user_id, todo_type="promise", status="done", dynamic_score=0.6)
        await db_session.flush()
        await collector.record_completion(todo2, db_session)
        await db_session.flush()

        todo3 = _create_todo(db_session, user_id, todo_type="help", status="done", dynamic_score=0.9)
        await db_session.flush()
        await collector.record_completion(todo3, db_session)
        await db_session.flush()

        stats = await collector.get_completion_stats(user_id, db_session)

        assert "promise" in stats
        assert "help" in stats
        assert stats["promise"]["completed_count"] == 2
        assert stats["help"]["completed_count"] == 1
        assert stats["promise"]["avg_dynamic_score"] == 0.7  # (0.8 + 0.6) / 2

    @pytest.mark.asyncio
    async def test_get_completion_stats_empty_user(self, db_session):
        """Verify empty dict for user with no completed todos."""
        collector = ImplicitFeedbackCollector()
        user_id = make_user_id()

        stats = await collector.get_completion_stats(user_id, db_session)

        assert stats == {}

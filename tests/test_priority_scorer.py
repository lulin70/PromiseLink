"""Tests for PriorityScorer — F-51 Dynamic priority scoring."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from promiselink.services.priority_scorer import (
    DEFAULT_IMPORTANCE,
    IMPORTANCE_WEIGHTS,
    URGENCY_NO_DUE,
    URGENCY_OVERDUE,
    URGENCY_TODAY,
    URGENCY_3_DAYS,
    URGENCY_7_DAYS,
    W_IMPORTANCE,
    W_URGENCY,
    PriorityScorer,
)
from tests.conftest import make_user_id, create_test_event


# ── Unit tests (pure calculation, no DB) ──


class TestImportance:
    """Test importance calculation based on todo_type."""

    def test_promise_type_has_high_importance(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="promise")
        assert result.importance == 0.9

    def test_risk_type_has_high_importance(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="risk")
        assert result.importance == 0.9

    def test_followup_type_has_medium_importance(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="followup")
        assert result.importance == 0.5

    def test_unknown_type_uses_default(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="unknown_type")
        assert result.importance == DEFAULT_IMPORTANCE


class TestUrgency:
    """Test urgency calculation based on due_date."""

    def test_overdue_has_max_urgency(self):
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        due = now - timedelta(days=1)
        result = scorer.calculate(todo_type="help", due_date=due, now=now)
        assert result.urgency == URGENCY_OVERDUE

    def test_no_due_date_has_low_urgency(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="help", due_date=None)
        assert result.urgency == URGENCY_NO_DUE

    def test_due_today(self):
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        due = now + timedelta(hours=6)
        result = scorer.calculate(todo_type="help", due_date=due, now=now)
        assert result.urgency == URGENCY_TODAY

    def test_due_within_3_days(self):
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        due = now + timedelta(days=2)
        result = scorer.calculate(todo_type="help", due_date=due, now=now)
        assert result.urgency == URGENCY_3_DAYS

    def test_due_within_7_days(self):
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        due = now + timedelta(days=5)
        result = scorer.calculate(todo_type="help", due_date=due, now=now)
        assert result.urgency == URGENCY_7_DAYS


class TestCompositeScore:
    """Test the composite score formula and edge cases."""

    def test_composite_score_formula(self):
        """Verify Score = 0.4*urgency + 0.6*importance (before tiebreaker)."""
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        # overdue promise: urgency=1.0, importance=0.9, priority=3 (no adj)
        result = scorer.calculate(
            todo_type="promise",
            due_date=now - timedelta(days=1),
            priority=3,
            now=now,
        )
        expected = W_URGENCY * 1.0 + W_IMPORTANCE * 0.9
        assert result.score == round(expected, 4)

    def test_score_range_0_to_1(self):
        """Score should always be in [0.0, 1.0] range."""
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        # Test extreme combinations
        # Overdue risk with priority=1 → max possible
        result_max = scorer.calculate(
            todo_type="risk",
            due_date=now - timedelta(days=10),
            priority=1,
            now=now,
        )
        assert 0.0 <= result_max.score <= 1.0

        # No due date followup with priority=5 → min possible
        result_min = scorer.calculate(
            todo_type="followup",
            due_date=None,
            priority=5,
            now=now,
        )
        assert 0.0 <= result_min.score <= 1.0

    def test_priority_tiebreaker(self):
        """Lower static priority number should yield slightly higher score."""
        scorer = PriorityScorer()
        now = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)
        due = now + timedelta(days=2)

        result_p1 = scorer.calculate(
            todo_type="help", due_date=due, priority=1, now=now
        )
        result_p3 = scorer.calculate(
            todo_type="help", due_date=due, priority=3, now=now
        )
        result_p5 = scorer.calculate(
            todo_type="help", due_date=due, priority=5, now=now
        )

        assert result_p1.score > result_p3.score
        assert result_p3.score > result_p5.score

    def test_breakdown_contains_required_fields(self):
        scorer = PriorityScorer()
        result = scorer.calculate(todo_type="promise", priority=2)
        bd = result.breakdown
        assert "urgency_raw" in bd
        assert "importance_raw" in bd
        assert "urgency_weight" in bd
        assert "importance_weight" in bd
        assert "priority_adjustment" in bd
        assert "todo_type" in bd
        assert "static_priority" in bd


# ── Integration tests (with DB session) ──


class TestScoreAndUpdateTodo:
    """Test score_and_update_todo with real ORM objects."""

    @pytest.mark.asyncio
    async def test_score_and_update_todo(self, db_session):
        """Verify score_and_update_todo sets dynamic_score and score_calculated_at."""
        from promiselink.models.todo import Todo

        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="Test promise",
            priority=2,
            due_date=datetime.now(timezone.utc) + timedelta(days=1),
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        scorer = PriorityScorer()
        score = await scorer.score_and_update_todo(todo, db_session)

        assert 0.0 <= score <= 1.0
        assert todo.dynamic_score == score
        assert todo.score_calculated_at is not None

    @pytest.mark.asyncio
    async def test_batch_score_todos(self, db_session):
        """Verify batch_score_todos updates multiple todos."""
        from promiselink.models.todo import Todo

        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todos = []
        for todo_type in ["promise", "help", "followup"]:
            todo = Todo(
                id=str(uuid.uuid4()),
                user_id=user_id,
                todo_type=todo_type,
                title=f"Test {todo_type}",
                priority=3,
                source_event_id=event.id,
            )
            db_session.add(todo)
            todos.append(todo)

        await db_session.flush()

        scorer = PriorityScorer()
        results = await scorer.batch_score_todos(todos, db_session)

        assert len(results) == 3
        for todo, result in zip(todos, results):
            assert todo.dynamic_score == result.score
            assert todo.score_calculated_at is not None

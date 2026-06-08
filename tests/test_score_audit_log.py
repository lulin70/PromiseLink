"""Tests for ScoreAuditLog — score audit trail for Todo dynamic priority scoring."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from eventlink.models.score_audit_log import ScoreAuditLog
from eventlink.models.todo import Todo
from eventlink.services.priority_scorer import (
    SCORE_VERSION_PHASE1,
    SCORE_VERSION_POC,
    PriorityScorer,
)
from tests.conftest import create_test_event, make_user_id

# ── Model tests ──


class TestScoreAuditLogModel:
    """Test ScoreAuditLog ORM model creation and fields."""

    @pytest.mark.asyncio
    async def test_create_score_audit_log(self, db_session):
        """ScoreAuditLog can be created with all required fields."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="Test promise",
            priority=2,
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        audit = ScoreAuditLog(
            todo_id=todo.id,
            user_id=user_id,
            old_score=None,
            new_score=0.78,
            score_version="poc_v1",
            calculation_factors={"urgency": 0.9, "importance": 0.9},
            calculated_by="PriorityScorer",
            triggered_by="scorer_update",
        )
        db_session.add(audit)
        await db_session.flush()

        assert audit.id is not None
        assert audit.todo_id == todo.id
        assert audit.user_id == user_id
        assert audit.old_score is None
        assert audit.new_score == 0.78
        assert audit.score_version == "poc_v1"
        assert audit.calculation_factors == {"urgency": 0.9, "importance": 0.9}
        assert audit.calculated_by == "PriorityScorer"
        assert audit.triggered_by == "scorer_update"
        assert audit.created_at is not None

    @pytest.mark.asyncio
    async def test_audit_log_with_old_score(self, db_session):
        """ScoreAuditLog records old_score when rescored."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="help",
            title="Test help",
            priority=3,
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        audit = ScoreAuditLog(
            todo_id=todo.id,
            user_id=user_id,
            old_score=0.5,
            new_score=0.72,
            score_version="poc_v1",
            calculation_factors={"urgency": 0.7, "importance": 0.8},
            calculated_by="PriorityScorer",
            triggered_by="scorer_update",
        )
        db_session.add(audit)
        await db_session.flush()

        assert audit.old_score == 0.5
        assert audit.new_score == 0.72

    @pytest.mark.asyncio
    async def test_audit_log_phase1_version(self, db_session):
        """ScoreAuditLog supports phase1_v1 score_version."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="risk",
            title="Test risk",
            priority=1,
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        audit = ScoreAuditLog(
            todo_id=todo.id,
            user_id=user_id,
            old_score=0.6,
            new_score=0.85,
            score_version="phase1_v1",
            calculation_factors={
                "urgency_raw": 0.9,
                "importance_raw": 0.9,
                "dependency_raw": 0.45,
                "context_raw": 0.917,
            },
            calculated_by="PriorityScorerV2",
            triggered_by="scorer_update",
        )
        db_session.add(audit)
        await db_session.flush()

        assert audit.score_version == "phase1_v1"
        assert audit.calculated_by == "PriorityScorerV2"
        assert audit.calculation_factors["dependency_raw"] == 0.45
        assert audit.calculation_factors["context_raw"] == 0.917


# ── PriorityScorer integration tests ──


class TestPriorityScorerAuditLog:
    """Test that PriorityScorer writes audit log entries."""

    @pytest.mark.asyncio
    async def test_score_and_update_todo_writes_audit_log(self, db_session):
        """score_and_update_todo creates a ScoreAuditLog entry."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="Test promise",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=1),
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        scorer = PriorityScorer()
        score = await scorer.score_and_update_todo(todo, db_session)

        # Query audit logs
        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog).where(ScoreAuditLog.todo_id == todo.id)
        )
        audit_entries = result.scalars().all()

        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry.old_score is None  # first calculation, no previous score
        assert entry.new_score == score
        assert entry.score_version == SCORE_VERSION_POC
        assert entry.calculated_by == "PriorityScorer"
        assert entry.triggered_by == "scorer_update"
        assert "urgency_raw" in entry.calculation_factors
        assert "importance_raw" in entry.calculation_factors

    @pytest.mark.asyncio
    async def test_rescore_records_old_score(self, db_session):
        """Rescoring a todo records the previous dynamic_score as old_score."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="care",
            title="Test care",
            priority=3,
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        scorer = PriorityScorer()

        # First scoring
        score1 = await scorer.score_and_update_todo(todo, db_session)

        # Second scoring (simulate rescore)
        score2 = await scorer.score_and_update_todo(todo, db_session)

        # Query audit logs
        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog)
            .where(ScoreAuditLog.todo_id == todo.id)
            .order_by(ScoreAuditLog.id)
        )
        audit_entries = result.scalars().all()

        assert len(audit_entries) == 2
        # First entry: old_score is None
        assert audit_entries[0].old_score is None
        assert audit_entries[0].new_score == score1
        # Second entry: old_score is the first score
        assert audit_entries[1].old_score == score1
        assert audit_entries[1].new_score == score2

    @pytest.mark.asyncio
    async def test_batch_score_todos_writes_audit_logs(self, db_session):
        """batch_score_todos creates audit log entries for each todo."""
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
        await scorer.batch_score_todos(todos, db_session)

        # Query audit logs
        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog).where(ScoreAuditLog.user_id == user_id)
        )
        audit_entries = result.scalars().all()

        assert len(audit_entries) == 3
        for entry in audit_entries:
            assert entry.score_version == SCORE_VERSION_POC
            assert entry.calculated_by == "PriorityScorer"
            assert entry.triggered_by == "scorer_update"

    @pytest.mark.asyncio
    async def test_audit_log_calculation_detail(self, db_session):
        """Audit log calculation_factors contains the full score breakdown."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="Test promise",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=1),
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        scorer = PriorityScorer()
        await scorer.score_and_update_todo(todo, db_session)

        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog).where(ScoreAuditLog.todo_id == todo.id)
        )
        entry = result.scalar_one()

        # Verify calculation_factors has expected fields
        factors = entry.calculation_factors
        assert "urgency_raw" in factors
        assert "importance_raw" in factors
        assert "urgency_weight" in factors
        assert "importance_weight" in factors
        assert "priority_adjustment" in factors
        assert "todo_type" in factors
        assert factors["todo_type"] == "promise"


# ── PriorityScorerV2 integration tests (with mocked dependencies) ──


class TestPriorityScorerV2AuditLog:
    """Test that PriorityScorerV2 writes audit log entries."""

    @pytest.mark.asyncio
    async def test_score_and_update_todo_v2_writes_audit_log(self, db_session):
        """score_and_update_todo_v2 creates a ScoreAuditLog entry with phase1_v1 version."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="Test promise v2",
            priority=2,
            due_date=datetime.now(UTC) + timedelta(days=1),
            source_event_id=event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        with patch("eventlink.services.dependency_analyzer.DependencyAnalyzer") as mock_da_cls, \
             patch("eventlink.services.context_matcher.ContextMatcher") as mock_cm_cls:
            mock_da_instance = AsyncMock()
            mock_da_instance.compute_dependency_score.return_value = 0.45
            mock_da_cls.return_value = mock_da_instance

            mock_cm_instance = AsyncMock()
            mock_cm_instance.compute_context_score.return_value = 0.917
            mock_cm_cls.return_value = mock_cm_instance

            from eventlink.services.priority_scorer import PriorityScorerV2
            scorer_v2 = PriorityScorerV2()
            score = await scorer_v2.score_and_update_todo_v2(todo, db_session)

        # Query audit logs
        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog).where(ScoreAuditLog.todo_id == todo.id)
        )
        audit_entries = result.scalars().all()

        assert len(audit_entries) == 1
        entry = audit_entries[0]
        assert entry.new_score == score
        assert entry.score_version == SCORE_VERSION_PHASE1
        assert entry.calculated_by == "PriorityScorerV2"
        assert entry.triggered_by == "scorer_update"
        # Phase1 breakdown should include dependency and context
        assert "dependency_raw" in entry.calculation_factors
        assert "context_raw" in entry.calculation_factors

    @pytest.mark.asyncio
    async def test_batch_score_with_context_writes_audit_logs(self, db_session):
        """batch_score_with_context creates audit log entries for each todo."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todos = []
        for todo_type in ["promise", "risk"]:
            todo = Todo(
                id=str(uuid.uuid4()),
                user_id=user_id,
                todo_type=todo_type,
                title=f"Test {todo_type} v2",
                priority=2,
                source_event_id=event.id,
            )
            db_session.add(todo)
            todos.append(todo)

        await db_session.flush()

        with patch("eventlink.services.dependency_analyzer.DependencyAnalyzer") as mock_da_cls, \
             patch("eventlink.services.context_matcher.ContextMatcher") as mock_cm_cls:
            mock_da_instance = AsyncMock()
            mock_da_instance.compute_dependency_score.return_value = 0.3
            mock_da_cls.return_value = mock_da_instance

            mock_cm_instance = AsyncMock()
            mock_cm_instance.compute_context_score.return_value = 0.5
            mock_cm_cls.return_value = mock_cm_instance

            from eventlink.services.priority_scorer import PriorityScorerV2
            scorer_v2 = PriorityScorerV2()
            await scorer_v2.batch_score_with_context(todos, db_session)

        # Query audit logs
        from sqlalchemy import select
        result = await db_session.execute(
            select(ScoreAuditLog).where(ScoreAuditLog.user_id == user_id)
        )
        audit_entries = result.scalars().all()

        assert len(audit_entries) == 2
        for entry in audit_entries:
            assert entry.score_version == SCORE_VERSION_PHASE1
            assert entry.calculated_by == "PriorityScorerV2"

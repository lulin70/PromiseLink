"""Tests for Todo State Machine — 5-state transitions."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.exceptions import InvalidTransitionError
from eventlink.models.todo import Todo
from eventlink.services.todo_state_machine import (
    TERMINAL_STATES,
    VALID_TRANSITIONS,
    TodoStateMachine,
)
from tests.conftest import make_user_id


def _create_todo(session: AsyncSession, user_id: str, status: str = "pending") -> Todo:
    """Helper to create a Todo object.
    
    Uses string IDs for SQLite compatibility (IS_SQLITE=True in tests).
    """
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type="promise",
        title="Test todo",
        status=status,
        priority=3,
        source_event_id=str(uuid.uuid4()),
    )
    session.add(todo)
    return todo


class TestValidTransitions:
    """Test VALID_TRANSITIONS mapping."""

    def test_pending_transitions(self):
        assert set(VALID_TRANSITIONS["pending"]) == {
            "in_progress", "done", "dismissed", "snoozed"
        }

    def test_in_progress_transitions(self):
        assert set(VALID_TRANSITIONS["in_progress"]) == {
            "done", "dismissed", "pending"
        }

    def test_snoozed_transitions(self):
        assert VALID_TRANSITIONS["snoozed"] == ["pending"]

    def test_done_no_transitions(self):
        assert VALID_TRANSITIONS["done"] == []

    def test_dismissed_no_transitions(self):
        assert VALID_TRANSITIONS["dismissed"] == []


class TestTerminalStates:
    """Test terminal state detection."""

    def test_done_is_terminal(self):
        assert "done" in TERMINAL_STATES

    def test_dismissed_is_terminal(self):
        assert "dismissed" in TERMINAL_STATES

    def test_pending_is_not_terminal(self):
        assert "pending" not in TERMINAL_STATES


class TestTodoStateMachine:
    """Test state machine transitions with side effects."""

    @pytest.mark.asyncio
    async def test_pending_to_in_progress(self, db_session):
        """Happy path: pending → in_progress."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        result = await sm.transition(todo, "in_progress")

        assert result.status == "in_progress"

    @pytest.mark.asyncio
    async def test_pending_to_done_quick_complete(self, db_session):
        """Valid: pending → done (quick complete)."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        result = await sm.transition(todo, "done", feedback="useful")

        assert result.status == "done"

    @pytest.mark.asyncio
    async def test_done_to_pending_invalid(self, db_session):
        """Invalid: done → pending (terminal state)."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id, status="done")
        await db_session.flush()

        with pytest.raises(InvalidTransitionError):
            await sm.transition(todo, "pending")

    @pytest.mark.asyncio
    async def test_dismissed_no_transitions(self, db_session):
        """Invalid: dismissed → any (terminal state)."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id, status="dismissed")
        await db_session.flush()

        with pytest.raises(InvalidTransitionError):
            await sm.transition(todo, "pending")

    @pytest.mark.asyncio
    async def test_snooze_requires_until(self, db_session):
        """Snooze transition requires snoozed_until parameter."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        with pytest.raises(ValueError, match="snoozed_until"):
            await sm.transition(todo, "snoozed")

    @pytest.mark.asyncio
    async def test_snooze_with_valid_until(self, db_session):
        """Snooze with valid until should succeed."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        until = datetime.utcnow() + timedelta(hours=24)
        result = await sm.transition(todo, "snoozed", snoozed_until=until)

        assert result.status == "snoozed"

    @pytest.mark.asyncio
    async def test_done_sets_completed_at(self, db_session):
        """Done transition sets completed_at timestamp."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id, status="in_progress")
        await db_session.flush()

        before = datetime.utcnow()
        result = await sm.transition(todo, "done")
        after = datetime.utcnow()

        assert result.completed_at is not None
        assert before <= result.completed_at <= after

    @pytest.mark.asyncio
    async def test_done_sets_feedback_useful(self, db_session):
        """Done transition sets feedback to 'useful'."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id, status="in_progress")
        await db_session.flush()

        result = await sm.transition(todo, "done")
        assert result.feedback == "useful"

    @pytest.mark.asyncio
    async def test_dismissed_sets_feedback_not_useful(self, db_session):
        """Dismissed transition sets feedback to 'not_useful'."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        result = await sm.transition(todo, "dismissed")
        assert result.feedback == "not_useful"

    @pytest.mark.asyncio
    async def test_done_with_custom_feedback(self, db_session):
        """Done transition accepts custom feedback."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id, status="in_progress")
        await db_session.flush()

        result = await sm.transition(todo, "done", feedback="very_useful")
        assert result.feedback == "very_useful"

    @pytest.mark.asyncio
    async def test_dismissed_with_custom_feedback(self, db_session):
        """Dismissed transition accepts custom feedback."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        result = await sm.transition(todo, "dismissed", feedback="wrong_person")
        assert result.feedback == "wrong_person"

    @pytest.mark.asyncio
    async def test_full_lifecycle_pending_to_done(self, db_session):
        """Full lifecycle: pending → in_progress → done."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        todo = await sm.transition(todo, "in_progress")
        assert todo.status == "in_progress"

        todo = await sm.transition(todo, "done")
        assert todo.status == "done"
        assert todo.completed_at is not None

    @pytest.mark.asyncio
    async def test_snooze_recover_lifecycle(self, db_session):
        """Snooze lifecycle: pending → snoozed → (auto-recover) → pending."""
        sm = TodoStateMachine(db_session)
        user_id = make_user_id()
        todo = _create_todo(db_session, user_id)
        await db_session.flush()

        until = datetime.utcnow() + timedelta(hours=1)
        todo = await sm.transition(todo, "snoozed", snoozed_until=until)
        assert todo.status == "snoozed"

        # Recover expired snoozes (none expired yet)
        recovered = await sm.recover_expired_snoozes()
        assert recovered == 0


class TestStaticHelpers:
    """Test static helper methods."""

    def test_can_transition_valid(self):
        assert TodoStateMachine.can_transition("pending", "in_progress") is True

    def test_can_transition_invalid(self):
        assert TodoStateMachine.can_transition("done", "pending") is False

    def test_get_valid_transitions(self):
        transitions = TodoStateMachine.get_valid_transitions("pending")
        assert "in_progress" in transitions
        assert "dismissed" in transitions

    def test_is_terminal(self):
        assert TodoStateMachine.is_terminal("done") is True
        assert TodoStateMachine.is_terminal("dismissed") is True
        assert TodoStateMachine.is_terminal("pending") is False


class TestPromiseFulfillmentUnit:
    """Unit tests for PromiseFulfillmentEngine (non-DB)."""

    def test_sensitivity_filter_matchable(self):
        from eventlink.services.promise_fulfillment import SensitivityFilter

        sf = SensitivityFilter()
        entity = type("MockEntity", (), {
            "properties": {"resource_sensitivity": "matchable"}
        })()
        assert sf.check(entity) is True

    def test_sensitivity_filter_no_match(self):
        from eventlink.services.promise_fulfillment import SensitivityFilter

        sf = SensitivityFilter()
        entity = type("MockEntity", (), {
            "properties": {"resource_sensitivity": "no_match"}
        })()
        assert sf.check(entity) is False

    def test_sensitivity_filter_default(self):
        from eventlink.services.promise_fulfillment import SensitivityFilter

        sf = SensitivityFilter()
        entity = type("MockEntity", (), {"properties": {}})()
        assert sf.check(entity) is True  # Default is matchable

    def test_sensitivity_batch_filter(self):
        from eventlink.services.promise_fulfillment import SensitivityFilter

        sf = SensitivityFilter()
        matchable = type("E", (), {"properties": {"resource_sensitivity": "matchable"}})()
        no_match = type("E", (), {"properties": {"resource_sensitivity": "no_match"}})()
        default = type("E", (), {"properties": {}})()

        ok, filtered = sf.batch_filter([matchable, no_match, default])
        assert len(ok) == 2
        assert len(filtered) == 1

    def test_poc_weights(self):
        from eventlink.services.promise_fulfillment import POC_WEIGHTS

        assert POC_WEIGHTS["keyword_overlap"] == 0.35
        assert POC_WEIGHTS["callability"] == 0.35
        assert POC_WEIGHTS["industry_alignment"] == 0.30
        # Disabled in PoC
        assert POC_WEIGHTS["topic_similarity"] == 0.0
        assert POC_WEIGHTS["llm_semantic"] == 0.0

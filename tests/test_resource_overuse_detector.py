"""Tests for ResourceOveruseDetector — F-39: Resource overuse warning.

Covers:
1. No warning when requests < threshold
2. Warning triggered when requests >= 3 in 30 days
3. Only "索取型" (their_promise) todos are counted, not "给予型"
4. Requests outside 30-day window are not counted
5. Dedup: only one warning Todo per (user, entity, 30-day window)
6. Severity escalation: critical when requests >= 6
7. Warning Todo has correct properties (risk_type, target_entity_id, etc.)
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.models.entity import Entity
from promiselink.models.todo import Todo
from promiselink.services.resource_overuse_detector import (
    ResourceOveruseDetector,
)
from tests.conftest import create_test_event, make_user_id


async def _create_entity(
    session: AsyncSession,
    user_id: str,
    name: str = "张三",
) -> Entity:
    """Create a test Entity for foreign key references."""
    event = await create_test_event(session, user_id=user_id)
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        source_event_id=str(event.id),
    )
    session.add(entity)
    await session.flush()
    return entity


async def _create_request_todo(
    session: AsyncSession,
    user_id: str,
    related_entity_id: str,
    action_type: str = "their_promise",
    todo_type: str = "help",
    created_at: datetime | None = None,
) -> Todo:
    """Create a test "索取型" Todo."""
    event = await create_test_event(session, user_id=user_id)
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title=f"请求帮助 - {action_type}",
        status="pending",
        priority=3,
        source_event_id=str(event.id),
        action_type=action_type,
        related_entity_id=related_entity_id,
        created_at=created_at or datetime.now(UTC),
    )
    session.add(todo)
    await session.flush()
    return todo


class TestNoWarningBelowThreshold:
    """Test 1: No warning when requests < threshold."""

    @pytest.mark.asyncio
    async def test_zero_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_one_request(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_two_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        await _create_request_todo(db_session, user_id, str(entity.id))
        await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None


class TestWarningAtThreshold:
    """Test 2: Warning triggered when requests >= 3 in 30 days."""

    @pytest.mark.asyncio
    async def test_exactly_three_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        await _create_request_todo(db_session, user_id, str(entity.id))
        await _create_request_todo(db_session, user_id, str(entity.id))
        await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is not None
        assert result.request_count == 3
        assert result.entity_name == "张三"
        assert result.window_days == 30
        assert result.severity == "warning"

    @pytest.mark.asyncio
    async def test_more_than_three_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        for _ in range(5):
            await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is not None
        assert result.request_count == 5


class TestOnlyRequestTypeCounted:
    """Test 3: Only "索取型" (their_promise) todos are counted."""

    @pytest.mark.asyncio
    async def test_my_promise_not_counted(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        # 3 my_promise todos should NOT trigger
        for _ in range(3):
            await _create_request_todo(
                db_session, user_id, str(entity.id), action_type="my_promise"
            )

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_action_types_only_counts_their_promise(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        # 2 their_promise + 2 my_promise = only 2 counted, below threshold
        await _create_request_todo(
            db_session, user_id, str(entity.id), action_type="their_promise"
        )
        await _create_request_todo(
            db_session, user_id, str(entity.id), action_type="their_promise"
        )
        await _create_request_todo(
            db_session, user_id, str(entity.id), action_type="my_promise"
        )
        await _create_request_todo(
            db_session, user_id, str(entity.id), action_type="my_promise"
        )

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_with_enough_their_promise(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        # 3 their_promise + 2 my_promise = 3 counted, triggers warning
        for _ in range(3):
            await _create_request_todo(
                db_session, user_id, str(entity.id), action_type="their_promise"
            )
        for _ in range(2):
            await _create_request_todo(
                db_session, user_id, str(entity.id), action_type="my_promise"
            )

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is not None
        assert result.request_count == 3


class TestWindowExpiry:
    """Test 4: Requests outside 30-day window are not counted."""

    @pytest.mark.asyncio
    async def test_old_requests_not_counted(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        # 3 requests 31 days ago — outside window
        old_time = datetime.now(UTC) - timedelta(days=31)
        for _ in range(3):
            await _create_request_todo(
                db_session, user_id, str(entity.id), created_at=old_time
            )

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is None

    @pytest.mark.asyncio
    async def test_mixed_old_and_new_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        # 2 old requests (outside window) + 2 new requests (inside window)
        old_time = datetime.now(UTC) - timedelta(days=31)
        await _create_request_todo(
            db_session, user_id, str(entity.id), created_at=old_time
        )
        await _create_request_todo(
            db_session, user_id, str(entity.id), created_at=old_time
        )
        await _create_request_todo(db_session, user_id, str(entity.id))
        await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        # Only 2 new requests counted, below threshold
        assert result is None


class TestDeduplication:
    """Test 5: Only one warning Todo per (user, entity, 30-day window)."""

    @pytest.mark.asyncio
    async def test_no_duplicate_warning(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        event = await create_test_event(db_session, user_id=user_id)

        # Create 3 requests
        for _ in range(3):
            await _create_request_todo(db_session, user_id, str(entity.id))

        # First check should create a warning
        warning1 = await detector.check_and_create_warning_todo(
            user_id=user_id,
            target_entity_id=str(entity.id),
            source_event_id=str(event.id),
            session=db_session,
        )
        assert warning1 is not None

        # Add another request (4th)
        await _create_request_todo(db_session, user_id, str(entity.id))

        # Second check should NOT create another warning (dedup)
        warning2 = await detector.check_and_create_warning_todo(
            user_id=user_id,
            target_entity_id=str(entity.id),
            source_event_id=str(event.id),
            session=db_session,
        )
        assert warning2 is None


class TestSeverityEscalation:
    """Test 6: Severity escalation — critical when requests >= 6."""

    @pytest.mark.asyncio
    async def test_warning_severity_at_threshold(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        for _ in range(3):
            await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is not None
        assert result.severity == "warning"

    @pytest.mark.asyncio
    async def test_critical_severity_at_six_requests(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id)
        for _ in range(6):
            await _create_request_todo(db_session, user_id, str(entity.id))

        result = await detector.check_overuse(user_id, str(entity.id), db_session)

        assert result is not None
        assert result.severity == "critical"
        assert result.request_count == 6


class TestWarningTodoProperties:
    """Test 7: Warning Todo has correct properties."""

    @pytest.mark.asyncio
    async def test_warning_todo_structure(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity = await _create_entity(db_session, user_id, name="李四")
        event = await create_test_event(db_session, user_id=user_id)

        for _ in range(3):
            await _create_request_todo(db_session, user_id, str(entity.id))

        todo = await detector.check_and_create_warning_todo(
            user_id=user_id,
            target_entity_id=str(entity.id),
            source_event_id=str(event.id),
            session=db_session,
        )

        assert todo is not None
        assert todo.todo_type == "risk"
        assert todo.status == "pending"
        assert todo.priority == 2
        assert "李四" in todo.title
        assert "3次" in todo.title
        assert "30天" in todo.title
        assert todo.related_entity_id == entity.id

        # Check properties
        props = todo.properties
        assert props["risk_type"] == "resource_overuse"
        assert props["target_entity_id"] == str(entity.id)
        assert props["request_count"] == 3
        assert props["window_days"] == 30
        assert props["severity"] == "warning"


class TestDifferentEntities:
    """Test: Requests to different entities are counted separately."""

    @pytest.mark.asyncio
    async def test_separate_entity_counts(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity1 = await _create_entity(db_session, user_id, name="张三")
        entity2 = await _create_entity(db_session, user_id, name="李四")

        # 2 requests to entity1, 2 requests to entity2 — neither triggers
        for _ in range(2):
            await _create_request_todo(db_session, user_id, str(entity1.id))
            await _create_request_todo(db_session, user_id, str(entity2.id))

        result1 = await detector.check_overuse(user_id, str(entity1.id), db_session)
        result2 = await detector.check_overuse(user_id, str(entity2.id), db_session)

        assert result1 is None
        assert result2 is None

    @pytest.mark.asyncio
    async def test_one_entity_triggers_other_does_not(self, db_session):
        detector = ResourceOveruseDetector()
        user_id = make_user_id()
        entity1 = await _create_entity(db_session, user_id, name="张三")
        entity2 = await _create_entity(db_session, user_id, name="李四")

        # 3 requests to entity1 (triggers), 1 request to entity2 (doesn't)
        for _ in range(3):
            await _create_request_todo(db_session, user_id, str(entity1.id))
        await _create_request_todo(db_session, user_id, str(entity2.id))

        result1 = await detector.check_overuse(user_id, str(entity1.id), db_session)
        result2 = await detector.check_overuse(user_id, str(entity2.id), db_session)

        assert result1 is not None
        assert result2 is None

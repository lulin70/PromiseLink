"""Tests for ContextMatcher — F-56 Event-driven context matching."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.context_matcher import ContextMatcher
from tests.conftest import create_test_event, make_user_id


class TestComputeContextScore:
    """Test compute_context_score method."""

    @pytest.mark.asyncio
    async def test_todo_without_entity_returns_zero(self, db_session):
        """Todo without related_entity_id should return 0.0."""
        user_id = make_user_id()
        event = await create_test_event(db_session, user_id=user_id)

        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="No entity todo",
            source_event_id=event.id,
            # related_entity_id is None by default
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        assert score == 0.0

    @pytest.mark.asyncio
    async def test_no_upcoming_events_returns_zero(self, db_session):
        """When there are no upcoming meeting/call events, score is 0.0."""
        user_id = make_user_id()
        # Use card_save event type so it won't be picked up as meeting/call
        event = await create_test_event(
            db_session, user_id=user_id, event_type="card_save"
        )

        # Create an entity from the event
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="李四",
            canonical_name="李四",
            source_event_id=event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        # Create a todo linked to the entity
        other_event = await create_test_event(
            db_session, user_id=user_id, event_type="card_save"
        )
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="followup",
            title="Follow up with 李四",
            related_entity_id=entity.id,
            source_event_id=other_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        # No meeting/call events → score = 0.0
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_upcoming_meeting_boosts_score(self, db_session):
        """An upcoming meeting linked to the todo's entity should boost score."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Create a meeting event with created_at in the near future (2h from now)
        meeting_event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="calendar",
            title="与张三的会议",
            raw_text="Meeting with 张三",
            status="pending",
            created_at=now + timedelta(hours=2),
        )
        db_session.add(meeting_event)
        await db_session.flush()

        # Create an entity from this meeting event
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="张三",
            canonical_name="张三",
            source_event_id=meeting_event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        # Create a todo linked to this entity
        source_event = await create_test_event(db_session, user_id=user_id)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="给张三发方案",
            related_entity_id=entity.id,
            source_event_id=source_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        # 2 hours until meeting → score = 1 - 2/24 ≈ 0.9167
        assert score > 0.0
        expected = round(max(0.0, 1.0 - 2.0 / 24.0), 4)
        assert score == expected

    @pytest.mark.asyncio
    async def test_distant_event_low_score(self, db_session):
        """An event far in the future should yield a low context score."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Create a meeting event 20h from now
        meeting_event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="calendar",
            title="与王五的会议",
            raw_text="Meeting with 王五",
            status="pending",
            created_at=now + timedelta(hours=20),
        )
        db_session.add(meeting_event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="王五",
            canonical_name="王五",
            source_event_id=meeting_event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        source_event = await create_test_event(db_session, user_id=user_id)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="care",
            title="关注王五项目进展",
            related_entity_id=entity.id,
            source_event_id=source_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        # 20h until meeting → score = 1 - 20/24 ≈ 0.1667
        assert 0.0 < score < 0.5
        expected = round(max(0.0, 1.0 - 20.0 / 24.0), 4)
        assert score == expected

    @pytest.mark.asyncio
    async def test_non_meeting_event_ignored(self, db_session):
        """Events that are not meeting or call type should be ignored."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Create a card_save event in the near future — should be ignored
        card_event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="card_save",
            source="wechat",
            title="保存名片",
            raw_text="Saved card",
            status="completed",
            created_at=now + timedelta(hours=1),
        )
        db_session.add(card_event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="赵六",
            canonical_name="赵六",
            source_event_id=card_event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        source_event = await create_test_event(db_session, user_id=user_id)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="followup",
            title="跟进赵六",
            related_entity_id=entity.id,
            source_event_id=source_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        # card_save event should be ignored → no matching meeting/call → score = 0.0
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_context_score_range(self, db_session):
        """Context score should always be in [0.0, 1.0] range."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Test with an event very close (near 0 hours) → score near 1.0
        meeting_event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="call",
            source="phone",
            title="与孙七通话",
            raw_text="Call with 孙七",
            status="pending",
            created_at=now + timedelta(minutes=30),
        )
        db_session.add(meeting_event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="孙七",
            canonical_name="孙七",
            source_event_id=meeting_event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        source_event = await create_test_event(db_session, user_id=user_id)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="help",
            title="帮助孙七",
            related_entity_id=entity.id,
            source_event_id=source_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_call_event_also_matched(self, db_session):
        """Call events should also be matched (not just meetings)."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Create a call event
        call_event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="call",
            source="phone",
            title="与周八通话",
            raw_text="Call with 周八",
            status="pending",
            created_at=now + timedelta(hours=3),
        )
        db_session.add(call_event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="周八",
            canonical_name="周八",
            source_event_id=call_event.id,
            confidence=1.0,
        )
        db_session.add(entity)
        await db_session.flush()

        source_event = await create_test_event(db_session, user_id=user_id)
        todo = Todo(
            id=str(uuid.uuid4()),
            user_id=user_id,
            todo_type="promise",
            title="给周八回电",
            related_entity_id=entity.id,
            source_event_id=source_event.id,
        )
        db_session.add(todo)
        await db_session.flush()

        matcher = ContextMatcher()
        score = await matcher.compute_context_score(todo, db_session)

        # 3h until call → score = 1 - 3/24 = 0.875
        assert score > 0.0
        expected = round(max(0.0, 1.0 - 3.0 / 24.0), 4)
        assert score == expected


class TestGetUpcomingContext:
    """Test get_upcoming_context method."""

    @pytest.mark.asyncio
    async def test_get_upcoming_context(self, db_session):
        """Verify get_upcoming_context returns sorted upcoming events with entities."""
        user_id = make_user_id()
        now = datetime.now(timezone.utc)

        # Create two upcoming meeting events
        meeting1 = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="meeting",
            source="calendar",
            title="上午会议",
            raw_text="Morning meeting",
            status="pending",
            created_at=now + timedelta(hours=5),
        )
        meeting2 = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="call",
            source="phone",
            title="下午通话",
            raw_text="Afternoon call",
            status="pending",
            created_at=now + timedelta(hours=10),
        )
        db_session.add_all([meeting1, meeting2])
        await db_session.flush()

        # Create entities for each event
        entity1 = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="吴九",
            canonical_name="吴九",
            source_event_id=meeting1.id,
            confidence=1.0,
        )
        entity2 = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="郑十",
            canonical_name="郑十",
            source_event_id=meeting2.id,
            confidence=1.0,
        )
        db_session.add_all([entity1, entity2])
        await db_session.flush()

        matcher = ContextMatcher()
        result = await matcher.get_upcoming_context(user_id, db_session)

        assert len(result) == 2
        # Should be sorted by hours_until (ascending)
        assert result[0]["event_title"] == "上午会议"
        assert result[1]["event_title"] == "下午通话"
        assert result[0]["hours_until"] < result[1]["hours_until"]
        # Check structure
        assert result[0]["event_type"] == "meeting"
        assert result[1]["event_type"] == "call"
        assert len(result[0]["entities"]) == 1
        assert result[0]["entities"][0]["name"] == "吴九"
        assert result[1]["entities"][0]["name"] == "郑十"

    @pytest.mark.asyncio
    async def test_get_upcoming_context_empty(self, db_session):
        """No upcoming events should return empty list."""
        user_id = make_user_id()

        matcher = ContextMatcher()
        result = await matcher.get_upcoming_context(user_id, db_session)

        assert result == []

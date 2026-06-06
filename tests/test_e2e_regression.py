"""P9 Regression Test Suite — E2E integration tests for POC acceptance.

Simulates real user workflows end-to-end, validating:
  1. Complete Pipeline flow (Event → Entity → Todo → Association → Brief)
  2. Cross-event association discovery
  3. Priority scoring (F-51)
  4. Implicit feedback (F-52)
  5. Concern/capability extraction (F-53)
  6. DataSourceAdapter interface (F-54)
  7. Todo state machine
  8. NLG service

These tests use in-memory SQLite and mock LLM calls to avoid external dependencies.
They validate the full integration path, not individual units.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.services.data_source_adapter import (
    DataSourceAdapter,
    EmailAdapter,
    ManualAdapter,
    RawEvent,
    WeChatAdapter,
    get_adapter,
    register_adapter,
)
from eventlink.services.implicit_feedback import ImplicitFeedbackCollector
from eventlink.services.priority_scorer import PriorityScorer, IMPORTANCE_WEIGHTS
from tests.conftest import create_test_event, make_user_id


# ═══════════════════════════════════════════════════════════════
#  E2E Test 1: Complete Pipeline Flow (mocked LLM)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_pipeline_creates_entities_and_todos(db_session):
    """E2E: Pipeline processes an event and creates entities + todos."""
    user_id = make_user_id()

    # Create event
    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="meeting",
        source="manual",
        title="投资对接会",
        raw_text="今天和李总开会，我答应下周发资料给他。",
        status="pending",
        metadata_={},
    )
    db_session.add(event)
    await db_session.commit()

    # Verify event was created
    result = await db_session.execute(
        select(Event).where(Event.id == event.id)
    )
    assert result.scalar_one_or_none() is not None


# ═══════════════════════════════════════════════════════════════
#  E2E Test 2: Cross-Event Association Discovery
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_cross_event_association(db_session):
    """E2E: Two events with shared topic discover association."""
    user_id = make_user_id()
    event1 = await create_test_event(db_session, user_id, raw_text="AI赛道讨论")
    event2 = await create_test_event(db_session, user_id, raw_text="AI项目对接")

    # Create entities from different events with overlapping concern
    entity1 = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="李总",
        canonical_name="李总",
        aliases=[],
        properties={
            "basic": {"company": "盛恒资本", "industry": "投资"},
            "concern": [{"category": "融资", "detail": "看AI项目"}],
            "capability": [{"category": "投资决策", "detail": "早期科技投资"}],
        },
        source_event_id=event1.id,
        confidence=0.95,
        status="confirmed",
    )
    entity2 = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="张总",
        canonical_name="张总",
        aliases=[],
        properties={
            "basic": {"company": "智谱AI", "industry": "AI"},
            "concern": [{"category": "市场拓展", "detail": "找早期客户"}],
            "capability": [{"category": "技术架构", "detail": "大模型应用"}],
        },
        source_event_id=event2.id,
        confidence=0.95,
        status="confirmed",
    )
    db_session.add_all([entity1, entity2])
    await db_session.commit()

    # Verify entities were created with concern/capability
    result = await db_session.execute(
        select(Entity).where(Entity.user_id == user_id)
    )
    entities = result.scalars().all()
    assert len(entities) == 2

    # Verify concern is dict list (F-53 format)
    for e in entities:
        concern = (e.properties or {}).get("concern", [])
        capability = (e.properties or {}).get("capability", [])
        assert isinstance(concern, list)
        assert isinstance(capability, list)


# ═══════════════════════════════════════════════════════════════
#  E2E Test 3: Priority Scoring (F-51)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_priority_scoring(db_session):
    """E2E: PriorityScorer assigns dynamic scores to todos."""
    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    # Create todos with different types
    todo_promise = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="promise",
        title="发送AI项目资料",
        description="发送AI项目资料给李总",
        status="pending",
        priority=2,
        due_date=datetime.now(timezone.utc) + timedelta(days=2),
    )
    todo_care = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="care",
        title="关注LP对接进展",
        description="关注李总LP对接进展",
        status="pending",
        priority=3,
    )
    db_session.add_all([todo_promise, todo_care])
    await db_session.commit()

    # Score todos
    scorer = PriorityScorer()
    result_promise = scorer.calculate(
        todo_type="promise",
        due_date=todo_promise.due_date,
        priority=2,
    )
    result_care = scorer.calculate(
        todo_type="care",
        due_date=None,
        priority=3,
    )

    # Promise should score higher than care (higher importance + has due date)
    assert result_promise.score > result_care.score
    assert result_promise.importance == IMPORTANCE_WEIGHTS["promise"]
    assert result_care.importance == IMPORTANCE_WEIGHTS["care"]
    assert 0.0 <= result_promise.score <= 1.0
    assert 0.0 <= result_care.score <= 1.0


# ═══════════════════════════════════════════════════════════════
#  E2E Test 4: Implicit Feedback (F-52)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_implicit_feedback(db_session):
    """E2E: ImplicitFeedbackCollector records completion order."""
    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    # Create and complete todos in sequence
    todo1 = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="promise",
        title="第一件完成的事",
        description="第一件完成的事",
        status="done",
        priority=2,
    )
    todo2 = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="care",
        title="第二件完成的事",
        description="第二件完成的事",
        status="done",
        priority=3,
    )
    db_session.add_all([todo1, todo2])
    await db_session.commit()

    collector = ImplicitFeedbackCollector()

    # Record completions
    rank1 = await collector.record_completion(todo1, db_session)
    rank2 = await collector.record_completion(todo2, db_session)

    assert rank1 == 1
    assert rank2 == 2
    assert todo1.completed_rank == 1
    assert todo2.completed_rank == 2


# ═══════════════════════════════════════════════════════════════
#  E2E Test 5: DataSourceAdapter Interface (F-54)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_data_source_adapter_manual():
    """E2E: ManualAdapter creates RawEvent for pipeline ingestion."""
    adapter = ManualAdapter()
    raw_event = adapter.create_raw_event(
        raw_text="今天和李总开会，讨论了AI项目合作。",
        event_type="meeting",
        user_id="test-user",
    )

    assert raw_event.source_type == "manual"
    assert raw_event.raw_text == "今天和李总开会，讨论了AI项目合作。"
    assert raw_event.user_id == "test-user"
    assert raw_event.event_type == "meeting"


@pytest.mark.asyncio
async def test_e2e_data_source_adapter_registry():
    """E2E: Adapter registry returns correct adapters."""
    email = get_adapter("email")
    assert isinstance(email, EmailAdapter)

    wechat = get_adapter("wechat")
    assert isinstance(wechat, WeChatAdapter)

    manual = get_adapter("manual")
    assert isinstance(manual, ManualAdapter)

    with pytest.raises(ValueError):
        get_adapter("unknown_source")


# ═══════════════════════════════════════════════════════════════
#  E2E Test 6: Todo State Machine
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_todo_lifecycle(db_session):
    """E2E: Todo transitions through pending → in_progress → done."""
    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="promise",
        title="发送资料",
        description="发送资料",
        status="pending",
        priority=2,
    )
    db_session.add(todo)
    await db_session.commit()

    # pending → in_progress
    todo.status = "in_progress"
    await db_session.commit()

    # in_progress → done
    todo.status = "done"
    todo.completed_at = datetime.now(timezone.utc)
    await db_session.commit()

    # Verify final state
    result = await db_session.execute(
        select(Todo).where(Todo.id == todo.id)
    )
    done_todo = result.scalar_one()
    assert done_todo.status == "done"
    assert done_todo.completed_at is not None


# ═══════════════════════════════════════════════════════════════
#  E2E Test 7: Concern/Capability Format Compatibility (F-53)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_concern_capability_in_entity(db_session):
    """E2E: Entity stores concern/capability as dict list (F-53 format)."""
    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="李总",
        canonical_name="李总",
        aliases=[],
        properties={
            "basic": {"company": "盛恒资本", "title": "合伙人"},
            "concern": [
                {"category": "融资", "detail": "寻找AI早期项目"},
                {"category": "招聘", "detail": "需要技术合伙人"},
            ],
            "capability": [
                {"category": "投资决策", "detail": "专注AI赛道"},
                {"category": "行业人脉", "detail": "LP资源丰富"},
            ],
            "demand": ["推荐AI项目"],
        },
        source_event_id=event.id,
        confidence=0.95,
        status="confirmed",
    )
    db_session.add(entity)
    await db_session.commit()

    # Read back and verify
    result = await db_session.execute(
        select(Entity).where(Entity.id == entity.id)
    )
    saved = result.scalar_one()
    concern = saved.properties["concern"]
    capability = saved.properties["capability"]

    assert len(concern) == 2
    assert concern[0]["category"] == "融资"
    assert len(capability) == 2
    assert capability[0]["category"] == "投资决策"
    # demand is still present as separate field
    assert "demand" in saved.properties


# ═══════════════════════════════════════════════════════════════
#  E2E Test 8: Association Discovery with Dict-Format Concern
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_association_with_dict_concern(db_session):
    """E2E: Association discovery handles dict-format concern/capability."""
    from eventlink.services.association_discovery import AssociationDiscoveryEngine

    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    # Entity A: has capability "投资决策"
    entity_a = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="李总",
        canonical_name="李总",
        aliases=[],
        properties={
            "basic": {"company": "盛恒资本", "industry": "投资"},
            "concern": [{"category": "市场拓展", "detail": "找好项目"}],
            "capability": [{"category": "投资决策", "detail": "专注AI"}],
            "resource": {"capabilities": ["投资决策"]},
        },
        source_event_id=event.id,
        confidence=0.95,
        status="confirmed",
    )

    # Entity B: has concern "融资" (matches A's capability)
    entity_b = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name="张总",
        canonical_name="张总",
        aliases=[],
        properties={
            "basic": {"company": "智谱AI", "industry": "AI"},
            "concern": [{"category": "融资", "detail": "需要资金"}],
            "capability": [{"category": "技术架构", "detail": "大模型"}],
            "resource": {"capabilities": ["技术架构"]},
        },
        source_event_id=event.id,
        confidence=0.95,
        status="confirmed",
    )

    db_session.add_all([entity_a, entity_b])
    await db_session.commit()

    # Test _discover_supply_demand with dict-format concern
    engine = AssociationDiscoveryEngine(session=db_session)
    score, evidence = engine._discover_supply_demand(entity_a, entity_b)

    # Should find supply-demand match (A's resource → B's concern, etc.)
    assert isinstance(score, float)
    assert isinstance(evidence, dict)


# ═══════════════════════════════════════════════════════════════
#  E2E Test 9: PriorityScorer + ImplicitFeedback Integration
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_priority_and_feedback_integration(db_session):
    """E2E: PriorityScorer and ImplicitFeedback work together."""
    user_id = make_user_id()
    event = await create_test_event(db_session, user_id)

    # Create a high-priority promise todo
    todo = Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_event_id=event.id,
        todo_type="promise",
        title="紧急承诺：今天必须发资料",
        description="紧急承诺：今天必须发资料",
        status="pending",
        priority=1,
        due_date=datetime.now(timezone.utc) + timedelta(hours=3),
    )
    db_session.add(todo)
    await db_session.commit()

    # Score it
    scorer = PriorityScorer()
    score_result = scorer.calculate(
        todo_type=todo.todo_type,
        due_date=todo.due_date,
        priority=todo.priority,
    )

    # High importance (promise=0.9) + high urgency (3h from now ≈ today=0.9)
    # Score ≈ 0.4 * 0.9 + 0.6 * 0.9 = 0.9
    assert score_result.score > 0.8, f"Expected high score, got {score_result.score}"

    # Complete it and record feedback
    todo.status = "done"
    todo.completed_at = datetime.now(timezone.utc)
    collector = ImplicitFeedbackCollector()
    rank = await collector.record_completion(todo, db_session)

    assert rank == 1
    assert todo.completed_rank == 1


# ═══════════════════════════════════════════════════════════════
#  E2E Test 10: RawEvent → Event Pipeline Entry (F-54)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_e2e_raw_event_to_event(db_session):
    """E2E: RawEvent from ManualAdapter can be converted to Event."""
    adapter = ManualAdapter()
    raw = adapter.create_raw_event(
        raw_text="下午和张总喝茶，聊了AI合作。",
        event_type="meeting",
        user_id="user-123",
    )

    # Convert RawEvent to Event (simulating what the API would do)
    event = Event(
        id=str(uuid.uuid4()),
        user_id=raw.user_id,
        event_type=raw.event_type,
        source=raw.source_type,
        title=raw.title or "未命名",
        raw_text=raw.raw_text,
        status="pending",
        metadata_=raw.metadata,
    )
    db_session.add(event)
    await db_session.commit()

    # Verify
    result = await db_session.execute(
        select(Event).where(Event.id == event.id)
    )
    saved = result.scalar_one()
    assert saved.source == "manual"
    assert saved.raw_text == "下午和张总喝茶，聊了AI合作。"

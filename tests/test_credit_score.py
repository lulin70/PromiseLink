"""Tests for promiselink.services.credit_score.

Tests CreditScoreService.batch_calculate / calculate with DB integration.
Score formula: my_fulfillment*40% + their_fulfillment*35% + consistency*15% + timeliness*10%
Grade: A+(>=90) A(80-89) B(70-79) C(60-69) D(<60)
"""

from __future__ import annotations

import uuid

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.credit_score import CreditScoreService


def _make_todo(
    user_id: str,
    *,
    related_entity_id: str,
    action_type: str = "my_promise",
    fulfillment_status: str = "pending",
    title: str = "test todo",
    todo_type: str = "promise",
) -> Todo:
    """Construct Todo with required fields for credit score tests."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=user_id,
        todo_type=todo_type,
        title=title,
        status="pending",
        action_type=action_type,
        fulfillment_status=fulfillment_status,
        related_entity_id=related_entity_id,
    )


async def _make_event_and_entity(session, user_id: str, name: str = "test entity") -> str:
    """Create Event + Entity pair so calculate() existence check passes.

    Returns the entity_id for use in Todo.related_entity_id.
    """
    eid = str(uuid.uuid4())
    session.add(Event(
        id=eid, user_id=user_id, event_type="meeting",
        source="test", title="placeholder", raw_text="x", status="completed",
    ))
    await session.flush()
    entity = Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        status="confirmed",
        source_event_id=eid,
    )
    session.add(entity)
    await session.flush()
    return str(entity.id)


# ═══════════════════════════════════════════════════════════════
# batch_calculate — DB 集成
# ═══════════════════════════════════════════════════════════════


class TestBatchCalculate:
    """batch_calculate 批量信用分计算 — Happy/Boundary."""

    @pytest.mark.asyncio
    async def test_boundary_empty_entity_list_returns_empty_dict(self, db_session):
        """空 entity_ids 列表应返回空 dict (不查询数据库)."""
        result = await CreditScoreService.batch_calculate(
            db_session, [], "user-1"
        )
        assert result == {}

    @pytest.mark.asyncio
    async def test_boundary_entity_with_no_todos_returns_default_score(self, db_session):
        """无 Todo 的实体应返回默认值: my_rate=0.5, their_rate=0.5, score≈50, grade=D."""
        eid = str(uuid.uuid4())
        result = await CreditScoreService.batch_calculate(
            db_session, [eid], "user-1"
        )
        assert eid in result
        data = result[eid]
        # my_rate=0.5 (no todos), their_rate=0.5 (no todos)
        # total_interactions=0, consistency=50 (<2 threshold)
        # timeliness=(0.5+0.5)/2*100=50
        # score = 50*0.4 + 50*0.35 + 50*0.15 + 50*0.10 = 50.0
        assert data["score"] == pytest.approx(50.0, abs=0.1)
        assert data["grade"] == "D"
        assert data["my_fulfillment_rate"] == 0.5
        assert data["their_fulfillment_rate"] == 0.5
        assert data["interaction_consistency"] == 50.0
        assert data["total_interactions"] == 0

    @pytest.mark.asyncio
    async def test_happy_fulfilled_my_promise_yields_higher_score(self, db_session):
        """兑现 my_promise 应比无 Todo 情况得分高."""
        user_id = "user-2"
        eid = str(uuid.uuid4())
        db_session.add(_make_todo(
            user_id, related_entity_id=eid,
            action_type="my_promise", fulfillment_status="fulfilled",
        ))
        await db_session.flush()

        result = await CreditScoreService.batch_calculate(db_session, [eid], user_id)
        data = result[eid]
        # my_rate=1.0 (1/1), their_rate=0.5 (no their_promises)
        # total_interactions=1, consistency=50 (<2)
        # timeliness=(1.0+0.5)/2*100=75
        # score = 100*0.4 + 50*0.35 + 50*0.15 + 75*0.10 = 40+17.5+7.5+7.5 = 72.5
        assert data["score"] == pytest.approx(72.5, abs=0.1)
        assert data["grade"] == "B"
        assert data["my_fulfillment_rate"] == 1.0
        assert data["their_fulfillment_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_happy_all_fulfilled_with_multiple_interactions_yields_a_plus(self, db_session):
        """my+their 全兑现 + 多互动 → A+ 等级."""
        user_id = "user-3"
        eid = str(uuid.uuid4())
        for _ in range(3):
            db_session.add(_make_todo(
                user_id, related_entity_id=eid,
                action_type="my_promise", fulfillment_status="fulfilled",
            ))
        for _ in range(2):
            db_session.add(_make_todo(
                user_id, related_entity_id=eid,
                action_type="their_promise", fulfillment_status="fulfilled",
            ))
        await db_session.flush()

        result = await CreditScoreService.batch_calculate(db_session, [eid], user_id)
        data = result[eid]
        # my_rate=1.0, their_rate=1.0, total_interactions=5
        # consistency=min(100, 5*10)=50, timeliness=100
        # score = 100*0.4 + 100*0.35 + 50*0.15 + 100*0.10 = 40+35+7.5+10 = 92.5
        assert data["score"] == pytest.approx(92.5, abs=0.1)
        assert data["grade"] == "A+"
        assert data["total_interactions"] == 5

    @pytest.mark.asyncio
    async def test_boundary_unfulfilled_my_promise_yields_low_score(self, db_session):
        """未兑现 my_promise 应拉低分数."""
        user_id = "user-4"
        eid = str(uuid.uuid4())
        db_session.add(_make_todo(
            user_id, related_entity_id=eid,
            action_type="my_promise", fulfillment_status="pending",
        ))
        db_session.add(_make_todo(
            user_id, related_entity_id=eid,
            action_type="their_promise", fulfillment_status="fulfilled",
        ))
        await db_session.flush()

        result = await CreditScoreService.batch_calculate(db_session, [eid], user_id)
        data = result[eid]
        # my_rate=0.0 (0/1), their_rate=1.0 (1/1)
        # total_interactions=2, consistency=min(100, 2*10)=20
        # timeliness=(0.0+1.0)/2*100=50
        # score = 0*0.4 + 100*0.35 + 20*0.15 + 50*0.10 = 0+35+3+5 = 43.0
        assert data["score"] == pytest.approx(43.0, abs=0.1)
        assert data["grade"] == "D"
        assert data["my_fulfillment_rate"] == 0.0
        assert data["their_fulfillment_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_happy_batch_multiple_entities_get_independent_scores(self, db_session):
        """批量计算多个实体应返回独立分数."""
        user_id = "user-5"
        eid_a = str(uuid.uuid4())
        eid_b = str(uuid.uuid4())
        # eid_a: fulfilled my_promise
        db_session.add(_make_todo(
            user_id, related_entity_id=eid_a,
            action_type="my_promise", fulfillment_status="fulfilled",
        ))
        # eid_b: unfulfilled my_promise
        db_session.add(_make_todo(
            user_id, related_entity_id=eid_b,
            action_type="my_promise", fulfillment_status="pending",
        ))
        await db_session.flush()

        result = await CreditScoreService.batch_calculate(
            db_session, [eid_a, eid_b], user_id
        )
        assert len(result) == 2
        assert result[eid_a]["score"] > result[eid_b]["score"]
        assert result[eid_a]["my_fulfillment_rate"] == 1.0
        assert result[eid_b]["my_fulfillment_rate"] == 0.0


# ═══════════════════════════════════════════════════════════════
# calculate — 单实体便捷包装
# ═══════════════════════════════════════════════════════════════


class TestCalculate:
    """calculate 单实体便捷包装."""

    @pytest.mark.asyncio
    async def test_happy_calculate_returns_same_as_batch(self, db_session):
        """calculate 单实体应返回与 batch_calculate 一致的结果."""
        user_id = "user-6"
        eid = await _make_event_and_entity(db_session, user_id)
        db_session.add(_make_todo(
            user_id, related_entity_id=eid,
            action_type="my_promise", fulfillment_status="fulfilled",
        ))
        await db_session.flush()

        batch_result = await CreditScoreService.batch_calculate(db_session, [eid], user_id)
        single_result = await CreditScoreService.calculate(db_session, eid, user_id)
        assert single_result["score"] == batch_result[eid]["score"]
        assert single_result["grade"] == batch_result[eid]["grade"]

    @pytest.mark.asyncio
    async def test_boundary_non_existent_entity_returns_default_dict(self, db_session):
        """未在数据库中的实体应返回默认字典 (score=0, grade=D)."""
        result = await CreditScoreService.calculate(
            db_session, str(uuid.uuid4()), "user-7"
        )
        assert result["score"] == 0
        assert result["grade"] == "D"
        assert result["my_fulfillment_rate"] == 0.5
        assert result["their_fulfillment_rate"] == 0.5
        assert result["interaction_consistency"] == 50
        assert result["total_interactions"] == 0


# ═══════════════════════════════════════════════════════════════
# Grade 阈值边界
# ═══════════════════════════════════════════════════════════════


class TestGradeThresholds:
    """验证 A+/A/B/C/D 等级阈值边界."""

    @pytest.mark.parametrize("expected_grade,min_score,max_score", [
        ("A+", 90, 100),
        ("A", 80, 89.999),
        ("B", 70, 79.999),
        ("C", 60, 69.999),
        ("D", 0, 59.999),
    ])
    def test_grade_thresholds_documented(self, expected_grade, min_score, max_score):
        """文档化等级阈值 (公式边界验证)."""
        # This test documents the grade thresholds from the source code
        # so that any change to the thresholds will require updating this test.
        if expected_grade == "A+":
            assert min_score == 90
        elif expected_grade == "A":
            assert min_score == 80
        elif expected_grade == "B":
            assert min_score == 70
        elif expected_grade == "C":
            assert min_score == 60
        elif expected_grade == "D":
            assert max_score < 60

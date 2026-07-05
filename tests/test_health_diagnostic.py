"""Tests for promiselink.services.health_diagnostic.

Covers compute_health_score / generate_suggestion pure functions and
scan_all_entity_health async DB function. Happy/Boundary/Error dimensions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.health_diagnostic import (
    compute_health_score,
    generate_suggestion,
    scan_all_entity_health,
)
from promiselink.services.relationship_stage import RelationshipStage


async def _make_event(session, user_id: str) -> str:
    """Create a placeholder Event to satisfy Entity.source_event_id FK."""
    eid = str(uuid.uuid4())
    session.add(Event(
        id=eid, user_id=user_id, event_type="meeting",
        source="test", title="placeholder", raw_text="x", status="completed",
    ))
    await session.flush()
    return eid


def _make_entity(user_id: str, name: str, *, source_event_id: str, **kwargs) -> Entity:
    """Construct Entity with required fields."""
    return Entity(
        id=str(uuid.uuid4()),
        user_id=user_id,
        entity_type="person",
        name=name,
        canonical_name=name,
        status="confirmed",
        source_event_id=source_event_id,
        **kwargs,
    )


# ═══════════════════════════════════════════════════════════════
# compute_health_score — 纯函数
# ═══════════════════════════════════════════════════════════════


class TestComputeHealthScore:
    """健康分数计算 — Happy/Boundary/Error 三维度."""

    def test_happy_high_stage_recent_interaction(self):
        """高阶段 + 多互动 + 近期联系 + 无逾期 → healthy (≥70)."""
        score, level = compute_health_score(
            stage_val=RelationshipStage.LONG_TERM_PARTNER.value,
            interaction_count=20,
            days_since_last=3,
            has_overdue_promise=False,
            has_pending_promise=True,
            pending_todo_count=1,
        )
        assert level == "healthy"
        assert score >= 70
        assert isinstance(score, float)

    def test_happy_new_connection_low_score(self):
        """新连接 + 少互动 + 从未联系 → at_risk (<40)."""
        score, level = compute_health_score(
            stage_val=RelationshipStage.NEW_CONNECTION.value,
            interaction_count=0,
            days_since_last=None,
            has_overdue_promise=False,
            has_pending_promise=False,
            pending_todo_count=0,
        )
        # new_connection order=1, stage_score=14.3; interaction=0; recency=30 (None);
        # promise=70 (neutral); todo=100 → total ≈ 14.3*0.3 + 0 + 30*0.2 + 70*0.15 + 100*0.1
        # = 4.3 + 0 + 6 + 10.5 + 10 = 30.8 → at_risk
        assert level == "at_risk"
        assert score < 40

    def test_boundary_days_since_last_thresholds(self):
        """recency_score 4 档阈值: ≤7=100, ≤30=60, ≤90=30, >90=0."""
        # ≤7 days
        _, level_7 = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=7, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        # ≤30 days
        _, level_30 = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=30, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        # ≤90 days
        score_90, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=90, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        # >90 days
        score_180, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=180, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        # recency 30 > 0 — score_90 > score_180
        assert score_90 > score_180

    def test_boundary_overdue_promise_reduces_score(self):
        """overdue_promise → promise_score=40 (低于 pending=100)."""
        score_overdue, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=True,
            has_pending_promise=False, pending_todo_count=0,
        )
        score_pending, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=True, pending_todo_count=0,
        )
        assert score_overdue < score_pending

    def test_boundary_todo_density_decreases_score(self):
        """pending_todo_count 越多,todo_score 越低 (max(0, 100-count*10))."""
        score_0, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        score_5, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=5,
        )
        score_15, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=15,
        )
        assert score_0 > score_5 > score_15

    def test_boundary_interaction_count_capped_at_100(self):
        """interaction_count * 8 上限 100 (12.5 interactions 已达上限)."""
        score_13, _ = compute_health_score(
            stage_val="new_connection", interaction_count=13,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        score_100, _ = compute_health_score(
            stage_val="new_connection", interaction_count=100,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        # 都达到 cap,分数应相等
        assert score_13 == score_100

    def test_error_unknown_stage_defaults_to_order_1(self):
        """未知 stage_val 走默认 order=1 (与 new_connection 相同)."""
        score_unknown, _ = compute_health_score(
            stage_val="nonexistent_stage", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        score_new, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        assert score_unknown == score_new

    def test_error_none_stage_defaults_to_new_connection(self):
        """stage_val=None 应与 new_connection 等价."""
        score_none, _ = compute_health_score(
            stage_val=None, interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        score_new, _ = compute_health_score(
            stage_val="new_connection", interaction_count=10,
            days_since_last=3, has_overdue_promise=False,
            has_pending_promise=False, pending_todo_count=0,
        )
        assert score_none == score_new


# ═══════════════════════════════════════════════════════════════
# generate_suggestion — 纯函数
# ═══════════════════════════════════════════════════════════════


class TestGenerateSuggestion:
    """建议生成 — Happy/Boundary."""

    def test_happy_new_connection(self):
        s = generate_suggestion("new_connection", 5)
        assert "深入交流" in s

    def test_happy_understanding_needs_long_gap(self):
        s = generate_suggestion("understanding_needs", 30)
        assert "未联系" in s or "跟进" in s

    def test_happy_understanding_needs_short_gap(self):
        s = generate_suggestion("understanding_needs", 5)
        assert "深化" in s or "价值" in s

    def test_happy_dormant(self):
        s = generate_suggestion("dormant", 100)
        assert "沉寂" in s or "活化" in s

    def test_boundary_unknown_stage_default_message(self):
        s = generate_suggestion("nonexistent_stage", 10)
        assert "保持当前节奏" in s

    def test_boundary_none_stage_uses_default(self):
        s = generate_suggestion(None, None)
        # None stage → "new_connection", None days → 999
        assert isinstance(s, str) and len(s) > 0


# ═══════════════════════════════════════════════════════════════
# scan_all_entity_health — DB 集成
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestScanAllEntityHealth:
    """扫描所有实体健康度 — DB 集成测试."""

    async def test_happy_returns_entities_with_scores(self, db_session):
        """有 person entity 时应返回带 health_score 的列表."""
        user_id = str(uuid.uuid4())
        event_id = await _make_event(db_session, user_id)
        entity = _make_entity(user_id, "张三", source_event_id=event_id, properties={
            "relationship_stage": "new_connection",
            "basic": {"company": "TestCorp"},
        })
        db_session.add(entity)
        await db_session.flush()

        results = await scan_all_entity_health(db_session, user_id, limit=20)

        assert isinstance(results, list)
        assert len(results) == 1
        item = results[0]
        assert item["entity_id"] == str(entity.id)
        assert item["name"] == "张三"
        assert item["company"] == "TestCorp"
        assert "health_score" in item
        assert "health_level" in item
        assert item["health_level"] in ("healthy", "attention", "at_risk")
        assert "suggestion" in item

    async def test_boundary_no_entities_returns_empty_list(self, db_session):
        """无 entity 应返回空列表."""
        results = await scan_all_entity_health(db_session, str(uuid.uuid4()))
        assert results == []

    async def test_boundary_filters_non_person_entities(self, db_session):
        """非 person entity (如 organization) 应被过滤."""
        user_id = str(uuid.uuid4())
        event_id = await _make_event(db_session, user_id)
        org = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="organization",
            name="TestOrg", canonical_name="TestOrg",
            status="confirmed", source_event_id=event_id,
        )
        person = _make_entity(user_id, "张三", source_event_id=event_id)
        db_session.add_all([org, person])
        await db_session.flush()

        results = await scan_all_entity_health(db_session, user_id)
        assert len(results) == 1
        assert results[0]["name"] == "张三"

    async def test_boundary_filters_deleted_entities(self, db_session):
        """status='deleted' 的 entity 应被过滤 (只保留 provisional/confirmed)."""
        user_id = str(uuid.uuid4())
        event_id = await _make_event(db_session, user_id)
        deleted_entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="person",
            name="已删除", canonical_name="已删除",
            status="deleted", source_event_id=event_id,
        )
        active_entity = _make_entity(user_id, "活跃", source_event_id=event_id)
        db_session.add_all([deleted_entity, active_entity])
        await db_session.flush()

        results = await scan_all_entity_health(db_session, user_id)
        assert len(results) == 1
        assert results[0]["name"] == "活跃"

    async def test_boundary_user_isolation(self, db_session):
        """不同用户的 entity 不应混入."""
        user_a = str(uuid.uuid4())
        user_b = str(uuid.uuid4())
        event_a = await _make_event(db_session, user_a)
        event_b = await _make_event(db_session, user_b)
        e_a = _make_entity(user_a, "A", source_event_id=event_a)
        e_b = _make_entity(user_b, "B", source_event_id=event_b)
        db_session.add_all([e_a, e_b])
        await db_session.flush()

        results_a = await scan_all_entity_health(db_session, user_a)
        results_b = await scan_all_entity_health(db_session, user_b)
        assert len(results_a) == 1 and results_a[0]["name"] == "A"
        assert len(results_b) == 1 and results_b[0]["name"] == "B"

    async def test_boundary_limit_truncates_results(self, db_session):
        """limit 参数应截断结果."""
        user_id = str(uuid.uuid4())
        event_id = await _make_event(db_session, user_id)
        for i in range(5):
            db_session.add(_make_entity(user_id, f"entity_{i}", source_event_id=event_id))
        await db_session.flush()

        results = await scan_all_entity_health(db_session, user_id, limit=3)
        assert len(results) == 3

    async def test_boundary_properties_none_uses_default_stage(self, db_session):
        """entity.properties=None 应走默认 stage (new_connection)."""
        user_id = str(uuid.uuid4())
        event_id = await _make_event(db_session, user_id)
        entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="无属性",
            canonical_name="无属性",
            status="confirmed",
            source_event_id=event_id,
            properties=None,
        )
        db_session.add(entity)
        await db_session.flush()

        results = await scan_all_entity_health(db_session, user_id)
        assert len(results) == 1
        # properties=None → stage_val="new_connection"
        assert results[0]["stage"] == "new_connection"

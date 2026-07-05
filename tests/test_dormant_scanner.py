"""Tests for promiselink.services.dormant_scanner.

Tests scan_dormant_contacts async DB function plus pure helpers
_extract_company / _extract_concerns / _generate_icebreaker.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.services.dormant_scanner import (
    DormantContactResult,
    _extract_company,
    _extract_concerns,
    _generate_icebreaker,
    scan_dormant_contacts,
)

# ── Helpers ──


async def _make_event(session, user_id: str, *, days_ago: int = 0, raw_text: str = "x") -> str:
    """Create an Event with controllable timestamp."""
    eid = str(uuid.uuid4())
    evt = Event(
        id=eid, user_id=user_id, event_type="meeting",
        source="test", title="placeholder", raw_text=raw_text, status="completed",
    )
    if days_ago > 0:
        evt.timestamp = datetime.now(UTC) - timedelta(days=days_ago)
    session.add(evt)
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
# _extract_company — 纯函数
# ═══════════════════════════════════════════════════════════════


class TestExtractCompany:
    """_extract_company 从 properties 提取公司名."""

    def test_none_properties_returns_none(self):
        assert _extract_company(None) is None

    def test_empty_dict_returns_none(self):
        assert _extract_company({}) is None

    def test_no_basic_key_returns_none(self):
        assert _extract_company({"other": "value"}) is None

    def test_basic_without_company_returns_none(self):
        assert _extract_company({"basic": {"title": "CEO"}}) is None

    def test_basic_with_company_returns_company(self):
        assert _extract_company({"basic": {"company": "智源AI"}}) == "智源AI"

    def test_basic_not_dict_returns_none(self):
        assert _extract_company({"basic": "not a dict"}) is None


# ═══════════════════════════════════════════════════════════════
# _extract_concerns — 纯函数
# ═══════════════════════════════════════════════════════════════


class TestExtractConcerns:
    """_extract_concerns 从 properties 提取关注点."""

    def test_none_properties_returns_empty_list(self):
        assert _extract_concerns(None) == []

    def test_empty_dict_returns_empty_list(self):
        assert _extract_concerns({}) == []

    def test_no_concern_key_returns_empty_list(self):
        assert _extract_concerns({"other": "value"}) == []

    def test_string_concern_returns_single_item_list(self):
        result = _extract_concerns({"concern": "技术方案"})
        assert result == ["技术方案"]

    def test_list_concern_returns_list(self):
        concerns = ["技术方案", "交付时间"]
        result = _extract_concerns({"concern": concerns})
        assert result == concerns


# ═══════════════════════════════════════════════════════════════
# _generate_icebreaker — 纯函数
# ═══════════════════════════════════════════════════════════════


class TestGenerateIcebreaker:
    """_generate_icebreaker 模板化破冰话术生成."""

    def test_with_concerns_returns_concern_based(self):
        """有 concerns 时优先返回基于关注点的话术."""
        result = _generate_icebreaker(
            name="张总", last_topic="", concerns=["技术方案"], days_ago=30
        )
        assert "张总" in result
        assert "技术方案" in result
        assert "进展" in result

    def test_without_concerns_recent_days_returns_recent_template(self):
        """无 concerns + days_ago<90 → '好久不见！最近一切都好吧？'."""
        result = _generate_icebreaker(
            name="李总", last_topic="", concerns=[], days_ago=30
        )
        assert "李总" in result
        assert "好久不见" in result
        assert "最近一切" in result

    def test_without_concerns_medium_days_returns_medium_template(self):
        """无 concerns + 90<=days_ago<180 → '几个月没联系了'."""
        result = _generate_icebreaker(
            name="王总", last_topic="", concerns=[], days_ago=120
        )
        assert "王总" in result
        assert "几个月没联系" in result

    def test_without_concerns_long_days_returns_long_template(self):
        """无 concerns + days_ago>=180 → '很久没聊了'."""
        result = _generate_icebreaker(
            name="赵总", last_topic="", concerns=[], days_ago=200
        )
        assert "赵总" in result
        assert "很久没聊" in result

    def test_with_long_last_topic_days_ago_template_takes_priority(self):
        """无 concerns + days_ago<90 + 长 last_topic → days_ago 模板优先于 last_topic.

        函数返回第一个非空模板，顺序为: concerns > days_ago > last_topic > default.
        由于 days_ago 分支总会产生非空模板，last_topic 模板实际不可达 (dead code).
        """
        result = _generate_icebreaker(
            name="张总",
            last_topic="上次讨论的技术方案非常详细",
            concerns=[],
            days_ago=30,
        )
        assert "张总" in result
        # days_ago=30 (<90) → "好久不见！最近一切都好吧？" wins over last_topic
        assert "好久不见" in result
        assert "最近一切" in result

    def test_default_fallback(self):
        """无 concerns + 短 last_topic + 短 days_ago → 默认模板."""
        result = _generate_icebreaker(
            name="张总", last_topic="", concerns=[], days_ago=0
        )
        assert "张总" in result
        # Should return some non-empty template
        assert len(result) > 5


# ═══════════════════════════════════════════════════════════════
# scan_dormant_contacts — DB 集成
# ═══════════════════════════════════════════════════════════════


class TestScanDormantContacts:
    """scan_dormant_contacts 沉睡联系人扫描."""

    @pytest.mark.asyncio
    async def test_boundary_empty_database_returns_empty(self, db_session):
        """无任何实体时应返回 ([], 0)."""
        items, total = await scan_dormant_contacts(db_session, "user-empty")
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_boundary_recent_entity_not_dormant(self, db_session):
        """近期互动的实体不算沉睡 (dormant_days < min_days 被跳过)."""
        user_id = "user-recent"
        eid = await _make_event(db_session, user_id, days_ago=5)
        db_session.add(_make_entity(user_id, "张三", source_event_id=eid))
        await db_session.flush()

        items, total = await scan_dormant_contacts(db_session, user_id, min_days=60)
        assert items == []
        assert total == 0

    @pytest.mark.asyncio
    async def test_happy_dormant_entity_included_in_results(self, db_session):
        """沉睡实体 (超过 min_days 天无互动) 应出现在结果中."""
        user_id = "user-dormant"
        # Create event 90 days ago mentioning "李四"
        old_eid = await _make_event(
            db_session, user_id, days_ago=90, raw_text="和李四讨论合作"
        )
        db_session.add(_make_entity(user_id, "李四", source_event_id=old_eid))
        await db_session.flush()

        items, total = await scan_dormant_contacts(db_session, user_id, min_days=60)
        assert total == 1
        assert len(items) == 1
        assert items[0].name == "李四"
        assert items[0].dormant_days >= 60

    @pytest.mark.asyncio
    async def test_happy_reactivation_score_calculated(self, db_session):
        """reactivation_score 应在 0-100 范围内."""
        user_id = "user-score"
        old_eid = await _make_event(
            db_session, user_id, days_ago=90, raw_text="和王五会议"
        )
        db_session.add(_make_entity(user_id, "王五", source_event_id=old_eid))
        await db_session.flush()

        items, _ = await scan_dormant_contacts(db_session, user_id, min_days=60)
        assert len(items) == 1
        score = items[0].reactivation_score
        assert 0 <= score <= 100

    @pytest.mark.asyncio
    async def test_happy_results_sorted_by_score_descending(self, db_session):
        """结果应按 reactivation_score 降序排列."""
        user_id = "user-sort"
        # Entity A: 100 days dormant
        eid_a = await _make_event(
            db_session, user_id, days_ago=100, raw_text="和赵六开会"
        )
        db_session.add(_make_entity(user_id, "赵六", source_event_id=eid_a))
        # Entity B: 200 days dormant (more decay → lower score typically)
        eid_b = await _make_event(
            db_session, user_id, days_ago=200, raw_text="和钱七见面"
        )
        db_session.add(_make_entity(user_id, "钱七", source_event_id=eid_b))
        await db_session.flush()

        items, total = await scan_dormant_contacts(db_session, user_id, min_days=60)
        assert total == 2
        # Verify sorted descending
        assert items[0].reactivation_score >= items[1].reactivation_score

    @pytest.mark.asyncio
    async def test_boundary_limit_truncates_results(self, db_session):
        """limit 参数应截断返回数量 (但 total 仍反映完整总数)."""
        user_id = "user-limit"
        for i in range(3):
            eid = await _make_event(
                db_session, user_id, days_ago=90, raw_text=f"和联系人{i}开会"
            )
            db_session.add(_make_entity(user_id, f"联系人{i}", source_event_id=eid))
        await db_session.flush()

        items, total = await scan_dormant_contacts(db_session, user_id, limit=2, min_days=60)
        assert len(items) == 2
        assert total == 3

    @pytest.mark.asyncio
    async def test_boundary_offset_skips_results(self, db_session):
        """offset 参数应跳过前 N 条结果."""
        user_id = "user-offset"
        for i in range(3):
            eid = await _make_event(
                db_session, user_id, days_ago=90, raw_text=f"和客户{i}见面"
            )
            db_session.add(_make_entity(user_id, f"客户{i}", source_event_id=eid))
        await db_session.flush()

        items, total = await scan_dormant_contacts(db_session, user_id, limit=10, offset=1, min_days=60)
        assert total == 3
        assert len(items) == 2  # 3 total - 1 offset = 2 returned


# ═══════════════════════════════════════════════════════════════
# DormantContactResult.to_dict
# ═══════════════════════════════════════════════════════════════


class TestDormantContactResultToDict:
    """DormantContactResult.to_dict 序列化."""

    def test_to_dict_contains_all_fields(self):
        """to_dict 应包含所有公开字段."""
        result = DormantContactResult(
            entity_id="eid-1",
            name="张三",
            company="智源AI",
            dormant_days=90,
            reactivation_score=75.567,
            last_interaction="2026-01-01T00:00:00",
            last_event_summary="讨论合作",
            reason="曾深度互动",
            icebreaker_topic="张总，好久不见",
            pending_their_promises=2,
            relationship_stage="understanding_needs",
        )
        d = result.to_dict()
        assert d["entity_id"] == "eid-1"
        assert d["name"] == "张三"
        assert d["company"] == "智源AI"
        assert d["dormant_days"] == 90
        # Score should be rounded to 1 decimal
        assert d["reactivation_score"] == 75.6
        assert d["pending_their_promises"] == 2
        assert d["relationship_stage"] == "understanding_needs"

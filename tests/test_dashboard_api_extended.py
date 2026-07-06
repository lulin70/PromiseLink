"""Extended tests for Dashboard API modules to improve coverage.

Covers:
  - dashboard_relationship_health.py (relationship-health + care-reminders)
  - dashboard_supply_demand.py (supply-demand matching)
  - dashboard_day_view.py (scheduled events, extended scenarios)
  - dashboard_morning_brief.py (morning brief)
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.scheduled_event import ScheduledEvent
from promiselink.models.todo import Todo

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"
TARGET_DATE = "2026-06-04"
FIXED_TODAY = date(2026, 6, 4)


# ── Fixtures (mirrors test_dashboard_api.py for isolation) ──


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    @sa_event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, db_engine):
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Helpers ──


async def _seed_event(
    session, title, event_type="meeting", days_offset=0, hour=10,
    status="completed", input_scope=None, created_at=None,
):
    target = date(2026, 6, 4) + timedelta(days=days_offset)
    ts = datetime(target.year, target.month, target.day, hour, 0, 0, tzinfo=UTC)
    evt = Event(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        event_type=event_type,
        source="test",
        title=title,
        timestamp=ts,
        status=status,
        input_scope=input_scope,
    )
    if created_at is not None:
        evt.created_at = created_at
    session.add(evt)
    await session.flush()
    return evt


async def _seed_todo(
    session, title, todo_type="promise", days_offset=0, status="pending",
    action_type=None, related_entity_id=None, source_event=None,
    fulfillment_status="pending", priority=3,
):
    target = date(2026, 6, 4) + timedelta(days=days_offset)
    due_dt = datetime(target.year, target.month, target.day, 18, 0, 0, tzinfo=UTC)
    evt_id = str(source_event.id) if source_event else str(uuid.uuid4())
    td = Todo(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        todo_type=todo_type,
        title=title,
        due_date=due_dt,
        status=status,
        action_type=action_type,
        source_event_id=evt_id,
        related_entity_id=str(related_entity_id) if related_entity_id else None,
        fulfillment_status=fulfillment_status,
        priority=priority,
    )
    session.add(td)
    await session.flush()
    return td


async def _seed_person_entity(
    session, name, source_event, properties=None, status="confirmed",
    created_at=None,
):
    ent = Entity(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        entity_type="person",
        name=name,
        canonical_name=name,
        source_event_id=str(source_event.id),
        properties=properties,
        status=status,
    )
    if created_at is not None:
        ent.created_at = created_at
        ent.updated_at = created_at
    session.add(ent)
    await session.flush()
    return ent


async def _seed_scheduled_event(
    session, topic, days_offset=0, hour=14, status="pending",
    event_type="meeting", participants=None, location=None,
):
    target = date(2026, 6, 4) + timedelta(days=days_offset)
    scheduled_at = datetime(target.year, target.month, target.day, hour, 0, 0, tzinfo=UTC)
    se = ScheduledEvent(
        id=str(uuid.uuid4()),
        user_id=TEST_USER_ID,
        scheduled_at=scheduled_at,
        topic=topic,
        event_type=event_type,
        status=status,
        participants=participants,
        location=location,
    )
    session.add(se)
    await session.flush()
    return se


# ════════════════════════════════════════════════════════════════════
# Relationship Health Tests (dashboard_relationship_health.py)
# ════════════════════════════════════════════════════════════════════


class TestRelationshipHealthNoData:
    """GET /relationship-health with no entities."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, client: AsyncClient):
        response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")
        assert response.status_code == 200
        data = response.json()
        assert data["total_entities"] == 0
        assert data["healthy_count"] == 0
        assert data["attention_count"] == 0
        assert data["at_risk_count"] == 0
        assert data["items"] == []
        assert "暂无联系人数据" in data["summary_text"]


class TestRelationshipHealthWithEntity:
    """GET /relationship-health with seeded entities."""

    @pytest.mark.asyncio
    async def test_single_entity_new_connection(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "初次会议", days_offset=0)
        await _seed_person_entity(
            db_session, "张三", source_event=evt,
            properties={"relationship_stage": "new_connection"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")

        assert response.status_code == 200
        data = response.json()
        assert data["total_entities"] == 1
        assert data["items"][0]["name"] == "张三"
        assert data["items"][0]["stage"] == "new_connection"
        assert data["items"][0]["health_level"] in ("healthy", "attention", "at_risk")
        assert data["items"][0]["stage_label"]  # non-empty label
        assert data["items"][0]["stage_color"]  # non-empty color


class TestRelationshipHealthStages:
    """Test that different stages produce different health scores."""

    @pytest.mark.asyncio
    async def test_higher_stage_higher_score(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "meeting1", days_offset=0)
        await _seed_person_entity(
            db_session, "NewConn", source_event=evt1,
            properties={"relationship_stage": "new_connection"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )
        evt2 = await _seed_event(db_session, "meeting2", days_offset=0)
        await _seed_person_entity(
            db_session, "Partner", source_event=evt2,
            properties={"relationship_stage": "long_term_partner"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")

        data = response.json()
        assert data["total_entities"] == 2
        partner = [i for i in data["items"] if i["name"] == "Partner"][0]
        new_conn = [i for i in data["items"] if i["name"] == "NewConn"][0]
        assert partner["health_score"] > new_conn["health_score"]

    @pytest.mark.asyncio
    async def test_items_sorted_by_score_desc(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "A", source_event=evt1,
            properties={"relationship_stage": "new_connection"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "B", source_event=evt2,
            properties={"relationship_stage": "active_cooperation"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )
        evt3 = await _seed_event(db_session, "m3", days_offset=0)
        await _seed_person_entity(
            db_session, "C", source_event=evt3,
            properties={"relationship_stage": "value_response"},
            created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
        )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")

        scores = [i["health_score"] for i in response.json()["items"]]
        assert scores == sorted(scores, reverse=True)


class TestRelationshipHealthSummary:
    """Test summary text for different scenarios."""

    @pytest.mark.asyncio
    async def test_summary_all_healthy(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "recent meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "Active", source_event=evt,
            properties={"relationship_stage": "active_cooperation"},
            created_at=datetime(2026, 6, 2, 10, 0, 0, tzinfo=UTC),
        )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")

        data = response.json()
        if data["at_risk_count"] == 0 and data["attention_count"] == 0:
            assert "良好" in data["summary_text"]

    @pytest.mark.asyncio
    async def test_summary_with_at_risk(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "old meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "Dormant", source_event=evt,
            properties={"relationship_stage": "new_connection"},
            created_at=datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC),
        )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/relationship-health")

        data = response.json()
        if data["at_risk_count"] > 0:
            assert "需要立即关注" in data["summary_text"]


class TestRelationshipHealthLimit:
    """Test the limit parameter."""

    @pytest.mark.asyncio
    async def test_limit_restricts_items(self, client: AsyncClient, db_session: AsyncSession):
        for i in range(5):
            evt = await _seed_event(db_session, f"m{i}", days_offset=0)
            await _seed_person_entity(
                db_session, f"Person{i}", source_event=evt,
                properties={"relationship_stage": "new_connection"},
                created_at=datetime(2026, 6, 1, 10, 0, 0, tzinfo=UTC),
            )

        with patch("promiselink.services.health_diagnostic.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(
                f"{API_PREFIX}/dashboard/relationship-health", params={"limit": 3}
            )

        data = response.json()
        assert len(data["items"]) == 3


# ════════════════════════════════════════════════════════════════════
# Care Reminders Tests (dashboard_relationship_health.py)
# ════════════════════════════════════════════════════════════════════


class TestCareRemindersNoData:
    """GET /care-reminders with no entities."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, client: AsyncClient):
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["personal_items"] == []
        assert data["business_items"] == []
        assert "暂无关怀提醒" in data["summary_text"]


class TestCareRemindersPersonalKeywords:
    """Test personal concern keyword classification."""

    @pytest.mark.asyncio
    async def test_family_milestone_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "张总", source_event=evt,
            properties={
                "concern": [{"category": "family", "detail": "孩子今年高考"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        assert response.status_code == 200
        data = response.json()
        assert len(data["personal_items"]) == 1
        item = data["personal_items"][0]
        assert item["name"] == "张总"
        assert item["care_type"] == "family_milestone"
        assert item["relevance_score"] > 0
        assert "高考" in item["concern_detail"]
        assert item["care_icon"]  # non-empty icon
        assert item["suggested_action"]  # non-empty action

    @pytest.mark.asyncio
    async def test_hobby_interest_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "李总", source_event=evt,
            properties={
                "concern": [{"detail": "最近在跑马拉松训练"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["care_type"] == "hobby_interest"

    @pytest.mark.asyncio
    async def test_personal_health_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "王总", source_event=evt,
            properties={
                "concern": [{"detail": "最近住院了"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["care_type"] == "personal_health"

    @pytest.mark.asyncio
    async def test_project_milestone_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "赵总", source_event=evt,
            properties={
                "concern": [{"detail": "公司产品刚上线"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["care_type"] == "project_milestone"

    @pytest.mark.asyncio
    async def test_life_change_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "孙总", source_event=evt,
            properties={
                "concern": [{"detail": "最近离职创业了"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["care_type"] == "life_change"


class TestCareRemindersBusinessConcern:
    """Test business concern (no keyword match)."""

    @pytest.mark.asyncio
    async def test_business_concern_no_keyword(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "周总", source_event=evt,
            properties={
                "concern": [{"category": "business", "detail": "项目预算审批"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["business_items"]) == 1
        assert data["business_items"][0]["care_type"] == "business"
        assert data["business_items"][0]["relevance_score"] == 0.0
        assert len(data["personal_items"]) == 0


class TestCareRemindersMultiplePerEntity:
    """Test that only best personal item per entity is kept."""

    @pytest.mark.asyncio
    async def test_best_personal_kept(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "吴总", source_event=evt,
            properties={
                "concern": [
                    {"detail": "孩子高考"},           # family_milestone, 2 hits → 0.7
                    {"detail": "孩子高考儿子留学"},    # family_milestone, 4 hits → 1.0 (higher)
                ]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["relevance_score"] == 1.0


class TestCareRemindersStringConcern:
    """Test string-type concern entries (not dict)."""

    @pytest.mark.asyncio
    async def test_string_concern_entry(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "郑总", source_event=evt,
            properties={
                "concern": ["孩子上学"]  # string, not dict
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["care_type"] == "family_milestone"


class TestCareRemindersSourceEventTitle:
    """Test that source_event_title is fetched correctly."""

    @pytest.mark.asyncio
    async def test_source_event_title_populated(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "和张总的季度会议", days_offset=0)
        await _seed_person_entity(
            db_session, "张总", source_event=evt,
            properties={
                "concern": [{"detail": "孩子高考"}]
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 1
        assert data["personal_items"][0]["source_event_title"] == "和张总的季度会议"


class TestCareRemindersSummary:
    """Test summary text generation."""

    @pytest.mark.asyncio
    async def test_summary_with_personal(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "张三", source_event=evt,
            properties={"concern": [{"detail": "孩子高考"}]},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert "个人关怀点" in data["summary_text"]
        assert "张三" in data["summary_text"]

    @pytest.mark.asyncio
    async def test_summary_only_business(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "李四", source_event=evt,
            properties={"concern": [{"detail": "项目预算"}]},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert len(data["personal_items"]) == 0
        assert len(data["business_items"]) == 1
        assert "业务关切" in data["summary_text"]


class TestCareRemindersCompany:
    """Test company extraction in care reminders."""

    @pytest.mark.asyncio
    async def test_company_extracted(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        await _seed_person_entity(
            db_session, "王总", source_event=evt,
            properties={
                "basic": {"company": "智源AI"},
                "concern": [{"detail": "孩子高考"}],
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/care-reminders")
        data = response.json()
        assert data["personal_items"][0]["company"] == "智源AI"


# ════════════════════════════════════════════════════════════════════
# Supply-Demand Tests (dashboard_supply_demand.py)
# ════════════════════════════════════════════════════════════════════


class TestSupplyDemandNoData:
    """GET /supply-demand with no entities."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, client: AsyncClient):
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["matches"] == []


class TestSupplyDemandMatchFound:
    """Test successful supply-demand matching."""

    @pytest.mark.asyncio
    async def test_match_with_overlap(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={
                "basic": {"company": "需求公司"},
                "resource": {"demand": "AI,云计算"},
            },
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={
                "basic": {"company": "供应公司"},
                "resource": {"capabilities": ["AI", "大数据", "云计算"]},
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        match = data["matches"][0]
        assert match["demander_name"] == "需求方"
        assert match["supplier_name"] == "供应方"
        assert match["demander_company"] == "需求公司"
        assert match["supplier_company"] == "供应公司"
        assert match["match_score"] > 0
        assert "关键词匹配" in match["match_reason"]


class TestSupplyDemandSelfMatchExcluded:
    """Test that self-matching is excluded."""

    @pytest.mark.asyncio
    async def test_self_match_excluded(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "m", days_offset=0)
        await _seed_person_entity(
            db_session, "自匹配", source_event=evt,
            properties={
                "resource": {
                    "demand": "AI,云计算",
                    "capabilities": ["AI", "云计算"],
                }
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        data = response.json()
        assert data["total"] == 0


class TestSupplyDemandNoOverlap:
    """Test that no keyword overlap produces no match."""

    @pytest.mark.asyncio
    async def test_no_overlap_no_match(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={"resource": {"demand": "AI"}},
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={"resource": {"capabilities": ["法律咨询"]}},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        data = response.json()
        assert data["total"] == 0


class TestSupplyDemandStringSupply:
    """Test supply as string (not list)."""

    @pytest.mark.asyncio
    async def test_string_supply(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={"resource": {"demand": "AI,大数据"}},
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={"resource": {"supply": "AI,大数据"}},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        data = response.json()
        assert data["total"] == 1
        assert data["matches"][0]["supply_text"] == "AI,大数据"


class TestSupplyDemandSupplyKeyFallback:
    """Test that 'supply' key is used when 'capabilities' is absent."""

    @pytest.mark.asyncio
    async def test_supply_key_fallback(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={"resource": {"demand": "AI,大数据"}},
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={"resource": {"supply": ["AI", "大数据"]}},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        data = response.json()
        assert data["total"] == 1
        assert "AI" in data["matches"][0]["supply_text"]


class TestSupplyDemandSortedByScore:
    """Test that matches are sorted by score descending."""

    @pytest.mark.asyncio
    async def test_sorted_by_score(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={"resource": {"demand": "AI,大数据,云计算"}},
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "高分配方", source_event=evt2,
            properties={"resource": {"capabilities": ["AI", "大数据", "云计算"]}},
        )
        evt3 = await _seed_event(db_session, "m3", days_offset=0)
        await _seed_person_entity(
            db_session, "低分配方", source_event=evt3,
            properties={"resource": {"capabilities": ["AI"]}},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand", params={"limit": 20})
        data = response.json()
        scores = [m["match_score"] for m in data["matches"]]
        assert scores == sorted(scores, reverse=True)


class TestSupplyDemandCompanyExtraction:
    """Test company extraction from properties."""

    @pytest.mark.asyncio
    async def test_company_extracted_in_match(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={
                "basic": {"company": "需方公司"},
                "resource": {"demand": "AI"},
            },
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={
                "basic": {"company": "供方公司"},
                "resource": {"capabilities": ["AI"]},
            },
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        match = response.json()["matches"][0]
        assert match["demander_company"] == "需方公司"
        assert match["supplier_company"] == "供方公司"

    @pytest.mark.asyncio
    async def test_no_company_returns_none(self, client: AsyncClient, db_session: AsyncSession):
        evt1 = await _seed_event(db_session, "m1", days_offset=0)
        await _seed_person_entity(
            db_session, "需求方", source_event=evt1,
            properties={"resource": {"demand": "AI"}},
        )
        evt2 = await _seed_event(db_session, "m2", days_offset=0)
        await _seed_person_entity(
            db_session, "供应方", source_event=evt2,
            properties={"resource": {"capabilities": ["AI"]}},
        )
        response = await client.get(f"{API_PREFIX}/dashboard/supply-demand")
        match = response.json()["matches"][0]
        assert match["demander_company"] is None
        assert match["supplier_company"] is None


# ════════════════════════════════════════════════════════════════════
# Day View Extended Tests (dashboard_day_view.py)
# ════════════════════════════════════════════════════════════════════


class TestDayViewScheduledEvents:
    """Test scheduled_events in day view."""

    @pytest.mark.asyncio
    async def test_scheduled_event_for_date(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_scheduled_event(db_session, "团队会议", days_offset=0, status="pending")
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        assert response.status_code == 200
        scheduled = response.json()["scheduled_events"]
        assert len(scheduled) == 1
        assert scheduled[0]["topic"] == "团队会议"
        assert scheduled[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_scheduled_event_participants(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_scheduled_event(
            db_session, "有参与者的会议", days_offset=0,
            participants=[{"name": "张三", "company": "ABC"}],
            location="会议室A",
        )
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        scheduled = response.json()["scheduled_events"]
        assert len(scheduled) == 1
        assert scheduled[0]["participants"] == [{"name": "张三", "company": "ABC"}]
        assert scheduled[0]["location"] == "会议室A"

    @pytest.mark.asyncio
    async def test_cancelled_scheduled_excluded(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_scheduled_event(db_session, "已取消", days_offset=0, status="cancelled")
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        scheduled = response.json()["scheduled_events"]
        assert len(scheduled) == 0


class TestDayViewOverdueScheduledMerged:
    """Test that overdue scheduled events are merged into the view."""

    @pytest.mark.asyncio
    async def test_overdue_scheduled_merged(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_scheduled_event(db_session, "今天的会议", days_offset=0, status="pending")
        await _seed_scheduled_event(db_session, "逾期会议", days_offset=-5, status="overdue")
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        scheduled = response.json()["scheduled_events"]
        topics = [s["topic"] for s in scheduled]
        assert "今天的会议" in topics
        assert "逾期会议" in topics

    @pytest.mark.asyncio
    async def test_summary_scheduled_counts(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_scheduled_event(db_session, "待定会议", days_offset=0, status="pending")
        await _seed_scheduled_event(db_session, "逾期会议", days_offset=-5, status="overdue")
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        summary = response.json()["summary"]
        assert summary["pending_schedules"] >= 1
        assert summary["overdue_schedules"] >= 1


class TestDayViewAdjacentDateEventsExcluded:
    """Test that events on adjacent dates don't appear in target date."""

    @pytest.mark.asyncio
    async def test_adjacent_events_excluded(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "前一天的事件", days_offset=-1)
        await _seed_event(db_session, "后一天的事件", days_offset=1)
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        events = response.json()["events"]
        titles = [e["title"] for e in events]
        assert "前一天的事件" not in titles
        assert "后一天的事件" not in titles
        assert len(events) == 0


class TestDayViewTimeConversion:
    """Test UTC to CST time conversion in event items."""

    @pytest.mark.asyncio
    async def test_time_converted_to_cst(self, client: AsyncClient, db_session: AsyncSession):
        # Event at 10:00 UTC = 18:00 CST
        await _seed_event(db_session, "上午十点UTC", days_offset=0, hour=10)
        response = await client.get(
            f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
        )
        events = response.json()["events"]
        assert len(events) == 1
        # 10:00 UTC + 8 hours = 18:00 CST
        assert events[0]["time"] == "18:00"


class TestDayViewActionableTodosMerged:
    """Test that actionable todos (no due date or overdue) are merged."""

    @pytest.mark.asyncio
    async def test_overdue_actionable_todo_appears(self, client: AsyncClient, db_session: AsyncSession):
        # Todo due in the past, still pending
        await _seed_todo(db_session, "逾期待办", todo_type="help", days_offset=-3, status="pending")
        with patch("promiselink.api.v1.dashboard_day_view.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 4)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            response = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": TARGET_DATE}
            )
        todos = response.json()["todos"]
        titles = [t["title"] for t in todos]
        assert "逾期待办" in titles


# ════════════════════════════════════════════════════════════════════
# Morning Brief Tests (dashboard_morning_brief.py)
# ════════════════════════════════════════════════════════════════════


class TestMorningBriefNoData:
    """GET /morning-brief with no data."""

    @pytest.mark.asyncio
    async def test_no_data_returns_empty(self, client: AsyncClient):
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert response.status_code == 200
        data = response.json()
        assert data["pending_promises"] == 0
        assert data["pending_cares"] == 0
        assert data["overdue_todos"] == 0
        assert data["today_events"] == 0
        assert data["today_todos"] == 0
        assert data["key_persons"] == []
        assert data["summary_text"] == "今天暂无待处理事项"


class TestMorningBriefCounts:
    """Test morning brief count fields."""

    @pytest.mark.asyncio
    async def test_counts_correct(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "今天的会议", days_offset=0)
        await _seed_todo(db_session, "待办承诺", todo_type="promise", status="pending", days_offset=0)
        await _seed_todo(db_session, "关怀跟进", todo_type="care", status="pending", days_offset=0)
        await _seed_todo(db_session, "逾期待办", todo_type="help", status="pending", days_offset=-5)

        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")

        assert response.status_code == 200
        data = response.json()
        assert data["pending_promises"] == 1
        assert data["pending_cares"] == 1
        assert data["overdue_todos"] == 1
        assert data["today_events"] == 1
        assert data["today_todos"] == 2  # promise + care due today

    @pytest.mark.asyncio
    async def test_done_todo_not_counted_as_overdue(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_todo(db_session, "已完成", todo_type="help", status="done", days_offset=-5)
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert data["overdue_todos"] == 0


class TestMorningBriefKeyPersons:
    """Test key_persons extraction."""

    @pytest.mark.asyncio
    async def test_key_persons_from_pending_todos(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        person1 = await _seed_person_entity(db_session, "张三", source_event=evt)
        person2 = await _seed_person_entity(db_session, "李四", source_event=evt)
        await _seed_todo(
            db_session, "给张三的承诺", todo_type="promise", status="pending",
            related_entity_id=person1.id, source_event=evt, days_offset=0,
        )
        await _seed_todo(
            db_session, "给李四的关怀", todo_type="care", status="pending",
            related_entity_id=person2.id, source_event=evt, days_offset=0,
        )
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert "张三" in data["key_persons"]
        assert "李四" in data["key_persons"]

    @pytest.mark.asyncio
    async def test_key_persons_excludes_done_todos(self, client: AsyncClient, db_session: AsyncSession):
        evt = await _seed_event(db_session, "meeting", days_offset=0)
        person = await _seed_person_entity(db_session, "王五", source_event=evt)
        await _seed_todo(
            db_session, "已完成的待办", todo_type="promise", status="done",
            related_entity_id=person.id, source_event=evt, days_offset=0,
        )
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert "王五" not in data["key_persons"]


class TestMorningBriefGreeting:
    """Test greeting field."""

    @pytest.mark.asyncio
    async def test_greeting_is_valid(self, client: AsyncClient):
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert data["greeting"] in ("早上好", "下午好", "晚上好")


class TestMorningBriefSummaryText:
    """Test summary_text generation."""

    @pytest.mark.asyncio
    async def test_summary_with_all_components(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "今天的会议", days_offset=0)
        await _seed_todo(db_session, "承诺", todo_type="promise", status="pending", days_offset=0)
        await _seed_todo(db_session, "关怀", todo_type="care", status="pending", days_offset=0)
        await _seed_todo(db_session, "逾期", todo_type="help", status="pending", days_offset=-5)

        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")

        summary = response.json()["summary_text"]
        assert "1个待回应承诺" in summary
        assert "1个关注跟进" in summary
        assert "1个已逾期" in summary
        assert "今天1个互动" in summary


class TestMorningBriefDate:
    """Test date field."""

    @pytest.mark.asyncio
    async def test_date_field(self, client: AsyncClient):
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert data["date"] == FIXED_TODAY.isoformat()


class TestMorningBriefAdjacentDateEventExcluded:
    """Events on adjacent dates should not be counted as today's events."""

    @pytest.mark.asyncio
    async def test_yesterday_event_not_counted(self, client: AsyncClient, db_session: AsyncSession):
        await _seed_event(db_session, "昨天的事", days_offset=-1)
        with patch("promiselink.api.v1.dashboard_morning_brief.date") as mock_date:
            mock_date.today.return_value = FIXED_TODAY
            response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        data = response.json()
        assert data["today_events"] == 0
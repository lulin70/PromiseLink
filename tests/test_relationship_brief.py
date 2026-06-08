"""Tests for RelationshipBriefService and RelationshipBrief API — F-47.

Covers:
1.  get_or_create_brief: create new brief
2.  get_or_create_brief: return existing brief
3.  update_brief_from_event: update last_interaction
4.  update_brief_from_event: sync open_promises from todos
5.  update_brief_from_event: extract their_concerns from care todos
6.  _calculate_strength_score: high interaction → high score
7.  _calculate_strength_score: no interaction → low score
8.  _generate_next_actions: overdue promise → priority reminder
9.  list_briefs: filter by stage
10. list_briefs: pagination (limit/offset)
11. API: GET /persons/{id}/relationship-brief success
12. API: GET /persons/{id}/relationship-brief not found → 404
13. API: PATCH optimistic lock success (version match)
14. API: PATCH optimistic lock conflict (version mismatch) → 409
15. API: user can only access own briefs (RBAC)
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.relationship_brief import RelationshipBrief
from eventlink.models.todo import Todo
from eventlink.services.relationship_brief_service import (
    BriefGenerationResult,
    RelationshipBriefService,
)


# ── Helper Functions ──────────────────────────────────────────


def make_user_id() -> str:
    return str(uuid.uuid4())


def make_entity_id() -> str:
    return str(uuid.uuid4())


async def create_person_entity(
    db_session: AsyncSession,
    user_id: str | None = None,
    name: str = "张三",
) -> str:
    """Create a person Entity in DB and return its ID as string.

    Also creates a dummy Event for the required source_event_id FK.
    """
    # Create a dummy event first (Entity.source_event_id FK requires it)
    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id or make_user_id(),
        event_type="manual",
        source="test",
        title="dummy",
        status="completed",
    )
    db_session.add(event)
    await db_session.flush()

    eid = uuid.uuid4()
    entity = Entity(
        id=str(eid),
        user_id=user_id or make_user_id(),
        entity_type="person",
        name=name,
        canonical_name=name,
        properties={
            "basic": {"company": "XX科技", "title": "技术总监", "city": "北京"},
        },
        source_event_id=str(event.id),
    )
    db_session.add(entity)
    await db_session.flush()
    return str(eid)


def make_event(
    user_id: str | None = None,
    event_type: str = "meeting",
    title: str = "测试会议",
    raw_text: str = "与张总讨论项目合作",
) -> Event:
    """Create a test Event instance."""
    return Event(
        id=str(uuid.uuid4()),
        user_id=user_id or make_user_id(),
        event_type=event_type,
        source="test",
        title=title,
        raw_text=raw_text,
        timestamp=datetime.now(timezone.utc),
        status="completed",
    )


def make_todo(
    todo_type: str = "promise",
    title: str = "测试待办",
    status: str = "pending",
    action_type: str | None = None,
    due_date: datetime | None = None,
    related_entity_id: uuid.UUID | None = None,
) -> Todo:
    """Create a test Todo instance."""
    return Todo(
        id=str(uuid.uuid4()),
        user_id=make_user_id(),
        todo_type=todo_type,
        title=title,
        source_event_id=str(uuid.uuid4()),
        status=status,
        action_type=action_type,
        due_date=due_date,
        related_entity_id=str(related_entity_id) if related_entity_id else None,
    )


# ── Service Tests ─────────────────────────────────────────────


class TestGetOrCreateBrief:
    """Test 1-2: get_or_create_brief — new vs existing."""

    @pytest.mark.asyncio
    async def test_create_new_brief(self, db_session: AsyncSession):
        """Test 1: Create a new brief when none exists."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief, is_new = await service.get_or_create_brief(user_id, person_id)

        assert is_new is True
        assert brief is not None
        assert brief.user_id == user_id
        assert brief.person_entity_id == person_id
        assert brief.relationship_stage == "new_connection"
        assert brief.version == 1
        assert isinstance(brief.brief_data, dict)
        assert "basic_info" in brief.brief_data
        assert "strength_score" in brief.brief_data

    @pytest.mark.asyncio
    async def test_return_existing_brief(self, db_session: AsyncSession):
        """Test 2: Return existing brief instead of creating duplicate."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)

        # First call creates
        brief1, is_new1 = await service.get_or_create_brief(user_id, person_id)
        await db_session.commit()

        # Second call returns same
        brief2, is_new2 = await service.get_or_create_brief(user_id, person_id)

        assert is_new2 is False
        assert brief2.id == brief1.id
        assert brief2.version == brief1.version


class TestUpdateBriefFromEvent:
    """Test 3-5: update_brief_from_event module updates."""

    @pytest.mark.asyncio
    async def test_update_last_interaction(self, db_session: AsyncSession):
        """Test 3: last_interaction updated to latest event info."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)
        event = make_event(
            user_id=user_id,
            event_type="call",
            title="电话讨论方案",
            raw_text="和客户电话沟通需求细节",
        )

        result = await service.update_brief_from_event(
            user_id, person_id, event
        )

        assert isinstance(result, BriefGenerationResult)
        assert result.brief is not None
        assert "last_interaction" in result.modules_updated
        li = result.brief.brief_data.get("last_interaction", {})
        assert li.get("event_type") == "call"
        assert "方案" in li.get("summary", "")

    @pytest.mark.asyncio
    async def test_sync_open_promises_from_todos(self, db_session: AsyncSession):
        """Test 4: open_promises synced from pending todos."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)
        event = make_event(user_id=user_id)
        todos = [
            make_todo(
                todo_type="promise",
                title="发送报价单",
                action_type="my_promise",
                due_date=datetime.now(timezone.utc) + timedelta(days=3),
            ),
            make_todo(
                todo_type="followup",
                title="对方提供资料",
                action_type="their_promise",
            ),
            # Done todo should be excluded
            make_todo(todo_type="promise", title="已完成的事", status="done"),
        ]

        result = await service.update_brief_from_event(
            user_id, person_id, event, todos=todos
        )

        promises = result.brief.brief_data.get("open_promises", {})
        my_p = promises.get("my_promises", [])
        their_p = promises.get("their_promises", [])
        assert len(my_p) >= 1
        assert len(their_p) >= 1
        assert "open_promises" in result.modules_updated

    @pytest.mark.asyncio
    async def test_extract_their_concerns(self, db_session: AsyncSession):
        """Test 5: their_concerns extracted from care-type todos."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)
        event = make_event(user_id=user_id)
        todos = [
            make_todo(todo_type="care", title="关心对方的物流成本问题"),
            make_todo(todo_type="care", title="关注系统稳定性"),
        ]

        result = await service.update_brief_from_event(
            user_id, person_id, event, todos=todos
        )

        concerns = result.brief.brief_data.get("their_concerns", [])
        assert len(concerns) >= 2
        assert any("物流" in c for c in concerns)
        assert "their_concerns" in result.modules_updated


class TestCalculateStrengthScore:
    """Test 6-7: _calculate_strength_score scoring logic."""

    def test_high_frequency_high_score(self):
        """Test 6: High interaction frequency yields high score."""
        data = {
            "interaction_freq": {"total_count": 20, "last_30_days": 8},
            "open_promises": {
                "my_promises": [{"title": "a"}],
                "their_promises": [{"title": "b"}],
            },
            "their_concerns": ["成本", "稳定性"],
            "my_contributions": ["分享报告"],
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
        }
        score = RelationshipBriefService._calculate_strength_score(data)
        assert score > 50  # Should be well above half

    def test_no_interaction_low_score(self):
        """Test 7: No interaction data yields very low score."""
        data = {
            "interaction_freq": {"total_count": 0, "last_30_days": 0},
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
            "my_contributions": [],
            "last_interaction": {},
        }
        score = RelationshipBriefService._calculate_strength_score(data)
        assert score < 10  # Near zero


class TestGenerateNextActions:
    """Test 8: _generate_next_actions rule-based generation."""

    def test_overdue_promise_priority_reminder(self):
        """Test 8: Overdue my_promise triggers high-priority reminder."""
        past_due = datetime.now(timezone.utc) - timedelta(days=2)
        data = {
            "basic_info": {"name": "张三"},
            "relationship_stage": "value_response",
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
            "open_promises": {
                "my_promises": [
                    {"title": "发送报价单", "due_date": past_due.isoformat()},
                ],
                "their_promises": [],
            },
            "their_concerns": [],
        }

        actions = RelationshipBriefService._generate_next_actions(data)

        assert len(actions) >= 1
        assert actions[0]["priority"] == "high"
        assert "兑现承诺" in actions[0]["action"] or "报价单" in actions[0]["action"]


class TestListBriefs:
    """Test 9-10: list_briefs filtering and pagination."""

    @pytest.mark.asyncio
    async def test_filter_by_stage(self, db_session: AsyncSession):
        """Test 9: List briefs filtered by relationship_stage."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()

        # Create briefs at different stages
        pid1 = await create_person_entity(db_session, user_id=user_id, name="A")
        brief1, _ = await service.get_or_create_brief(user_id, pid1)
        brief1.relationship_stage = "understanding_needs"

        pid2 = await create_person_entity(db_session, user_id=user_id, name="B")
        brief2, _ = await service.get_or_create_brief(user_id, pid2)
        brief2.relationship_stage = "deep_trust"

        pid3 = await create_person_entity(db_session, user_id=user_id, name="C")
        brief3, _ = await service.get_or_create_brief(user_id, pid3)
        brief3.relationship_stage = "understanding_needs"

        await db_session.commit()

        # Filter by stage
        results, total = await service.list_briefs(
            user_id, stage="understanding_needs"
        )
        assert total == 2
        assert all(b.relationship_stage == "understanding_needs" for b in results)

    @pytest.mark.asyncio
    async def test_pagination_limit_offset(self, db_session: AsyncSession):
        """Test 10: Pagination with limit and offset works correctly."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()

        # Create 5 briefs
        for i in range(5):
            pid = await create_person_entity(
                db_session, user_id=user_id, name=f"Person{i}"
            )
            await service.get_or_create_brief(user_id, pid)

        await db_session.commit()

        # Page 1: limit=2, offset=0
        page1, total = await service.list_briefs(user_id, limit=2, offset=0)
        assert total == 5
        assert len(page1) == 2

        # Page 2: limit=2, offset=2
        page2, _ = await service.list_briefs(user_id, limit=2, offset=2)
        assert len(page2) == 2

        # Page 3: limit=2, offset=4
        page3, _ = await service.list_briefs(user_id, limit=2, offset=4)
        assert len(page3) == 1


# ── API Tests (using dependency overrides) ────────────────────


TEST_USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def api_client(db_session: AsyncSession):
    """Create an httpx AsyncClient with DB dependency overridden."""
    from httpx import ASGITransport, AsyncClient
    from eventlink.database import get_async_session
    from eventlink.core.auth import get_current_user_id
    from eventlink.main import app

    app.dependency_overrides[get_async_session] = lambda: db_session  # type: ignore[return-value]
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client

    app.dependency_overrides.clear()


class TestAPIGetRelationshipBrief:
    """Test 11-12: GET /persons/{id}/relationship-brief."""

    @pytest.mark.asyncio
    async def test_get_brief_success(self, api_client, db_session: AsyncSession):
        """Test 11: GET brief returns 200 with correct data."""
        user_id = TEST_USER_ID

        # Create dummy event for Entity FK
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="manual",
            source="test",
            title="dummy",
            status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="李四",
            canonical_name="李四",
            source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="understanding_needs",
            brief_data={"strength_score": 42, "notes": "test"},
            version=2,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["person_entity_id"] == str(person_entity.id)
        assert data["relationship_stage"] == "understanding_needs"
        assert data["version"] == 2

    @pytest.mark.asyncio
    async def test_get_brief_not_found_404(self, api_client):
        """Test 12: GET non-existent brief returns 404."""
        fake_id = str(uuid.uuid4())
        response = await api_client.get(
            f"/api/v1/persons/{fake_id}/relationship-brief"
        )

        assert response.status_code == 404


class TestAPIPatchRelationshipBrief:
    """Test 13-14: PATCH /relationship-briefs/{id} optimistic locking."""

    @pytest.mark.asyncio
    async def test_patch_optimistic_lock_success(
        self, api_client, db_session: AsyncSession
    ):
        """Test 13: PATCH with matching version succeeds."""
        user_id = TEST_USER_ID
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=person_id,
            relationship_stage="new_connection",
            brief_data={"notes": "", "strength_score": 10},
            version=3,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.patch(
            f"/api/v1/relationship-briefs/{brief.id}",
            json={
                "notes": "更新后的备注",
                "expected_version": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 4  # Version incremented
        assert data["brief_data"]["notes"] == "更新后的备注"

    @pytest.mark.asyncio
    async def test_patch_optimistic_lock_conflict_409(
        self, api_client, db_session: AsyncSession
    ):
        """Test 14: PATCH with wrong version returns 409 Conflict."""
        user_id = TEST_USER_ID
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=person_id,
            relationship_stage="new_connection",
            brief_data={},
            version=5,
        )
        db_session.add(brief)
        await db_session.commit()

        # Send expected_version=99 but actual is 5
        response = await api_client.patch(
            f"/api/v1/relationship-briefs/{brief.id}",
            json={
                "notes": "应该失败",
                "expected_version": 99,
            },
        )

        assert response.status_code == 409
        assert "Optimistic lock" in response.json()["detail"]


class TestAPIRBAC:
    """Test 15: RBAC — users can only access their own briefs."""

    @pytest.mark.asyncio
    async def test_user_cannot_access_others_brief(
        self, api_client, db_session: AsyncSession
    ):
        """Test 15: User A cannot access User B's brief (returns 404)."""
        owner_id = TEST_USER_ID
        person_id = await create_person_entity(db_session, user_id=owner_id)

        brief = RelationshipBrief(
            user_id=owner_id,
            person_entity_id=person_id,
            relationship_stage="new_connection",
            brief_data={},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        # Switch auth to a different user
        from eventlink.main import app as main_app
        from eventlink.core.auth import get_current_user_id

        other_user_id = "99999999-9999-9999-9999-999999999999"
        main_app.dependency_overrides[get_current_user_id] = lambda: other_user_id

        try:
            response = await api_client.patch(
                f"/api/v1/relationship-briefs/{brief.id}",
                json={
                    "notes": "恶意修改",
                    "expected_version": 1,
                },
            )

            assert response.status_code == 404
            # Global 404 handler returns {"error": {"message": "Resource not found"}}
            resp_data = response.json()
            assert "not found" in str(resp_data).lower() or "access denied" in str(resp_data).lower()
        finally:
            main_app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID


# ── Additional Edge Case Tests ────────────────────────────────


class TestGetBriefNotFound:
    """Edge case: get_brief raises ValueError when not found."""

    @pytest.mark.asyncio
    async def test_get_brief_raises_when_missing(self, db_session: AsyncSession):
        """get_brief should raise ValueError for non-existent pair."""
        service = RelationshipBriefService(db_session)

        with pytest.raises(ValueError, match="not found"):
            await service.get_brief(make_user_id(), make_entity_id())


class TestUpdateBriefPartialOptimisticLock:
    """Test update_brief_partial optimistic lock in service layer."""

    @pytest.mark.asyncio
    async def test_update_partial_version_mismatch_raises(self, db_session: AsyncSession):
        """update_brief_partial raises on version mismatch."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief, _ = await service.get_or_create_brief(user_id, person_id)
        current_version = brief.version

        with pytest.raises(ValueError, match="Optimistic lock"):
            await service.update_brief_partial(
                brief_id=str(brief.id),
                notes="test",
                expected_version=current_version + 999,
            )


class TestGenerateNextActionsMultipleRules:
    """Test next_actions generation with multiple active rules."""

    def test_stale_interaction_triggers_contact_action(self):
        """Last interaction > 7 days ago should suggest contacting."""
        old_date = datetime.now(timezone.utc) - timedelta(days=14)
        data = {
            "basic_info": {"name": "王五"},
            "relationship_stage": "value_response",
            "last_interaction": {"date": old_date.isoformat()},
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
        }

        actions = RelationshipBriefService._generate_next_actions(data)

        action_texts = [a["action"] for a in actions]
        assert any("主动联系" in t for t in action_texts)

    def test_understanding_needs_stage_action(self):
        """Stage understanding_needs should trigger '深入了解需求' action."""
        data = {
            "basic_info": {"name": "赵六"},
            "relationship_stage": "understanding_needs",
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
        }

        actions = RelationshipBriefService._generate_next_actions(data)

        action_texts = [a["action"] for a in actions]
        assert any("深入了解" in t for t in action_texts)

    def test_max_five_actions(self):
        """Should never return more than 5 actions (3 standard + 2 association-based)."""
        past_due = datetime.now(timezone.utc) - timedelta(days=2)
        stale_date = datetime.now(timezone.utc) - timedelta(days=14)
        data = {
            "basic_info": {"name": "钱七"},
            "relationship_stage": "understanding_needs",
            "last_interaction": {"date": stale_date.isoformat()},
            "open_promises": {
                "my_promises": [
                    {"title": "逾期任务A", "due_date": past_due.isoformat()},
                    {"title": "逾期任务B", "due_date": past_due.isoformat()},
                    {"title": "逾期任务C", "due_date": past_due.isoformat()},
                ],
                "their_promises": [],
            },
            "their_concerns": ["重要话题1", "重要话题2", "重要话题3"],
        }

        actions = RelationshipBriefService._generate_next_actions(data)

        assert len(actions) <= 5


class TestSyncOpenPromisesExcludesDone:
    """Verify done/dismissed todos are excluded from open promises."""

    def test_done_todos_excluded_from_promises(self):
        """Todos with status=done should not appear in open_promises."""
        todos = [
            make_todo(title="待完成", status="pending"),
            make_todo(title="已做完", status="done"),
            make_todo(title="已忽略", status="dismissed"),
        ]

        promises = RelationshipBriefService._sync_open_promises(todos)

        titles = [p["title"] for p in promises["my_promises"]]
        assert "待完成" in titles
        assert "已做完" not in titles
        assert "已忽略" not in titles


# ── Aggregated View API Tests ──────────────────────────────────


class TestAPIAggregatedBrief:
    """Tests for GET /persons/{id}/relationship-brief/aggregated."""

    @pytest.mark.asyncio
    async def test_aggregated_returns_12_modules(
        self, api_client, db_session: AsyncSession
    ):
        """Aggregated endpoint returns 12 structured modules."""
        user_id = TEST_USER_ID

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="manual",
            source="test",
            title="dummy",
            status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="王五",
            canonical_name="王五",
            properties={"basic": {"company": "YY公司"}},
            source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="understanding_needs",
            brief_data={
                "strength_score": 55,
                "basic_info": {"name": "王五"},
                "open_promises": {
                    "my_promises": [{"title": "发送方案"}],
                    "their_promises": [],
                },
                "their_concerns": ["成本问题"],
                "next_actions": [
                    {"action": "深入了解需求", "priority": "high"},
                    {"action": "发送报价单", "priority": "medium"},
                ],
                "interaction_freq": {"total_count": 5, "last_30_days": 2},
                "notes": "重要客户",
            },
            version=3,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )

        assert response.status_code == 200
        data = response.json()

        # Must have exactly 12 modules
        modules = data["modules"]
        assert len(modules) == 12

        module_names = [m["module_name"] for m in modules]
        for key in [
            "basic_info", "relationship_stage", "last_interaction",
            "interaction_freq", "open_promises", "their_concerns",
            "my_contributions", "cooperation_signals", "risk_flags",
            "next_actions", "strength_score", "notes",
        ]:
            assert key in module_names, f"Missing module: {key}"

    @pytest.mark.asyncio
    async def test_aggregated_resolves_person_name_and_company(
        self, api_client, db_session: AsyncSession
    ):
        """person_name and person_company resolved from entity."""
        user_id = TEST_USER_ID

        event = Event(
            id=str(uuid.uuid4()), user_id=user_id, event_type="manual",
            source="test", title="dummy", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="赵六",
            canonical_name="赵六",
            properties={"company": "ZZ集团"},
            source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="new_connection",
            brief_data={},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["person_name"] == "赵六"
        assert data["person_company"] == "ZZ集团"

    @pytest.mark.asyncio
    async def test_aggregated_strength_score_mapping(
        self, api_client, db_session: AsyncSession
    ):
        """Strength score correctly maps to label."""
        user_id = TEST_USER_ID

        event = Event(
            id=str(uuid.uuid4()), user_id=user_id, event_type="manual",
            source="test", title="dummy", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id, entity_type="person", name="测试人",
            canonical_name="测试人", source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        # Score >= 80 → 关系稳固
        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="deep_trust",
            brief_data={"strength_score": 85},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["strength_label"] == "关系稳固"

        # Update to low score → 刚建立联系
        from sqlalchemy.orm.attributes import flag_modified
        brief.brief_data["strength_score"] = 5
        flag_modified(brief, "brief_data")
        await db_session.commit()
        await db_session.refresh(brief)

        response2 = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["strength_label"] == "刚建立联系"

    @pytest.mark.asyncio
    async def test_aggregated_open_promises_high_priority(
        self, api_client, db_session: AsyncSession
    ):
        """When open_promises has data, its priority is 'high'."""
        user_id = TEST_USER_ID

        event = Event(
            id=str(uuid.uuid4()), user_id=user_id, event_type="manual",
            source="test", title="dummy", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id, entity_type="person", name="钱七",
            canonical_name="钱七", source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="value_response",
            brief_data={
                "open_promises": {
                    "my_promises": [{"title": "发送合同"}],
                    "their_promises": [],
                },
            },
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )
        assert response.status_code == 200
        data = response.json()
        op_module = next(m for m in data["modules"] if m["module_name"] == "open_promises")
        assert op_module["priority"] == "high"
        assert op_module["has_data"] is True

    @pytest.mark.asyncio
    async def test_aggregated_empty_module_has_data_false(
        self, api_client, db_session: AsyncSession
    ):
        """Modules with no meaningful data have has_data=False."""
        user_id = TEST_USER_ID

        event = Event(
            id=str(uuid.uuid4()), user_id=user_id, event_type="manual",
            source="test", title="dummy", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        person_entity = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id, entity_type="person", name="孙八",
            canonical_name="孙八", source_event_id=str(event.id),
        )
        db_session.add(person_entity)
        await db_session.flush()

        # Minimal brief with almost empty data
        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=str(person_entity.id),
            relationship_stage="new_connection",
            brief_data={
                "open_promises": {"my_promises": [], "their_promises": []},
                "their_concerns": [],
                "my_contributions": [],
                "risk_flags": [],
                "next_actions": [],
                "interaction_freq": {},
                "last_interaction": {},
            },
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await api_client.get(
            f"/api/v1/persons/{person_entity.id}/relationship-brief/aggregated"
        )
        assert response.status_code == 200
        data = response.json()

        # Check empty modules have has_data=False
        for module in data["modules"]:
            key = module["module_name"]
            if key in ("open_promises", "their_concerns", "risk_flags"):
                assert module["has_data"] is False, (
                    f"{key} should have has_data=False when empty"
                )
                assert module["summary"] == "暂无数据"

    @pytest.mark.asyncio
    async def test_aggregated_not_found_404(self, api_client):
        """GET aggregated returns 404 when brief does not exist."""
        fake_id = str(uuid.uuid4())
        response = await api_client.get(
            f"/api/v1/persons/{fake_id}/relationship-brief/aggregated"
        )
        assert response.status_code == 404


# ── Additional Coverage Tests ──────────────────────────────────


class TestGetAssociationsForEntity:
    """Test _get_associations_for_entity hot and cold discovery."""

    @pytest.mark.asyncio
    async def test_get_associations_for_entity_hot(self, db_session: AsyncSession):
        """Test hot association query returns correct associations."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()

        # Create event + entities
        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="manual",
            source="test",
            title="dummy",
            status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity_a = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="实体A",
            canonical_name="实体A",
            source_event_id=str(event.id),
        )
        entity_b = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="实体B",
            canonical_name="实体B",
            source_event_id=str(event.id),
        )
        db_session.add_all([entity_a, entity_b])
        await db_session.flush()

        from eventlink.models.association import Association

        assoc = Association(
            id=str(uuid.uuid4()),
            user_id=user_id,
            source_entity_id=str(entity_a.id),
            target_entity_id=str(entity_b.id),
            source_event_id=str(event.id),
            association_type="industry_chain",
            strength=0.8,
            confidence=0.9,
            properties={"evidence": {"relation": "potential_investor_startup"}},
        )
        db_session.add(assoc)
        await db_session.commit()

        entries = await service._get_associations_for_entity(str(entity_a.id))

        assert len(entries) >= 1
        hot_entry = next(
            (e for e in entries if e["association_type"] == "industry_chain"), None
        )
        assert hot_entry is not None
        assert hot_entry["other_entity_name"] == "实体B"
        assert hot_entry["evidence"]["relation"] == "potential_investor_startup"

    @pytest.mark.asyncio
    async def test_get_associations_for_entity_cold_discovery(
        self, db_session: AsyncSession
    ):
        """Test cold association discovery is triggered."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()

        event = Event(
            id=str(uuid.uuid4()),
            user_id=user_id,
            event_type="manual",
            source="test",
            title="dummy",
            status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity_a = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="冷发现A",
            canonical_name="冷发现A",
            properties={"basic": {"city": "北京", "company": "XX公司"}},
            source_event_id=str(event.id),
        )
        entity_b = Entity(
            id=str(uuid.uuid4()),
            user_id=user_id,
            entity_type="person",
            name="冷发现B",
            canonical_name="冷发现B",
            properties={"basic": {"city": "北京", "company": "YY公司"}},
            source_event_id=str(event.id),
        )
        db_session.add_all([entity_a, entity_b])
        await db_session.commit()

        # Cold discovery may or may not produce results depending on
        # AssociationDiscoveryEngine, but the method should not raise
        entries = await service._get_associations_for_entity(str(entity_a.id))

        # At minimum, it should return a list (possibly empty if no hot assocs)
        assert isinstance(entries, list)


class TestUpdateBriefPartial:
    """Test update_brief_partial with notes and recalculation."""

    @pytest.mark.asyncio
    async def test_update_brief_partial_notes(self, db_session: AsyncSession):
        """Test partial update with notes field."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief, _ = await service.get_or_create_brief(user_id, person_id)
        await db_session.commit()

        version_before = brief.version
        updated = await service.update_brief_partial(
            brief_id=str(brief.id),
            notes="重要客户，需重点维护",
        )

        assert updated.brief_data.get("notes") == "重要客户，需重点维护"
        assert updated.version == version_before + 1

    @pytest.mark.asyncio
    async def test_update_brief_partial_recalculate(self, db_session: AsyncSession):
        """Test partial update recalculates strength_score and next_actions."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(db_session, user_id=user_id)

        brief, _ = await service.get_or_create_brief(user_id, person_id)
        await db_session.commit()

        updated = await service.update_brief_partial(
            brief_id=str(brief.id),
            brief_data_partial={
                "interaction_freq": {"total_count": 10, "last_30_days": 5},
                "their_concerns": ["成本问题"],
            },
        )

        # strength_score should be recalculated
        assert updated.brief_data.get("strength_score", 0) > 0
        # next_actions should be regenerated
        assert isinstance(updated.brief_data.get("next_actions"), list)


class TestExtractMyContributions:
    """Test _extract_my_contributions with help type todo."""

    def test_extract_my_contributions_help_todo(self):
        """Test _extract_my_contributions with help type todo."""
        todos = [
            make_todo(todo_type="help", title="帮助对方搭建技术架构"),
            make_todo(todo_type="care", title="关心对方项目进展"),
            make_todo(todo_type="help", title="提供市场分析报告"),
        ]

        contributions = RelationshipBriefService._extract_my_contributions(todos)

        assert len(contributions) == 2
        assert any("技术架构" in c for c in contributions)
        assert any("市场分析" in c for c in contributions)


class TestExtractCooperationSignals:
    """Test _extract_cooperation_signals extraction."""

    def test_extract_cooperation_signals(self):
        """Test _extract_cooperation_signals extraction."""
        todos = [
            make_todo(
                todo_type="cooperation_signal",
                title="引荐张三和李四（投资-创业链）",
            ),
            make_todo(todo_type="followup", title="跟进项目"),
        ]

        signals = RelationshipBriefService._extract_cooperation_signals(todos)

        assert len(signals) == 1
        assert "引荐" in signals[0]


class TestExtractRiskFlags:
    """Test _extract_risk_flags extraction."""

    def test_extract_risk_flags(self):
        """Test _extract_risk_flags extraction."""
        todos = [
            make_todo(todo_type="risk", title="对方公司经营异常"),
            make_todo(todo_type="care", title="关心对方状态"),
        ]

        flags = RelationshipBriefService._extract_risk_flags(todos)

        assert len(flags) == 1
        assert "经营异常" in flags[0]


class TestNextActionsAssociationBased:
    """Test association-based next actions generation."""

    def test_next_actions_association_based_industry_chain(self):
        """Test association-based next actions for industry_chain."""
        data = {
            "basic_info": {"name": "张三"},
            "relationship_stage": "value_response",
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
        }
        associations = [
            {
                "association_type": "industry_chain",
                "other_entity_name": "李四",
                "evidence": {"relation": "potential_investor_startup"},
                "confidence": 0.9,
            }
        ]

        actions = RelationshipBriefService._generate_next_actions(data, associations)

        action_texts = [a["action"] for a in actions]
        assert any("引荐" in t and "投资-创业链" in t for t in action_texts)

    def test_next_actions_association_based_supply_demand(self):
        """Test association-based next actions for supply_demand."""
        data = {
            "basic_info": {"name": "供应商A"},
            "relationship_stage": "value_response",
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
        }
        associations = [
            {
                "association_type": "supply_demand",
                "other_entity_name": "需求方B",
                "evidence": {
                    "matches": [
                        {
                            "supplier": "供应商A",
                            "requester": "需求方B",
                            "matched_items": ["GPU服务器"],
                        }
                    ]
                },
                "confidence": 0.8,
            }
        ]

        actions = RelationshipBriefService._generate_next_actions(data, associations)

        action_texts = [a["action"] for a in actions]
        assert any("可帮助" in t for t in action_texts)

    def test_next_actions_default_fallback(self):
        """Test default '保持定期联系' fallback action."""
        data = {
            "basic_info": {"name": "测试人"},
            "relationship_stage": "new_connection",
            "last_interaction": {
                "date": datetime.now(timezone.utc).isoformat(),
            },
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
        }

        actions = RelationshipBriefService._generate_next_actions(data, None)

        # No overdue promises, no stale interaction, no special stage
        # → should get default fallback
        action_texts = [a["action"] for a in actions]
        assert any("保持定期联系" in t for t in action_texts)


class TestBasicInfoFallbackDBQuery:
    """Test basic_info fallback when entity not in entities param."""

    @pytest.mark.asyncio
    async def test_basic_info_fallback_db_query(self, db_session: AsyncSession):
        """Test basic_info fallback when entity not in entities param."""
        service = RelationshipBriefService(db_session)
        user_id = make_user_id()
        person_id = await create_person_entity(
            db_session, user_id=user_id, name="数据库回退人"
        )

        event = make_event(user_id=user_id)
        # Pass empty entities list — should trigger DB fallback
        result = await service.update_brief_from_event(
            user_id, person_id, event, entities=[]
        )

        basic_info = result.brief.brief_data.get("basic_info", {})
        assert basic_info.get("name") == "数据库回退人"
        assert "basic_info" in result.modules_updated

"""User Journey (E2E) tests for PromiseLink.

Simulates real user workflows as defined in the PRD:

  Journey 1: "记录一次重要交流" (First Experience)
    User logs in → creates event → pipeline processes → views dashboard →
    checks todos → checks entities

  Journey 2: "查看今日待办" (Daily Review)
    User logs in → views morning brief → sees todos by priority →
    marks todo done → views day-view

  Journey 3: "关系追踪" (Relationship Tracking)
    User creates event about Person A → creates another event about Person A →
    system discovers association → user views relationship brief

Uses httpx.AsyncClient + FastAPI dependency injection against in-memory SQLite,
with LLM calls mocked out. No external services required.
"""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.services.relationship_brief_service import RelationshipBriefService

# ── Constants ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"


# ── Fixtures ──


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite async engine for testing."""
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
    """Provide an async DB session for direct data setup."""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session, mock_pipeline):
    """Provide an httpx.AsyncClient with DB dependency overridden and LLM mocked."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Helpers ──


async def insert_event(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "event_type": "meeting",
        "source": "manual",
        "title": "Test Event",
        "raw_text": "Test raw text",
        "status": "completed",
    }
    data.update(overrides)
    event = Event(**data)
    session.add(event)
    await session.flush()
    return event


async def insert_entity(session: AsyncSession, **overrides) -> Entity:
    """Insert an Entity directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "entity_type": "person",
        "name": "Test Person",
        "canonical_name": "Test Person",
        "aliases": [],
        "properties": {"basic": {"company": "Test Corp", "title": "Engineer"}},
        "source_event_id": str(source_event_id),
        "confidence": 0.9,
        "status": "confirmed",
    }
    data.update(overrides)
    entity = Entity(**data)
    session.add(entity)
    await session.flush()
    return entity


async def insert_todo(session: AsyncSession, **overrides) -> Todo:
    """Insert a Todo directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "todo_type": "promise",
        "title": "Follow up",
        "description": "Send a message",
        "priority": 2,
        "status": "pending",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


async def insert_association(session: AsyncSession, **overrides) -> Association:
    """Insert an Association directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    source_entity_id = overrides.pop("source_entity_id", None)
    target_entity_id = overrides.pop("target_entity_id", None)

    if source_event_id is None:
        event = await insert_event(session)
        source_event_id = event.id
    if source_entity_id is None:
        entity = await insert_entity(session, source_event_id=source_event_id, name="Source Entity")
        source_entity_id = entity.id
    if target_entity_id is None:
        entity2 = await insert_entity(session, source_event_id=source_event_id, name="Target Entity")
        target_entity_id = entity2.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "source_entity_id": str(source_entity_id),
        "target_entity_id": str(target_entity_id),
        "association_type": "same_city",
        "strength": 0.7,
        "confidence": 0.8,
        "status": "confirmed",
        "source_event_id": str(source_event_id),
    }
    data.update(overrides)
    assoc = Association(**data)
    session.add(assoc)
    await session.flush()
    return assoc


async def simulate_pipeline_output(
    session: AsyncSession,
    raw_text: str,
    event_title: str,
    person_name: str,
    person_company: str = "",
    person_title: str = "",
    concerns: list[dict] | None = None,
    todo_title: str = "",
    todo_type: str = "promise",
) -> dict:
    """Simulate what the pipeline would produce for a given event.

    Creates event, entity, todo, and updates the relationship brief.
    Returns a dict with all created object IDs.
    """
    # 1. Create event
    event = await insert_event(
        session,
        title=event_title,
        raw_text=raw_text,
        status="completed",
    )

    # 2. Create entity
    entity_props = {
        "basic": {"company": person_company, "title": person_title},
    }
    if concerns:
        entity_props["concern"] = concerns

    entity = await insert_entity(
        session,
        name=person_name,
        canonical_name=person_name,
        source_event_id=event.id,
        properties=entity_props,
    )

    # 3. Create todo
    todo = None
    if todo_title:
        todo = await insert_todo(
            session,
            title=todo_title,
            todo_type=todo_type,
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
        )

    # 4. Update relationship brief
    service = RelationshipBriefService(session)
    result = await service.update_brief_from_event(
        user_id=TEST_USER_ID,
        person_entity_id=str(entity.id),
        event=event,
        entities=[entity],
        todos=[todo] if todo else [],
    )
    await session.commit()

    return {
        "event_id": str(event.id),
        "entity_id": str(entity.id),
        "todo_id": str(todo.id) if todo else None,
        "brief_id": str(result.brief.id) if result.brief else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Journey 1: "记录一次重要交流" (First Experience)
# ══════════════════════════════════════════════════════════════════════════════


class TestJourney1RecordInteraction:
    """Core first experience: Record an interaction → AI processes → view results.

    This is the primary user journey defined in the PRD:
    1. User logs in
    2. User creates event: "今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案"
    3. System processes the event through the pipeline
    4. User views dashboard — sees the new event
    5. User checks todos — sees "给张总发AI方案" (promise todo)
    6. User checks entities — sees "张总" with concern about AI in manufacturing
    """

    @pytest.mark.asyncio
    async def test_step1_user_creates_event_via_api(self, client: AsyncClient):
        """Step 1: User creates an event via the API."""
        payload = {
            "event_type": "meeting",
            "source": "manual",
            "title": "和张总见面",
            "raw_text": "今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
        }
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "和张总见面"
        assert data["status"] == "pending"
        assert data["pipeline_status"] == "pending"

    @pytest.mark.asyncio
    async def test_step2_pipeline_processes_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 2: After pipeline processing, entities and todos are created."""
        # Simulate pipeline output
        ids = await simulate_pipeline_output(
            session=db_session,
            raw_text="今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
            event_title="和张总见面",
            person_name="张总",
            person_company="某制造集团",
            person_title="总经理",
            concerns=[{"category": "AI应用", "detail": "AI在制造业的应用"}],
            todo_title="给张总发AI方案",
            todo_type="promise",
        )

        # Verify entity was created with concern
        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        entities = resp.json()["items"]
        zhang_entities = [e for e in entities if e["name"] == "张总"]
        assert len(zhang_entities) >= 1

        # Verify todo was created
        resp = await client.get(f"{API_PREFIX}/todos")
        assert resp.status_code == 200
        todos = resp.json()["items"]
        ai_todos = [t for t in todos if "AI方案" in t["title"]]
        assert len(ai_todos) >= 1
        assert ai_todos[0]["todo_type"] == "promise"

    @pytest.mark.asyncio
    async def test_step3_user_views_dashboard_with_new_event(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 3: User views dashboard and sees the new event."""
        # Create event for today (use UTC+8 local date to match dashboard query)
        _CST = timezone(timedelta(hours=8))
        now_local = datetime.now(_CST)
        today_local = now_local.date()
        # Store as naive UTC (matching how the DB stores timestamps)
        event_ts = now_local.astimezone(UTC).replace(tzinfo=None)
        event = await insert_event(
            db_session,
            title="和张总见面",
            timestamp=event_ts,
            status="completed",
        )
        await db_session.commit()

        # View dashboard for today
        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = today_local
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            resp = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": "今天"}
            )

        assert resp.status_code == 200
        data = resp.json()
        event_titles = [e["title"] for e in data["events"]]
        assert "和张总见面" in event_titles

    @pytest.mark.asyncio
    async def test_step4_user_checks_todos_for_promise(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 4: User checks todos and sees the promise todo."""
        event = await insert_event(db_session, title="和张总见面")
        entity = await insert_entity(
            db_session, name="张总", source_event_id=event.id
        )
        await insert_todo(
            db_session,
            title="给张总发AI方案",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=1,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"todo_type": "promise"})
        assert resp.status_code == 200
        todos = resp.json()["items"]
        promise_todos = [t for t in todos if t["todo_type"] == "promise"]
        assert len(promise_todos) >= 1
        assert any("AI方案" in t["title"] for t in promise_todos)

    @pytest.mark.asyncio
    async def test_step5_user_checks_entities_for_concern(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 5: User checks entities and sees 张总 with concern about AI."""
        event = await insert_event(db_session)
        await insert_entity(
            db_session,
            name="张总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某制造集团", "title": "总经理"},
                "concern": [{"category": "AI应用", "detail": "AI在制造业的应用"}],
            },
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/entities", params={"search": "张总"})
        assert resp.status_code == 200
        entities = resp.json()["items"]
        assert len(entities) >= 1
        assert entities[0]["name"] == "张总"
        # Verify concern data is in properties
        concerns = (entities[0].get("properties") or {}).get("concern", [])
        assert len(concerns) >= 1
        assert concerns[0]["category"] == "AI应用"

    @pytest.mark.asyncio
    async def test_full_journey_end_to_end(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Complete Journey 1: Create event → pipeline → dashboard → todos → entities."""
        # Step 1: Create event
        payload = {
            "event_type": "meeting",
            "source": "manual",
            "title": "和张总见面",
            "raw_text": "今天和张总见面，他关心AI在制造业的应用，我答应下周发他一份方案",
        }
        resp = await client.post(f"{API_PREFIX}/events", json=payload)
        assert resp.status_code == 201

        # Step 2: Simulate pipeline processing
        ids = await simulate_pipeline_output(
            session=db_session,
            raw_text=payload["raw_text"],
            event_title="和张总见面",
            person_name="张总",
            person_company="某制造集团",
            person_title="总经理",
            concerns=[{"category": "AI应用", "detail": "AI在制造业的应用"}],
            todo_title="给张总发AI方案",
            todo_type="promise",
        )

        # Step 3: Check entities
        resp = await client.get(f"{API_PREFIX}/entities", params={"search": "张总"})
        assert resp.status_code == 200
        entities = resp.json()["items"]
        assert any(e["name"] == "张总" for e in entities)

        # Step 4: Check todos
        resp = await client.get(f"{API_PREFIX}/todos", params={"todo_type": "promise"})
        assert resp.status_code == 200
        todos = resp.json()["items"]
        assert any("AI方案" in t["title"] for t in todos)

        # Step 5: Check relationship brief exists
        entity_id = ids["entity_id"]
        resp = await client.get(
            f"{API_PREFIX}/persons/{entity_id}/relationship-brief"
        )
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["relationship_stage"] == "new_connection"
        assert brief["brief_data"]["basic_info"]["name"] == "张总"


# ══════════════════════════════════════════════════════════════════════════════
# Journey 2: "查看今日待办" (Daily Review)
# ══════════════════════════════════════════════════════════════════════════════


class TestJourney2DailyReview:
    """Daily review workflow:
    1. User logs in
    2. User views morning brief
    3. User sees today's todos sorted by priority
    4. User marks a todo as done
    5. User views day-view to see today's events
    """

    @pytest.mark.asyncio
    async def test_step1_morning_brief_shows_pending_todos(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 1-2: Morning brief shows pending promises and cares."""
        event = await insert_event(db_session, title="日常互动")
        entity = await insert_entity(
            db_session, name="李总", source_event_id=event.id
        )
        await insert_todo(
            db_session,
            title="给李总发资料",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=1,
        )
        await insert_todo(
            db_session,
            title="关注李总融资需求",
            todo_type="care",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=2,
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        data = resp.json()

        assert data["pending_promises"] >= 1
        assert data["pending_cares"] >= 1
        assert "李总" in data["key_persons"]
        assert len(data["summary_text"]) > 0

    @pytest.mark.asyncio
    async def test_step2_todos_sorted_by_urgency(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 3: Todos are sorted by priority (urgency)."""
        event = await insert_event(db_session)

        # Create todos with different priorities
        await insert_todo(
            db_session, title="低优先级", priority=5, source_event_id=event.id
        )
        await insert_todo(
            db_session, title="高优先级", priority=1, source_event_id=event.id
        )
        await insert_todo(
            db_session, title="中优先级", priority=3, source_event_id=event.id
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/todos", params={"sort_by": "urgency"})
        assert resp.status_code == 200
        todos = resp.json()["items"]
        priorities = [t["priority"] for t in todos]
        assert priorities == sorted(priorities)

    @pytest.mark.asyncio
    async def test_step3_mark_todo_as_done(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 4: User marks a todo as done via PATCH."""
        event = await insert_event(db_session)
        todo = await insert_todo(
            db_session,
            title="待完成事项",
            status="pending",
            source_event_id=event.id,
        )
        await db_session.commit()

        # Mark as done
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "done"

    @pytest.mark.asyncio
    async def test_step4_day_view_shows_todays_events(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 5: Day-view shows today's events."""
        today_ts = datetime.now(UTC).replace(hour=10, minute=0, second=0, microsecond=0)
        event = await insert_event(
            db_session,
            title="今天的会议",
            timestamp=today_ts,
            event_type="meeting",
            status="completed",
        )
        await db_session.commit()

        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = today_ts.date()
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            resp = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": "今天"}
            )

        assert resp.status_code == 200
        data = resp.json()
        event_titles = [e["title"] for e in data["events"]]
        assert "今天的会议" in event_titles

    @pytest.mark.asyncio
    async def test_full_daily_review_journey(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Complete Journey 2: Morning brief → todos → mark done → day-view."""
        # Setup: Create events and todos for today
        today_ts = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
        event = await insert_event(
            db_session, title="晨会", timestamp=today_ts, event_type="meeting", status="completed"
        )
        entity = await insert_entity(
            db_session, name="王总", source_event_id=event.id
        )
        todo = await insert_todo(
            db_session,
            title="给王总发报告",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            priority=1,
        )
        await db_session.commit()

        # Step 1: Morning brief
        resp = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["pending_promises"] >= 1

        # Step 2: List todos sorted by urgency
        resp = await client.get(f"{API_PREFIX}/todos", params={"sort_by": "urgency"})
        assert resp.status_code == 200
        todos = resp.json()["items"]
        assert any(t["title"] == "给王总发报告" for t in todos)

        # Step 3: Mark todo as done
        resp = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "done"

        # Step 4: Day-view
        with patch("promiselink.core.natural_date.date") as mock_date:
            mock_date.today.return_value = today_ts.date()
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)

            resp = await client.get(
                f"{API_PREFIX}/dashboard/day-view", params={"date": "今天"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert any(e["title"] == "晨会" for e in data["events"])


# ══════════════════════════════════════════════════════════════════════════════
# Journey 3: "关系追踪" (Relationship Tracking)
# ══════════════════════════════════════════════════════════════════════════════


class TestJourney3RelationshipTracking:
    """Relationship tracking workflow:
    1. User creates event about meeting Person A
    2. User creates another event about meeting Person A again
    3. System discovers association between the two events
    4. User views relationship brief for Person A
    5. Brief shows relationship evolution
    """

    @pytest.mark.asyncio
    async def test_step1_first_interaction_creates_entity(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 1: First event about Person A creates entity and brief."""
        ids = await simulate_pipeline_output(
            session=db_session,
            raw_text="今天和李总喝茶，聊了AI合作的可能性",
            event_title="和李总喝茶",
            person_name="李总",
            person_company="盛恒资本",
            person_title="合伙人",
            concerns=[{"category": "AI合作", "detail": "AI合作的可能性"}],
            todo_title="跟进李总AI合作意向",
            todo_type="care",
        )

        # Verify entity exists
        resp = await client.get(f"{API_PREFIX}/entities", params={"search": "李总"})
        assert resp.status_code == 200
        entities = resp.json()["items"]
        assert any(e["name"] == "李总" for e in entities)

        # Verify brief exists
        entity_id = ids["entity_id"]
        resp = await client.get(
            f"{API_PREFIX}/persons/{entity_id}/relationship-brief"
        )
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["relationship_stage"] == "new_connection"

    @pytest.mark.asyncio
    async def test_step2_second_interaction_updates_brief(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 2: Second event about the same person updates the brief."""
        # First interaction
        ids1 = await simulate_pipeline_output(
            session=db_session,
            raw_text="今天和李总喝茶，聊了AI合作的可能性",
            event_title="和李总喝茶",
            person_name="李总",
            person_company="盛恒资本",
            person_title="合伙人",
            todo_title="跟进李总AI合作意向",
            todo_type="care",
        )
        entity_id = ids1["entity_id"]

        # Second interaction — update the same entity's brief
        event2 = await insert_event(
            db_session,
            title="和李总深度交流",
            raw_text="和李总深入讨论了投资方案，他答应下周安排面谈",
            status="completed",
        )
        todo2 = await insert_todo(
            db_session,
            title="准备投资方案给李总",
            todo_type="promise",
            source_event_id=event2.id,
            related_entity_id=entity_id,
            status="pending",
        )
        await db_session.commit()

        # Update the brief with second event
        entity_result = await db_session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = entity_result.scalar_one()

        service = RelationshipBriefService(db_session)
        result = await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=entity_id,
            event=event2,
            entities=[entity],
            todos=[todo2],
        )
        await db_session.commit()

        # Verify brief was updated (version incremented)
        resp = await client.get(
            f"{API_PREFIX}/persons/{entity_id}/relationship-brief"
        )
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["version"] >= 2  # Updated at least once
        # Last interaction should reflect the second event
        assert brief["brief_data"]["last_interaction"]["summary"] == "和李总深度交流"

    @pytest.mark.asyncio
    async def test_step3_association_discovered(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 3: Association is discovered between entities from different events."""
        # Create two entities with overlapping interests
        event = await insert_event(db_session, raw_text="AI赛道讨论")

        entity_a = await insert_entity(
            db_session,
            name="李总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "盛恒资本", "industry": "投资"},
                "concern": [{"category": "市场拓展", "detail": "找好项目"}],
                "capability": [{"category": "投资决策", "detail": "专注AI"}],
            },
        )

        entity_b = await insert_entity(
            db_session,
            name="张总",
            source_event_id=event.id,
            properties={
                "basic": {"company": "智谱AI", "industry": "AI"},
                "concern": [{"category": "融资", "detail": "需要资金"}],
                "capability": [{"category": "技术架构", "detail": "大模型"}],
            },
        )

        # Create association (simulating pipeline step 10)
        await insert_association(
            db_session,
            source_entity_id=entity_a.id,
            target_entity_id=entity_b.id,
            association_type="supply_demand",
            source_event_id=event.id,
        )
        await db_session.commit()

        # Verify association is visible via API
        resp = await client.get(f"{API_PREFIX}/associations")
        assert resp.status_code == 200
        assocs = resp.json()["items"]
        supply_demand = [a for a in assocs if a["association_type"] == "supply_demand"]
        assert len(supply_demand) >= 1

    @pytest.mark.asyncio
    async def test_step4_relationship_brief_shows_evolution(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Step 4-5: Relationship brief shows evolution across multiple interactions."""
        # First interaction
        ids1 = await simulate_pipeline_output(
            session=db_session,
            raw_text="初识李总，交换了名片",
            event_title="初识李总",
            person_name="李总",
            person_company="盛恒资本",
            person_title="合伙人",
            todo_title="跟进李总",
            todo_type="care",
        )
        entity_id = ids1["entity_id"]

        # Second interaction — deeper engagement
        event2 = await insert_event(
            db_session,
            title="和李总深度交流",
            raw_text="和李总深入讨论了投资方案",
            status="completed",
        )
        entity_result = await db_session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = entity_result.scalar_one()

        todo2 = await insert_todo(
            db_session,
            title="准备投资方案给李总",
            todo_type="promise",
            source_event_id=event2.id,
            related_entity_id=entity_id,
            status="pending",
        )
        await db_session.commit()

        service = RelationshipBriefService(db_session)
        await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=entity_id,
            event=event2,
            entities=[entity],
            todos=[todo2],
        )
        await db_session.commit()

        # View aggregated brief
        resp = await client.get(
            f"{API_PREFIX}/persons/{entity_id}/relationship-brief/aggregated"
        )
        assert resp.status_code == 200
        data = resp.json()

        # Verify brief shows evolution
        assert data["person_name"] == "李总"
        assert data["person_company"] == "盛恒资本"
        assert data["version"] >= 2
        assert data["strength_score"] > 0  # Should have some score after interactions

        # Verify modules have data
        modules_with_data = [m for m in data["modules"] if m["has_data"]]
        assert len(modules_with_data) >= 3  # At least basic_info, last_interaction, interaction_freq

    @pytest.mark.asyncio
    async def test_full_relationship_tracking_journey(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Complete Journey 3: Two interactions → association → brief evolution."""
        # Interaction 1: Meet 李总
        ids1 = await simulate_pipeline_output(
            session=db_session,
            raw_text="今天和李总喝茶，聊了AI合作的可能性",
            event_title="和李总喝茶",
            person_name="李总",
            person_company="盛恒资本",
            person_title="合伙人",
            concerns=[{"category": "AI合作", "detail": "AI合作的可能性"}],
            todo_title="跟进李总AI合作意向",
            todo_type="care",
        )

        # Interaction 2: Meet 李总 again
        event2 = await insert_event(
            db_session,
            title="和李总深度交流",
            raw_text="和李总深入讨论了投资方案，他答应下周安排面谈",
            status="completed",
        )
        entity_id = ids1["entity_id"]
        entity_result = await db_session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = entity_result.scalar_one()

        todo2 = await insert_todo(
            db_session,
            title="准备投资方案给李总",
            todo_type="promise",
            source_event_id=event2.id,
            related_entity_id=entity_id,
            status="pending",
        )
        await db_session.commit()

        service = RelationshipBriefService(db_session)
        await service.update_brief_from_event(
            user_id=TEST_USER_ID,
            person_entity_id=entity_id,
            event=event2,
            entities=[entity],
            todos=[todo2],
        )
        await db_session.commit()

        # Also create 张总 entity and association
        ids2 = await simulate_pipeline_output(
            session=db_session,
            raw_text="和张总聊了AI在制造业的应用",
            event_title="和张总交流",
            person_name="张总",
            person_company="智谱AI",
            person_title="CTO",
        )

        # Create association between 李总 and 张总
        await insert_association(
            db_session,
            source_entity_id=entity_id,
            target_entity_id=ids2["entity_id"],
            association_type="supply_demand",
        )
        await db_session.commit()

        # Verify the full journey
        # 1. Entity for 李总 exists
        resp = await client.get(f"{API_PREFIX}/entities", params={"search": "李总"})
        assert resp.status_code == 200
        assert any(e["name"] == "李总" for e in resp.json()["items"])

        # 2. Brief for 李总 has evolved
        resp = await client.get(
            f"{API_PREFIX}/persons/{entity_id}/relationship-brief/aggregated"
        )
        assert resp.status_code == 200
        brief = resp.json()
        assert brief["version"] >= 2
        assert brief["strength_score"] > 0

        # 3. Association exists
        resp = await client.get(f"{API_PREFIX}/associations")
        assert resp.status_code == 200
        assocs = resp.json()["items"]
        assert len(assocs) >= 1

        # 4. Entity history shows both events
        resp = await client.get(f"{API_PREFIX}/entities/{entity_id}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history["events"]) >= 1
        assert len(history["associations"]) >= 1

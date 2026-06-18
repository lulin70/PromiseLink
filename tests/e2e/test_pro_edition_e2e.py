"""Pro Edition E2E tests — covering two critical user journeys.

Scenario 1: License activation flow (Gateway)
    User inputs license key → activates → obtains JWT → verifies token works.

Scenario 2: Event recording + correction flow (PromiseLink app)
    User records event → AI parses (mocked) → corrects entity → confirms
    promise → verifies detail page.

Uses FastAPI TestClient (gateway) and httpx.AsyncClient+ASGITransport
(promiselink app) so no real server is needed. LLM calls are mocked.

Run:
    cd /Users/lin/trae_projects/PromiseLink && \\
    python -m pytest tests/e2e/test_pro_edition_e2e.py -v --tb=short
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

# ── Path setup so both `gateway` and `promiselink` are importable ──

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_SRC_PATH = _PROJECT_ROOT / "src"
if str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# Set test environment variables BEFORE importing gateway modules.
os.environ.setdefault("GATEWAY_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Gateway imports
from gateway.config import get_settings  # noqa: E402
from gateway.core.jwt_handler import JWTHandler  # noqa: E402
from gateway.main import create_app  # noqa: E402
from gateway.services.api_key_pool import create_default_key_pool  # noqa: E402
from gateway.services.billing_service import BillingService  # noqa: E402
from gateway.services.relay_service import RelayService  # noqa: E402
from gateway.tests._helpers import (  # noqa: E402
    InMemoryLicenseService,
    make_device_fingerprint,
    make_license,
    make_license_key,
    make_user_id,
)

# PromiseLink imports
from promiselink.core.auth import get_current_user_id  # noqa: E402
from promiselink.database import Base, get_async_session  # noqa: E402
from promiselink.main import app as pl_app  # noqa: E402
from promiselink.models.entity import Entity  # noqa: E402
from promiselink.models.event import Event  # noqa: E402
from promiselink.models.todo import Todo  # noqa: E402

# ── Constants ──

TEST_API_KEY = "pl_gateway_client_dev_key"
PL_TEST_USER_ID = "00000000-0000-0000-0000-000000000030"
PL_OTHER_USER_ID = "00000000-0000-0000-0000-000000000040"
API_PREFIX = "/api/v1"


# ══════════════════════════════════════════════════════════════════════════════
# Gateway fixtures (for Scenario 1: license activation)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_gateway_settings_cache():
    """Clear the settings LRU cache before and after each gateway test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def gateway_settings():
    """Return gateway test settings."""
    return get_settings()


@pytest.fixture
def gateway_jwt_handler(gateway_settings):
    """Return a JWTHandler for the gateway."""
    return JWTHandler(gateway_settings)


@pytest.fixture
def gateway_license_store():
    """Return a fresh in-memory license store."""
    return {}


@pytest.fixture
def gateway_license_service(gateway_jwt_handler, gateway_license_store):
    """Return an InMemoryLicenseService wired to the shared store."""
    return InMemoryLicenseService(
        jwt_handler=gateway_jwt_handler,
        licenses=gateway_license_store,
    )


@pytest.fixture
def gateway_billing_service(gateway_settings, gateway_license_store):
    """Return a BillingService sharing the license store."""
    return BillingService(settings=gateway_settings, licenses=gateway_license_store)


@pytest.fixture
def gateway_mock_llm_transport():
    """Return an httpx.MockTransport that simulates LLM provider responses."""
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        model = body.get("model", "test-model")
        resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Mock LLM response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 10,
                "total_tokens": 20,
            },
        }
        return httpx.Response(status_code=200, json=resp)

    return httpx.MockTransport(handler)


@pytest.fixture
def gateway_api_key_pool(gateway_settings):
    """Return a default API key pool."""
    return create_default_key_pool(gateway_settings)


@pytest.fixture
def gateway_relay_service(
    gateway_billing_service, gateway_settings, gateway_mock_llm_transport, gateway_api_key_pool
):
    """Return a RelayService with mock HTTP transport."""
    return RelayService(
        api_key_pool=gateway_api_key_pool,
        billing_service=gateway_billing_service,
        http_client=httpx.AsyncClient(transport=gateway_mock_llm_transport),
        settings=gateway_settings,
    )


@pytest.fixture
def gateway_client(
    gateway_settings,
    gateway_jwt_handler,
    gateway_license_service,
    gateway_billing_service,
    gateway_relay_service,
    gateway_api_key_pool,
):
    """Create a FastAPI TestClient for the gateway with all services injected."""
    app = create_app(
        settings=gateway_settings,
        jwt_handler=gateway_jwt_handler,
        license_service=gateway_license_service,
        billing_service=gateway_billing_service,
        relay_service=gateway_relay_service,
        api_key_pool=gateway_api_key_pool,
    )
    with TestClient(app) as client:
        yield client


# ══════════════════════════════════════════════════════════════════════════════
# PromiseLink app fixtures (for Scenario 2: event recording)
# ══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def pl_db_engine():
    """Create an in-memory SQLite async engine for PromiseLink tests."""
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
async def pl_db_session(pl_db_engine):
    """Provide an async DB session for direct data setup."""
    session_factory = async_sessionmaker(
        pl_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def pl_client(pl_db_session):
    """Provide an httpx.AsyncClient with DB dependency overridden and LLM mocked."""
    async def override_get_async_session():
        yield pl_db_session

    pl_app.dependency_overrides[get_async_session] = override_get_async_session
    pl_app.dependency_overrides[get_current_user_id] = lambda: PL_TEST_USER_ID

    # Mock the background pipeline to avoid real LLM calls
    async def mock_process_event(event_id):
        pass

    import promiselink.services.event_processor as processor_module

    original_process = processor_module.process_event_background
    processor_module.process_event_background = mock_process_event

    transport = ASGITransport(app=pl_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    processor_module.process_event_background = original_process
    pl_app.dependency_overrides.clear()


# ── PromiseLink DB helpers ──


async def _pl_insert_event(session: AsyncSession, **overrides) -> Event:
    """Insert an Event directly into the test DB."""
    data = {
        "id": str(uuid.uuid4()),
        "user_id": PL_TEST_USER_ID,
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


async def _pl_insert_entity(session: AsyncSession, **overrides) -> Entity:
    """Insert an Entity directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await _pl_insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": PL_TEST_USER_ID,
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


async def _pl_insert_todo(session: AsyncSession, **overrides) -> Todo:
    """Insert a Todo directly into the test DB."""
    source_event_id = overrides.pop("source_event_id", None)
    if source_event_id is None:
        event = await _pl_insert_event(session)
        source_event_id = event.id

    data = {
        "id": str(uuid.uuid4()),
        "user_id": PL_TEST_USER_ID,
        "todo_type": "promise",
        "title": "Test Promise",
        "description": "Test description",
        "priority": 3,
        "status": "pending",
        "source_event_id": str(source_event_id),
        "action_type": "my_promise",
        "fulfillment_status": "pending",
    }
    data.update(overrides)
    todo = Todo(**data)
    session.add(todo)
    await session.flush()
    return todo


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 1: License Activation Flow (Gateway)
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario1LicenseActivation:
    """E2E scenario 1: License activation full flow.

    Simulates a user entering a license key, activating it, obtaining a
    relay JWT, and verifying the token works for authenticated endpoints.
    """

    def test_license_activation_and_jwt_verification(
        self,
        gateway_client: TestClient,
        gateway_license_store,
        gateway_jwt_handler,
    ):
        """User activates license → gets JWT → JWT works on protected endpoint.

        Steps:
        1. Admin pre-creates a license in the store.
        2. User activates the license via POST /api/v1/pro/license/activate.
        3. User receives access_token and refresh_token.
        4. User calls GET /api/v1/pro/usage with the access_token → 200.
        5. Verify the JWT payload contains correct user_id and license_key.
        """
        # ── Step 1: Admin pre-creates a license ──
        license_key = make_license_key("E2EACT01")
        user_id = make_user_id("e2e-user-01")
        device_fp = make_device_fingerprint("e2e-device-01")

        lic = make_license(license_key, status="active")
        gateway_license_store[license_key] = lic

        # ── Step 2: User creates a pre-activation JWT and activates ──
        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=user_id,
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        activate_resp = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": license_key,
                "device_fingerprint": device_fp,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert activate_resp.status_code == 200, (
            f"Activation failed: {activate_resp.text}"
        )

        # ── Step 3: User receives relay JWT ──
        activate_data = activate_resp.json()["data"]
        assert activate_data["license"]["license_key"] == license_key
        assert activate_data["license"]["status"] == "active"

        access_token = activate_data["tokens"]["access_token"]
        refresh_token = activate_data["tokens"]["refresh_token"]
        assert access_token, "access_token must be non-empty"
        assert refresh_token, "refresh_token must be non-empty"
        assert activate_data["tokens"]["token_type"] == "Bearer"

        relay_headers = {
            "X-API-Key": TEST_API_KEY,
            "Authorization": f"Bearer {access_token}",
        }

        # ── Step 4: User calls protected endpoint with the JWT ──
        usage_resp = gateway_client.get(
            "/api/v1/pro/usage",
            headers=relay_headers,
        )
        assert usage_resp.status_code == 200, (
            f"Usage query with relay JWT failed: {usage_resp.text}"
        )
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["limit"] > 0
        assert usage_data["quota"]["tokens"]["used"] == 0
        assert usage_data["traffic_light"] == "green"

        # ── Step 5: Verify JWT payload correctness ──
        import jwt as pyjwt

        payload = pyjwt.decode(
            access_token,
            gateway_jwt_handler.settings.jwt_secret_key,
            algorithms=[gateway_jwt_handler.settings.jwt_algorithm],
            audience=gateway_jwt_handler.settings.jwt_audience,
            options={"verify_exp": False},
        )
        assert payload["user_id"] == user_id, (
            f"JWT user_id mismatch: expected {user_id}, got {payload.get('user_id')}"
        )
        assert payload["license_key"] == license_key, (
            f"JWT license_key mismatch: expected {license_key}, got {payload.get('license_key')}"
        )
        assert payload["plan_type"] == "pro"
        assert payload["device_fingerprint"] == device_fp

    def test_license_activation_rejects_invalid_key(
        self,
        gateway_client: TestClient,
        gateway_jwt_handler,
    ):
        """Activating with a non-existent license key returns an error.

        Verifies the error path of the activation flow.
        """
        user_id = make_user_id("e2e-user-invalid")
        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=user_id,
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        # Use a valid-format key that doesn't exist in the store
        fake_key = make_license_key("NOLICENCE")
        device_fp = make_device_fingerprint("e2e-device-invalid")

        resp = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": fake_key,
                "device_fingerprint": device_fp,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert resp.status_code == 404, (
            f"Non-existent license should return 404, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "LICENSE_NOT_FOUND"

    def test_license_activation_and_relay_call(
        self,
        gateway_client: TestClient,
        gateway_license_store,
        gateway_jwt_handler,
    ):
        """Full flow: activate → call LLM relay → verify usage recorded.

        Verifies the JWT obtained from activation works for relay calls
        and that usage is properly tracked.
        """
        # Setup license
        license_key = make_license_key("E2ERELAY")
        user_id = make_user_id("e2e-relay-user")
        device_fp = make_device_fingerprint("e2e-relay-device")

        lic = make_license(license_key, status="active")
        gateway_license_store[license_key] = lic

        # Activate
        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=user_id,
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )
        activate_resp = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": license_key,
                "device_fingerprint": device_fp,
            },
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert activate_resp.status_code == 200
        access_token = activate_resp.json()["data"]["tokens"]["access_token"]

        relay_headers = {
            "X-API-Key": TEST_API_KEY,
            "Authorization": f"Bearer {access_token}",
        }

        # Call LLM relay
        relay_resp = gateway_client.post(
            "/api/v1/pro/relay/llm",
            json={
                "model": "moka-chat",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
            },
            headers=relay_headers,
        )
        assert relay_resp.status_code == 200, (
            f"LLM relay failed: {relay_resp.text}"
        )
        relay_data = relay_resp.json()["data"]
        assert relay_data["content"] == "Mock LLM response"
        assert relay_data["usage"]["total_tokens"] == 20

        # Verify usage was recorded
        usage_resp = gateway_client.get(
            "/api/v1/pro/usage",
            headers=relay_headers,
        )
        assert usage_resp.status_code == 200
        usage_data = usage_resp.json()["data"]
        assert usage_data["quota"]["tokens"]["used"] == 20


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 2: Event Recording + Correction Flow (PromiseLink app)
# ══════════════════════════════════════════════════════════════════════════════


class TestScenario2EventRecordingAndCorrection:
    """E2E scenario 2: Event recording + entity correction flow.

    Simulates a user recording an event, the AI parsing it (mocked by
    direct DB inserts), the user correcting the parsed entity, confirming
    a promise, and verifying the detail page.
    """

    @pytest.mark.asyncio
    async def test_event_creation_and_view(
        self, pl_client: AsyncClient, pl_db_session: AsyncSession
    ):
        """2.1 User records an event and views it.

        Steps:
        1. User POST /events with meeting content.
        2. Event is created with status=pending.
        3. User GET /events/{id} to view details.
        """
        # Record event
        resp = await pl_client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "manual",
                "title": "与张总的合作会议",
                "raw_text": "今天和张总见面讨论了AI合作方案，张总承诺下周提供技术方案。",
            },
        )
        assert resp.status_code == 201
        event_data = resp.json()
        event_id = event_data["id"]
        assert event_data["event_type"] == "meeting"
        assert event_data["title"] == "与张总的合作会议"
        assert event_data["status"] == "pending"

        # View event detail
        resp = await pl_client.get(f"{API_PREFIX}/events/{event_id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["id"] == event_id
        assert "张总" in detail["raw_text"]

    @pytest.mark.asyncio
    async def test_ai_parsed_entity_correction(
        self, pl_client: AsyncClient, pl_db_session: AsyncSession
    ):
        """2.2 User corrects AI-parsed entity information.

        Steps:
        1. AI (mocked) parses event and creates an entity with wrong info.
        2. User views entity list and finds the parsed entity.
        3. User PATCH /entities/{id} to correct the name and properties.
        4. Verify the correction is persisted.
        """
        # Simulate AI parsing result by inserting an entity directly
        event = await _pl_insert_event(
            pl_db_session,
            title="与李总的会议",
            raw_text="今天和李总讨论了合作",
        )
        entity = await _pl_insert_entity(
            pl_db_session,
            name="李总",  # AI parsed name (may be incorrect)
            canonical_name="李总",
            source_event_id=event.id,
            properties={
                "basic": {
                    "company": "未知公司",  # AI guessed wrong
                    "title": "未知",
                }
            },
        )
        await pl_db_session.commit()

        # User views entity list
        resp = await pl_client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(e["name"] == "李总" for e in data["items"])

        # User corrects the entity
        resp = await pl_client.patch(
            f"{API_PREFIX}/entities/{entity.id}",
            json={
                "name": "李明远",
                "aliases": ["李总", "李总工"],
                "properties": {
                    "basic": {
                        "company": "智源科技",
                        "title": "技术总监",
                        "city": "北京",
                    }
                },
                "status": "confirmed",
            },
        )
        assert resp.status_code == 200
        updated = resp.json()
        assert updated["name"] == "李明远"
        assert "李总" in updated["aliases"]
        assert "李总工" in updated["aliases"]
        assert updated["status"] == "confirmed"

        # Verify correction persisted
        resp = await pl_client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["name"] == "李明远"
        assert detail["properties"]["basic"]["company"] == "智源科技"
        assert detail["properties"]["basic"]["title"] == "技术总监"

    @pytest.mark.asyncio
    async def test_promise_confirmation_flow(
        self, pl_client: AsyncClient, pl_db_session: AsyncSession
    ):
        """2.3 User confirms and fulfills a promise extracted by AI.

        Steps:
        1. AI (mocked) extracts a promise from the event.
        2. User views pending confirmations.
        3. User confirms the promise (PATCH /todos/{id}/confirm).
        4. User marks the promise as fulfilled.
        5. Verify promise stats reflect the fulfillment.
        """
        # Simulate AI extracting a promise
        event = await _pl_insert_event(
            pl_db_session,
            title="与王总的承诺",
            raw_text="我答应王总下周发一份技术方案",
        )
        entity = await _pl_insert_entity(
            pl_db_session,
            name="王总",
            source_event_id=event.id,
        )
        todo = await _pl_insert_todo(
            pl_db_session,
            title="给王总发技术方案",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="pending",
            description="我答应下周发技术方案",
        )
        await pl_db_session.commit()

        # View pending confirmations
        resp = await pl_client.get(f"{API_PREFIX}/todos/pending-confirmations")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        assert any(t["title"] == "给王总发技术方案" for t in items)

        # Confirm the promise
        new_due = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        resp = await pl_client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={
                "confirmation_status": "confirmed",
                "description": "确认后的承诺：下周五前发方案",
                "due_date": new_due,
            },
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["confirmation_status"] == "confirmed"

        # Mark as fulfilled
        resp = await pl_client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 200
        fulfilled = resp.json()
        assert fulfilled["fulfillment_status"] == "fulfilled"

        # Verify promise stats
        resp = await pl_client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["my_promises"]["fulfilled"] >= 1

    @pytest.mark.asyncio
    async def test_entity_detail_and_history_view(
        self, pl_client: AsyncClient, pl_db_session: AsyncSession
    ):
        """2.4 User views entity detail page with interaction history.

        Steps:
        1. Create event + entity + todo (simulating AI parse result).
        2. User GET /entities/{id} to view detail.
        3. User GET /entities/{id}/history to view interaction history.
        4. Verify history includes the event and todo.
        """
        event = await _pl_insert_event(
            pl_db_session,
            title="与赵六的战略讨论",
            raw_text="和赵六讨论了AI战略合作的细节",
        )
        entity = await _pl_insert_entity(
            pl_db_session,
            name="赵六",
            canonical_name="赵六",
            source_event_id=event.id,
            properties={
                "basic": {"company": "某AI公司", "title": "CTO", "city": "北京"},
                "concern": [{"category": "AI应用", "detail": "寻找AI落地场景"}],
            },
        )
        await _pl_insert_todo(
            pl_db_session,
            title="给赵六发AI案例",
            todo_type="promise",
            source_event_id=event.id,
            related_entity_id=entity.id,
            status="pending",
            action_type="my_promise",
        )
        await pl_db_session.commit()

        # View entity detail
        resp = await pl_client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["name"] == "赵六"
        assert detail["entity_type"] == "person"
        assert detail["properties"]["basic"]["title"] == "CTO"

        # View entity history
        resp = await pl_client.get(f"{API_PREFIX}/entities/{entity.id}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert history["entity"]["name"] == "赵六"
        assert len(history["events"]) >= 1
        assert len(history["todos"]) >= 1
        assert history["events"][0]["title"] == "与赵六的战略讨论"

    @pytest.mark.asyncio
    async def test_full_journey_event_to_fulfillment(
        self, pl_client: AsyncClient, pl_db_session: AsyncSession
    ):
        """2.5 Full journey: record event → correct entity → confirm → fulfill.

        Integrates all sub-flows into a single end-to-end test.
        """
        # Step 1: Record event
        resp = await pl_client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "manual",
                "title": "与陈总的深度交流",
                "raw_text": "今天和陈总聊了两个小时，我承诺本周五前发一份详细的产品方案。",
            },
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]

        # Step 2: Simulate AI parsing (mocked pipeline doesn't run)
        entity = await _pl_insert_entity(
            pl_db_session,
            name="陈总",
            canonical_name="陈总",
            source_event_id=event_id,
            properties={"basic": {"company": "未知", "title": "未知"}},
        )
        todo = await _pl_insert_todo(
            pl_db_session,
            title="给陈总发产品方案",
            todo_type="promise",
            source_event_id=event_id,
            related_entity_id=entity.id,
            status="pending",
            action_type="my_promise",
            confirmation_status="pending",
            description="本周五前发方案",
        )
        await pl_db_session.commit()

        # Step 3: User corrects entity info
        resp = await pl_client.patch(
            f"{API_PREFIX}/entities/{entity.id}",
            json={
                "name": "陈建华",
                "aliases": ["陈总"],
                "properties": {
                    "basic": {"company": "创新科技", "title": "CEO", "city": "上海"}
                },
            },
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "陈建华"

        # Step 4: User confirms the promise
        resp = await pl_client.patch(
            f"{API_PREFIX}/todos/{todo.id}/confirm",
            json={
                "confirmation_status": "confirmed",
                "description": "确认：本周五前发产品方案给陈总",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["confirmation_status"] == "confirmed"

        # Step 5: User marks promise as fulfilled
        resp = await pl_client.patch(
            f"{API_PREFIX}/promises/{todo.id}/fulfillment",
            json={"fulfillment_status": "fulfilled"},
        )
        assert resp.status_code == 200
        assert resp.json()["fulfillment_status"] == "fulfilled"

        # Step 6: Verify entity detail page shows corrected info
        resp = await pl_client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["name"] == "陈建华"
        assert detail["properties"]["basic"]["company"] == "创新科技"

        # Step 7: Verify entity history includes the event
        resp = await pl_client.get(f"{API_PREFIX}/entities/{entity.id}/history")
        assert resp.status_code == 200
        history = resp.json()
        assert len(history["events"]) >= 1
        assert len(history["todos"]) >= 1

        # Step 8: Verify promise stats
        resp = await pl_client.get(f"{API_PREFIX}/promises/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["my_promises"]["fulfilled"] >= 1
        assert stats["fulfillment_rate"] > 0

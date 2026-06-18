"""Pro Edition Security Tests — 10 P0 security test cases.

Covers ten security dimensions (all P0 priority):
  1.  SQL Injection       — events/entities/todos APIs
  2.  XSS                 — event content / entity names
  3.  Path Traversal      — export API
  4.  JWT Authentication  — invalid / expired / tampered JWT
  5.  Authorization       — cross-user data access
  6.  Input Validation    — super long / special chars / null
  7.  Rate Limiting       — API rate limit enforcement
  8.  License Activation  — invalid / revoked / bound keys
  9.  Admin API Auth      — no admin key / wrong admin key
  10. Relay Client        — invalid JWT / gateway unreachable degradation

Tests 1-7 use the PromiseLink app via httpx.AsyncClient+ASGITransport.
Tests 8-9 use the Gateway app via FastAPI TestClient.
Test 10 uses the RelayClient directly with mocked HTTP.

Run:
    cd /Users/lin/trae_projects/PromiseLink && \\
    python -m pytest tests/test_pro_security.py -v --tb=short
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

# ── Path setup ──

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
import jwt as pyjwt  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from jose import jwt as jose_jwt  # noqa: E402
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Gateway imports
from gateway.config import get_settings as get_gateway_settings  # noqa: E402
from gateway.core.jwt_handler import JWTHandler  # noqa: E402
from gateway.main import create_app as create_gateway_app  # noqa: E402
from gateway.services.api_key_pool import create_default_key_pool  # noqa: E402
from gateway.services.billing_service import BillingService  # noqa: E402
from gateway.services.relay_service import RelayService  # noqa: E402
from gateway.tests._helpers import (  # noqa: E402
    InMemoryLicenseService,
    make_admin_jwt,
    make_device_fingerprint,
    make_license,
    make_license_key,
    make_user_id,
)

# PromiseLink imports
from promiselink.core.auth import create_access_token, get_current_user_id  # noqa: E402
from promiselink.database import Base, get_async_session  # noqa: E402
from promiselink.main import app as pl_app  # noqa: E402
from promiselink.models.entity import Entity  # noqa: E402
from promiselink.models.event import Event  # noqa: E402
from promiselink.models.todo import Todo  # noqa: E402

# ── Constants ──

TEST_API_KEY = "pl_gateway_client_dev_key"
TEST_USER_ID = "00000000-0000-0000-0000-000000000050"
OTHER_USER_ID = "00000000-0000-0000-0000-000000000060"
API_PREFIX = "/api/v1"


# ══════════════════════════════════════════════════════════════════════════════
# PromiseLink app fixtures (for tests 1-7)
# ══════════════════════════════════════════════════════════════════════════════


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
async def client(db_session):
    """Authenticated client: overrides get_current_user_id to TEST_USER_ID."""
    async def override_get_async_session():
        yield db_session

    pl_app.dependency_overrides[get_async_session] = override_get_async_session
    pl_app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

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


@pytest_asyncio.fixture
async def jwt_client(db_session):
    """Client WITHOUT get_current_user_id override — real JWT validation runs."""
    async def override_get_async_session():
        yield db_session

    pl_app.dependency_overrides[get_async_session] = override_get_async_session

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


# ── DB helpers ──


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
# Gateway fixtures (for tests 8-9)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _reset_gateway_settings_cache():
    """Clear the gateway settings LRU cache before and after each test."""
    get_gateway_settings.cache_clear()
    yield
    get_gateway_settings.cache_clear()


@pytest.fixture
def gateway_settings():
    """Return gateway test settings."""
    return get_gateway_settings()


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
        resp = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1700000000,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Mock LLM response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
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
    app = create_gateway_app(
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
# 1. SQL Injection Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0SQLInjection:
    """P0-1: SQL injection protection on events/entities/todos APIs."""

    SQL_PAYLOADS = [
        "'; DROP TABLE events; --",
        "' OR '1'='1",
        "1; DELETE FROM users WHERE 1=1; --",
        "' UNION SELECT * FROM entities --",
        "admin'--",
        "'; INSERT INTO events(title) VALUES('hacked'); --",
    ]

    @pytest.mark.asyncio
    async def test_sql_injection_in_event_title(self, client: AsyncClient):
        """SQL injection in event title should not break the database."""
        for payload in self.SQL_PAYLOADS:
            resp = await client.post(
                f"{API_PREFIX}/events",
                json={
                    "event_type": "meeting",
                    "source": "test",
                    "title": payload,
                    "raw_text": "normal text",
                },
            )
            assert resp.status_code == 201, (
                f"Event creation failed for payload {payload!r}: {resp.status_code}"
            )

        # Verify events table is intact
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200
        assert resp.json()["total"] >= len(self.SQL_PAYLOADS)

    @pytest.mark.asyncio
    async def test_sql_injection_in_entity_search(self, client: AsyncClient, db_session: AsyncSession):
        """SQL injection in entity search should not leak data."""
        await insert_entity(db_session, name="Zhang San")
        await db_session.commit()

        for payload in self.SQL_PAYLOADS:
            resp = await client.get(
                f"{API_PREFIX}/entities", params={"search": payload}
            )
            assert resp.status_code == 200
            data = resp.json()
            # Injection should not return all entities
            assert data["total"] <= 1, (
                f"Entity search for {payload!r} returned {data['total']} results. "
                "Possible SQL injection."
            )

    @pytest.mark.asyncio
    async def test_sql_injection_in_todo_search(self, client: AsyncClient, db_session: AsyncSession):
        """SQL injection in todo search should not leak data."""
        event = await insert_event(db_session, title="Todo Test Event")
        await insert_todo(db_session, title="Follow up call", source_event_id=event.id)
        await db_session.commit()

        for payload in self.SQL_PAYLOADS:
            resp = await client.get(
                f"{API_PREFIX}/todos", params={"search": payload}
            )
            assert resp.status_code == 200
            # Should not crash or return all todos
            data = resp.json()
            assert data["total"] <= 1, (
                f"Todo search for {payload!r} returned {data['total']} results."
            )

    @pytest.mark.asyncio
    async def test_database_integrity_after_injection(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Verify database integrity is maintained after injection attempts."""
        await insert_event(db_session, title="Baseline Event")
        await insert_entity(db_session, name="Baseline Person")
        await db_session.commit()

        for payload in self.SQL_PAYLOADS:
            await client.post(
                f"{API_PREFIX}/events",
                json={
                    "event_type": "meeting",
                    "source": "test",
                    "title": payload,
                    "raw_text": payload,
                },
            )

        # Verify tables still exist and baseline data is intact
        resp = await client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 200, "events table may have been dropped"
        assert resp.json()["total"] >= 1, "Baseline events deleted — SQL injection succeeded"

        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200, "entities table may have been dropped"
        assert resp.json()["total"] >= 1, "Baseline entities deleted — SQL injection succeeded"


# ══════════════════════════════════════════════════════════════════════════════
# 2. XSS Protection Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0XSSProtection:
    """P0-2: XSS protection on event content and entity names."""

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "<svg onload=alert(document.cookie)>",
        "javascript:alert('xss')",
        "<iframe src='javascript:alert(1)'></iframe>",
        "<body onload=alert('xss')>",
    ]

    @pytest.mark.asyncio
    async def test_xss_in_event_title_stored_safely(self, client: AsyncClient):
        """XSS payloads in event title should be stored as plain text in JSON."""
        for payload in self.XSS_PAYLOADS:
            resp = await client.post(
                f"{API_PREFIX}/events",
                json={
                    "event_type": "meeting",
                    "source": "test",
                    "title": payload,
                    "raw_text": "normal text",
                },
            )
            assert resp.status_code == 201, (
                f"Event creation failed for XSS payload {payload!r}: {resp.status_code}"
            )
            # Response must be JSON, never HTML
            assert resp.headers["content-type"].startswith("application/json"), (
                "Response is not JSON — possible XSS via content-type confusion"
            )

    @pytest.mark.asyncio
    async def test_xss_in_entity_name_stored_safely(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """XSS payloads in entity name should be stored as JSON values."""
        event = await insert_event(db_session, title="XSS Test Event")
        entity = await insert_entity(
            db_session, name="XSS Target", source_event_id=event.id
        )
        await db_session.commit()

        xss_name = "<script>alert('name')</script>"
        resp = await client.patch(
            f"{API_PREFIX}/entities/{entity.id}",
            json={"name": xss_name},
        )
        assert resp.status_code == 200, f"Entity update failed: {resp.text}"
        assert resp.headers["content-type"].startswith("application/json")

        # Retrieve and verify XSS payload is in JSON (not executed)
        resp = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/json")
        assert "alert" in json.dumps(resp.json()), "XSS payload should be stored as text"

    @pytest.mark.asyncio
    async def test_xss_not_reflected_as_html(self, client: AsyncClient):
        """API response should never return HTML content-type."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "test",
                "title": "<script>alert('xss')</script>",
                "raw_text": "<img src=x onerror=alert(1)>",
            },
        )
        assert resp.status_code == 201
        assert resp.headers["content-type"].startswith("application/json"), (
            f"Content-Type is {resp.headers['content-type']} — possible XSS vector"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 3. Path Traversal Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0PathTraversal:
    """P0-3: Path traversal protection on export API."""

    TRAVERSAL_PAYLOADS = [
        "../../../etc/passwd",
        "..\\..\\..\\windows\\system32",
        "....//....//....//etc/passwd",
        "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
        "..%252f..%252f..%252fetc%252fpasswd",
        "/etc/passwd",
        "/etc/shadow",
        "C:\\Windows\\System32\\config\\SAM",
    ]

    @pytest.mark.asyncio
    async def test_path_traversal_in_export_endpoint(self, client: AsyncClient):
        """Path traversal in export user_id should not access system files."""
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = await client.get(f"{API_PREFIX}/export/{payload}")
            # Should be 403 (user_id mismatch) or 404/422 (route not matched)
            assert resp.status_code in (403, 404, 422), (
                f"Export with traversal payload {payload!r} returned {resp.status_code}. "
                "Possible path traversal vulnerability."
            )
            if resp.status_code == 200:
                body = resp.text
                assert "root:" not in body, "/etc/passwd content leaked!"
                assert "[boot loader]" not in body, "Windows system file leaked!"

    @pytest.mark.asyncio
    async def test_path_traversal_in_entity_id(self, client: AsyncClient):
        """Path traversal in entity_id path parameter should return 404 or 422."""
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = await client.get(f"{API_PREFIX}/entities/{payload}")
            assert resp.status_code in (404, 422), (
                f"GET entity with traversal payload {payload!r} returned {resp.status_code}."
            )

    @pytest.mark.asyncio
    async def test_path_traversal_in_event_id(self, client: AsyncClient):
        """Path traversal in event_id path parameter should return 404 or 422."""
        for payload in self.TRAVERSAL_PAYLOADS:
            resp = await client.get(f"{API_PREFIX}/events/{payload}")
            assert resp.status_code in (404, 422), (
                f"GET event with traversal payload {payload!r} returned {resp.status_code}."
            )


# ══════════════════════════════════════════════════════════════════════════════
# 4. JWT Authentication Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0JWTAuthentication:
    """P0-4: JWT authentication — invalid / expired / tampered tokens."""

    @pytest.mark.asyncio
    async def test_no_token_returns_401(self, jwt_client: AsyncClient):
        """Accessing protected endpoint without token should return 401."""
        resp = await jwt_client.get(f"{API_PREFIX}/events")
        assert resp.status_code == 401, (
            f"Expected 401 for no token, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_expired_jwt_returns_401(self, jwt_client: AsyncClient):
        """Expired JWT token should return 401."""
        from promiselink.config import get_settings

        settings = get_settings()
        expired_payload = {
            "sub": TEST_USER_ID,
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
            "iss": "promiselink",
            "aud": "promiselink-api",
        }
        expired_token = jose_jwt.encode(
            expired_payload, settings.secret_key, algorithm=settings.algorithm
        )

        resp = await jwt_client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 for expired JWT, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_tampered_jwt_returns_401(self, jwt_client: AsyncClient):
        """JWT with tampered payload should return 401."""
        valid_token = create_access_token(TEST_USER_ID)
        # Tamper with the token by changing the last characters
        tampered_token = valid_token[:-8] + "XXXXXXXX"

        resp = await jwt_client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": f"Bearer {tampered_token}"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 for tampered JWT, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_invalid_signature_jwt_returns_401(self, jwt_client: AsyncClient):
        """JWT with wrong signing key should return 401."""
        payload = {
            "sub": TEST_USER_ID,
            "iat": datetime.now(UTC),
            "exp": datetime.now(UTC) + timedelta(minutes=30),
            "iss": "promiselink",
            "aud": "promiselink-api",
        }
        wrong_token = jose_jwt.encode(payload, "wrong-secret-key", algorithm="HS256")

        resp = await jwt_client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": f"Bearer {wrong_token}"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 for invalid signature JWT, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_valid_jwt_returns_200(self, jwt_client: AsyncClient):
        """Valid JWT token should allow access to protected endpoint."""
        valid_token = create_access_token(TEST_USER_ID)

        resp = await jwt_client.get(
            f"{API_PREFIX}/events",
            headers={"Authorization": f"Bearer {valid_token}"},
        )
        assert resp.status_code == 200, (
            f"Expected 200 for valid JWT, got {resp.status_code}."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Authorization (Cross-User Access) Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0Authorization:
    """P0-5: Authorization — cross-user data access protection."""

    @pytest.mark.asyncio
    async def test_cross_user_event_access_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User A cannot access User B's event by ID."""
        other_event = await insert_event(
            db_session,
            user_id=OTHER_USER_ID,
            title="Other User's Secret Event",
            raw_text="private data",
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/events/{other_event.id}")
        assert resp.status_code == 404, (
            f"Expected 404 for cross-user event access, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_cross_user_entity_list_isolation(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User A's entity list should not include User B's entities."""
        await insert_entity(db_session, name="My Contact")
        await insert_entity(
            db_session, user_id=OTHER_USER_ID, name="Other User's Contact"
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/entities")
        assert resp.status_code == 200
        names = [e["name"] for e in resp.json()["items"]]
        assert "Other User's Contact" not in names, (
            "User A can see User B's entities — data isolation failure!"
        )

    @pytest.mark.asyncio
    async def test_cross_user_entity_update_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User A cannot update User B's entity."""
        other_entity = await insert_entity(
            db_session, user_id=OTHER_USER_ID, name="Other's Entity"
        )
        await db_session.commit()

        resp = await client.patch(
            f"{API_PREFIX}/entities/{other_entity.id}",
            json={"name": "Hacked Name"},
        )
        assert resp.status_code == 404, (
            f"Expected 404 for cross-user entity update, got {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_cross_user_export_returns_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """User A cannot export User B's data."""
        await insert_event(
            db_session, user_id=OTHER_USER_ID, title="Other User's Data"
        )
        await db_session.commit()

        resp = await client.get(f"{API_PREFIX}/export/{OTHER_USER_ID}")
        assert resp.status_code == 403, (
            f"Expected 403 for cross-user export, got {resp.status_code}."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 6. Input Validation Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0InputValidation:
    """P0-6: Input validation — super long / special chars / null values."""

    @pytest.mark.asyncio
    async def test_super_long_raw_text_rejected(self, client: AsyncClient):
        """Super long raw_text (over 500KB) should be rejected with 400."""
        long_text = "X" * 600000  # 600KB, exceeds 500KB limit
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "test",
                "title": "Long Text Test",
                "raw_text": long_text,
            },
        )
        assert resp.status_code == 400, (
            f"Super long raw_text returned {resp.status_code}. Expected 400."
        )

    @pytest.mark.asyncio
    async def test_missing_required_field_returns_422(self, client: AsyncClient):
        """Missing required field (event_type) should return 422."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={"source": "test", "title": "Test"},
        )
        assert resp.status_code == 422, (
            f"Missing event_type returned {resp.status_code}. Expected 422."
        )

    @pytest.mark.asyncio
    async def test_null_values_in_required_fields(self, client: AsyncClient):
        """Null values for required fields should return 422."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={"event_type": None, "source": "test", "title": "Test"},
        )
        assert resp.status_code == 422, (
            f"Null event_type returned {resp.status_code}. Expected 422."
        )

    @pytest.mark.asyncio
    async def test_invalid_event_type_returns_400(self, client: AsyncClient):
        """Invalid event_type value should return 400."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={"event_type": "invalid_type", "source": "test", "title": "Test"},
        )
        assert resp.status_code == 400, (
            f"Invalid event_type returned {resp.status_code}. Expected 400."
        )

    @pytest.mark.asyncio
    async def test_special_characters_handled(self, client: AsyncClient):
        """Special characters in content should be handled correctly."""
        special_text = "特殊字符测试: <>&\"'\\/\n\t emoji: 🎉🚀💡"
        resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "test",
                "title": "Special Chars Test",
                "raw_text": special_text,
            },
        )
        assert resp.status_code == 201, (
            f"Special characters returned {resp.status_code}. Expected 201."
        )

    @pytest.mark.asyncio
    async def test_malformed_json_returns_error(self, client: AsyncClient):
        """Malformed JSON body should return 422 or 400, not 500."""
        resp = await client.post(
            f"{API_PREFIX}/events",
            content=b'{"event_type": "meeting", "source": "test", INVALID JSON',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422), (
            f"Malformed JSON returned {resp.status_code}. Expected 400 or 422."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 7. Rate Limiting Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0RateLimiting:
    """P0-7: API rate limit enforcement.

    The client fixture overrides get_current_user_id but NOT get_optional_user_id.
    Without an Authorization header, get_optional_user_id returns None, so the
    unauthenticated rate limit (30/minute) applies.
    """

    @pytest.mark.asyncio
    async def test_rate_limit_triggers_after_threshold(self, client: AsyncClient):
        """Rapid requests beyond the unauthenticated limit should return 429."""
        status_codes = []
        for _ in range(40):  # 40 requests, limit is 30
            resp = await client.get(f"{API_PREFIX}/events")
            status_codes.append(resp.status_code)
            if resp.status_code == 429:
                break

        assert 429 in status_codes, (
            f"No rate limiting triggered after {len(status_codes)} requests. "
            f"Status codes: {set(status_codes)}."
        )

    @pytest.mark.asyncio
    async def test_rate_limit_no_500_errors(self, client: AsyncClient):
        """Rapid requests should not cause 500 errors — only 429."""
        status_codes = []
        for _ in range(45):
            resp = await client.get(f"{API_PREFIX}/events")
            status_codes.append(resp.status_code)

        assert 500 not in status_codes, (
            f"500 errors occurred during rate limiting. "
            f"Status codes: {set(status_codes)}"
        )
        for code in status_codes:
            assert code in (200, 429), (
                f"Unexpected status code {code} during rate limiting."
            )


# ══════════════════════════════════════════════════════════════════════════════
# 8. License Activation Security Tests (Gateway)
# ══════════════════════════════════════════════════════════════════════════════


class TestP0LicenseActivationSecurity:
    """P0-8: License activation security — invalid / revoked / bound keys."""

    def test_invalid_license_key_format_rejected(
        self, gateway_client: TestClient, gateway_jwt_handler
    ):
        """License key with invalid format should be rejected with 422."""
        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=make_user_id("invalid-key-test"),
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        invalid_keys = [
            "INVALID-KEY-FORMAT",
            "PL-PRO-AAA-BBB-CCC",  # Too short groups
            "not-a-license-key",
            "'; DROP TABLE licenses; --",
            "../../etc/passwd",
        ]

        for key in invalid_keys:
            resp = gateway_client.post(
                "/api/v1/pro/license/activate",
                json={
                    "license_key": key,
                    "device_fingerprint": make_device_fingerprint("test"),
                },
                headers={
                    "X-API-Key": TEST_API_KEY,
                    "Authorization": f"Bearer {user_jwt}",
                },
            )
            assert resp.status_code == 422, (
                f"Invalid license key {key!r} should return 422, got {resp.status_code}"
            )

    def test_nonexistent_license_rejected(
        self, gateway_client: TestClient, gateway_jwt_handler
    ):
        """Non-existent but valid-format license key should return 404."""
        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=make_user_id("noexist-test"),
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        fake_key = make_license_key("NOSUCHKEY")
        resp = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={
                "license_key": fake_key,
                "device_fingerprint": make_device_fingerprint("test"),
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

    def test_cancelled_license_rejected(
        self, gateway_client: TestClient, gateway_license_store, gateway_jwt_handler
    ):
        """Cancelled (revoked) license should be rejected."""
        license_key = make_license_key("CANCELLED")
        user_id = make_user_id("cancelled-user")
        device_fp = make_device_fingerprint("cancelled-device")

        lic = make_license(license_key, status="cancelled")
        gateway_license_store[license_key] = lic

        user_jwt = gateway_jwt_handler.create_access_token(
            user_id=user_id,
            license_key="",
            plan_type="pro",
            device_fingerprint="",
        )

        resp = gateway_client.post(
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
        assert resp.status_code in (403, 409), (
            f"Cancelled license should be rejected, got {resp.status_code}"
        )

    def test_license_hijacking_rejected(
        self,
        gateway_client: TestClient,
        gateway_license_store,
        gateway_jwt_handler,
    ):
        """A second user cannot activate a license already bound to another user."""
        license_key = make_license_key("HIJACK")
        device_a = make_device_fingerprint("device-a")
        device_b = make_device_fingerprint("device-b")
        user_a = make_user_id("user-a")
        user_b = make_user_id("user-b")

        lic = make_license(license_key, status="active")
        gateway_license_store[license_key] = lic

        # User A activates
        jwt_a = gateway_jwt_handler.create_access_token(
            user_id=user_a, license_key="", plan_type="pro", device_fingerprint=""
        )
        resp_a = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": license_key, "device_fingerprint": device_a},
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {jwt_a}",
            },
        )
        assert resp_a.status_code == 200, (
            f"User A activation should succeed, got {resp_a.status_code}"
        )

        # User B tries to hijack
        jwt_b = gateway_jwt_handler.create_access_token(
            user_id=user_b, license_key="", plan_type="pro", device_fingerprint=""
        )
        resp_b = gateway_client.post(
            "/api/v1/pro/license/activate",
            json={"license_key": license_key, "device_fingerprint": device_b},
            headers={
                "X-API-Key": TEST_API_KEY,
                "Authorization": f"Bearer {jwt_b}",
            },
        )
        assert resp_b.status_code == 409, (
            f"User B hijack should be rejected with 409, got {resp_b.status_code}"
        )
        assert resp_b.json()["error"]["code"] == "LICENSE_ALREADY_ACTIVATED"


# ══════════════════════════════════════════════════════════════════════════════
# 9. Admin API Authentication Tests (Gateway)
# ══════════════════════════════════════════════════════════════════════════════


class TestP0AdminAPIAuth:
    """P0-9: Admin API authentication — no admin key / wrong admin key."""

    def test_no_admin_key_rejected(self, gateway_client: TestClient, gateway_settings):
        """Admin endpoint without X-Admin-API-Key header should return 401."""
        admin_jwt = make_admin_jwt(gateway_settings)
        resp = gateway_client.get(
            "/api/v1/admin/usage/summary",
            headers={"Authorization": f"Bearer {admin_jwt}"},
        )
        assert resp.status_code == 401, (
            f"Missing admin key should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_wrong_admin_key_rejected(self, gateway_client: TestClient, gateway_settings):
        """Admin endpoint with wrong X-Admin-API-Key should return 401."""
        admin_jwt = make_admin_jwt(gateway_settings)
        resp = gateway_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": "wrong-admin-key-xxxxxxxxxxxxxxxxxxx",
                "Authorization": f"Bearer {admin_jwt}",
            },
        )
        assert resp.status_code == 401, (
            f"Wrong admin key should be rejected, got {resp.status_code}"
        )
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_no_admin_jwt_rejected(self, gateway_client: TestClient, gateway_settings):
        """Admin endpoint without admin JWT should return 401."""
        resp = gateway_client.get(
            "/api/v1/admin/usage/summary",
            headers={"X-Admin-API-Key": gateway_settings.admin_api_key},
        )
        assert resp.status_code == 401, (
            f"Missing admin JWT should be rejected, got {resp.status_code}"
        )

    def test_wrong_admin_jwt_rejected(self, gateway_client: TestClient, gateway_settings):
        """Admin endpoint with wrong admin JWT should return 401."""
        # Create a JWT signed with the wrong secret
        now = int(time.time())
        payload = {
            "admin_id": "attacker",
            "role": "admin",
            "iat": now,
            "exp": now + 3600,
            "iss": "promiselink-gateway-admin",
            "aud": "promiselink-admin-client",
        }
        wrong_jwt = pyjwt.encode(payload, "wrong-admin-secret-key-min-32-chars!", algorithm="HS256")

        resp = gateway_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": gateway_settings.admin_api_key,
                "Authorization": f"Bearer {wrong_jwt}",
            },
        )
        assert resp.status_code == 401, (
            f"Wrong admin JWT should be rejected, got {resp.status_code}"
        )

    def test_valid_admin_credentials_accepted(
        self, gateway_client: TestClient, gateway_settings
    ):
        """Valid admin API key + admin JWT should return 200."""
        admin_jwt = make_admin_jwt(gateway_settings)
        resp = gateway_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": gateway_settings.admin_api_key,
                "Authorization": f"Bearer {admin_jwt}",
            },
        )
        assert resp.status_code == 200, (
            f"Valid admin credentials should be accepted, got {resp.status_code}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 10. Relay Client Degradation Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestP0RelayClientDegradation:
    """P0-10: Relay client — invalid JWT / gateway unreachable degradation.

    Tests the RelayClient class directly with mocked HTTP to verify
    graceful degradation when the gateway is unreachable or returns auth errors.
    """

    @pytest.mark.asyncio
    async def test_invalid_jwt_raises_auth_error(self):
        """RelayClient with an invalid JWT should raise RelayAuthError."""
        from promiselink.services.relay_client import RelayAuthError, RelayClient

        # Mock transport returns 401 for all requests
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=401,
                json={"error": {"code": "JWT_INVALID", "message": "Invalid token"}},
            )

        transport = httpx.MockTransport(handler)
        client = RelayClient(
            gateway_url="https://gateway.test",
            license_key="PL-PRO-TEST-KEY-001",
            user_token="invalid.jwt.token",
        )
        # Inject mock transport
        client._client = httpx.AsyncClient(transport=transport)

        try:
            with pytest.raises(RelayAuthError):
                await client.chat_completion(
                    messages=[{"role": "user", "content": "test"}],
                    stream=False,
                )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_gateway_unreachable_raises_unavailable_error(self):
        """RelayClient should raise RelayUnavailableError when gateway is unreachable."""
        from promiselink.services.relay_client import RelayClient, RelayUnavailableError

        # Mock transport that simulates network error
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = RelayClient(
            gateway_url="https://gateway.test",
            license_key="PL-PRO-TEST-KEY-002",
            timeout=5,
            max_retries=1,
        )
        client._client = httpx.AsyncClient(transport=transport)

        try:
            with pytest.raises(RelayUnavailableError):
                await client.chat_completion(
                    messages=[{"role": "user", "content": "test"}],
                    stream=False,
                )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_unreachable(self):
        """RelayClient.health_check should return False when gateway is unreachable."""
        from promiselink.services.relay_client import RelayClient

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        transport = httpx.MockTransport(handler)
        client = RelayClient(
            gateway_url="https://gateway.test",
            license_key="PL-PRO-TEST-KEY-003",
        )
        client._client = httpx.AsyncClient(transport=transport)

        try:
            result = await client.health_check()
            assert result is False, (
                "health_check should return False when gateway is unreachable"
            )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_200(self):
        """RelayClient.health_check should return True when gateway responds 200."""
        from promiselink.services.relay_client import RelayClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=200, json={"status": "healthy"})

        transport = httpx.MockTransport(handler)
        client = RelayClient(
            gateway_url="https://gateway.test",
            license_key="PL-PRO-TEST-KEY-004",
        )
        client._client = httpx.AsyncClient(transport=transport)

        try:
            result = await client.health_check()
            assert result is True, (
                "health_check should return True when gateway responds 200"
            )
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_token_refresh_on_401(self):
        """RelayClient should attempt token refresh on 401 before giving up."""
        from promiselink.services.relay_client import RelayAuthError, RelayClient

        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # Always return 401 to simulate persistent auth failure
            return httpx.Response(
                status_code=401,
                json={"error": {"code": "JWT_INVALID", "message": "Token expired"}},
            )

        transport = httpx.MockTransport(handler)
        client = RelayClient(
            gateway_url="https://gateway.test",
            license_key="PL-PRO-TEST-KEY-005",
            user_token="expired.token",
            max_retries=2,
        )
        client._client = httpx.AsyncClient(transport=transport)

        try:
            with pytest.raises(RelayAuthError):
                await client.chat_completion(
                    messages=[{"role": "user", "content": "test"}],
                    stream=False,
                )
            # Should have attempted at least 2 HTTP calls (original + retry after refresh)
            assert call_count >= 2, (
                f"Expected at least 2 HTTP calls (retry after refresh), got {call_count}"
            )
        finally:
            await client.close()

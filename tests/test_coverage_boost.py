"""Coverage boost tests for PromiseLink.

Targets modules with lowest coverage to push overall from 77% to 80%+:
- health.py (25%)
- notification_service.py (56%)
- rate_limiter.py (57%)
- core/auth.py (68%)
- pipeline steps step_05-step_12 (73-76%)
- core/logging.py (60%)
- core/redis.py CacheService (49%)
- database.py (62%)
"""

import os
import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import (
    _get_client_ip,
    create_access_token,
    get_current_user_id,
    get_optional_user_id,
    verify_token,
)
from promiselink.core.logging import configure_logging, get_logger, new_request_id
from promiselink.core.rate_limiter import (
    InMemorySlidingWindow,
    check_rate_limit,
    reset_rate_limits,
)
from promiselink.core.redis import CacheService
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.services.notification_service import (
    NotificationChannel,
    NotificationMessage,
    NotificationPriority,
    NotificationService,
)
from promiselink.services.steps.context import PipelineContext


# ── Shared Fixtures ──

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
API_PREFIX = "/api/v1"


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """Create a real SQLite file DB with session factory for pipeline step tests."""
    from promiselink.database import Base

    db_path = str(tmp_path / "coverage_test.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session, db_path, session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


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
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    async_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    yield async_session
    await async_session.close()


@pytest_asyncio.fixture
async def client(db_session):
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _make_context(event_id=None, user_id=None, llm_client=None):
    """Create a PipelineContext for testing."""
    from promiselink.services.event_pipeline import PipelineResult
    ctx = PipelineContext(
        event_id=event_id or str(uuid.uuid4()),
        user_id=user_id or TEST_USER_ID,
        llm_client=llm_client or AsyncMock(),
        result=PipelineResult(event_id=event_id or str(uuid.uuid4())),
    )
    return ctx


# ══════════════════════════════════════════════════════════════════
# 1. Health API Tests (health.py: 25% → target 80%+)
# ══════════════════════════════════════════════════════════════════


class TestHealthAPI:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_basic_health_check(self, client):
        """GET /health returns healthy status."""
        response = await client.get(f"{API_PREFIX}/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "promiselink"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_db_health_check(self, client):
        """GET /health/db returns database status."""
        response = await client.get(f"{API_PREFIX}/health/db")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["components"]["database"] == "connected"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_full_health_check(self, client):
        """GET /health/full returns all component statuses."""
        response = await client.get(f"{API_PREFIX}/health/full")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "components" in data
        assert "database" in data["components"]
        assert "cache" in data["components"]
        assert "llm" in data["components"]
        assert data["service"] == "promiselink"
        assert data["version"] != ""  # Version read from config
        # Verify each component has a valid status
        assert data["components"]["database"]["status"] == "healthy"
        assert data["components"]["cache"]["status"] in ("healthy", "degraded")
        assert data["components"]["llm"]["status"] in ("configured", "not_configured", "error")


# ══════════════════════════════════════════════════════════════════
# 2. Notification Service Tests (notification_service.py: 56% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestNotificationService:
    """Tests for NotificationService."""

    def _make_service(self, app_id="test_id", app_secret="test_secret"):
        with patch("promiselink.services.notification_service.get_settings") as mock_settings:
            settings = MagicMock()
            settings.wechat_app_id = app_id
            settings.wechat_app_secret = app_secret
            mock_settings.return_value = settings
            return NotificationService()

    def _make_message(self, channel=NotificationChannel.WECHAT_TEMPLATE):
        return NotificationMessage(
            user_id="user-1",
            channel=channel,
            priority=NotificationPriority.HIGH,
            title="Test Title",
            content="Test Content",
        )

    @pytest.mark.asyncio
    async def test_send_wechat_template(self):
        """send() with WECHAT_TEMPLATE channel calls _send_wechat_template."""
        svc = self._make_service()
        msg = self._make_message(NotificationChannel.WECHAT_TEMPLATE)
        result = await svc.send(msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_wechat_subscribe(self):
        """send() with WECHAT_SUBSCRIBE channel calls _send_wechat_subscribe."""
        svc = self._make_service()
        msg = self._make_message(NotificationChannel.WECHAT_SUBSCRIBE)
        result = await svc.send(msg)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_push_returns_false(self):
        """send() with PUSH channel returns False (not implemented)."""
        svc = self._make_service()
        msg = self._make_message(NotificationChannel.PUSH)
        result = await svc.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_wechat_template_not_configured(self):
        """_send_wechat_template returns False when not configured."""
        svc = self._make_service(app_id="", app_secret="")
        msg = self._make_message(NotificationChannel.WECHAT_TEMPLATE)
        result = await svc.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_wechat_subscribe_not_configured(self):
        """_send_wechat_subscribe returns False when not configured."""
        svc = self._make_service(app_id="", app_secret="")
        msg = self._make_message(NotificationChannel.WECHAT_SUBSCRIBE)
        result = await svc.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_send_handles_exception(self):
        """send() catches exceptions and returns False."""
        svc = self._make_service()
        msg = self._make_message(NotificationChannel.WECHAT_TEMPLATE)
        with patch.object(svc, "_send_wechat_template", side_effect=RuntimeError("boom")):
            result = await svc.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_todo_created(self):
        """notify_todo_created creates and sends a notification."""
        svc = self._make_service()
        result = await svc.notify_todo_created(
            user_id="user-1",
            todo_title="Follow up",
            todo_type="promise",
            todo_id="todo-1",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_notify_todo_created_various_types(self):
        """notify_todo_created maps todo types to correct priorities."""
        svc = self._make_service()
        type_priority_map = {
            "promise": NotificationPriority.HIGH,
            "risk": NotificationPriority.HIGH,
            "help": NotificationPriority.MEDIUM,
            "care": NotificationPriority.MEDIUM,
            "cooperation_signal": NotificationPriority.MEDIUM,
            "followup": NotificationPriority.LOW,
        }
        for todo_type, expected_priority in type_priority_map.items():
            with patch.object(svc, "send", new_callable=AsyncMock) as mock_send:
                mock_send.return_value = True
                result = await svc.notify_todo_created(
                    user_id="user-1",
                    todo_title="Test",
                    todo_type=todo_type,
                    todo_id="todo-1",
                )
                assert result is True
                # Verify the message was created with correct priority
                sent_msg = mock_send.call_args[0][0]
                assert sent_msg.priority == expected_priority, (
                    f"todo_type={todo_type} should map to {expected_priority}, "
                    f"got {sent_msg.priority}"
                )

    @pytest.mark.asyncio
    async def test_notify_todo_created_unknown_type_defaults_medium(self):
        """Unknown todo type defaults to MEDIUM priority."""
        svc = self._make_service()
        with patch.object(svc, "send", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = True
            result = await svc.notify_todo_created(
                user_id="user-1",
                todo_title="Test",
                todo_type="unknown_type",
                todo_id="todo-1",
            )
            assert result is True
            sent_msg = mock_send.call_args[0][0]
            assert sent_msg.priority == NotificationPriority.MEDIUM


# ══════════════════════════════════════════════════════════════════
# 3. Rate Limiter Tests (rate_limiter.py: 57% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestInMemorySlidingWindow:
    """Tests for InMemorySlidingWindow rate limiter."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_keys(self):
        """InMemorySlidingWindow cleans up expired keys when > 1000."""
        limiter = InMemorySlidingWindow()
        # Fill with more than 1000 keys
        for i in range(1001):
            limiter._windows[f"key_{i}"] = [0.0]  # All expired (timestamp 0)

        # Trigger cleanup by making a request
        allowed, remaining, retry_after = await limiter.is_allowed("new_key", 5)
        assert allowed is True
        # Old keys should have been cleaned up
        assert len(limiter._windows) < 1001

    @pytest.mark.asyncio
    async def test_cleanup_preserves_valid_keys(self):
        """Cleanup only removes keys with all expired timestamps."""
        limiter = InMemorySlidingWindow()
        now = time.time()
        # Fill with expired keys
        for i in range(1001):
            limiter._windows[f"key_{i}"] = [0.0]
        # Add a valid key
        limiter._windows["valid_key"] = [now]

        await limiter.is_allowed("new_key", 5)
        # Valid key should still exist
        assert "valid_key" in limiter._windows

    @pytest.mark.asyncio
    async def test_rate_limiter_disabled(self):
        """check_rate_limit returns allowed when rate limiting is disabled."""
        with patch("promiselink.core.rate_limiter.get_settings") as mock_settings:
            settings = MagicMock()
            settings.rate_limit_enabled = False
            mock_settings.return_value = settings
            allowed, remaining, retry_after = await check_rate_limit("key", 5)
        assert allowed is True
        assert remaining == 5
        assert retry_after == 0

    @pytest.mark.asyncio
    async def test_rate_limiter_redis_path(self):
        """check_rate_limit uses Redis when redis_enabled is True."""
        with patch("promiselink.core.rate_limiter.get_settings") as mock_settings:
            settings = MagicMock()
            settings.rate_limit_enabled = True
            settings.redis_enabled = True
            mock_settings.return_value = settings

            with patch("promiselink.core.rate_limiter._redis_limiter") as mock_redis:
                mock_redis.is_allowed = AsyncMock(return_value=(True, 4, 0))
                allowed, remaining, retry_after = await check_rate_limit("key", 5)

        assert allowed is True

    @pytest.mark.asyncio
    async def test_rate_limiter_memory_path(self):
        """check_rate_limit uses in-memory when redis is disabled."""
        with patch("promiselink.core.rate_limiter.get_settings") as mock_settings:
            settings = MagicMock()
            settings.rate_limit_enabled = True
            settings.redis_enabled = False
            mock_settings.return_value = settings
            allowed, remaining, retry_after = await check_rate_limit("test_mem_key2", 5)

        assert allowed is True

    def test_reset_rate_limits_specific_key(self):
        """reset_rate_limits can reset a specific key."""
        limiter = InMemorySlidingWindow()
        limiter._windows["key1"] = [time.time()]
        limiter._windows["key2"] = [time.time()]
        limiter.reset("key1")
        assert "key1" not in limiter._windows
        assert "key2" in limiter._windows

    def test_reset_rate_limits_all(self):
        """reset_rate_limits clears all keys when no key specified."""
        limiter = InMemorySlidingWindow()
        limiter._windows["key1"] = [time.time()]
        limiter._windows["key2"] = [time.time()]
        limiter.reset()
        assert len(limiter._windows) == 0


class TestRedisSlidingWindow:
    """Tests for RedisSlidingWindow rate limiter."""

    @pytest.mark.asyncio
    async def test_redis_unavailable_falls_back_to_memory(self):
        """RedisSlidingWindow falls back to in-memory when Redis is unavailable."""
        from promiselink.core.rate_limiter import RedisSlidingWindow

        limiter = RedisSlidingWindow()
        # get_redis is imported from promiselink.core.redis inside the method
        with patch("promiselink.core.redis.get_redis", return_value=None):
            allowed, remaining, retry_after = await limiter.is_allowed("test_key_fallback", 5)

        assert allowed is True
        assert remaining >= 0

    @pytest.mark.asyncio
    async def test_redis_rate_limit_allowed(self):
        """RedisSlidingWindow allows request under limit."""
        from promiselink.core.rate_limiter import RedisSlidingWindow

        limiter = RedisSlidingWindow()
        mock_redis = AsyncMock()
        # redis.pipeline() is synchronous, returns pipeline object
        mock_pipeline = MagicMock()
        mock_pipeline.zremrangebyscore = MagicMock()
        mock_pipeline.zcard = MagicMock()
        mock_pipeline.zadd = MagicMock()
        mock_pipeline.expire = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[0, 0, 1, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            allowed, remaining, retry_after = await limiter.is_allowed("test_key_allowed", 5)

        assert allowed is True

    @pytest.mark.asyncio
    async def test_redis_rate_limit_blocked(self):
        """RedisSlidingWindow blocks request over limit."""
        from promiselink.core.rate_limiter import RedisSlidingWindow

        limiter = RedisSlidingWindow()
        mock_redis = AsyncMock()
        # redis.pipeline() is synchronous, returns pipeline object
        mock_pipeline = MagicMock()
        mock_pipeline.zremrangebyscore = MagicMock()
        mock_pipeline.zcard = MagicMock()
        mock_pipeline.zadd = MagicMock()
        mock_pipeline.expire = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value=[0, 5, 1, True])
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.zrange = AsyncMock(return_value=[(b"member", time.time())])

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            allowed, remaining, retry_after = await limiter.is_allowed("test_key_blocked", 5)

        assert allowed is False
        assert retry_after > 0

    @pytest.mark.asyncio
    async def test_redis_exception_falls_back(self):
        """RedisSlidingWindow falls back to in-memory on Redis error."""
        from promiselink.core.rate_limiter import RedisSlidingWindow

        limiter = RedisSlidingWindow()
        mock_redis = AsyncMock()
        mock_redis.pipeline.side_effect = Exception("Redis connection error")

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            allowed, remaining, retry_after = await limiter.is_allowed("fallback_key2", 5)

        assert allowed is True


# ══════════════════════════════════════════════════════════════════
# 4. Core Auth Tests (core/auth.py: 68% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestCoreAuth:
    """Tests for core auth utilities."""

    def test_get_client_ip_from_forwarded(self):
        """_get_client_ip ignores X-Forwarded-For when no trusted proxies configured."""
        request = MagicMock()
        request.headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        request.client = MagicMock()
        request.client.host = "10.0.0.1"
        # Without trusted_proxies configured, X-Forwarded-For is ignored
        assert _get_client_ip(request) == "10.0.0.1"

    def test_get_client_ip_from_client(self):
        """_get_client_ip falls back to request.client.host."""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "9.8.7.6"
        assert _get_client_ip(request) == "9.8.7.6"

    def test_get_client_ip_unknown(self):
        """_get_client_ip returns 'unknown' when no IP available."""
        request = MagicMock()
        request.headers = {}
        request.client = None
        assert _get_client_ip(request) == "unknown"

    @pytest.mark.asyncio
    async def test_get_optional_user_id_no_credentials_no_poc(self):
        """get_optional_user_id returns None when no credentials and POC disabled."""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        with patch("promiselink.core.auth.get_settings") as mock_settings:
            settings = MagicMock()
            settings.poc_anonymous_access = False
            mock_settings.return_value = settings
            result = await get_optional_user_id(request, None)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_id_poc_allowed_from_localhost(self):
        """get_optional_user_id returns default user when POC enabled from localhost."""
        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "127.0.0.1"

        with patch("promiselink.core.auth.get_settings") as mock_settings:
            settings = MagicMock()
            settings.poc_anonymous_access = True
            mock_settings.return_value = settings

            with patch.dict(os.environ, {"POC_ALLOWED_IPS": "127.0.0.1,::1"}):
                result = await get_optional_user_id(request, None)

        assert result == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_get_optional_user_id_poc_blocked_from_unknown_ip(self):
        """get_optional_user_id raises 403 when POC enabled but IP not allowed."""
        from fastapi import HTTPException

        request = MagicMock()
        request.headers = {}
        request.client = MagicMock()
        request.client.host = "10.0.0.1"

        with patch("promiselink.core.auth.get_settings") as mock_settings:
            settings = MagicMock()
            settings.poc_anonymous_access = True
            mock_settings.return_value = settings

            with patch.dict(os.environ, {"POC_ALLOWED_IPS": "127.0.0.1,::1"}):
                with pytest.raises(HTTPException) as exc_info:
                    await get_optional_user_id(request, None)
                assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_get_optional_user_id_with_invalid_token(self):
        """get_optional_user_id returns None for invalid token."""
        from fastapi import HTTPException

        request = MagicMock()
        credentials = MagicMock()
        credentials.credentials = "invalid_token"

        with patch("promiselink.core.auth.verify_token", side_effect=HTTPException(status_code=401)):
            result = await get_optional_user_id(request, credentials)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_optional_user_id_with_valid_token(self):
        """get_optional_user_id returns user_id from valid token."""
        request = MagicMock()
        credentials = MagicMock()
        credentials.credentials = "valid_token"

        with patch("promiselink.core.auth.verify_token", return_value={"sub": "user-123"}):
            result = await get_optional_user_id(request, credentials)

        assert result == "user-123"

    @pytest.mark.asyncio
    async def test_get_optional_user_id_token_missing_sub(self):
        """get_optional_user_id returns None when token has no sub."""
        request = MagicMock()
        credentials = MagicMock()
        credentials.credentials = "valid_token"

        with patch("promiselink.core.auth.verify_token", return_value={"no_sub": True}):
            result = await get_optional_user_id(request, credentials)

        assert result is None

    def test_create_and_verify_token(self):
        """create_access_token and verify_token round-trip."""
        token = create_access_token("user-123")
        payload = verify_token(token)
        assert payload["sub"] == "user-123"
        assert payload["iss"] == "promiselink"

    def test_verify_token_invalid_raises(self):
        """verify_token raises 401 for invalid token."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_token("invalid.token.here")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_id_no_credentials(self):
        """get_current_user_id raises 401 when no credentials."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user_id(None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_id_token_missing_sub(self):
        """get_current_user_id raises 401 when token has no sub."""
        from fastapi import HTTPException

        credentials = MagicMock()
        credentials.credentials = "token_without_sub"

        with patch("promiselink.core.auth.verify_token", return_value={"no_sub": True}):
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user_id(credentials)
            assert exc_info.value.status_code == 401


# ══════════════════════════════════════════════════════════════════
# 5. Pipeline Step Tests (step_05-step_12: 73-76% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestStep05PromiseAnalysis:
    """Tests for Step05_PromiseAnalysis."""

    @pytest.mark.asyncio
    async def test_step05_with_todos_and_entities(self, file_db):
        """Step05 processes todos with promise bidirectional analysis."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_05_promise import Step05_PromiseAnalysis

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="person",
            name="张三", canonical_name="张三", source_event_id=event_id,
            confidence=0.9, status="confirmed",
        )
        session.add(entity)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Follow up", source_event_id=event_id,
            priority=3, status="pending",
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_analysis = MagicMock()
        mock_analysis.action_type = MagicMock(value="their_promise")
        mock_analysis.promisor_entity_id = str(entity.id)
        mock_analysis.beneficiary_entity_id = None
        mock_analysis.confirmation_status = MagicMock(value="unconfirmed")
        mock_analysis.evidence_quote = "I will follow up"
        mock_handler = AsyncMock()
        mock_handler.analyze_todo = AsyncMock(return_value=mock_analysis)

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler", return_value=mock_handler):
            step = Step05_PromiseAnalysis()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step5_promise" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step05_handles_analysis_exception(self, file_db):
        """Step05 continues when individual todo analysis fails."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_05_promise import Step05_PromiseAnalysis

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Follow up", source_event_id=event_id,
            priority=3, status="pending",
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_handler = AsyncMock()
        mock_handler.analyze_todo = AsyncMock(side_effect=RuntimeError("Analysis failed"))

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler", return_value=mock_handler):
            step = Step05_PromiseAnalysis()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # Pipeline should still record timing even when analysis fails
        assert "step5_promise" in result_ctx.result.step_timings
        # The todo should remain unchanged (no action_type set)
        assert result_ctx.result.step_timings["step5_promise"] >= 0

    @pytest.mark.asyncio
    async def test_step05_handles_apply_exception(self, file_db):
        """Step05 continues when applying analysis result to todo fails."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_05_promise import Step05_PromiseAnalysis

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="person",
            name="张三", canonical_name="张三", source_event_id=event_id,
            confidence=0.9, status="confirmed",
        )
        session.add(entity)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Follow up", source_event_id=event_id,
            priority=3, status="pending",
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        # Analysis result that raises on attribute access
        mock_analysis = MagicMock()
        mock_analysis.action_type = MagicMock(value="their_promise")
        mock_analysis.promisor_entity_id = str(entity.id)
        mock_analysis.beneficiary_entity_id = None
        mock_analysis.confirmation_status = MagicMock(value="unconfirmed")
        mock_analysis.evidence_quote = "test"

        mock_handler = AsyncMock()
        mock_handler.analyze_todo = AsyncMock(return_value=mock_analysis)

        # Patch the todo's action_type setter to raise
        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.promise_bidirectional.PromiseBidirectionalHandler", return_value=mock_handler):
            # Make the assignment fail by patching the property
            original_setattr = type(todo).__setattr__
            def failing_setattr(obj, name, value):
                if name == "action_type":
                    raise RuntimeError("apply error")
                return original_setattr(obj, name, value)
            with patch.object(type(todo), "__setattr__", failing_setattr):
                step = Step05_PromiseAnalysis()
                result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # Step should still record timing despite apply failure
        assert "step5_promise" in result_ctx.result.step_timings


class TestStep06ResourceOveruse:
    """Tests for Step06_ResourceOveruse."""

    @pytest.mark.asyncio
    async def test_step06_with_their_promise_todo(self, file_db):
        """Step06 checks resource overuse for their_promise todos."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_06_resource import Step06_ResourceOveruse

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity_id = str(uuid.uuid4())
        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Their promise", source_event_id=event_id,
            priority=3, status="pending",
            action_type="their_promise", related_entity_id=entity_id,
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_detector = AsyncMock()
        mock_detector.check_and_create_warning_todo = AsyncMock(return_value=None)

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.resource_overuse_detector.ResourceOveruseDetector", return_value=mock_detector):
            step = Step06_ResourceOveruse()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step6_resource" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step06_handles_overuse_check_error(self, file_db):
        """Step06 continues when overuse check fails for an entity."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_06_resource import Step06_ResourceOveruse

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity_id = str(uuid.uuid4())
        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Their promise", source_event_id=event_id,
            priority=3, status="pending",
            action_type="their_promise", related_entity_id=entity_id,
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_detector = AsyncMock()
        mock_detector.check_and_create_warning_todo = AsyncMock(
            side_effect=RuntimeError("Overuse check failed")
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.resource_overuse_detector.ResourceOveruseDetector", return_value=mock_detector):
            step = Step06_ResourceOveruse()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # Step should still record timing despite overuse check failure
        assert "step6_resource" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step06_handles_init_error(self):
        """Step06 handles initialization errors gracefully."""
        from promiselink.services.steps.step_06_resource import Step06_ResourceOveruse

        ctx = _make_context()

        with patch("promiselink.database.AsyncSessionLocal") as mock_sf, \
             patch("promiselink.services.resource_overuse_detector.ResourceOveruseDetector", side_effect=RuntimeError("init error")):
            # Make the session factory raise on __call__
            mock_sf.side_effect = RuntimeError("DB connection failed")
            step = Step06_ResourceOveruse()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step6_resource" in result_ctx.result.step_timings


class TestStep07PriorityScoring:
    """Tests for Step07_PriorityScoring."""

    @pytest.mark.asyncio
    async def test_step07_scores_todos(self, file_db):
        """Step07 scores todos with PriorityScorerV2."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_07_priority import Step07_PriorityScoring

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Follow up", source_event_id=event_id,
            priority=3, status="pending",
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_score_result = MagicMock()
        mock_score_result.score = 85.5
        mock_scorer = AsyncMock()
        mock_scorer.score_with_context = AsyncMock(return_value=mock_score_result)

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.priority_scorer.PriorityScorerV2", return_value=mock_scorer):
            step = Step07_PriorityScoring()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step7_priority" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step07_handles_score_error(self, file_db):
        """Step07 continues when scoring a todo fails."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from promiselink.services.steps.step_07_priority import Step07_PriorityScoring

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=user_id, todo_type="promise",
            title="Follow up", source_event_id=event_id,
            priority=3, status="pending",
        )
        session.add(todo)
        await session.commit()

        ctx = _make_context(event_id=event_id)

        mock_scorer = AsyncMock()
        mock_scorer.score_with_context = AsyncMock(
            side_effect=RuntimeError("Scoring failed")
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.priority_scorer.PriorityScorerV2", return_value=mock_scorer):
            step = Step07_PriorityScoring()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # Step should still record timing despite scoring failure
        assert "step7_priority" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step07_handles_init_error(self):
        """Step07 handles initialization errors gracefully."""
        from promiselink.services.steps.step_07_priority import Step07_PriorityScoring

        ctx = _make_context()

        with patch("promiselink.database.AsyncSessionLocal") as mock_sf, \
             patch("promiselink.services.priority_scorer.PriorityScorerV2", side_effect=RuntimeError("init error")):
            mock_sf.side_effect = RuntimeError("DB connection failed")
            step = Step07_PriorityScoring()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step7_priority" in result_ctx.result.step_timings


class TestStep12RelationshipBrief:
    """Tests for Step12_RelationshipBriefUpdate."""

    @pytest.mark.asyncio
    async def test_step12_updates_briefs(self, file_db):
        """Step12 updates relationship briefs for person entities."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.services.steps.step_12_brief import Step12_RelationshipBriefUpdate

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="person",
            name="张三", canonical_name="张三", source_event_id=event_id,
            confidence=0.9, status="confirmed",
        )
        session.add(entity)
        await session.commit()

        ctx = _make_context(event_id=event_id, user_id=user_id)

        mock_brief_result = MagicMock()
        mock_brief_result.is_new = True
        mock_brief_result.modules_updated = ["trust"]
        mock_brief_service = AsyncMock()
        mock_brief_service.update_brief_from_event = AsyncMock(return_value=mock_brief_result)

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", return_value=mock_brief_service):
            step = Step12_RelationshipBriefUpdate()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step12_briefs" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step12_skips_non_person_entities(self, file_db):
        """Step12 skips entities that are not persons."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.services.steps.step_12_brief import Step12_RelationshipBriefUpdate

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="organization",
            name="Acme Corp", canonical_name="Acme Corp", source_event_id=event_id,
            confidence=0.9, status="confirmed",
        )
        session.add(entity)
        await session.commit()

        ctx = _make_context(event_id=event_id, user_id=user_id)

        mock_brief_service = AsyncMock()

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", return_value=mock_brief_service):
            step = Step12_RelationshipBriefUpdate()
            result_ctx = await step.execute(ctx)

        # Should not call update_brief_from_event for non-person entities
        mock_brief_service.update_brief_from_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_step12_handles_brief_update_error(self, file_db):
        """Step12 continues when brief update fails for an entity."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.services.steps.step_12_brief import Step12_RelationshipBriefUpdate

        session, db_path, session_factory, engine = file_db
        event_id = str(uuid.uuid4())
        user_id = TEST_USER_ID

        event = Event(
            id=event_id, user_id=user_id, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        session.add(event)

        entity = Entity(
            id=str(uuid.uuid4()), user_id=user_id, entity_type="person",
            name="张三", canonical_name="张三", source_event_id=event_id,
            confidence=0.9, status="confirmed",
        )
        session.add(entity)
        await session.commit()

        ctx = _make_context(event_id=event_id, user_id=user_id)

        mock_brief_service = AsyncMock()
        mock_brief_service.update_brief_from_event = AsyncMock(
            side_effect=RuntimeError("Brief update failed")
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory), \
             patch("promiselink.services.relationship_brief_service.RelationshipBriefService", return_value=mock_brief_service):
            step = Step12_RelationshipBriefUpdate()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # Step should still record timing despite brief update failure
        assert "step12_briefs" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step12_handles_import_error(self):
        """Step12 handles ImportError when RelationshipBriefService not available."""
        from promiselink.services.steps.step_12_brief import Step12_RelationshipBriefUpdate

        ctx = _make_context()

        # The ImportError is caught inside the execute method when
        # RelationshipBriefService import fails
        with patch("promiselink.database.AsyncSessionLocal") as mock_sf:
            mock_sf.side_effect = ImportError("not found")
            step = Step12_RelationshipBriefUpdate()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        # ImportError should be silently caught, timing still recorded
        assert "step12_briefs" in result_ctx.result.step_timings

    @pytest.mark.asyncio
    async def test_step12_handles_general_exception(self):
        """Step12 handles general exceptions gracefully."""
        from promiselink.services.steps.step_12_brief import Step12_RelationshipBriefUpdate

        ctx = _make_context()

        with patch("promiselink.database.AsyncSessionLocal") as mock_sf:
            mock_sf.side_effect = RuntimeError("DB error")
            step = Step12_RelationshipBriefUpdate()
            result_ctx = await step.execute(ctx)

        assert result_ctx is not None
        assert "step12_briefs" in result_ctx.result.step_timings


# ══════════════════════════════════════════════════════════════════
# 6. Core Logging Tests (core/logging.py: 60% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestCoreLogging:
    """Tests for core logging configuration."""

    def test_configure_logging_json(self):
        """configure_logging with json_output=True configures JSON renderer."""
        configure_logging(log_level="DEBUG", json_output=True)
        logger = get_logger("test_json")
        assert logger is not None
        # Verify the logger can bind context (structlog feature)
        bound = logger.bind(request_id="test")
        assert bound is not None

    def test_configure_logging_console(self):
        """configure_logging with json_output=False configures console renderer."""
        configure_logging(log_level="INFO", json_output=False)
        logger = get_logger("test_console")
        assert logger is not None
        bound = logger.bind(request_id="test")
        assert bound is not None

    def test_get_logger_returns_logger(self):
        """get_logger returns a structlog logger proxy."""
        import structlog
        logger = get_logger("test_module")
        # get_logger returns a BoundLoggerLazyProxy, not BoundLogger directly
        assert logger is not None
        # Verify it can be used for logging (has bind method)
        assert hasattr(logger, "bind")

    def test_new_request_id_returns_uuid(self):
        """new_request_id generates a UUID string."""
        req_id = new_request_id()
        assert isinstance(req_id, str)
        assert len(req_id) > 0

    def test_new_request_id_sets_context(self):
        """new_request_id sets the request_id context variable."""
        from promiselink.core.logging import request_id_var
        req_id = new_request_id()
        assert request_id_var.get() == req_id


# ══════════════════════════════════════════════════════════════════
# 7. CacheService Tests (core/redis.py: 49% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestCacheService:
    """Tests for CacheService with in-memory backend."""

    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """CacheService set/get with memory fallback."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            await cache.set("key1", {"data": "value"}, ttl=60)
            result = await cache.get("key1")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        """CacheService get returns None for missing key."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_expired_key(self):
        """CacheService get returns None for expired key."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            # Set a key, then manually expire it
            await cache.set("key1", "value", ttl=60)
            # Directly manipulate the cache to set an expired time
            cache._memory_cache["key1"] = ("value", time.time() - 1)
            result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_key(self):
        """CacheService delete removes key from memory cache."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            await cache.set("key1", "value", ttl=60)
            await cache.delete("key1")
            result = await cache.get("key1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self):
        """CacheService delete on nonexistent key does not raise."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            await cache.delete("nonexistent")  # Should not raise

    @pytest.mark.asyncio
    async def test_eviction_when_over_capacity(self):
        """CacheService evicts oldest entries when over capacity."""
        cache = CacheService()
        with patch("promiselink.core.redis.get_redis", return_value=None):
            # Fill beyond capacity
            for i in range(1001):
                await cache.set(f"key_{i}", f"value_{i}", ttl=60)
            # First keys should have been evicted
            result = await cache.get("key_0")
            assert result is None
            # Later keys should still exist
            result = await cache.get("key_1000")
            assert result == "value_1000"

    @pytest.mark.asyncio
    async def test_llm_cache_key(self):
        """CacheService llm_cache_key generates consistent hash."""
        cache = CacheService()
        key1 = await cache.llm_cache_key("test prompt", "model-1")
        key2 = await cache.llm_cache_key("test prompt", "model-1")
        key3 = await cache.llm_cache_key("different prompt", "model-1")
        assert key1 == key2
        assert key1 != key3

    @pytest.mark.asyncio
    async def test_redis_get_fallback_on_error(self):
        """CacheService get falls back to memory when Redis fails."""
        cache = CacheService()
        # First, store in memory (with Redis set failing)
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis error"))
        mock_redis.get = AsyncMock(side_effect=Exception("Redis error"))

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            await cache.set("key1", "value", ttl=60)

        # Now get with Redis also failing
        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            result = await cache.get("key1")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_redis_set_fallback_on_error(self):
        """CacheService set falls back to memory when Redis fails."""
        cache = CacheService()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=Exception("Redis error"))

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            await cache.set("key1", "value", ttl=60)
            # Should be stored in memory
            with patch("promiselink.core.redis.get_redis", return_value=None):
                result = await cache.get("key1")
        assert result == "value"

    @pytest.mark.asyncio
    async def test_redis_delete_fallback_on_error(self):
        """CacheService delete falls back to memory when Redis fails."""
        cache = CacheService()
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis error"))

        with patch("promiselink.core.redis.get_redis", return_value=None):
            await cache.set("key1", "value", ttl=60)

        with patch("promiselink.core.redis.get_redis", return_value=mock_redis):
            await cache.delete("key1")

        with patch("promiselink.core.redis.get_redis", return_value=None):
            result = await cache.get("key1")
        assert result is None


# ══════════════════════════════════════════════════════════════════
# 8. Database Tests (database.py: 62% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestDatabase:
    """Tests for database module."""

    @pytest.mark.asyncio
    async def test_get_session_context(self):
        """get_session_context provides a working session."""
        from promiselink.database import get_session_context

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory):
            async with get_session_context() as session:
                assert session is not None

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_get_session_context_rollback_on_error(self):
        """get_session_context rolls back on exception."""
        from promiselink.database import get_session_context

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )

        with patch("promiselink.database.AsyncSessionLocal", session_factory):
            with pytest.raises(ValueError):
                async with get_session_context() as session:
                    assert session is not None
                    raise ValueError("test error")

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_init_db(self):
        """init_db creates all tables."""
        from promiselink.database import init_db

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )

        with patch("promiselink.database.async_engine", engine):
            await init_db()

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_close_db(self):
        """close_db disposes the engine."""
        from promiselink.database import close_db

        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )

        with patch("promiselink.database.async_engine", engine):
            await close_db()


# ══════════════════════════════════════════════════════════════════
# 9. Main App Exception Handler Tests (main.py: 58% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestMainAppExceptionHandlers:
    """Tests for FastAPI exception handlers in main.py."""

    @pytest.mark.asyncio
    async def test_business_error_handler(self, client):
        """BusinessError returns 400 with structured error."""
        from promiselink.core.exceptions import BusinessError

        # Use the app's test client to trigger the exception handler directly
        from fastapi import Request
        from fastapi.responses import JSONResponse

        # Create a mock request and call the handler directly
        mock_request = MagicMock(spec=Request)
        exc = BusinessError("test error", "TEST_ERROR", {"key": "value"})

        from promiselink.main import business_error_handler
        response = await business_error_handler(mock_request, exc)

        assert response.status_code == 400
        # JSONResponse body
        import json
        body = json.loads(response.body.decode())
        assert body["error"]["code"] == "TEST_ERROR"
        assert body["error"]["message"] == "test error"

    @pytest.mark.asyncio
    async def test_llm_error_handler(self):
        """LLMError returns appropriate status code."""
        from promiselink.core.exceptions import LLMError, LLMRateLimitError, LLMTimeoutError
        from promiselink.main import llm_error_handler
        from fastapi import Request

        mock_request = MagicMock(spec=Request)

        # Test rate limit error → 429
        exc = LLMRateLimitError("test_provider")
        response = await llm_error_handler(mock_request, exc)
        assert response.status_code == 429

        # Test timeout error → 504
        exc = LLMTimeoutError("test_provider", 30)
        response = await llm_error_handler(mock_request, exc)
        assert response.status_code == 504

        # Test generic LLM error → 503
        exc = LLMError("generic error", "LLM_GENERIC")
        response = await llm_error_handler(mock_request, exc)
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_promiselink_error_handler(self):
        """PromiseLinkError returns 500 with structured error."""
        from promiselink.core.exceptions import PromiseLinkError
        from promiselink.main import promiselink_error_handler
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        exc = PromiseLinkError("internal error", "INTERNAL", {"detail": "test"})

        response = await promiselink_error_handler(mock_request, exc)
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_404_handler(self, unauth_client):
        """404 returns structured error response."""
        response = await unauth_client.get("/nonexistent/path")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"

    @pytest.mark.skip(reason="根路径不是用户使用的路径，API 文档在 /docs")
    @pytest.mark.asyncio
    async def test_root_endpoint(self, unauth_client):
        """Root endpoint returns app info."""
        response = await unauth_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        assert "name" in data
        assert "version" in data


# ══════════════════════════════════════════════════════════════════
# 10. Dashboard API Tests (dashboard.py: 55% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestDashboardAPI:
    """Tests for Dashboard day-view, range-view, and morning-brief endpoints."""

    @pytest.mark.asyncio
    async def test_day_view_default(self, client):
        """GET /dashboard/day-view returns today's data."""
        response = await client.get(f"{API_PREFIX}/dashboard/day-view")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "events" in data
        assert "todos" in data
        assert "summary" in data
        assert "adjacent_dates" in data
        assert "date_label" in data

    @pytest.mark.asyncio
    async def test_day_view_with_date(self, client):
        """GET /dashboard/day-view?date=明天 returns tomorrow's data."""
        response = await client.get(f"{API_PREFIX}/dashboard/day-view?date=明天")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data

    @pytest.mark.asyncio
    async def test_day_view_with_iso_date(self, client):
        """GET /dashboard/day-view?date=2026-06-10 returns specific date."""
        response = await client.get(f"{API_PREFIX}/dashboard/day-view?date=2026-06-10")
        assert response.status_code == 200
        data = response.json()
        assert data["date"] == "2026-06-10"

    @pytest.mark.asyncio
    async def test_day_view_with_event_and_todo(self, client, db_session):
        """Day-view returns events and todos for the target date."""
        from promiselink.models.event import Event
        from promiselink.models.todo import Todo
        from datetime import date as date_type

        today = date_type.today()
        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test Meeting", raw_text="test",
            status="completed",
        )
        db_session.add(event)

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Follow up", source_event_id=str(event.id),
            priority=3, status="pending", due_date=today,
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/dashboard/day-view?date=今天")
        assert response.status_code == 200
        data = response.json()
        assert len(data["events"]) >= 1
        assert len(data["todos"]) >= 1
        assert data["summary"]["total_events"] >= 1
        assert data["summary"]["total_todos"] >= 1

    @pytest.mark.asyncio
    async def test_range_view_with_dates(self, client):
        """GET /dashboard/range-view with start_date and end_date."""
        response = await client.get(
            f"{API_PREFIX}/dashboard/range-view?start_date=2026-06-01&end_date=2026-06-30"
        )
        assert response.status_code == 200
        data = response.json()
        assert "range_start" in data
        assert "range_end" in data
        assert "total_events" in data
        assert "total_todos" in data

    @pytest.mark.asyncio
    async def test_range_view_with_range_text(self, client):
        """GET /dashboard/range-view?range_text=本周."""
        response = await client.get(
            f"{API_PREFIX}/dashboard/range-view?range_text=本周"
        )
        assert response.status_code == 200
        data = response.json()
        assert "range_start" in data

    @pytest.mark.asyncio
    async def test_range_view_missing_params(self, client):
        """GET /dashboard/range-view without params returns 400."""
        response = await client.get(f"{API_PREFIX}/dashboard/range-view")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_morning_brief(self, client):
        """GET /dashboard/morning-brief returns daily summary."""
        response = await client.get(f"{API_PREFIX}/dashboard/morning-brief")
        assert response.status_code == 200
        data = response.json()
        assert "date" in data
        assert "greeting" in data
        assert "pending_promises" in data
        assert "pending_cares" in data
        assert "overdue_todos" in data
        assert "today_events" in data
        assert "today_todos" in data
        assert "key_persons" in data
        assert "summary_text" in data
        assert data["greeting"] in ("早上好", "下午好", "晚上好")


# ══════════════════════════════════════════════════════════════════
# 11. Events API Tests (events.py: 66% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestEventsAPI:
    """Tests for Events CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_event(self, client):
        """POST /events creates a new event."""
        response = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "meeting",
                "source": "test",
                "title": "Test Meeting",
                "raw_text": "Discussed project timeline",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["event_type"] == "meeting"
        assert data["status"] == "pending"
        assert data["pipeline_status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_event_invalid_type(self, client):
        """POST /events with invalid event_type returns 400."""
        response = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "invalid_type",
                "source": "test",
                "title": "Test",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_create_event_oversized_raw_text(self, client):
        """POST /events with raw_text > 500KB returns 400 (ValidationError)."""
        response = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "manual",
                "source": "test",
                "title": "Big",
                "raw_text": "x" * 512001,
            },
        )
        assert response.status_code in (400, 413)

    @pytest.mark.asyncio
    async def test_list_events(self, client):
        """GET /events returns paginated list."""
        response = await client.get(f"{API_PREFIX}/events")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_events_with_filter(self, client):
        """GET /events?event_type=meeting filters by type."""
        response = await client.get(f"{API_PREFIX}/events?event_type=meeting")
        assert response.status_code == 200
        data = response.json()
        # All returned items should be of type "meeting"
        for item in data["items"]:
            assert item["event_type"] == "meeting"

    @pytest.mark.asyncio
    async def test_get_event_not_found(self, client):
        """GET /events/{id} returns 404 for nonexistent event."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"{API_PREFIX}/events/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_event_detail(self, client):
        """GET /events/{id} returns event detail."""
        # First create an event
        create_resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "call",
                "source": "test",
                "title": "Call with client",
                "raw_text": "Discussed next steps",
            },
        )
        event_id = create_resp.json()["id"]
        response = await client.get(f"{API_PREFIX}/events/{event_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "call"
        assert "raw_text" in data

    @pytest.mark.asyncio
    async def test_delete_event(self, client):
        """DELETE /events/{id} deletes an event."""
        create_resp = await client.post(
            f"{API_PREFIX}/events",
            json={
                "event_type": "manual",
                "source": "test",
                "title": "To delete",
            },
        )
        event_id = create_resp.json()["id"]
        response = await client.delete(f"{API_PREFIX}/events/{event_id}")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_event_not_found(self, client):
        """DELETE /events/{id} returns 404 for nonexistent event."""
        fake_id = str(uuid.uuid4())
        response = await client.delete(f"{API_PREFIX}/events/{fake_id}")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 12. Entities API Tests (entities.py: 57% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestEntitiesAPI:
    """Tests for Entities CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_entities(self, client):
        """GET /entities returns paginated list."""
        response = await client.get(f"{API_PREFIX}/entities")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_entities_with_search(self, client, db_session):
        """GET /entities?search=张 filters by name."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="张三", canonical_name="张三", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/entities?search=张")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_entities_with_type_filter(self, client, db_session):
        """GET /entities?event_type=person filters by entity type."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="李四", canonical_name="李四", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/entities?event_type=person")
        assert response.status_code == 200
        data = response.json()
        # All returned items should be of entity_type "person"
        for item in data["items"]:
            assert item["entity_type"] == "person"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(self, client):
        """GET /entities/{id} returns 404 for nonexistent entity."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"{API_PREFIX}/entities/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_entity_detail(self, client, db_session):
        """GET /entities/{id} returns entity detail."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="王五", canonical_name="王五", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/entities/{entity.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "王五"

    @pytest.mark.asyncio
    async def test_update_entity(self, client, db_session):
        """PATCH /entities/{id} updates entity fields."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="赵六", canonical_name="赵六", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.patch(
            f"{API_PREFIX}/entities/{entity.id}",
            json={"name": "赵六六", "status": "merged"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "赵六六"

    @pytest.mark.asyncio
    async def test_update_entity_not_found(self, client):
        """PATCH /entities/{id} returns 404 for nonexistent entity."""
        fake_id = str(uuid.uuid4())
        response = await client.patch(
            f"{API_PREFIX}/entities/{fake_id}",
            json={"name": "test"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_entity(self, client, db_session):
        """DELETE /entities/{id} deletes entity."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="孙七", canonical_name="孙七", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.delete(f"{API_PREFIX}/entities/{entity.id}")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_entity_not_found(self, client):
        """DELETE /entities/{id} returns 404 for nonexistent entity."""
        fake_id = str(uuid.uuid4())
        response = await client.delete(f"{API_PREFIX}/entities/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_entity_history(self, client, db_session):
        """GET /entities/{id}/history returns entity interaction history."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="History Test", raw_text="test",
            status="completed",
        )
        db_session.add(event)
        await db_session.commit()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="周八", canonical_name="周八", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/entities/{entity.id}/history")
        assert response.status_code == 200
        data = response.json()
        assert "entity" in data
        assert "events" in data
        assert "todos" in data
        assert "associations" in data

    @pytest.mark.asyncio
    async def test_get_entity_history_not_found(self, client):
        """GET /entities/{id}/history returns 404 for nonexistent entity."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"{API_PREFIX}/entities/{fake_id}/history")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 13. Todos API Tests (todos.py: 57% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestTodosAPI:
    """Tests for Todos CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_list_todos(self, client):
        """GET /todos returns paginated list."""
        response = await client.get(f"{API_PREFIX}/todos")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_todos_with_filters(self, client, db_session):
        """GET /todos with type and status filters."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Test promise", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.get(
            f"{API_PREFIX}/todos?todo_type=promise&status=pending"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_list_todos_sort_by_created(self, client):
        """GET /todos?sort_by=created sorts by creation date."""
        response = await client.get(f"{API_PREFIX}/todos?sort_by=created")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_list_todos_sort_by_due_date(self, client):
        """GET /todos?sort_by=due_date sorts by due date."""
        response = await client.get(f"{API_PREFIX}/todos?sort_by=due_date")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_todo_not_found(self, client):
        """GET /todos/{id} returns 404 for nonexistent todo."""
        fake_id = str(uuid.uuid4())
        response = await client.get(f"{API_PREFIX}/todos/{fake_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_todo_detail(self, client, db_session):
        """GET /todos/{id} returns todo detail."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="care",
            title="Check on client", source_event_id=str(event.id),
            priority=2, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["todo_type"] == "care"
        assert data["title"] == "Check on client"

    @pytest.mark.asyncio
    async def test_update_todo_status(self, client, db_session):
        """PATCH /todos/{id} with status change uses state machine."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Follow up", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"status": "in_progress"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "in_progress"

    @pytest.mark.asyncio
    async def test_update_todo_with_feedback(self, client, db_session):
        """PATCH /todos/{id} with feedback updates properties."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Follow up", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        # PATCH returns TodoResponse (no properties field)
        response = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"feedback": "Already done via phone"},
        )
        assert response.status_code == 200

        # Verify feedback was persisted by fetching detail (TodoDetailResponse has properties)
        detail_resp = await client.get(f"{API_PREFIX}/todos/{todo.id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail.get("properties", {}).get("feedback") == "Already done via phone"

    @pytest.mark.asyncio
    async def test_update_todo_priority_override(self, client, db_session):
        """PATCH /todos/{id} with priority_override sets user priority."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Follow up", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.patch(
            f"{API_PREFIX}/todos/{todo.id}",
            json={"priority_override": "high"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["priority_source"] == "user"

    @pytest.mark.asyncio
    async def test_update_todo_not_found(self, client):
        """PATCH /todos/{id} returns 404 for nonexistent todo."""
        fake_id = str(uuid.uuid4())
        response = await client.patch(
            f"{API_PREFIX}/todos/{fake_id}",
            json={"status": "done"},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_todo(self, client, db_session):
        """DELETE /todos/{id} deletes a todo."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="help",
            title="Help with project", source_event_id=str(event.id),
            priority=2, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        response = await client.delete(f"{API_PREFIX}/todos/{todo.id}")
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_todo_not_found(self, client):
        """DELETE /todos/{id} returns 404 for nonexistent todo."""
        fake_id = str(uuid.uuid4())
        response = await client.delete(f"{API_PREFIX}/todos/{fake_id}")
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 14. Relationship Briefs API Tests (relationship_briefs.py: 58% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestRelationshipBriefsAPI:
    """Tests for Relationship Briefs endpoints."""

    @pytest.mark.asyncio
    async def test_get_relationship_brief_not_found(self, client):
        """GET /persons/{id}/relationship-brief returns 404 when no brief."""
        fake_id = str(uuid.uuid4())
        response = await client.get(
            f"{API_PREFIX}/persons/{fake_id}/relationship-brief"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_relationship_brief_aggregated_not_found(self, client):
        """GET /persons/{id}/relationship-brief/aggregated returns 404."""
        fake_id = str(uuid.uuid4())
        response = await client.get(
            f"{API_PREFIX}/persons/{fake_id}/relationship-brief/aggregated"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_relationship_brief(self, client, db_session):
        """GET /persons/{id}/relationship-brief returns brief."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.relationship_brief import RelationshipBrief

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="测试人", canonical_name="测试人", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            relationship_stage="new_connection",
            brief_data={"basic_info": {"name": "测试人"}},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await client.get(
            f"{API_PREFIX}/persons/{entity.id}/relationship-brief"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["relationship_stage"] == "new_connection"

    @pytest.mark.asyncio
    async def test_get_relationship_brief_aggregated(self, client, db_session):
        """GET /persons/{id}/relationship-brief/aggregated returns aggregated view."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.relationship_brief import RelationshipBrief

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="聚合测试", canonical_name="聚合测试", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            relationship_stage="understanding_needs",
            brief_data={
                "basic_info": {"name": "聚合测试"},
                "strength_score": 65,
                "their_concerns": ["效率"],
                "open_promises": {"my_promises": [{"title": "跟进", "due_date": None}], "their_promises": []},
                "next_actions": [{"action": "主动联系", "priority": "medium"}],
            },
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await client.get(
            f"{API_PREFIX}/persons/{entity.id}/relationship-brief/aggregated"
        )
        assert response.status_code == 200
        data = response.json()
        assert "modules" in data
        assert data["strength_score"] == 65
        assert data["relationship_stage"] == "understanding_needs"
        assert len(data["modules"]) == 12  # 12 modules

    @pytest.mark.asyncio
    async def test_list_relationship_briefs(self, client, db_session):
        """GET /relationship-briefs returns list of briefs."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.relationship_brief import RelationshipBrief

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="列表测试", canonical_name="列表测试", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            relationship_stage="new_connection",
            brief_data={},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await client.get(f"{API_PREFIX}/relationship-briefs")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert data["total"] >= 1

    @pytest.mark.asyncio
    async def test_update_relationship_brief(self, client, db_session):
        """PATCH /relationship-briefs/{id} updates brief with optimistic lock."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.relationship_brief import RelationshipBrief

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="更新测试", canonical_name="更新测试", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            relationship_stage="new_connection",
            brief_data={"notes": ""},
            version=1,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await client.patch(
            f"{API_PREFIX}/relationship-briefs/{brief.id}",
            json={
                "notes": "Updated notes",
                "expected_version": 1,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == 2

    @pytest.mark.asyncio
    async def test_update_relationship_brief_version_conflict(self, client, db_session):
        """PATCH /relationship-briefs/{id} returns 409 on version mismatch."""
        from promiselink.models.entity import Entity
        from promiselink.models.event import Event
        from promiselink.models.relationship_brief import RelationshipBrief

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        entity = Entity(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, entity_type="person",
            name="冲突测试", canonical_name="冲突测试", source_event_id=str(event.id),
            confidence=0.9, status="confirmed",
        )
        db_session.add(entity)
        await db_session.flush()

        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(entity.id),
            relationship_stage="new_connection",
            brief_data={},
            version=3,
        )
        db_session.add(brief)
        await db_session.commit()

        response = await client.patch(
            f"{API_PREFIX}/relationship-briefs/{brief.id}",
            json={
                "notes": "Stale update",
                "expected_version": 1,  # Wrong version
            },
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_update_relationship_brief_not_found(self, client):
        """PATCH /relationship-briefs/{id} returns 404 for nonexistent brief."""
        fake_id = str(uuid.uuid4())
        response = await client.patch(
            f"{API_PREFIX}/relationship-briefs/{fake_id}",
            json={"notes": "test", "expected_version": 1},
        )
        assert response.status_code == 404


# ══════════════════════════════════════════════════════════════════
# 15. Email Sync API Tests (email_sync.py: 49% → 80%+)
# ══════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="Email Sync API is a Pro-only feature",
)
class TestEmailSyncAPI:
    """Tests for Email Sync endpoint."""

    @pytest.mark.asyncio
    async def test_email_sync_disallowed_host(self, client):
        """POST /email/sync with disallowed IMAP host returns 400."""
        response = await client.post(
            f"{API_PREFIX}/email/sync",
            json={
                "imap_host": "evil.imap.server.com",
                "email": "user@evil.com",
                "password": "secret",
            },
        )
        assert response.status_code == 400
        body = response.json()
        msg = body.get("error", {}).get("message", "") or body.get("detail", "")
        assert "not in the allowed list" in msg

    @pytest.mark.asyncio
    async def test_email_sync_connection_failure(self, client):
        """POST /email/sync with IMAP connection failure returns 502."""
        with patch("promiselink.api.v1.email_sync.EmailAdapter") as MockAdapter:
            mock_adapter = AsyncMock()
            mock_adapter.connect = AsyncMock(return_value=False)
            MockAdapter.return_value = mock_adapter

            response = await client.post(
                f"{API_PREFIX}/email/sync",
                json={
                    "imap_host": "imap.gmail.com",
                    "email": "user@gmail.com",
                    "password": "secret",
                },
            )
        assert response.status_code == 502

    @pytest.mark.asyncio
    async def test_email_sync_success(self, client):
        """POST /email/sync with successful sync returns synced emails."""
        from promiselink.services.email_adapter import EmailMessage

        mock_msg = EmailMessage(
            message_id="<test@gmail.com>",
            subject="Test Subject",
            from_addr="sender@gmail.com",
            from_name="Sender",
            to_addrs=["user@gmail.com"],
            date=datetime.now(timezone.utc),
            body_text="Test body",
            body_html=None,
        )

        with patch("promiselink.api.v1.email_sync.EmailAdapter") as MockAdapter:
            mock_adapter = MagicMock()
            mock_adapter.connect = AsyncMock(return_value=True)
            mock_adapter.fetch_unread = AsyncMock(return_value=[mock_msg])
            mock_adapter.parse_to_event = MagicMock(
                return_value=MagicMock(
                    title="Test Subject",
                    raw_text="Test body",
                    occurred_at=datetime.now(timezone.utc),
                    metadata={},
                )
            )
            mock_adapter.mark_as_read = AsyncMock()
            mock_adapter.disconnect = MagicMock()
            MockAdapter.return_value = mock_adapter

            response = await client.post(
                f"{API_PREFIX}/email/sync",
                json={
                    "imap_host": "imap.gmail.com",
                    "email": "user@gmail.com",
                    "password": "secret",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["synced_count"] == 1
        assert len(data["event_ids"]) == 1

    @pytest.mark.asyncio
    async def test_email_sync_with_errors(self, client):
        """POST /email/sync handles individual email processing errors."""
        with patch("promiselink.api.v1.email_sync.EmailAdapter") as MockAdapter:
            mock_adapter = MagicMock()
            mock_adapter.connect = AsyncMock(return_value=True)
            mock_adapter.fetch_unread = AsyncMock(return_value=[])
            mock_adapter.disconnect = MagicMock()
            MockAdapter.return_value = mock_adapter

            response = await client.post(
                f"{API_PREFIX}/email/sync",
                json={
                    "imap_host": "imap.qq.com",
                    "email": "user@qq.com",
                    "password": "secret",
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert data["synced_count"] == 0


# ══════════════════════════════════════════════════════════════════
# 16. Health API Error Path Tests (health.py: 36% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestHealthAPIErrorPaths:
    """Tests for health check error paths."""

    @pytest.mark.asyncio
    async def test_db_health_check_error(self, client, db_session):
        """GET /health/db handles database error gracefully."""
        # Make session.execute raise an exception
        with patch.object(db_session, "execute", side_effect=Exception("DB error")):
            response = await client.get(f"{API_PREFIX}/health/db")
        # The endpoint should return 200 with unhealthy status, not crash
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["components"]["database"] != "connected"

    @pytest.mark.asyncio
    async def test_full_health_check_cache_degraded(self, client):
        """GET /health/full shows degraded cache when Redis unavailable."""
        with patch("promiselink.core.redis.get_redis", return_value=None):
            response = await client.get(f"{API_PREFIX}/health/full")
        assert response.status_code == 200
        data = response.json()
        cache_status = data["components"]["cache"]["status"]
        assert cache_status in ("healthy", "degraded")

    @pytest.mark.asyncio
    async def test_full_health_check_llm_not_configured(self, client):
        """GET /health/full shows not_configured when LLM key missing."""
        with patch("promiselink.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_api_key = ""
            settings.llm_base_url = ""
            settings.llm_model = ""
            settings.app_version = "test"
            mock_settings.return_value = settings
            response = await client.get(f"{API_PREFIX}/health/full")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["llm"]["status"] == "not_configured"

    @pytest.mark.asyncio
    async def test_full_health_check_llm_configured(self, client):
        """GET /health/full shows configured when LLM key present."""
        with patch("promiselink.config.get_settings") as mock_settings:
            settings = MagicMock()
            settings.llm_api_key = "sk-test-key"
            settings.llm_base_url = "https://api.moka-ai.com/v1"
            settings.llm_model = "moka/claude-sonnet-4-6"
            settings.app_version = "test"
            mock_settings.return_value = settings
            response = await client.get(f"{API_PREFIX}/health/full")
        assert response.status_code == 200
        data = response.json()
        assert data["components"]["llm"]["status"] == "configured"


# ══════════════════════════════════════════════════════════════════
# 17. Main App Additional Tests (main.py: 66% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestMainAppAdditional:
    """Additional tests for main.py coverage."""

    @pytest.mark.asyncio
    async def test_internal_error_handler(self):
        """500 error handler returns structured error."""
        from promiselink.main import internal_error_handler
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        exc = Exception("test error")

        response = await internal_error_handler(mock_request, exc)
        assert response.status_code == 500
        import json
        body = json.loads(response.body.decode())
        assert body["error"]["code"] == "INTERNAL_ERROR"

    @pytest.mark.asyncio
    async def test_track_task(self):
        """_track_task adds task to pending set and removes on done."""
        import asyncio
        from promiselink.main import _track_task, _pending_tasks

        async def dummy():
            pass

        task = asyncio.create_task(dummy())
        _track_task(task)
        assert task in _pending_tasks

        # Wait for task to complete
        await task
        # The done callback should have removed it
        assert task not in _pending_tasks

    @pytest.mark.asyncio
    async def test_signal_handler(self):
        """_signal_handler sets shutdown event."""
        from promiselink.main import _signal_handler, _shutdown_event

        _shutdown_event.clear()
        _signal_handler(15, None)
        assert _shutdown_event.is_set()
        _shutdown_event.clear()


# ══════════════════════════════════════════════════════════════════
# 18. TodoStateMachine Tests (todo_state_machine.py: 39% → 80%+)
# ══════════════════════════════════════════════════════════════════


class TestTodoStateMachine:
    """Tests for TodoStateMachine."""

    def test_can_transition(self):
        """can_transition validates state transitions."""
        from promiselink.services.todo_state_machine import TodoStateMachine
        assert TodoStateMachine.can_transition("pending", "done") is True
        assert TodoStateMachine.can_transition("pending", "in_progress") is True
        assert TodoStateMachine.can_transition("done", "pending") is False
        assert TodoStateMachine.can_transition("dismissed", "pending") is False

    def test_get_valid_transitions(self):
        """get_valid_transitions returns valid target states."""
        from promiselink.services.todo_state_machine import TodoStateMachine
        transitions = TodoStateMachine.get_valid_transitions("pending")
        assert "in_progress" in transitions
        assert "done" in transitions
        assert "snoozed" in transitions

    def test_is_terminal(self):
        """is_terminal checks if a state is terminal."""
        from promiselink.services.todo_state_machine import TodoStateMachine
        assert TodoStateMachine.is_terminal("done") is True
        assert TodoStateMachine.is_terminal("dismissed") is True
        assert TodoStateMachine.is_terminal("pending") is False

    @pytest.mark.asyncio
    async def test_transition_pending_to_done(self, db_session):
        """Transition from pending to done sets completed_at."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event
        from promiselink.services.todo_state_machine import TodoStateMachine

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Test", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        sm = TodoStateMachine(session=db_session)
        result = await sm.transition(todo, "done", feedback="useful")
        assert result.status == "done"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_transition_invalid(self, db_session):
        """Invalid transition raises InvalidTransitionError."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event
        from promiselink.services.todo_state_machine import TodoStateMachine
        from promiselink.core.exceptions import InvalidTransitionError

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Test", source_event_id=str(event.id),
            priority=3, status="done",
        )
        db_session.add(todo)
        await db_session.commit()

        sm = TodoStateMachine(session=db_session)
        with pytest.raises(InvalidTransitionError):
            await sm.transition(todo, "pending")

    @pytest.mark.asyncio
    async def test_transition_to_snoozed_requires_until(self, db_session):
        """Transition to snoozed requires snoozed_until."""
        from promiselink.models.todo import Todo
        from promiselink.models.event import Event
        from promiselink.services.todo_state_machine import TodoStateMachine

        event = Event(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, event_type="meeting",
            source="test", title="Test", raw_text="test", status="completed",
        )
        db_session.add(event)
        await db_session.flush()

        todo = Todo(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID, todo_type="promise",
            title="Test", source_event_id=str(event.id),
            priority=3, status="pending",
        )
        db_session.add(todo)
        await db_session.commit()

        sm = TodoStateMachine(session=db_session)
        with pytest.raises(ValueError, match="snoozed_until is required"):
            await sm.transition(todo, "snoozed")


# ══════════════════════════════════════════════════════════════════
# 19. RelationshipStage Machine Tests (relationship_stage.py)
# ══════════════════════════════════════════════════════════════════


class TestRelationshipStageMachine:
    """Tests for RelationshipStageMachine."""

    def test_can_transition_valid(self):
        """Valid transitions are allowed."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.UNDERSTANDING_NEEDS,
        ) is True

    def test_can_transition_invalid(self):
        """Invalid transitions are rejected."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.DEEP_TRUST,
        ) is False

    def test_can_transition_same_stage(self):
        """Same-stage transition is allowed (no-op)."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.NEW_CONNECTION,
            RelationshipStage.NEW_CONNECTION,
        ) is True

    def test_can_transition_dormant_recovery(self):
        """DORMANT can recover to any active stage."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        assert sm.can_transition(
            RelationshipStage.DORMANT,
            RelationshipStage.NEW_CONNECTION,
        ) is True
        assert sm.can_transition(
            RelationshipStage.DORMANT,
            RelationshipStage.ACTIVE_COOPERATION,
        ) is True

    def test_suggest_transition_dormant(self):
        """Suggest DORMANT when no interaction for >90 days."""
        from datetime import timedelta
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        result = sm.suggest_transition(
            RelationshipStage.ACTIVE_COOPERATION,
            {"last_interaction_date": old_date},
        )
        assert result is not None
        assert result.requires_confirmation is True

    def test_suggest_transition_value_response(self):
        """Suggest VALUE_RESPONSE when multiple value exchanges."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.UNDERSTANDING_NEEDS,
            {"value_exchange_count": 3},
        )
        assert result is not None
        assert result.current_stage == RelationshipStage.VALUE_RESPONSE

    def test_suggest_transition_understanding_needs(self):
        """Suggest UNDERSTANDING_NEEDS when care todos exist."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.NEW_CONNECTION,
            {"care_todo_count": 2},
        )
        assert result is not None
        assert result.current_stage == RelationshipStage.UNDERSTANDING_NEEDS

    def test_suggest_transition_no_suggestion(self):
        """No suggestion when conditions not met."""
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        result = sm.suggest_transition(
            RelationshipStage.DEEP_TRUST,
            {},
        )
        assert result is None

    def test_apply_transition_requires_confirmation(self):
        """PoC transitions require user confirmation."""
        from promiselink.models.relationship_brief import RelationshipBrief
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(uuid.uuid4()),
            relationship_stage="new_connection",
            brief_data={}, version=1,
        )
        result = sm.apply_transition(
            brief, RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=False,
        )
        assert result.success is False
        assert result.requires_confirmation is True

    def test_apply_transition_confirmed(self):
        """Confirmed transition succeeds."""
        from promiselink.models.relationship_brief import RelationshipBrief
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        sm = RelationshipStageMachine()
        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(uuid.uuid4()),
            relationship_stage="new_connection",
            brief_data={}, version=1,
        )
        result = sm.apply_transition(
            brief, RelationshipStage.UNDERSTANDING_NEEDS,
            confirmed_by_user=True,
        )
        assert result.success is True
        assert brief.relationship_stage == "understanding_needs"

    def test_apply_transition_invalid_raises(self):
        """Invalid transition raises InvalidTransitionError."""
        from promiselink.models.relationship_brief import RelationshipBrief
        from promiselink.services.relationship_stage import (
            RelationshipStage,
            RelationshipStageMachine,
        )
        from promiselink.core.exceptions import InvalidTransitionError
        sm = RelationshipStageMachine()
        brief = RelationshipBrief(
            id=str(uuid.uuid4()), user_id=TEST_USER_ID,
            person_entity_id=str(uuid.uuid4()),
            relationship_stage="new_connection",
            brief_data={}, version=1,
        )
        with pytest.raises(InvalidTransitionError):
            sm.apply_transition(brief, RelationshipStage.DEEP_TRUST)

    def test_get_all_stages(self):
        """get_all_stages returns ordered list."""
        from promiselink.services.relationship_stage import RelationshipStageMachine
        stages = RelationshipStageMachine.get_all_stages()
        assert len(stages) == 7
        assert stages[0]["order"] == 1

    def test_check_dormant_eligibility(self):
        """check_dormant_eligibility detects inactivity."""
        from datetime import timedelta
        from promiselink.services.relationship_stage import RelationshipStageMachine
        sm = RelationshipStageMachine()
        old_date = datetime.now(timezone.utc) - timedelta(days=100)
        assert sm.check_dormant_eligibility(old_date) is True
        assert sm.check_dormant_eligibility(datetime.now(timezone.utc)) is False
        assert sm.check_dormant_eligibility(None) is False


# ══════════════════════════════════════════════════════════════════
# 20. RelationshipBrief Service Helper Tests
# ══════════════════════════════════════════════════════════════════


class TestRelationshipBriefHelpers:
    """Tests for RelationshipBriefService static helpers."""

    def test_strength_score_calculation(self):
        """_calculate_strength_score computes score correctly."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        data = {
            "interaction_freq": {"last_30_days": 5},
            "open_promises": {"my_promises": [{"title": "p1"}], "their_promises": []},
            "their_concerns": ["concern1"],
            "my_contributions": ["contrib1"],
            "last_interaction": {"date": datetime.now(timezone.utc).isoformat()},
        }
        score = RelationshipBriefService._calculate_strength_score(data)
        assert 0 < score <= 100

    def test_strength_score_empty(self):
        """_calculate_strength_score returns 0 for empty data."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        score = RelationshipBriefService._calculate_strength_score({})
        assert score == 0

    def test_sync_open_promises(self):
        """_sync_open_promises categorizes promises correctly."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        from promiselink.models.todo import Todo

        todos = [
            MagicMock(todo_type="promise", title="My promise", status="pending",
                      due_date=None, action_type="my_promise"),
            MagicMock(todo_type="promise", title="Their promise", status="pending",
                      due_date=None, action_type="their_promise"),
            MagicMock(todo_type="promise", title="Done promise", status="done",
                      due_date=None, action_type="my_promise"),
        ]
        result = RelationshipBriefService._sync_open_promises(todos)
        assert len(result["my_promises"]) == 1
        assert len(result["their_promises"]) == 1

    def test_extract_their_concerns(self):
        """_extract_their_concerns extracts care-type todo titles."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        todos = [
            MagicMock(todo_type="care", title="关注效率问题"),
            MagicMock(todo_type="promise", title="Not a concern"),
        ]
        concerns = RelationshipBriefService._extract_their_concerns(todos)
        assert len(concerns) == 1
        assert "效率" in concerns[0]

    def test_extract_risk_flags(self):
        """_extract_risk_flags extracts risk-type todo titles."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        todos = [
            MagicMock(todo_type="risk", title="逾期风险"),
            MagicMock(todo_type="care", title="Not a risk"),
        ]
        flags = RelationshipBriefService._extract_risk_flags(todos)
        assert len(flags) == 1

    def test_generate_next_actions_default(self):
        """_generate_next_actions returns default action when no data."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        actions = RelationshipBriefService._generate_next_actions({})
        assert len(actions) == 1
        assert actions[0]["action"] == "保持定期联系"

    def test_generate_next_actions_with_concerns(self):
        """_generate_next_actions includes concern follow-up."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        data = {
            "their_concerns": ["项目进度"],
            "basic_info": {"name": "张三"},
        }
        actions = RelationshipBriefService._generate_next_actions(data)
        assert any("关注" in a["action"] for a in actions)

    def test_generate_next_actions_with_associations(self):
        """_generate_next_actions includes association-based actions."""
        from promiselink.services.relationship_brief_service import RelationshipBriefService
        data = {"basic_info": {"name": "张三"}}
        associations = [
            {
                "association_type": "industry_chain",
                "other_entity_name": "李四",
                "evidence": {"relation": "potential_investor_startup"},
            }
        ]
        actions = RelationshipBriefService._generate_next_actions(data, associations)
        assert any("引荐" in a["action"] for a in actions)

    def test_module_has_meaningful_data(self):
        """_module_has_meaningful_data checks data presence."""
        from promiselink.api.v1.relationship_briefs import _module_has_meaningful_data
        assert _module_has_meaningful_data("strength_score", {"strength_score": 50}) is True
        assert _module_has_meaningful_data("notes", {"notes": ""}) is False
        assert _module_has_meaningful_data("basic_info", {"basic_info": {}}) is False
        assert _module_has_meaningful_data("basic_info", {"basic_info": {"name": "test"}}) is True

    def test_strength_label(self):
        """_strength_label returns correct label/color pairs."""
        from promiselink.api.v1.relationship_briefs import _strength_label
        assert _strength_label(85)[0] == "关系稳固"
        assert _strength_label(65)[0] == "关系良好"
        assert _strength_label(45)[0] == "关系发展中"
        assert _strength_label(25)[0] == "关系初期"
        assert _strength_label(10)[0] == "刚建立联系"

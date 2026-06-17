"""Tests for WeChat Forward API endpoint (PRD §5.17)."""

import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="WeChat Forward API is a Pro-only feature",
)


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
async def client(db_session, db_engine):
    """Provide an httpx.AsyncClient with DB dependency overridden."""

    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════
# POST /wechat/forward — Happy Path
# ════════════════════════════════════════════════════════════════════


class TestWeChatForwardHappyPath:
    """Tests for POST /api/v1/wechat/forward — success cases."""

    @pytest.mark.asyncio
    async def test_forward_group_chat(self, client: AsyncClient):
        """Parse a group chat with multiple speakers."""
        text = "张三 10:30\n明天下午3点见面聊聊合作\n\n李四 10:32\n好的，我准备一下资料"

        with patch(
            "promiselink.services.event_pipeline.process_event_with_short_transactions",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{API_PREFIX}/wechat/forward",
                json={"text": text},
            )

        assert resp.status_code == 201
        data = resp.json()

        assert data["event_type"] == "wechat_forward"
        assert data["source"] == "wechat_forward"
        assert data["status"] == "pending"
        assert "张三" in data["speakers"]
        assert "李四" in data["speakers"]
        assert data["message_count"] == 2
        assert data["time_range"] == "10:30-10:32"

    @pytest.mark.asyncio
    async def test_forward_single_chat(self, client: AsyncClient):
        """Parse a single chat format."""
        text = "张三 10:30\n明天下午3点见面聊聊合作\n\n10:32\n好的，我准备一下资料"

        with patch(
            "promiselink.services.event_pipeline.process_event_with_short_transactions",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{API_PREFIX}/wechat/forward",
                json={"text": text},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "wechat_forward"
        assert data["message_count"] >= 1

    @pytest.mark.asyncio
    async def test_forward_unstructured_text(self, client: AsyncClient):
        """Fallback: unparseable text is treated as a single message."""
        text = "这是一段没有格式的纯文本内容"

        with patch(
            "promiselink.services.event_pipeline.process_event_with_short_transactions",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{API_PREFIX}/wechat/forward",
                json={"text": text},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["event_type"] == "wechat_forward"
        assert "微信转发" in data["title"]

    @pytest.mark.asyncio
    async def test_response_includes_id_and_user_id(
        self, client: AsyncClient
    ):
        """Response includes id and user_id fields."""
        text = "张三 10:30\n测试消息"

        with patch(
            "promiselink.services.event_pipeline.process_event_with_short_transactions",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"{API_PREFIX}/wechat/forward",
                json={"text": text},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert data["user_id"] == TEST_USER_ID


# ════════════════════════════════════════════════════════════════════
# POST /wechat/forward — Validation Errors
# ════════════════════════════════════════════════════════════════════


class TestWeChatForwardValidation:
    """Tests for POST /api/v1/wechat/forward — validation errors."""

    @pytest.mark.asyncio
    async def test_empty_text_returns_422(self, client: AsyncClient):
        """Empty text fails min_length=1 validation."""
        resp = await client.post(
            f"{API_PREFIX}/wechat/forward",
            json={"text": ""},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_missing_text_field_returns_422(
        self, client: AsyncClient
    ):
        """Missing text field returns 422."""
        resp = await client.post(
            f"{API_PREFIX}/wechat/forward",
            json={},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_text_exceeding_max_length_returns_422(
        self, client: AsyncClient
    ):
        """Text exceeding max_length=512000 returns 422."""
        long_text = "x" * 512001
        resp = await client.post(
            f"{API_PREFIX}/wechat/forward",
            json={"text": long_text},
        )
        assert resp.status_code == 422


# ════════════════════════════════════════════════════════════════════
# POST /wechat/forward — Unauthorized Access
# ════════════════════════════════════════════════════════════════════


class TestWeChatForwardUnauthorized:
    """Tests for POST /api/v1/wechat/forward — unauthorized access."""

    @pytest.mark.asyncio
    async def test_forward_requires_auth(self, db_session, db_engine):
        """Without auth override, endpoint returns 401."""

        async def override_get_async_session():
            yield db_session

        # Only override DB, NOT auth — so auth is required
        app.dependency_overrides[get_async_session] = override_get_async_session

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"{API_PREFIX}/wechat/forward",
                json={"text": "测试消息"},
            )
        app.dependency_overrides.clear()

        assert resp.status_code == 401

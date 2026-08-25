"""测试 P0-2 修复：dashboard root + summary 端点。

确保 /api/v1/dashboard 和 /api/v1/dashboard/summary 返回 200，
为前端 dashboard 调用提供兼容路径。
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import MagicMock

from promiselink.main import app
from promiselink.database import get_async_session
from promiselink.core.auth import get_current_user_id
from promiselink.api.dependencies import rate_limit_dependency


class TestDashboardRootAndSummary:
    """P0-2: dashboard root + summary 兼容性测试."""

    @pytest.fixture
    def mock_user_id(self):
        return "test_user"

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        return session

    @pytest.fixture
    async def client(self, mock_user_id, mock_session):
        async def override_session():
            yield mock_session

        async def override_user():
            return mock_user_id

        async def no_rate_limit():
            return None

        app.dependency_overrides[get_async_session] = override_session
        app.dependency_overrides[get_current_user_id] = override_user
        app.dependency_overrides[rate_limit_dependency] = no_rate_limit
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()

    @pytest.mark.asyncio
    async def test_dashboard_root_returns_200(self, client):
        """P0-2: /api/v1/dashboard 不再 405, 返回 200 with summary."""
        resp = await client.get("/api/v1/dashboard")
        assert resp.status_code == 200, f"期望 200, 实际 {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert "date" in body
        assert "summary" in body
        assert "endpoints" in body

    @pytest.mark.asyncio
    async def test_dashboard_summary_returns_200(self, client):
        """P0-2: /api/v1/dashboard/summary 不再 405, 返回 200."""
        resp = await client.get("/api/v1/dashboard/summary")
        assert resp.status_code == 200, f"期望 200, 实际 {resp.status_code}: {resp.text[:200]}"
        body = resp.json()
        assert "date" in body
        assert "summary" in body

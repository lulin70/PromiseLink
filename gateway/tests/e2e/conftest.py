"""Shared fixtures for E2E tests.

Sets up a fully wired FastAPI ``TestClient`` with:
- :class:`InMemoryLicenseService` (real JWT signing, in-memory license store)
- :class:`BillingService` (shared license store, in-memory usage records)
- :class:`RelayService` with an ``httpx.MockTransport`` for upstream LLM calls

The ``TestClient`` exercises the real HTTP request → middleware → endpoint →
response cycle — no service methods are mocked.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.config import get_settings
from gateway.core.jwt_handler import JWTHandler
from gateway.main import create_app
from gateway.services.api_key_pool import create_default_key_pool
from gateway.services.billing_service import BillingService
from gateway.services.relay_service import RelayService
from gateway.tests._helpers import InMemoryLicenseService

# ── Constants ────────────────────────────────────────────────────────

TEST_API_KEY = "pl_gateway_client_dev_key"
TEST_ADMIN_API_KEY = "dev-admin-api-key-min-32-chars-padding!!"


# ── Core fixtures ────────────────────────────────────────────────────


@pytest.fixture
def test_settings():
    """Return test settings (cache cleared by parent conftest autouse)."""
    return get_settings()


@pytest.fixture
def jwt_handler(test_settings) -> JWTHandler:
    """Return a JWTHandler instance for signing/verifying tokens."""
    return JWTHandler(test_settings)


@pytest.fixture
def license_store() -> dict[str, Any]:
    """Return a fresh in-memory license store (shared dict)."""
    return {}


@pytest.fixture
def license_service(jwt_handler, license_store) -> InMemoryLicenseService:
    """Return an InMemoryLicenseService wired to the shared license store."""
    return InMemoryLicenseService(
        jwt_handler=jwt_handler,
        licenses=license_store,
    )


@pytest.fixture
def billing_service(test_settings, license_store) -> BillingService:
    """Return a BillingService sharing the same license store."""
    return BillingService(settings=test_settings, licenses=license_store)


@pytest.fixture
def mock_llm_transport() -> httpx.MockTransport:
    """Return an httpx.MockTransport that simulates LLM provider responses.

    Each call returns a deterministic chat completion with 10 input + 10
    output tokens (20 total), so quota calculations are predictable.
    """
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
def api_key_pool(test_settings):
    """Return a default API key pool with Moka AI and OpenAI keys."""
    return create_default_key_pool(test_settings)


@pytest.fixture
def relay_service(billing_service, test_settings, mock_llm_transport, api_key_pool) -> RelayService:
    """Return a RelayService with a mock HTTP transport for upstream calls."""
    svc = RelayService(
        api_key_pool=api_key_pool,
        billing_service=billing_service,
        http_client=httpx.AsyncClient(transport=mock_llm_transport),
        settings=test_settings,
    )
    return svc


@pytest.fixture
def app_client(
    test_settings,
    jwt_handler,
    license_service,
    billing_service,
    relay_service,
    api_key_pool,
) -> TestClient:
    """Create a FastAPI TestClient with all services injected.

    The TestClient exercises the full HTTP stack: middleware, auth,
    routing, exception handlers — exactly as a real client would.
    """
    app = create_app(
        settings=test_settings,
        jwt_handler=jwt_handler,
        license_service=license_service,
        billing_service=billing_service,
        relay_service=relay_service,
        api_key_pool=api_key_pool,
    )
    with TestClient(app) as client:
        # Expose service references on the client for direct inspection
        client._license_service = license_service  # type: ignore[attr-defined]
        client._billing_service = billing_service  # type: ignore[attr-defined]
        client._jwt_handler = jwt_handler  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client

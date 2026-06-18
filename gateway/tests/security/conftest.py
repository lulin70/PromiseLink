"""Shared fixtures for security tests.

Mirrors the E2E conftest but kept separate so security tests can evolve
independently. Provides a fully wired ``TestClient`` with real JWT signing,
in-memory license/billing stores, and a mock upstream LLM transport.
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
def api_key_pool(test_settings):
    """Return a default API key pool with Moka AI and OpenAI keys."""
    return create_default_key_pool(test_settings)


@pytest.fixture
def relay_service(billing_service, test_settings, mock_llm_transport, api_key_pool) -> RelayService:
    """Return a RelayService with a mock HTTP transport for upstream calls."""
    return RelayService(
        api_key_pool=api_key_pool,
        billing_service=billing_service,
        http_client=httpx.AsyncClient(transport=mock_llm_transport),
        settings=test_settings,
    )


@pytest.fixture
def app_client(
    test_settings,
    jwt_handler,
    license_service,
    billing_service,
    relay_service,
    api_key_pool,
) -> TestClient:
    """Create a FastAPI TestClient with all services injected."""
    app = create_app(
        settings=test_settings,
        jwt_handler=jwt_handler,
        license_service=license_service,
        billing_service=billing_service,
        relay_service=relay_service,
        api_key_pool=api_key_pool,
    )
    with TestClient(app) as client:
        client._license_service = license_service  # type: ignore[attr-defined]
        client._billing_service = billing_service  # type: ignore[attr-defined]
        client._jwt_handler = jwt_handler  # type: ignore[attr-defined]
        client._app = app  # type: ignore[attr-defined]
        yield client


@pytest.fixture
def activated_license_and_token(
    app_client: TestClient,
    license_store,
    jwt_handler,
):
    """Activate a license and return (license_key, user_id, device_fp, access_token).

    This fixture provides a pre-activated license for tests that need a
    valid authenticated session as a starting point.
    """
    from gateway.tests._helpers import (
        make_device_fingerprint,
        make_license,
        make_license_key,
        make_user_id,
    )

    license_key = make_license_key("SECURITY")
    user_id = make_user_id("sec-user")
    device_fp = make_device_fingerprint("sec-device")

    lic = make_license(license_key, status="active")
    license_store[license_key] = lic

    user_jwt = jwt_handler.create_access_token(
        user_id=user_id,
        license_key="",
        plan_type="pro",
        device_fingerprint="",
    )

    resp = app_client.post(
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
    assert resp.status_code == 200, f"Setup activation failed: {resp.text}"
    access_token = resp.json()["data"]["tokens"]["access_token"]

    return {
        "license_key": license_key,
        "user_id": user_id,
        "device_fp": device_fp,
        "access_token": access_token,
    }

"""Tests for the admin monitoring API endpoints.

Tests cover:
- Admin two-factor authentication (API key + JWT / token endpoint)
- Usage summary endpoint
- User usage list (pagination + sorting)
- Single user usage detail
- CSV export
- Health check endpoint
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from gateway.main import create_app
from gateway.models.tables import License, UsageRecord
from gateway.services.billing_service import BillingService

# ── Test constants ──

# Must match settings.admin_api_key default
TEST_ADMIN_API_KEY = "dev-admin-api-key-min-32-chars-padding!!"
TEST_ADMIN_PASSPHRASE = "dev-admin-passphrase"
WRONG_ADMIN_KEY = "wrong-admin-key-xxx"

LICENSE_KEY_A = "PL-PRO-AAAA-0001-USER"
LICENSE_KEY_B = "PL-PRO-BBBB-0002-USER"
LICENSE_KEY_C = "PL-PRO-CCCC-0003-USER"

# Admin JWT constants (must match middleware/auth.py)
_ADMIN_JWT_ISSUER = "promiselink-gateway-admin"
_ADMIN_JWT_AUDIENCE = "promiselink-admin-client"


# ── Helpers ──


def _make_license(
    license_key: str,
    user_id: str,
    *,
    status: str = "active",
    used_tokens: int = 0,
    limit_tokens: int = 500000,
    used_asr: int = 0,
    used_tts: int = 0,
    used_ocr: int = 0,
) -> License:
    """Build a License ORM row with test defaults."""
    now = datetime.now(UTC)
    return License(
        license_key=license_key,
        user_id=user_id,
        plan_type="pro",
        quota_limit_tokens=limit_tokens,
        quota_limit_asr=200,
        quota_limit_tts=200,
        quota_limit_ocr=100,
        quota_used_tokens=used_tokens,
        quota_used_asr=used_asr,
        quota_used_tts=used_tts,
        quota_used_ocr=used_ocr,
        quota_reset_at=now,
        status=status,
        started_at=now,
        expires_at=now + timedelta(days=365),
        max_devices=1,
    )


def _make_record(
    license_key: str,
    user_id: str,
    request_type: str = "llm",
    *,
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    input_tokens: int = 100,
    output_tokens: int = 50,
    status_code: int = 200,
    success: bool = True,
    created_at: datetime | None = None,
) -> UsageRecord:
    """Build a UsageRecord ORM row with test defaults."""
    return UsageRecord(
        request_id=f"req-{license_key}-{request_type}-{datetime.now().microsecond}",
        user_id=user_id,
        license_key=license_key,
        request_type=request_type,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        duration_ms=500,
        cost_cny=Decimal("0.001"),
        status_code=status_code,
        success=success,
        created_at=created_at or datetime.now(UTC),
    )


# ── Fixtures ──


@pytest.fixture
def admin_billing_service() -> BillingService:
    """Create a BillingService pre-populated with test licenses and records."""
    svc = BillingService()
    svc._licenses = {}
    svc._usage_records = []

    # License A — green (low usage)
    lic_a = _make_license(LICENSE_KEY_A, "user_a", used_tokens=50000)
    svc._licenses[LICENSE_KEY_A] = lic_a

    # License B — yellow (80% usage)
    lic_b = _make_license(LICENSE_KEY_B, "user_b", used_tokens=400000)
    svc._licenses[LICENSE_KEY_B] = lic_b

    # License C — red (100% usage, inactive)
    lic_c = _make_license(
        LICENSE_KEY_C, "user_c", status="inactive", used_tokens=500000
    )
    svc._licenses[LICENSE_KEY_C] = lic_c

    # Usage records for license A
    svc._usage_records.append(
        _make_record(LICENSE_KEY_A, "user_a", "llm", input_tokens=200, output_tokens=100)
    )
    svc._usage_records.append(
        _make_record(LICENSE_KEY_A, "user_a", "asr", input_tokens=0, output_tokens=0)
    )
    svc._usage_records.append(
        _make_record(LICENSE_KEY_A, "user_a", "tts", input_tokens=0, output_tokens=0)
    )

    # Usage records for license B
    svc._usage_records.append(
        _make_record(LICENSE_KEY_B, "user_b", "llm", input_tokens=500, output_tokens=200)
    )
    svc._usage_records.append(
        _make_record(LICENSE_KEY_B, "user_b", "ocr", input_tokens=0, output_tokens=0)
    )

    # Usage records for license C
    svc._usage_records.append(
        _make_record(LICENSE_KEY_C, "user_c", "llm", input_tokens=100, output_tokens=50)
    )

    return svc


@pytest.fixture
def admin_license_store(admin_billing_service):
    """Create a mock license_service that shares the billing service's licenses."""
    from gateway.services.license_service import LicenseService

    store = LicenseService.__new__(LicenseService)
    store._licenses = admin_billing_service._licenses
    store._activations = {}
    return store


@pytest.fixture
def admin_client(admin_billing_service, admin_license_store, jwt_handler, test_settings):
    """Create a FastAPI TestClient with admin test data."""
    app = create_app(
        settings=test_settings,
        jwt_handler=jwt_handler,
        license_service=admin_license_store,
        billing_service=admin_billing_service,
    )
    with TestClient(app) as client:
        yield client


def _make_admin_jwt(test_settings) -> str:
    """Create a valid admin JWT for testing (matches POST /api/v1/admin/token)."""
    now = int(time.time())
    payload = {
        "admin_id": test_settings.admin_id,
        "role": "admin",
        "iat": now,
        "exp": now + test_settings.admin_jwt_ttl,
        "iss": _ADMIN_JWT_ISSUER,
        "aud": _ADMIN_JWT_AUDIENCE,
    }
    return pyjwt.encode(payload, test_settings.admin_jwt_secret, algorithm="HS256")


@pytest.fixture
def admin_headers(test_settings) -> dict:
    """Return headers with a valid admin API key and admin JWT (two-factor)."""
    return {
        "X-Admin-API-Key": TEST_ADMIN_API_KEY,
        "Authorization": f"Bearer {_make_admin_jwt(test_settings)}",
    }


# ── Authentication Tests ──


class TestAdminAuth:
    """Tests for admin two-factor authentication."""

    def test_missing_admin_api_key(self, admin_client: TestClient, test_settings):
        """Request without X-Admin-API-Key header → 401."""
        # Only send the JWT, no API key
        resp = admin_client.get(
            "/api/v1/admin/usage/summary",
            headers={"Authorization": f"Bearer {_make_admin_jwt(test_settings)}"},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_wrong_admin_api_key(self, admin_client: TestClient, test_settings):
        """Request with wrong X-Admin-API-Key → 401."""
        resp = admin_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": WRONG_ADMIN_KEY,
                "Authorization": f"Bearer {_make_admin_jwt(test_settings)}",
            },
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_missing_admin_jwt(self, admin_client: TestClient):
        """Request with API key but no JWT → 401."""
        resp = admin_client.get(
            "/api/v1/admin/usage/summary",
            headers={"X-Admin-API-Key": TEST_ADMIN_API_KEY},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "JWT_MISSING"

    def test_correct_two_factor(self, admin_client: TestClient, admin_headers):
        """Request with correct API key + JWT → 200."""
        resp = admin_client.get(
            "/api/v1/admin/usage/summary",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_token_endpoint_success(self, admin_client: TestClient):
        """POST /api/v1/admin/token with correct key + passphrase → 200 + JWT."""
        resp = admin_client.post(
            "/api/v1/admin/token",
            headers={"X-Admin-API-Key": TEST_ADMIN_API_KEY},
            json={"passphrase": TEST_ADMIN_PASSPHRASE},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] > 0

    def test_token_endpoint_wrong_passphrase(self, admin_client: TestClient):
        """POST /api/v1/admin/token with wrong passphrase → 403."""
        resp = admin_client.post(
            "/api/v1/admin/token",
            headers={"X-Admin-API-Key": TEST_ADMIN_API_KEY},
            json={"passphrase": "wrong-passphrase"},
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "PERMISSION_DENIED"

    def test_token_endpoint_missing_api_key(self, admin_client: TestClient):
        """POST /api/v1/admin/token without API key → 401."""
        resp = admin_client.post(
            "/api/v1/admin/token",
            json={"passphrase": TEST_ADMIN_PASSPHRASE},
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "API_KEY_INVALID"

    def test_token_endpoint_then_use_jwt(self, admin_client: TestClient):
        """Full flow: get token from endpoint, then use it for admin API."""
        # Step 1: Get admin JWT
        resp = admin_client.post(
            "/api/v1/admin/token",
            headers={"X-Admin-API-Key": TEST_ADMIN_API_KEY},
            json={"passphrase": TEST_ADMIN_PASSPHRASE},
        )
        assert resp.status_code == 200
        token = resp.json()["data"]["access_token"]

        # Step 2: Use the JWT for an admin endpoint
        resp = admin_client.get(
            "/api/v1/admin/usage/summary",
            headers={
                "X-Admin-API-Key": TEST_ADMIN_API_KEY,
                "Authorization": f"Bearer {token}",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ── Usage Summary Tests ──


class TestUsageSummary:
    """Tests for GET /api/v1/admin/usage/summary."""

    def test_summary_returns_counts(self, admin_client: TestClient, admin_headers):
        """Summary returns total users, active users, and call counts."""
        resp = admin_client.get("/api/v1/admin/usage/summary", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_users"] == 3
        assert data["active_users"] == 2  # A and B are active, C is inactive
        assert data["total_calls"] == 6

    def test_summary_service_breakdown(self, admin_client: TestClient, admin_headers):
        """Summary returns per-service call counts."""
        resp = admin_client.get("/api/v1/admin/usage/summary", headers=admin_headers)
        data = resp.json()["data"]
        breakdown = data["service_breakdown"]
        # LLM: A(1) + B(1) + C(1) = 3
        assert breakdown["llm"] == 3
        # ASR: A(1) = 1
        assert breakdown["asr"] == 1
        # TTS: A(1) = 1
        assert breakdown["tts"] == 1
        # OCR: B(1) = 1
        assert breakdown["ocr"] == 1

    def test_summary_today_calls(self, admin_client: TestClient, admin_headers):
        """Summary returns today's call count."""
        resp = admin_client.get("/api/v1/admin/usage/summary", headers=admin_headers)
        data = resp.json()["data"]
        # All records were created with now() → today_calls == total_calls
        assert data["today_calls"] == 6
        assert data["month_calls"] == 6


# ── User Usage List Tests ──


class TestUsageUsers:
    """Tests for GET /api/v1/admin/usage/users."""

    def test_users_list_default(self, admin_client: TestClient, admin_headers):
        """Default list returns all users sorted by total_calls desc."""
        resp = admin_client.get("/api/v1/admin/usage/users", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 3
        assert data["page"] == 1
        assert len(data["items"]) == 3
        # Sorted by total_calls desc: A(3) > B(2) > C(1)
        assert data["items"][0]["license_key"] == LICENSE_KEY_A
        assert data["items"][0]["total_calls"] == 3
        assert data["items"][1]["license_key"] == LICENSE_KEY_B
        assert data["items"][1]["total_calls"] == 2
        assert data["items"][2]["license_key"] == LICENSE_KEY_C
        assert data["items"][2]["total_calls"] == 1

    def test_users_list_pagination(self, admin_client: TestClient, admin_headers):
        """Pagination returns correct page slice."""
        resp = admin_client.get(
            "/api/v1/admin/usage/users?page=1&page_size=2",
            headers=admin_headers,
        )
        data = resp.json()["data"]
        assert data["total"] == 3
        assert data["total_pages"] == 2
        assert len(data["items"]) == 2

        # Page 2
        resp = admin_client.get(
            "/api/v1/admin/usage/users?page=2&page_size=2",
            headers=admin_headers,
        )
        data = resp.json()["data"]
        assert len(data["items"]) == 1

    def test_users_list_sort_by_llm(self, admin_client: TestClient, admin_headers):
        """Sort by LLM calls ascending."""
        resp = admin_client.get(
            "/api/v1/admin/usage/users?sort_by=llm&order=asc",
            headers=admin_headers,
        )
        data = resp.json()["data"]
        # All have 1 LLM call; verify ascending order doesn't error
        assert len(data["items"]) == 3
        for item in data["items"]:
            assert item["llm_calls"] == 1

    def test_users_list_traffic_light(self, admin_client: TestClient, admin_headers):
        """Traffic light colours are computed correctly."""
        resp = admin_client.get("/api/v1/admin/usage/users", headers=admin_headers)
        data = resp.json()["data"]
        lights = {item["license_key"]: item["traffic_light"] for item in data["items"]}
        # A: 50000/500000 = 10% → green
        assert lights[LICENSE_KEY_A] == "green"
        # B: 400000/500000 = 80% → yellow
        assert lights[LICENSE_KEY_B] == "yellow"
        # C: 500000/500000 = 100% → red
        assert lights[LICENSE_KEY_C] == "red"

    def test_users_list_no_auth(self, admin_client: TestClient):
        """User list without admin key → 401."""
        resp = admin_client.get("/api/v1/admin/usage/users")
        assert resp.status_code == 401


# ── Single User Detail Tests ──


class TestUserDetail:
    """Tests for GET /api/v1/admin/usage/users/{license_key}."""

    def test_user_detail_success(self, admin_client: TestClient, admin_headers):
        """Detail returns full usage info for a license."""
        resp = admin_client.get(
            f"/api/v1/admin/usage/users/{LICENSE_KEY_A}",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["license_key"] == LICENSE_KEY_A
        assert data["user_id"] == "user_a"
        assert data["total_calls"] == 3
        assert data["llm_calls"] == 1
        assert data["asr_calls"] == 1
        assert data["tts_calls"] == 1
        assert data["traffic_light"] == "green"
        assert len(data["recent_records"]) == 3

    def test_user_detail_not_found(self, admin_client: TestClient, admin_headers):
        """Detail for non-existent license → 404."""
        resp = admin_client.get(
            "/api/v1/admin/usage/users/PL-PRO-NONEXISTENT-0000",
            headers=admin_headers,
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "LICENSE_NOT_FOUND"

    def test_user_detail_no_auth(self, admin_client: TestClient):
        """Detail without admin key → 401."""
        resp = admin_client.get(f"/api/v1/admin/usage/users/{LICENSE_KEY_A}")
        assert resp.status_code == 401


# ── CSV Export Tests ──


class TestCsvExport:
    """Tests for GET /api/v1/admin/usage/export."""

    def test_export_returns_csv(self, admin_client: TestClient, admin_headers):
        """Export returns a CSV file with all users."""
        resp = admin_client.get("/api/v1/admin/usage/export", headers=admin_headers)
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")

        # Parse CSV content (csv.writer uses \r\n line endings)
        content = resp.content.decode("utf-8-sig")
        lines = [line for line in content.splitlines() if line]
        # Header + 3 data rows
        assert len(lines) == 4
        # Verify header
        header = lines[0].split(",")
        assert "license_key" in header
        assert "traffic_light" in header
        # Verify data rows contain license keys
        assert LICENSE_KEY_A in content
        assert LICENSE_KEY_B in content
        assert LICENSE_KEY_C in content

    def test_export_no_auth(self, admin_client: TestClient):
        """Export without admin key → 401."""
        resp = admin_client.get("/api/v1/admin/usage/export")
        assert resp.status_code == 401


# ── Health Check Tests ──


class TestAdminHealth:
    """Tests for GET /api/v1/admin/health."""

    def test_health_returns_status(self, admin_client: TestClient, admin_headers):
        """Health endpoint returns component statuses."""
        resp = admin_client.get("/api/v1/admin/health", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "status" in data
        assert "version" in data
        assert "timestamp" in data
        assert "components" in data
        assert "api_key_pool" in data["components"]
        assert "redis" in data["components"]
        assert "database" in data["components"]

    def test_health_key_pool_detail(self, admin_client: TestClient, admin_headers):
        """Health endpoint returns key pool details."""
        resp = admin_client.get("/api/v1/admin/health", headers=admin_headers)
        data = resp.json()["data"]
        pool = data["components"]["api_key_pool"]
        assert "total_keys" in pool
        assert "active_keys" in pool
        assert "circuit_open_count" in pool
        # The default pool has 2 keys (moka + openai)
        assert pool["total_keys"] >= 1

    def test_health_no_auth(self, admin_client: TestClient):
        """Health without admin key → 401."""
        resp = admin_client.get("/api/v1/admin/health")
        assert resp.status_code == 401

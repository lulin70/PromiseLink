"""Shared fixtures and configuration for gateway tests.

Sets up a deterministic test environment before any gateway module is
imported:
- ``GATEWAY_ENV=test`` so settings use test defaults.
- Clears the ``get_settings`` LRU cache so each test gets a fresh config.

Provides async fixtures for:
- RSA keypair (for RS256 JWT signing/verification)
- In-memory SQLite async DB session (using tables.Base metadata)
- fakeredis async Redis client
- Active and bound License rows
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Ensure the PromiseLink project root is on sys.path so ``import gateway``
# works regardless of where pytest is invoked from.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Set test environment variables BEFORE importing any gateway module.
os.environ.setdefault("GATEWAY_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

# Fixed 32-byte base64 key for deterministic API Key encryption in tests.
_TEST_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
os.environ.setdefault("GATEWAY_ENCRYPTION_KEY", _TEST_KEY)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gateway.config import get_settings  # noqa: E402
from gateway.core.jwt_handler import generate_rsa_keypair  # noqa: E402
from gateway.models.tables import Base, License  # noqa: E402

# ── Settings cache reset ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """Clear the settings LRU cache before and after each test so
    environment-variable changes take effect."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Helper functions (importable by test modules) ───────────────────


def make_user_id(seed: str = "") -> str:
    """Return a deterministic user ID for testing.

    Args:
        seed: Optional seed string for deterministic output.

    Returns:
        A user ID string like ``u_<16 hex chars>``.
    """
    if seed:
        h = hashlib.sha256(seed.encode()).hexdigest()[:16]
        return f"u_{h}"
    return f"u_{uuid.uuid4().hex[:16]}"


def make_device_fingerprint(seed: str = "") -> str:
    """Return a valid SHA256 device fingerprint for testing.

    Args:
        seed: Optional seed string for deterministic output.

    Returns:
        A fingerprint string like ``sha256:<64 hex chars>``.
    """
    if seed:
        h = hashlib.sha256(seed.encode()).hexdigest()
    else:
        h = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    return f"sha256:{h}"


def make_license_key(seed: str = "") -> str:
    """Return a valid license key for testing.

    The key format is ``PL-PRO-xxxx-xxxx-xxxx`` where each group is
    4 uppercase alphanumeric characters.

    Args:
        seed: Optional seed string. If it looks like ``XXXX-YYYY-ZZZZ``
            it is used directly (prefixed with ``PL-PRO-``).

    Returns:
        A license key string.
    """
    if seed and "-" in seed and len(seed) >= 14:
        # Caller provided a suffix like "A1B2-C3D4-E5F6"
        return f"PL-PRO-{seed[:14]}"
    # Generate deterministic groups from seed or random UUID
    src = (seed or uuid.uuid4().hex).upper()
    # Take alphanumeric chars and pad if needed
    chars = "".join(c for c in src if c.isalnum())
    while len(chars) < 12:
        chars += "0"
    g1 = chars[:4]
    g2 = chars[4:8]
    g3 = chars[8:12]
    return f"PL-PRO-{g1}-{g2}-{g3}"


# ── RSA keypair fixtures ────────────────────────────────────────────


@pytest.fixture
def rsa_keypair() -> tuple[str, str]:
    """Generate a fresh RSA keypair for each test (slow but isolated)."""
    return generate_rsa_keypair()


@pytest.fixture
def private_key_pem(rsa_keypair: tuple[str, str]) -> str:
    """Return the private key PEM string."""
    return rsa_keypair[0]


@pytest.fixture
def public_key_pem(rsa_keypair: tuple[str, str]) -> str:
    """Return the public key PEM string."""
    return rsa_keypair[1]


# ── Database session fixture ────────────────────────────────────────


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite async engine with all gateway tables.

    Uses the Base from gateway.models.tables so all service models
    (License, UsageRecord, MonthlyUsage, AuditLog) are registered.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncSession:
    """Create a fresh async DB session for each test.

    The session uses ``expire_on_commit=False`` so objects remain
    accessible after commit without a re-fetch.
    """
    factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    async with factory() as session:
        yield session


# ── Redis fixture (fakeredis) ───────────────────────────────────────


@pytest_asyncio.fixture
async def redis_client():
    """Create a fakeredis async client for each test."""
    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


# ── License fixtures ────────────────────────────────────────────────


def _make_license_row(
    *,
    license_key: str | None = None,
    user_id: str | None = None,
    device_fingerprint: str | None = None,
    status: str = "active",
    plan_type: str = "pro",
    expires_in_days: int = 365,
) -> License:
    """Build a License ORM object with sensible test defaults."""
    now = datetime.now(UTC)
    return License(
        license_key=license_key or make_license_key(),
        user_id=user_id,
        plan_type=plan_type,
        quota_limit_tokens=500000,
        quota_limit_asr=200,
        quota_limit_tts=200,
        quota_limit_ocr=100,
        quota_used_tokens=0,
        quota_used_asr=0,
        quota_used_tts=0,
        quota_used_ocr=0,
        quota_reset_at=now,
        status=status,
        started_at=now,
        expires_at=now + timedelta(days=expires_in_days),
        device_fingerprint=device_fingerprint,
        device_bound_at=now if device_fingerprint else None,
        max_devices=1,
    )


@pytest_asyncio.fixture
async def active_license(db_session: AsyncSession) -> License:
    """Create an active (unbound) license in the database.

    The license has no user_id or device_fingerprint set, making it
    ready for activation flow tests.
    """
    lic = _make_license_row(status="active")
    db_session.add(lic)
    await db_session.commit()
    await db_session.refresh(lic)
    return lic


@pytest_asyncio.fixture
async def bound_license(db_session: AsyncSession) -> License:
    """Create a license already bound to a user and device.

    Used for verification, refresh, and revocation tests where the
    activation step has already been completed.
    """
    user_id = make_user_id("bound-user")
    device_fp = make_device_fingerprint("bound-device")
    lic = _make_license_row(
        user_id=user_id,
        device_fingerprint=device_fp,
        status="active",
    )
    db_session.add(lic)
    await db_session.commit()
    await db_session.refresh(lic)
    return lic


# ── Test constants (for API/relay tests) ────────────────────────────

TEST_USER_ID = "u_test_user_001"
TEST_LICENSE_KEY = "PL-PRO-TEST-KEY-001"
TEST_DEVICE_FP = "sha256:abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"
TEST_API_KEY = "pl_gateway_client_dev_key"


# ── Helper functions for relay/API tests ────────────────────────────


def make_llm_response(
    content: str = "Hello from LLM",
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    *,
    model: str = "moka/claude-sonnet-4-6",
) -> dict:
    """Build a mock OpenAI-compatible LLM response dict.

    Args:
        content: The response content text.
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.
        model: The model name.

    Returns:
        A dict matching the OpenAI chat completion response format.
    """
    return {
        "id": "chatcmpl-test-001",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def make_llm_stream_lines(
    tokens: list[str] | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    *,
    model: str = "moka/claude-sonnet-4-6",
) -> list[bytes]:
    """Build mock SSE stream lines for a streaming LLM response.

    Args:
        tokens: List of token strings to stream. Defaults to ["Hello", " world"].
        prompt_tokens: Number of input tokens (included in final usage chunk).
        completion_tokens: Number of output tokens (included in final usage chunk).
        model: The model name.

    Returns:
        A list of bytes lines matching the OpenAI SSE streaming format.
    """
    if tokens is None:
        tokens = ["Hello", " world"]
    import json as _json

    lines: list[bytes] = []
    for i, tok in enumerate(tokens):
        chunk = {
            "id": "chatcmpl-test-stream",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": tok},
                    "finish_reason": None if i < len(tokens) - 1 else "stop",
                }
            ],
        }
        lines.append(f"data: {_json.dumps(chunk)}\n\n".encode())
    # Final chunk with usage data (OpenAI sends usage when stream_options.include_usage=True)
    if prompt_tokens or completion_tokens:
        usage_chunk = {
            "id": "chatcmpl-test-stream",
            "object": "chat.completion.chunk",
            "created": 1700000000,
            "model": model,
            "choices": [],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        lines.append(f"data: {_json.dumps(usage_chunk)}\n\n".encode())
    lines.append(b"data: [DONE]\n\n")
    return lines


def make_mock_client(
    handler=None,
    *,
    status_code: int = 200,
    json_data: dict | None = None,
    content_data: bytes | None = None,
    content: bytes | None = None,
    stream_lines: list[bytes] | None = None,
) -> httpx.AsyncClient:
    """Create a mock httpx AsyncClient for testing relay service.

    Wraps an :class:`httpx.MockTransport` in an :class:`httpx.AsyncClient`
    so the returned client has ``.post()``, ``.stream()``, etc. methods
    that the relay service expects.

    Args:
        handler: Optional callable ``(httpx.Request) -> httpx.Response``. If
            provided, it is used directly and the other arguments are ignored.
        status_code: HTTP status code to return.
        json_data: JSON body to return (mutually exclusive with content/stream).
        content_data: Alias for ``content`` — raw bytes to return.
        content: Raw bytes to return (alias for ``content_data``).
        stream_lines: List of bytes lines for streaming response.

    Returns:
        An :class:`httpx.AsyncClient` with a mock transport.
    """
    import httpx

    # content_data is an alias for content
    raw_content = content_data if content_data is not None else content

    if handler is None:
        def handler(request: httpx.Request) -> httpx.Response:
            if stream_lines is not None:
                # Join stream lines into a single bytes body. httpx.Response
                # expects a bytes body (not a list) for the async client to
                # stream correctly via aiter_lines().
                body = b"".join(stream_lines)
                return httpx.Response(
                    status_code=status_code,
                    content=body,
                    headers={"content-type": "text/event-stream"},
                )
            if raw_content is not None:
                return httpx.Response(status_code=status_code, content=raw_content)
            return httpx.Response(
                status_code=status_code,
                json=json_data or make_llm_response(),
            )

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# ── API test fixtures (app_client, auth_headers, etc.) ─────────────


@pytest.fixture
def test_settings():
    """Return test settings with deterministic values."""
    from gateway.config import get_settings

    return get_settings()


@pytest.fixture
def jwt_handler(test_settings):
    """Return a JWTHandler instance for signing/verifying tokens."""
    from gateway.core.jwt_handler import JWTHandler

    return JWTHandler(test_settings)


@pytest.fixture
def license_store(jwt_handler, test_settings):
    """Return an in-memory license store for API tests.

    This is an :class:`InMemoryLicenseService` that is also subscriptable
    (delegates ``__getitem__``/``__setitem__`` to ``_licenses``) so tests
    can do ``license_store[KEY]`` to access licenses directly.

    The store is pre-populated with a test license under
    :data:`TEST_LICENSE_KEY` bound to :data:`TEST_USER_ID` and
    :data:`TEST_DEVICE_FP`.
    """
    from gateway.services.license_service import create_test_license
    from gateway.tests._helpers import InMemoryLicenseService

    class _SubscriptableLicenseService(InMemoryLicenseService):
        """InMemoryLicenseService with dict-like subscript access."""

        def __getitem__(self, key: str):
            return self._licenses[key]

        def __setitem__(self, key: str, value) -> None:
            self._licenses[key] = value

        def __contains__(self, key: object) -> bool:
            return key in self._licenses

    store = _SubscriptableLicenseService(jwt_handler=jwt_handler, licenses={})
    # Pre-populate a test license bound to TEST_USER_ID/TEST_DEVICE_FP
    store[TEST_LICENSE_KEY] = create_test_license(
        license_key=TEST_LICENSE_KEY,
        user_id=TEST_USER_ID,
        device_fingerprint=TEST_DEVICE_FP,
    )
    return store


@pytest.fixture
def auth_headers(jwt_handler, test_settings) -> dict:
    """Return headers with a valid API key and relay JWT."""
    token = jwt_handler.create_access_token(
        user_id=TEST_USER_ID,
        license_key=TEST_LICENSE_KEY,
        plan_type="pro",
        device_fingerprint=TEST_DEVICE_FP,
    )
    return {
        "X-API-Key": TEST_API_KEY,
        "Authorization": f"Bearer {token}",
    }


@pytest.fixture
def valid_token(jwt_handler, test_settings) -> str:
    """Return a valid relay JWT token string."""
    return jwt_handler.create_access_token(
        user_id=TEST_USER_ID,
        license_key=TEST_LICENSE_KEY,
        plan_type="pro",
        device_fingerprint=TEST_DEVICE_FP,
    )


@pytest.fixture
def app_client(
    jwt_handler,
    license_store,
    billing_service,
    api_key_pool,
    relay_service,
    test_settings,
):
    """Create a FastAPI TestClient with all mocked dependencies injected.

    All service instances (license_store, billing_service, api_key_pool,
    relay_service) are shared between the test and the app so that test
    modifications (e.g. ``relay_service._http_client = mock``) affect the
    app's behavior.
    """
    from fastapi.testclient import TestClient

    from gateway.main import create_app

    app = create_app(
        settings=test_settings,
        jwt_handler=jwt_handler,
        license_service=license_store,
        billing_service=billing_service,
        api_key_pool=api_key_pool,
        relay_service=relay_service,
    )
    with TestClient(app) as client:
        yield client


# ── Relay/billing/api_key_pool fixtures ─────────────────────────────


@pytest.fixture
def api_key_pool(test_settings):
    """Return an API Key pool with test keys for relay tests.

    Uses the real :class:`APIKeyPool` (sync) with two test keys:
    ``key-moka-1`` (moka_ai provider) and ``key-openai-1`` (openai provider).
    The base URLs point to ``moka.test`` and ``openai.test`` so tests can
    distinguish providers by URL.
    """
    from gateway.services.api_key_pool import APIKeyPool, KeyInfo

    pool = APIKeyPool(settings=test_settings)
    pool.add_key(KeyInfo(
        key_id="key-moka-1",
        provider="moka_ai",
        api_key="sk-moka-test-key",
        base_url="https://moka.test/v1",
    ))
    pool.add_key(KeyInfo(
        key_id="key-openai-1",
        provider="openai",
        api_key="sk-openai-test-key",
        base_url="https://openai.test/v1",
    ))
    return pool


@pytest.fixture
def billing_service(test_settings, license_store):
    """Return a real BillingService sharing the license_store.

    The billing service's ``_licenses`` dict is set to the
    :class:`InMemoryLicenseService` instance (which acts as a dict via
    subscript delegation to its internal ``_licenses``).
    """
    from gateway.services.billing_service import BillingService

    svc = BillingService(settings=test_settings, licenses=license_store._licenses)
    return svc


@pytest.fixture
def relay_service(api_key_pool, billing_service, test_settings):
    """Return a RelayService with mocked dependencies.

    The ``_http_client`` is left as ``None`` so individual tests can
    inject an ``httpx.MockTransport`` via ``relay_service._http_client = ...``.
    """
    from gateway.services.relay_service import RelayService

    return RelayService(
        api_key_pool=api_key_pool,
        billing_service=billing_service,
        http_client=None,
        settings=test_settings,
    )

"""Unit tests for the four Phase-0 ORM data models.

Tests cover:

* Table names and column definitions match the tech design (§3.2–§3.5).
* Default values are applied on creation.
* Basic CRUD (insert / select / update / delete) works end-to-end.
* :meth:`UsageRecord.to_dict` produces a JSON-serialisable dict.
* :attr:`RelaySession.is_expired` correctly reflects the expiry time.

All tests use an in-memory SQLite database with ``StaticPool`` so that a
single connection is shared across sessions within one test.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.database import Base, configure_test_engine
from gateway.models import ApiKeyPool, License, RelaySession, UsageRecord


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
async def db_session() -> AsyncSession:
    """Yield an :class:`AsyncSession` backed by in-memory SQLite.

    Tables are created before and dropped after each test for isolation.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    configure_test_engine(engine)

    # Import models so Base.metadata is populated.
    import gateway.models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from gateway.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    # Reset the global engine so subsequent tests get a fresh one.
    import gateway.database as db_mod

    db_mod._engine = None
    db_mod._session_factory = None


# ── License model tests (§3.2) ─────────────────────────────────────


class TestLicenseModel:
    """Tests for the :class:`License` ORM model."""

    async def test_table_name(self):
        """Table name is ``licenses``."""
        assert License.__tablename__ == "licenses"

    async def test_create_license(self, db_session: AsyncSession):
        """A license can be inserted and retrieved."""
        lic = License(
            id="lic-001",
            user_id="user-001",
            license_key="PL-PRO-A1B2-C3D4-E5F6",
            plan_type="pro",
            expires_at=datetime.now(timezone.utc) + timedelta(days=365),
        )
        db_session.add(lic)
        await db_session.commit()

        result = await db_session.execute(
            select(License).where(License.id == "lic-001")
        )
        fetched = result.scalar_one()
        assert fetched.license_key == "PL-PRO-A1B2-C3D4-E5F6"
        assert fetched.plan_type == "pro"
        assert fetched.status == "active"
        assert fetched.user_id == "user-001"

    async def test_default_values(self, db_session: AsyncSession):
        """Default quota and status values are applied."""
        lic = License(
            id="lic-002",
            user_id="user-002",
            license_key="PL-PRO-0000-0000-0001",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(lic)
        await db_session.commit()
        await db_session.refresh(lic)

        assert lic.quota_limit_tokens == 500000
        assert lic.quota_used_tokens == 0
        assert lic.quota_limit_media == 200
        assert lic.quota_used_media == 0
        assert lic.status == "active"
        assert lic.plan_type == "pro"
        assert lic.created_at is not None
        assert lic.updated_at is not None

    async def test_device_fingerprint_nullable(self, db_session: AsyncSession):
        """device_fingerprint is nullable (not yet bound)."""
        lic = License(
            id="lic-003",
            user_id="user-003",
            license_key="PL-PRO-0000-0000-0002",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db_session.add(lic)
        await db_session.commit()
        await db_session.refresh(lic)
        assert lic.device_fingerprint is None

    async def test_repr(self):
        """__repr__ includes key fields."""
        lic = License(
            id="x",
            license_key="PL-PRO-TEST",
            expires_at=datetime.now(timezone.utc),
        )
        r = repr(lic)
        assert "License" in r
        assert "PL-PRO-TEST" in r


# ── ApiKeyPool model tests (§3.3) ──────────────────────────────────


class TestApiKeyPoolModel:
    """Tests for the :class:`ApiKeyPool` ORM model."""

    async def test_table_name(self):
        """Table name is ``api_key_pool``."""
        assert ApiKeyPool.__tablename__ == "api_key_pool"

    async def test_create_api_key(self, db_session: AsyncSession):
        """An API key entry can be inserted and retrieved."""
        entry = ApiKeyPool(
            id="key-001",
            provider="deepseek",
            api_key_encrypted="ENC:encrypted_data_here",
            base_weight=100,
            health_score=Decimal("1.00"),
        )
        db_session.add(entry)
        await db_session.commit()

        result = await db_session.execute(
            select(ApiKeyPool).where(ApiKeyPool.id == "key-001")
        )
        fetched = result.scalar_one()
        assert fetched.provider == "deepseek"
        assert fetched.api_key_encrypted == "ENC:encrypted_data_here"
        assert fetched.base_weight == 100
        assert fetched.health_score == Decimal("1.00")
        assert fetched.status == "active"

    async def test_default_values(self, db_session: AsyncSession):
        """Default weight, health_score, and statistics are applied."""
        entry = ApiKeyPool(
            id="key-002",
            provider="openai",
            api_key_encrypted="ENC:test",
        )
        db_session.add(entry)
        await db_session.commit()
        await db_session.refresh(entry)

        assert entry.base_weight == 100
        assert entry.health_score == Decimal("1.00")
        assert entry.total_requests == 0
        assert entry.success_requests == 0
        assert entry.failed_requests == 0
        assert entry.status == "active"
        assert entry.cooldown_until is None
        assert entry.circuit_breaker_until is None

    async def test_repr(self):
        """__repr__ includes key fields."""
        entry = ApiKeyPool(
            id="k",
            provider="deepseek",
            api_key_encrypted="ENC:x",
        )
        r = repr(entry)
        assert "ApiKeyPool" in r
        assert "deepseek" in r


# ── UsageRecord model tests (§3.4) ─────────────────────────────────


class TestUsageRecordModel:
    """Tests for the :class:`UsageRecord` ORM model."""

    async def test_table_name(self):
        """Table name is ``usage_records``."""
        assert UsageRecord.__tablename__ == "usage_records"

    async def test_create_usage_record(self, db_session: AsyncSession):
        """A usage record can be inserted and retrieved."""
        rec = UsageRecord(
            user_id="user-001",
            provider="deepseek",
            model="deepseek-chat",
            request_type="llm",
            tokens_in=150,
            tokens_out=80,
            cost=Decimal("0.000230"),
            latency_ms=850,
            status="success",
        )
        db_session.add(rec)
        await db_session.commit()

        result = await db_session.execute(
            select(UsageRecord).where(UsageRecord.user_id == "user-001")
        )
        fetched = result.scalar_one()
        assert fetched.provider == "deepseek"
        assert fetched.model == "deepseek-chat"
        assert fetched.request_type == "llm"
        assert fetched.tokens_in == 150
        assert fetched.tokens_out == 80
        assert fetched.cost == Decimal("0.000230")
        assert fetched.latency_ms == 850
        assert fetched.status == "success"
        assert fetched.id is not None  # autoincrement PK

    async def test_default_values(self, db_session: AsyncSession):
        """Default token counts and cost are zero."""
        rec = UsageRecord(
            user_id="user-002",
            provider="openai",
            model="gpt-4",
            request_type="llm",
        )
        db_session.add(rec)
        await db_session.commit()
        await db_session.refresh(rec)

        assert rec.tokens_in == 0
        assert rec.tokens_out == 0
        assert rec.cost == Decimal("0")
        assert rec.status == "success"
        assert rec.created_at is not None

    async def test_to_dict(self, db_session: AsyncSession):
        """to_dict returns a JSON-serialisable dict with all fields."""
        rec = UsageRecord(
            user_id="user-003",
            provider="moka_ai",
            model="moka-chat",
            request_type="llm",
            tokens_in=100,
            tokens_out=50,
            cost=Decimal("0.000300"),
            latency_ms=500,
            status="success",
        )
        db_session.add(rec)
        await db_session.commit()
        await db_session.refresh(rec)

        d = rec.to_dict()
        assert d["user_id"] == "user-003"
        assert d["provider"] == "moka_ai"
        assert d["model"] == "moka-chat"
        assert d["request_type"] == "llm"
        assert d["tokens_in"] == 100
        assert d["tokens_out"] == 50
        assert d["cost"] == "0.000300"  # Decimal serialised as string
        assert d["latency_ms"] == 500
        assert d["status"] == "success"
        assert d["id"] is not None
        assert "created_at" in d
        assert isinstance(d["created_at"], str)  # ISO-format string

    async def test_to_dict_none_latency(self, db_session: AsyncSession):
        """to_dict handles nullable latency_ms."""
        rec = UsageRecord(
            user_id="u",
            provider="p",
            model="m",
            request_type="llm",
        )
        db_session.add(rec)
        await db_session.commit()
        await db_session.refresh(rec)

        d = rec.to_dict()
        assert d["latency_ms"] is None

    async def test_repr(self):
        """__repr__ includes key fields."""
        rec = UsageRecord(
            user_id="u1",
            provider="deepseek",
            model="deepseek-chat",
            request_type="llm",
        )
        r = repr(rec)
        assert "UsageRecord" in r
        assert "u1" in r


# ── RelaySession model tests (§3.5) ────────────────────────────────


class TestRelaySessionModel:
    """Tests for the :class:`RelaySession` ORM model."""

    async def test_table_name(self):
        """Table name is ``relay_sessions``."""
        assert RelaySession.__tablename__ == "relay_sessions"

    async def test_create_session(self, db_session: AsyncSession):
        """A relay session can be inserted and retrieved."""
        session = RelaySession(
            id="sess-001",
            user_id="user-001",
            jwt_jti="jti-abc123",
            device_fingerprint="sha256:abcdef",
        )
        db_session.add(session)
        await db_session.commit()

        result = await db_session.execute(
            select(RelaySession).where(RelaySession.id == "sess-001")
        )
        fetched = result.scalar_one()
        assert fetched.user_id == "user-001"
        assert fetched.jwt_jti == "jti-abc123"
        assert fetched.device_fingerprint == "sha256:abcdef"
        assert fetched.status == "active"
        assert fetched.created_at is not None
        assert fetched.expires_at is not None

    async def test_default_expiry_24_hours(self, db_session: AsyncSession):
        """Default expires_at is created_at + 24 hours."""
        session = RelaySession(
            id="sess-002",
            user_id="user-002",
            jwt_jti="jti-def456",
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        delta = session.expires_at - session.created_at
        # Should be approximately 24 hours (within a few seconds tolerance)
        assert timedelta(hours=23, minutes=59) < delta < timedelta(hours=24, minutes=1)

    async def test_is_expired_false_for_future(self, db_session: AsyncSession):
        """is_expired is False when expires_at is in the future."""
        session = RelaySession(
            id="sess-003",
            user_id="user-003",
            jwt_jti="jti-future",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        assert session.is_expired is False

    async def test_is_expired_true_for_past(self, db_session: AsyncSession):
        """is_expired is True when expires_at has passed."""
        session = RelaySession(
            id="sess-004",
            user_id="user-004",
            jwt_jti="jti-past",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        assert session.is_expired is True

    async def test_is_expired_false_for_none(self):
        """is_expired is False when expires_at is None (defensive)."""
        session = RelaySession(
            id="sess-005",
            user_id="user-005",
            jwt_jti="jti-none",
        )
        # Force expires_at to None for the test
        session.expires_at = None
        assert session.is_expired is False

    async def test_is_expired_handles_naive_datetime(self):
        """is_expired handles tz-naive expires_at gracefully."""
        session = RelaySession(
            id="sess-006",
            user_id="user-006",
            jwt_jti="jti-naive",
        )
        # Set a naive past datetime (1 hour ago, no tzinfo)
        session.expires_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
        assert session.is_expired is True

    async def test_repr(self):
        """__repr__ includes key fields."""
        session = RelaySession(
            id="s1",
            user_id="u1",
            jwt_jti="jti1",
        )
        r = repr(session)
        assert "RelaySession" in r
        assert "s1" in r

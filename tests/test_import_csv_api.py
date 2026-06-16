"""Tests for F-08 CSV Import API — POST /api/v1/import/csv.

Validates CSV file upload, parsing, entity creation, and
entity resolution (dedup/merge) behavior.
"""

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
from promiselink.models.entity import Entity
from promiselink.models.event import Event

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


# ── Helpers ──

SAMPLE_CSV = (
    "name,company,title,phone,email,wechat,concern,capability\n"
    "张三,Acme Corp,CEO,13800138000,zhangsan@acme.com,zhangsan_wx,寻找AI创业团队,技术咨询\n"
    "李四,Tech Inc,CTO,13900139000,lisi@tech.com,lisi_wx,需要投资,大模型开发\n"
)

SAMPLE_CSV_MINIMAL = (
    "name\n"
    "王五\n"
)


async def insert_event(session: AsyncSession, **overrides) -> Event:
    data = {
        "id": str(uuid.uuid4()),
        "user_id": TEST_USER_ID,
        "event_type": "meeting",
        "source": "test",
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
        "properties": {"basic": {"company": "Test Corp"}},
        "source_event_id": str(source_event_id),
        "confidence": 0.9,
        "status": "confirmed",
    }
    data.update(overrides)
    entity = Entity(**data)
    session.add(entity)
    await session.flush()
    return entity


# ══════════════════════════════════════════════════════════════════════════════
# CSV Import API Tests
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="CSV Import API is a Pro-only feature",
)
class TestCSVImportBasic:
    """Basic import functionality tests."""

    async def test_import_csv_returns_200(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200

    async def test_import_csv_statistics(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        data = resp.json()
        assert data["imported_count"] == 2
        assert data["created_entities"] == 2

    async def test_import_csv_minimal_columns(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV_MINIMAL.encode("utf-8"), "text/csv")},
        )
        data = resp.json()
        assert data["imported_count"] == 1
        assert data["created_entities"] == 1

    async def test_import_creates_entities(self, client: AsyncClient, db_session: AsyncSession):
        await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        await db_session.commit()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Entity).where(Entity.user_id == TEST_USER_ID)
        )
        entities = result.scalars().all()
        names = {e.name for e in entities}
        assert "张三" in names
        assert "李四" in names

    async def test_import_entity_properties(self, client: AsyncClient, db_session: AsyncSession):
        await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        await db_session.commit()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Entity).where(Entity.name == "张三", Entity.user_id == TEST_USER_ID)
        )
        entity = result.scalar_one()
        props = entity.properties or {}
        assert props["basic"]["company"] == "Acme Corp"
        assert props["basic"]["title"] == "CEO"
        assert props["basic"]["phone"] == "13800138000"
        assert props["basic"]["email"] == "zhangsan@acme.com"
        assert props["basic"]["wechat"] == "zhangsan_wx"
        assert props["concern"] == "寻找AI创业团队"
        assert props["capability"] == "技术咨询"


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="CSV Import API is a Pro-only feature",
)
class TestCSVImportValidation:
    """Input validation tests."""

    async def test_reject_non_csv_file(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("data.xlsx", b"fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    async def test_reject_empty_file(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("empty.csv", b"", "text/csv")},
        )
        assert resp.status_code == 400

    async def test_reject_csv_without_name_column(self, client: AsyncClient):
        csv_data = b"company,title\nAcme,CEO\n"
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("noname.csv", csv_data, "text/csv")},
        )
        assert resp.status_code == 400

    async def test_skip_rows_without_name(self, client: AsyncClient):
        csv_data = "name,company\n,Acme Corp\n张三,Tech Inc\n".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("skip.csv", csv_data, "text/csv")},
        )
        data = resp.json()
        # Row with empty name is counted in imported_count but not created
        assert data["imported_count"] == 2
        assert data["created_entities"] == 1

    async def test_skip_empty_rows(self, client: AsyncClient):
        csv_data = "name,company\n张三,Acme\n,\n李四,Tech\n".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("empty_rows.csv", csv_data, "text/csv")},
        )
        data = resp.json()
        assert data["imported_count"] == 2
        assert data["created_entities"] == 2


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="CSV Import API is a Pro-only feature",
)
class TestCSVImportEncoding:
    """Encoding handling tests."""

    async def test_utf8_encoding(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("utf8.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["created_entities"] == 2

    async def test_gbk_encoding(self, client: AsyncClient):
        gbk_data = (
            "name,company,title\n"
            "王五,测试公司,工程师\n"
        ).encode("gbk")
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("gbk.csv", gbk_data, "text/csv")},
        )
        assert resp.status_code == 200
        assert resp.json()["created_entities"] == 1


@pytest.mark.skipif(
    os.environ.get("APP_EDITION", "basic") != "pro",
    reason="CSV Import API is a Pro-only feature",
)
class TestCSVImportDedup:
    """Entity resolution / dedup tests."""

    async def test_merge_duplicate_name(self, client: AsyncClient, db_session: AsyncSession):
        # First import
        await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("first.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        await db_session.commit()

        # Second import with same name should merge
        csv_dup = (
            "name,company,title,phone\n"
            "张三,Acme Corp,CTO,13800138001\n"
        )
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("dup.csv", csv_dup.encode("utf-8"), "text/csv")},
        )
        data = resp.json()
        # Same name + same company → exact match → merge
        assert "merged" in data["message"] or data["created_entities"] == 0

    async def test_create_different_name(self, client: AsyncClient, db_session: AsyncSession):
        # First import
        await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("first.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        await db_session.commit()

        # Different name → create new
        csv_new = (
            "name,company,title\n"
            "赵六,New Corp,PM\n"
        )
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("new.csv", csv_new.encode("utf-8"), "text/csv")},
        )
        data = resp.json()
        assert data["created_entities"] == 1

    async def test_import_creates_source_event(self, client: AsyncClient, db_session: AsyncSession):
        resp = await client.post(
            f"{API_PREFIX}/import/csv",
            files={"file": ("contacts.csv", SAMPLE_CSV.encode("utf-8"), "text/csv")},
        )
        assert resp.status_code == 200
        await db_session.commit()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Event).where(
                Event.user_id == TEST_USER_ID,
                Event.source == "csv_import",
            )
        )
        events = result.scalars().all()
        assert len(events) == 1
        assert "contacts.csv" in events[0].title

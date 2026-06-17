"""Shared test fixtures for PromiseLink tests."""

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force IS_SQLITE=True BEFORE importing models, so column types use String(36)
os.environ.setdefault("DATABASE_URL", "sqlite://")

from promiselink.database import Base


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset in-memory rate limiter state before each test."""
    from promiselink.core.rate_limiter import reset_rate_limits
    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite async session for testing.

    Re-creates all tables with SQLite-compatible column types.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Disable foreign keys for SQLite in tests
    # (test data often references non-existent parent records for isolation)
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def auth_headers():
    """Provide authenticated headers for API tests."""
    from promiselink.core.auth import create_access_token

    token = create_access_token(user_id="test-user-001")
    return {"Authorization": f"Bearer {token}"}


def make_user_id() -> str:
    return str(uuid.uuid4())


async def create_test_event(
    session: AsyncSession,
    user_id: str | None = None,
    event_type: str = "meeting",
    raw_text: str = "Test event",
    source: str = "test",
    title: str = "Test Event",
):
    """Create a test Event record for foreign key references.

    Must be called within an active session/transaction.
    """
    from promiselink.models.event import Event

    event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id or make_user_id(),
        event_type=event_type,
        source=source,
        title=title,
        raw_text=raw_text,
        status="completed",
    )
    session.add(event)
    await session.flush()
    return event


def make_entity_data(
    name: str = "张三",
    company: str = "智源AI",
    title: str = "CEO",
    city: str = "北京",
    industry: str = "人工智能",
    entity_type: str = "person",
) -> dict:
    return {
        "name": name,
        "company": company,
        "title": title,
        "city": city,
        "industry": industry,
        "entity_type": entity_type,
        "properties": {
            "basic": {
                "company": company,
                "title": title,
                "city": city,
                "industry": industry,
            }
        },
    }

"""Shared test fixtures for EventLink tests."""

import os
import uuid

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Force IS_SQLITE=True BEFORE importing models, so column types use String(36)
os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")

from eventlink.database import Base


@pytest_asyncio.fixture
async def db_session():
    """Create an in-memory SQLite async session for testing.

    Re-creates all tables with SQLite-compatible column types.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Enable foreign keys for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
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


def make_user_id() -> str:
    return str(uuid.uuid4())


async def create_test_event(
    session: AsyncSession,
    user_id: str | None = None,
    event_type: str = "meeting",
    raw_text: str = "Test event",
    source: str = "test",
    title: str = "Test Event",
) -> "Event":
    """Create a test Event record for foreign key references.

    Must be called within an active session/transaction.
    """
    from eventlink.models.event import Event

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

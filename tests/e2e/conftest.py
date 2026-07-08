"""Fixtures for e2e tests with real-structured LLM responses.

Provides a file-based SQLite DB + session factory so the pipeline's
``AsyncSessionLocal`` can be patched to use an isolated test database
(each step opens its own session via ``AsyncSessionLocal()``).
"""

import uuid

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.database import Base


@pytest_asyncio.fixture
async def file_db(tmp_path):
    """Create a real SQLite file DB with a session factory for pipeline e2e tests.

    Returns (session, db_path, session_factory, engine). The session is a
    long-lived session for test setup/verification; the session_factory is
    meant to be patched onto ``promiselink.database.AsyncSessionLocal`` so
    pipeline steps open their own short-lived sessions on the same engine.
    """
    db_path = str(tmp_path / "e2e_real_llm.db")
    url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session, db_path, session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def make_user_id() -> str:
    """Generate a random user ID for test isolation."""
    return str(uuid.uuid4())

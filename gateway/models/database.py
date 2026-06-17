"""Database connection management (async SQLAlchemy 2.0).

Provides an async engine and session factory. For testing, the engine can be
swapped to an in-memory SQLite instance.
"""

from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gateway.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Return the global async engine, creating it on first call."""
    global _engine
    if _engine is None:
        s = settings or get_settings()
        _engine = create_async_engine(
            s.database_url,
            echo=False,
            pool_pre_ping=True,
        )
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(settings),
            expire_on_commit=False,
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield an async DB session."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def init_db(engine: AsyncEngine | None = None) -> None:
    """Create all tables (used in tests and startup)."""
    from gateway.models.tables import Base

    eng = engine or get_engine()
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose the engine (used on shutdown)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def set_engine(engine: AsyncEngine) -> None:
    """Override the global engine (for testing)."""
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(engine, expire_on_commit=False)

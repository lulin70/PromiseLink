"""PostgreSQL async database connection for the gateway.

Uses SQLAlchemy 2.0 async with asyncpg driver.  All models inherit from
:class:`Base` which is exported here so Alembic and tests can discover the
full metadata.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from gateway.config import get_settings


class Base(DeclarativeBase):
    """Declarative base for all gateway ORM models."""

    pass


# Module-level placeholders; lazily initialised so importing this module
# never triggers a database connection (important for unit tests).
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Return the global async engine, creating it on first call."""
    global _engine
    if _engine is None:
        settings = get_settings()
        engine_kwargs: dict[str, Any] = {
            "echo": settings.gateway_env == "development",
        }
        # SQLite (used in tests) does not accept pool_size / max_overflow.
        if not settings.database_url.startswith("sqlite"):
            engine_kwargs["pool_size"] = settings.pg_pool_size
            engine_kwargs["max_overflow"] = settings.pg_max_overflow
            engine_kwargs["pool_pre_ping"] = True
        _engine = create_async_engine(settings.database_url, **engine_kwargs)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, creating it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an :class:`AsyncSession`."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Create all tables (development / test convenience)."""
    # Import models so they register with Base.metadata.
    import gateway.models  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Dispose of the engine connection pool."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def configure_test_engine(engine: AsyncEngine) -> None:
    """Override the global engine for testing purposes.

    Tests that need an in-memory SQLite engine can call this to inject
    their own engine before any session is created.
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Re-export Any for type-checker friendliness in downstream modules.
__all__ = [
    "Any",
    "AsyncSession",
    "Base",
    "close_db",
    "configure_test_engine",
    "get_db",
    "get_engine",
    "get_session_factory",
    "init_db",
]

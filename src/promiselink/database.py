"""Database connection and session management."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Generator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from promiselink.config import get_settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.database")

# Per-user locks to serialize pipeline write operations.
# SQLite only supports one concurrent writer; without this, concurrent
# pipeline executions cause "database is locked" errors and data loss.
# Per-user locking allows different users to process events concurrently
# while still serializing writes within a single user's pipeline.
_pipeline_locks: dict[str, asyncio.Lock] = {}

settings = get_settings()


# ── Dialect detection (used by models for SQLite/PG compatibility) ──

def _is_sqlite() -> bool:
    """Detect if current dialect is SQLite based on config URL."""
    return settings.database_url.startswith("sqlite")


IS_SQLITE = _is_sqlite()


def _uuid_default() -> str | uuid.UUID:
    """Generate a default UUID value compatible with current dialect."""
    if IS_SQLITE:
        return str(uuid.uuid4())
    return uuid.uuid4()


# Base class for all models
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# Sync engine for migrations
def get_sync_engine() -> Any:
    """Get synchronous engine for Alembic migrations."""
    url = settings.database_url
    if url.startswith("sqlite"):
        # SQLite-specific settings: WAL mode + busy_timeout for concurrency
        engine = create_engine(url, connect_args={"check_same_thread": False}, echo=settings.debug)

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
        engine = create_engine(url, echo=settings.debug, pool_pre_ping=True)

    return engine


# Sync session maker (for migrations and simple scripts)
sync_engine = get_sync_engine()
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def get_sync_session() -> Generator[Session, None, None]:
    """Get synchronous database session."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


# Async engine for FastAPI
def get_async_engine() -> Any:
    """Get asynchronous engine for FastAPI."""
    url = settings.database_url

    # Convert SQLite URL to async format
    if url.startswith("sqlite"):
        if "+aiosqlite" not in url:
            url = url.replace("sqlite://", "sqlite+aiosqlite://")
        engine = create_async_engine(url, echo=settings.debug, connect_args={"check_same_thread": False})

        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn: Any, connection_record: Any) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
        # PostgreSQL async
        if "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://")
        engine = create_async_engine(url, echo=settings.debug, pool_pre_ping=True)

    return engine


async_engine = get_async_engine()
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Get asynchronous database session for dependency injection."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context() -> AsyncIterator[AsyncSession]:
    """Get database session as async context manager."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except SQLAlchemyError:
            await session.rollback()
            raise


async def commit_with_retry(
    session: AsyncSession,
    max_retries: int = 3,
    base_delay: float = 0.5,
) -> None:
    """Commit session with exponential backoff retry for SQLite lock contention.

    When multiple pipeline steps or concurrent requests write to SQLite,
    ``session.commit()`` can raise ``OperationalError: database is locked``.
    This helper retries with exponential backoff so transient lock contention
    does not cause data loss.

    Args:
        session: The async session to commit.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Base delay in seconds for exponential backoff (default 0.5s).
    """
    for attempt in range(max_retries + 1):
        try:
            await session.commit()
            return
        except OperationalError as e:
            if "database is locked" not in str(e).lower() or attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "database_locked_retry",
                attempt=attempt + 1,
                max_retries=max_retries,
                delay=delay,
                error=str(e),
            )
            await asyncio.sleep(delay)
            await session.rollback()


def get_pipeline_lock(user_id: str = "") -> asyncio.Lock:
    """Return the per-user pipeline write lock.

    Pipeline entry points should acquire this lock before processing events
    to prevent concurrent SQLite write operations that cause data loss.
    Per-user locking allows different users to process events concurrently.
    For PostgreSQL (Phase 1+), this lock can be removed.
    """
    if user_id not in _pipeline_locks:
        _pipeline_locks[user_id] = asyncio.Lock()
    return _pipeline_locks[user_id]


async def init_db() -> None:
    """Initialize database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await async_engine.dispose()

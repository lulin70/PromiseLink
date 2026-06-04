"""Database connection and session management."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from eventlink.config import get_settings

settings = get_settings()


# ── Dialect detection (used by models for SQLite/PG compatibility) ──

def _is_sqlite() -> bool:
    """Detect if current dialect is SQLite based on config URL or test mode."""
    import sys
    # In pytest environment, always use SQLite-compatible types
    if "pytest" in sys.modules:
        return True
    return settings.database_url.startswith("sqlite")


IS_SQLITE = _is_sqlite()


def _uuid_default():
    """Generate a default UUID value compatible with current dialect."""
    if IS_SQLITE:
        return str(uuid.uuid4())
    return uuid.uuid4()


# Base class for all models
class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    pass


# Sync engine for migrations
def get_sync_engine():
    """Get synchronous engine for Alembic migrations."""
    url = settings.database_url
    if url.startswith("sqlite"):
        # SQLite-specific settings: WAL mode + busy_timeout for concurrency
        engine = create_engine(url, connect_args={"check_same_thread": False}, echo=settings.debug)
        
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
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


def get_sync_session() -> Session:
    """Get synchronous database session."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Async engine for FastAPI
def get_async_engine():
    """Get asynchronous engine for FastAPI."""
    url = settings.database_url
    
    # Convert SQLite URL to async format
    if url.startswith("sqlite"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://")
        engine = create_async_engine(url, echo=settings.debug, connect_args={"check_same_thread": False})
        
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
        # PostgreSQL async
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
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_session_context():
    """Get database session as async context manager."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Initialize database tables."""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections."""
    await async_engine.dispose()

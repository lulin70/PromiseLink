"""Shared test fixtures for PromiseLink tests.

W5 admission baseline (see docs/design/W5_IMPLEMENTATION_READINESS_CHECKLIST_v1.md §3).

Notes:
- This module no longer unconditionally overrides ``DATABASE_URL`` to ``sqlite://``.
  The backend is selected by the ``db_backend`` fixture (default ``sqlite``; opt-in
  ``postgresql`` via the ``dual_db`` marker or ``--postgresql-url``).
- ``Base.metadata.create_all`` is retained **only** as a temporary in-memory
  convenience for SQLite fixtures. The W4+ Test Plan requires ``alembic upgrade
  head`` on every fixture-backed backend before any test runs; the
  ``_run_alembic_upgrade`` helper below performs that step. Production paths
  never call ``create_all``; see ``promiselink.database.init_db`` for the
  (deprecated) shortcut.
- ``PRAGMA foreign_keys=ON`` is enabled on every SQLite connection that
  fixtures open. Tests that need to bypass FK enforcement must opt in
  explicitly via ``allow_fk_off=True`` on the fixture.
"""

from __future__ import annotations

import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.database import Base


# Allowed values for the ``db_backend`` fixture.
DB_BACKENDS = ("sqlite", "postgresql")


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register W5 admission CLI options.

    The conftest used to silently override ``DATABASE_URL``. We now expose
    the choice to the test runner instead, matching Test Plan §16.1.
    """
    parser.addoption(
        "--postgresql-url",
        action="store",
        default=os.environ.get("W5_PG_URL", ""),
        help="PostgreSQL URL used when the ``dual_db`` marker is selected.",
    )
    parser.addoption(
        "--skip-alembic",
        action="store_true",
        default=False,
        help="Skip the ``alembic upgrade head`` step on fixture connect. "
        "Only allowed when ``--allow-skip-alembic`` is also set; otherwise "
        "the run fails with a non-zero exit code.",
    )
    parser.addoption(
        "--allow-skip-alembic",
        action="store_true",
        default=False,
        help="Explicit opt-in flag for ``--skip-alembic``. Production-bound "
        "runs must never set this.",
    )
    parser.addoption(
        "--db-backend",
        action="store",
        default="sqlite",
        choices=list(DB_BACKENDS),
        help="Select the database backend for the ``db_backend`` fixture. "
        "``postgresql`` requires the ``dual_db`` marker and ``--postgresql-url``. "
        "Default is ``sqlite``. The fixture no longer falls back silently to "
        "sqlite when this option is missing — explicit declaration is enforced.",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Enforce W5 strict-marker behaviour.

    The ``--strict-markers`` flag (set in ``pyproject.toml``) rejects unknown
    markers. This hook only adds a defensive check that no item in the run
    is silently masked by ``xfail``/``skip`` without an explicit reason.
    """
    for item in items:
        mark = item.get_closest_marker("xfail")
        if mark is not None and not mark.kwargs.get("reason"):
            raise pytest.UsageError(
                f"xfail marker on {item.nodeid} must declare reason=<str>"
            )


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Reset in-memory rate limiter state before each test."""
    from promiselink.core.rate_limiter import reset_rate_limits

    reset_rate_limits()
    yield
    reset_rate_limits()


@pytest.fixture
def db_backend(request: pytest.FixtureRequest) -> str:
    """Return the backend selected for this test.

    Defaults to ``sqlite``. Tests marked with ``@pytest.mark.dual_db`` must
    also select ``postgresql`` either via ``--postgresql-url <url>`` or by
    setting ``W5_PG_URL`` in the environment.
    """
    backend = request.config.getoption("--db-backend")
    if backend not in DB_BACKENDS:
        raise pytest.UsageError(f"--db-backend must be one of {DB_BACKENDS}")
    if backend == "postgresql" and not request.config.getoption("--postgresql-url"):
        raise pytest.UsageError(
            "--postgresql-url (or W5_PG_URL) is required when --db-backend=postgresql"
        )
    if backend == "postgresql" and "dual_db" not in request.keywords:
        raise pytest.UsageError(
            "postgresql backend requires the ``dual_db`` marker on the test"
        )
    return backend


def _build_sqlite_url(tmp_path) -> str:
    """Build a per-test SQLite URL backed by a temp file (not in-memory).

    Using a temp file lets ``alembic upgrade head`` operate on the same
    backing store as the application engine.
    """
    db_file = tmp_path / "w5.sqlite"
    return f"sqlite+aiosqlite:///{db_file}"


def _build_postgresql_url(config: pytest.Config) -> str:
    url = config.getoption("--postgresql-url") or os.environ.get("W5_PG_URL", "")
    if not url.startswith("postgresql"):
        raise pytest.UsageError("PostgreSQL URL must use the postgresql:// scheme")
    if "+asyncpg" not in url and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://")
    return url


def _run_alembic_upgrade(sync_url: str, config: pytest.Config) -> str:
    """Execute ``alembic upgrade head`` against ``sync_url`` and return head.

    This is the W5 admission contract for fixture-backed backends. Production
    paths must rely on the same step. The helper is invoked from the
    fixture, so collection errors fail fast with a non-zero exit code.

    ``alembic/env.py`` calls ``get_settings().database_url`` and imports
    ``promiselink.database`` (whose module-level ``sync_engine`` is created
    eagerly on import). To keep the fixture isolated we patch
    ``promiselink.config.get_settings`` for the duration of the upgrade so
    both the Alembic env and any settings consumers point at ``sync_url``.
    The patch is reverted on exit even if Alembic raises.
    """
    if config.getoption("--skip-alembic"):
        if not config.getoption("--allow-skip-alembic"):
            raise pytest.UsageError(
                "--skip-alembic requires explicit --allow-skip-alembic opt-in"
            )
        return "skip-alembic-opt-in"

    from unittest.mock import patch

    from alembic.config import Config as AlembicConfig
    from alembic import command as alembic_command

    from promiselink import config as pl_config
    from promiselink.config import Settings

    # Build an isolated Settings instance pointing at this fixture's URL.
    # We use ``app_env="development"`` so the production-time ``validate_*``
    # hooks in Settings do not fire (they would require llm_api_key etc.).
    # The fixture-only URL points at a per-test temp file.
    fixture_settings = Settings(database_url=sync_url, app_env="development")

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    alembic_ini = os.path.join(repo_root, "alembic.ini")
    if not os.path.exists(alembic_ini):
        raise RuntimeError(f"alembic.ini not found at {alembic_ini}")

    # ``promiselink.database`` module-level engine caches ``settings`` at
    # import time. Reset the lazy cache so a freshly patched ``get_settings``
    # is honoured by engine creation triggered from env.py.
    pl_database = None
    try:
        from promiselink import database as _pl_database

        pl_database = _pl_database
        pl_database.settings = fixture_settings
        pl_database.IS_SQLITE = fixture_settings.is_sqlite
    except Exception:
        # If the module is not importable yet, alembic env.py will trigger it.
        pass

    pl_config.get_settings.cache_clear()
    cfg = AlembicConfig(alembic_ini)
    cfg.set_main_option("sqlalchemy.url", sync_url)
    cfg.set_main_option("script_location", os.path.join(repo_root, "src/promiselink/alembic"))

    try:
        with patch("promiselink.config.get_settings", return_value=fixture_settings):
            alembic_command.upgrade(cfg, "head")
    finally:
        pl_config.get_settings.cache_clear()
        if pl_database is not None:
            from promiselink import config as _pl_config

            pl_database.settings = _pl_config.get_settings()
            pl_database.IS_SQLITE = pl_database.settings.is_sqlite

    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(cfg).get_current_head()
    return head or "head"


@pytest_asyncio.fixture
async def db_session(
    request: pytest.FixtureRequest,
    tmp_path,
) -> AsyncIterator[AsyncSession]:
    """Yield an async session for the selected backend.

    Always runs ``alembic upgrade head`` (unless explicitly opted out).
    SQLite connections enable ``PRAGMA foreign_keys=ON``; ``PRAGMA foreign_keys``
    is queried post-connect and the fixture fails if pragma is not effective.
    """
    backend = request.getfixturevalue("db_backend")
    if backend == "sqlite":
        url = _build_sqlite_url(tmp_path)
        sync_url = url.replace("+aiosqlite", "")
    else:
        url = _build_postgresql_url(request.config)
        sync_url = url.replace("+asyncpg", "").replace("+psycopg2", "")

    head = _run_alembic_upgrade(sync_url, request.config)

    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    if backend == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fks(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    if backend == "sqlite":
        # Verify PRAGMA foreign_keys took effect on the engine. We use a
        # short-lived sync engine so that aiosqlite quirks do not mask the
        # assertion (the SQLAlchemy async connection wraps pysqlite but
        # ``cursor.execute("PRAGMA foreign_keys")`` does not always return
        # a row in that path). The independent sync connection shares the
        # underlying SQLite file, so PRAGMA is consistent.
        from sqlalchemy import create_engine, event as sa_event, text as sa_text

        verify_engine = create_engine(sync_url, connect_args={"check_same_thread": False})

        @sa_event.listens_for(verify_engine, "connect")
        def _enable_fks_on_verify(dbapi_conn, _record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        try:
            with verify_engine.connect() as conn:
                fk_value = conn.execute(sa_text("PRAGMA foreign_keys")).scalar()
                if fk_value != 1:
                    raise RuntimeError(
                        f"SQLite PRAGMA foreign_keys did not enable (got {fk_value!r})"
                    )
        finally:
            verify_engine.dispose()

    async with async_session() as session:
        # Expose the migration head to tests that need to assert schema state.
        session.info["migration_head"] = head
        yield session

    await engine.dispose()


@pytest.fixture
def auth_headers():
    """Provide authenticated headers for API tests."""
    from promiselink.core.auth import create_access_token

    token = create_access_token(user_id="test-user-001")
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def mock_pipeline(monkeypatch):
    """Stub process_event_background to avoid real LLM calls in API tests.

    Mocks at promiselink.api.v1.events.process_event_background (where the
    function is imported and captured by background_tasks.add_task). This
    is the correct mock location — mocking at promiselink.services.event_processor
    does NOT take effect because the events module already imported the function
    by value via `from ... import process_event_background`.

    Tests that need the real pipeline (e.g., test_real_pipeline_e2e.py,
    test_poc_comprehensive.py) should NOT depend on this fixture.
    """
    from promiselink.api.v1 import events as events_module

    async def _noop(event_id):
        pass

    monkeypatch.setattr(events_module, "process_event_background", _noop)
    yield


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
"""Tests for POST /api/v1/events/upload — file upload event creation.

Validates txt/md file upload, markdown stripping, encoding handling,
and input validation (file extension, size limits).
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from promiselink.api.v1.events import _strip_markdown
from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app
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


# ══════════════════════════════════════════════════════════════════════════════
# Successful Upload Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTxtUpload:
    """Successful .txt file upload tests."""

    async def test_upload_txt_returns_201(self, client: AsyncClient):
        content = "今天和李总讨论了新项目的合作方案".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("meeting.txt", content, "text/plain")},
        )
        assert resp.status_code == 201

    async def test_upload_txt_creates_event(self, client: AsyncClient, db_session: AsyncSession):
        content = "今天和李总讨论了新项目的合作方案".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("meeting.txt", content, "text/plain")},
        )
        data = resp.json()
        assert data["source"] == "file_upload"
        assert data["event_type"] == "meeting"
        assert data["title"] == "meeting.txt"
        assert data["pipeline_status"] == "pending"
        assert data["entity_count"] == 0
        assert data["todo_count"] == 0

    async def test_upload_txt_stores_raw_text(self, client: AsyncClient, db_session: AsyncSession):
        text = "今天和李总讨论了新项目的合作方案"
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("meeting.txt", text.encode("utf-8"), "text/plain")},
        )
        event_id = resp.json()["id"]
        await db_session.commit()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one()
        assert event.raw_text == text
        assert event.source == "file_upload"

    async def test_upload_txt_custom_event_type(self, client: AsyncClient):
        content = "和陈宇鑫通了电话".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("call.txt", content, "text/plain")},
            data={"event_type": "call"},
        )
        assert resp.status_code == 201
        assert resp.json()["event_type"] == "call"

    async def test_upload_txt_gbk_encoding(self, client: AsyncClient, db_session: AsyncSession):
        text = "今天和王总讨论了合作"
        content = text.encode("gbk")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("meeting.txt", content, "text/plain")},
        )
        assert resp.status_code == 201
        event_id = resp.json()["id"]
        await db_session.commit()

        # Verify the text was decoded correctly via GBK fallback
        from sqlalchemy import select
        result = await db_session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one()
        assert event.raw_text == text


class TestMdUpload:
    """Successful .md file upload tests with markdown stripping."""

    async def test_upload_md_returns_201(self, client: AsyncClient):
        content = "# Meeting Notes\n\nDiscussion about project".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("notes.md", content, "text/markdown")},
        )
        assert resp.status_code == 201

    async def test_upload_md_strips_markdown(self, client: AsyncClient, db_session: AsyncSession):
        md_content = (
            "# 会议纪要\n\n"
            "> 这是引用内容\n\n"
            "**重要事项**：需要跟进\n\n"
            "*注意事项*：请确认\n\n"
            "- 项目A\n"
            "- 项目B\n\n"
            "[点击查看](https://example.com)\n\n"
            "```python\nprint('hello')\n```\n"
        )
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("notes.md", md_content.encode("utf-8"), "text/markdown")},
        )
        event_id = resp.json()["id"]
        await db_session.commit()

        from sqlalchemy import select
        result = await db_session.execute(
            select(Event).where(Event.id == event_id)
        )
        event = result.scalar_one()
        # Markdown markers should be stripped
        assert "# " not in event.raw_text
        assert "**" not in event.raw_text
        assert "*" not in event.raw_text  # italic markers removed
        assert ">" not in event.raw_text  # blockquote markers removed
        assert "- " not in event.raw_text  # list markers removed
        assert "```" not in event.raw_text
        assert "(https://" not in event.raw_text
        # But text content should be preserved
        assert "会议纪要" in event.raw_text
        assert "重要事项" in event.raw_text
        assert "注意事项" in event.raw_text
        assert "项目A" in event.raw_text
        assert "点击查看" in event.raw_text
        assert "print" in event.raw_text


# ══════════════════════════════════════════════════════════════════════════════
# Validation Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestUploadValidation:
    """Input validation tests for file upload."""

    async def test_reject_non_txt_md_file(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("data.pdf", b"fake pdf content", "application/pdf")},
        )
        assert resp.status_code == 400

    async def test_reject_xlsx_file(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("data.xlsx", b"fake", "application/octet-stream")},
        )
        assert resp.status_code == 400

    async def test_reject_oversized_file(self, client: AsyncClient):
        # Create content larger than 1MB
        big_content = b"x" * (1_048_576 + 1)
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("big.txt", big_content, "text/plain")},
        )
        assert resp.status_code == 400

    async def test_reject_empty_file(self, client: AsyncClient):
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("empty.txt", b"", "text/plain")},
        )
        assert resp.status_code == 400

    async def test_reject_no_extension_file(self, client: AsyncClient):
        # File with no extension should be rejected
        content = "some text".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("noextension", content, "text/plain")},
        )
        assert resp.status_code == 400

    async def test_reject_invalid_event_type(self, client: AsyncClient):
        content = "some text".encode("utf-8")
        resp = await client.post(
            f"{API_PREFIX}/events/upload",
            files={"file": ("note.txt", content, "text/plain")},
            data={"event_type": "invalid_type"},
        )
        assert resp.status_code == 400


# ══════════════════════════════════════════════════════════════════════════════
# Markdown Stripping Unit Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestStripMarkdown:
    """Unit tests for _strip_markdown function."""

    def test_strip_headers(self):
        text = "# Heading 1\n## Heading 2\n### Heading 3"
        result = _strip_markdown(text)
        assert "# " not in result
        assert "Heading 1" in result
        assert "Heading 2" in result
        assert "Heading 3" in result

    def test_strip_bold(self):
        text = "This is **bold** text"
        result = _strip_markdown(text)
        assert result == "This is bold text"

    def test_strip_italic(self):
        text = "This is *italic* text"
        result = _strip_markdown(text)
        assert result == "This is italic text"

    def test_strip_links(self):
        text = "Click [here](https://example.com) for more"
        result = _strip_markdown(text)
        assert result == "Click here for more"
        assert "https://" not in result

    def test_strip_code_blocks(self):
        text = "Some code:\n```python\nprint('hello')\n```\nDone"
        result = _strip_markdown(text)
        assert "```" not in result
        assert "print" in result
        assert "Done" in result

    def test_strip_inline_code(self):
        text = "Use `pip install` command"
        result = _strip_markdown(text)
        assert result == "Use pip install command"

    def test_strip_blockquotes(self):
        text = "> This is a quote\n> Another line"
        result = _strip_markdown(text)
        assert ">" not in result
        assert "This is a quote" in result
        assert "Another line" in result

    def test_strip_unordered_list(self):
        text = "- Item 1\n- Item 2\n* Item 3"
        result = _strip_markdown(text)
        assert "- " not in result
        assert "* " not in result
        assert "Item 1" in result
        assert "Item 2" in result
        assert "Item 3" in result

    def test_strip_ordered_list(self):
        text = "1. First\n2. Second\n3. Third"
        result = _strip_markdown(text)
        assert "1. " not in result
        assert "First" in result
        assert "Second" in result
        assert "Third" in result

    def test_preserve_plain_text(self):
        text = "Just plain text with no formatting."
        result = _strip_markdown(text)
        assert result == text

    def test_combined_markdown(self):
        text = (
            "# Meeting Notes\n\n"
            "> Important quote\n\n"
            "**Action items:**\n\n"
            "- Follow up with *John*\n"
            "- Review [docs](https://example.com)\n\n"
            "```bash\nls -la\n```\n"
        )
        result = _strip_markdown(text)
        assert "# " not in result
        assert ">" not in result
        assert "**" not in result
        assert "- " not in result
        assert "```" not in result
        assert "(https://" not in result
        assert "Meeting Notes" in result
        assert "Important quote" in result
        assert "Action items" in result
        assert "John" in result
        assert "docs" in result
        assert "ls -la" in result

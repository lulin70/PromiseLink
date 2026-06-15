"""Tests for Media API endpoints — ASR, TTS, OCR, OCR-Event."""

import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event as sa_event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from promiselink.core.auth import get_current_user_id
from promiselink.database import Base, get_async_session
from promiselink.main import app


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

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Create an async session bound to the test engine."""
    async_session = AsyncSession(bind=db_engine, expire_on_commit=False)
    yield async_session
    await async_session.close()


@pytest_asyncio.fixture
async def client(db_session):
    """Create an AsyncClient with the test session override."""
    async def override_get_async_session():
        yield db_session

    app.dependency_overrides[get_async_session] = override_get_async_session
    app.dependency_overrides[get_current_user_id] = lambda: TEST_USER_ID

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client():
    """Create an AsyncClient without authentication."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helper ──


def _make_fake_audio_bytes() -> bytes:
    """Create minimal fake mp3 bytes for testing."""
    # Minimal MP3 header bytes (ID3 tag start)
    return b"\xff\xfb\x90\x00" + b"\x00" * 100


def _make_fake_image_bytes() -> bytes:
    """Create minimal fake JPEG bytes for testing."""
    # Minimal JPEG header bytes
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


# ── ASR Tests ──


async def test_asr_endpoint_requires_auth(unauth_client):
    """POST /media/asr without token → 401."""
    fake_audio = _make_fake_audio_bytes()
    response = await unauth_client.post(
        f"{API_PREFIX}/media/asr",
        files={"audio": ("test.mp3", fake_audio, "audio/mpeg")},
    )
    assert response.status_code == 401


@patch("promiselink.api.v1.media.ASRService")
async def test_asr_endpoint_with_mock(mock_asr_cls, client):
    """POST /media/asr with mock ASR service returns correct structure."""
    from promiselink.services.asr_service import ASRResult

    mock_service = MagicMock()
    mock_service.transcribe = AsyncMock(
        return_value=ASRResult(text="你好世界", confidence=0.95, provider="moka_ai")
    )
    mock_service.close = AsyncMock()
    mock_asr_cls.return_value = mock_service

    fake_audio = _make_fake_audio_bytes()
    response = await client.post(
        f"{API_PREFIX}/media/asr",
        files={"audio": ("test.mp3", fake_audio, "audio/mpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "你好世界"
    assert data["confidence"] == 0.95
    assert data["provider"] == "moka_ai"


# ── TTS Tests ──


async def test_tts_endpoint_requires_auth(unauth_client):
    """POST /media/tts without token → 401."""
    response = await unauth_client.post(
        f"{API_PREFIX}/media/tts",
        json={"text": "你好"},
    )
    assert response.status_code == 401


@patch("promiselink.api.v1.media.TTSService")
async def test_tts_endpoint_with_mock(mock_tts_cls, client):
    """POST /media/tts with mock TTS service returns audio response."""
    from promiselink.services.tts_service import TTSResult

    mock_service = MagicMock()
    mock_service.synthesize = AsyncMock(
        return_value=TTSResult(
            audio_bytes=b"fake_mp3_audio_data",
            provider="moka_ai",
            duration_ms=500,
        )
    )
    mock_service.close = AsyncMock()
    mock_tts_cls.return_value = mock_service

    response = await client.post(
        f"{API_PREFIX}/media/tts",
        json={"text": "你好世界", "voice": "alloy"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mp3"
    assert response.content == b"fake_mp3_audio_data"
    assert response.headers["x-provider"] == "moka_ai"


# ── OCR Tests ──


async def test_ocr_endpoint_requires_auth(unauth_client):
    """POST /media/ocr without token → 401."""
    fake_image = _make_fake_image_bytes()
    response = await unauth_client.post(
        f"{API_PREFIX}/media/ocr",
        files={"image": ("test.jpg", fake_image, "image/jpeg")},
    )
    assert response.status_code == 401


@patch("promiselink.api.v1.media.OCRService")
async def test_ocr_endpoint_with_mock(mock_ocr_cls, client):
    """POST /media/ocr with mock OCR service returns correct structure."""
    from promiselink.services.ocr_service import OCRResult

    structured_data = {
        "names": ["张三"],
        "companies": ["智源AI"],
        "titles": ["CEO"],
        "phone": ["13800138000"],
        "email": ["zhangsan@example.com"],
        "notes": [],
    }

    mock_service = MagicMock()
    mock_service.recognize = AsyncMock(
        return_value=OCRResult(
            text="张三 CEO 智源AI 13800138000 zhangsan@example.com",
            structured_data=structured_data,
            provider="moka_ai",
        )
    )
    mock_service.close = AsyncMock()
    mock_ocr_cls.return_value = mock_service

    fake_image = _make_fake_image_bytes()
    response = await client.post(
        f"{API_PREFIX}/media/ocr",
        files={"image": ("card.jpg", fake_image, "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "张三" in data["text"]
    assert data["structured_data"] is not None
    assert data["structured_data"]["names"] == ["张三"]
    assert data["provider"] == "moka_ai"


# ── OCR-Event Tests ──


@patch("promiselink.api.v1.media.OCRService")
async def test_ocr_event_endpoint_with_mock(mock_ocr_cls, client):
    """POST /media/ocr-event with mock OCR + pipeline creates event."""
    from promiselink.services.ocr_service import OCRResult

    structured_data = {
        "names": ["李四"],
        "companies": ["未来科技"],
        "titles": ["CTO"],
        "phone": [],
        "email": ["lisi@future.tech"],
        "notes": [],
    }

    mock_service = MagicMock()
    mock_service.recognize = AsyncMock(
        return_value=OCRResult(
            text="李四 CTO 未来科技 lisi@future.tech",
            structured_data=structured_data,
            provider="moka_ai",
        )
    )
    mock_service.close = AsyncMock()
    mock_ocr_cls.return_value = mock_service

    fake_image = _make_fake_image_bytes()
    response = await client.post(
        f"{API_PREFIX}/media/ocr-event",
        files={"image": ("card.jpg", fake_image, "image/jpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert "event_id" in data
    assert data["event_id"]  # non-empty
    assert "李四" in data["ocr_text"]
    assert data["structured_data"] is not None
    assert data["structured_data"]["names"] == ["李四"]

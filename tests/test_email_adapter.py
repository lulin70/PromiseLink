"""Tests for EmailAdapter — IMAP-based email ingestion.

All IMAP network calls are mocked; no real server connections.
"""

import email as email_lib
import imaplib
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eventlink.services.data_source_adapter import RawEvent, get_adapter
from eventlink.services.email_adapter import (
    EmailAdapter,
    EmailMessage,
    _decode_header_value,
    _extract_attachments,
    _extract_body_html,
    _extract_body_text,
    parse_email_message,
)


# ── Fixtures ──


def _make_raw_email(
    subject: str = "Test Subject",
    from_addr: str = "sender@example.com",
    from_name: str = "Sender Name",
    to_addr: str = "recipient@example.com",
    body_text: str = "Hello, this is a test email.",
    message_id: str = "<msg123@example.com>",
    date: str = "Sun, 1 Jun 2026 10:00:00 +0800",
) -> bytes:
    """Build a raw email message as bytes."""
    msg = email_lib.message.EmailMessage()
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["Date"] = date
    msg.set_content(body_text)
    return msg.as_bytes()


def _make_multipart_email(
    subject: str = "Multipart Test",
    from_addr: str = "sender@example.com",
    body_text: str = "Plain text body",
    body_html: str = "<p>HTML body</p>",
    message_id: str = "<multi123@example.com>",
    attachments: list[tuple[str, bytes]] | None = None,
) -> bytes:
    """Build a multipart email with text, html, and optional attachments."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders

    msg = MIMEMultipart()
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = "recipient@example.com"
    msg["Date"] = "Sun, 1 Jun 2026 12:00:00 +0800"

    msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    if attachments:
        for filename, content in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(content)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            msg.attach(part)

    return msg.as_bytes()


# ── Unit tests: EmailMessage dataclass ──


class TestEmailMessage:
    """Test EmailMessage dataclass."""

    def test_email_message_creation(self):
        msg = EmailMessage(
            message_id="<test@example.com>",
            subject="Test",
            from_addr="a@b.com",
            from_name="Alice",
            to_addrs=["b@c.com"],
            date=datetime(2026, 6, 1, 10, 0, 0),
            body_text="Hello",
        )
        assert msg.message_id == "<test@example.com>"
        assert msg.subject == "Test"
        assert msg.from_addr == "a@b.com"
        assert msg.from_name == "Alice"
        assert msg.to_addrs == ["b@c.com"]
        assert msg.body_text == "Hello"
        assert msg.body_html is None
        assert msg.attachments == []

    def test_email_message_with_all_fields(self):
        msg = EmailMessage(
            message_id="<test2@example.com>",
            subject="Full",
            from_addr="x@y.com",
            from_name="Bob",
            to_addrs=["c@d.com", "e@f.com"],
            date=datetime(2026, 6, 1, 12, 0, 0),
            body_text="Body",
            body_html="<p>HTML</p>",
            attachments=["doc.pdf", "image.png"],
        )
        assert msg.body_html == "<p>HTML</p>"
        assert len(msg.attachments) == 2


# ── Unit tests: parse_email_message ──


class TestParseEmailMessage:
    """Test parse_email_message function."""

    def test_parse_simple_email(self):
        raw = _make_raw_email()
        result = parse_email_message(raw)

        assert result.message_id == "msg123@example.com"
        assert result.subject == "Test Subject"
        assert result.from_addr == "sender@example.com"
        assert result.from_name == "Sender Name"
        assert result.to_addrs == ["recipient@example.com"]
        assert "test email" in result.body_text
        assert result.body_html is None
        assert result.attachments == []

    def test_parse_email_with_no_subject(self):
        raw = _make_raw_email(subject="")
        result = parse_email_message(raw)
        assert result.subject == ""

    def test_parse_multipart_email(self):
        raw = _make_multipart_email()
        result = parse_email_message(raw)

        assert result.message_id == "multi123@example.com"
        assert result.subject == "Multipart Test"
        assert "Plain text body" in result.body_text
        assert result.body_html is not None
        assert "HTML body" in result.body_html

    def test_parse_email_with_attachments(self):
        raw = _make_multipart_email(
            attachments=[("report.pdf", b"PDF content")]
        )
        result = parse_email_message(raw)

        assert len(result.attachments) == 1
        assert "report.pdf" in result.attachments

    def test_parse_email_date_parsing(self):
        raw = _make_raw_email()
        result = parse_email_message(raw)
        assert isinstance(result.date, datetime)
        assert result.date.year == 2026
        assert result.date.month == 6

    def test_parse_email_invalid_date_falls_back(self):
        raw = _make_raw_email(date="invalid-date")
        result = parse_email_message(raw)
        # Should fall back to datetime.utcnow()
        assert isinstance(result.date, datetime)

    def test_parse_email_missing_message_id(self):
        raw = _make_raw_email(message_id="")
        result = parse_email_message(raw)
        assert result.message_id == ""


# ── Unit tests: helper functions ──


class TestDecodeHeaderValue:
    """Test _decode_header_value helper."""

    def test_plain_string(self):
        assert _decode_header_value("Hello") == "Hello"

    def test_none_value(self):
        assert _decode_header_value(None) == ""

    def test_empty_string(self):
        assert _decode_header_value("") == ""

    def test_encoded_header(self):
        # UTF-8 encoded subject
        result = _decode_header_value("=?utf-8?b?5rWL6K+V?=")
        assert isinstance(result, str)


class TestExtractBodyText:
    """Test _extract_body_text helper."""

    def test_plain_text_email(self):
        raw = _make_raw_email(body_text="Hello World")
        msg = email_lib.message_from_bytes(raw)
        assert "Hello World" in _extract_body_text(msg)

    def test_multipart_email(self):
        raw = _make_multipart_email(body_text="Multipart text")
        msg = email_lib.message_from_bytes(raw)
        assert "Multipart text" in _extract_body_text(msg)


# ── Unit tests: EmailAdapter ──


class TestEmailAdapterSourceType:
    """Test EmailAdapter source_type property."""

    def test_source_type_is_email(self):
        adapter = EmailAdapter()
        assert adapter.source_type == "email"


class TestEmailAdapterConnect:
    """Test EmailAdapter.connect() with mocked IMAP."""

    @pytest.mark.asyncio
    async def test_connect_ssl_success(self):
        adapter = EmailAdapter()
        with patch("eventlink.services.email_adapter.imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn

            result = await adapter.connect("imap.gmail.com", "user@gmail.com", "password")

            assert result is True
            assert adapter._connected is True
            mock_imap.assert_called_once_with("imap.gmail.com", 993)
            mock_conn.login.assert_called_once_with("user@gmail.com", "password")

    @pytest.mark.asyncio
    async def test_connect_non_ssl(self):
        adapter = EmailAdapter()
        with patch("eventlink.services.email_adapter.imaplib.IMAP4") as mock_imap:
            mock_conn = MagicMock()
            mock_imap.return_value = mock_conn

            result = await adapter.connect(
                "imap.example.com", "user@example.com", "password",
                port=143, use_ssl=False
            )

            assert result is True
            mock_imap.assert_called_once_with("imap.example.com", 143)

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        adapter = EmailAdapter()
        with patch("eventlink.services.email_adapter.imaplib.IMAP4_SSL") as mock_imap:
            mock_imap.side_effect = imaplib.IMAP4.error("Connection refused")

            result = await adapter.connect("bad.host", "user", "pass")

            assert result is False
            assert adapter._connected is False


class TestEmailAdapterFetchUnread:
    """Test EmailAdapter.fetch_unread() with mocked IMAP."""

    @pytest.mark.asyncio
    async def test_fetch_unread_not_connected_raises(self):
        adapter = EmailAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.fetch_unread()

    @pytest.mark.asyncio
    async def test_fetch_unread_success(self):
        adapter = EmailAdapter()
        adapter._connected = True
        mock_conn = MagicMock()
        adapter._connection = mock_conn

        raw_email = _make_raw_email()
        mock_conn.search.return_value = ("OK", [b"1 2"])
        mock_conn.fetch.return_value = ("OK", [(b"1 (RFC822 {1234}", raw_email)])
        mock_conn.select.return_value = ("OK", [b"1"])

        messages = await adapter.fetch_unread()

        assert len(messages) == 2  # Two message IDs "1" and "2"
        for msg in messages:
            assert isinstance(msg, EmailMessage)
            assert msg.subject == "Test Subject"

    @pytest.mark.asyncio
    async def test_fetch_unread_empty(self):
        adapter = EmailAdapter()
        adapter._connected = True
        mock_conn = MagicMock()
        adapter._connection = mock_conn

        mock_conn.search.return_value = ("OK", [b""])
        mock_conn.select.return_value = ("OK", [b"1"])

        messages = await adapter.fetch_unread()
        assert messages == []

    @pytest.mark.asyncio
    async def test_fetch_unread_search_failure(self):
        adapter = EmailAdapter()
        adapter._connected = True
        mock_conn = MagicMock()
        adapter._connection = mock_conn

        mock_conn.search.return_value = ("NO", [b""])
        mock_conn.select.return_value = ("OK", [b"1"])

        messages = await adapter.fetch_unread()
        assert messages == []


class TestEmailAdapterParseToEvent:
    """Test EmailAdapter.parse_to_event()."""

    def test_parse_to_event_basic(self):
        adapter = EmailAdapter()
        msg = EmailMessage(
            message_id="<abc@example.com>",
            subject="Meeting Tomorrow",
            from_addr="boss@company.com",
            from_name="Boss",
            to_addrs=["me@company.com"],
            date=datetime(2026, 6, 1, 10, 0, 0),
            body_text="Let's meet tomorrow at 3pm to discuss the project.",
        )

        raw_event = adapter.parse_to_event(msg, user_id="user_123")

        assert isinstance(raw_event, RawEvent)
        assert raw_event.source_type == "email"
        assert raw_event.source_id == "<abc@example.com>"
        assert raw_event.event_type == "email"
        assert raw_event.title == "Meeting Tomorrow"
        assert raw_event.raw_text == "Let's meet tomorrow at 3pm to discuss the project."
        assert raw_event.occurred_at == datetime(2026, 6, 1, 10, 0, 0)
        assert raw_event.metadata["from"] == "boss@company.com"
        assert raw_event.metadata["from_name"] == "Boss"
        assert raw_event.metadata["to"] == ["me@company.com"]
        assert raw_event.metadata["message_id"] == "<abc@example.com>"
        assert raw_event.user_id == "user_123"

    def test_parse_to_event_no_subject(self):
        adapter = EmailAdapter()
        msg = EmailMessage(
            message_id="<no-subject@example.com>",
            subject="",
            from_addr="a@b.com",
            from_name="A",
            to_addrs=["c@d.com"],
            date=datetime(2026, 6, 1, 10, 0, 0),
            body_text="Content",
        )

        raw_event = adapter.parse_to_event(msg)
        assert raw_event.title == "(无主题)"

    def test_parse_to_event_with_attachments(self):
        adapter = EmailAdapter()
        msg = EmailMessage(
            message_id="<attach@example.com>",
            subject="Report",
            from_addr="a@b.com",
            from_name="A",
            to_addrs=["c@d.com"],
            date=datetime(2026, 6, 1, 10, 0, 0),
            body_text="See attached report.",
            attachments=["report.pdf"],
        )

        raw_event = adapter.parse_to_event(msg)
        assert raw_event.metadata["attachments"] == ["report.pdf"]


class TestEmailAdapterMarkAsRead:
    """Test EmailAdapter.mark_as_read()."""

    @pytest.mark.asyncio
    async def test_mark_as_read_not_connected_raises(self):
        adapter = EmailAdapter()
        with pytest.raises(RuntimeError, match="Not connected"):
            await adapter.mark_as_read("<msg@example.com>")

    @pytest.mark.asyncio
    async def test_mark_as_read_success(self):
        adapter = EmailAdapter()
        adapter._connected = True
        mock_conn = MagicMock()
        adapter._connection = mock_conn

        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b"1"])
        mock_conn.store.return_value = ("OK", [b"1"])

        result = await adapter.mark_as_read("<msg@example.com>")

        assert result is True
        mock_conn.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")

    @pytest.mark.asyncio
    async def test_mark_as_read_not_found(self):
        adapter = EmailAdapter()
        adapter._connected = True
        mock_conn = MagicMock()
        adapter._connection = mock_conn

        mock_conn.select.return_value = ("OK", [b"1"])
        mock_conn.search.return_value = ("OK", [b""])

        result = await adapter.mark_as_read("<nonexistent@example.com>")
        assert result is False


class TestEmailAdapterFetchNewEvents:
    """Test EmailAdapter.fetch_new_events() — DataSourceAdapter interface."""

    @pytest.mark.asyncio
    async def test_fetch_new_events_no_config(self):
        adapter = EmailAdapter()
        events = await adapter.fetch_new_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_fetch_new_events_with_config(self):
        adapter = EmailAdapter(config={
            "imap_host": "imap.example.com",
            "email": "user@example.com",
            "password": "pass",
            "user_id": "user_123",
        })

        with patch.object(adapter, "connect", new_callable=AsyncMock) as mock_connect, \
             patch.object(adapter, "fetch_unread", new_callable=AsyncMock) as mock_fetch:

            mock_connect.return_value = True
            mock_fetch.return_value = [
                EmailMessage(
                    message_id="<1@example.com>",
                    subject="Test 1",
                    from_addr="a@b.com",
                    from_name="A",
                    to_addrs=["c@d.com"],
                    date=datetime(2026, 6, 1, 10, 0, 0),
                    body_text="Body 1",
                ),
            ]

            events = await adapter.fetch_new_events()

            assert len(events) == 1
            assert events[0].source_type == "email"
            assert events[0].event_type == "email"
            assert events[0].title == "Test 1"
            assert events[0].user_id == "user_123"

    @pytest.mark.asyncio
    async def test_fetch_new_events_with_since_filter(self):
        adapter = EmailAdapter(config={
            "imap_host": "imap.example.com",
            "email": "user@example.com",
            "password": "pass",
        })
        adapter._connected = True

        with patch.object(adapter, "fetch_unread", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [
                EmailMessage(
                    message_id="<old@example.com>",
                    subject="Old",
                    from_addr="a@b.com",
                    from_name="A",
                    to_addrs=["c@d.com"],
                    date=datetime(2026, 5, 1, 10, 0, 0),
                    body_text="Old email",
                ),
                EmailMessage(
                    message_id="<new@example.com>",
                    subject="New",
                    from_addr="a@b.com",
                    from_name="A",
                    to_addrs=["c@d.com"],
                    date=datetime(2026, 6, 1, 10, 0, 0),
                    body_text="New email",
                ),
            ]

            events = await adapter.fetch_new_events(since=datetime(2026, 5, 15, 0, 0, 0))

            assert len(events) == 1
            assert events[0].title == "New"


class TestEmailAdapterAcknowledge:
    """Test EmailAdapter.acknowledge()."""

    @pytest.mark.asyncio
    async def test_acknowledge_delegates_to_mark_as_read(self):
        adapter = EmailAdapter()
        adapter._connected = True
        adapter._connection = MagicMock()
        with patch.object(adapter, "mark_as_read", new_callable=AsyncMock) as mock_mark:
            mock_mark.return_value = True
            result = await adapter.acknowledge("<msg@example.com>")
            assert result is True
            mock_mark.assert_called_once_with("<msg@example.com>")

    @pytest.mark.asyncio
    async def test_acknowledge_returns_false_when_not_connected(self):
        adapter = EmailAdapter()
        result = await adapter.acknowledge("<msg@example.com>")
        assert result is False


class TestEmailAdapterDisconnect:
    """Test EmailAdapter.disconnect()."""

    def test_disconnect_connected(self):
        adapter = EmailAdapter()
        mock_conn = MagicMock()
        adapter._connection = mock_conn
        adapter._connected = True

        adapter.disconnect()

        mock_conn.close.assert_called_once()
        mock_conn.logout.assert_called_once()
        assert adapter._connected is False
        assert adapter._connection is None

    def test_disconnect_not_connected(self):
        adapter = EmailAdapter()
        adapter._connection = None
        adapter._connected = False
        # Should not raise
        adapter.disconnect()
        assert adapter._connected is False


# ── Integration: Adapter Registry ──


class TestEmailAdapterRegistry:
    """Test that EmailAdapter works with the adapter registry."""

    def test_get_adapter_returns_email_adapter(self):
        adapter = get_adapter("email")
        assert isinstance(adapter, EmailAdapter)
        assert adapter.source_type == "email"

    def test_get_adapter_with_config(self):
        config = {"imap_host": "imap.gmail.com", "email": "user@gmail.com", "password": "pass"}
        adapter = get_adapter("email", config=config)
        assert isinstance(adapter, EmailAdapter)
        assert adapter.config == config

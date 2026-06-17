"""EmailAdapter — IMAP-based email ingestion for PromiseLink.

Implements PRD §5.17.2: Email data source adapter.
Connects to IMAP servers, fetches unread emails, and converts them
into RawEvent objects for the PromiseLink pipeline.

Design:
- One email → one Event (raw_text stores full body text)
- source_event_id chains back to original email message_id
- Supports SSL/TLS IMAP connections
- Phase 1 uses app password; OAuth2 deferred to Phase 2
"""

import email
import imaplib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from promiselink.core.logging import get_logger
from promiselink.services.data_source_adapter import DataSourceAdapter, RawEvent

logger = get_logger("promiselink.email_adapter")


@dataclass
class EmailMessage:
    """Parsed email message data."""

    message_id: str
    subject: str
    from_addr: str
    from_name: str
    to_addrs: list[str]
    date: datetime
    body_text: str
    body_html: str | None = None
    attachments: list[str] = field(default_factory=list)


def _decode_header_value(value: str | None) -> str:
    """Decode RFC 2047 encoded header value."""
    if not value:
        return ""
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_body_text(msg: email.message.Message) -> str:
    """Extract plain text body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/plain" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
    return ""


def _extract_body_html(msg: email.message.Message) -> str | None:
    """Extract HTML body from an email message."""
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))
            if content_type == "text/html" and "attachment" not in content_disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
    return None


def _extract_attachments(msg: email.message.Message) -> list[str]:
    """Extract attachment filenames from an email message."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in content_disposition:
                filename = part.get_filename()
                if filename:
                    attachments.append(_decode_header_value(filename))
    return attachments


def parse_email_message(raw_message: bytes) -> EmailMessage:
    """Parse raw email bytes into an EmailMessage dataclass.

    Args:
        raw_message: Raw email bytes from IMAP FETCH.

    Returns:
        Parsed EmailMessage.
    """
    msg = email.message_from_bytes(raw_message)

    # Message-ID
    message_id = msg.get("Message-ID", "").strip("<> ")

    # Subject
    subject = _decode_header_value(msg.get("Subject", ""))

    # From
    from_raw = msg.get("From", "")
    from_name, from_addr = parseaddr(from_raw)
    from_name = _decode_header_value(from_name) if from_name else from_addr

    # To
    to_raw = msg.get_all("To", [])
    to_addrs = []
    for to_item in to_raw:
        _, addr = parseaddr(to_item)
        if addr:
            to_addrs.append(addr)

    # Date
    date_str = msg.get("Date", "")
    try:
        date = parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        date = datetime.now(UTC)

    # Body
    body_text = _extract_body_text(msg)
    body_html = _extract_body_html(msg)
    attachments = _extract_attachments(msg)

    return EmailMessage(
        message_id=message_id,
        subject=subject,
        from_addr=from_addr,
        from_name=from_name,
        to_addrs=to_addrs,
        date=date,
        body_text=body_text,
        body_html=body_html,
        attachments=attachments,
    )


class EmailAdapter(DataSourceAdapter):
    """Email data source adapter with IMAP integration.

    Connects to an IMAP server, fetches unread emails, and converts
    them into RawEvent objects for the PromiseLink pipeline.

    Usage:
        adapter = EmailAdapter()
        await adapter.connect("imap.gmail.com", "user@gmail.com", "app-password")
        events = await adapter.fetch_new_events()
    """

    @property
    def source_type(self) -> str:
        return "email"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._connection: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None
        self._email: str = ""
        self._connected: bool = False

    async def connect(
        self,
        imap_host: str,
        email_addr: str,
        password: str,
        port: int = 993,
        use_ssl: bool = True,
    ) -> bool:
        """Connect to IMAP server.

        Args:
            imap_host: IMAP server hostname.
            email_addr: Email address for login.
            password: App password or OAuth2 token.
            port: IMAP port (default 993 for SSL).
            use_ssl: Whether to use SSL/TLS connection.

        Returns:
            True if connection and login succeeded.
        """
        try:
            if use_ssl:
                self._connection = imaplib.IMAP4_SSL(imap_host, port)
            else:
                self._connection = imaplib.IMAP4(imap_host, port)

            self._connection.login(email_addr, password)
            self._email = email_addr
            self._connected = True

            logger.info(
                "email_adapter_connected",
                imap_host=imap_host,
                email=email_addr,
            )
            return True
        except (imaplib.IMAP4.error, OSError) as exc:
            logger.error(
                "email_adapter_connect_failed",
                imap_host=imap_host,
                email=email_addr,
                error=str(exc),
            )
            self._connected = False
            return False

    async def fetch_unread(self, folder: str = "INBOX") -> list[EmailMessage]:
        """Fetch unread emails from the specified folder.

        Args:
            folder: IMAP folder to search (default "INBOX").

        Returns:
            List of parsed EmailMessage objects.

        Raises:
            RuntimeError: If not connected to IMAP server.
        """
        if not self._connected or not self._connection:
            raise RuntimeError("Not connected to IMAP server. Call connect() first.")

        self._connection.select(folder, readonly=False)

        # Search for unread messages
        status, message_ids = self._connection.search(None, "UNSEEN")
        if status != "OK":
            logger.warning("email_adapter_search_failed", folder=folder)
            return []

        id_list = message_ids[0].split()
        if not id_list:
            return []

        messages: list[EmailMessage] = []
        for msg_id in id_list:
            try:
                status, data = self._connection.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue

                # data[0] is a tuple: (b'1 (RFC822 {size}', raw_bytes)
                raw_message = data[0][1]
                email_msg = parse_email_message(raw_message)
                messages.append(email_msg)
            except Exception as exc:
                logger.warning(
                    "email_adapter_fetch_message_failed",
                    msg_id=msg_id,
                    error=str(exc),
                )

        logger.info(
            "email_adapter_fetched",
            folder=folder,
            count=len(messages),
        )
        return messages

    def parse_to_event(self, message: EmailMessage, user_id: str | None = None) -> RawEvent:
        """Parse an EmailMessage into a RawEvent for the pipeline.

        One email → one Event. raw_text stores the full body text.
        The message_id is preserved in metadata for source_event_id chaining.

        Args:
            message: Parsed EmailMessage.
            user_id: Optional user ID to associate.

        Returns:
            RawEvent ready for pipeline ingestion.
        """
        return RawEvent(
            source_type="email",
            source_id=message.message_id or f"email_{message.date.timestamp()}",
            raw_text=message.body_text,
            event_type="email",
            title=message.subject or "(无主题)",
            occurred_at=message.date,
            metadata={
                "from": message.from_addr,
                "from_name": message.from_name,
                "to": message.to_addrs,
                "message_id": message.message_id,
                "attachments": message.attachments,
            },
            user_id=user_id,
        )

    async def mark_as_read(self, message_id: str) -> bool:
        """Mark an email as read (SEEN) on the IMAP server.

        Args:
            message_id: The email Message-ID header value.

        Returns:
            True if the message was marked as read.
        """
        if not self._connected or not self._connection:
            raise RuntimeError("Not connected to IMAP server. Call connect() first.")

        try:
            self._connection.select("INBOX", readonly=False)
            # Search by Message-ID header
            status, msg_nums = self._connection.search(
                None, f'(HEADER Message-ID "{message_id}")'
            )
            if status != "OK" or not msg_nums[0]:
                logger.warning(
                    "email_adapter_mark_read_not_found",
                    message_id=message_id,
                )
                return False

            for num in msg_nums[0].split():
                self._connection.store(num, "+FLAGS", "\\Seen")

            logger.info("email_adapter_marked_read", message_id=message_id)
            return True
        except Exception as exc:
            logger.error(
                "email_adapter_mark_read_failed",
                message_id=message_id,
                error=str(exc),
            )
            return False

    async def fetch_new_events(self, since: datetime | None = None) -> list[RawEvent]:
        """Fetch new email events from IMAP server.

        Implements DataSourceAdapter.fetch_new_events().

        Args:
            since: Only fetch events newer than this timestamp.
                   None means fetch all available unread.

        Returns:
            List of RawEvent objects from unread emails.
        """
        if not self._connected:
            # Try to connect with config if available
            imap_host = self.config.get("imap_host")
            email_addr = self.config.get("email")
            password = self.config.get("password")
            if not all([imap_host, email_addr, password]):
                logger.warning("email_adapter_no_config", reason="missing_connection_params")
                return []
            connected = await self.connect(imap_host, email_addr, password)
            if not connected:
                return []

        messages = await self.fetch_unread(
            folder=self.config.get("folder", "INBOX")
        )

        user_id = self.config.get("user_id")
        events = [self.parse_to_event(msg, user_id=user_id) for msg in messages]

        # Filter by 'since' if provided
        if since:
            events = [e for e in events if e.occurred_at and e.occurred_at > since]

        return events

    async def acknowledge(self, source_id: str) -> bool:
        """Acknowledge an email event by marking it as read.

        Args:
            source_id: The email Message-ID to acknowledge.

        Returns:
            True if acknowledgment succeeded, False if not connected or failed.
        """
        if not self._connected or not self._connection:
            return False
        return await self.mark_as_read(source_id)

    def disconnect(self) -> None:
        """Disconnect from the IMAP server."""
        if self._connection:
            try:
                self._connection.close()
                self._connection.logout()
            except Exception as exc:
                logger.debug(
                    "email_adapter_disconnect_error",
                    error=str(exc),
                )
            finally:
                self._connection = None
                self._connected = False
                logger.info("email_adapter_disconnected")

"""Email sync endpoint — IMAP-based email ingestion API.

Implements PRD §5.17.2: POST /api/v1/email/sync
Fetches unread emails from IMAP and creates Events in the pipeline.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_llm_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import BusinessError, ValidationError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.event import Event
from promiselink.services.email_adapter import EmailAdapter

logger = get_logger("promiselink.api.email_sync")
router = APIRouter(dependencies=[Depends(rate_limit_llm_dependency)])

# IMAP host whitelist — only allow known email providers
ALLOWED_IMAP_HOSTS = {
    "imap.gmail.com", "imap.mail.gmail.com",
    "imap.outlook.com", "imap-mail.outlook.com", "outlook.office365.com",
    "imap.qq.com", "imap.exmail.qq.com",
    "imap.163.com", "imap.126.com",
    "imap.yahoo.com", "imap.mail.yahoo.com",
    "imap.sina.com", "imap.sohu.com",
    "imap.aliyun.com", "imap.mxhichina.com",
    "imap.icloud.com", "imap.mail.me.com",
    "imap.exchange.com",
}


class EmailSyncRequest(BaseModel):
    """Email sync request. WARNING: password is transmitted in plaintext.
    Ensure HTTPS is used in production. Password is not stored after sync."""

    imap_host: str = Field(..., description="IMAP server hostname")
    email: str = Field(..., description="Email address for login")
    password: str = Field(..., description="App password or OAuth2 token")
    folder: str = Field(default="INBOX", description="IMAP folder to sync")
    port: int = Field(default=993, description="IMAP port")
    use_ssl: bool = Field(default=True, description="Use SSL/TLS connection")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "imap_host": "imap.gmail.com",
                "email": "user@gmail.com",
                "password": "xxxx xxxx xxxx xxxx",
                "folder": "INBOX",
                "port": 993,
                "use_ssl": True,
            }
        }
    )


class EmailSyncResponse(BaseModel):
    """Response schema for email sync."""

    synced_count: int = Field(description="Number of emails synced")
    event_ids: list[str] = Field(default_factory=list, description="Created event IDs")
    errors: list[str] = Field(default_factory=list, description="Any errors encountered")


@router.post("/email/sync", response_model=EmailSyncResponse)
async def sync_emails(
    request: EmailSyncRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """
    Sync unread emails from IMAP server and create Events.

    Connects to the specified IMAP server, fetches unread emails,
    and creates one Event per email. Each Event then enters the
    processing pipeline asynchronously.
    """
    new_request_id()

    # IMAP host whitelist check (prevent SSRF)
    if request.imap_host.lower() not in ALLOWED_IMAP_HOSTS:
        raise ValidationError(
            f"IMAP host '{request.imap_host}' is not in the allowed list. "
            f"Allowed hosts: {', '.join(sorted(ALLOWED_IMAP_HOSTS)[:5])}...",
        )

    adapter = EmailAdapter()

    # Connect to IMAP
    connected = await adapter.connect(
        imap_host=request.imap_host,
        email_addr=request.email,
        password=request.password,
        port=request.port,
        use_ssl=request.use_ssl,
    )
    if not connected:
        raise BusinessError(
            f"Failed to connect to IMAP server: {request.imap_host}",
            code="BAD_GATEWAY",
        )

    try:
        # Fetch unread emails
        messages = await adapter.fetch_unread(folder=request.folder)

        event_ids: list[str] = []
        errors: list[str] = []

        for msg in messages:
            try:
                raw_event = adapter.parse_to_event(msg, user_id=user_id)

                # Create Event in DB
                event = Event(
                    user_id=user_id,
                    event_type="email",
                    source="email",
                    title=raw_event.title or "(无主题)",
                    raw_text=raw_event.raw_text,
                    timestamp=raw_event.occurred_at or datetime.now(UTC),
                    metadata_=raw_event.metadata,
                    status="pending",
                )
                session.add(event)
                await session.flush()

                event_id = str(event.id)
                event_ids.append(event_id)

                # Mark email as read on IMAP server
                if msg.message_id:
                    await adapter.mark_as_read(msg.message_id)

                # Trigger pipeline processing in background
                background_tasks.add_task(
                    _process_email_event_background, event_id=event_id
                )

                logger.info(
                    "email_sync_event_created",
                    event_id=event_id,
                    message_id=msg.message_id,
                    subject=msg.subject[:50] if msg.subject else "",
                )

            except Exception as exc:
                errors.append(f"Failed to process email: {exc}")
                logger.warning(
                    "email_sync_message_failed",
                    message_id=msg.message_id,
                    error=str(exc),
                )

        await session.commit()

        return EmailSyncResponse(
            synced_count=len(event_ids),
            event_ids=event_ids,
            errors=errors,
        )

    finally:
        adapter.disconnect()


async def _process_email_event_background(event_id: str) -> None:
    """Process an email event through the pipeline in the background."""
    from promiselink.services.event_pipeline import process_event_with_short_transactions

    await process_event_with_short_transactions(event_id=event_id)

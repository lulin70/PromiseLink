"""F-23: Privacy Protection API — GDPR compliance endpoints.

Endpoints:
  GET    /privacy/data-summary — Return summary of all user data
  DELETE /privacy/user-data    — Delete all user data (right to be forgotten)
  POST   /privacy/export       — Trigger full data export (returns download link)
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.auth import get_current_user_id
from eventlink.core.logging import get_logger, new_request_id
from eventlink.database import get_async_session
from eventlink.models.association import Association
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.models.voice_session import VoiceSession

logger = get_logger("eventlink.api.privacy")
router = APIRouter(prefix="/privacy", tags=["Privacy"])


# ── Pydantic Models ──


class DataSummaryResponse(BaseModel):
    """Summary of all user data counts."""

    events: int = 0
    entities: int = 0
    todos: int = 0
    associations: int = 0
    voice_sessions: int = 0


class DeleteUserDataResponse(BaseModel):
    """Response after deleting all user data."""

    deleted: bool = True
    events_deleted: int = 0
    entities_deleted: int = 0
    todos_deleted: int = 0
    associations_deleted: int = 0
    voice_sessions_deleted: int = 0


class ExportResponse(BaseModel):
    """Response for data export trigger."""

    download_url: str
    message: str = "Export initiated. Use the download URL to retrieve your data."


# ── Endpoints ──


@router.get(
    "/data-summary",
    response_model=DataSummaryResponse,
)
async def get_data_summary(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> DataSummaryResponse:
    """Return summary counts of all user data.

    Returns the number of events, entities, todos, associations,
    and voice sessions owned by the authenticated user.
    """
    new_request_id()

    events_count = (
        await session.execute(
            select(func.count()).select_from(Event).where(Event.user_id == user_id)
        )
    ).scalar() or 0

    entities_count = (
        await session.execute(
            select(func.count()).select_from(Entity).where(Entity.user_id == user_id)
        )
    ).scalar() or 0

    todos_count = (
        await session.execute(
            select(func.count()).select_from(Todo).where(Todo.user_id == user_id)
        )
    ).scalar() or 0

    associations_count = (
        await session.execute(
            select(func.count()).select_from(Association).where(Association.user_id == user_id)
        )
    ).scalar() or 0

    voice_sessions_count = (
        await session.execute(
            select(func.count()).select_from(VoiceSession).where(VoiceSession.user_id == user_id)
        )
    ).scalar() or 0

    logger.info(
        "privacy_data_summary",
        user_id=user_id,
        events=events_count,
        entities=entities_count,
        todos=todos_count,
        associations=associations_count,
        voice_sessions=voice_sessions_count,
    )

    return DataSummaryResponse(
        events=events_count,
        entities=entities_count,
        todos=todos_count,
        associations=associations_count,
        voice_sessions=voice_sessions_count,
    )


@router.delete(
    "/user-data",
    response_model=DeleteUserDataResponse,
)
async def delete_user_data(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> DeleteUserDataResponse:
    """Delete all user data (GDPR right to be forgotten).

    Permanently removes all events, entities, todos, associations,
    and voice sessions owned by the authenticated user.
    """
    new_request_id()

    logger.warning("privacy_delete_user_data", user_id=user_id)

    # Delete in dependency order to respect foreign keys
    # 1. Associations (references entities)
    assoc_result = await session.execute(
        delete(Association).where(Association.user_id == user_id)
    )
    associations_deleted = assoc_result.rowcount

    # 2. Todos (references events and entities)
    todos_result = await session.execute(
        delete(Todo).where(Todo.user_id == user_id)
    )
    todos_deleted = todos_result.rowcount

    # 3. Voice sessions (standalone, but has voice_turns FK)
    from eventlink.models.voice_session import VoiceTurn
    # Delete voice turns first
    await session.execute(
        delete(VoiceTurn).where(
            VoiceTurn.session_id.in_(
                select(VoiceSession.id).where(VoiceSession.user_id == user_id)
            )
        )
    )
    voice_result = await session.execute(
        delete(VoiceSession).where(VoiceSession.user_id == user_id)
    )
    voice_sessions_deleted = voice_result.rowcount

    # 4. Entities (references events via source_event_id)
    entities_result = await session.execute(
        delete(Entity).where(Entity.user_id == user_id)
    )
    entities_deleted = entities_result.rowcount

    # 5. Events (standalone)
    events_result = await session.execute(
        delete(Event).where(Event.user_id == user_id)
    )
    events_deleted = events_result.rowcount

    logger.info(
        "privacy_user_data_deleted",
        user_id=user_id,
        events=events_deleted,
        entities=entities_deleted,
        todos=todos_deleted,
        associations=associations_deleted,
        voice_sessions=voice_sessions_deleted,
    )

    return DeleteUserDataResponse(
        deleted=True,
        events_deleted=events_deleted,
        entities_deleted=entities_deleted,
        todos_deleted=todos_deleted,
        associations_deleted=associations_deleted,
        voice_sessions_deleted=voice_sessions_deleted,
    )


@router.post(
    "/export",
    response_model=ExportResponse,
)
async def export_user_data(
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
) -> ExportResponse:
    """Trigger full data export for the authenticated user.

    Returns a download URL that can be used to retrieve the exported data.
    The actual export is handled by the existing /export/{user_id} endpoint.
    """
    new_request_id()

    logger.info("privacy_export_requested", user_id=user_id)

    # Use the existing export endpoint URL as the download link
    download_url = f"/api/v1/export/{user_id}"

    return ExportResponse(
        download_url=download_url,
        message="Export initiated. Use the download URL to retrieve your data.",
    )

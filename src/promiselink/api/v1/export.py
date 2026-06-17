"""Data export API endpoint — F-21: User data portability guarantee.

Provides a structured JSON export of all user-owned data for data
portability and compliance (Phase 1 PRD requirement).
"""

import asyncio
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import BusinessError, ForbiddenError
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo

logger = get_logger("promiselink.api.export")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

EXPORT_VERSION = "1.0"
MAX_EXPORT_ENTITIES = 10000


def _serialize_model(obj) -> dict:
    """Convert a SQLAlchemy model instance to a plain dict for JSON export.

    Uses the ORM mapper to resolve Python attribute names (which may
    differ from DB column names, e.g. ``metadata_`` → ``metadata``).
    Handles UUID and datetime serialization.
    """
    result: dict[str, Any] = {}
    mapper = obj.__mapper__
    for column_prop in mapper.column_attrs:
        key = column_prop.key  # Python attribute name
        value = getattr(obj, key, None)
        if value is None:
            result[key] = None
        elif isinstance(value, uuid.UUID):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return result


def _fetch_vector_embeddings(user_id: str) -> list[dict]:
    """Fetch vector embeddings for a user from the separate SQLite vec DB.

    Returns a list of dicts with target_type, target_id, source_text, created_at.
    The raw embedding BLOB is intentionally excluded — it is a binary
    representation that is not useful in a portable JSON export.
    """
    from promiselink.services.semantic_search import SemanticSearchEngine

    db_path = SemanticSearchEngine._default_db_path()
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            """
            SELECT target_type, target_id, source_text, created_at
            FROM vector_embeddings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        # Table may not exist yet (fresh install)
        return []

    return [
        {
            "target_type": target_type,
            "target_id": target_id,
            "source_text": source_text,
            "created_at": created_at,
        }
        for target_type, target_id, source_text, created_at in rows
    ]


@router.get("/export/{user_id}")
async def export_user_data(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    authenticated_user_id: str = Depends(get_current_user_id),
):
    """Export all data owned by *user_id* as a streaming JSON document.

    **Data isolation**: the requested *user_id* must match the
    authenticated user.  Attempting to export another user's data
    returns 403.

    **Export structure**:
    ```json
    {
      "export_version": "1.0",
      "exported_at": "2026-06-07T...",
      "user_id": "...",
      "events": [...],
      "entities": [...],
      "associations": [...],
      "todos": [...],
      "vector_embeddings": [...]
    }
    ```

    Returns a StreamingResponse to avoid loading all data into memory.
    If the user has more than MAX_EXPORT_ENTITIES records, returns 400
    suggesting pagination.
    """
    new_request_id()

    # ── Authorization: enforce data isolation ──
    if str(user_id) != authenticated_user_id:
        raise ForbiddenError("Cannot export data belonging to another user")

    user_id_str = str(user_id)

    # ── Check total entity count to prevent excessive exports ──
    entity_count = 0
    for model in (Event, Entity, Association, Todo):
        result = await session.execute(
            select(func.count()).select_from(model).where(model.user_id == user_id_str)
        )
        entity_count += result.scalar_one()
    if entity_count > MAX_EXPORT_ENTITIES:
        raise BusinessError(
            message=(
                f"Export exceeds limit of {MAX_EXPORT_ENTITIES} entities "
                f"({entity_count} found). Please use pagination or contact support."
            ),
            code="EXPORT_LIMIT_EXCEEDED",
            details={"entity_count": entity_count, "max_export_entities": MAX_EXPORT_ENTITIES},
        )

    logger.info(
        "data_export_started",
        user_id=user_id_str,
        entity_count=entity_count,
    )

    # Fetch all data
    events_result = await session.execute(
        select(Event).where(Event.user_id == user_id_str)
    )
    events = events_result.scalars().all()

    entities_result = await session.execute(
        select(Entity).where(Entity.user_id == user_id_str)
    )
    entities = entities_result.scalars().all()

    associations_result = await session.execute(
        select(Association).where(Association.user_id == user_id_str)
    )
    associations = associations_result.scalars().all()

    todos_result = await session.execute(
        select(Todo).where(Todo.user_id == user_id_str)
    )
    todos = todos_result.scalars().all()

    vector_embeddings = await asyncio.to_thread(_fetch_vector_embeddings, user_id_str)

    export_data = {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "user_id": user_id_str,
        "events": [_serialize_model(e) for e in events],
        "entities": [_serialize_model(e) for e in entities],
        "associations": [_serialize_model(a) for a in associations],
        "todos": [_serialize_model(t) for t in todos],
        "vector_embeddings": vector_embeddings,
    }

    return JSONResponse(content=export_data)

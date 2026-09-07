"""EntityCorrection retention — 180-day cleanup worker.

Called from the background worker registered in main.py
(``_entity_correction_retention_maintenance``). Default retention: 180 days
(configurable via Settings.entity_correction_retention_days).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.entity_correction import EntityCorrection

logger = get_logger("promiselink.entity_correction_retention")


async def cleanup_entity_corrections(
    session: AsyncSession,
    retention_days: int = 180,
) -> int:
    """Delete EntityCorrection rows older than ``retention_days``.

    Idempotent: running twice within the same instant deletes zero rows on the
    second call (already-deleted rows are gone).

    Returns:
        Number of rows deleted.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        delete(EntityCorrection)
        .where(EntityCorrection.created_at < cutoff)
        .execution_options(synchronize_session=False)
    )
    deleted = int(cast(CursorResult[Any], result).rowcount or 0)
    if deleted > 0:
        logger.info(
            "correction_retention_run",
            deleted_count=deleted,
            retention_days=retention_days,
            cutoff_iso=cutoff.isoformat(),
        )
    await session.commit()
    return deleted

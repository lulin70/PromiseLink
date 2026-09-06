"""EntityCorrection service — W3 纠偏回流.

Wraps EntityCorrection ORM creation with automatic PII redaction on
``original_extracted_text``. Functions return ORM objects (not committed) so
the caller controls transaction scope (the contract is: every record_correction
must share the SAME session/transaction as the business mutation it audits).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.core.text_utils import redact_pii_from_text
from promiselink.database import IS_SQLITE
from promiselink.models.entity_correction import EntityCorrection

logger = get_logger("promiselink.entity_correction_service")


async def record_correction(
    session: AsyncSession,
    *,
    user_id: str,
    event_id: str,
    correction_type: str,
    action: str,
    entity_id: str | None = None,
    original_extracted_text: str | None = None,
    original_canonical_name: str | None = None,
    candidate_entity_ids: list[str] | None = None,
    selected_entity_id: str | None = None,
) -> EntityCorrection:
    """Append an audit row for a user correction.

    The function does NOT commit; the caller commits the surrounding
    business mutation in the same transaction. This is the W3 atomicity
    contract: correction and data succeed or fail together.

    Args:
        session: Active async session (caller-owned transaction).
        user_id: Owner scope.
        event_id: Source event id.
        correction_type: One of entity|todo|promise|association.
        action: One of select_existing|create_new|ignore|edit|delete|add|modify|confirm.
        entity_id: Target entity id (nullable for todo/promise if not applicable).
        original_extracted_text: Raw text snippet — auto-redacted via
            ``redact_pii_from_text`` (5 PII classes). Safe to pass None.
        original_canonical_name: Canonical name at the time of correction.
        candidate_entity_ids: List of candidate entity ids presented to user.
        selected_entity_id: User's final selection.

    Returns:
        The newly constructed (uncommitted) EntityCorrection row.
    """
    redacted_text = redact_pii_from_text(original_extracted_text or "") or None

    # SQLite uses String(36) columns for UUIDs, so bind plain str to avoid the
    # DBAPI bind mismatch. PostgreSQL still accepts uuid.UUID instances.
    def _uid(value: str | None) -> uuid.UUID | str | None:
        if value is None:
            return None
        if IS_SQLITE:
            return str(uuid.UUID(value))
        return uuid.UUID(value)

    row = EntityCorrection(
        id=uuid.uuid4(),
        user_id=_uid(user_id),  # type: ignore[arg-type]
        event_id=_uid(event_id),  # type: ignore[arg-type]
        correction_type=correction_type,
        entity_id=_uid(entity_id),  # type: ignore[arg-type]
        original_extracted_text=redacted_text,
        original_canonical_name=original_canonical_name,
        candidate_entity_ids=list(candidate_entity_ids) if candidate_entity_ids else None,
        selected_entity_id=_uid(selected_entity_id),  # type: ignore[arg-type]
        action=action,
        created_at=datetime.now(UTC),
    )
    session.add(row)

    # Whitelisted log keys (FR-W3-NFR-4: never log raw text or candidate ids).
    logger.info(
        "correction_recorded",
        event_id=event_id,
        correction_type=correction_type,
        action=action,
        entity_id=entity_id,
        user_id=user_id,
    )

    return row

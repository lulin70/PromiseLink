"""CSV Import API endpoint — F-08: Cold-start data import.

Accepts CSV file upload, parses rows into Entity objects, and
runs EntityResolution to deduplicate / merge against existing data.
"""

import csv
import io
import uuid

from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.api.dependencies import rate_limit_dependency
from promiselink.core.auth import get_current_user_id
from promiselink.core.exceptions import ValidationError
from promiselink.core.file_utils import decode_content
from promiselink.core.logging import get_logger, new_request_id
from promiselink.database import get_async_session
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.schemas.api_responses import ImportCSVResponse
from promiselink.services.entity_resolution import EntityResolutionEngine, ResolutionAction

logger = get_logger("promiselink.api.import_csv")
router = APIRouter(dependencies=[Depends(rate_limit_dependency)])

REQUIRED_COLUMNS = {"name"}
ALL_COLUMNS = {"name", "company", "title", "phone", "email", "wechat", "concern", "capability"}
MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB


def _parse_csv(text: str) -> tuple[list[dict], int, list[str]]:
    """Parse CSV text into a list of row dicts.

    Returns:
        (rows, total_rows, errors) where rows only contains valid rows.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    errors: list[str] = []
    total_rows = 0

    if reader.fieldnames is None:
        raise ValidationError("CSV file is empty or has no header row")

    # Validate header: must contain 'name'
    header_set = {f.strip().lower() for f in reader.fieldnames}
    if not REQUIRED_COLUMNS.issubset(header_set):
        raise ValidationError(f"CSV header must contain 'name' column. Found: {list(reader.fieldnames)}")

    for line_num, raw_row in enumerate(reader, start=2):
        # Normalize keys to lowercase
        row = {k.strip().lower(): (v.strip() if v else "") for k, v in raw_row.items()}

        # Skip empty rows (all values blank)
        if not any(row.values()):
            continue

        total_rows += 1

        # Must have a non-empty name
        if not row.get("name"):
            errors.append(f"Row {line_num}: missing 'name', skipped")
            continue

        rows.append(row)

    return rows, total_rows, errors


def _build_entity_data(row: dict) -> dict:
    """Build entity data dict from a CSV row for resolution engine."""
    basic: dict = {}
    for key in ("company", "title", "phone", "email", "wechat"):
        if row.get(key):
            basic[key] = row[key]

    properties: dict = {}
    if basic:
        properties["basic"] = basic

    # concern and capability stored at top-level of properties
    if row.get("concern"):
        properties["concern"] = row["concern"]
    if row.get("capability"):
        properties["capability"] = row["capability"]

    return {
        "name": row["name"],
        "company": row.get("company", ""),
        "title": row.get("title", ""),
        "entity_type": "person",
        "properties": properties,
    }


@router.post("/import/csv", response_model=ImportCSVResponse)
async def import_csv(
    file: UploadFile,
    session: AsyncSession = Depends(get_async_session),
    user_id: str = Depends(get_current_user_id),
):
    """Import entities from a CSV file.

    CSV format: name, company, title, phone, email, wechat, concern, capability

    Each row is resolved against existing entities via EntityResolutionEngine:
    - New entities are created
    - Matching entities are merged (auto-merge threshold ≥ 0.85)
    - Ambiguous matches are created as provisional (confirm threshold ≥ 0.70)

    Returns import statistics: total_rows, created, merged, skipped.
    """
    new_request_id()

    # ── Validate file ──
    if not file.filename:
        raise ValidationError("No filename provided")

    if not file.filename.lower().endswith(".csv"):
        raise ValidationError("Only .csv files are accepted")

    # Check file size before reading full content
    if hasattr(file, 'size') and file.size is not None:
        if file.size > MAX_CSV_SIZE:
            raise ValidationError("File too large, max 10MB")

    content = await file.read()
    if not content:
        raise ValidationError("Uploaded file is empty")

    if len(content) > MAX_CSV_SIZE:
        raise ValidationError("File too large, max 10MB")

    # ── Decode & parse ──
    text = decode_content(content)
    rows, total_rows, parse_errors = _parse_csv(text)

    if not rows and total_rows == 0:
        raise ValidationError("CSV file contains no data rows")

    # ── Create a sentinel Event for CSV import source ──
    import_event = Event(
        id=str(uuid.uuid4()),
        user_id=user_id,
        event_type="manual",
        source="csv_import",
        title=f"CSV Import: {file.filename}",
        raw_text=f"Imported {len(rows)} rows from {file.filename}",
        status="completed",
    )
    session.add(import_event)
    await session.flush()

    # ── Process each row through EntityResolution ──
    engine = EntityResolutionEngine(session)
    created = 0
    merged = 0
    skipped = 0

    for row in rows:
        entity_data = _build_entity_data(row)
        entity_data["source_event_id"] = str(import_event.id)
        entity_data["confidence"] = 1.0

        try:
            result = await engine.resolve(entity_data, user_id)

            if result.action == ResolutionAction.MERGE and result.target_entity:
                await engine.merge_entity(entity_data, result.target_entity)
                merged += 1
            elif result.action == ResolutionAction.CONFIRM and result.target_entity:
                # Auto-create as provisional — user can confirm later
                entity = Entity(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    entity_type="person",
                    name=entity_data["name"],
                    canonical_name=entity_data["name"],
                    aliases=[],
                    properties=entity_data.get("properties", {}),
                    source_event_id=str(import_event.id),
                    confidence=1.0,
                    status="provisional",
                )
                session.add(entity)
                created += 1
            else:
                # CREATE — new entity
                entity = Entity(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    entity_type="person",
                    name=entity_data["name"],
                    canonical_name=entity_data["name"],
                    aliases=[],
                    properties=entity_data.get("properties", {}),
                    source_event_id=str(import_event.id),
                    confidence=1.0,
                    status="confirmed",
                )
                session.add(entity)
                created += 1
        except Exception as exc:
            logger.warning(
                "csv_import_row_failed",
                name=row.get("name"),
                error=str(exc),
            )
            skipped += 1

    await session.flush()

    logger.info(
        "csv_import_completed",
        user_id=user_id,
        filename=file.filename,
        total_rows=total_rows,
        created=created,
        merged=merged,
        skipped=skipped,
    )

    return ImportCSVResponse(
        imported_count=total_rows,
        created_entities=created,
        created_todos=0,
        message=(
            f"Imported {total_rows} rows: "
            f"{created} created, {merged} merged, {skipped} skipped"
        ),
    )

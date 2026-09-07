"""Frequent contact scanner (W4) — pair-wise co-occurrence with 3 hits / 90 days rule.

Default threshold (3 hits, 90 days) is configurable via Settings
(``co_occurrence_threshold`` / ``co_occurrence_window_days``). Marking is
written into ``Entity.properties['frequent_contact']`` (JSONB) — zero schema
change.

Storage model (W4 amendment, 2026-09-07): associations keeps ONE canonical
co_occurrence row per unordered entity pair (enforced by
``uq_association_user_source_target_type`` + direction normalization in the
discovery engine). Repeat encounters accumulate shared event ids on that row
in ``properties.evidence.shared_event_ids``. The scanner therefore counts
distinct shared events per pair in Python — portable across SQLite and
PostgreSQL without dialect-specific JSON SQL.

Idempotency contract: each event id is counted at most once per pair (set
dedup), so running the scanner multiple times after re-processing the same
event does not inflate the count.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.database import IS_SQLITE
from promiselink.models.association import Association
from promiselink.models.event import Event

logger = get_logger("promiselink.frequent_contact_scanner")


def _as_id(value: str) -> Any:
    """Bind ids in the column's native type (str on SQLite, UUID on PostgreSQL)."""
    return value if IS_SQLITE else uuid.UUID(value)


async def scan_frequent_contacts(
    session: AsyncSession,
    user_id: str,
    *,
    threshold: int = 3,
    window_days: int = 90,
) -> list[dict[str, Any]]:
    """Mark entities that hit ``threshold`` co-occurrences within ``window_days``.

    Args:
        session: Active async session (caller-owned transaction).
        user_id: Owner scope.
        threshold: Minimum number of distinct shared events required.
        window_days: Rolling window in days.

    Returns:
        List of dicts describing each pair that qualified:
            [{entity_a, entity_b, count, last_seen}]
    """
    if threshold < 2:
        # Below 2 means even single repeats qualify; not useful and noisy.
        return []
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    assocs = (
        (
            await session.execute(
                select(Association).where(
                    Association.user_id == _as_id(user_id),
                    Association.association_type == "co_occurrence",
                )
            )
        )
        .scalars()
        .all()
    )

    # Collect the distinct shared event ids per unordered entity pair.
    shared_by_pair: dict[tuple[str, str], set[str]] = {}
    for assoc in assocs:
        a_id, b_id = sorted([str(assoc.source_entity_id), str(assoc.target_entity_id)])
        pair_key = (a_id, b_id)
        props = assoc.properties or {}
        if isinstance(props, str):
            props = json.loads(props) if props else {}
        evidence = (props or {}).get("evidence") or {}
        event_ids = {str(v) for v in (evidence.get("shared_event_ids") or [])}
        if assoc.source_event_id:
            # Legacy rows only carry the discovery event on the row itself.
            event_ids.add(str(assoc.source_event_id))
        if event_ids:
            shared_by_pair.setdefault(pair_key, set()).update(event_ids)

    if not shared_by_pair:
        return []

    all_event_ids = sorted({eid for ids in shared_by_pair.values() for eid in ids})
    event_rows = (
        await session.execute(
            select(Event.id, Event.timestamp).where(
                Event.id.in_([_as_id(e) for e in all_event_ids])
            )
        )
    ).fetchall()

    ts_by_event: dict[str, datetime] = {}
    for eid, ts in event_rows:
        parsed = _as_datetime(ts)
        if parsed is not None:
            ts_by_event[str(eid)] = parsed

    qualified: list[dict[str, Any]] = []
    for (entity_a, entity_b), event_ids in shared_by_pair.items():
        recent = [
            ts_by_event[e] for e in event_ids if e in ts_by_event and ts_by_event[e] >= cutoff
        ]
        if len(recent) >= threshold:
            qualified.append(
                {
                    "entity_a": entity_a,
                    "entity_b": entity_b,
                    "count": len(recent),
                    "last_seen": max(recent).isoformat(),
                }
            )
    if not qualified:
        return []

    # Aggregate by entity id so we can update Entity.properties once per entity.
    pair_by_entity: dict[str, dict[str, Any]] = {}
    for p in qualified:
        for key in ("entity_a", "entity_b"):
            entry = pair_by_entity.setdefault(
                str(p[key]), {"max_count": 0, "last_seen": None, "partners": []}
            )
            entry["max_count"] = max(entry["max_count"], p["count"])
            last_seen = p["last_seen"]
            if last_seen and (entry["last_seen"] is None or last_seen > entry["last_seen"]):
                entry["last_seen"] = last_seen
            other = p["entity_b"] if key == "entity_a" else p["entity_a"]
            if other not in entry["partners"]:
                entry["partners"].append(other)

    entity_ids = list(pair_by_entity.keys())
    entities = (
        await session.execute(
            text("SELECT id, properties FROM entities WHERE user_id = :uid AND id IN :ids").bindparams(
                bindparam("ids", expanding=True),
            ),
            {"uid": user_id, "ids": tuple(entity_ids)},
        )
    ).fetchall()

    now_iso = datetime.now(UTC).isoformat()
    for eid, props in entities:
        if isinstance(props, str):
            props = json.loads(props) if props else {}
        elif props is None:
            props = {}
        else:
            props = dict(props)
        entry = pair_by_entity[str(eid)]
        existing = props.get("frequent_contact") or {}
        props["frequent_contact"] = {
            "count": int(entry["max_count"]),
            "since": existing.get("since") or now_iso,
            "last_seen": entry["last_seen"],
            "window_days": window_days,
            "partners": entry["partners"],
        }
        await session.execute(
            text("UPDATE entities SET properties = :props WHERE id = :id AND user_id = :uid"),
            {"props": _serialize_jsonb(props), "id": str(eid), "uid": user_id},
        )
    await session.commit()
    logger.info(
        "frequent_contact_scan_done",
        user_id=user_id,
        pairs_qualified=len(qualified),
        entities_marked=len(entity_ids),
        threshold=threshold,
        window_days=window_days,
    )
    return qualified


def _as_datetime(value: Any) -> datetime | None:
    """Normalize SQLite strings / PostgreSQL datetimes to aware datetimes (UTC)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        # SQLite CURRENT_TIMESTAMP / naive ISO strings are UTC by convention.
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iso_or_none(value: Any) -> str | None:
    """Normalize SQLite strings and PostgreSQL datetimes to ISO strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def _serialize_jsonb(props: dict[str, Any]) -> Any:
    """SQLite needs a JSON string; PostgreSQL JSONB also accepts JSON strings."""
    return json.dumps(props, ensure_ascii=False, default=str)

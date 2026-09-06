"""Frequent contact scanner (W4) — pair-wise co-occurrence with 3 hits / 90 days rule.

Default threshold (3 hits, 90 days) is configurable via Settings
(``co_occurrence_threshold`` / ``co_occurrence_window_days``). Marking is
written into ``Entity.properties['frequent_contact']`` (JSONB) — zero schema
change.

Idempotency contract: each event id is counted at most once per pair, so
running the scanner multiple times after re-processing the same event does
not inflate the count.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger

logger = get_logger("promiselink.frequent_contact_scanner")


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
        threshold: Minimum number of distinct events required.
        window_days: Rolling window in days.

    Returns:
        List of dicts describing each pair that qualified:
            [{entity_a, entity_b, count, last_seen}]
    """
    if threshold < 2:
        # Below 2 means even single repeats qualify; not useful and noisy.
        return []
    cutoff = datetime.now(UTC) - timedelta(days=window_days)

    rows = (
        await session.execute(
            text(
                """
                SELECT LEAST(a.source_entity_id, a.target_entity_id) AS entity_a,
                       GREATEST(a.source_entity_id, a.target_entity_id) AS entity_b,
                       COUNT(DISTINCT e.id) AS cnt,
                       MAX(e.timestamp) AS last_seen
                FROM associations a
                JOIN events e ON e.id = a.source_event_id
                WHERE a.user_id = :uid
                  AND a.association_type = 'co_occurrence'
                  AND e.timestamp >= :cutoff
                GROUP BY entity_a, entity_b
                HAVING COUNT(DISTINCT e.id) >= :threshold
                """
            ),
            {"uid": user_id, "cutoff": cutoff, "threshold": threshold},
        )
    ).fetchall()

    pairs = [
        {
            "entity_a": str(r.entity_a),
            "entity_b": str(r.entity_b),
            "count": int(r.cnt),
            "last_seen": _iso_or_none(r.last_seen),
        }
        for r in rows
    ]
    if not pairs:
        return pairs

    # Aggregate by entity id so we can update Entity.properties once per entity.
    pair_by_entity: dict[str, dict[str, Any]] = {}
    for p in pairs:
        for key in ("entity_a", "entity_b"):
            entry = pair_by_entity.setdefault(p[key], {"max_count": 0, "last_seen": None, "partners": []})
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
            import json

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
        pairs_qualified=len(pairs),
        entities_marked=len(entity_ids),
        threshold=threshold,
        window_days=window_days,
    )
    return pairs


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
    import json

    return json.dumps(props, ensure_ascii=False, default=str)

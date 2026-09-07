"""Graph building and edge operations for association discovery.

Contains the :class:`AssociationGraphMixin` with methods that build
association edges (SQL pushdown grouping, co-occurrence by event) and
fetch existing edge sets for deduplication. These methods are mixed into
:class:`promiselink.services.association_discovery.AssociationDiscoveryEngine`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select

from promiselink.core.logging import get_logger
from promiselink.database import IS_SQLITE
from promiselink.models.association import Association
from promiselink.models.entity import Entity

logger = get_logger("promiselink.association_discovery")

__all__ = ["AssociationGraphMixin"]


def _as_assoc_id(value: str) -> Any:
    """Bind entity/event ids in the column's native type (str on SQLite, UUID on PG)."""
    return value if IS_SQLITE else uuid.UUID(value)


def _append_shared_event(assoc: Association, ev_id: str) -> None:
    """Record ``ev_id`` on a co_occurrence row's evidence (idempotent, W4)."""
    props = dict(assoc.properties or {})
    evidence = dict(props.get("evidence") or {})
    shared = [str(v) for v in (evidence.get("shared_event_ids") or [])]
    legacy = evidence.get("shared_event_id")
    if legacy and str(legacy) not in shared:
        shared.append(str(legacy))
    if ev_id not in shared:
        shared.append(ev_id)
    evidence["shared_event_ids"] = shared
    evidence["shared_event_id"] = ev_id
    props["evidence"] = evidence
    assoc.properties = props
    assoc.source_event_id = _as_assoc_id(ev_id)
    assoc.last_interaction = datetime.now(UTC)


class AssociationGraphMixin:
    """Graph/edge building and fetching methods for AssociationDiscoveryEngine.

    These methods rely on ``self.session`` and ``self._create_association``
    being provided by the host class.
    """

    # Provided by the host class (AssociationDiscoveryEngine)
    session: Any
    _create_association: Any

    # ── SQL Pushdown (for full scan) ──

    async def _discover_batch_sql_pushdown(
        self,
        user_id: str,
        existing_pair_keys: set[tuple[str, str]],
    ) -> list[Association]:
        """SQL pushdown for same_city and same_company associations.

        Queries entities from DB and groups by city/company in Python.
        Only creates associations within each group — O(G²) per group
        instead of O(P²) globally.

        For PostgreSQL Phase 1: can be replaced with native JSONB queries.
        """
        results: list[Association] = []

        # Fetch all entities for this user
        stmt = (
            select(Entity)
            .where(
                Entity.user_id == user_id,
                Entity.entity_type == "person",
                # 2026-08-16 fix: merged/deleted entities are tombstones —
                # scanning them re-links duplicates into the graph (and legacy
                # merged rows carry malformed properties that crash parsing).
                Entity.status.not_in(("merged", "deleted")),
            )
            .order_by(Entity.id)
        )
        all_result = await self.session.execute(stmt)
        all_entities = list(all_result.scalars().all())

        # Same city: group entities by city
        city_map: dict[str, list[Entity]] = {}
        for e in all_entities:
            city = (e.properties or {}).get("basic", {}).get("city")
            if city:
                city_map.setdefault(city, []).append(e)

        for city, group in city_map.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = tuple(sorted([str(group[i].id), str(group[j].id)]))
                    if pair_key in existing_pair_keys:
                        continue
                    assoc = self._create_association(
                        source_entity=group[i],
                        target_entity=group[j],
                        assoc_data={
                            "association_type": "same_city",
                            "confidence": 0.7,
                            "evidence": {"city": city},
                            "status": "provisional",
                        },
                    )
                    results.append(assoc)
                    existing_pair_keys.add(cast(tuple[str, str], pair_key))

        # Same company: group entities by company
        company_map: dict[str, list[Entity]] = {}
        for e in all_entities:
            company = (e.properties or {}).get("basic", {}).get("company")
            if company:
                company_map.setdefault(company, []).append(e)

        for company, group in company_map.items():
            if len(group) < 2:
                continue
            # Pre-build work_history company → entity_id inverted index for ex_colleague check
            # 2026-08-16 fix: work_history items may be plain strings (legacy
            # rows / LLM drift) — treat a string item as the company name.
            work_company_index: dict[str, list[int]] = {}
            for idx, entity in enumerate(group):
                history = (entity.properties or {}).get("work_history", [])
                for h in history:
                    h_company = (h.get("company") or "") if isinstance(h, dict) else str(h)
                    if h_company:
                        work_company_index.setdefault(h_company, []).append(idx)

            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = tuple(sorted([str(group[i].id), str(group[j].id)]))
                    if pair_key in existing_pair_keys:
                        continue
                    # Check for ex_colleague using inverted index
                    is_ex_colleague = False
                    history_i = (group[i].properties or {}).get("work_history", [])
                    for ha in history_i:
                        ha_company = (ha.get("company") or "") if isinstance(ha, dict) else str(ha)
                        if (
                            ha_company
                            and ha_company in work_company_index
                            and j in work_company_index[ha_company]
                        ):
                            is_ex_colleague = True
                            break

                    if is_ex_colleague:
                        confidence = 0.9
                        assoc = self._create_association(
                            source_entity=group[i],
                            target_entity=group[j],
                            assoc_data={
                                "association_type": "ex_colleague",
                                "confidence": confidence,
                                "evidence": {"company": company},
                                "status": "confirmed",
                            },
                        )
                    else:
                        assoc = self._create_association(
                            source_entity=group[i],
                            target_entity=group[j],
                            assoc_data={
                                "association_type": "competitor",
                                "confidence": 0.7,
                                "evidence": {"industry": company, "source": "same_company"},
                                "status": "provisional",
                            },
                        )
                    results.append(assoc)
                    existing_pair_keys.add(cast(tuple[str, str], pair_key))

        return results

    async def _discover_co_occurrence_by_event(
        self,
        entities: list[Entity],
        existing_pairs: set[tuple],
        event_id: str | None = None,
    ) -> list[Association]:
        """Discover co_occurrence associations by grouping entities by event."""
        entity_events: dict[str, set[str]] = {}
        for e in entities:
            eid = str(e.id)
            events = set()
            if e.source_event_id:
                events.add(str(e.source_event_id))
            for ev_id in (e.properties or {}).get("event_ids", []):
                events.add(str(ev_id))
            entity_events[eid] = events

        event_entities: dict[str, list[str]] = {}
        for eid, events in entity_events.items():
            for ev_id in events:
                event_entities.setdefault(ev_id, []).append(eid)

        entity_map = {str(e.id): e for e in entities}
        new_associations: list[Association] = []
        # W4: repeated co-occurrence must accumulate shared events on the one
        # canonical row (uq_association_user_source_target_type enforces a
        # single row per unordered pair per type). Track rows created in this
        # batch so a second shared event inside the same batch updates the
        # pending row instead of issuing a doomed DB query.
        batch_rows: dict[tuple[str, str], Association] = {}
        repeated: list[tuple[str, str, str]] = []
        repeated_db_rows: list[tuple[str, str, str]] = []

        for ev_id, eids in event_entities.items():
            if len(eids) < 2:
                continue
            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    a_id, b_id = eids[i], eids[j]
                    # Normalize direction: smaller ID first (consistent with _create_association)
                    if a_id > b_id:
                        a_id, b_id = b_id, a_id
                    key = (a_id, b_id, "co_occurrence")
                    if key in existing_pairs:
                        repeated.append((eids[i], eids[j], ev_id))
                        continue
                    a = entity_map.get(eids[i])
                    b = entity_map.get(eids[j])
                    if not a or not b:
                        continue
                    assoc = self._create_association(
                        source_entity=a,
                        target_entity=b,
                        assoc_data={
                            "association_type": "co_occurrence",
                            "confidence": 0.6,
                            "evidence": {
                                "shared_event_id": ev_id,
                                "shared_event_ids": [ev_id],
                            },
                            "status": "confirmed",
                        },
                        event_id=event_id,
                    )
                    new_associations.append(assoc)
                    existing_pairs.add(key)
                    batch_rows[(a_id, b_id)] = assoc

        for a_id, b_id, ev_id in repeated:
            pair_key = (a_id, b_id) if a_id < b_id else (b_id, a_id)
            pending = batch_rows.get(pair_key)
            if pending is not None:
                _append_shared_event(pending, ev_id)
            else:
                repeated_db_rows.append((pair_key[0], pair_key[1], ev_id))

        if repeated_db_rows:
            await self._accumulate_co_occurrence_events(repeated_db_rows)

        return new_associations

    async def _accumulate_co_occurrence_events(
        self, repeated: list[tuple[str, str, str]]
    ) -> int:
        """Accumulate shared events onto existing co_occurrence rows (W4).

        Each entry holds ``(entity_a_id, entity_b_id, event_id)`` for a pair
        whose canonical row already exists. Updates ``last_interaction``,
        points ``source_event_id`` at the latest shared event and appends to
        ``properties.evidence.shared_event_ids`` so the frequent-contact
        scanner can count distinct shared events per pair within its window.
        """
        now = datetime.now(UTC)
        updated = 0
        for a_id, b_id, ev_id in repeated:
            x, y = (a_id, b_id) if a_id < b_id else (b_id, a_id)
            stmt = select(Association).where(
                Association.association_type == "co_occurrence",
                or_(
                    and_(
                        Association.source_entity_id == _as_assoc_id(x),
                        Association.target_entity_id == _as_assoc_id(y),
                    ),
                    and_(
                        Association.source_entity_id == _as_assoc_id(y),
                        Association.target_entity_id == _as_assoc_id(x),
                    ),
                ),
            )
            assoc = (await self.session.execute(stmt)).scalar_one_or_none()
            if assoc is None:
                # Row vanished (merge/cleanup raced) — nothing to accumulate.
                continue
            _append_shared_event(assoc, ev_id)
            assoc.last_interaction = now
            updated += 1
        if updated:
            await self.session.flush()
        return updated

    # ── Helper Methods ──

    async def _fetch_all_person_entities(self, user_id: str) -> list[Entity]:
        """Fetch all person entities for a user (for cold discovery sweep).

        Uses pagination to avoid loading all entities into memory at once.
        MAX_ENTITY_LIMIT caps total entities to prevent OOM on large datasets.
        """
        MAX_ENTITY_LIMIT = 5000
        BATCH_SIZE = 500

        all_entities = []
        offset = 0
        while offset < MAX_ENTITY_LIMIT:
            stmt = (
                select(Entity)
                .where(
                    Entity.user_id == user_id,
                    Entity.entity_type == "person",
                    # 2026-08-16 fix: skip merged/deleted tombstones (see
                    # _discover_batch_sql_pushdown)
                    Entity.status.not_in(("merged", "deleted")),
                )
                .order_by(Entity.updated_at.desc())
                .limit(BATCH_SIZE)
                .offset(offset)
            )
            result = await self.session.execute(stmt)
            batch = list(result.scalars().all())
            all_entities.extend(batch)
            if len(batch) < BATCH_SIZE:
                break
            offset += BATCH_SIZE

        if len(all_entities) >= MAX_ENTITY_LIMIT:
            import structlog

            logger = structlog.get_logger()
            logger.warning(
                "entity_limit_reached",
                user_id=user_id,
                limit=MAX_ENTITY_LIMIT,
                _message=f"Entity count capped at {MAX_ENTITY_LIMIT}. Consider increasing for this user.",
            )

        return all_entities

    async def _get_existing_pair_set(self, user_id: str) -> set[tuple]:
        """Get set of existing association pairs for dedup.

        Returns set of (min_id, max_id, association_type) tuples
        with normalized direction (smaller ID first) to prevent
        bidirectional duplicates.
        """
        stmt = select(
            Association.source_entity_id,
            Association.target_entity_id,
            Association.association_type,
        ).where(Association.user_id == user_id)
        result = await self.session.execute(stmt)
        normalized = set()
        for src, tgt, assoc_type in result.fetchall():
            src, tgt = str(src), str(tgt)
            # Normalize direction: smaller ID first
            if src > tgt:
                src, tgt = tgt, src
            normalized.add((src, tgt, assoc_type))
        return normalized

    async def _fetch_existing_associations(self, user_id: str) -> list[Association]:
        """Fetch all existing associations for a user."""
        stmt = select(Association).where(Association.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

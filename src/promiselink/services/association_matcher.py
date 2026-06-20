"""Entity matching and resolution logic for association discovery.

Contains the :class:`AssociationMatcherMixin` with methods that find
candidate entity pairs for incremental discovery, create Association ORM
objects (with normalized direction), and update existing associations
after entity merges. These methods are mixed into
:class:`promiselink.services.association_discovery.AssociationDiscoveryEngine`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select

from promiselink.core.logging import get_logger
from promiselink.models.association import Association
from promiselink.models.entity import Entity

logger = get_logger("promiselink.association_discovery")

__all__ = ["AssociationMatcherMixin"]


class AssociationMatcherMixin:
    """Entity matching and resolution methods for AssociationDiscoveryEngine.

    These methods rely on ``self.session`` being provided by the host class.
    """

    # Provided by the host class (AssociationDiscoveryEngine)
    session: Any

    # ── Incremental Candidate Finding ──

    async def _find_incremental_candidates(
        self, new_entity: Entity, user_id: str
    ) -> list[Entity]:
        """Find candidate entities for incremental discovery.

        Strategy: Only look at entities that share city or company with
        the new entity, plus entities from the same events.

        This avoids scanning ALL entities — typically returns <20 candidates
        even when the user has 1000+ entities.
        """
        props = new_entity.properties or {}
        basic = props.get("basic", {})
        city = basic.get("city", "")
        company = basic.get("company", "")


        # Build OR conditions for candidate matching
        or_conditions = []
        if city:
            or_conditions.append(Entity.name != "")  # Placeholder, real filter below
        if company:
            or_conditions.append(Entity.name != "")  # Placeholder

        # Fetch candidates that share city or company
        # We need to filter by JSONB properties, which varies by DB
        # For SQLite: properties is JSON text, use LIKE
        # For PostgreSQL: properties is JSONB, use containment operator

        # Simple approach: fetch entities with SQL pre-filtering where possible
        # For SQLite: use LIKE on JSON text for city/company
        # For PostgreSQL: use JSONB containment (Phase 2)
        # Limit results to avoid O(N) memory load
        CANDIDATE_LIMIT = 200

        stmt = select(Entity).where(
            and_(
                Entity.user_id == user_id,
                Entity.entity_type == "person",
                Entity.id != str(new_entity.id),
            )
        ).options(
            # Only load columns needed for candidate matching, skip large JSON fields
            # We still need properties for city/company/keywords matching
        ).limit(CANDIDATE_LIMIT)
        result = await self.session.execute(stmt)
        all_entities = list(result.scalars().all())

        # Filter: keep entities that share city, company, event_ids,
        #         OR have overlapping keywords/topics (for semantic associations)
        candidates = []
        new_event_ids = set()
        if new_entity.source_event_id:
            new_event_ids.add(str(new_entity.source_event_id))
        for ev_id in props.get("event_ids", []):
            new_event_ids.add(str(ev_id))

        # Build keyword sets for topic-overlap candidate matching
        new_keywords = set(
            k.lower() for k in props.get("event_keywords", [])
        ) | set(t.lower() for t in props.get("tech_stack", []))
        new_topics = set(props.get("event_topics", []))

        for e in all_entities:
            e_props = e.properties or {}
            e_basic = e_props.get("basic", {})

            # Share city?
            if city and e_basic.get("city") == city:
                candidates.append(e)
                continue

            # Share company?
            if company and e_basic.get("company") == company:
                candidates.append(e)
                continue

            # Share event?
            e_event_ids = set()
            if e.source_event_id:
                e_event_ids.add(str(e.source_event_id))
            for ev_id in e_props.get("event_ids", []):
                e_event_ids.add(str(ev_id))
            if new_event_ids & e_event_ids:
                candidates.append(e)
                continue

            # Overlapping keywords or topics? (for topic_overlap/supply_demand)
            if new_keywords:
                e_keywords = set(
                    k.lower() for k in e_props.get("event_keywords", [])
                ) | set(t.lower() for t in e_props.get("tech_stack", []))
                if new_keywords & e_keywords:
                    candidates.append(e)
                    continue

            if new_topics:
                e_topics = set(e_props.get("event_topics", []))
                if new_topics & e_topics:
                    candidates.append(e)
                    continue

        return candidates

    # ── Helper Methods ──

    async def _fetch_entities_by_ids(self, entity_ids: list[str]) -> list[Entity]:
        """Fetch entities by their IDs."""
        if not entity_ids:
            return []
        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _maybe_update_association(
        self,
        pair_key: tuple[str, str],
        new_data: dict,
        user_id: str,
    ) -> None:
        """Update existing association if confidence changed after merge."""
        stmt = select(Association).where(
            Association.user_id == user_id,
            Association.association_type == new_data["association_type"],
        ).where(
            (Association.source_entity_id == pair_key[0]) | (Association.source_entity_id == pair_key[1])
        ).where(
            (Association.target_entity_id == pair_key[0]) | (Association.target_entity_id == pair_key[1])
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing and abs(existing.confidence - new_data["confidence"]) > 0.05:
            existing.confidence = new_data["confidence"]
            existing.strength = new_data["confidence"]
            existing.properties = existing.properties or {}
            existing.properties["evidence"] = new_data.get("evidence", {})
            existing.properties["updated_after_merge"] = True

    def _create_association(
        self,
        source_entity: Entity,
        target_entity: Entity,
        assoc_data: dict[str, Any],
        event_id: str | None = None,
    ) -> Association:
        """Create an Association ORM object.

        Normalizes direction so source_entity_id < target_entity_id
        to prevent bidirectional duplicates (A→B and B→A for same type).
        """
        src_id = str(source_entity.id)
        tgt_id = str(target_entity.id)
        # Normalize direction: smaller ID first
        if src_id > tgt_id:
            src_id, tgt_id = tgt_id, src_id
        return Association(
            user_id=source_entity.user_id,
            source_entity_id=src_id,
            target_entity_id=tgt_id,
            association_type=assoc_data["association_type"],
            strength=assoc_data["confidence"],
            confidence=assoc_data["confidence"],
            status=assoc_data["status"],
            source_event_id=event_id or str(source_entity.source_event_id or ""),
            properties={
                "evidence": assoc_data["evidence"],
                "discovered_at": datetime.now(UTC).isoformat(),
                "discovered_by": "AssociationDiscoveryEngine",
            },
        )

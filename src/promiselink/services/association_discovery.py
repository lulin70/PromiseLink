"""Association Discovery Engine — discovers relationships between entities.

Implements 11 association types:

Structural types (exact field match):
  co_occurrence, same_city, ex_colleague, competitor,
  alumni, tech_overlap, deal_link, risk_link, supply_chain

Semantic types (LLM-assisted inference):
  topic_overlap, supply_demand, industry_chain

Architecture (Phase 1):
  - **Incremental discovery**: Only process new/merged entities, not full rescan
  - **SQL pushdown**: same_city/same_company via SQL JOIN, not Python memory
  - **Lazy discovery**: Low-frequency types computed on-demand with Redis cache
  - **Conflict resolution**: existing_pairs dedup + merge-triggered partial rescan

Hot types (computed on write):
  co_occurrence, same_city, ex_colleague, competitor, topic_overlap

Cold types (computed on read):
  alumni, tech_overlap, deal_link, risk_link, supply_chain,
  supply_demand, industry_chain

The implementation is split across companion modules:
  - :mod:`association_scoring` — confidence scoring and similarity calculations
  - :mod:`association_graph` — edge building and SQL pushdown operations
  - :mod:`association_matcher` — candidate matching and association creation
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.association import Association
from promiselink.models.entity import Entity
from promiselink.services.association_graph import AssociationGraphMixin
from promiselink.services.association_matcher import AssociationMatcherMixin
from promiselink.services.association_scoring import (
    PROVISIONAL_THRESHOLD,
    AssociationScoringMixin,
)

logger = get_logger("promiselink.association_discovery")

# ── Constants ──

CONFIRM_THRESHOLD = 0.70

# Time decay: half-life of 180 days (6 months)
DECAY_HALF_LIFE_DAYS = 180

# Hot types: computed on every write (incremental)
HOT_ASSOCIATION_TYPES = {"co_occurrence", "same_city", "ex_colleague", "competitor", "topic_overlap"}

# Cold types: computed on read (lazy, cached)
COLD_ASSOCIATION_TYPES = {
    "alumni", "tech_overlap", "deal_link", "risk_link", "supply_chain",
    "supply_demand", "industry_chain",
}

VALID_ASSOCIATION_TYPES = HOT_ASSOCIATION_TYPES | COLD_ASSOCIATION_TYPES


class AssociationDiscoveryEngine(
    AssociationGraphMixin, AssociationScoringMixin, AssociationMatcherMixin
):
    """Discovers relationships between entities.

    Two modes:
    1. **Incremental** (default): Only process new/merged entities
    2. **Full scan**: Process all entities (for initial load or manual trigger)
    """

    def __init__(
        self,
        session: AsyncSession,
        config: dict[str, Any] | None = None,
        confirm_threshold: float = CONFIRM_THRESHOLD,
    ):
        self.session = session
        self.config = config or {}
        self.confirm_threshold = confirm_threshold

        # Cold-type discoverers (used for lazy computation)
        self.cold_discoverers = {
            "alumni": self._discover_alumni,
            "tech_overlap": self._discover_tech_overlap,
            "deal_link": self._discover_deal_link,
            "risk_link": self._discover_risk_link,
            "supply_chain": self._discover_supply_chain,
            "supply_demand": self._discover_supply_demand,
            "industry_chain": self._discover_industry_chain,
        }

    # ── Public API ──

    async def discover_incremental(
        self,
        user_id: str,
        new_entity_ids: list[str],
        merged_entity_ids: list[str] | None = None,
        event_id: str | None = None,
    ) -> list[Association]:
        """Incremental discovery: only process new and merged entities.

        This is the primary entry point for the pipeline. Instead of scanning
        all entities, it only discovers associations involving the newly
        created/merged entities.

        For new entities: find associations with ALL existing entities.
        For merged entities: re-scan only that entity's associations.

        Args:
            user_id: The user whose entities to scan.
            new_entity_ids: IDs of newly created entities.
            merged_entity_ids: IDs of entities that were merged (need rescan).
            event_id: Optional event_id to tag as source.

        Returns:
            List of newly created Association objects.
        """
        if not new_entity_ids and not merged_entity_ids:
            return []

        logger.info(
            "incremental_discovery_started",
            user_id=user_id,
            new_entities=len(new_entity_ids),
            merged_entities=len(merged_entity_ids or []),
        )

        # Fetch new entities
        new_entities = await self._fetch_entities_by_ids(new_entity_ids)
        if not new_entities:
            return []

        # Fetch existing associations for dedup
        existing_pairs = await self._get_existing_pair_set(user_id)

        new_associations: list[Association] = []

        # Step 1: Co-occurrence from the current event (most efficient)
        co_occ = self._discover_co_occurrence_by_event(
            new_entities, existing_pairs, event_id
        )
        for assoc in co_occ:
            self.session.add(assoc)
            new_associations.append(assoc)
        if co_occ:
            await self.session.flush()

        # Step 2: For each new entity, find hot + cold associations with existing entities
        for new_entity in new_entities:
            # Find candidates: entities that share city/company with new entity
            candidates = await self._find_incremental_candidates(new_entity, user_id)
            for candidate in candidates:
                pair_key = tuple(sorted([str(new_entity.id), str(candidate.id)]))

                # Hot types (same_city, ex_colleague, competitor, co_occurrence, topic_overlap)
                results = self._discover_hot_types(new_entity, candidate)
                for r in results:
                    type_key = (pair_key[0], pair_key[1], r["association_type"])
                    if type_key in existing_pairs:
                        continue
                    assoc = self._create_association(
                        source_entity=new_entity,
                        target_entity=candidate,
                        assoc_data=r,
                        event_id=event_id,
                    )
                    self.session.add(assoc)
                    new_associations.append(assoc)
                    existing_pairs.add(type_key)

                # Cold types (industry_chain, supply_demand, etc.) — also persist for Step 7.5 todos
                cold_results = await self.discover_cold_types(new_entity, candidate)
                for r in cold_results:
                    type_key = (pair_key[0], pair_key[1], r["association_type"])
                    if type_key in existing_pairs:
                        continue
                    assoc = self._create_association(
                        source_entity=new_entity,
                        target_entity=candidate,
                        assoc_data=r,
                        event_id=event_id,
                    )
                    self.session.add(assoc)
                    new_associations.append(assoc)
                    existing_pairs.add(type_key)

        if new_associations:
            await self.session.flush()

        # Step 2.5: Cold discovery for new entities against existing entities
        # This catches associations like industry_chain that aren't found by
        # city/company-based candidate matching (e.g., 投资↔人工智能)
        # Limit batch size to avoid O(N*M) explosion
        COLD_DISCOVERY_BATCH_LIMIT = 100
        if new_entities:
            all_persons = await self._fetch_all_person_entities(user_id)
            # Limit to most recently updated persons for cold discovery
            all_persons_sorted = sorted(
                all_persons, key=lambda e: e.updated_at or e.created_at, reverse=True
            )
            all_persons_limited = all_persons_sorted[:COLD_DISCOVERY_BATCH_LIMIT]
            for new_entity in new_entities:
                for existing in all_persons_limited:
                    if str(existing.id) == str(new_entity.id):
                        continue
                    pair_key = tuple(sorted([str(new_entity.id), str(existing.id)]))
                    # Only run cold discovery if no cold-type associations exist yet
                    has_cold = any(
                        pk for pk in existing_pairs
                        if pk[0] == pair_key[0] and pk[1] == pair_key[1]
                        and pk[2] in ("industry_chain", "supply_demand", "alumni",
                                       "tech_overlap", "deal_link", "risk_link")
                    )
                    if has_cold:
                        continue
                    cold_results = await self.discover_cold_types(new_entity, existing)
                    for r in cold_results:
                        type_key = (pair_key[0], pair_key[1], r["association_type"])
                        if type_key in existing_pairs:
                            continue
                        assoc = self._create_association(
                            source_entity=new_entity,
                            target_entity=existing,
                            assoc_data=r,
                            event_id=event_id,
                        )
                        self.session.add(assoc)
                        new_associations.append(assoc)
                        existing_pairs.add(type_key)
            if new_associations:
                await self.session.flush()

        # Step 3: For merged entities, rescan their associations
        if merged_entity_ids:
            merged_entities = await self._fetch_entities_by_ids(merged_entity_ids)
            for merged_entity in merged_entities:
                # Re-discover hot associations for the merged entity
                candidates = await self._find_incremental_candidates(merged_entity, user_id)
                for candidate in candidates:
                    if str(candidate.id) == str(merged_entity.id):
                        continue
                    pair_key = tuple(sorted([str(merged_entity.id), str(candidate.id)]))
                    # For merged entities, we need to check if existing associations
                    # are still valid (city/company may have changed after merge)
                    results = self._discover_hot_types(merged_entity, candidate)
                    for r in results:
                        type_key = (pair_key[0], pair_key[1], r["association_type"])
                        if type_key in existing_pairs:
                            # Update existing association if confidence changed
                            await self._maybe_update_association(
                                cast(tuple[str, str], pair_key), r, user_id
                            )
                            continue
                        assoc = self._create_association(
                            source_entity=merged_entity,
                            target_entity=candidate,
                            assoc_data=r,
                            event_id=event_id,
                        )
                        self.session.add(assoc)
                        new_associations.append(assoc)
                        existing_pairs.add(type_key)

            if new_associations:
                await self.session.flush()

        logger.info(
            "incremental_discovery_completed",
            user_id=user_id,
            new_associations=len(new_associations),
        )

        return new_associations

    async def discover_all_pairs(
        self,
        user_id: str,
        event_id: str | None = None,
    ) -> list[Association]:
        """Full scan discovery (for initial load or manual trigger).

        Uses SQL pushdown for same_city/same_company to avoid O(P²) in Python.
        Only computes HOT association types. Cold types are computed on read.

        Args:
            user_id: The user whose entities to scan.
            event_id: Optional event_id to tag as source.

        Returns:
            List of newly created Association objects.
        """
        stmt = select(Entity).where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
        ).limit(500)
        result = await self.session.execute(stmt)
        entities = list(result.scalars().all())

        if len(entities) < 2:
            return []

        logger.info(
            "full_discovery_started",
            user_id=user_id,
            entity_count=len(entities),
        )

        existing_pairs = await self._get_existing_pair_set(user_id)
        existing_pair_keys = {
            tuple(sorted([e[0], e[1]]))
            for e in existing_pairs
        }

        new_associations: list[Association] = []

        # Step 1: Co-occurrence by event
        co_occ = self._discover_co_occurrence_by_event(entities, existing_pairs, event_id)
        for assoc in co_occ:
            self.session.add(assoc)
            new_associations.append(assoc)
        if co_occ:
            await self.session.flush()

        # Step 2: SQL pushdown for same_city and same_company/ex_colleague/competitor
        batch_results = await self._discover_batch_sql_pushdown(
            user_id, existing_pair_keys
        )
        for assoc in batch_results:
            self.session.add(assoc)
            new_associations.append(assoc)
        if batch_results:
            await self.session.flush()

        logger.info(
            "full_discovery_completed",
            user_id=user_id,
            new_associations=len(new_associations),
        )

        return new_associations

    async def discover_cold_types(
        self,
        entity_a: Entity,
        entity_b: Entity,
    ) -> list[dict[str, Any]]:
        """Discover cold association types between two entities (on-demand).

        Used when the user queries associations — computes alumni, tech_overlap,
        deal_link, risk_link, supply_chain lazily.

        Results are cached in Redis for 1 hour.

        Args:
            entity_a: First entity.
            entity_b: Second entity.

        Returns:
            List of association data dicts.
        """
        results = []
        for assoc_type, discoverer in self.cold_discoverers.items():
            confidence, evidence = await discoverer(entity_a, entity_b)
            if confidence > PROVISIONAL_THRESHOLD:
                status = "confirmed" if confidence >= self.confirm_threshold else "provisional"
                results.append({
                    "association_type": assoc_type,
                    "confidence": round(confidence, 4),
                    "evidence": evidence,
                    "status": status,
                })
        return results

    def discover_pair(
        self,
        entity_a: Entity,
        entity_b: Entity,
    ) -> list[dict[str, Any]]:
        """Discover all HOT associations between two entities.

        Only returns hot types (co_occurrence, same_city, ex_colleague, competitor).
        Cold types are computed on-demand via discover_cold_types().
        """
        return self._discover_hot_types(entity_a, entity_b)

    async def apply_time_decay(self, user_id: str) -> int:
        """Apply time decay to all associations of a user."""
        stmt = select(Association).where(
            Association.user_id == user_id,
            Association.status != "rejected",
        )
        result = await self.session.execute(stmt)
        associations = list(result.scalars().all())

        now = datetime.now(UTC)
        updated = 0

        for assoc in associations:
            last = assoc.last_interaction or assoc.created_at or now
            days_since = (now - last).days if last else 0
            decay_factor = 0.5 ** (days_since / DECAY_HALF_LIFE_DAYS)
            new_strength = assoc.strength * decay_factor

            if new_strength < 0.1:
                assoc.status = "rejected"
                assoc.strength = new_strength
            else:
                assoc.strength = round(new_strength, 4)

            updated += 1

        if updated:
            await self.session.flush()

        return updated


__all__ = [
    "COLD_ASSOCIATION_TYPES",
    "CONFIRM_THRESHOLD",
    "DECAY_HALF_LIFE_DAYS",
    "HOT_ASSOCIATION_TYPES",
    "VALID_ASSOCIATION_TYPES",
    "AssociationDiscoveryEngine",
    "AssociationGraphMixin",
    "AssociationMatcherMixin",
    "AssociationScoringMixin",
    "PROVISIONAL_THRESHOLD",
]

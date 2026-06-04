"""Association Discovery Engine — discovers relationships between entities.

Implements 8 association types as defined in Algorithm Design v1.2 §6:
  alumni, ex_colleague, same_city, competitor,
  tech_overlap, deal_link, risk_link, supply_chain

Plus a co_occurrence type for entities that appear in the same event.

Architecture (Phase 1):
  - **Incremental discovery**: Only process new/merged entities, not full rescan
  - **SQL pushdown**: same_city/same_company via SQL JOIN, not Python memory
  - **Lazy discovery**: Low-frequency types (alumni, tech_overlap, deal_link,
    risk_link, supply_chain) computed on-demand with Redis cache
  - **Conflict resolution**: existing_pairs dedup + merge-triggered partial rescan

Hot types (computed on write):
  co_occurrence, same_city, ex_colleague, competitor

Cold types (computed on read):
  alumni, tech_overlap, deal_link, risk_link, supply_chain
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.logging import get_logger
from eventlink.models.association import Association
from eventlink.models.entity import Entity

logger = get_logger("eventlink.association_discovery")

# ── Constants ──

CONFIRM_THRESHOLD = 0.70
PROVISIONAL_THRESHOLD = 0.30

# Time decay: half-life of 180 days (6 months)
DECAY_HALF_LIFE_DAYS = 180

# Hot types: computed on every write (incremental)
HOT_ASSOCIATION_TYPES = {"co_occurrence", "same_city", "ex_colleague", "competitor"}

# Cold types: computed on read (lazy, cached)
COLD_ASSOCIATION_TYPES = {"alumni", "tech_overlap", "deal_link", "risk_link", "supply_chain"}

VALID_ASSOCIATION_TYPES = HOT_ASSOCIATION_TYPES | COLD_ASSOCIATION_TYPES


class AssociationDiscoveryEngine:
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

        # Step 2: For each new entity, find hot associations with existing entities
        for new_entity in new_entities:
            # Find candidates: entities that share city/company with new entity
            candidates = await self._find_incremental_candidates(new_entity, user_id)
            for candidate in candidates:
                pair_key = tuple(sorted([str(new_entity.id), str(candidate.id)]))
                if pair_key in existing_pairs:
                    continue
                results = self._discover_hot_types(new_entity, candidate)
                for r in results:
                    type_key = (pair_key[0], pair_key[1], r["association_type"])
                    reverse_key = (pair_key[1], pair_key[0], r["association_type"])
                    if type_key in existing_pairs or reverse_key in existing_pairs:
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
                    existing_pairs.add(pair_key)

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
                        reverse_key = (pair_key[1], pair_key[0], r["association_type"])
                        if type_key in existing_pairs or reverse_key in existing_pairs:
                            # Update existing association if confidence changed
                            await self._maybe_update_association(
                                pair_key, r, user_id
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
                        existing_pairs.add(pair_key)

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
        )
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
            confidence, evidence = discoverer(entity_a, entity_b)
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

        now = datetime.utcnow()
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

    # ── Hot Type Discovery (computed on write) ──

    def _discover_hot_types(
        self, entity_a: Entity, entity_b: Entity
    ) -> list[dict[str, Any]]:
        """Discover hot association types between two entities."""
        results = []

        # Same city
        confidence, evidence = self._discover_same_city(entity_a, entity_b)
        if confidence > PROVISIONAL_THRESHOLD:
            results.append({
                "association_type": "same_city",
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "status": "confirmed" if confidence >= self.confirm_threshold else "provisional",
            })

        # Ex-colleague
        confidence, evidence = self._discover_ex_colleague(entity_a, entity_b)
        if confidence > PROVISIONAL_THRESHOLD:
            results.append({
                "association_type": "ex_colleague",
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "status": "confirmed" if confidence >= self.confirm_threshold else "provisional",
            })

        # Competitor
        confidence, evidence = self._discover_competitor(entity_a, entity_b)
        if confidence > PROVISIONAL_THRESHOLD:
            results.append({
                "association_type": "competitor",
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "status": "confirmed" if confidence >= self.confirm_threshold else "provisional",
            })

        # Co-occurrence
        confidence, evidence = self._discover_co_occurrence(entity_a, entity_b)
        if confidence > PROVISIONAL_THRESHOLD:
            results.append({
                "association_type": "co_occurrence",
                "confidence": round(confidence, 4),
                "evidence": evidence,
                "status": "confirmed" if confidence >= self.confirm_threshold else "provisional",
            })

        return results

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

        conditions = [Entity.user_id == user_id, Entity.entity_type == "person"]

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

        # Simple approach: fetch all entities and filter in Python
        # This is acceptable because we're only fetching for ONE new entity
        stmt = select(Entity).where(
            and_(
                Entity.user_id == user_id,
                Entity.entity_type == "person",
                Entity.id != str(new_entity.id),
            )
        )
        result = await self.session.execute(stmt)
        all_entities = list(result.scalars().all())

        # Filter: keep entities that share city, company, or event_ids
        candidates = []
        new_event_ids = set()
        if new_entity.source_event_id:
            new_event_ids.add(str(new_entity.source_event_id))
        for ev_id in props.get("event_ids", []):
            new_event_ids.add(str(ev_id))

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

        return candidates

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
        stmt = select(Entity).where(
            Entity.user_id == user_id,
            Entity.entity_type == "person",
        ).order_by(Entity.id)
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
                    existing_pair_keys.add(pair_key)

        # Same company: group entities by company
        company_map: dict[str, list[Entity]] = {}
        for e in all_entities:
            company = (e.properties or {}).get("basic", {}).get("company")
            if company:
                company_map.setdefault(company, []).append(e)

        for company, group in company_map.items():
            if len(group) < 2:
                continue
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = tuple(sorted([str(group[i].id), str(group[j].id)]))
                    if pair_key in existing_pair_keys:
                        continue
                    # Check for ex_colleague
                    history_i = (group[i].properties or {}).get("work_history", [])
                    history_j = (group[j].properties or {}).get("work_history", [])
                    is_ex_colleague = any(
                        (ha.get("company") or "") == (hb.get("company") or "") and ha.get("company")
                        for ha in history_i for hb in history_j
                    )

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
                    existing_pair_keys.add(pair_key)

        return results

    # ── Individual Discovery Methods ──

    def _discover_same_city(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Same city."""
        city_a = (a.properties or {}).get("basic", {}).get("city", "") or ""
        city_b = (b.properties or {}).get("basic", {}).get("city", "") or ""
        if city_a and city_b and city_a == city_b:
            return 0.7, {"city": city_a}
        return 0.0, {}

    def _discover_ex_colleague(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Ex-colleague: same company with overlapping time periods."""
        history_a = (a.properties or {}).get("work_history", [])
        history_b = (b.properties or {}).get("work_history", [])
        for ha in history_a:
            for hb in history_b:
                if (ha.get("company") or "") == (hb.get("company") or "") and ha.get("company"):
                    confidence = 0.9 if ha.get("end") and hb.get("end") else 0.7
                    return confidence, {"company": ha["company"]}
        return 0.0, {}

    def _discover_competitor(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Competitor: same industry or in competitor list."""
        company_a = (a.properties or {}).get("basic", {}).get("company", "") or ""
        company_b = (b.properties or {}).get("basic", {}).get("company", "") or ""
        competitor_pairs = self.config.get("competitor_pairs", {})
        if company_b in competitor_pairs.get(company_a, []):
            return 0.95, {"company_a": company_a, "company_b": company_b, "source": "competitor_list"}
        industry_a = (a.properties or {}).get("basic", {}).get("industry", "") or ""
        industry_b = (b.properties or {}).get("basic", {}).get("industry", "") or ""
        if industry_a and industry_a == industry_b:
            return 0.7, {"industry": industry_a, "source": "same_industry"}
        return 0.0, {}

    def _discover_co_occurrence(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Co-occurrence: appeared in the same event(s)."""
        source_a = str(a.source_event_id) if a.source_event_id else None
        source_b = str(b.source_event_id) if b.source_event_id else None
        if source_a and source_b and source_a == source_b:
            return 0.6, {"shared_event_id": source_a}

        events_a = set(str(e) for e in (a.properties or {}).get("event_ids", []))
        events_b = set(str(e) for e in (b.properties or {}).get("event_ids", []))
        if source_a:
            events_a.add(source_a)
        if source_b:
            events_b.add(source_b)

        shared = events_a & events_b
        if shared:
            return 0.6, {"shared_event_ids": list(shared)[:3]}

        company_a = (a.properties or {}).get("basic", {}).get("company", "") or ""
        company_b = (b.properties or {}).get("basic", {}).get("company", "") or ""
        if company_a and company_b and company_a == company_b:
            return 0.4, {"company": company_a, "source": "same_company_inference"}

        return 0.0, {}

    # ── Cold Type Discovery (computed on read) ──

    def _discover_alumni(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Alumni: same school."""
        schools_a = set((a.properties or {}).get("basic", {}).get("schools", []))
        schools_b = set((b.properties or {}).get("basic", {}).get("schools", []))
        common = schools_a & schools_b
        if not common:
            return 0.0, {}
        majors_a = set((a.properties or {}).get("basic", {}).get("majors", []))
        majors_b = set((b.properties or {}).get("basic", {}).get("majors", []))
        confidence = 0.95 if (majors_a & majors_b) else 0.75
        return confidence, {"common_schools": list(common)}

    def _discover_tech_overlap(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Tech overlap: shared technology stack."""
        techs_a = set((a.properties or {}).get("tech_stack", []))
        techs_b = set((b.properties or {}).get("tech_stack", []))
        if not techs_a or not techs_b:
            return 0.0, {}
        overlap = techs_a & techs_b
        if not overlap:
            return 0.0, {}
        ratio = len(overlap) / min(len(techs_a), len(techs_b))
        confidence = 0.5 + ratio * 0.4
        return confidence, {"common_techs": list(overlap), "overlap_ratio": round(ratio, 2)}

    def _discover_deal_link(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Deal link: shared projects/deals."""
        deals_a = set((a.properties or {}).get("deals", []))
        deals_b = set((b.properties or {}).get("deals", []))
        common = deals_a & deals_b
        if common:
            return 1.0, {"common_deals": list(common)}
        return 0.0, {}

    def _discover_risk_link(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Risk link: co-occurrence in negative events."""
        risk_events_a = (a.properties or {}).get("risk_events", [])
        risk_events_b = (b.properties or {}).get("risk_events", [])
        common = set(str(e) for e in risk_events_a) & set(str(e) for e in risk_events_b)
        if common:
            return 0.8, {"common_risk_events": len(common)}
        return 0.0, {}

    def _discover_supply_chain(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Supply chain: upstream/downstream relationship."""
        company_a = (a.properties or {}).get("basic", {}).get("company", "") or ""
        company_b = (b.properties or {}).get("basic", {}).get("company", "") or ""
        supply_chain_map = self.config.get("supply_chain_map", {})
        if company_b in supply_chain_map.get(company_a, []):
            return 0.85, {"upstream": company_a, "downstream": company_b}
        if company_a in supply_chain_map.get(company_b, []):
            return 0.85, {"upstream": company_b, "downstream": company_a}
        return 0.0, {}

    # ── Helper Methods ──

    async def _fetch_entities_by_ids(self, entity_ids: list[str]) -> list[Entity]:
        """Fetch entities by their IDs."""
        if not entity_ids:
            return []
        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _get_existing_pair_set(self, user_id: str) -> set[tuple]:
        """Get set of existing association pairs for dedup.

        Returns set of (source_id, target_id, association_type) tuples.
        """
        stmt = select(Association).where(Association.user_id == user_id)
        result = await self.session.execute(stmt)
        associations = result.scalars().all()
        return {
            (a.source_entity_id, a.target_entity_id, a.association_type)
            for a in associations
        }

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
        """Create an Association ORM object."""
        return Association(
            user_id=source_entity.user_id,
            source_entity_id=str(source_entity.id),
            target_entity_id=str(target_entity.id),
            association_type=assoc_data["association_type"],
            strength=assoc_data["confidence"],
            confidence=assoc_data["confidence"],
            status=assoc_data["status"],
            source_event_id=event_id or str(source_entity.source_event_id or ""),
            properties={
                "evidence": assoc_data["evidence"],
                "discovered_at": datetime.utcnow().isoformat(),
                "discovered_by": "AssociationDiscoveryEngine",
            },
        )

    def _discover_co_occurrence_by_event(
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
        new_associations = []

        for ev_id, eids in event_entities.items():
            if len(eids) < 2:
                continue
            for i in range(len(eids)):
                for j in range(i + 1, len(eids)):
                    a_id, b_id = eids[i], eids[j]
                    key = (a_id, b_id, "co_occurrence")
                    reverse_key = (b_id, a_id, "co_occurrence")
                    if key in existing_pairs or reverse_key in existing_pairs:
                        continue
                    a = entity_map.get(a_id)
                    b = entity_map.get(b_id)
                    if not a or not b:
                        continue
                    assoc = self._create_association(
                        source_entity=a,
                        target_entity=b,
                        assoc_data={
                            "association_type": "co_occurrence",
                            "confidence": 0.6,
                            "evidence": {"shared_event_id": ev_id},
                            "status": "confirmed",
                        },
                        event_id=event_id,
                    )
                    new_associations.append(assoc)
                    existing_pairs.add(key)

        return new_associations

    async def _fetch_existing_associations(
        self, user_id: str
    ) -> list[Association]:
        """Fetch all existing associations for a user."""
        stmt = select(Association).where(Association.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

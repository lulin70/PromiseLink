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
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.association import Association
from promiselink.models.entity import Entity

logger = get_logger("promiselink.association_discovery")

# ── Constants ──

CONFIRM_THRESHOLD = 0.70
PROVISIONAL_THRESHOLD = 0.30

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

        # Topic overlap (semantic: events discuss similar topics/domains)
        confidence, evidence = self._discover_topic_overlap(entity_a, entity_b)
        if confidence > PROVISIONAL_THRESHOLD:
            results.append({
                "association_type": "topic_overlap",
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
                    pair_key = tuple(sorted([str(group[i].id), str(group[j].id)]))  # type: ignore[assignment]
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
            # Pre-build work_history company → entity_id inverted index for ex_colleague check
            work_company_index: dict[str, list[int]] = {}
            for idx, entity in enumerate(group):
                history = (entity.properties or {}).get("work_history", [])
                for h in history:
                    h_company = h.get("company") or ""
                    if h_company:
                        work_company_index.setdefault(h_company, []).append(idx)

            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    pair_key = tuple(sorted([str(group[i].id), str(group[j].id)]))  # type: ignore[assignment]
                    if pair_key in existing_pair_keys:
                        continue
                    # Check for ex_colleague using inverted index
                    is_ex_colleague = False
                    history_i = (group[i].properties or {}).get("work_history", [])
                    for ha in history_i:
                        ha_company = ha.get("company") or ""
                        if ha_company and ha_company in work_company_index and j in work_company_index[ha_company]:
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
                    existing_pair_keys.add(pair_key)  # type: ignore[arg-type]

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

    async def _discover_alumni(self, a: Entity, b: Entity) -> tuple[float, dict]:
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

    async def _discover_tech_overlap(self, a: Entity, b: Entity) -> tuple[float, dict]:
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

    async def _discover_deal_link(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Deal link: shared projects/deals."""
        deals_a = set((a.properties or {}).get("deals", []))
        deals_b = set((b.properties or {}).get("deals", []))
        common = deals_a & deals_b
        if common:
            return 1.0, {"common_deals": list(common)}
        return 0.0, {}

    async def _discover_risk_link(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Risk link: co-occurrence in negative events."""
        risk_events_a = (a.properties or {}).get("risk_events", [])
        risk_events_b = (b.properties or {}).get("risk_events", [])
        common = set(str(e) for e in risk_events_a) & set(str(e) for e in risk_events_b)
        if common:
            return 0.8, {"common_risk_events": len(common)}
        return 0.0, {}

    async def _discover_supply_chain(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Supply chain: upstream/downstream relationship."""
        company_a = (a.properties or {}).get("basic", {}).get("company", "") or ""
        company_b = (b.properties or {}).get("basic", {}).get("company", "") or ""
        supply_chain_map = self.config.get("supply_chain_map", {})
        if company_b in supply_chain_map.get(company_a, []):
            return 0.85, {"upstream": company_a, "downstream": company_b}
        if company_a in supply_chain_map.get(company_b, []):
            return 0.85, {"upstream": company_b, "downstream": company_a}
        return 0.0, {}

    # ── Semantic Association Types (LLM-assisted) ──

    def _discover_topic_overlap(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Topic overlap: entities whose events discuss similar topics/domains.

        Compares event_topics (from LLM extraction) and event_keywords
        between two entities using keyword overlap + topic similarity.
        Uses character-level tokenization for Chinese text to handle
        cases like "大模型应用" ∩ "大模型" → partial match.

        This captures semantic relationships like:
          - Entity A discussed "AI赛道投资" ↔ Entity B discussed "大模型API"
          - Both events share keywords like AI, 投资, 大模型

        Returns:
            (confidence, evidence_dict)
        """
        props_a = a.properties or {}
        props_b = b.properties or {}

        topics_a = set(props_a.get("event_topics", []))
        topics_b = set(props_b.get("event_topics", []))
        keywords_a_raw = props_a.get("event_keywords", [])
        keywords_b_raw = props_b.get("event_keywords", [])

        # Also consider entity-level tech_stack as topic signal
        tech_a = set(t.lower() for t in props_a.get("tech_stack", []))
        tech_b = set(t.lower() for t in props_b.get("tech_stack", []))

        # Build keyword sets with Chinese-aware normalization
        # For Chinese: use individual chars as tokens for fuzzy matching
        def _tokenize_chinese(texts: list[str]) -> set[str]:
            tokens = set()
            for t in texts:
                t_lower = t.lower()
                # Add the full string
                tokens.add(t_lower)
                # For Chinese strings, also add individual chars and bigrams
                # This handles "大模型应用" partially matching "大模型"
                if any("\u4e00" <= c <= "\u9fff" for c in t):
                    for i in range(len(t)):
                        tokens.add(t_lower[i])
                        if i < len(t) - 1:
                            tokens.add(t_lower[i:i + 2])
            return tokens

        all_keywords_a = _tokenize_chinese(keywords_a_raw) | tech_a
        all_keywords_b = _tokenize_chinese(keywords_b_raw) | tech_b

        if not all_keywords_a or not all_keywords_b:
            return 0.0, {}

        # Keyword overlap (Jaccard similarity on tokenized sets)
        kw_overlap = all_keywords_a & all_keywords_b
        kw_jaccard = len(kw_overlap) / min(len(all_keywords_a), len(all_keywords_b))

        # Topic string similarity (substring/semantic match)
        topic_score = 0.0
        matched_topics = []
        if topics_a and topics_b:
            for ta in topics_a:
                for tb in topics_b:
                    ta_words = set(ta)
                    tb_words = set(tb)
                    if ta_words & tb_words:
                        overlap_ratio = len(ta_words & tb_words) / min(len(ta_words), len(tb_words))
                        if overlap_ratio > 0.3:
                            topic_score = max(topic_score, overlap_ratio)
                            matched_topics.append((ta, tb))

        # Combine scores: keyword overlap (60%) + topic similarity (40%)
        confidence = 0.4 + kw_jaccard * 0.35 + topic_score * 0.25

        if confidence <= PROVISIONAL_THRESHOLD:
            return 0.0, {}

        evidence: dict[str, Any] = {}
        # Show original keyword matches (not tokenized), for readability
        orig_overlap = set(k.lower() for k in keywords_a_raw) & set(k.lower() for k in keywords_b_raw)
        if orig_overlap:
            evidence["common_keywords"] = list(orig_overlap)
        if kw_overlap:
            evidence["partial_keyword_matches"] = len(kw_overlap)
            evidence["keyword_overlap_ratio"] = round(kw_jaccard, 2)
        if matched_topics:
            evidence["matched_topic_pairs"] = matched_topics

        return confidence, evidence

    async def _discover_supply_demand(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Supply-demand match: A's resources can satisfy B's demands.

        This is PromiseLink's core value proposition — discovering that
        one person in your network has what another person needs.

        Matches entity A's resource.capabilities against entity B's concern (demand),
        and vice versa (bidirectional).

        Examples:
          - 张总(需求: 找投资方) ↔ 李总(资源: 盛恒资本投资人)
          - A(需求: 需要AI技术方案) ↔ B(资源: 大模型应用开发)

        Returns:
            (confidence, evidence_dict)
        """
        props_a = a.properties or {}
        props_b = b.properties or {}

        # Normalize capabilities: support both str list and dict list (F-53)
        def _norm_capabilities(props: dict) -> set[str]:
            caps = (props.get("resource", {}) or {}).get("capabilities", [])
            result = set()
            for c in caps:
                if isinstance(c, dict):
                    result.add(c.get("category", "").lower())
                elif isinstance(c, str):
                    result.add(c.lower())
            return result

        # Normalize concern: support both str list and dict list (F-53)
        def _norm_concern(props: dict) -> set[str]:
            items = props.get("concern") or []
            result = set()
            for d in items:
                if isinstance(d, dict):
                    result.add(d.get("category", "").lower())
                elif isinstance(d, str):
                    result.add(d.lower())
            return result

        res_a = _norm_capabilities(props_a)
        res_b = _norm_capabilities(props_b)
        demand_a = _norm_concern(props_a)
        demand_b = _norm_concern(props_b)

        # Bidirectional: A's resource → B's demand, AND B's resource → A's demand
        matches = []

        # A can supply what B needs
        a_supplies_b = res_a & demand_b
        if a_supplies_b:
            matches.append(("supplies", a.name, b.name, list(a_supplies_b)))

        # B can supply what A needs
        b_supplies_a = res_b & demand_a
        if b_supplies_a:
            matches.append(("supplies", b.name, a.name, list(b_supplies_a)))

        if not matches:
            # F-58: Semantic similarity fallback when structured matching finds nothing
            semantic_score = await self._semantic_similarity_fallback(a, b)
            if semantic_score > 0:
                return semantic_score * 0.3, {"semantic_match": True, "similarity": round(semantic_score, 4)}
            return 0.0, {}

        # Confidence based on match quality: more specific matches = higher confidence
        total_matches = sum(len(m[3]) for m in matches)
        confidence = 0.5 + min(total_matches * 0.1, 0.45)

        evidence = {
            "matches": [
                {"direction": m[0], "supplier": m[1], "requester": m[2], "matched_items": m[3]}
                for m in matches
            ],
            "total_match_count": total_matches,
        }

        # F-58: Blend with semantic similarity if available
        semantic_score = await self._semantic_similarity_fallback(a, b)
        if semantic_score > 0:
            # Hybrid: 70% structured + 30% semantic
            confidence = 0.7 * confidence + 0.3 * semantic_score
            evidence["semantic_boost"] = round(semantic_score, 4)

        return confidence, evidence

    async def _semantic_similarity_fallback(self, a: Entity, b: Entity) -> float:
        """F-58: Compute semantic similarity between two entities using embeddings.

        Uses pre-computed embeddings stored in vector_embeddings table.
        Returns 0.0 if embeddings are not available.

        Threshold: cosine_similarity > 0.7 to be considered a match.

        Args:
            a: First entity
            b: Second entity

        Returns:
            Semantic similarity score (0.0 ~ 1.0), or 0.0 if not available
        """
        try:
            import asyncio

            from promiselink.services.semantic_search import SemanticSearchEngine

            # Derive db_path from Settings (same as SemanticSearchEngine._default_db_path)
            db_path = SemanticSearchEngine._default_db_path()

            # Run synchronous sqlite3 in thread pool to avoid blocking event loop
            def _read_embeddings():
                import sqlite3
                conn = sqlite3.connect(db_path)
                try:
                    rows = conn.execute(
                        "SELECT embedding FROM vector_embeddings WHERE target_id = ? AND target_type = 'entity'",
                        (str(a.id),)
                    ).fetchone()
                    if not rows:
                        return None, None

                    import struct
                    blob_a = rows[0]
                    count = len(blob_a) // 4
                    emb_a = list(struct.unpack(f"{count}f", blob_a))

                    rows = conn.execute(
                        "SELECT embedding FROM vector_embeddings WHERE target_id = ? AND target_type = 'entity'",
                        (str(b.id),)
                    ).fetchone()
                    if not rows:
                        return emb_a, None

                    blob_b = rows[0]
                    count = len(blob_b) // 4
                    emb_b = list(struct.unpack(f"{count}f", blob_b))

                    return emb_a, emb_b
                finally:
                    conn.close()

            emb_a, emb_b = await asyncio.to_thread(_read_embeddings)

            if emb_a is None or emb_b is None:
                return 0.0

            # Cosine similarity
            similarity = SemanticSearchEngine._cosine_similarity(emb_a, emb_b)

            # Only return if above threshold
            if similarity > 0.7:
                return round(similarity, 4)
            return 0.0
        except Exception as e:
            # Embeddings not available, return 0.0 gracefully
            logger.error(f"semantic_similarity_failed: {e}")
            return 0.0

    async def _discover_industry_chain(self, a: Entity, b: Entity) -> tuple[float, dict]:
        """Industry chain: upstream/downstream industry relationship.

        Uses configurable industry chain mapping to detect relationships like:
          - Investment firm → Startup (investor-investee)
          - Platform provider → Application developer
          - Enterprise client → Solution vendor

        Config format (in self.config["industry_chain_map"]):
          {
            "投资": ["创业公司", "AI应用", "SaaS"],
            "互联网平台": ["应用开发者", "内容创作者"],
            ...
          }

        Also does basic inference from industry fields when no config exists:
          - "投资" industry ↔ technology/AI company = potential investor-startup link

        Returns:
            (confidence, evidence_dict)
        """
        basic_a = (a.properties or {}).get("basic", {})
        basic_b = (b.properties or {}).get("basic", {})
        industry_a = (basic_a.get("industry") or "").lower()
        industry_b = (basic_b.get("industry") or "").lower()
        company_a = (basic_a.get("company") or "")
        company_b = (basic_b.get("company") or "")

        if not industry_a or not industry_b:
            return 0.0, {}

        # Use configured chain map first
        chain_map = self.config.get("industry_chain_map", {})

        # Check both directions
        if industry_b in chain_map.get(industry_a, []):
            return 0.80, {
                "relation": "upstream_downstream",
                "upstream": f"{company_a}({industry_a})",
                "downstream": f"{company_b}({industry_b})",
            }
        if industry_a in chain_map.get(industry_b, []):
            return 0.80, {
                "relation": "upstream_downstream",
                "upstream": f"{company_b}({industry_b})",
                "downstream": f"{company_a}({industry_a})",
            }

        # Fallback: built-in inference rules for common industry pairs
        investment_keywords = {"投资", "创投", "风投", "vc", "pe", "基金", "资本"}
        tech_startup_keywords = {
            "人工智能", "ai", "大模型", "saas", "互联网", "科技",
            "软件开发", "信息技术", "创业",
        }

        a_is_investment = any(kw in industry_a for kw in investment_keywords)
        b_is_tech = any(kw in industry_b for kw in tech_startup_keywords)
        b_is_investment = any(kw in industry_b for kw in investment_keywords)
        a_is_tech = any(kw in industry_a for kw in tech_startup_keywords)

        if a_is_investment and b_is_tech:
            return 0.65, {
                "relation": "potential_investor_startup",
                "investor": f"{company_a}({industry_a})",
                "startup": f"{company_b}({industry_b})",
                "inference": "built_in_rule",
            }
        if b_is_investment and a_is_tech:
            return 0.65, {
                "relation": "potential_investor_startup",
                "investor": f"{company_b}({industry_b})",
                "startup": f"{company_a}({industry_a})",
                "inference": "built_in_rule",
            }

        return 0.0, {}

    # ── Helper Methods ──

    async def _fetch_entities_by_ids(self, entity_ids: list[str]) -> list[Entity]:
        """Fetch entities by their IDs."""
        if not entity_ids:
            return []
        stmt = select(Entity).where(Entity.id.in_(entity_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

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
                .where(Entity.user_id == user_id, Entity.entity_type == "person")
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
                    # Normalize direction: smaller ID first (consistent with _create_association)
                    if a_id > b_id:
                        a_id, b_id = b_id, a_id
                    key = (a_id, b_id, "co_occurrence")
                    if key in existing_pairs:
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

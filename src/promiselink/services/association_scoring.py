"""Scoring algorithms and similarity calculations for association discovery.

Contains the :class:`AssociationScoringMixin` with all confidence-scoring
and similarity-calculation methods used by
:class:`promiselink.services.association_discovery.AssociationDiscoveryEngine`.
"""

from __future__ import annotations

from typing import Any

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity

logger = get_logger("promiselink.association_discovery")

# Provisional threshold: associations below this confidence are discarded.
PROVISIONAL_THRESHOLD = 0.30

__all__ = ["AssociationScoringMixin", "PROVISIONAL_THRESHOLD"]


class AssociationScoringMixin:
    """Scoring and similarity methods for AssociationDiscoveryEngine.

    These methods are mixed into :class:`AssociationDiscoveryEngine` and
    rely on ``self.confirm_threshold`` and ``self.config`` being set by
    the host class.
    """

    # Provided by the host class (AssociationDiscoveryEngine)
    confirm_threshold: float
    config: dict[str, Any]

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

        def _normalize_entry(entry: Any) -> dict:
            """Normalize work_history entry to dict.

            LLM may return work_history as list of strings (company names)
            instead of list of dicts. Handle both formats gracefully.
            """
            if isinstance(entry, dict):
                return entry
            if isinstance(entry, str) and entry.strip():
                return {"company": entry.strip()}
            return {}

        for ha_raw in history_a:
            ha = _normalize_entry(ha_raw)
            if not ha.get("company"):
                continue
            for hb_raw in history_b:
                hb = _normalize_entry(hb_raw)
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
            def _read_embeddings() -> Any:
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
        except Exception as e:  # Graceful degradation — keep broad catch for resilience
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

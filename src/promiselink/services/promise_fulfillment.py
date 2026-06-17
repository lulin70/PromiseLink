"""Promise Fulfillment Engine — PoC promise fulfillment loop.

Renamed from OpportunityMatcher per v4.0 positioning.
PoC stage uses 3 dimensions: keyword_overlap(35%) + callability(35%) + industry(30%).
Phase1 adds care dimension, Phase2 enables full 6-dimension matching.
Algorithm Design §2 + §3.5
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from promiselink.services.llm_client import LLMClient
    from promiselink.services.llm_provider import LLMProvider

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo

logger = get_logger("promiselink.promise_fulfillment")


# ── Weight configurations per stage ──

POC_WEIGHTS = {
    "keyword_overlap": 0.35,
    "callability": 0.35,
    "industry_alignment": 0.30,
    # Disabled in PoC:
    "topic_similarity": 0.0,
    "llm_semantic": 0.0,
    "history_collaboration": 0.0,
}

PHASE1_WEIGHTS = {
    "keyword_overlap": 0.20,
    "industry_alignment": 0.15,
    "care": 0.30,
    "callability": 0.20,
    "history_collaboration": 0.10,
    "topic_similarity": 0.05,
    "llm_semantic": 0.0,
}

FULL_WEIGHTS = {
    "keyword_overlap": 0.25,
    "industry_alignment": 0.20,
    "topic_similarity": 0.15,
    "llm_semantic": 0.10,
    "history_collaboration": 0.10,
    "callability": 0.20,
}


class SensitivityFilter:
    """2-level sensitivity filter: matchable / no_match."""

    LEVELS = {"matchable": True, "no_match": False}
    DEFAULT = "matchable"

    def check(self, person: Entity) -> bool:
        """Check if person can participate in matching."""
        sensitivity = self._get_sensitivity(person)
        return self.LEVELS.get(sensitivity, True)

    def _get_sensitivity(self, person: Entity) -> str:
        props = person.properties or {}
        resource = props.get("resource", {})
        if isinstance(resource, dict):
            sens = resource.get("sensitivity")
            if sens:
                return str(sens)  # type: ignore[no-any-return]
        sens = props.get("resource_sensitivity")
        if sens:
            return str(sens)  # type: ignore[no-any-return]
        return self.DEFAULT

    def batch_filter(self, persons: list[Entity]) -> tuple[list[Entity], list[Entity]]:
        """Filter persons into (matchable, filtered) lists."""
        matchable: list[Entity] = []
        filtered: list[Entity] = []
        for p in persons:
            (matchable if self.check(p) else filtered).append(p)
        return matchable, filtered


class PromiseFulfillmentEngine:
    """Promise Fulfillment Engine — PoC stage 3-dimension matching.

    PoC: keyword_overlap(35%) + callability(35%) + industry(30%)
    Phase1: +care dimension (30%)
    Phase2: Full 6-dimension matching
    """

    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMProvider | LLMClient | None = None,
        config: dict | None = None,
        stage: str = "poc",
    ):
        self.session = session
        self.llm = llm_client
        self.config = config or {}
        self.sensitivity_filter = SensitivityFilter()

        if stage == "poc":
            self.weights = POC_WEIGHTS
        elif stage == "phase1":
            self.weights = PHASE1_WEIGHTS
        else:
            self.weights = FULL_WEIGHTS

        self.stage = stage

    async def calculate_match_score(
        self, todo: Todo, person: Entity
    ) -> dict[str, Any]:
        """Calculate match score between a todo and a person.

        Args:
            todo: The todo item to match.
            person: The person entity to match against.

        Returns:
            Dict with total_score, dimensions, match_reason, filtered.
        """
        # Sensitivity pre-filter
        if not self.sensitivity_filter.check(person):
            return {
                "total_score": 0.0,
                "dimensions": {},
                "match_reason": "Resource marked as no_match",
                "filtered": True,
            }

        # Calculate enabled dimensions
        d1 = self._keyword_overlap(todo, person)
        d2 = self._industry_alignment(todo, person)
        d3 = await self._topic_similarity(todo, person)
        d4 = await self._llm_semantic_judge(todo, person) if self.llm and self.weights.get("llm_semantic", 0) > 0 else 0.0
        d5 = self._history_collaboration(todo, person)
        d6 = self._callability(todo, person)

        dimensions = {
            "keyword_overlap": round(d1, 4),
            "industry_alignment": round(d2, 4),
            "topic_similarity": round(d3, 4),
            "llm_semantic": round(d4, 4),
            "history_collaboration": round(d5, 4),
            "callability": round(d6, 4),
        }

        total = sum(
            dimensions[k] * self.weights.get(k, 0.0)
            for k in dimensions
        )

        result = {
            "total_score": round(total, 4),
            "dimensions": dimensions,
            "match_reason": self._generate_reason(dimensions),
            "filtered": False,
        }

        logger.info(
            "match_score_calculated",
            todo_id=str(todo.id),
            person_id=str(person.id),
            total_score=result["total_score"],
        )
        return result

    async def find_matching_persons(
        self, todo: Todo, user_id: str, top_k: int = 5
    ) -> list[dict[str, Any]]:
        """Find top-k matching persons for a todo.

        Args:
            todo: The todo item to find matches for.
            user_id: Owner user ID.
            top_k: Number of top matches to return.

        Returns:
            List of match result dicts sorted by total_score descending.
        """
        # Get all person entities for this user
        stmt = select(Entity).where(
            and_(
                Entity.user_id == user_id,
                Entity.entity_type == "person",
                Entity.status.in_(["provisional", "confirmed", "merged"]),
            )
        )
        result = await self.session.execute(stmt)
        persons = list(result.scalars().all())

        # Filter by sensitivity
        matchable, filtered = self.sensitivity_filter.batch_filter(persons)

        if filtered:
            logger.info(
                "persons_filtered_by_sensitivity",
                filtered_count=len(filtered),
            )

        # Calculate scores
        matches = []
        for person in matchable:
            score_result = await self.calculate_match_score(todo, person)
            if score_result["total_score"] > 0.0:
                score_result["person_id"] = str(person.id)
                score_result["person_name"] = person.name
                matches.append(score_result)

        # Sort by total_score descending
        matches.sort(key=lambda x: x["total_score"], reverse=True)

        logger.info(
            "matching_completed",
            todo_id=str(todo.id),
            total_candidates=len(matchable),
            matches_found=len(matches),
            top_score=matches[0]["total_score"] if matches else 0.0,
        )
        return matches[:top_k]

    # ── Dimension 1: Keyword Overlap ──

    def _keyword_overlap(self, todo: Todo, person: Entity) -> float:
        """Keyword overlap — Jaccard similarity.

        PoC: Simple Jaccard on keyword sets.
        Phase1: TF-IDF weighted Jaccard.
        """
        todo_kw = set(
            (todo.properties or {}).get("keywords", [])
            if isinstance(todo.properties, dict)
            else []
        )
        person_kw = set(
            (person.properties or {}).get("keywords", [])
            if isinstance(person.properties, dict)
            else []
        )
        if not todo_kw or not person_kw:
            return 0.0
        intersection = todo_kw & person_kw
        union = todo_kw | person_kw
        return len(intersection) / len(union)

    # ── Dimension 2: Industry Alignment ──

    def _industry_alignment(self, todo: Todo, person: Entity) -> float:
        """Industry classification match.

        Exact match → 1.0, related industry → 0.5, no match → 0.0.
        """
        todo_domain = (
            (todo.properties or {}).get("domain_l1")
            if isinstance(todo.properties, dict)
            else None
        )
        person_industry = (
            (person.properties or {}).get("basic", {}).get("industry")
            if isinstance(person.properties, dict)
            else None
        )
        if not todo_domain or not person_industry:
            return 0.0
        if todo_domain == person_industry:
            return 1.0
        related = self.config.get("related_industries", {}).get(todo_domain, [])
        return 0.5 if person_industry in related else 0.0

    # ── Dimension 3: Topic Similarity ──

    async def _topic_similarity(self, todo: Todo, person: Entity) -> float:
        """Topic similarity — Jaccard on topic tags.

        PoC: Tag-based Jaccard.
        Phase1: Embedding cosine similarity.
        """
        todo_topics = set(
            (todo.properties or {}).get("topic_tags", [])
            if isinstance(todo.properties, dict)
            else []
        )
        person_topics = set(
            (person.properties or {}).get("topic_tags", [])
            if isinstance(person.properties, dict)
            else []
        )
        if not todo_topics or not person_topics:
            return 0.0
        intersection = todo_topics & person_topics
        union = todo_topics | person_topics
        return len(intersection) / len(union)

    # ── Dimension 4: LLM Semantic ──

    async def _llm_semantic_judge(self, todo: Todo, person: Entity) -> float:
        """LLM semantic judgment (Phase2 only)."""
        if self.llm is None:
            return 0.5
        sanitized = self._sanitize_for_llm(todo, person)
        try:
            response = await self.llm.generate(
                f"判断商机与人物的匹配度(0-1)：{json.dumps(sanitized, ensure_ascii=False)}",
                max_tokens=10,
            )
            return max(0.0, min(1.0, float(response.strip())))
        except (ValueError, Exception):
            return 0.5

    # ── Dimension 5: History Collaboration ──

    def _history_collaboration(self, todo: Todo, person: Entity) -> float:
        """History collaboration frequency.

        PoC: Returns 0.0 (no history data yet).
        Phase1: Segment mapping + time decay.
        """
        return 0.0  # PoC: no history data

    # ── Dimension 6: Callability ──

    def _callability(self, todo: Todo, person: Entity) -> float:
        """Callability — resource tags vs demand keywords match.

        Core dimension for private assistant positioning.
        """
        resources = (
            (person.properties or {}).get("resource", [])
            if isinstance(person.properties, dict)
            else []
        )
        if not resources:
            return 0.0

        demand_keywords = set(
            (todo.properties or {}).get("keywords", [])
            if isinstance(todo.properties, dict)
            else []
        )
        if not demand_keywords:
            return 0.3  # Neutral score when no explicit demand

        matched = sum(
            1 for r in resources
            if isinstance(r, dict) and set(r.get("tags", [])) & demand_keywords
        )
        return min(1.0, matched / max(len(resources), 1))

    # ── Helper Methods ──

    def _sanitize_for_llm(self, todo: Todo, person: Entity) -> dict:
        """Sanitize data for LLM input (no PII)."""
        todo_props = todo.properties or {} if isinstance(todo.properties, dict) else {}
        person_props = person.properties or {} if isinstance(person.properties, dict) else {}
        return {
            "todo": {
                "description": todo.description or "",
                "keywords": todo_props.get("keywords", []),
            },
            "person": {
                "company": person_props.get("basic", {}).get("company"),
                "title": person_props.get("basic", {}).get("title"),
                "industry": person_props.get("basic", {}).get("industry"),
            },
        }

    def _generate_reason(self, dimensions: dict[str, float]) -> str:
        """Generate human-readable match reason."""
        reasons = []
        if dimensions.get("industry_alignment", 0) >= 0.5:
            reasons.append("同行业")
        if dimensions.get("keyword_overlap", 0) >= 0.3:
            reasons.append("关键词相关")
        if dimensions.get("history_collaboration", 0) >= 0.3:
            reasons.append("有过合作")
        if dimensions.get("topic_similarity", 0) >= 0.5:
            reasons.append("话题相关")
        if dimensions.get("callability", 0) >= 0.5:
            reasons.append("可调用资源匹配")
        return "·".join(reasons) if reasons else "潜在关联"

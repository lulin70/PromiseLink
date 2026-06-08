"""Entity Resolution Engine — 5-step algorithm.

Algorithm Design §1: exact_match → alias_match → fuzzy_match → context_match → llm_reasoning
Thresholds: AUTO_MERGE ≥ 0.85, CONFIRM ≥ 0.70, CREATE < 0.70
"""

from __future__ import annotations

import json
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING
from datetime import UTC, datetime

if TYPE_CHECKING:
    from eventlink.services.llm_client import LLMClient
    from eventlink.services.llm_provider import LLMProvider

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.logging import get_logger
from eventlink.models.entity import Entity

logger = get_logger("eventlink.entity_resolution")


class ResolutionAction(str, Enum):
    """Action to take after resolution."""
    MERGE = "merge"
    CONFIRM = "confirm"
    CREATE = "create"


@dataclass
class ResolutionResult:
    """Result of entity resolution process."""
    action: ResolutionAction
    target_entity: Optional[Entity] = None
    confidence: float = 0.0
    matched_step: str = ""
    matched_fields: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    @property
    def is_merge(self) -> bool:
        return self.action == ResolutionAction.MERGE

    @property
    def needs_confirmation(self) -> bool:
        return self.action == ResolutionAction.CONFIRM


class EntityResolutionEngine:
    """Entity Resolution 5-step Engine.

    Steps (in priority order):
    1. exact_match — name exact match (confidence 0.85~1.0)
    2. alias_match — name in aliases list (confidence 0.80~0.95)
    3. fuzzy_match — rapidfuzz token_sort_ratio (confidence 0.70~0.90)
    4. context_match — company/city/industry overlap (confidence 0.0~0.60)
    5. llm_reasoning — LLM judgment (Phase1, PoC returns 0.0)
    """

    def __init__(
        self,
        session: AsyncSession,
        auto_merge_threshold: float = 0.85,
        confirm_threshold: float = 0.70,
        llm_client: LLMProvider | LLMClient | None = None,
    ):
        self.session = session
        self.auto_merge_threshold = auto_merge_threshold
        self.confirm_threshold = confirm_threshold
        self.llm = llm_client

    async def resolve(
        self, new_entity_data: dict[str, Any], user_id: str
    ) -> ResolutionResult:
        """Execute 5-step resolution for a new entity.

        Args:
            new_entity_data: Dict with keys: name, company, title, city,
                industry, entity_type, etc.
            user_id: Owner user ID for scoping.

        Returns:
            ResolutionResult with action, confidence, and matched info.
        """
        logger.info(
            "resolution_started",
            entity_name=new_entity_data.get("name"),
            user_id=user_id,
        )

        name_prefix = self._extract_surname(new_entity_data.get("name") or "")
        candidates = await self._find_candidates(new_entity_data, user_id, name_prefix=name_prefix)

        if not candidates:
            result = ResolutionResult(
                action=ResolutionAction.CREATE,
                confidence=0.0,
                matched_step="no_candidates",
                matched_fields={},
                explanation="No existing entities found, create new",
            )
            logger.info("resolution_no_candidates", entity_name=new_entity_data.get("name"))
            return result

        # Execute 4 deterministic steps in priority order
        steps = [
            ("exact_match", self._step_exact),
            ("alias_match", self._step_alias),
            ("fuzzy_match", self._step_fuzzy),
            ("context_match", self._step_context),
        ]

        for step_name, step_fn in steps:
            best_result: Optional[ResolutionResult] = None

            for candidate in candidates:
                confidence, matched_fields = step_fn(new_entity_data, candidate)

                if confidence >= self.auto_merge_threshold:
                    result = ResolutionResult(
                        action=ResolutionAction.MERGE,
                        target_entity=candidate,
                        confidence=confidence,
                        matched_step=step_name,
                        matched_fields=matched_fields,
                        explanation=f"{step_name}: confidence {confidence:.2f}, auto merge",
                    )
                    logger.info(
                        "resolution_auto_merge",
                        step=step_name,
                        confidence=confidence,
                        entity_name=new_entity_data.get("name"),
                        target_id=str(candidate.id),
                    )
                    return result

                if confidence >= self.confirm_threshold:
                    if best_result is None or confidence > best_result.confidence:
                        best_result = ResolutionResult(
                            action=ResolutionAction.CONFIRM,
                            target_entity=candidate,
                            confidence=confidence,
                            matched_step=step_name,
                            matched_fields=matched_fields,
                            explanation=f"{step_name}: confidence {confidence:.2f}, needs confirmation",
                        )

            if best_result:
                logger.info(
                    "resolution_needs_confirm",
                    step=step_name,
                    confidence=best_result.confidence,
                    entity_name=new_entity_data.get("name"),
                )
                return best_result

        # Step 5: LLM reasoning (Phase1 only)
        if self.llm:
            for candidate in candidates:
                confidence, matched_fields = await self._step_llm(
                    new_entity_data, candidate
                )
                if confidence >= self.auto_merge_threshold:
                    return ResolutionResult(
                        action=ResolutionAction.MERGE,
                        target_entity=candidate,
                        confidence=confidence,
                        matched_step="llm_reasoning",
                        matched_fields=matched_fields,
                        explanation=f"llm_reasoning: confidence {confidence:.2f}, auto merge",
                    )
                if confidence >= self.confirm_threshold:
                    return ResolutionResult(
                        action=ResolutionAction.CONFIRM,
                        target_entity=candidate,
                        confidence=confidence,
                        matched_step="llm_reasoning",
                        matched_fields=matched_fields,
                        explanation=f"llm_reasoning: confidence {confidence:.2f}, needs confirmation",
                    )

        # No match found — create new entity
        result = ResolutionResult(
            action=ResolutionAction.CREATE,
            confidence=0.0,
            matched_step="new_entity",
            matched_fields={},
            explanation="No matching candidate found, create new entity",
        )
        logger.info("resolution_create_new", entity_name=new_entity_data.get("name"))
        return result

    async def merge_entity(
        self, new_entity_data: dict[str, Any], target: Entity
    ) -> Entity:
        """Merge new entity data into an existing entity.

        Strategy: Keep canonical_name, merge properties, add new name to aliases.

        Args:
            new_entity_data: New entity data to merge.
            target: Existing entity to merge into.

        Returns:
            Updated target entity.
        """
        # Add new name to aliases if different from canonical
        new_name = new_entity_data.get("name", "").strip()
        if new_name and new_name != target.name and new_name != target.canonical_name:
            aliases = list(target.aliases or [])
            if new_name not in aliases:
                aliases.append(new_name)
                target.aliases = aliases

        # Merge properties (new values override old, old preserved in merge_history)
        existing_props = dict(target.properties or {})
        new_props = new_entity_data.get("properties", {})

        if new_props:
            # Preserve merge history
            merge_history = existing_props.get("merge_history", [])
            merge_history.append({
                "merged_at": datetime.now(UTC).isoformat(),
                "merged_fields": list(new_props.keys()),
            })
            existing_props["merge_history"] = merge_history

            # Override with new values, but deep-merge nested dicts
            for key, value in new_props.items():
                if value is None:
                    continue
                if key == "basic" and isinstance(value, dict):
                    # Deep merge: don't lose existing fields
                    existing_basic = dict(existing_props.get("basic", {}))
                    for bk, bv in value.items():
                        if bv is not None and bv != "":
                            existing_basic[bk] = bv
                    existing_props["basic"] = existing_basic
                elif key == "resource" and isinstance(value, dict):
                    # Deep merge resource
                    existing_resource = dict(existing_props.get("resource", {}))
                    for rk, rv in value.items():
                        if rv is not None:
                            existing_resource[rk] = rv
                    existing_props["resource"] = existing_resource
                else:
                    existing_props[key] = value

            target.properties = existing_props

        # Update basic info from new data if more complete
        basic = dict(existing_props.get("basic", {}))
        for field_key in ("company", "title", "city", "industry", "phone", "email"):
            new_val = new_entity_data.get(field_key)
            if new_val and not basic.get(field_key):
                basic[field_key] = new_val
        existing_props["basic"] = basic

        # Track event_ids for co_occurrence association discovery
        event_ids = list(existing_props.get("event_ids", []))
        new_event_id = new_entity_data.get("source_event_id")
        if new_event_id and str(new_event_id) not in event_ids:
            event_ids.append(str(new_event_id))
        # Also include target's own source_event_id
        if target.source_event_id and str(target.source_event_id) not in event_ids:
            event_ids.insert(0, str(target.source_event_id))
        existing_props["event_ids"] = event_ids

        target.properties = existing_props

        # Update confidence (take max)
        new_confidence = new_entity_data.get("confidence", 1.0)
        target.confidence = max(target.confidence, new_confidence)

        await self.session.flush()

        logger.info(
            "entity_merged",
            target_id=str(target.id),
            target_name=target.name,
            merged_name=new_name,
        )
        return target

    async def _find_candidates(
        self, new_entity_data: dict[str, Any], user_id: str, *, name_prefix: str = ""
    ) -> list[Entity]:
        """Find candidate entities for resolution.

        Optimized: first query by name prefix (LIKE 'X%') to narrow candidates,
        then fallback to full scan if prefix query returns too few results (<5).

        Args:
            new_entity_data: New entity data dict.
            user_id: Owner user ID for scoping.
            name_prefix: Surname prefix extracted from the new entity name,
                e.g. "许" from "许总". Used for SQL LIKE pre-filtering.
        """
        entity_type = new_entity_data.get("entity_type", "person")

        base_conditions = and_(
            Entity.user_id == user_id,
            Entity.entity_type == entity_type,
            Entity.status.in_(["provisional", "confirmed", "merged"]),
        )

        # Try prefix-filtered query first
        if name_prefix:
            stmt = select(Entity).where(
                and_(base_conditions, Entity.name.like(f"{name_prefix}%"))
            )
            result = await self.session.execute(stmt)
            candidates = list(result.scalars().all())

            if len(candidates) >= 5:
                logger.debug(
                    "find_candidates_prefix_hit",
                    prefix=name_prefix,
                    count=len(candidates),
                )
                return candidates

            # Too few results with prefix — fallback to full scan
            logger.debug(
                "find_candidates_prefix_fallback",
                prefix=name_prefix,
                count=len(candidates),
            )

        stmt = select(Entity).where(base_conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ── Step 1: Exact Match ──

    def _step_exact(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Step 1: Exact name match (case-insensitive, trimmed).

        Returns:
            (confidence, matched_fields) tuple.
        """
        new_name = (new.get("name") or "").lower().strip()
        existing_name = existing.name.lower().strip()

        if new_name != existing_name:
            return 0.0, {}

        company_match = self._compare_company(new, existing)
        score = 1.0 if company_match else 0.85
        fields = {"name": 1.0, "company": 1.0 if company_match else 0.5}
        return score, fields

    # ── Step 2: Alias Match ──

    # Chinese honorific patterns: "X总" → "X" surname, "X哥/X姐" → "X" surname
    HONORIFIC_SUFFIXES = ("总", "哥", "姐", "叔", "姨", "爷", "老", "董", "局", "处", "院")

    def _step_alias(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Step 2: Name in aliases list or Chinese honorific match.

        Extended with Chinese honorific matching:
        - "许总" matches "许永亮" (surname + honorific → full name)
        - "许总" matches "许总/许永亮" (already in aliases)

        Returns:
            (confidence, matched_fields) tuple.
        """
        new_name = (new.get("name") or "").strip()
        existing_name = existing.name.strip()
        aliases = existing.aliases or []

        # Check direct alias match
        if new_name in aliases:
            company_match = self._compare_company(new, existing)
            score = 0.95 if company_match else 0.80
            fields = {"name": 0.95, "alias": True, "company": 1.0 if company_match else 0.5}
            return score, fields

        # Check if new_name is in existing_name (e.g., "许总" in "许总/许永亮")
        if new_name in existing_name and "/" in existing_name:
            company_match = self._compare_company(new, existing)
            score = 0.90 if company_match else 0.80
            fields = {"name": 0.90, "alias": True, "company": 1.0 if company_match else 0.5}
            return score, fields

        # Chinese honorific matching: "许总" → surname "许" → match "许永亮"
        new_surname = self._extract_surname(new_name)
        if new_surname:
            # Check if existing name starts with the same surname
            existing_surname = self._extract_surname(existing_name)
            if new_surname == existing_surname and new_surname:
                # Same surname + honorific pattern → likely same person
                # Boost confidence if company also matches
                company_match = self._compare_company(new, existing)
                # Also check if they share context (same event, same company)
                context_boost = 0.0
                if company_match:
                    context_boost = 0.10
                # Base score: surname match is strong signal in Chinese business context
                score = 0.82 + context_boost
                fields = {
                    "name": 0.82,
                    "surname_match": new_surname,
                    "company": 1.0 if company_match else 0.5,
                }
                return score, fields

            # Also check aliases for surname match
            for alias in aliases:
                alias_surname = self._extract_surname(alias)
                if new_surname == alias_surname and new_surname:
                    company_match = self._compare_company(new, existing)
                    score = 0.85 if company_match else 0.80
                    fields = {
                        "name": 0.85,
                        "surname_match": new_surname,
                        "alias": True,
                        "company": 1.0 if company_match else 0.5,
                    }
                    return score, fields

        return 0.0, {}

    @classmethod
    def _extract_surname(cls, name: str) -> str:
        """Extract surname from a Chinese name with honorific.

        Examples:
            "许总" → "许"
            "许永亮" → "许"
            "李总" → "李"
            "陈宇欣" → "陈"
            "PM" → "" (non-Chinese)

        Returns:
            Surname string, or empty string if not a Chinese name.
        """
        if not name or len(name) < 1:
            return ""
        first_char = name[0]
        # Check if first character is a common Chinese surname character
        # (CJK Unified Ideographs range: U+4E00-U+9FFF)
        if '\u4e00' <= first_char <= '\u9fff':
            # If name is "X总/X哥/X姐" pattern, surname is X
            if len(name) == 2 and name[1] in cls.HONORIFIC_SUFFIXES:
                return first_char
            # If name is longer and starts with a surname, return first char
            # Common Chinese surnames are 1 character (rarely 2)
            return first_char
        return ""

    # ── Step 3: Fuzzy Match ──

    def _step_fuzzy(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Step 3: Fuzzy name match using rapidfuzz.

        Score = name_sim * 0.5 + company_sim * 0.3 + title_sim * 0.2
        Capped at 0.90 to prevent false merges.

        Returns:
            (confidence, matched_fields) tuple.
        """
        try:
            from rapidfuzz import fuzz
        except ImportError:
            # Fallback: simple string comparison
            return self._fuzzy_fallback(new, existing)

        new_name = new.get("name") or ""
        name_sim = fuzz.token_sort_ratio(new_name, existing.name) / 100

        if name_sim < 0.70:
            return 0.0, {}

        existing_basic = (existing.properties or {}).get("basic", {})
        company_sim = fuzz.token_sort_ratio(
            new.get("company") or "", existing_basic.get("company") or ""
        ) / 100
        title_sim = fuzz.token_sort_ratio(
            new.get("title") or "", existing_basic.get("title") or ""
        ) / 100

        score = name_sim * 0.5 + company_sim * 0.3 + title_sim * 0.2
        fields = {"name": round(name_sim, 4), "company": round(company_sim, 4), "title": round(title_sim, 4)}
        return min(score, 0.90), fields

    def _fuzzy_fallback(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Simple fuzzy fallback when rapidfuzz is not available."""
        new_name = (new.get("name") or "").lower().strip()
        existing_name = existing.name.lower().strip()

        # Simple character overlap ratio
        if not new_name or not existing_name:
            return 0.0, {}

        set_a = set(new_name)
        set_b = set(existing_name)
        overlap = len(set_a & set_b)
        union = len(set_a | set_b)
        name_sim = overlap / union if union > 0 else 0.0

        if name_sim < 0.70:
            return 0.0, {}

        score = min(name_sim * 0.7, 0.90)
        return score, {"name": round(name_sim, 4)}

    # ── Step 4: Context Match ──

    def _step_context(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Step 4: Context-based matching (company/city/industry).

        Max score 0.60 — context alone is not sufficient for merge.

        Returns:
            (confidence, matched_fields) tuple.
        """
        context_score = 0.0
        fields: dict[str, float] = {}
        existing_basic = (existing.properties or {}).get("basic", {}) if existing.properties else {}

        if self._same_value(new.get("company"), existing_basic.get("company")):
            context_score += 0.30
            fields["company"] = 1.0

        if self._same_value(new.get("city"), existing_basic.get("city")):
            context_score += 0.20
            fields["city"] = 1.0

        if self._overlapping_industries(new, existing):
            context_score += 0.10
            fields["industry"] = 0.8

        return context_score, fields

    # ── Step 5: LLM Reasoning (Phase1) ──

    @staticmethod
    def _sanitize_for_llm(
        new: dict[str, Any], existing: Entity, existing_basic: dict
    ) -> dict:
        """Sanitize entity data for LLM input (strip potential prompt injection).

        Only includes safe fields, truncates long values, removes special chars.
        """
        def _safe(value: Any, max_len: int = 100) -> str:
            if not value:
                return ""
            text = str(value)[:max_len]
            # Remove characters that could be interpreted as prompt instructions
            text = text.replace("\n", " ").replace("```", "")
            return text.strip()

        return {
            "entity_a": {
                "name": _safe(new.get("name")),
                "company": _safe(new.get("company")),
                "title": _safe(new.get("title")),
                "city": _safe(new.get("city")),
            },
            "entity_b": {
                "name": _safe(existing.name),
                "company": _safe(existing_basic.get("company")),
                "title": _safe(existing_basic.get("title")),
            },
        }

    async def _step_llm(
        self, new: dict[str, Any], existing: Entity
    ) -> tuple[float, dict[str, float]]:
        """Step 5: LLM-based reasoning (Phase1 only).

        PoC: Returns 0.0 (skip LLM, create new entity).
        Phase1: Call LLM API with entity comparison prompt.
        """
        if not self.llm:
            return 0.0, {}

        existing_basic = (existing.properties or {}).get("basic", {}) if existing.properties else {}
        # Sanitize inputs to prevent prompt injection
        sanitized = self._sanitize_for_llm(new, existing, existing_basic)
        prompt = (
            f"判断以下两个实体是否为同一人/组织，返回0-1的置信度：\n"
            f"实体A: {json.dumps(sanitized['entity_a'], ensure_ascii=False)}\n"
            f"实体B: {json.dumps(sanitized['entity_b'], ensure_ascii=False)}\n"
            f"只返回数字："
        )
        try:
            response = await self.llm.generate(prompt, max_tokens=10)
            score = self._parse_llm_confidence(response)
            return score, {"llm_judgment": score}
        except Exception as e:
            logger.warning("llm_resolution_failed", error=str(e))
            return 0.0, {}

    # ── Helper Methods ──

    @staticmethod
    def _parse_llm_confidence(text: str) -> float:
        """Extract confidence score from LLM response text.

        Handles cases where LLM returns extra text alongside the number,
        e.g. "0.05\\n\\n这两个实体几乎可以确定不是同一人..."

        Args:
            text: Raw LLM response text.

        Returns:
            Confidence score clamped to [0.0, 1.0], or 0.5 as default.
        """
        import re as _re

        if not text or not text.strip():
            return 0.5

        text = text.strip()

        # Strategy 1: Try direct float parse (ideal case)
        try:
            score = float(text)
            return max(0.0, min(1.0, score))
        except ValueError:
            pass

        # Strategy 2: Find number after confidence keyword
        match = _re.search(
            r'(?:confidence|置信度|得分|分数)[:\s]*([01]?\.?\d+)',
            text,
            _re.IGNORECASE,
        )
        if match:
            try:
                score = float(match.group(1))
                return max(0.0, min(1.0, score))
            except ValueError:
                pass

        # Strategy 3: Find first float-like number (0.0 to 1.0 pattern)
        match = _re.search(r'([01]\.\d+)', text)
        if match:
            try:
                return max(0.0, min(1.0, float(match.group(1))))
            except ValueError:
                pass

        # Strategy 4: Find any number at the start of the text
        match = _re.match(r'\s*(\d+\.?\d*)', text)
        if match:
            try:
                score = float(match.group(1))
                if 0.0 <= score <= 1.0:
                    return score
            except ValueError:
                pass

        return 0.5  # Default confidence when parsing fails

    def _compare_company(self, new: dict[str, Any], existing: Entity) -> bool:
        """Compare company field between new data and existing entity."""
        new_company = (new.get("company") or "").lower().strip()
        existing_company = (
            (existing.properties or {}).get("basic", {}).get("company") or ""
        ).lower().strip()
        if not new_company or not existing_company:
            return True  # If either is missing, don't penalize
        return new_company == existing_company

    @staticmethod
    def _same_value(a: Any, b: Any) -> bool:
        """Check if two values are the same (case-insensitive string comparison)."""
        if not a or not b:
            return False
        return str(a).lower().strip() == str(b).lower().strip()

    @staticmethod
    def _overlapping_industries(new: dict[str, Any], existing: Entity) -> bool:
        """Check if industries overlap."""
        new_ind = new.get("industry") or ""
        exist_ind = (existing.properties or {}).get("basic", {}).get("industry") or ""
        if not new_ind or not exist_ind:
            return False
        return new_ind.lower().strip() == exist_ind.lower().strip()

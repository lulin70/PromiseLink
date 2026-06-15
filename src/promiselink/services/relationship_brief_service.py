"""RelationshipBrief Service — F-47: Generate and manage relationship progress tracking cards.

Implements 12-module relationship brief generation and management:
  1. basic_info          - Basic info (name, company, role)
  2. relationship_stage  - Current stage (new_connection → dormant)
  3. last_interaction    - Last contact time and context
  4. interaction_freq    - Interaction frequency analysis
  5. open_promises       - Outstanding promises (my + their)
  6. their_concerns      - What they care about
  7. my_contributions    - What I've helped with
  8. cooperation_signals - Potential cooperation signals
  9. risk_flags          - Risk indicators
  10. next_actions        - Recommended next steps
  11. strength_score      - Relationship strength (0-100)
  12. notes               - Manual notes
"""

from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from promiselink.services.llm_client import LLMClient
    from promiselink.services.llm_provider import LLMProvider

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.logging import get_logger
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.relationship_brief import RelationshipBrief
from promiselink.models.todo import Todo

logger = get_logger("promiselink.relationship_brief_service")

# Valid relationship stages
VALID_STAGES = {
    "new_connection",
    "understanding_needs",
    "value_response",
    "deep_trust",
    "active_cooperation",
    "long_term_partner",
    "dormant",
}


@dataclass
class BriefGenerationResult:
    """Result of a brief update/generation operation."""

    brief: RelationshipBrief | None
    modules_updated: list[str] = field(default_factory=list)
    is_new: bool = False


class RelationshipBriefService:
    """F-47: Generate and manage relationship progress tracking cards.

    Provides CRUD operations and automatic module updates based on events/todos.
    Uses optimistic locking with version field for concurrent updates.
    """

    def __init__(
        self,
        session: AsyncSession,
        llm_client: LLMProvider | LLMClient | None = None,
    ) -> None:
        self.session = session
        self.llm_client = llm_client

    # ── Core CRUD ──────────────────────────────────────────────

    async def get_or_create_brief(
        self,
        user_id: str,
        person_entity_id: str,
    ) -> tuple[RelationshipBrief, bool]:
        """Get existing brief or create new one.

        Args:
            user_id: The owner user ID.
            person_entity_id: The target person entity ID.

        Returns:
            Tuple of (brief, is_new) where is_new indicates if a new record was created.
        """
        result = await self.session.execute(
            select(RelationshipBrief).where(
                RelationshipBrief.user_id == user_id,
                RelationshipBrief.person_entity_id == person_entity_id,
            )
        )
        brief = result.scalar_one_or_none()

        if brief is not None:
            return brief, False

        # Create new brief with default structure
        brief = RelationshipBrief(
            user_id=user_id,
            person_entity_id=person_entity_id,
            relationship_stage="new_connection",
            brief_data=self._default_brief_data(),
            version=1,
        )
        self.session.add(brief)
        await self.session.flush()

        logger.info(
            "brief_created",
            user_id=user_id,
            person_entity_id=person_entity_id,
            brief_id=str(brief.id),
        )

        return brief, True

    async def get_brief(
        self,
        user_id: str,
        person_entity_id: str,
    ) -> RelationshipBrief:
        """Get brief by user + person entity. Raises if not found.

        Args:
            user_id: The owner user ID.
            person_entity_id: The target person entity ID.

        Returns:
            The RelationshipBrief instance.

        Raises:
            ValueError: If no brief exists for this pair.
        """
        result = await self.session.execute(
            select(RelationshipBrief).where(
                RelationshipBrief.user_id == user_id,
                RelationshipBrief.person_entity_id == person_entity_id,
            )
        )
        brief = result.scalar_one_or_none()

        if brief is None:
            raise ValueError(
                f"RelationshipBrief not found for user={user_id}, "
                f"person_entity={person_entity_id}"
            )

        return brief

    async def list_briefs(
        self,
        user_id: str,
        stage: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RelationshipBrief], int]:
        """List briefs for a user, optionally filtered by stage.

        Args:
            user_id: The owner user ID.
            stage: Optional relationship stage to filter by.
            limit: Max results to return.
            offset: Pagination offset.

        Returns:
            Tuple of (list of briefs, total count).
        """
        query = select(RelationshipBrief).where(
            RelationshipBrief.user_id == user_id
        )

        count_query = select(func.count()).select_from(RelationshipBrief).where(
            RelationshipBrief.user_id == user_id
        )

        if stage is not None:
            query = query.where(RelationshipBrief.relationship_stage == stage)
            count_query = count_query.where(
                RelationshipBrief.relationship_stage == stage
            )

        total = (await self.session.execute(count_query)).scalar() or 0

        query = (
            query.order_by(RelationshipBrief.last_updated_at.desc())
            .limit(min(limit, 500))
            .offset(offset)
        )
        result = await self.session.execute(query)
        briefs = list(result.scalars().all())

        return briefs, total

    # ── Event-driven Update ────────────────────────────────────

    async def update_brief_from_event(
        self,
        user_id: str,
        person_entity_id: str,
        event: Event,
        entities: list[Entity] | None = None,
        todos: list[Todo] | None = None,
    ) -> BriefGenerationResult:
        """Update a relationship brief after processing an event.

        Updates these modules:
        - last_interaction   (always update to latest event)
        - interaction_freq   (recount from available data)
        - open_promises      (sync from todos)
        - their_concerns     (extract from care-type todos)
        - my_contributions   (extract from help-type todos)
        - cooperation_signals(extract from cooperation_signal-type todos)
        - risk_flags         (extract from risk-type todos)
        - next_actions       (regenerate top 3)
        - strength_score     (recalculate based on all data)

        Uses optimistic locking with version field.

        Args:
            user_id: Owner user ID.
            person_entity_id: Target person entity ID.
            event: The newly processed event.
            entities: Optional related entities.
            todos: Optional generated/related todos.

        Returns:
            BriefGenerationResult with updated brief and changed modules.
        """
        brief, is_new = await self.get_or_create_brief(user_id, person_entity_id)

        modules_updated: list[str] = []
        data = copy.deepcopy(brief.brief_data) if brief.brief_data else {}

        # 1. Update last_interaction
        data["last_interaction"] = self._build_last_interaction(event)
        modules_updated.append("last_interaction")

        # 2. Update basic_info from entity if provided
        if entities:
            person_entity = next(
                (e for e in entities if str(e.id) == person_entity_id), None
            )
            if person_entity:
                data["basic_info"] = self._build_basic_info(person_entity)
                modules_updated.append("basic_info")

        # Fallback: query entity from DB if basic_info is still empty
        if not data.get("basic_info", {}).get("name"):
            try:
                db_entity_result = await self.session.execute(
                    select(Entity).where(Entity.id == person_entity_id)
                )
                db_entity = db_entity_result.scalar_one_or_none()
                if db_entity:
                    data["basic_info"] = self._build_basic_info(db_entity)
                    if "basic_info" not in modules_updated:
                        modules_updated.append("basic_info")
            except Exception:
                logger.debug(
                    "brief_basic_info_db_fallback_failed",
                    person_entity_id=person_entity_id,
                )

        # 3. Update interaction_freq
        data["interaction_freq"] = await self._build_interaction_freq(
            user_id, person_entity_id, event
        )
        modules_updated.append("interaction_freq")

        # 4. Sync open_promises from todos
        if todos:
            data["open_promises"] = self._sync_open_promises(todos)
            modules_updated.append("open_promises")

            # Extract concerns/contributions/signals/risks from todos
            concerns = self._extract_their_concerns(todos)
            if concerns:
                existing = set(data.get("their_concerns", []))
                existing.update(concerns)
                data["their_concerns"] = sorted(existing)
                modules_updated.append("their_concerns")

            contributions = self._extract_my_contributions(todos)
            if contributions:
                existing = set(data.get("my_contributions", []))
                existing.update(contributions)
                data["my_contributions"] = sorted(existing)
                modules_updated.append("my_contributions")

            signals = self._extract_cooperation_signals(todos)
            if signals:
                existing = set(data.get("cooperation_signals", []))
                existing.update(signals)
                data["cooperation_signals"] = sorted(existing)
                modules_updated.append("cooperation_signals")

            risks = self._extract_risk_flags(todos)
            if risks:
                existing = set(data.get("risk_flags", []))
                existing.update(risks)
                data["risk_flags"] = sorted(existing)
                modules_updated.append("risk_flags")

        # 5. Regenerate next_actions (include association-based suggestions)
        associations = await self._get_associations_for_entity(str(brief.person_entity_id))
        data["next_actions"] = self._generate_next_actions(data, associations)
        modules_updated.append("next_actions")

        # 6. Recalculate strength_score
        data["strength_score"] = self._calculate_strength_score(data)
        modules_updated.append("strength_score")

        # 7. Sync relationship_stage into brief_data
        data["relationship_stage"] = brief.relationship_stage

        # Apply changes with optimistic lock increment
        brief.brief_data = data
        brief.version += 1
        # Force SQLAlchemy to detect JSON/JSONB mutation (critical for SQLite)
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(brief, "brief_data")

        await self.session.flush()

        logger.info(
            "brief_updated_from_event",
            brief_id=str(brief.id),
            modules=modules_updated,
            version=brief.version,
        )

        return BriefGenerationResult(
            brief=brief,
            modules_updated=modules_updated,
            is_new=is_new,
        )

    async def update_brief_partial(
        self,
        brief_id: str,
        notes: str | None = None,
        brief_data_partial: dict | None = None,
        expected_version: int | None = None,
    ) -> RelationshipBrief:
        """Partial update of a brief with optimistic locking.

        Args:
            brief_id: The brief UUID.
            notes: New notes text to set.
            brief_data_partial: Partial dict to merge into brief_data.
            expected_version: Expected current version for optimistic lock.

        Returns:
            Updated RelationshipBrief.

        Raises:
            ValueError: If brief not found or version mismatch.
        """
        result = await self.session.execute(
            select(RelationshipBrief).where(RelationshipBrief.id == brief_id)
        )
        brief = result.scalar_one_or_none()

        if brief is None:
            raise ValueError(f"RelationshipBrief not found: {brief_id}")

        if expected_version is not None and brief.version != expected_version:
            raise ValueError(
                f"Optimistic lock conflict: expected version {expected_version}, "
                f"current version {brief.version}"
            )

        data = copy.deepcopy(brief.brief_data) if brief.brief_data else {}

        if notes is not None:
            data["notes"] = notes

        if brief_data_partial:
            data.update(brief_data_partial)

        # Recalculate derived fields after manual update
        entity_id = str(brief.person_entity_id)
        associations = await self._get_associations_for_entity(entity_id)
        data["next_actions"] = self._generate_next_actions(data, associations)
        data["strength_score"] = self._calculate_strength_score(data)

        brief.brief_data = data
        brief.version += 1
        # Force SQLAlchemy to detect JSON/JSONB mutation (critical for SQLite)
        from sqlalchemy.orm.attributes import flag_modified as _flag_modified
        _flag_modified(brief, "brief_data")

        await self.session.flush()

        logger.info(
            "brief_partial_update",
            brief_id=str(brief.id),
            version=brief.version,
        )

        return brief

    # ── Static Helpers ──────────────────────────────────────────

    @staticmethod
    def _default_brief_data() -> dict[str, Any]:
        """Return default empty brief_data structure."""
        return {
            "basic_info": {},
            "relationship_stage": "new_connection",
            "last_interaction": {},
            "interaction_freq": {
                "total_count": 0,
                "last_30_days": 0,
                "avg_interval_days": 0,
            },
            "open_promises": {"my_promises": [], "their_promises": []},
            "their_concerns": [],
            "my_contributions": [],
            "cooperation_signals": [],
            "risk_flags": [],
            "next_actions": [],
            "strength_score": 0,
            "notes": "",
        }

    @staticmethod
    def _build_last_interaction(event: Event) -> dict[str, Any]:
        """Build last_interaction dict from an event."""
        return {
            "date": event.timestamp.isoformat() if event.timestamp else datetime.now(timezone.utc).isoformat(),
            "event_type": event.event_type,
            "summary": (event.title or "")[:200],
        }

    @staticmethod
    def _build_basic_info(entity: Entity) -> dict[str, Any]:
        """Build basic_info dict from an Entity."""
        props = entity.properties or {}
        basic = props.get("basic", {})
        return {
            "name": entity.name or "",
            "company": basic.get("company", ""),
            "role": basic.get("title", ""),
            "contact_summary": "",
        }

    async def _build_interaction_freq(
        self,
        user_id: str,
        person_entity_id: str,
        latest_event: Event,
    ) -> dict[str, Any]:
        """Build interaction_freq summary.

        Counts events referencing this person entity.
        For PoC, uses simple counting without full history scan.
        """
        # Count total events for this user-person pair via entity references
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        # Simple approach: count all events for user as proxy
        total_result = await self.session.execute(
            select(func.count()).select_from(Event).where(Event.user_id == user_id)
        )
        total_count = total_result.scalar() or 0

        recent_result = await self.session.execute(
            select(func.count())
            .select_from(Event)
            .where(
                Event.user_id == user_id,
                Event.timestamp >= thirty_days_ago,
            )
        )
        recent_count = recent_result.scalar() or 0

        avg_interval = 0
        if recent_count > 1:
            avg_interval = round(30 / recent_count)

        return {
            "total_count": total_count + 1,  # include current event
            "last_30_days": recent_count + 1,
            "avg_interval_days": avg_interval,
        }

    @staticmethod
    def _sync_open_promises(todos: list[Todo]) -> dict[str, list[dict]]:
        """Sync open promises from pending/in_progress todos."""
        my_promises: list[dict] = []
        their_promises: list[dict] = []

        for todo in todos:
            if todo.status in ("done", "dismissed"):
                continue

            promise_entry: dict[str, Any] = {
                "title": todo.title,
                "due_date": todo.due_date.isoformat() if todo.due_date else None,
            }

            action_type = getattr(todo, "action_type", None) or ""
            if action_type in ("my_promise", "my_followup"):
                my_promises.append(promise_entry)
            elif action_type == "their_promise":
                their_promises.append(promise_entry)
            else:
                # Default: treat as my promise
                my_promises.append(promise_entry)

        return {"my_promises": my_promises, "their_promises": their_promises}

    @staticmethod
    def _extract_their_concerns(todos: list[Todo]) -> list[str]:
        """Extract concerns from care-type todos."""
        concerns: list[str] = []
        for todo in todos:
            if todo.todo_type == "care" and todo.title:
                concerns.append(todo.title[:100])
        return concerns

    @staticmethod
    def _extract_my_contributions(todos: list[Todo]) -> list[str]:
        """Extract contributions from help-type todos."""
        contributions: list[str] = []
        for todo in todos:
            if todo.todo_type == "help" and todo.title:
                contributions.append(todo.title[:100])
        return contributions

    @staticmethod
    def _extract_cooperation_signals(todos: list[Todo]) -> list[str]:
        """Extract cooperation signals from cooperation_signal-type todos."""
        signals: list[str] = []
        for todo in todos:
            if todo.todo_type == "cooperation_signal" and todo.title:
                signals.append(todo.title[:100])
        return signals

    @staticmethod
    def _extract_risk_flags(todos: list[Todo]) -> list[str]:
        """Extract risk flags from risk-type todos."""
        flags: list[str] = []
        for todo in todos:
            if todo.todo_type == "risk" and todo.title:
                flags.append(todo.title[:100])
        return flags

    @staticmethod
    def _calculate_strength_score(brief_data: dict) -> int:
        """Calculate relationship strength score (0-100).

        Factors:
        - interaction_freq.last_30_days (up to 30 pts)
        - open_promises count (up to 20 pts, having promises means engagement)
        - their_concerns known (up to 15 pts)
        - my_contributions count (up to 15 pts)
        - recency of last_interaction (up to 20 pts)
        """
        score = 0

        freq = brief_data.get("interaction_freq", {})
        last_30 = freq.get("last_30_days", 0)
        score += min(last_30 * 3, 30)  # up to 30 pts

        promises = brief_data.get("open_promises", {})
        my_p = len(promises.get("my_promises", []))
        their_p = len(promises.get("their_promises", []))
        promise_count = my_p + their_p
        score += min(promise_count * 5, 20)  # up to 20 pts

        concerns = brief_data.get("their_concerns", [])
        if concerns:
            score += min(len(concerns) * 5, 15)  # up to 15 pts

        contributions = brief_data.get("my_contributions", [])
        if contributions:
            score += min(len(contributions) * 5, 15)  # up to 15 pts

        last_int = brief_data.get("last_interaction", {})
        date_str = last_int.get("date")
        if date_str:
            try:
                last_date = datetime.fromisoformat(date_str)
                days_ago = (datetime.now(timezone.utc) - last_date).days
                if days_ago <= 1:
                    score += 20
                elif days_ago <= 7:
                    score += 14
                elif days_ago <= 14:
                    score += 8
                elif days_ago <= 30:
                    score += 4
            except (ValueError, TypeError):
                pass

        return min(score, 100)

    async def _get_associations_for_entity(self, entity_id: str) -> list[dict]:
        """Fetch associations involving this entity for action generation.

        Returns list of dicts with: association_type, other_entity_name, evidence.
        """
        from promiselink.models.association import Association
        from promiselink.models.entity import Entity

        result = await self.session.execute(
            select(Association).where(
                (Association.source_entity_id == entity_id)
                | (Association.target_entity_id == entity_id)
            )
        )
        assocs = result.scalars().all()

        # Also run cold-type discovery for richer suggestions
        ent_result = await self.session.execute(
            select(Entity).where(Entity.id == entity_id)
        )
        entity = ent_result.scalar_one_or_none()
        if not entity:
            return []

        # Get all other entities for cold discovery
        all_ent_result = await self.session.execute(
            select(Entity).where(Entity.id != entity_id)
        )
        other_entities = all_ent_result.scalars().all()

        # Build entity name map
        name_map = {str(entity.id): entity.name}
        for e in other_entities:
            name_map[str(e.id)] = e.name

        entries = []
        seen_types = set()

        # Hot associations from DB
        for a in assocs:
            other_id = str(a.target_entity_id if str(a.source_entity_id) == entity_id else a.source_entity_id)
            other_name = name_map.get(other_id, "")
            key = (a.association_type, other_name)
            if key not in seen_types:
                seen_types.add(key)
                entries.append({
                    "association_type": a.association_type,
                    "other_entity_name": other_name,
                    "evidence": (a.properties or {}).get("evidence", {}),
                    "confidence": a.confidence or 0,
                })

        # Cold associations (semantic discoveries)
        try:
            from promiselink.services.association_discovery import AssociationDiscoveryEngine
            engine = AssociationDiscoveryEngine(self.session)
            for other in other_entities:
                cold_results = await engine.discover_cold_types(entity, other)
                for cr in cold_results:
                    atype = cr["association_type"]
                    key = (atype, other.name)
                    if key not in seen_types:
                        seen_types.add(key)
                        entries.append({
                            "association_type": atype,
                            "other_entity_name": other.name,
                            "evidence": cr.get("evidence", {}),
                            "confidence": cr.get("confidence", 0),
                        })
        except Exception:
            logger.debug("cold_discovery_failed_best_effort", entity_id=entity_id)

        return entries

    @staticmethod
    def _generate_next_actions(brief_data: dict, associations: list[dict] | None = None) -> list[dict]:
        """Generate recommended next actions based on current state and associations.

        Rules (no LLM needed for PoC):
        1. If has open my_promise overdue → "兑现承诺: {promise_title}"
        2. If last_interaction > 7 days ago → "主动联系{person_name}"
        3. If stage=understanding_needs → "深入了解{person_name}当前需求"
        4. If has their_concerns → "关注对方关心的话题: {concern}"
        5. Association-based actions (the soul of PromiseLink):
           - industry_chain: "引荐{A}和{B}（投资-创业链）"
           - supply_demand: "{A}可以帮助{B}"
           - topic_overlap: "安排{A}和{B}交流（同领域）"
        6. Default → "保持定期联系"
        Max 5 actions.
        """
        actions: list[dict] = []
        now = datetime.now(timezone.utc)

        # Rule 1: Overdue my promises
        promises = brief_data.get("open_promises", {})
        for p in promises.get("my_promises", []):
            due_str = p.get("due_date")
            if due_str:
                try:
                    due_date = datetime.fromisoformat(due_str)
                    if due_date < now:
                        actions.append({
                            "action": f"兑现承诺: {p['title']}",
                            "priority": "high",
                            "suggested_date": now.strftime("%Y-%m-%d"),
                        })
                except (ValueError, TypeError):
                    pass

        # Rule 2: Last interaction too long ago
        last_int = brief_data.get("last_interaction", {})
        date_str = last_int.get("date")
        if date_str:
            try:
                last_date = datetime.fromisoformat(date_str)
                days_since = (now - last_date).days
                if days_since > 7:
                    basic = brief_data.get("basic_info", {})
                    name = basic.get("name", "对方")
                    actions.append({
                        "action": f"主动联系{name}",
                        "priority": "medium",
                        "suggested_date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                    })
            except (ValueError, TypeError):
                pass

        # Rule 3: Stage-specific action
        stage = brief_data.get("relationship_stage", "")
        if stage == "understanding_needs":
            basic = brief_data.get("basic_info", {})
            name = basic.get("name", "对方")
            actions.append({
                "action": f"深入了解{name}当前需求",
                "priority": "medium",
                "suggested_date": (now + timedelta(days=3)).strftime("%Y-%m-%d"),
            })

        # Rule 4: Their concerns follow-up
        concerns = brief_data.get("their_concerns", [])
        if concerns and len(actions) < 5:
            actions.append({
                "action": f"关注对方关心的话题: {concerns[0]}",
                "priority": "low",
                "suggested_date": (now + timedelta(days=5)).strftime("%Y-%m-%d"),
            })

        # Rule 5: Association-based actions (the soul of PromiseLink)
        # These are the actions that emerge from discovering hidden links
        if associations and len(actions) < 5:
            basic = brief_data.get("basic_info", {})
            person_name = basic.get("name", "对方")
            for assoc in associations:
                atype = assoc.get("association_type", "")
                other_name = assoc.get("other_entity_name", "")
                evidence = assoc.get("evidence", {})
                if not other_name:
                    continue

                if atype == "industry_chain":
                    rel = evidence.get("relation", "")
                    if rel == "potential_investor_startup":
                        actions.append({
                            "action": f"引荐{person_name}和{other_name}（投资-创业链）",
                            "priority": "high",
                            "source": "association:industry_chain",
                        })
                    else:
                        actions.append({
                            "action": f"对接{person_name}和{other_name}（产业链上下游）",
                            "priority": "medium",
                            "source": "association:industry_chain",
                        })
                elif atype == "supply_demand":
                    matches = evidence.get("matches", [])
                    if matches:
                        m = matches[0]
                        items = ", ".join(m.get("matched_items", [])[:2])
                        actions.append({
                            "action": f"{m.get('supplier', person_name)} 可帮助 {m.get('requester', other_name)} ({items})",
                            "priority": "high",
                            "source": "association:supply_demand",
                        })
                elif atype == "topic_overlap":
                    actions.append({
                        "action": f"安排{person_name}和{other_name}交流（同领域）",
                        "priority": "medium",
                        "source": "association:topic_overlap",
                    })
                elif atype == "same_city":
                    actions.append({
                        "action": f"约{person_name}和{other_name}同城见面",
                        "priority": "low",
                        "source": "association:same_city",
                    })

        # Rule 6: Default fallback
        if not actions:
            actions.append({
                "action": "保持定期联系",
                "priority": "low",
                "suggested_date": (now + timedelta(days=7)).strftime("%Y-%m-%d"),
            })

        return actions[:5]

"""Todo Generator Service — LLM-based todo generation from events.

Generates 6 types of todos (v4.0):
- promise (雾绿#A0C4A8): 提取"我答应过什么"
- help (雾紫#B0A0C4): 建议"我能为他做什么"
- care (雾蓝#A0B0C4): 提取"对方正在关心什么"
- followup (雾金#C4C0A0): 标记需跟进的事项
- cooperation_signal (雾白#B8C4C0): 识别合作信号
- risk (烟粉#C4A7A0): 识别潜在风险

Uses 3 LLM prompts:
- Template 3: Generic todo generation by type
- Template 11: Promise extraction (first-person commitments)
- Template 12: Care extraction (other party's concerns)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from promiselink.services.llm_client import LLMClient
    from promiselink.services.llm_provider import LLMProvider

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from promiselink.core.exceptions import InvalidTodoTypeError
from promiselink.core.logging import get_logger
from promiselink.core.text_utils import extract_json_from_text, sanitize_llm_input
from promiselink.models.entity import Entity
from promiselink.models.event import Event
from promiselink.models.todo import Todo
from promiselink.prompts.todo_generation import (
    TEMPLATE_3_TODO_GENERATION,
    TEMPLATE_11_PROMISE_EXTRACTION,
    TEMPLATE_12_CARE_EXTRACTION,
)

logger = get_logger("promiselink.todo_generator")

# Priority mapping: string → int (1=highest, 5=lowest)
PRIORITY_MAP = {"high": 1, "medium": 3, "low": 5}

# Default due_date offsets by todo_type (in days)
DUE_DATE_OFFSETS = {
    "promise": 3,
    "help": 5,
    "care": 7,
    "followup": 7,
    "cooperation_signal": 3,
    "risk": 1,
}

# All valid todo types
VALID_TODO_TYPES = [
    "promise",
    "help",
    "care",
    "followup",
    "cooperation_signal",
    "risk",
]

# Rule-based fallback: promise keywords that indicate a commitment
_PROMISE_KEYWORDS = re.compile(
    r"承诺|答应|保证|一定|包在我身上|放心吧|没问题|交给我|我会|我将|我一定|尽快|马上给|回头我|之后我|下周我|明天我"
)

# Rule-based fallback: care/followup keywords that indicate something to track
_CARE_KEYWORDS = re.compile(
    r"担心|焦虑|急需|正在找|希望|考虑|纠结|犹豫|头疼|困扰|着急|迫切|关注|在意"
)

# Rule-based fallback: followup keywords
_FOLLOWUP_KEYWORDS = re.compile(
    r"待确认|待定|再说|后续|跟进|回头|之后联系|到时候|看情况"
)


@dataclass
class GeneratedTodo:
    """A generated todo before persistence.

    Represents an AI-generated todo that has not yet been written to the database.
    """

    todo_type: str
    title: str
    description: str | None = None
    priority: int = 3
    due_date: datetime | None = None
    related_entity_id: str | None = None
    properties: dict | None = None
    is_ai_inference: bool = False
    confidence_level: str = "confirmed"
    requires_confirmation: bool = False


class TodoGenerator:
    """Todo generation service using LLM prompts.

    Generates 6 types of todos from event content:
    - promise: Extract "what I promised"
    - help: Suggest "what I can do for them"
    - care: Extract "what they care about"
    - followup: Mark items needing follow-up
    - cooperation_signal: Identify cooperation signals
    - risk: Identify potential risks

    Strategy per event type:
    - meeting/call: promise + care + cooperation_signal + risk
    - card_save (with conversation text): promise + care only
    - card_save (no conversation text): skip
    - manual: promise + care + followup
    """

    def __init__(self, llm_client: LLMProvider | LLMClient, session: AsyncSession):
        self.llm = llm_client
        self.session = session

    async def generate_todos(
        self,
        event: Event,
        entities: list[Entity],
        user_context: str = "",
    ) -> list[Todo]:
        """Generate todos from an event and its extracted entities.

        Strategy:
        1. Always run promise extraction (Template 11) — high priority
        2. Always run care extraction (Template 12) — high priority
        3. For meeting/call events, also run cooperation_signal and risk
        4. For card_save, only run promise and care if raw_text has conversation

        Args:
            event: The source event containing raw_text.
            entities: List of extracted Entity objects from this event.
            user_context: Optional user background context for LLM.

        Returns:
            List of persisted Todo objects.
        """
        logger.info(
            "todo_generation_started",
            event_id=str(event.id),
            event_type=event.event_type,
            entity_count=len(entities),
        )

        # Truncate overly long conversation text
        conversation = event.raw_text or ""
        if len(conversation) > 8000:
            logger.warning(
                "conversation_truncated",
                event_id=str(event.id),
                original_len=len(conversation),
            )
            conversation = conversation[:8000]

        if not conversation.strip():
            logger.info("no_conversation_text", event_id=str(event.id))
            return []

        conversation = sanitize_llm_input(conversation)
        persons = self._format_persons(entities)

        # Event date for LLM deadline inference
        event_date = event.timestamp.isoformat() if event.timestamp else datetime.now(UTC).isoformat()

        all_generated: list[GeneratedTodo] = []

        # Step 1 & 2: Parallel extract promises and cares (Templates 11 & 12)
        promise_care_results = await asyncio.gather(
            self._extract_promises(conversation, persons, event_date),
            self._extract_cares(conversation, persons, event_date),
            return_exceptions=True,
        )

        promises = promise_care_results[0] if not isinstance(promise_care_results[0], BaseException) else []
        cares = promise_care_results[1] if not isinstance(promise_care_results[1], BaseException) else []
        all_generated.extend(promises)
        all_generated.extend(cares)

        for i, r in enumerate(promise_care_results):
            if isinstance(r, BaseException):
                logger.warning("parallel_todo_extraction_failed",
                    type=["promises", "cares"][i], error=str(r))

        # Step 3: Event-type-specific generation (parallel where possible)
        if event.event_type in ("meeting", "call"):
            extra_results = await asyncio.gather(
                *[
                    self._generate_typed_todo(
                        todo_type=extra_type,
                        conversation=conversation,
                        persons=persons,
                        user_context=user_context,
                        event_date=event_date,
                    )
                    for extra_type in ("cooperation_signal", "risk")
                ],
                return_exceptions=True,
            )
            for gen_todo in extra_results:
                if isinstance(gen_todo, BaseException):
                    logger.warning("parallel_typed_todo_failed",
                        todo_type="unknown", error=str(gen_todo))
                elif gen_todo is not None:
                    all_generated.append(gen_todo)

        elif event.event_type == "manual":
            gen_followup = await self._generate_typed_todo(
                todo_type="followup",
                conversation=conversation,
                persons=persons,
                user_context=user_context,
                event_date=event_date,
            )
            if gen_followup:
                all_generated.append(gen_followup)

        # Deduplicate: skip todos similar to existing ones
        unique_generated: list[GeneratedTodo] = []
        for gen in all_generated:
            is_dup = await self._is_duplicate_todo(
                gen=gen,
                user_id=str(event.user_id),
            )
            if not is_dup:
                unique_generated.append(gen)
            else:
                logger.debug(
                    "todo_deduplicated",
                    todo_type=gen.todo_type,
                    title=gen.title[:50],
                )

        # Rule-based fallback: if LLM generated nothing but text contains
        # promise/care/followup keywords, create basic todos
        if not all_generated:
            fallback_todos = self._rule_based_fallback(
                conversation=conversation,
                persons=persons,
            )
            if fallback_todos:
                logger.info(
                    "todo_rule_based_fallback",
                    event_id=str(event.id),
                    fallback_count=len(fallback_todos),
                )
                unique_generated.extend(fallback_todos)

        # Persist all unique generated todos
        # F-50: Associate todos with extracted entities by matching person names
        entity_name_map: dict[str, str] = {}
        for ent in entities:
            if ent.id and ent.name:
                entity_name_map[ent.name] = str(ent.id)

        persisted_todos: list[Todo] = []
        for gen in unique_generated:
            try:
                # Match todo to entity by person name in title/description
                if not gen.related_entity_id and entity_name_map:
                    todo_text = f"{gen.title} {gen.description}"
                    for name, eid in entity_name_map.items():
                        if name and name in todo_text:
                            gen.related_entity_id = eid
                            break
                todo = await self._persist_todo(
                    gen=gen,
                    user_id=str(event.user_id),
                    event_id=str(event.id),
                )
                persisted_todos.append(todo)
            except SQLAlchemyError as e:
                logger.error(
                    "todo_persist_failed",
                    error=str(e),
                    todo_type=gen.todo_type,
                    title=gen.title,
                )

        logger.info(
            "todo_generation_completed",
            event_id=str(event.id),
            total_generated=len(all_generated),
            persisted=len(persisted_todos),
        )

        # F-46: Apply deduplication (v4.4)
        from promiselink.services.todo_deduplicator import TodoDeduplicator

        deduplicator = TodoDeduplicator()
        dedup_result = deduplicator.deduplicate(persisted_todos, user_id=str(event.user_id))
        persisted_todos = dedup_result.todos

        # F-46b: DB-level deletion of duplicates
        if hasattr(dedup_result, 'pending_deletions') and dedup_result.pending_deletions:
            from sqlalchemy import delete as sql_delete
            await self.session.execute(
                sql_delete(Todo).where(Todo.id.in_(dedup_result.pending_deletions))
            )
            logger.info("todo_dedup_db_deletion", deleted_ids=len(dedup_result.pending_deletions))

        if dedup_result.removed_count > 0:
            logger.info(
                "todo_deduplication_applied",
                original=dedup_result.original_count,
                final=len(persisted_todos),
                removed=dedup_result.removed_count,
            )

        return persisted_todos

    async def _extract_promises(
        self, conversation: str, persons: str, event_date: str
    ) -> list[GeneratedTodo]:
        """Extract promises using Template 11.

        Parses LLM response for promise array and converts to GeneratedTodo list.

        Args:
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.
            event_date: Event occurrence date for deadline inference.

        Returns:
            List of GeneratedTodo objects for each extracted promise.
        """
        try:
            prompt = TEMPLATE_11_PROMISE_EXTRACTION.format(
                conversation=conversation,
                persons=persons,
                event_date=event_date,
            )
            response = await self.llm.call(prompt, max_tokens=2000, temperature=0.2)
            data = extract_json_from_text(response)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("promise_extraction_failed", error=str(e))
            return []

        promises = data.get("promises", [])
        if not promises:
            return []

        generated: list[GeneratedTodo] = []
        for p in promises:
            content = p.get("content", "")
            if not content:
                continue

            # Parse suggested deadline
            due_date = self._parse_due_date(p.get("suggested_deadline"))
            if not due_date:
                offset_days = DUE_DATE_OFFSETS.get("promise", 3)
                due_date = datetime.now(UTC) + timedelta(days=offset_days)

            priority_str = p.get("priority", "high")
            generated.append(GeneratedTodo(
                todo_type="promise",
                title=f"[承诺] {p.get('to_person', '')} — {content[:20]}",
                description=content,
                priority=PRIORITY_MAP.get(priority_str, 1),
                due_date=due_date,
                properties={
                    "to_person": p.get("to_person"),
                    "source_text": p.get("source_text"),
                    "mentioned_deadline": p.get("mentioned_deadline"),
                },
                is_ai_inference=data.get("is_ai_inference", False),
                confidence_level=data.get("confidence_level", "confirmed"),
                requires_confirmation=data.get("requires_confirmation", False),
            ))

        logger.info("promises_extracted", count=len(generated))
        return generated

    async def _extract_cares(
        self, conversation: str, persons: str, event_date: str
    ) -> list[GeneratedTodo]:
        """Extract care items using Template 12.

        Parses LLM response for care array and converts to GeneratedTodo list.

        Args:
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.
            event_date: Event occurrence date for deadline inference.

        Returns:
            List of GeneratedTodo objects for each extracted care item.
        """
        try:
            prompt = TEMPLATE_12_CARE_EXTRACTION.format(
                conversation=conversation,
                persons=persons,
                event_date=event_date,
            )
            response = await self.llm.call(prompt, max_tokens=2000, temperature=0.2)
            data = extract_json_from_text(response)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("care_extraction_failed", error=str(e))
            return []

        cares = data.get("cares", [])
        if not cares:
            return []

        generated: list[GeneratedTodo] = []
        for c in cares:
            topic = c.get("topic", "")
            detail = c.get("detail", "")
            if not topic and not detail:
                continue

            urgency_str = c.get("urgency", "medium")
            priority_map = {"high": 1, "medium": 3, "low": 5}
            priority = priority_map.get(urgency_str, 3)

            offset_days = DUE_DATE_OFFSETS.get("care", 7)
            due_date = datetime.now(UTC) + timedelta(days=offset_days)

            title = f"[关注] {c.get('person', '')} — {topic[:20]}" if topic else f"[关注] {detail[:25]}"
            generated.append(GeneratedTodo(
                todo_type="care",
                title=title[:60],
                description=detail or topic,
                priority=priority,
                due_date=due_date,
                properties={
                    "person": c.get("person"),
                    "topic": topic,
                    "detail": detail,
                    "urgency": urgency_str,
                    "source_text": c.get("source_text"),
                },
                is_ai_inference=data.get("is_ai_inference", False),
                confidence_level=data.get("confidence_level", "confirmed"),
                requires_confirmation=data.get("requires_confirmation", False),
            ))

        logger.info("cares_extracted", count=len(generated))
        return generated

    async def _generate_typed_todo(
        self,
        todo_type: str,
        conversation: str,
        persons: str,
        user_context: str = "",
        event_date: str = "",
    ) -> GeneratedTodo | None:
        """Generate a single typed todo using Template 3.

        Args:
            todo_type: One of the 6 valid todo types.
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.
            user_context: Optional user background context.
            event_date: Event occurrence date for deadline inference.

        Returns:
            A GeneratedTodo object, or None if generation fails.
        """
        if todo_type not in VALID_TODO_TYPES:
            raise InvalidTodoTypeError(todo_type)

        try:
            prompt = TEMPLATE_3_TODO_GENERATION.format(
                todo_type=todo_type,
                conversation=conversation,
                persons=persons,
                user_context=user_context or "(无)",
                event_date=event_date or datetime.now(UTC).isoformat(),
            )
            response = await self.llm.call(prompt, max_tokens=1500, temperature=0.3)
            data = extract_json_from_text(response)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(
                "typed_todo_generation_failed",
                todo_type=todo_type,
                error=str(e),
            )
            return None

        description = data.get("description", "")
        if not description:
            return None

        priority_str = data.get("priority", "medium")
        due_date = self._parse_due_date(data.get("due_date_suggestion"))
        if not due_date:
            offset_days = DUE_DATE_OFFSETS.get(todo_type, 7)
            due_date = datetime.now(UTC) + timedelta(days=offset_days)

        context_data = data.get("context", {})

        # Build title based on type — keep title SHORT, put detail in description
        type_labels = {
            "promise": "承诺",
            "help": "帮助建议",
            "care": "关注点",
            "followup": "跟进事项",
            "cooperation_signal": "合作信号",
            "risk": "风险预警",
        }
        label = type_labels.get(todo_type, todo_type)
        # Extract related persons from context
        related = context_data.get("related_entities", []) if context_data else []
        person_str = related[0] if related else ""
        # Title: [标签] 人物 + 核心关键词（≤30字）
        short_desc = description[:25] if len(description) > 25 else description
        if person_str:
            title = f"{person_str} — {short_desc}"
        else:
            title = short_desc
        title = f"[{label}] {title}"[:60]

        return GeneratedTodo(
            todo_type=todo_type,
            title=title,
            description=description,
            priority=PRIORITY_MAP.get(priority_str, 3),
            due_date=due_date,
            properties=context_data,
            is_ai_inference=data.get("is_ai_inference", True),
            confidence_level=data.get("confidence_level", "inferred"),
            requires_confirmation=data.get("requires_confirmation", False),
        )

    async def _persist_todo(
        self,
        gen: GeneratedTodo,
        user_id: str,
        event_id: str,
    ) -> Todo:
        """Persist a GeneratedTodo to database.

        Creates a Todo ORM object, adds it to the session, and flushes.

        Args:
            gen: The GeneratedTodo to persist.
            user_id: Owner user ID.
            event_id: Source event ID.

        Returns:
            The persisted Todo object (with DB-assigned ID after flush).
        """
        todo = Todo(
            user_id=user_id,
            todo_type=gen.todo_type,
            title=gen.title,
            description=gen.description,
            related_entity_id=gen.related_entity_id,
            priority=gen.priority,
            status="pending",
            due_date=gen.due_date,
            source_event_id=event_id,
            properties={
                **(gen.properties or {}),
                "is_ai_inference": gen.is_ai_inference,
                "confidence_level": gen.confidence_level,
                "requires_confirmation": gen.requires_confirmation,
            },
        )
        self.session.add(todo)
        await self.session.flush()

        logger.debug(
            "todo_persisted",
            todo_id=str(todo.id),
            todo_type=gen.todo_type,
            title=gen.title,
        )
        return todo

    def _format_persons(self, entities: list[Entity]) -> str:
        """Format entity list for LLM prompt.

        Extracts basic info (name, title, company) from each entity's properties.

        Args:
            entities: List of Entity objects.

        Returns:
            Formatted string suitable for LLM prompt insertion.
        """
        parts = []
        for e in entities:
            basic = (e.properties or {}).get("basic", {})
            parts.append(
                f"- {e.name}: {basic.get('title', '')} @ {basic.get('company', '')}"
            )
        return "\n".join(parts) if parts else "无"

    def _rule_based_fallback(
        self, conversation: str, persons: str
    ) -> list[GeneratedTodo]:
        """Generate basic todos using keyword matching when LLM produces nothing.

        This is a safety net: if the LLM fails to extract any promise/care/followup
        todos but the text clearly contains commitment or concern keywords, we
        generate basic placeholder todos so the user doesn't miss important items.

        Args:
            conversation: Sanitized conversation text.
            persons: Formatted person list for context.

        Returns:
            List of GeneratedTodo objects from rule-based extraction.
        """
        fallback: list[GeneratedTodo] = []

        # Extract first person name from persons string for context
        person_name = ""
        if persons and persons != "无":
            for line in persons.strip().split("\n"):
                if line.startswith("- "):
                    person_name = line[2:].split(":")[0].strip()
                    break

        # Check for promise keywords
        promise_matches = _PROMISE_KEYWORDS.findall(conversation)
        if promise_matches:
            # Find the sentence containing the keyword
            keyword = promise_matches[0]
            sentences = re.split(r"[。！？；\n]", conversation)
            relevant_sentence = ""
            for s in sentences:
                if keyword in s:
                    relevant_sentence = s.strip()[:80]
                    break

            title = f"[承诺] {person_name} — 待确认承诺事项" if person_name else "[承诺] 待确认承诺事项"
            fallback.append(GeneratedTodo(
                todo_type="promise",
                title=title[:60],
                description=relevant_sentence or f"文本中包含承诺关键词「{keyword}」，请确认具体承诺内容",
                priority=1,
                due_date=datetime.now(UTC) + timedelta(days=3),
                properties={
                    "source_text": relevant_sentence[:200] if relevant_sentence else None,
                    "rule_based_fallback": True,
                    "matched_keyword": keyword,
                },
                is_ai_inference=False,
                confidence_level="inferred",
                requires_confirmation=True,
            ))

        # Check for care keywords
        care_matches = _CARE_KEYWORDS.findall(conversation)
        if care_matches:
            keyword = care_matches[0]
            sentences = re.split(r"[。！？；\n]", conversation)
            relevant_sentence = ""
            for s in sentences:
                if keyword in s:
                    relevant_sentence = s.strip()[:80]
                    break

            title = f"[关注] {person_name} — 待确认关注点" if person_name else "[关注] 待确认关注点"
            fallback.append(GeneratedTodo(
                todo_type="care",
                title=title[:60],
                description=relevant_sentence or f"文本中包含关注关键词「{keyword}」，请确认对方关注点",
                priority=3,
                due_date=datetime.now(UTC) + timedelta(days=7),
                properties={
                    "source_text": relevant_sentence[:200] if relevant_sentence else None,
                    "rule_based_fallback": True,
                    "matched_keyword": keyword,
                },
                is_ai_inference=False,
                confidence_level="inferred",
                requires_confirmation=True,
            ))

        # Check for followup keywords
        followup_matches = _FOLLOWUP_KEYWORDS.findall(conversation)
        if followup_matches:
            keyword = followup_matches[0]
            sentences = re.split(r"[。！？；\n]", conversation)
            relevant_sentence = ""
            for s in sentences:
                if keyword in s:
                    relevant_sentence = s.strip()[:80]
                    break

            title = f"[跟进] {person_name} — 待跟进事项" if person_name else "[跟进] 待跟进事项"
            fallback.append(GeneratedTodo(
                todo_type="followup",
                title=title[:60],
                description=relevant_sentence or f"文本中包含跟进关键词「{keyword}」，请确认跟进事项",
                priority=3,
                due_date=datetime.now(UTC) + timedelta(days=7),
                properties={
                    "source_text": relevant_sentence[:200] if relevant_sentence else None,
                    "rule_based_fallback": True,
                    "matched_keyword": keyword,
                },
                is_ai_inference=False,
                confidence_level="inferred",
                requires_confirmation=True,
            ))

        return fallback

    async def _is_duplicate_todo(
        self,
        gen: GeneratedTodo,
        user_id: str,
    ) -> bool:
        """Check if a similar todo already exists in the database.

        Deduplication criteria:
        1. Same user_id
        2. Same todo_type
        3. Same target person (from properties.to_person or properties.person)
        4. Title similarity > 0.6 (simple word overlap ratio)

        Args:
            gen: The GeneratedTodo to check.
            user_id: Owner user ID.

        Returns:
            True if a similar todo exists, False otherwise.
        """

        # Extract target person from generated todo properties
        props = gen.properties or {}
        target_person = props.get("to_person") or props.get("person") or ""

        # Query existing pending/in_progress todos of same type for this user
        stmt = (
            select(Todo)
            .where(
                Todo.user_id == user_id,
                Todo.todo_type == gen.todo_type,
                Todo.status.in_(["pending", "in_progress"]),
            )
        )
        result = await self.session.execute(stmt)
        existing_todos = result.scalars().all()

        if not existing_todos:
            return False

        gen_title_words = set(gen.title.replace("—", " ").split())

        for existing in existing_todos:
            # Check target person match
            if target_person:
                ex_props = existing.properties or {}
                ex_person = ex_props.get("to_person") or ex_props.get("person") or ""
                if ex_person and target_person != ex_person:
                    continue  # Different person, not a duplicate

            # Check title similarity
            ex_title_words = set(existing.title.replace("—", " ").split())
            if not gen_title_words or not ex_title_words:
                continue

            # Word overlap ratio
            overlap = len(gen_title_words & ex_title_words)
            union = len(gen_title_words | ex_title_words)
            similarity = overlap / union if union > 0 else 0

            if similarity > 0.6:
                logger.debug(
                    "duplicate_todo_found",
                    existing_title=existing.title[:50],
                    new_title=gen.title[:50],
                    similarity=round(similarity, 2),
                )
                return True

        return False

    @staticmethod
    def _parse_due_date(date_str: str | None) -> datetime | None:
        """Parse ISO 8601 date string to datetime with UTC timezone.

        Args:
            date_str: ISO 8601 formatted date string from LLM response.

        Returns:
            Parsed datetime object, or None if parsing fails.
        """
        if not date_str:
            return None
        try:
            # Handle various ISO 8601 formats
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except (ValueError, TypeError):
            return None

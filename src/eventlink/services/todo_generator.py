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

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.exceptions import InvalidTodoTypeError
from eventlink.core.logging import get_logger
from eventlink.core.text_utils import extract_json_from_text, sanitize_llm_input
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.models.todo import Todo
from eventlink.prompts.todo_generation import (
    TEMPLATE_11_PROMISE_EXTRACTION,
    TEMPLATE_12_CARE_EXTRACTION,
    TEMPLATE_3_TODO_GENERATION,
)

logger = get_logger("eventlink.todo_generator")

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

    def __init__(self, llm_client, session: AsyncSession):
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

        all_generated: list[GeneratedTodo] = []

        # Step 1 & 2: Always extract promises and cares (Templates 11 & 12)
        promises = await self._extract_promises(conversation, persons)
        all_generated.extend(promises)

        cares = await self._extract_cares(conversation, persons)
        all_generated.extend(cares)

        # Step 3: Event-type-specific generation
        if event.event_type in ("meeting", "call"):
            for extra_type in ("cooperation_signal", "risk"):
                gen_todo = await self._generate_typed_todo(
                    todo_type=extra_type,
                    conversation=conversation,
                    persons=persons,
                    user_context=user_context,
                )
                if gen_todo:
                    all_generated.append(gen_todo)

        elif event.event_type == "card_save":
            # card_save already handled by promise/care above; skip extras
            pass

        elif event.event_type == "manual":
            gen_followup = await self._generate_typed_todo(
                todo_type="followup",
                conversation=conversation,
                persons=persons,
                user_context=user_context,
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

        # Persist all unique generated todos
        persisted_todos: list[Todo] = []
        for gen in unique_generated:
            try:
                todo = await self._persist_todo(
                    gen=gen,
                    user_id=str(event.user_id),
                    event_id=str(event.id),
                )
                persisted_todos.append(todo)
            except Exception as e:
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

        return persisted_todos

    async def _extract_promises(
        self, conversation: str, persons: str
    ) -> list[GeneratedTodo]:
        """Extract promises using Template 11.

        Parses LLM response for promise array and converts to GeneratedTodo list.

        Args:
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.

        Returns:
            List of GeneratedTodo objects for each extracted promise.
        """
        try:
            prompt = TEMPLATE_11_PROMISE_EXTRACTION.format(
                conversation=conversation,
                persons=persons,
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
                due_date = datetime.now(timezone.utc) + timedelta(days=offset_days)

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
        self, conversation: str, persons: str
    ) -> list[GeneratedTodo]:
        """Extract care items using Template 12.

        Parses LLM response for care array and converts to GeneratedTodo list.

        Args:
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.

        Returns:
            List of GeneratedTodo objects for each extracted care item.
        """
        try:
            prompt = TEMPLATE_12_CARE_EXTRACTION.format(
                conversation=conversation,
                persons=persons,
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
            due_date = datetime.now(timezone.utc) + timedelta(days=offset_days)

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
    ) -> GeneratedTodo | None:
        """Generate a single typed todo using Template 3.

        Args:
            todo_type: One of the 6 valid todo types.
            conversation: Sanitized conversation text.
            persons: Formatted person list for LLM context.
            user_context: Optional user background context.

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
            due_date = datetime.now(timezone.utc) + timedelta(days=offset_days)

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
        from difflib import SequenceMatcher

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
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None

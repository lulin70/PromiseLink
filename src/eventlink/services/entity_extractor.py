"""Entity Extractor — LLM-based entity extraction from event raw text.

Selects prompt template based on event_type, calls LLM, parses response,
runs entity resolution, and persists entities to database.

Template mapping:
  - card_save → Template 1 (business card OCR extraction)
  - meeting / call / manual → Template 2 (conversation entity extraction)
"""

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from eventlink.core.logging import get_logger
from eventlink.core.text_utils import sanitize_llm_input
from eventlink.models.entity import Entity
from eventlink.models.event import Event
from eventlink.prompts.entity_extraction import (
    TEMPLATE_1_CARD_EXTRACTION,
    TEMPLATE_2_CONVERSATION_EXTRACTION,
)
from eventlink.services.entity_resolution import (
    EntityResolutionEngine,
    ResolutionAction,
)
from eventlink.services.llm_client import LLMClient

logger = get_logger("eventlink.entity_extractor")

# ── Data Classes ──


@dataclass
class ExtractedPerson:
    """Extracted person entity from event."""

    name: str
    company: str | None = None
    title: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    resource: list[str] = field(default_factory=list)
    demand: list[str] = field(default_factory=list)
    industry: str | None = None
    confidence: float = 1.0
    is_ai_inference: bool = False
    confidence_level: str = "confirmed"
    requires_confirmation: bool = False


@dataclass
class ExtractionResult:
    """Result of entity extraction from an event."""

    persons: list[ExtractedPerson]
    keywords: list[str] = field(default_factory=list)
    summary: str = ""
    events: list[dict] = field(default_factory=list)
    is_ai_inference: bool = False
    confidence_level: str = "confirmed"
    requires_confirmation: bool = False
    persisted_entities: list[Entity] = field(default_factory=list)


# ── Entity Extractor ──


class EntityExtractor:
    """Entity extraction service using LLM prompts.

    Selects prompt template based on event_type, calls LLM, parses
    structured JSON response, runs entity resolution for each person,
    and persists entities to database.
    """

    # event_type → prompt template mapping
    CARD_TYPES = {"card_save"}
    CONVERSATION_TYPES = {"meeting", "call", "manual"}

    def __init__(
        self,
        llm_client: LLMClient,
        session: AsyncSession,
        resolution_engine: EntityResolutionEngine | None = None,
    ):
        self.llm = llm_client
        self.session = session
        self.resolution_engine = resolution_engine

    async def extract_from_event(self, event: Event) -> ExtractionResult:
        """Extract entities from an event based on its type.

        Steps:
        1. Select prompt template based on event_type
        2. Call LLM
        3. Parse response
        4. Run entity resolution for each person
        5. Persist entities to database
        6. Return extraction result
        """
        # Truncate overly long raw_text to avoid LLM timeout
        if event.raw_text and len(event.raw_text) > 8000:
            logger.warning(
                "raw_text_truncated",
                event_id=str(event.id),
                original_len=len(event.raw_text),
                truncated_len=8000,
            )
            event.raw_text = event.raw_text[:8000]

        raw_text = event.raw_text or ""
        if not raw_text.strip():
            logger.warning(
                "extract_empty_text",
                event_id=str(event.id),
                event_type=event.event_type,
            )
            return ExtractionResult(persons=[])

        logger.info(
            "extract_started",
            event_id=str(event.id),
            event_type=event.event_type,
            text_length=len(raw_text),
        )

        # Step 1-3: Select template and call LLM
        if event.event_type in self.CARD_TYPES:
            # card_save: try direct JSON parse first (raw_text is already structured)
            result = self._extract_card_direct(raw_text)
            if not result or not result.persons:
                # Fallback to LLM extraction
                result = await self._extract_card(raw_text)
        elif event.event_type in self.CONVERSATION_TYPES:
            language = self._detect_language(raw_text)
            result = await self._extract_conversation(raw_text, language=language)
        else:
            logger.warning(
                "extract_unknown_event_type",
                event_id=str(event.id),
                event_type=event.event_type,
            )
            return ExtractionResult(persons=[])

        # Step 4-5: Resolve and persist each person
        persisted_entities: list[Entity] = []
        for person in result.persons:
            try:
                # Use savepoint to isolate each person's persistence
                # so a failure doesn't roll back already-successful entities
                async with self.session.begin_nested():
                    entity = await self._resolve_and_persist(
                        person=person,
                        user_id=str(event.user_id),
                        event_id=str(event.id),
                    )
                    persisted_entities.append(entity)
            except Exception:
                logger.exception(
                    "resolve_persist_failed",
                    person_name=person.name,
                    event_id=str(event.id),
                )

        logger.info(
            "extract_completed",
            event_id=str(event.id),
            persons_extracted=len(result.persons),
            entities_persisted=len(persisted_entities),
        )

        result.persisted_entities = persisted_entities
        return result

    def _extract_card_direct(self, raw_text: str) -> ExtractionResult | None:
        """Extract from card_save JSON directly without LLM.

        For card_save events, raw_text is already structured JSON.
        Parse it directly to preserve all fields (city, phone, email, etc.)
        which LLM might lose or alter.

        Args:
            raw_text: JSON string from card_save event.

        Returns:
            ExtractionResult, or None if parsing fails.
        """
        import json as _json

        try:
            data = _json.loads(raw_text)
        except (_json.JSONDecodeError, ValueError):
            return None

        person_data = data.get("person") or data
        if not person_data.get("name"):
            return None

        person = ExtractedPerson(
            name=person_data.get("name", ""),
            company=person_data.get("company"),
            title=person_data.get("title"),
            phone=person_data.get("phone"),
            email=person_data.get("email"),
            city=person_data.get("city"),
            resource=person_data.get("resource", []),
            demand=person_data.get("demand", []),
            industry=person_data.get("industry"),
            confidence=1.0,
            is_ai_inference=False,
            confidence_level="confirmed",
            requires_confirmation=False,
        )

        logger.info(
            "card_direct_extracted",
            person_name=person.name,
            city=person.city,
            company=person.company,
        )

        return ExtractionResult(
            persons=[person],
            is_ai_inference=False,
            confidence_level="confirmed",
            requires_confirmation=False,
        )

    async def _extract_card(self, raw_text: str) -> ExtractionResult:
        """Extract from card scan OCR text using Template 1.

        Args:
            raw_text: OCR-recognized text from a business card.

        Returns:
            ExtractionResult with a single ExtractedPerson.
        """
        sanitized = sanitize_llm_input(raw_text)
        prompt = TEMPLATE_1_CARD_EXTRACTION.format(ocr_text=sanitized)

        try:
            response = await self.llm.call_json(
                prompt=prompt,
                temperature=0.3,
            )
        except Exception as e:
            logger.warning("card_extraction_failed", error=str(e)[:200])
            return ExtractionResult(persons=[])

        data = response

        person = ExtractedPerson(
            name=data.get("name", ""),
            company=data.get("company"),
            title=data.get("title"),
            phone=data.get("phone"),
            email=data.get("email"),
            city=data.get("city"),
            resource=data.get("resource", []),
            demand=data.get("demand", []),
            industry=data.get("industry"),
            confidence=float(data.get("confidence", 1.0)),
            is_ai_inference=bool(data.get("is_ai_inference", False)),
            confidence_level=data.get("confidence_level", "confirmed"),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
        )

        return ExtractionResult(
            persons=[person],
            is_ai_inference=person.is_ai_inference,
            confidence_level=person.confidence_level,
            requires_confirmation=person.requires_confirmation,
        )

    async def _extract_conversation(
        self, raw_text: str, language: str = "zh-CN"
    ) -> ExtractionResult:
        """Extract from meeting/call transcript using Template 2.

        Args:
            raw_text: Transcript text from a meeting, call, or manual input.
            language: Language code for the transcript (default: zh-CN).

        Returns:
            ExtractionResult with potentially multiple ExtractedPerson instances.
        """
        sanitized = sanitize_llm_input(raw_text)
        prompt = TEMPLATE_2_CONVERSATION_EXTRACTION.format(
            language=language,
            transcript=sanitized,
        )

        try:
            response = await self.llm.call_json(
                prompt=prompt,
                temperature=0.3,
            )
        except Exception as e:
            logger.warning("conversation_extraction_failed", error=str(e)[:200])
            return ExtractionResult(persons=[])

        data = response

        persons: list[ExtractedPerson] = []
        for p in data.get("persons", []):
            person = ExtractedPerson(
                name=p.get("name", ""),
                company=p.get("company"),
                title=p.get("title"),
                resource=p.get("resource", []),
                demand=p.get("demand", []),
            )
            persons.append(person)

        return ExtractionResult(
            persons=persons,
            keywords=data.get("keywords", []),
            summary=data.get("summary", ""),
            events=data.get("events", []),
            is_ai_inference=bool(data.get("is_ai_inference", False)),
            confidence_level=data.get("confidence_level", "confirmed"),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
        )

    async def _resolve_and_persist(
        self, person: ExtractedPerson, user_id: str, event_id: str
    ) -> Entity:
        """Run entity resolution and persist to database.

        If resolution says CREATE: create new Entity.
        If resolution says MERGE: merge into existing Entity.
        If resolution says CONFIRM: create provisional Entity (needs user confirmation).

        Args:
            person: Extracted person data.
            user_id: Owner user ID for scoping.
            event_id: Source event ID.

        Returns:
            Created or updated Entity.
        """
        person_data = self._person_to_resolution_data(person, event_id=event_id)

        if self.resolution_engine:
            resolution = await self.resolution_engine.resolve(
                new_entity_data=person_data, user_id=user_id
            )

            if resolution.action == ResolutionAction.MERGE and resolution.target_entity:
                # Merge into existing entity
                merged = await self.resolution_engine.merge_entity(
                    new_entity_data=person_data,
                    target=resolution.target_entity,
                )
                logger.info(
                    "entity_merged",
                    person_name=person.name,
                    target_id=str(resolution.target_entity.id),
                    confidence=resolution.confidence,
                    matched_step=resolution.matched_step,
                )
                return merged

            if resolution.action == ResolutionAction.CONFIRM:
                # Create provisional entity that needs user confirmation
                entity = self._create_entity(
                    person=person,
                    user_id=user_id,
                    event_id=event_id,
                    status="provisional",
                )
                self.session.add(entity)
                await self.session.flush()

                logger.info(
                    "entity_provisional",
                    person_name=person.name,
                    entity_id=str(entity.id),
                    confidence=resolution.confidence,
                    matched_step=resolution.matched_step,
                )
                return entity

        # CREATE action or no resolution engine: create new entity
        status = "provisional" if person.requires_confirmation else "confirmed"
        entity = self._create_entity(
            person=person,
            user_id=user_id,
            event_id=event_id,
            status=status,
        )
        self.session.add(entity)
        await self.session.flush()

        logger.info(
            "entity_created",
            person_name=person.name,
            entity_id=str(entity.id),
            status=status,
        )
        return entity

    # ── Helper Methods ──

    @staticmethod
    def _person_to_resolution_data(
        person: ExtractedPerson, event_id: str | None = None
    ) -> dict[str, Any]:
        """Convert ExtractedPerson to a dict suitable for entity resolution.

        Args:
            person: Extracted person data.
            event_id: Optional event ID for tracking co-occurrence.

        Returns:
            Dictionary with entity resolution-compatible structure.
        """
        return {
            "name": person.name,
            "entity_type": "person",
            "company": person.company,
            "title": person.title,
            "city": person.city,
            "industry": person.industry,
            "confidence": person.confidence,
            "source_event_id": event_id,
            "properties": {
                "basic": {
                    "company": person.company,
                    "title": person.title,
                    "phone": person.phone,
                    "email": person.email,
                    "city": person.city,
                    "industry": person.industry,
                },
                "resource": {
                    "capabilities": person.resource,
                    "sensitivity": "matchable",
                },
                "concern": person.demand,
            },
        }

    @staticmethod
    def _create_entity(
        person: ExtractedPerson, user_id: str, event_id: str, status: str
    ) -> Entity:
        """Create an Entity ORM instance from extracted person data.

        Args:
            person: Extracted person data.
            user_id: Owner user ID.
            event_id: Source event ID.
            status: Entity status (confirmed or provisional).

        Returns:
            New Entity instance (not yet added to session).
        """
        return Entity(
            user_id=user_id,
            entity_type="person",
            name=person.name,
            canonical_name=person.name,
            aliases=[],
            properties={
                "basic": {
                    "company": person.company,
                    "title": person.title,
                    "phone": person.phone,
                    "email": person.email,
                    "city": person.city,
                    "industry": person.industry,
                },
                "resource": {
                    "capabilities": person.resource,
                    "sensitivity": "matchable",
                },
                "concern": person.demand,
                "event_ids": [event_id] if event_id else [],
            },
            source_event_id=event_id,
            confidence=person.confidence,
            status=status,
        )

    @staticmethod
    def _detect_language(text: str) -> str:
        """Detect the dominant language of the input text.

        Simple heuristic: if CJK characters exceed 30% of total,
        classify as zh-CN; otherwise en-US.

        Args:
            text: Input text to classify.

        Returns:
            Language code string (e.g., "zh-CN", "en-US").
        """
        if not text:
            return "zh-CN"

        cjk_count = 0
        for ch in text:
            cp = ord(ch)
            if (
                0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
                or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
                or 0x3000 <= cp <= 0x303F  # CJK Symbols and Punctuation
                or 0x3040 <= cp <= 0x309F  # Hiragana
                or 0x30A0 <= cp <= 0x30FF  # Katakana
            ):
                cjk_count += 1

        ratio = cjk_count / len(text) if text else 0
        return "zh-CN" if ratio > 0.3 else "en-US"

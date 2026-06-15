"""Tests for F-53: concern/capability enhanced extraction."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from promiselink.models.entity import Entity
from promiselink.services.entity_extractor import EntityExtractor, ExtractedPerson
from promiselink.services.llm_client import LLMClient
from promiselink.prompts.entity_extraction import (
    TEMPLATE_1_CARD_EXTRACTION,
    TEMPLATE_2_CONVERSATION_EXTRACTION,
)


def test_extracted_person_has_concern_capability_fields():
    """ExtractedPerson dataclass has concern and capability fields with defaults."""
    person = ExtractedPerson(name="张三")
    assert hasattr(person, "concern")
    assert hasattr(person, "capability")
    assert person.concern == []
    assert person.capability == []

    person_with_data = ExtractedPerson(
        name="李四",
        concern=[{"category": "融资", "detail": "正在寻求A轮融资"}],
        capability=[{"category": "投资决策", "detail": "专注早期科技投资"}],
    )
    assert person_with_data.concern == [{"category": "融资", "detail": "正在寻求A轮融资"}]
    assert person_with_data.capability == [{"category": "投资决策", "detail": "专注早期科技投资"}]


def test_card_template_includes_concern_capability():
    """TEMPLATE_1_CARD_EXTRACTION contains concern and capability rules and output fields."""
    # Check rules mention concern/capability
    assert "concern" in TEMPLATE_1_CARD_EXTRACTION
    assert "capability" in TEMPLATE_1_CARD_EXTRACTION
    assert "concern受控词表" in TEMPLATE_1_CARD_EXTRACTION
    assert "capability受控词表" in TEMPLATE_1_CARD_EXTRACTION

    # Check JSON output format includes concern/capability
    assert '"concern"' in TEMPLATE_1_CARD_EXTRACTION
    assert '"capability"' in TEMPLATE_1_CARD_EXTRACTION
    assert '"category"' in TEMPLATE_1_CARD_EXTRACTION
    assert '"detail"' in TEMPLATE_1_CARD_EXTRACTION


def test_conversation_template_includes_concern_capability():
    """TEMPLATE_2_CONVERSATION_EXTRACTION contains concern and capability rules and output fields."""
    assert "concern识别" in TEMPLATE_2_CONVERSATION_EXTRACTION
    assert "capability识别" in TEMPLATE_2_CONVERSATION_EXTRACTION
    assert "concern受控词表" in TEMPLATE_2_CONVERSATION_EXTRACTION
    assert "capability受控词表" in TEMPLATE_2_CONVERSATION_EXTRACTION

    # Check person JSON output includes concern/capability
    assert '"concern"' in TEMPLATE_2_CONVERSATION_EXTRACTION
    assert '"capability"' in TEMPLATE_2_CONVERSATION_EXTRACTION


def test_create_entity_includes_concern_capability():
    """_create_entity generates Entity with concern and capability in properties."""
    person = ExtractedPerson(
        name="张三",
        company="智源AI",
        title="CEO",
        concern=[{"category": "融资", "detail": "正在寻求A轮融资"}],
        capability=[{"category": "投资决策", "detail": "专注早期科技投资"}],
    )
    user_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    entity = EntityExtractor._create_entity(
        person=person,
        user_id=user_id,
        event_id=event_id,
        status="confirmed",
    )

    assert isinstance(entity, Entity)
    assert entity.properties["concern"] == [{"category": "融资", "detail": "正在寻求A轮融资"}]
    assert entity.properties["capability"] == [{"category": "投资决策", "detail": "专注早期科技投资"}]


def test_create_entity_concern_not_mapped_from_demand():
    """concern is independent from demand — not mapped from person.demand."""
    person = ExtractedPerson(
        name="张三",
        company="智源AI",
        demand=["AI项目"],
        concern=[{"category": "融资", "detail": "正在寻求A轮融资"}],
        capability=[{"category": "投资决策", "detail": "专注早期科技投资"}],
    )
    user_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    entity = EntityExtractor._create_entity(
        person=person,
        user_id=user_id,
        event_id=event_id,
        status="confirmed",
    )

    # concern should be person.concern, NOT person.demand
    assert entity.properties["concern"] == [{"category": "融资", "detail": "正在寻求A轮融资"}]
    assert entity.properties["concern"] != person.demand
    # demand should still be preserved
    assert entity.properties["demand"] == ["AI项目"]

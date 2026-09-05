"""Golden case schema (W2, FR-4) — validates case files before any LLM run."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExpectedOutput(BaseModel):
    """Expected extraction result for one golden case."""

    min_persons: int = 0
    max_persons: int | None = None
    person_names: list[str] = Field(default_factory=list)
    must_have_person_fields: list[str] = Field(default_factory=list)
    forbidden_person_fields: list[str] = Field(default_factory=list)
    keywords_any: list[str] = Field(default_factory=list)
    min_events: int = 0
    expect_confirmation: bool = False


class GoldenCase(BaseModel):
    """One golden test case: input text + layered expectation."""

    id: str
    layer: Literal["must_extract", "must_not", "ambiguous"]
    event_type: Literal[
        "card_save", "meeting", "call", "manual", "wechat_forward", "followup"
    ]
    input_text: str = Field(min_length=8)
    expected: ExpectedOutput
    notes: str = ""

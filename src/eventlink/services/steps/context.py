"""Shared types for the pipeline steps.

Extracted from pipeline_steps.py to break the circular import between
pipeline_steps and event_pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from eventlink.services.entity_extractor import ExtractionResult
from eventlink.services.llm_client import LLMClient
from eventlink.models.entity import Entity
from eventlink.models.todo import Todo


@dataclass
class PipelineContext:
    """Shared state carried between pipeline steps."""

    event_id: str
    # Populated after Step1
    user_id: str | None = None
    # Shared services (set by orchestrator)
    llm_client: LLMClient | None = None
    memory: Any = None  # MemoryProvider
    settings: Any = None  # Settings
    # Accumulated result
    result: Any = None  # PipelineResult — set by orchestrator
    # Intermediate results shared between steps
    entities: list[Entity] = field(default_factory=list)
    extraction: ExtractionResult | None = None
    todos: list[Todo] = field(default_factory=list)
    merged_entity_ids: list[str] = field(default_factory=list)
    # Control flow
    should_stop: bool = False


class PipelineStep(ABC):
    """Base class for all pipeline steps."""

    name: str = "unnamed_step"

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute this step, mutating context as needed."""

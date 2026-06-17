"""Shared types for the pipeline steps.

Extracted from pipeline_steps.py to break the circular import between
pipeline_steps and event_pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from promiselink.config import Settings
from promiselink.models.entity import Entity
from promiselink.models.todo import Todo
from promiselink.services.entity_extractor import ExtractionResult
from promiselink.services.llm_client import LLMClient
from promiselink.services.memory_provider import MemoryProvider


@dataclass
class PipelineResult:
    """Result of the full event processing pipeline."""

    event_id: str
    status: str = "completed"
    entities: list[Entity] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)
    extraction: ExtractionResult | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    step_timings: dict[str, float] = field(default_factory=dict)
    failed_steps: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.status == "completed" and self.error is None and not self.failed_steps


@dataclass
class PipelineContext:
    """Shared state carried between pipeline steps."""

    event_id: str
    # Populated after Step1
    user_id: str | None = None
    # Shared services (set by orchestrator)
    llm_client: LLMClient | None = None
    memory: MemoryProvider | None = None
    settings: Settings | None = None
    # Accumulated result
    result: PipelineResult | None = None
    # Intermediate results shared between steps
    entities: list[Entity] = field(default_factory=list)
    extraction: ExtractionResult | None = None
    todos: list[Todo] = field(default_factory=list)
    merged_entity_ids: list[str] = field(default_factory=list)
    # Control flow
    should_stop: bool = False
    # Step failure tracking
    failed_steps: list[str] = field(default_factory=list)


class PipelineStep(ABC):
    """Base class for all pipeline steps."""

    name: str = "unnamed_step"

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """Execute this step, mutating context as needed."""

"""Backward-compatibility re-exports.

The step classes have been moved to ``eventlink.services.steps``.
This module re-exports them under their old names so that any code
still importing from ``pipeline_steps`` continues to work.
"""

from eventlink.services.steps import *  # noqa: F401,F403

# Old class name aliases for backward compatibility
from eventlink.services.steps import (
    PipelineContext,
    PipelineStep,
    Step01_VerifyEvent as Step1_RawEventToEvent,
    Step02_ExtractEntities as Step2_EntityExtraction,
    Step03_SemanticEmbedding as Step5_5_DependencyAnalysis,
    Step04_TodoGeneration as Step5_TodoGeneration,
    Step05_PromiseAnalysis as Step7_ConcernCapabilityExtraction,
    Step06_ResourceOveruse as Step8_3_ContextMatching,
    Step07_PriorityScoring as Step6_PriorityScoring,
    Step08_Notification as Step9_Notification,
    Step09_MemoryStorage as Step10_MemoryStorage,
    Step10_AssociationDiscovery as Step4_AssociationDiscovery,
    Step11_AssociationTodos as Step8_5_SemanticAssociation,
    Step12_RelationshipBriefUpdate as Step13_RelationshipBriefUpdate,
    Step13_CompleteEvent as Step8_EventStatusUpdate,
)

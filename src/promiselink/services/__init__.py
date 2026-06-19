"""PromiseLink service modules."""

from promiselink.services.association_discovery import AssociationDiscoveryEngine
from promiselink.services.data_source_adapter import (
    DataSourceAdapter,
    ManualAdapter,
    RawEvent,
    WeChatAdapter,
    get_adapter,
    register_adapter,
)
from promiselink.services.embedding_provider import EMBEDDING_DIMENSIONS, EmbeddingProvider
from promiselink.services.entity_extractor import EntityExtractor, ExtractedPerson, ExtractionResult
from promiselink.services.entity_resolution import (
    EntityResolutionEngine,
    ResolutionAction,
    ResolutionResult,
)
from promiselink.services.event_pipeline import process_event_with_short_transactions
from promiselink.services.implicit_feedback import ImplicitFeedbackCollector
from promiselink.services.llm_client import LLMClient
from promiselink.services.memory_provider import (
    CarryMemProvider,
    FileStoreProvider,
    MemoryEntry,
    MemoryProvider,
    NullMemoryProvider,
    SearchResult,
    create_memory_provider,
)
from promiselink.services.promise_fulfillment import PromiseFulfillmentEngine, SensitivityFilter
from promiselink.services.semantic_search import SemanticSearchEngine
from promiselink.services.steps.context import PipelineResult
from promiselink.services.todo_generator import GeneratedTodo, TodoGenerator
from promiselink.services.todo_state_machine import TodoStateMachine

# Note: EmailAdapter is Pro-only (email_adapter.py migrated to PromiseLink-Pro).
# Pro edition registers it lazily via register_adapter().

__all__ = [
    "AssociationDiscoveryEngine",
    "DataSourceAdapter",
    "ManualAdapter",
    "RawEvent",
    "WeChatAdapter",
    "get_adapter",
    "register_adapter",
    "EmbeddingProvider",
    "EMBEDDING_DIMENSIONS",
    "EntityExtractor",
    "ExtractionResult",
    "ExtractedPerson",
    "EntityResolutionEngine",
    "ResolutionAction",
    "ResolutionResult",
    "PipelineResult",
    "process_event_with_short_transactions",
    "ImplicitFeedbackCollector",
    "LLMClient",
    "CarryMemProvider",
    "FileStoreProvider",
    "MemoryEntry",
    "MemoryProvider",
    "NullMemoryProvider",
    "SearchResult",
    "create_memory_provider",
    "PromiseFulfillmentEngine",
    "SensitivityFilter",
    "SemanticSearchEngine",
    "TodoGenerator",
    "GeneratedTodo",
    "TodoStateMachine",
]

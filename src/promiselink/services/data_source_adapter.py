"""DataSourceAdapter — Abstract interface for external data ingestion.

Implements F-54: Data source adapter architecture.
Pipeline remains unchanged; new data sources only need to implement this interface.

Design reference: Integration_Design_v1.md v2.5 §10, API_Design_v1.md v2.5 §3.14
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from promiselink.core.logging import get_logger

logger = get_logger("promiselink.data_source_adapter")


@dataclass
class RawEvent:
    """Normalized raw event from an external data source.

    This is the universal input format that the PromiseLink pipeline accepts.
    Each adapter converts its source-specific format into this structure.
    """

    source_type: str  # "email", "wechat", "calendar", "manual", etc.
    source_id: str  # Unique ID from the source system
    raw_text: str  # The text content to process
    event_type: str = "manual"  # Maps to Event.event_type
    title: str | None = None
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None


class DataSourceAdapter(ABC):
    """Abstract base class for data source adapters.

    Each external data source (email, WeChat, calendar, etc.) implements
    this interface to convert its data into RawEvent objects that the
    PromiseLink pipeline can process.

    The pipeline itself never changes — only new adapters are added.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    async def fetch_new_events(self, since: datetime | None = None) -> list[RawEvent]:
        """Fetch new events from the external source.

        Args:
            since: Only fetch events newer than this timestamp.
                   None means fetch all available.

        Returns:
            List of RawEvent objects ready for pipeline ingestion.
        """
        ...

    @abstractmethod
    async def acknowledge(self, source_id: str) -> bool:
        """Acknowledge that an event has been successfully processed.

        Args:
            source_id: The source-specific ID to acknowledge.

        Returns:
            True if acknowledgment succeeded.
        """
        ...

    @property
    @abstractmethod
    def source_type(self) -> str:
        """Return the source type identifier (e.g., 'email', 'wechat')."""
        ...


# EmailAdapter is now implemented in email_adapter.py
# Import it here for registry and backward compatibility
from promiselink.services.email_adapter import EmailAdapter  # noqa: F401 — re-exported


class WeChatAdapter(DataSourceAdapter):
    """WeChat data source adapter — PoC skeleton.

    WeChat ecosystem constraints:
    - No direct message reading (API limitation)
    - Only support forwarded messages / card saves
    - User must explicitly share content to PromiseLink

    Full implementation deferred to Phase 1.
    """

    @property
    def source_type(self) -> str:
        return "wechat"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def fetch_new_events(self, since: datetime | None = None) -> list[RawEvent]:
        """PoC: WeChat doesn't support push-based ingestion.

        Phase 1 will implement webhook-based forwarding.
        """
        logger.info("wechat_adapter_fetch_skipped", reason="PoC_skeleton")
        return []

    async def acknowledge(self, source_id: str) -> bool:
        """PoC: No-op."""
        return True


class ManualAdapter(DataSourceAdapter):
    """Manual input adapter — the default data source.

    This is the primary data source for PoC: users manually input
    event text through the API or voice interface.
    """

    @property
    def source_type(self) -> str:
        return "manual"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def fetch_new_events(self, since: datetime | None = None) -> list[RawEvent]:
        """Manual adapter doesn't fetch — events are pushed via API."""
        return []

    async def acknowledge(self, source_id: str) -> bool:
        return True

    def create_raw_event(
        self,
        raw_text: str,
        event_type: str = "manual",
        title: str | None = None,
        user_id: str | None = None,
    ) -> RawEvent:
        """Create a RawEvent from manual input.

        This is the primary entry point for PoC event ingestion.
        """
        return RawEvent(
            source_type=self.source_type,
            source_id=f"manual_{datetime.now().timestamp()}",
            raw_text=raw_text,
            event_type=event_type,
            title=title,
            user_id=user_id,
        )


# ── Adapter Registry ──

_ADAPTERS: dict[str, type[DataSourceAdapter]] = {
    "email": EmailAdapter,
    "wechat": WeChatAdapter,
    "manual": ManualAdapter,
}


def get_adapter(source_type: str, config: dict[str, Any] | None = None) -> DataSourceAdapter:
    """Get a data source adapter by type.

    Args:
        source_type: The adapter type identifier
        config: Optional configuration dict

    Returns:
        DataSourceAdapter instance

    Raises:
        ValueError: If source_type is not registered
    """
    adapter_cls = _ADAPTERS.get(source_type)
    if not adapter_cls:
        raise ValueError(f"Unknown data source adapter: {source_type}")
    return adapter_cls(config=config)


def register_adapter(source_type: str, adapter_cls: type[DataSourceAdapter]) -> None:
    """Register a new data source adapter.

    Args:
        source_type: Unique identifier for this adapter
        adapter_cls: The adapter class to register
    """
    _ADAPTERS[source_type] = adapter_cls
    logger.info("adapter_registered", source_type=source_type)

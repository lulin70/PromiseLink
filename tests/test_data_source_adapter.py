"""Tests for F-54: DataSourceAdapter — Abstract interface for data ingestion."""

import pytest

from eventlink.services.data_source_adapter import (
    DataSourceAdapter,
    EmailAdapter,
    ManualAdapter,
    RawEvent,
    WeChatAdapter,
    get_adapter,
    register_adapter,
)


class TestRawEvent:
    """Test RawEvent dataclass."""

    def test_raw_event_creation(self):
        """Verify RawEvent creation with required and optional fields."""
        event = RawEvent(
            source_type="email",
            source_id="msg_123",
            raw_text="Meeting tomorrow at 3pm",
        )
        assert event.source_type == "email"
        assert event.source_id == "msg_123"
        assert event.raw_text == "Meeting tomorrow at 3pm"
        assert event.event_type == "manual"  # default
        assert event.title is None
        assert event.metadata == {}

    def test_raw_event_with_all_fields(self):
        """Verify RawEvent creation with all fields specified."""
        from datetime import datetime

        now = datetime.now()
        event = RawEvent(
            source_type="wechat",
            source_id="wx_456",
            raw_text="Let's catch up",
            event_type="meeting",
            title="Catch up",
            occurred_at=now,
            metadata={"chat_id": "abc"},
            user_id="user_789",
        )
        assert event.event_type == "meeting"
        assert event.title == "Catch up"
        assert event.occurred_at == now
        assert event.metadata == {"chat_id": "abc"}
        assert event.user_id == "user_789"


class TestManualAdapter:
    """Test ManualAdapter."""

    @pytest.mark.asyncio
    async def test_manual_adapter_create_raw_event(self):
        """Verify ManualAdapter creates RawEvent from manual input."""
        adapter = ManualAdapter()
        event = adapter.create_raw_event(
            raw_text="Had coffee with Zhang San",
            event_type="meeting",
            title="Coffee with Zhang San",
            user_id="user_123",
        )
        assert event.source_type == "manual"
        assert event.source_id.startswith("manual_")
        assert event.raw_text == "Had coffee with Zhang San"
        assert event.event_type == "meeting"
        assert event.title == "Coffee with Zhang San"
        assert event.user_id == "user_123"

    @pytest.mark.asyncio
    async def test_manual_adapter_fetch_returns_empty(self):
        """Verify ManualAdapter.fetch_new_events returns empty list."""
        adapter = ManualAdapter()
        events = await adapter.fetch_new_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_manual_adapter_acknowledge(self):
        """Verify ManualAdapter.acknowledge returns True."""
        adapter = ManualAdapter()
        result = await adapter.acknowledge("any_id")
        assert result is True


class TestEmailAdapter:
    """Test EmailAdapter — now delegates to full implementation."""

    @pytest.mark.asyncio
    async def test_email_adapter_source_type(self):
        """Verify EmailAdapter.source_type returns 'email'."""
        adapter = EmailAdapter()
        assert adapter.source_type == "email"

    @pytest.mark.asyncio
    async def test_email_adapter_fetch_returns_empty_when_not_connected(self):
        """Verify EmailAdapter.fetch_new_events returns empty list when not connected."""
        adapter = EmailAdapter()
        events = await adapter.fetch_new_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_email_adapter_acknowledge_returns_false_when_not_connected(self):
        """Verify EmailAdapter.acknowledge returns False when not connected."""
        adapter = EmailAdapter()
        result = await adapter.acknowledge("msg_123")
        assert result is False


class TestWeChatAdapter:
    """Test WeChatAdapter PoC skeleton."""

    @pytest.mark.asyncio
    async def test_wechat_adapter_source_type(self):
        """Verify WeChatAdapter.source_type returns 'wechat'."""
        adapter = WeChatAdapter()
        assert adapter.source_type == "wechat"

    @pytest.mark.asyncio
    async def test_wechat_adapter_fetch_returns_empty(self):
        """Verify WeChatAdapter.fetch_new_events returns empty list (PoC)."""
        adapter = WeChatAdapter()
        events = await adapter.fetch_new_events()
        assert events == []

    @pytest.mark.asyncio
    async def test_wechat_adapter_acknowledge(self):
        """Verify WeChatAdapter.acknowledge returns True (PoC)."""
        adapter = WeChatAdapter()
        result = await adapter.acknowledge("wx_123")
        assert result is True


class TestAdapterRegistry:
    """Test adapter registry functions."""

    def test_get_adapter_returns_correct_type(self):
        """Verify get_adapter returns the correct adapter type."""
        email = get_adapter("email")
        assert isinstance(email, EmailAdapter)

        wechat = get_adapter("wechat")
        assert isinstance(wechat, WeChatAdapter)

        manual = get_adapter("manual")
        assert isinstance(manual, ManualAdapter)

    def test_get_adapter_with_config(self):
        """Verify get_adapter passes config to adapter."""
        config = {"imap_host": "imap.example.com"}
        adapter = get_adapter("email", config=config)
        assert isinstance(adapter, EmailAdapter)
        assert adapter.config == config

    def test_get_adapter_unknown_type_raises(self):
        """Verify get_adapter raises ValueError for unknown type."""
        with pytest.raises(ValueError, match="Unknown data source adapter"):
            get_adapter("slack")

    def test_register_adapter(self):
        """Verify register_adapter adds a new adapter type."""
        # Create a custom adapter
        class SlackAdapter(DataSourceAdapter):
            @property
            def source_type(self) -> str:
                return "slack"

            def __init__(self, config=None):
                self.config = config or {}

            async def fetch_new_events(self, since=None):
                return []

            async def acknowledge(self, source_id: str) -> bool:
                return True

        register_adapter("slack", SlackAdapter)
        adapter = get_adapter("slack")
        assert isinstance(adapter, SlackAdapter)
        assert adapter.source_type == "slack"

        # Cleanup: remove the registered adapter to avoid test pollution
        from eventlink.services import data_source_adapter
        data_source_adapter._ADAPTERS.pop("slack", None)


class TestDataSourceAdapterIsAbstract:
    """Test that DataSourceAdapter cannot be instantiated directly."""

    def test_adapter_interface_is_abstract(self):
        """Verify DataSourceAdapter is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            DataSourceAdapter()  # type: ignore[abstract]

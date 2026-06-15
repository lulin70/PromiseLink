"""Tests for WeChatForwardAdapter — PRD §5.17.

Covers:
- Chat message extraction from various WeChat forward formats
- Speaker identification
- Event creation with correct metadata
- Edge cases: empty input, single message, unparseable text
"""

import pytest

from promiselink.services.wechat_forward_adapter import (
    ChatMessage,
    WeChatForwardAdapter,
)


# ── Fixtures ──

@pytest.fixture
def adapter() -> WeChatForwardAdapter:
    return WeChatForwardAdapter()


# ── _extract_chat_messages Tests ──


class TestExtractChatMessages:
    """Test WeChat chat message extraction."""

    def test_group_chat_standard_format(self, adapter: WeChatForwardAdapter):
        """Standard group chat with multiple speakers and times."""
        text = """张三 10:30
明天下午3点见面聊聊合作

李四 10:32
好的，我准备一下资料

张三 10:35
记得把上次的合同带上"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 3
        assert messages[0].speaker == "张三"
        assert messages[0].time == "10:30"
        assert messages[0].content == "明天下午3点见面聊聊合作"
        assert messages[1].speaker == "李四"
        assert messages[1].time == "10:32"
        assert messages[1].content == "好的，我准备一下资料"
        assert messages[2].speaker == "张三"
        assert messages[2].time == "10:35"
        assert messages[2].content == "记得把上次的合同带上"

    def test_multiline_message_content(self, adapter: WeChatForwardAdapter):
        """Message with multiple lines of content."""
        text = """张三 10:30
明天下午3点见面聊聊合作
地点在国贸大厦
3楼会议室"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 1
        assert messages[0].speaker == "张三"
        assert "明天下午3点见面聊聊合作" in messages[0].content
        assert "地点在国贸大厦" in messages[0].content
        assert "3楼会议室" in messages[0].content

    def test_single_speaker(self, adapter: WeChatForwardAdapter):
        """Single speaker with multiple messages."""
        text = """张三 10:30
第一条消息

张三 10:35
第二条消息"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 2
        assert all(m.speaker == "张三" for m in messages)

    def test_chinese_date_prefix_in_time(self, adapter: WeChatForwardAdapter):
        """Time with Chinese date prefix like '昨天 10:30'."""
        text = """张三 昨天 10:30
昨天的消息

李四 昨天 10:35
回复昨天的消息"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 2
        assert messages[0].speaker == "张三"
        assert messages[0].time == "昨天 10:30"
        assert messages[1].speaker == "李四"
        assert messages[1].time == "昨天 10:35"

    def test_weekday_prefix_in_time(self, adapter: WeChatForwardAdapter):
        """Time with weekday prefix like '星期三 10:30'."""
        text = """张三 星期三 10:30
周三的消息"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 1
        assert messages[0].speaker == "张三"
        assert messages[0].time == "星期三 10:30"

    def test_am_pm_prefix_in_time(self, adapter: WeChatForwardAdapter):
        """Time with 上午/下午 prefix."""
        text = """张三 上午 10:30
上午的消息

李四 下午 2:30
下午的消息"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 2
        assert messages[0].time == "上午 10:30"
        assert messages[1].time == "下午 2:30"

    def test_empty_input(self, adapter: WeChatForwardAdapter):
        """Empty or whitespace-only input returns empty list."""
        assert adapter._extract_chat_messages("") == []
        assert adapter._extract_chat_messages("   ") == []
        assert adapter._extract_chat_messages("\n\n") == []

    def test_unparseable_text_fallback(self, adapter: WeChatForwardAdapter):
        """Text that doesn't match WeChat format falls back to single message."""
        text = "这是一段没有任何格式的纯文本内容"

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 1
        assert messages[0].speaker == "未知"
        assert messages[0].time is None
        assert messages[0].content == text

    def test_time_only_lines_single_chat(self, adapter: WeChatForwardAdapter):
        """Single chat format where only time appears (no speaker name for the other party)."""
        text = """张三 10:30
明天见面聊聊

10:32
好的没问题

张三 10:35
记得带上资料"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 3
        assert messages[0].speaker == "张三"
        assert messages[1].speaker == "对方"
        assert messages[2].speaker == "张三"

    def test_speaker_with_english_name(self, adapter: WeChatForwardAdapter):
        """Speaker with English name."""
        text = """John 10:30
Let's meet tomorrow

Mary 10:32
Sure, sounds good"""

        messages = adapter._extract_chat_messages(text)

        assert len(messages) == 2
        assert messages[0].speaker == "John"
        assert messages[1].speaker == "Mary"


# ── _identify_speakers Tests ──


class TestIdentifySpeakers:
    """Test speaker identification."""

    def test_multiple_speakers(self, adapter: WeChatForwardAdapter):
        messages = [
            ChatMessage(speaker="张三", time="10:30", content="hi"),
            ChatMessage(speaker="李四", time="10:32", content="hello"),
            ChatMessage(speaker="张三", time="10:35", content="bye"),
        ]
        speakers = adapter._identify_speakers(messages)

        assert list(speakers.keys()) == ["张三", "李四"]

    def test_single_speaker(self, adapter: WeChatForwardAdapter):
        messages = [
            ChatMessage(speaker="张三", time="10:30", content="hi"),
            ChatMessage(speaker="张三", time="10:35", content="bye"),
        ]
        speakers = adapter._identify_speakers(messages)

        assert list(speakers.keys()) == ["张三"]

    def test_empty_messages(self, adapter: WeChatForwardAdapter):
        speakers = adapter._identify_speakers([])
        assert speakers == {}


# ── parse_forwarded_message Tests ──


class TestParseForwardedMessage:
    """Test full message parsing into Event."""

    def test_standard_group_chat(self, adapter: WeChatForwardAdapter):
        text = """张三 10:30
明天下午3点见面聊聊合作

李四 10:32
好的，我准备一下资料

张三 10:35
记得把上次的合同带上"""

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert event.event_type == "wechat_forward"
        assert event.source == "wechat_forward"
        assert "张三" in event.title
        assert "2" in event.title  # 2 speakers
        assert event.raw_text == text
        assert event.metadata_ is not None
        assert event.metadata_["speakers"] == ["张三", "李四"]
        assert event.metadata_["message_count"] == 3
        assert event.metadata_["time_range"] == "10:30-10:35"
        assert event.user_id == "user_123"
        assert event.status == "pending"

    def test_single_speaker_title(self, adapter: WeChatForwardAdapter):
        text = """张三 10:30
明天见面"""

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert "张三" in event.title
        assert event.metadata_["speakers"] == ["张三"]
        assert event.metadata_["message_count"] == 1

    def test_unparseable_text_event(self, adapter: WeChatForwardAdapter):
        text = "这是一段没有格式的文本"

        event = adapter.parse_forwarded_message(text, user_id="user_456")

        assert event.event_type == "wechat_forward"
        assert event.raw_text == text
        assert event.metadata_["message_count"] == 1
        assert event.metadata_["time_range"] == ""

    def test_time_range_single_time(self, adapter: WeChatForwardAdapter):
        text = """张三 10:30
只有一条消息"""

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert event.metadata_["time_range"] == "10:30"

    def test_time_range_with_date_prefix(self, adapter: WeChatForwardAdapter):
        text = """张三 昨天 10:30
昨天的消息

李四 昨天 10:35
回复"""

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert event.metadata_["time_range"] == "10:30-10:35"

    def test_three_speakers(self, adapter: WeChatForwardAdapter):
        text = """张三 10:30
第一个发言

李四 10:32
第二个发言

王五 10:35
第三个发言"""

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert event.metadata_["speakers"] == ["张三", "李四", "王五"]
        assert "3" in event.title

    def test_preserves_original_text(self, adapter: WeChatForwardAdapter):
        """Ensure raw_text preserves the exact original input."""
        text = "张三 10:30\n明天见面\n\n李四 10:32\n好的"

        event = adapter.parse_forwarded_message(text, user_id="user_123")

        assert event.raw_text == text


# ── _compute_time_range Tests ──


class TestComputeTimeRange:
    """Test time range computation."""

    def test_no_times(self, adapter: WeChatForwardAdapter):
        messages = [ChatMessage(speaker="A", time=None, content="hi")]
        assert adapter._compute_time_range(messages) == ""

    def test_single_time(self, adapter: WeChatForwardAdapter):
        messages = [ChatMessage(speaker="A", time="10:30", content="hi")]
        assert adapter._compute_time_range(messages) == "10:30"

    def test_multiple_times(self, adapter: WeChatForwardAdapter):
        messages = [
            ChatMessage(speaker="A", time="10:30", content="hi"),
            ChatMessage(speaker="B", time="10:35", content="hello"),
        ]
        assert adapter._compute_time_range(messages) == "10:30-10:35"

    def test_time_with_date_prefix(self, adapter: WeChatForwardAdapter):
        messages = [
            ChatMessage(speaker="A", time="昨天 10:30", content="hi"),
            ChatMessage(speaker="B", time="昨天 10:35", content="hello"),
        ]
        assert adapter._compute_time_range(messages) == "10:30-10:35"

    def test_empty_messages(self, adapter: WeChatForwardAdapter):
        assert adapter._compute_time_range([]) == ""

"""Tests for promiselink.services.notification_service.

Tests NotificationService dispatch logic and notify_todo_created
convenience method. Uses instance attribute injection to avoid
env-var coupling (no real WeChat API calls).
"""

from __future__ import annotations

import pytest

from promiselink.services.notification_service import (
    NotificationChannel,
    NotificationMessage,
    NotificationPriority,
    NotificationService,
    notification_service,
)

# ── Helpers ──


def _make_service(*, configured: bool = False) -> NotificationService:
    """Create NotificationService with controllable config."""
    svc = NotificationService.__new__(NotificationService)
    svc.wechat_app_id = "test_app_id" if configured else None
    svc.wechat_app_secret = "test_app_secret" if configured else None
    svc._access_token = None
    return svc


def _make_message(
    channel: NotificationChannel = NotificationChannel.WECHAT_SUBSCRIBE,
    priority: NotificationPriority = NotificationPriority.MEDIUM,
    user_id: str = "user-1",
    title: str = "Test",
    content: str = "test content",
) -> NotificationMessage:
    return NotificationMessage(
        user_id=user_id,
        channel=channel,
        priority=priority,
        title=title,
        content=content,
    )


# ═══════════════════════════════════════════════════════════════
# NotificationChannel / NotificationPriority — 枚举
# ═══════════════════════════════════════════════════════════════


class TestNotificationEnums:
    """NotificationChannel / NotificationPriority 枚举值."""

    def test_channel_values(self):
        assert NotificationChannel.WECHAT_TEMPLATE.value == "wechat_template"
        assert NotificationChannel.WECHAT_SUBSCRIBE.value == "wechat_subscribe"
        assert NotificationChannel.PUSH.value == "push"

    def test_priority_values(self):
        assert NotificationPriority.HIGH.value == "high"
        assert NotificationPriority.MEDIUM.value == "medium"
        assert NotificationPriority.LOW.value == "low"


# ═══════════════════════════════════════════════════════════════
# NotificationMessage — dataclass
# ═══════════════════════════════════════════════════════════════


class TestNotificationMessage:
    """NotificationMessage dataclass 字段."""

    def test_required_fields(self):
        msg = _make_message()
        assert msg.user_id == "user-1"
        assert msg.channel == NotificationChannel.WECHAT_SUBSCRIBE
        assert msg.priority == NotificationPriority.MEDIUM
        assert msg.title == "Test"
        assert msg.content == "test content"

    def test_optional_fields_default_none(self):
        msg = _make_message()
        assert msg.data is None
        assert msg.todo_id is None

    def test_optional_fields_can_be_set(self):
        msg = NotificationMessage(
            user_id="u",
            channel=NotificationChannel.PUSH,
            priority=NotificationPriority.LOW,
            title="t",
            content="c",
            data={"key": "value"},
            todo_id="todo-1",
        )
        assert msg.data == {"key": "value"}
        assert msg.todo_id == "todo-1"


# ═══════════════════════════════════════════════════════════════
# NotificationService.send — 渠道路由
# ═══════════════════════════════════════════════════════════════


class TestNotificationServiceSend:
    """NotificationService.send 渠道路由与配置检查."""

    @pytest.mark.asyncio
    async def test_happy_wechat_template_configured_returns_true(self):
        """已配置 wechat_app_id/secret 时 WECHAT_TEMPLATE 应返回 True (stub)."""
        svc = _make_service(configured=True)
        msg = _make_message(channel=NotificationChannel.WECHAT_TEMPLATE)
        assert await svc.send(msg) is True

    @pytest.mark.asyncio
    async def test_boundary_wechat_template_not_configured_returns_false(self):
        """未配置 wechat_app_id/secret 时 WECHAT_TEMPLATE 应返回 False."""
        svc = _make_service(configured=False)
        msg = _make_message(channel=NotificationChannel.WECHAT_TEMPLATE)
        assert await svc.send(msg) is False

    @pytest.mark.asyncio
    async def test_happy_wechat_subscribe_configured_returns_true(self):
        """已配置时 WECHAT_SUBSCRIBE 应返回 True (stub)."""
        svc = _make_service(configured=True)
        msg = _make_message(channel=NotificationChannel.WECHAT_SUBSCRIBE)
        assert await svc.send(msg) is True

    @pytest.mark.asyncio
    async def test_boundary_wechat_subscribe_not_configured_returns_false(self):
        """未配置时 WECHAT_SUBSCRIBE 应返回 False."""
        svc = _make_service(configured=False)
        msg = _make_message(channel=NotificationChannel.WECHAT_SUBSCRIBE)
        assert await svc.send(msg) is False

    @pytest.mark.asyncio
    async def test_boundary_push_always_returns_false(self):
        """PUSH 渠道未实现，应始终返回 False."""
        svc = _make_service(configured=True)
        msg = _make_message(channel=NotificationChannel.PUSH)
        assert await svc.send(msg) is False

    @pytest.mark.asyncio
    async def test_boundary_unknown_channel_returns_false(self):
        """未知渠道应返回 False (不抛异常)."""
        svc = _make_service(configured=True)
        msg = _make_message()
        # Bypass enum validation by setting an invalid channel
        msg.channel = "unknown_channel"
        assert await svc.send(msg) is False

    @pytest.mark.asyncio
    async def test_boundary_send_exception_returns_false(self):
        """send 内部抛异常时应被捕获并返回 False (不向调用方传播)."""
        svc = _make_service(configured=True)
        msg = _make_message(channel=NotificationChannel.WECHAT_TEMPLATE)
        # Force _send_wechat_template to raise
        svc._send_wechat_template = _raise_on_call
        assert await svc.send(msg) is False


async def _raise_on_call(message):
    raise RuntimeError("simulated WeChat API failure")


# ═══════════════════════════════════════════════════════════════
# NotificationService.notify_todo_created — 便捷方法
# ═══════════════════════════════════════════════════════════════


class TestNotifyTodoCreated:
    """notify_todo_created 便捷方法 — 优先级映射."""

    @pytest.mark.parametrize("todo_type,expected_priority", [
        ("promise", NotificationPriority.HIGH),
        ("risk", NotificationPriority.HIGH),
        ("help", NotificationPriority.MEDIUM),
        ("care", NotificationPriority.MEDIUM),
        ("cooperation_signal", NotificationPriority.MEDIUM),
        ("followup", NotificationPriority.LOW),
        ("unknown_type", NotificationPriority.MEDIUM),  # default
    ])
    @pytest.mark.asyncio
    async def test_priority_mapping(self, todo_type, expected_priority):
        """每种 todo_type 应映射到正确的优先级."""
        svc = _make_service(configured=True)
        # Patch _send_wechat_subscribe to capture message
        captured: list[NotificationMessage] = []

        async def _capture(msg):
            captured.append(msg)
            return True

        svc._send_wechat_subscribe = _capture
        await svc.notify_todo_created("u-1", "test todo", todo_type, "todo-id-1")
        assert len(captured) == 1
        assert captured[0].priority == expected_priority

    @pytest.mark.asyncio
    async def test_happy_returns_true_when_configured(self):
        svc = _make_service(configured=True)
        result = await svc.notify_todo_created("u-1", "title", "promise", "todo-id")
        assert result is True

    @pytest.mark.asyncio
    async def test_boundary_returns_false_when_not_configured(self):
        svc = _make_service(configured=False)
        result = await svc.notify_todo_created("u-1", "title", "promise", "todo-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_happy_title_contains_todo_title(self):
        """通知标题应包含 todo 标题."""
        svc = _make_service(configured=True)
        captured: list[NotificationMessage] = []

        async def _capture(msg):
            captured.append(msg)
            return True

        svc._send_wechat_subscribe = _capture
        await svc.notify_todo_created("u-1", "发送技术方案", "promise", "todo-id-1")
        assert "发送技术方案" in captured[0].title

    @pytest.mark.asyncio
    async def test_happy_message_uses_wechat_subscribe_channel(self):
        """notify_todo_created 应使用 WECHAT_SUBSCRIBE 渠道."""
        svc = _make_service(configured=True)
        captured: list[NotificationMessage] = []

        async def _capture(msg):
            captured.append(msg)
            return True

        svc._send_wechat_subscribe = _capture
        await svc.notify_todo_created("u-1", "title", "promise", "todo-id")
        assert captured[0].channel == NotificationChannel.WECHAT_SUBSCRIBE

    @pytest.mark.asyncio
    async def test_happy_todo_id_propagated(self):
        """todo_id 应被传播到 NotificationMessage.todo_id."""
        svc = _make_service(configured=True)
        captured: list[NotificationMessage] = []

        async def _capture(msg):
            captured.append(msg)
            return True

        svc._send_wechat_subscribe = _capture
        await svc.notify_todo_created("u-1", "title", "promise", "todo-123")
        assert captured[0].todo_id == "todo-123"


# ═══════════════════════════════════════════════════════════════
# notification_service singleton
# ═══════════════════════════════════════════════════════════════


class TestNotificationServiceSingleton:
    """notification_service 单例."""

    def test_singleton_is_instance_of_service(self):
        assert isinstance(notification_service, NotificationService)

    def test_singleton_has_wechat_attributes(self):
        assert hasattr(notification_service, "wechat_app_id")
        assert hasattr(notification_service, "wechat_app_secret")

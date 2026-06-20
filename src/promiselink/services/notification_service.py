"""Notification service for PromiseLink.

Supports multiple channels:
- WeChat Official Account template messages
- WeChat Mini Program subscribe messages
- Push notifications (future)

Reference:
- Template messages: https://developers.weixin.qq.com/doc/offiaccount/Message_Management/Template_Message_Interface.html
- Subscribe messages: https://developers.weixin.qq.com/miniprogram/dev/framework/open-ability/subscribe-message.html
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

from promiselink.config import get_settings
from promiselink.core.logging import get_logger

logger = get_logger("promiselink.notification")


class NotificationChannel(str, Enum):
    WECHAT_TEMPLATE = "wechat_template"
    WECHAT_SUBSCRIBE = "wechat_subscribe"
    PUSH = "push"


class NotificationPriority(str, Enum):
    HIGH = "high"      # 承诺到期、风险提醒
    MEDIUM = "medium"  # 关注点更新、合作信号
    LOW = "low"        # 日常摘要


@dataclass
class NotificationMessage:
    """A notification to be sent to a user."""
    user_id: str
    channel: NotificationChannel
    priority: NotificationPriority
    title: str
    content: str
    data: dict[str, Any] | None = None
    todo_id: str | None = None


class NotificationService:
    """Notification dispatch service."""

    def __init__(self) -> None:
        settings = get_settings()
        self.wechat_app_id = settings.wechat_app_id
        self.wechat_app_secret = settings.wechat_app_secret
        self._access_token: str | None = None

    async def send(self, message: NotificationMessage) -> bool:
        """Send a notification through the appropriate channel.

        Returns:
            True if sent successfully, False otherwise.
        """
        try:
            if message.channel == NotificationChannel.WECHAT_TEMPLATE:
                return await self._send_wechat_template(message)
            elif message.channel == NotificationChannel.WECHAT_SUBSCRIBE:
                return await self._send_wechat_subscribe(message)
            elif message.channel == NotificationChannel.PUSH:
                return await self._send_push(message)
            else:
                logger.warning("unknown_notification_channel", channel=message.channel)
                return False
        except Exception as e:  # External API — keep broad catch for resilience
            logger.error("notification_send_failed", channel=message.channel, user_id=message.user_id, error=str(e))
            return False

    async def _send_wechat_template(self, message: NotificationMessage) -> bool:
        """Send WeChat Official Account template message.

        Requires: user has followed the official account.
        Template ID and data format configured per message type.
        """
        if not self.wechat_app_id or not self.wechat_app_secret:
            logger.debug("wechat_not_configured", action="template_message")
            return False

        # Phase 1: Implement template message sending
        # 1. Get access_token
        # 2. POST https://api.weixin.qq.com/cgi-bin/message/template/send
        logger.info(
            "notification_wechat_template",
            user_id=message.user_id,
            title=message.title,
            priority=message.priority,
        )
        return True  # Stub: always return True for PoC

    async def _send_wechat_subscribe(self, message: NotificationMessage) -> bool:
        """Send WeChat Mini Program subscribe message.

        Requires: user has subscribed to the message type in the mini program.
        """
        if not self.wechat_app_id or not self.wechat_app_secret:
            logger.debug("wechat_not_configured", action="subscribe_message")
            return False

        # Phase 1: Implement subscribe message sending
        logger.info(
            "notification_wechat_subscribe",
            user_id=message.user_id,
            title=message.title,
            priority=message.priority,
        )
        return True  # Stub

    async def _send_push(self, message: NotificationMessage) -> bool:
        """Send push notification (future: APNs/FCM)."""
        logger.info(
            "notification_push",
            user_id=message.user_id,
            title=message.title,
        )
        return False  # Not implemented

    async def notify_todo_created(self, user_id: str, todo_title: str, todo_type: str, todo_id: str) -> bool:
        """Convenience method: notify user about a new todo."""
        priority_map = {
            "promise": NotificationPriority.HIGH,
            "risk": NotificationPriority.HIGH,
            "help": NotificationPriority.MEDIUM,
            "care": NotificationPriority.MEDIUM,
            "cooperation_signal": NotificationPriority.MEDIUM,
            "followup": NotificationPriority.LOW,
        }
        msg = NotificationMessage(
            user_id=user_id,
            channel=NotificationChannel.WECHAT_SUBSCRIBE,
            priority=priority_map.get(todo_type, NotificationPriority.MEDIUM),
            title=f"新提醒：{todo_title}",
            content=f"您有一条{todo_type}类型的待办事项",
            todo_id=todo_id,
        )
        return await self.send(msg)


# Singleton
notification_service = NotificationService()

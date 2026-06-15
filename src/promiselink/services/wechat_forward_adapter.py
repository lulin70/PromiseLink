"""WeChatForwardAdapter — Parse forwarded WeChat chat messages into Event objects.

Implements PRD §5.17: Users manually paste/forward WeChat chat records into
PromiseLink mini-program, and the content is parsed into structured Events.

WeChat forwarded message format (group chat):
    张三 10:30
    明天下午3点见面聊聊合作

    李四 10:32
    好的，我准备一下资料

Single chat format:
    张三 10:30
    明天下午3点见面聊聊合作

    10:32
    好的，我准备一下资料

Parsing uses rule-based logic only (no LLM dependency).
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from promiselink.core.logging import get_logger
from promiselink.models.event import Event

logger = get_logger("promiselink.wechat_forward_adapter")


@dataclass
class ChatMessage:
    """A single chat message extracted from forwarded WeChat content."""

    speaker: str
    time: Optional[str]
    content: str


# Pattern: "名字 时间" where 时间 is like "10:30", "昨天 10:30", "上午 10:30", etc.
# WeChat uses various time formats: "10:30", "昨天 10:30", "星期三 10:30", "2024-01-15 10:30"
_SPEAKER_LINE_PATTERN = re.compile(
    r"^(\S{1,20})\s+"  # speaker name (1-20 non-space chars)
    r"("                # time group start
    r"(?:昨天|前天|今天|星期[一二三四五六日天]|周[一二三四五六日天]|上午|下午|晚上)?\s*"  # optional date prefix
    r"\d{1,2}:\d{2}"   # HH:MM
    r"(?::\d{2})?"     # optional :SS
    r")"                # time group end
    r"\s*$"
)

# Simpler pattern for single chat where only time appears (no speaker name)
_TIME_ONLY_PATTERN = re.compile(
    r"^("
    r"(?:昨天|前天|今天|星期[一二三四五六日天]|周[一二三四五六日天]|上午|下午|晚上)?\s*"
    r"\d{1,2}:\d{2}"
    r"(?::\d{2})?"
    r")\s*$"
)


class WeChatForwardAdapter:
    """Parse forwarded WeChat chat messages into Event objects.

    Supports:
    - Group chat format (multiple speakers with names)
    - Single chat format (alternating time-only lines for the other party)
    - Fallback: unparseable text is treated as a single message
    """

    def parse_forwarded_message(self, text: str, user_id: str) -> Event:
        """Parse a forwarded WeChat message into an Event.

        Args:
            text: The raw forwarded WeChat chat content.
            user_id: The user ID who forwarded the message.

        Returns:
            An Event instance (not yet persisted to database).
        """
        messages = self._extract_chat_messages(text)
        speakers = self._identify_speakers(messages)

        # Build title
        speaker_names = list(speakers.keys())
        speaker_count = len(speaker_names)
        if speaker_count > 0:
            first_speaker = speaker_names[0]
            title = f"微信转发: {first_speaker}等{speaker_count}人的对话"
        else:
            title = "微信转发: 对话记录"

        # Build time_range
        time_range = self._compute_time_range(messages)

        # Build metadata
        metadata = {
            "speakers": speaker_names,
            "message_count": len(messages),
            "time_range": time_range,
        }

        event = Event(
            user_id=user_id,
            event_type="wechat_forward",
            source="wechat_forward",
            title=title,
            raw_text=text,
            metadata_=metadata,
            status="pending",
            timestamp=datetime.now(timezone.utc),
        )

        logger.info(
            "wechat_forward_parsed",
            user_id=user_id,
            speaker_count=speaker_count,
            message_count=len(messages),
            time_range=time_range,
        )

        return event

    def _extract_chat_messages(self, text: str) -> list[ChatMessage]:
        """Extract individual chat messages from forwarded WeChat text.

        Parsing logic:
        1. Split text by lines
        2. Identify "名字 时间" format lines as new message start
        3. Subsequent lines (until next speaker line) are the message content
        4. If no format is recognized, treat entire text as one message

        Args:
            text: Raw forwarded WeChat text.

        Returns:
            List of ChatMessage objects.
        """
        if not text or not text.strip():
            return []

        lines = text.strip().split("\n")
        messages: list[ChatMessage] = []
        current_speaker: Optional[str] = None
        current_time: Optional[str] = None
        current_content_lines: list[str] = []

        has_recognized_format = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # Empty line: could be separator between messages
                # If we have a current message, just continue (content may span paragraphs)
                continue

            # Try to match speaker line pattern
            speaker_match = _SPEAKER_LINE_PATTERN.match(stripped)
            if speaker_match:
                # Save previous message if any
                if current_speaker is not None:
                    messages.append(ChatMessage(
                        speaker=current_speaker,
                        time=current_time,
                        content="\n".join(current_content_lines).strip(),
                    ))

                has_recognized_format = True
                current_speaker = speaker_match.group(1)
                current_time = speaker_match.group(2)
                current_content_lines = []
                continue

            # Try to match time-only line (single chat format)
            time_match = _TIME_ONLY_PATTERN.match(stripped)
            if time_match and current_speaker is not None:
                # This is likely a time indicator for the other party in single chat
                # Save previous message and start a new one with "对方" as speaker
                if current_content_lines:
                    messages.append(ChatMessage(
                        speaker=current_speaker,
                        time=current_time,
                        content="\n".join(current_content_lines).strip(),
                    ))
                current_speaker = "对方"
                current_time = time_match.group(1)
                current_content_lines = []
                has_recognized_format = True
                continue

            # Regular content line
            if current_speaker is not None:
                current_content_lines.append(stripped)
            else:
                # Content before any speaker line — treat as preamble or standalone
                current_content_lines.append(stripped)

        # Save the last message
        if current_speaker is not None and current_content_lines:
            messages.append(ChatMessage(
                speaker=current_speaker,
                time=current_time,
                content="\n".join(current_content_lines).strip(),
            ))

        # Fallback: if no format recognized, treat entire text as one message
        if not has_recognized_format and not messages:
            messages.append(ChatMessage(
                speaker="未知",
                time=None,
                content=text.strip(),
            ))

        return messages

    def _identify_speakers(self, messages: list[ChatMessage]) -> dict[str, str]:
        """Identify unique speakers from chat messages.

        Args:
            messages: List of ChatMessage objects.

        Returns:
            Dict mapping speaker name to a label (currently same as name).
            The dict preserves insertion order (Python 3.7+).
        """
        seen: dict[str, str] = {}
        for msg in messages:
            if msg.speaker not in seen:
                seen[msg.speaker] = msg.speaker
        return seen

    def _compute_time_range(self, messages: list[ChatMessage]) -> str:
        """Compute the time range from chat messages.

        Args:
            messages: List of ChatMessage objects.

        Returns:
            A string like "10:30-10:35" or empty string if no times found.
        """
        times = [msg.time for msg in messages if msg.time is not None]
        if not times:
            return ""

        # Extract just the HH:MM part for range computation
        def extract_hhmm(t: str) -> str:
            """Extract the last HH:MM pattern from a time string."""
            match = re.search(r"(\d{1,2}:\d{2})", t)
            return match.group(1) if match else t

        hhmm_times = [extract_hhmm(t) for t in times]
        if len(hhmm_times) == 1:
            return hhmm_times[0]
        return f"{hhmm_times[0]}-{hhmm_times[-1]}"
